"""Survey, plot and sampling effort summaries for the data quality report.

Analysis set: all surveys that were not rejected in review. Diversity is
computed on the data as recorded, so each placeholder morphospecies counts
as one taxon. Known naming problems are reported next to the numbers, not
applied to them.
"""

import numpy as np
import pandas as pd
from scipy.special import gammaln

SEVERITIES = ["error", "warning", "info"]
FLAG_COUNTS = ["n_error", "n_warning", "n_info"]


# Flag counts.


def _count_flags(flags: pd.DataFrame, by: str) -> pd.DataFrame:
    """Count flags of each severity for each value of column by."""
    f = flags[flags[by].notna()]
    out = f.pivot_table(
        index=by,
        columns="severity",
        values="check_id",
        aggfunc="size",
        fill_value=0,
    )
    return out.reindex(columns=SEVERITIES, fill_value=0).add_prefix("n_")


def status_from_counts(df: pd.DataFrame) -> np.ndarray:
    """Return Error if any error, Warning if any warning, otherwise OK."""
    return np.select(
        [df["n_error"] > 0, df["n_warning"] > 0],
        ["Error", "Warning"],
        default="OK",
    )


def analysis_surveys(m: dict) -> pd.DataFrame:
    """Return the surveys used for the summaries: all not rejected."""
    return m["surveys"][m["surveys"]["review_state"] != "rejected"]


# Incidence statistics. Rows are sampling units, columns are taxa.


def incidence_matrix(records: pd.DataFrame, unit: str) -> pd.DataFrame:
    """Return a table of units by taxa, with 1 when the taxon is present."""
    r = records[records["taxon_key"].notna()]
    return pd.crosstab(r[unit], r["taxon_key"]).clip(upper=1)


def chao2(inc: pd.DataFrame, n_units: int | None = None) -> dict:
    """Estimate total richness (Chao2) and sample coverage.

    Uses the bias corrected Chao2 and the incidence coverage of Chao and
    Jost (2012). Q1 and Q2 are the taxa found in exactly one and two
    units. n_units counts units with no species too.
    """
    t = n_units if n_units is not None else len(inc)
    y = inc.sum(axis=0)
    s_obs = int((y > 0).sum())
    q1, q2 = int((y == 1).sum()), int((y == 2).sum())
    if t <= 1:
        return {
            "S_obs": s_obs,
            "chao2": np.nan,
            "coverage": np.nan,
            "Q1": q1,
            "Q2": q2,
            "T": t,
        }
    k = (t - 1) / t
    est = s_obs + k * q1 * (q1 - 1) / (2 * (q2 + 1))
    u = y.sum()
    if q2 > 0:
        cov = 1 - q1 / u * ((t - 1) * q1 / ((t - 1) * q1 + 2 * q2))
    elif q1 > 0:
        cov = 1 - q1 / u * ((t - 1) * (q1 - 1) / ((t - 1) * (q1 - 1) + 2))
    else:
        cov = 1.0
    return {
        "S_obs": s_obs,
        "chao2": est,
        "coverage": cov,
        "Q1": q1,
        "Q2": q2,
        "T": t,
    }


def rarefaction_curve(
    inc: pd.DataFrame, n_units: int | None = None
) -> pd.DataFrame:
    """Return the expected richness for 1 to T sampling units.

    This is sample based rarefaction (Colwell et al. 2012). For each taxon,
    the chance to miss it in t units is C(T minus y, t) / C(T, t), worked
    out on the log scale.
    """
    t_max = n_units if n_units is not None else len(inc)
    y = inc.sum(axis=0).to_numpy()
    rows = []
    for t in range(1, t_max + 1):
        with np.errstate(invalid="ignore"):
            log_p = (
                gammaln(t_max - y + 1)
                - gammaln(t_max - y - t + 1)
                - gammaln(t_max + 1)
                + gammaln(t_max - t + 1)
            )
        p_absent = np.where(t_max - y >= t, np.exp(log_p), 0.0)
        rows.append(
            {"units": t, "expected_richness": float(np.sum(1 - p_absent))}
        )
    return pd.DataFrame(rows)


def incidence_diversity(inc: pd.DataFrame) -> dict:
    """Return Shannon and Simpson diversity from quadrat frequencies.

    The data only record presence, so each taxon is weighted by the number
    of quadrats where it was found.
    """
    y = inc.sum(axis=0)
    y = y[y > 0]
    if y.empty:
        return {"shannon_H": np.nan, "hill_N1": np.nan, "simpson_1mD": np.nan}
    p = y / y.sum()
    h = float(-(p * np.log(p)).sum())
    return {
        "shannon_H": h,
        "hill_N1": float(np.exp(h)),
        "simpson_1mD": float(1 - (p**2).sum()),
    }


