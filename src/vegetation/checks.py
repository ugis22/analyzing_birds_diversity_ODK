"""QA/QC checks for herbaceous vegetation data.

Each check is a function registered under the id used in
config/veg_qaqc_checks.yaml. A check receives the joined tables and the
parameters, and returns the rows that fail. It never changes data.
run_checks adds the level, severity and description from the config and
returns one long table of flags, the only input for reports and dashboards.
"""

import re

import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process

from common.config import load_config
from common.geo import haversine_m

FLAG_COLUMNS = [
    "check_id",
    "check_name",
    "level",
    "severity",
    "entity_key",
    "plot_name",
    "survey_key",
    "quadrat_number",
    "value",
    "message",
    "description",
]
ENTITY_COLUMNS = [
    "entity_key",
    "plot_name",
    "survey_key",
    "quadrat_number",
    "value",
    "message",
]

CANONICAL = re.compile(r"^[A-Z][a-z]+(-[a-z]+)? [a-z]+(-[a-z]+)?$")

REGISTRY = {}


def check(check_id):
    """Register the decorated function under check_id."""

    def deco(fn):
        REGISTRY[check_id] = fn
        return fn

    return deco


def _flags(df: pd.DataFrame, entity_col: str, value=None, message=None):
    """Turn the failing rows into flag rows.

    value and message can be a constant or a function of the failing
    rows. The plot, survey and quadrat columns are copied when present.
    """
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=ENTITY_COLUMNS)

    def resolve(spec):
        v = spec(df) if callable(spec) else spec
        if isinstance(v, (pd.Series, np.ndarray, list)):
            return np.asarray(v, dtype=object)
        return v

    out = pd.DataFrame({"entity_key": df[entity_col].astype(str).to_numpy()})
    for c in ["plot_name", "survey_key", "quadrat_number"]:
        out[c] = df[c].to_numpy() if c in df else None
    out["value"] = resolve(value)
    out["message"] = resolve(message)
    return out


def _accepted(surveys: pd.DataFrame) -> pd.DataFrame:
    """Return the surveys that were not rejected in review."""
    return surveys[surveys["review_state"] != "rejected"]


def _quadrats(m: dict) -> pd.DataFrame:
    """Return the quadrats with the plot name and review state added."""
    cols = ["survey_key", "plot_name", "review_state"]
    return m["quadrats"].merge(m["surveys"][cols], on="survey_key", how="left")


def _records(m: dict) -> pd.DataFrame:
    """Return the species records with quadrat number and plot name."""
    q = m["quadrats"][["quadrat_key", "quadrat_number"]]
    s = m["surveys"][["survey_key", "plot_name"]]
    return (
        m["species_records"]
        .merge(q, on="quadrat_key", how="left")
        .merge(s, on="survey_key", how="left")
    )


def _has_species(q: pd.DataFrame) -> pd.Series:
    """Return True for quadrats with at least one species record."""
    return (q["n_listed_species"] + q["n_additional_rows"]) > 0


def _r1(x: pd.Series) -> pd.Series:
    """Round to one decimal and convert to text."""
    return x.round(1).astype(str)


def _r0(x: pd.Series) -> pd.Series:
    """Round to a whole number and convert to text."""
    return x.round(0).astype(int).astype(str)


# Project and design checks.


@check("D01")
def stratum_not_sampled(m, p):
    """Flag design strata where no plot was registered."""
    st = (
        m["plots"]
        .groupby("stratum_label")
        .agg(n=("plot_name", "size"), reg=("registered", "sum"))
        .reset_index()
    )
    bad = st[st["reg"] == 0]
    return _flags(
        bad,
        "stratum_label",
        lambda d: d["n"].astype(str) + " plots, 0 registered",
        lambda d: (
            "Stratum '" + d["stratum_label"] + "' has no registered plot"
        ),
    )


@check("D02")
def primary_not_registered(m, p):
    """Flag primary plots that were never registered."""
    pl = m["plots"]
    bad = pl[(pl["design_status"] == "primary") & ~pl["registered"]]
    return _flags(
        bad,
        "plot_name",
        lambda d: d["stratum_label"],
        "Primary plot not registered",
    )