# Survey level.


def survey_summary(m: dict, flags: pd.DataFrame) -> pd.DataFrame:
    """Return one row for each survey with counts, richness and flags."""
    s, q, r = m["surveys"], m["quadrats"], m["species_records"]
    rv = r[r["taxon_key"].notna()]
    per_q = q.assign(has=(q["n_listed_species"] + q["n_additional_rows"]) > 0)
    agg = per_q.groupby("survey_key").agg(
        n_quadrats=("quadrat_key", "size"),
        quadrats_with_species=("has", "sum"),
        photos=("quadrat_image", "count"),
        gps_points=("lat", "count"),
        median_gps_accuracy_m=("accuracy", "median"),
        median_offset_from_line_m=("offset_m", lambda x: x.abs().median()),
    )

    def n_taxa(mask):
        return lambda x: x[mask.loc[x.index]].nunique()

    typed = rv["entry_mode"].isin(["new_missing", "reuse_missing"])
    rich = rv.groupby("survey_key").agg(
        richness=("taxon_key", "nunique"),
        listed_taxa=("taxon_key", n_taxa(rv["source"] == "species_list")),
        free_text_taxa=("taxon_key", n_taxa(typed)),
        unknown_morphospecies=("taxon_key", n_taxa(rv["is_unknown"])),
    )
    spq = (
        rv.groupby(["survey_key", "quadrat_key"])["taxon_key"]
        .nunique()
        .groupby("survey_key")
        .mean()
    )
    cols = [
        "survey_key",
        "plot_name",
        "design_status",
        "survey_date",
        "recorder",
        "device_id",
        "start_time",
        "duration_min",
        "review_state",
        "quadrats_with_species_reported",
    ]
    out = (
        s[cols]
        .join(agg, on="survey_key")
        .join(rich, on="survey_key")
        .assign(mean_species_per_quadrat=lambda d: d["survey_key"].map(spq))
        .join(_count_flags(flags, "survey_key"), on="survey_key")
    )
    out[FLAG_COUNTS] = out[FLAG_COUNTS].fillna(0).astype(int)
    out["status"] = status_from_counts(out)
    out["in_analysis_set"] = out["review_state"] != "rejected"
    out["unknown_share"] = out["unknown_morphospecies"] / out["richness"]
    return out.sort_values(["plot_name", "start_time"]).reset_index(drop=True)


# Plot level.


def plot_summary(m: dict, flags: pd.DataFrame) -> pd.DataFrame:
    """Return one row for each prescribed location.

    Diversity metrics come from the accepted survey of the plot. Plots
    without one have empty metrics.
    """
    p, r = m["plots"], m["species_records"]
    acc = analysis_surveys(m)
    n_all = m["surveys"].groupby("centroid_uuid").size()
    n_acc = acc.groupby("centroid_uuid").size()
    rows = []
    for sk, pn in zip(acc["survey_key"], acc["plot_name"]):
        rr = r[r["survey_key"] == sk]
        inc = incidence_matrix(rr, "quadrat_key")
        n_q = int((m["quadrats"]["survey_key"] == sk).sum())
        c2 = chao2(inc, n_q)
        div = incidence_diversity(inc)
        if len(inc):
            freq = inc.sum(axis=0).sort_values(ascending=False) / n_q
        else:
            freq = pd.Series(dtype=float)
        unknown = rr.loc[rr["is_unknown"], "taxon_key"].nunique()
        rows.append(
            {
                "plot_name": pn,
                "analysis_survey_key": sk,
                "richness": c2["S_obs"],
                "chao2_richness": c2["chao2"],
                "sample_coverage": c2["coverage"],
                "singletons_Q1": c2["Q1"],
                "doubletons_Q2": c2["Q2"],
                "mean_species_per_quadrat": rr.groupby("quadrat_key")[
                    "taxon_key"
                ]
                .nunique()
                .mean(),
                "unknown_share": unknown / max(c2["S_obs"], 1),
                "top_taxon": freq.index[0] if len(freq) else None,
                "top_taxon_frequency": freq.iloc[0] if len(freq) else np.nan,
                **div,
            }
        )
    metrics = pd.DataFrame(rows)
    cols = [
        "plot_name",
        "plot_number",
        "stratum_label",
        "design_status",
        "registered",
        "is_viable",
        "not_viable_reason",
        "ecosystem_type",
        "mid_to_centroid_m",
        "len_a_b_m",
        "bearing_a_b_deg",
        "deviation_from_ns_deg",
        "centroid_uuid",
    ]
    out = p[cols].copy()
    out["n_surveys"] = out["centroid_uuid"].map(n_all).fillna(0).astype(int)
    out["n_surveys_in_analysis"] = (
        out["centroid_uuid"].map(n_acc).fillna(0).astype(int)
    )
    out = out.merge(metrics, on="plot_name", how="left").join(
        _count_flags(flags, "plot_name"), on="plot_name"
    )
    out[FLAG_COUNTS] = out[FLAG_COUNTS].fillna(0).astype(int)
    out["status"] = np.where(
        ~out["registered"], "Not registered", status_from_counts(out)
    )
    return (
        out.drop(columns="centroid_uuid")
        .sort_values("plot_number")
        .reset_index(drop=True)
    )