# Plot registration checks.


@check("P01")
def plot_not_viable(m, p):
    """List plots registered as not viable, with the reason given."""
    bad = m["plots"][m["plots"]["is_viable"] == "no"]
    return _flags(
        bad,
        "plot_name",
        lambda d: d["not_viable_reason"],
        "Plot registered as not viable",
    )


@check("P02")
def not_viable_without_reason(m, p):
    """Flag plots marked not viable without a reason."""
    pl = m["plots"]
    no_reason = pl["not_viable_reason"].fillna("").str.strip().eq("")
    bad = pl[(pl["is_viable"] == "no") & no_reason]
    return _flags(bad, "plot_name", None, "Not viable without a reason")


@check("P03")
def multiple_registrations(m, p):
    """Flag plots with more than one registration or vegplot entity."""
    pl = m["plots"]
    bad = pl[(pl["n_registrations"] > 1) | (pl["n_vegplot_entities"] > 1)]
    return _flags(
        bad,
        "plot_name",
        lambda d: (
            d["n_registrations"].astype(str)
            + " registrations, "
            + d["n_vegplot_entities"].astype(str)
            + " vegplot entities"
        ),
        "Plot registered more than once",
    )


@check("P04")
def midpoint_far(m, p):
    """Flag plots whose midpoint moved too far from the centroid."""
    pl = m["plots"]
    limit = p["max_midpoint_shift_m"]
    bad = pl[pl["mid_to_centroid_m"] > limit]
    return _flags(
        bad,
        "plot_name",
        lambda d: d["mid_to_centroid_m"].round(1),
        lambda d: (
            "Midpoint "
            + _r1(d["mid_to_centroid_m"])
            + f" m from centroid (max {limit} m)"
        ),
    )


@check("P05")
def transect_length(m, p):
    """Flag transects whose total or half lengths are far from 50 m."""
    pl = m["plots"]
    tol = p["length_tolerance_m"]
    full = (pl["len_a_b_m"] - p["transect_length_m"]).abs() > tol
    half_a = (pl["len_a_mid_m"] - p["half_length_m"]).abs() > tol
    half_b = (pl["len_mid_b_m"] - p["half_length_m"]).abs() > tol
    bad = pl[full | half_a | half_b]
    return _flags(
        bad,
        "plot_name",
        lambda d: d["len_a_b_m"].round(1),
        lambda d: (
            "A to B "
            + _r1(d["len_a_b_m"])
            + " m (A to mid "
            + _r1(d["len_a_mid_m"])
            + ", mid to B "
            + _r1(d["len_mid_b_m"])
            + "); expected 50 (25 + 25)"
        ),
    )


@check("P06")
def transect_not_ns(m, p):
    """Flag transects that are not laid out north to south."""
    pl = m["plots"]
    bad = pl[pl["deviation_from_ns_deg"] > p["bearing_tolerance_deg"]]
    return _flags(
        bad,
        "plot_name",
        lambda d: d["bearing_a_b_deg"].round(0),
        lambda d: (
            "Bearing A to B "
            + _r0(d["bearing_a_b_deg"])
            + " deg, "
            + _r0(d["deviation_from_ns_deg"])
            + " deg off the north/south axis"
        ),
    )


@check("P07")
def transect_not_straight(m, p):
    """Flag transects whose midpoint is not on the line from A to B."""
    pl = m["plots"]
    bad = pl[pl["mid_offset_from_ab_m"] > p["collinearity_tolerance_m"]]
    return _flags(
        bad,
        "plot_name",
        lambda d: d["mid_offset_from_ab_m"].round(1),
        lambda d: (
            "Midpoint "
            + _r1(d["mid_offset_from_ab_m"])
            + " m off the line from A to B"
        ),
    )