# Sampling effort.


def design_coverage(m: dict) -> pd.DataFrame:
    """Count planned, registered, viable and surveyed plots by stratum."""
    p = m["plots"]
    surveyed = set(analysis_surveys(m)["centroid_uuid"])
    t = p.assign(
        viable=p["is_viable"].eq("yes"),
        surveyed=p["centroid_uuid"].isin(surveyed),
    )
    return (
        t.groupby(["stratum_label", "design_status"])
        .agg(
            planned=("plot_name", "size"),
            registered=("registered", "sum"),
            viable=("viable", "sum"),
            surveyed=("surveyed", "sum"),
        )
        .reset_index()
    )


def field_completeness(
    m: dict, gps_max: float = 5, expected_quadrats: int = 20
) -> pd.DataFrame:
    """Count the quadrat fields that were filled, against the expected."""
    cols = ["survey_key", "review_state"]
    q = m["quadrats"].merge(m["surveys"][cols], on="survey_key")
    q = q[q["review_state"] != "rejected"]
    expected = len(analysis_surveys(m)) * expected_quadrats
    items = {
        "quadrats recorded": len(q),
        "quadrat photos": int(q["quadrat_image"].notna().sum()),
        "quadrat GPS points": int(q["lat"].notna().sum()),
        f"GPS accuracy <= {gps_max} m": int((q["accuracy"] <= gps_max).sum()),
        "herbs_present answered": int(q["herbs_present"].notna().sum()),
    }
    return pd.DataFrame(
        {
            "item": list(items),
            "count": list(items.values()),
            "expected": expected,
        }
    ).assign(completeness=lambda d: d["count"] / d["expected"])


def project_accumulation(m: dict) -> tuple[pd.DataFrame, dict]:
    """Return rarefaction and Chao2 across plots, one plot = one unit."""
    acc = analysis_surveys(m)
    r = m["species_records"]
    r = r[r["survey_key"].isin(acc["survey_key"])]
    inc = incidence_matrix(r, "survey_key")
    return rarefaction_curve(inc), chao2(inc)


def plot_accumulation(m: dict) -> pd.DataFrame:
    """Return the quadrat rarefaction curve of every accepted survey."""
    acc = analysis_surveys(m)
    r = m["species_records"]
    frames = []
    for sk, pn in zip(acc["survey_key"], acc["plot_name"]):
        inc = incidence_matrix(r[r["survey_key"] == sk], "quadrat_key")
        n_q = int((m["quadrats"]["survey_key"] == sk).sum())
        frames.append(rarefaction_curve(inc, n_q).assign(plot_name=pn))
    return pd.concat(frames, ignore_index=True)


def daily_effort(m: dict) -> pd.DataFrame:
    """Count surveys and hours in plots for each day and recorder."""
    s = m["surveys"]
    return (
        s.groupby(["survey_date", "recorder"])
        .agg(
            surveys=("survey_key", "size"),
            rejected=("review_state", lambda x: (x == "rejected").sum()),
            hours=("duration_min", lambda x: x.sum() / 60),
        )
        .reset_index()
    )


def taxon_frequency(m: dict) -> pd.DataFrame:
    """Return how many plots and quadrats each taxon was found in."""
    acc = analysis_surveys(m)
    r = m["species_records"]
    r = r[r["survey_key"].isin(acc["survey_key"]) & r["taxon_key"].notna()]
    out = r.groupby("taxon_key").agg(
        taxon=("taxon_name", lambda x: x.dropna().str.strip().iloc[0]),
        source=("source", "first"),
        is_unknown=("is_unknown", "max"),
        plots=("survey_key", "nunique"),
        quadrats=("quadrat_key", "nunique"),
    )
    out["plot_frequency"] = out["plots"] / len(acc)
    return out.sort_values("quadrats", ascending=False).reset_index(drop=True)