@check("P08")
def registration_accuracy(m, p):
    """Flag registrations with a GPS point less accurate than allowed."""
    pl = m["plots"]
    pl = pl.assign(
        worst=pl[["a_accuracy", "mid_accuracy", "b_accuracy"]].max(axis=1)
    )
    bad = pl[pl["worst"] > p["gps_accuracy_max_m"]]
    return _flags(
        bad,
        "plot_name",
        lambda d: d["worst"],
        "Registration GPS accuracy worse than 5 m",
    )


@check("P09")
def viable_without_survey(m, p):
    """Flag viable registered plots with no accepted survey."""
    pl = m["plots"]
    surveyed = set(_accepted(m["surveys"])["centroid_uuid"])
    bad = pl[(pl["is_viable"] == "yes") & ~pl["centroid_uuid"].isin(surveyed)]
    return _flags(
        bad, "plot_name", None, "Viable plot has no accepted herbaceous survey"
    )


# Survey checks.


@check("S01")
def rejected(m, p):
    """Flag submissions rejected in ODK Central review."""
    s = m["surveys"]
    return _flags(
        s[s["review_state"] == "rejected"],
        "survey_key",
        "rejected",
        "Submission rejected in review",
    )


@check("S02")
def duplicate_survey(m, p):
    """Flag plots surveyed more than once in the same replicate."""
    s = m["surveys"]
    dup = s[s.duplicated(["centroid_uuid", "replicate"], keep=False)].copy()
    dup["n_ok"] = dup.groupby("centroid_uuid")["review_state"].transform(
        lambda r: (r != "rejected").sum()
    )
    dup["n_dup"] = dup.groupby("centroid_uuid")["survey_key"].transform("size")
    return _flags(
        dup,
        "survey_key",
        lambda d: d["review_state"].replace("", "not reviewed"),
        lambda d: (
            "Plot surveyed "
            + d["n_dup"].astype(str)
            + " times in "
            + d["replicate"]
            + "; "
            + d["n_ok"].astype(str)
            + " not rejected"
        ),
    )


@check("S03")
def quadrat_count(m, p):
    """Flag surveys that do not have the expected number of quadrats."""
    expected = p["expected_quadrats"]
    n = m["quadrats"].groupby("survey_key").size()
    s = m["surveys"].assign(
        n=lambda d: d["survey_key"].map(n).fillna(0).astype(int)
    )
    bad = s[(s["n"] != expected) | (s["quadrat_repeat_count"] != expected)]
    return _flags(
        bad, "survey_key", lambda d: d["n"], f"Quadrat count is not {expected}"
    )


@check("S04")
def quadrat_numbers(m, p):
    """Flag surveys whose quadrat numbers are not 1 to 20, once each."""
    expected = p["expected_quadrats"]
    exp = list(range(1, expected + 1))
    nums = (
        m["quadrats"]
        .groupby("survey_key")["quadrat_number"]
        .apply(lambda x: sorted(x.tolist()) == exp)
    )
    s = m["surveys"]
    ok = s["survey_key"].map(nums).fillna(False).astype(bool)
    return _flags(
        s[~ok], "survey_key", None, f"Quadrat numbers are not 1 to {expected}"
    )


@check("S05")
def end_before_start(m, p):
    """Flag surveys whose end time is not after the start time."""
    s = m["surveys"]
    return _flags(
        s[s["end_time"] <= s["start_time"]],
        "survey_key",
        lambda d: d["duration_min"].round(1),
        "End time not after start time",
    )


@check("S06")
def duration(m, p):
    """Flag surveys that were unusually short or long."""
    s = m["surveys"]
    lo, hi = p["duration_min_minutes"], p["duration_max_minutes"]
    bad = s[(s["duration_min"] < lo) | (s["duration_min"] > hi)]
    return _flags(
        bad,
        "survey_key",
        lambda d: d["duration_min"].round(0),
        lambda d: (
            "Duration "
            + _r0(d["duration_min"])
            + f" min (expected {lo} to {hi})"
        ),
    )


@check("S07")
def submitted_before_end(m, p):
    """Flag submissions received before the end time on the device."""
    s = m["surveys"]
    bad = s[s["submission_date"] < s["end_time"]].copy()
    bad["gap"] = (
        bad["end_time"] - bad["submission_date"]
    ).dt.total_seconds() / 60
    return _flags(
        bad,
        "survey_key",
        lambda d: d["gap"].round(0),
        lambda d: (
            "Received " + _r0(d["gap"]) + " min before the form end time"
        ),
    )


@check("S08")
def plot_not_ok(m, p):
    """Flag surveys on plots that are not registered or not viable."""
    s = m["surveys"]
    registered = s["registered"].fillna(False).astype(bool)
    bad = s[~registered | (s["is_viable"] != "yes")]
    return _flags(
        bad,
        "survey_key",
        lambda d: d["is_viable"],
        "Survey on a plot that is not registered or not viable",
    )


@check("S09")
def before_registration(m, p):
    """Flag surveys that started before the plot was registered."""
    s = m["surveys"]
    return _flags(
        s[s["start_time"] < s["reg_end_time"]],
        "survey_key",
        None,
        "Survey before plot registration",
    )


@check("S10")
def backup_plot(m, p):
    """List surveys made on a backup plot."""
    s = m["surveys"]
    return _flags(
        s[s["design_status"] == "backup"],
        "survey_key",
        "backup",
        "Survey on a backup plot",
    )


@check("S11")
def recorder_not_in_team(m, p):
    """Flag surveys whose recorder is not among the team members."""
    s = m["surveys"]
    in_team = [r in t for r, t in zip(s["recorder_uuid"], s["team_uuids"])]
    bad = s[[not x for x in in_team]]
    return _flags(
        bad,
        "survey_key",
        lambda d: d["recorder"],
        "Recorder not among selected team members",
    )


@check("S12")
def inactive_choices(m, p):
    """Flag surveys that selected an inactive team member or transport."""
    team = m["raw"]["ent_project_team"].set_index("__id")["choice_status"]
    transport = m["raw"]["ent_transport"].set_index("__id")["choice_status"]
    s = m["surveys"].copy()

    def inactive(members, tr):
        out = [
            team.get(u, "missing")
            for u in members
            if team.get(u, "missing") != "active"
        ]
        status = transport.get(tr, "missing")
        if status != "active":
            out.append(f"transport {status}")
        return out

    s["inactive"] = [
        inactive(t, tr) for t, tr in zip(s["team_uuids"], s["transport_uuid"])
    ]
    bad = s[s["inactive"].map(len) > 0]
    return _flags(
        bad,
        "survey_key",
        lambda d: d["inactive"].map(str),
        "Inactive team member or transport selected",
    )


@check("S13")
def qws_mismatch(m, p):
    """Flag surveys whose form summary of quadrats with species is wrong.

    The number is computed again from the quadrat records and compared
    with the value the form saved.
    """
    q = m["quadrats"]
    has = q.assign(h=_has_species(q)).groupby("survey_key")["h"].sum()
    s = m["surveys"].assign(recomputed=lambda d: d["survey_key"].map(has))
    bad = s[s["recomputed"] != s["quadrats_with_species_reported"]]
    return _flags(
        bad,
        "survey_key",
        lambda d: (
            d["quadrats_with_species_reported"].astype(str)
            + " vs "
            + d["recomputed"].astype(str)
        ),
        "Form summary of quadrats with species differs from the records",
    )


@check("S14")
def few_qws(m, p):
    """Flag surveys where few quadrats have any species.

    Uses the number computed from the records, because the form summary
    is not reliable (see S13).
    """
    q = m["quadrats"]
    has = q.assign(h=_has_species(q)).groupby("survey_key")["h"].sum()
    s = m["surveys"].assign(
        share=lambda d: d["survey_key"].map(has) / p["expected_quadrats"]
    )
    bad = s[s["share"] < p["min_share_quadrats_with_species"]]
    return _flags(
        bad, "survey_key", lambda d: d["share"], "Few quadrats with species"
    )


@check("S15")
def background_point(m, p):
    """Flag surveys whose background point is missing or far away."""
    mids = m["plots"][["centroid_uuid", "mid_lat", "mid_lon"]]
    s = m["surveys"].merge(mids, on="centroid_uuid", how="left")
    s["dist"] = haversine_m(
        s["bg_lat"], s["bg_lon"], s["mid_lat"], s["mid_lon"]
    )
    bad = s[s["bg_lat"].isna() | (s["dist"] > p["background_point_max_m"])]
    return _flags(
        bad,
        "survey_key",
        lambda d: d["dist"].round(0),
        lambda d: np.where(
            d["bg_lat"].isna(),
            "Background geopoint missing",
            "Background geopoint "
            + d["dist"].round(0).astype(str)
            + " m from plot midpoint",
        ),
    )


@check("S16")
def attachments(m, p):
    """Flag surveys with fewer attachments on the server than expected."""
    s = m["surveys"]
    bad = s[s["attachments_present"] < s["attachments_expected"]]
    return _flags(
        bad,
        "survey_key",
        lambda d: (
            d["attachments_present"].astype(str)
            + " of "
            + d["attachments_expected"].astype(str)
        ),
        "Attachments missing on the server",
    )


@check("S17")
def not_confirmed(m, p):
    """Flag submissions that the recorder did not confirm."""
    s = m["surveys"]
    return _flags(
        s[s["confirm_submission"] != "yes"],
        "survey_key",
        None,
        "Submission not confirmed",
    )


@check("S18")
def off_transect(m, p):
    """Flag surveys whose quadrats lie away from the registered line.

    Uses the median side distance of all quadrats of the survey, so one
    bad GPS point does not raise the flag.
    """
    q = _quadrats(m)
    med = q.groupby("survey_key")["offset_m"].apply(lambda x: x.abs().median())
    s = m["surveys"].assign(med=lambda d: d["survey_key"].map(med))
    bad = s[s["med"] > p["survey_offset_median_m"]]
    return _flags(
        bad,
        "survey_key",
        lambda d: d["med"].round(1),
        lambda d: (
            "Median quadrat distance from registered line "
            + _r1(d["med"])
            + " m"
        ),
    )


@check("S19")
def walk_order(m, p):
    """Flag surveys walked out and back instead of side by side.

    The SOP places two quadrats at each 5 m mark, one on each side. If
    quadrats 1 to 10 move away from A and 11 to 20 come back, the team
    walked one side out and the other side back.
    """
    q = m["quadrats"]
    half = p["expected_quadrats"] // 2

    def pattern(g):
        g = g.sort_values("quadrat_number")
        first = g[g["quadrat_number"] <= half]
        second = g[g["quadrat_number"] > half]
        r1 = first["quadrat_number"].corr(first["along_m"], method="spearman")
        r2 = second["quadrat_number"].corr(
            second["along_m"], method="spearman"
        )
        return pd.Series({"r_out": r1, "r_back": r2})

    pat = q.groupby("survey_key")[["quadrat_number", "along_m"]].apply(pattern)
    s = m["surveys"].join(pat, on="survey_key")
    bad = s[(s["r_out"] > 0.7) & (s["r_back"] < -0.7)]
    return _flags(
        bad,
        "survey_key",
        lambda d: (
            d["r_out"].round(2).astype(str)
            + " / "
            + d["r_back"].round(2).astype(str)
        ),
        "Quadrats 1 to 10 move away from A and 11 to 20 come back; "
        "the SOP alternates sides at each 5 m mark",
    )


# Quadrat checks.


@check("Q01")
def q_photo(m, p):
    """Flag quadrats without a photo."""
    q = _quadrats(m)
    return _flags(
        q[q["quadrat_image"].isna()], "quadrat_key", None, "Photo missing"
    )


@check("Q02")
def q_gps(m, p):
    """Flag quadrats without a GPS point."""
    q = _quadrats(m)
    return _flags(
        q[q["lat"].isna() | q["lon"].isna()],
        "quadrat_key",
        None,
        "Geopoint missing",
    )


@check("Q03")
def q_accuracy(m, p):
    """Flag quadrat GPS points less accurate than allowed."""
    q = _quadrats(m)
    return _flags(
        q[q["accuracy"] > p["gps_accuracy_max_m"]],
        "quadrat_key",
        lambda d: d["accuracy"],
        "GPS accuracy worse than 5 m",
    )


@check("Q04")
def q_outside_belt(m, p):
    """Flag quadrats too far to the side of the transect line."""
    q = _quadrats(m)
    lim = p["belt_half_width_m"] + p["position_tolerance_m"]
    return _flags(
        q[q["offset_m"].abs() > lim],
        "quadrat_key",
        lambda d: d["offset_m"].round(1),
        lambda d: (
            "Quadrat "
            + _r1(d["offset_m"].abs())
            + f" m from the transect line (limit {lim} m)"
        ),
    )


@check("Q05")
def q_beyond_ends(m, p):
    """Flag quadrats that fall before endpoint A or after endpoint B."""
    q = _quadrats(m)
    tol = p["position_tolerance_m"]
    before_a = q["along_m"] < -tol
    after_b = q["along_m"] > q["len_a_b_m"] + tol
    return _flags(
        q[before_a | after_b],
        "quadrat_key",
        lambda d: d["along_m"].round(1),
        lambda d: (
            "Lies at "
            + _r1(d["along_m"])
            + " m along a "
            + _r0(d["len_a_b_m"])
            + " m transect"
        ),
    )


@check("Q06")
def q_jump(m, p):
    """Flag single quadrats far from both neighbours.

    This finds one wrong GPS point without flagging a whole survey.
    """
    q = _quadrats(m)
    near = q[["dist_prev_m", "dist_next_m"]]
    far = (near.fillna(np.inf) > p["position_jump_m"]).all(axis=1)
    bad = q[far & near.notna().any(axis=1)]
    return _flags(
        bad,
        "quadrat_key",
        lambda d: d[["dist_prev_m", "dist_next_m"]].min(axis=1).round(1),
        "Quadrat is far from both neighbouring quadrats",
    )


@check("Q07")
def q_dup_coords(m, p):
    """Flag quadrats with the same coordinates as another in the survey."""
    q = _quadrats(m)
    dup = q.duplicated(["survey_key", "lat", "lon"], keep=False)
    return _flags(
        q[dup & q["lat"].notna()],
        "quadrat_key",
        None,
        "Identical coordinates to another quadrat of the survey",
    )


@check("Q08")
def q_yes_no_species(m, p):
    """Flag quadrats marked with herbs present but no species."""
    q = _quadrats(m)
    bad = q[(q["herbs_present"] == "yes") & ~_has_species(q)]
    return _flags(
        bad, "quadrat_key", None, "herbs_present is yes but no species"
    )


@check("Q09")
def q_no_but_species(m, p):
    """Flag quadrats marked with no herbs but with species."""
    q = _quadrats(m)
    bad = q[(q["herbs_present"] == "no") & _has_species(q)]
    return _flags(
        bad, "quadrat_key", None, "herbs_present is no but species recorded"
    )


@check("Q10")
def q_additional_no_rows(m, p):
    """Flag quadrats that say additional species but have none."""
    q = _quadrats(m)
    flagged = q["additional_species_present"] == "yes"
    bad = q[flagged & (q["n_additional_rows"] == 0)]
    return _flags(
        bad, "quadrat_key", None, "Additional species flagged but none entered"
    )


@check("Q11")
def q_count_mismatch(m, p):
    """Flag quadrats whose species count differs from the selection."""
    q = _quadrats(m)
    differs = q["count_herb_species"] != q["n_listed_species"]
    bad = q[q["count_herb_species"].notna() & differs]
    return _flags(
        bad,
        "quadrat_key",
        lambda d: (
            d["count_herb_species"].astype(str)
            + " vs "
            + d["n_listed_species"].astype(str)
        ),
        "count_herb_species differs from selected species",
    )


@check("Q12")
def q_comment(m, p):
    """List quadrats with a field comment, for the reviewer to read."""
    q = _quadrats(m)
    return _flags(
        q[q["quadrat_comment"].notna()],
        "quadrat_key",
        lambda d: d["quadrat_comment"],
        "Field comment",
    )


# Species record checks.


def _species_names(m: dict):
    """Return the species list and a map from lower case name to name."""
    sp = m["raw"]["ent_species"]
    return sp, {n.lower(): n for n in sp["label"]}


def _free_text_names(m: dict) -> pd.DataFrame:
    """Return the records whose name was typed by the field team."""
    r = _records(m)
    typed = r["entry_mode"].isin(["new_missing", "reuse_missing"])
    ft = r[(r["source"] == "additional_species") & typed]
    return ft[ft["taxon_name"].notna()]


@check("R01")
def r_uuid_unknown(m, p):
    """Flag selected species ids that are not in the species list."""
    r = _records(m)
    bad = r[(r["source"] == "species_list") & r["taxon_name"].isna()]
    return _flags(
        bad,
        "record_key",
        lambda d: d["species_uuid"],
        "Species id not in species list",
    )


@check("R02")
def r_not_herb(m, p):
    """Flag selected species that are not herbaceous."""
    r = _records(m)
    group = r["species_group"]
    bad = r[
        (r["source"] == "species_list")
        & group.notna()
        & (group != "herbaceous")
    ]
    return _flags(
        bad,
        "record_key",
        lambda d: d["taxon_name"] + " (" + d["species_group"] + ")",
        "Not herbaceous",
    )


@check("R03")
def r_empty(m, p):
    """Flag additional species rows with no species."""
    r = _records(m)
    bad = r[(r["source"] == "additional_species") & r["taxon_name"].isna()]
    return _flags(
        bad,
        "record_key",
        lambda d: d["entry_mode"],
        "Additional species row has no species",
    )


@check("R04")
def r_dup_in_quadrat(m, p):
    """Flag taxa recorded more than once in the same quadrat."""
    r = _records(m)
    dup = r.duplicated(["quadrat_key", "taxon_key"], keep=False)
    bad = r[r["taxon_key"].notna() & dup]
    return _flags(
        bad,
        "record_key",
        lambda d: d["taxon_name"],
        "Taxon recorded twice in the quadrat",
    )


@check("R05")
def r_not_canonical(m, p):
    """Flag typed names that are not written as 'Genus epithet'."""
    ft = _free_text_names(m)
    ok = ft["taxon_name"].map(lambda n: bool(CANONICAL.match(n)))
    return _flags(
        ft[~ok],
        "record_key",
        lambda d: "'" + d["taxon_name"] + "'",
        "Not a canonical 'Genus epithet' (check spaces, case, characters)",
    )


@check("R06")
def r_missing_in_list(m, p):
    """Flag typed names that already exist in the species list."""
    ft = _free_text_names(m)
    _, names = _species_names(m)
    bad = ft[ft["taxon_key"].isin(names)]
    return _flags(
        bad,
        "record_key",
        lambda d: d["taxon_name"].str.strip(),
        "Entered as missing, but the species is in the species list",
    )


@check("R07")
def r_misspelling(m, p):
    """Flag typed names that look like a misspelled listed name.

    A name is flagged when it is close to a listed name but not equal, or
    when its genus is not in the list but is close to a listed genus.
    """
    ft = _free_text_names(m)
    sp, names = _species_names(m)
    genera = {g.lower(): g for g in sp["genus"].dropna().unique()}
    score_min = p["fuzzy_name_score"]
    hits = {}
    for key in ft["taxon_key"].unique():
        if key in names or not isinstance(key, str):
            continue
        genus = key.split()[0] if key.split() else key
        best = process.extractOne(
            key, list(names.values()), scorer=fuzz.WRatio, processor=str.lower
        )
        if best and best[1] >= score_min:
            hits[key] = f"closest listed name '{best[0]}' ({best[1]:.0f})"
        elif genus not in genera:
            g = process.extractOne(
                genus,
                list(genera.values()),
                scorer=fuzz.ratio,
                processor=str.lower,
            )
            if g and g[1] >= score_min:
                hits[key] = (
                    "genus not in species list; closest listed genus "
                    f"'{g[0]}' ({g[1]:.0f})"
                )
    bad = ft[ft["taxon_key"].isin(hits)]
    return _flags(
        bad,
        "record_key",
        lambda d: d["taxon_name"].str.strip(),
        lambda d: "Possible misspelling: " + d["taxon_key"].map(hits),
    )


@check("R08")
def r_multi_placeholder(m, p):
    """Flag typed names created under more than one placeholder id."""
    r = _records(m)
    is_missing = r["extra_reason"].eq("missing_species")
    miss = r[is_missing & r["extra_label"].notna()].copy()
    miss["name_key"] = miss["extra_label"].str.strip().str.lower()
    n_ph = miss.groupby("name_key")["placeholder_id"].nunique()
    bad = miss[miss["name_key"].isin(n_ph[n_ph > 1].index)]
    ph = bad.groupby("name_key")["placeholder_id"].apply(
        lambda x: ", ".join(sorted(set(x)))
    )
    return _flags(
        bad,
        "record_key",
        lambda d: d["extra_label"].str.strip(),
        lambda d: "Same name under placeholders " + d["name_key"].map(ph),
    )


@check("R09")
def r_unknown_pending(m, p):
    """List unknown species that are still not identified."""
    r = _records(m)
    pending = r["resolved_name"].fillna("Unknown") == "Unknown"
    bad = r[r["is_unknown"] & pending]
    return _flags(
        bad,
        "record_key",
        lambda d: d["placeholder_id"],
        "Unknown morphospecies not yet identified",
    )


@check("R10")
def r_resolution_note(m, p):
    """Flag records whose later identification note says to check them."""
    r = _records(m)
    bad = r[r["resolution_note"].notna()]
    return _flags(
        bad,
        "record_key",
        lambda d: d["placeholder_id"],
        lambda d: "Identification note: " + d["resolution_note"],
    )


@check("R11")
def r_unknown_no_photo(m, p):
    """Flag new unknown species created without a close up photo."""
    r = _records(m)
    bad = r[(r["entry_mode"] == "new_unknown") & r["macro_image_1"].isna()]
    return _flags(
        bad,
        "record_key",
        lambda d: d["placeholder_id"],
        "New unknown without macro photo",
    )


# Runner.


def run_checks(
    m: dict, config_name: str = "veg_qaqc_checks.yaml"
) -> pd.DataFrame:
    """Run every check listed in the config and return all flags.

    Raises KeyError when the config lists a check that has no function.
    """
    cfg = load_config(config_name)
    params = cfg["params"]
    frames = []
    for meta in cfg["checks"]:
        fn = REGISTRY.get(meta["id"])
        if fn is None:
            raise KeyError(
                f"Check {meta['id']} is in the config but not implemented"
            )
        f = fn(m, params)
        if len(f):
            frames.append(
                f.assign(
                    check_id=meta["id"],
                    check_name=meta["name"],
                    level=meta["level"],
                    severity=meta["severity"],
                    description=meta["description"],
                )
            )
    if frames:
        flags = pd.concat(frames, ignore_index=True)
    else:
        flags = pd.DataFrame(columns=FLAG_COLUMNS)

    # Survey flags only carry the survey key, so add the plot name.
    plot_of = m["surveys"].set_index("survey_key")["plot_name"]
    is_survey = flags["level"] == "survey"
    flags["survey_key"] = np.where(
        is_survey, flags["entity_key"], flags["survey_key"]
    )
    flags["plot_name"] = flags["plot_name"].fillna(
        flags["survey_key"].map(plot_of)
    )
    return flags[FLAG_COLUMNS]


def check_catalogue(config_name: str = "veg_qaqc_checks.yaml") -> pd.DataFrame:
    """Return the list of checks from the config, one row per check."""
    return pd.DataFrame(load_config(config_name)["checks"])
