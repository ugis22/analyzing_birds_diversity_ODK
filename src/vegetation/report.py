"""Build the vegetation data quality report from its template.

The template is reports/templates/03_template.md. Each placeholder
{{NAME}} is replaced with a number or an HTML table computed by the
pipeline, so the numbers in the report always come from the code.
Run it as the module vegetation.report.
"""

import html

import numpy as np
import pandas as pd

from common.paths import ROOT
from vegetation import cli, summaries
from vegetation.model import PLACEHOLDER

TEMPLATE = ROOT / "reports" / "templates" / "03_template.md"
TARGET = ROOT / "reports" / "03_vegetation_data_quality_report.md"
STATUS_TEXT = {
    "OK": "OK",
    "Warning": "Warning",
    "Error": "<b>Error</b>",
    "Not registered": "Not registered",
}


def _short(name):
    """Remove the project prefix from a plot name."""
    if isinstance(name, str):
        return name.replace("SavMon_LW_", "").replace("_", " ")
    return name


def _taxon_label(key):
    """Write a lower case taxon key as a name; keep placeholders as is."""
    if not isinstance(key, str) or PLACEHOLDER.match(key):
        return key
    return key.capitalize()


def _cell(v, floatfmt: str) -> str:
    """Format one table cell as HTML text."""
    if v is None or v is pd.NA or (isinstance(v, float) and np.isnan(v)):
        return ""
    if isinstance(v, (bool, np.bool_)):
        return "yes" if v else "no"
    if isinstance(v, (float, np.floating)):
        return format(v, floatfmt)
    text = str(v)
    if text.startswith("<b>"):
        return text
    return html.escape(text, quote=False)


def _html(df: pd.DataFrame, floatfmt: str = ".1f") -> str:
    """Return a DataFrame as a plain HTML table, one row per line."""
    head = "".join(
        f"<th>{html.escape(str(c), quote=False)}</th>" for c in df.columns
    )
    lines = ["<table>", f"<tr>{head}</tr>"]
    for row in df.itertuples(index=False):
        cells = "".join(f"<td>{_cell(v, floatfmt)}</td>" for v in row)
        lines.append(f"<tr>{cells}</tr>")
    lines.append("</table>")
    return "\n".join(lines)


def _pct(x: float) -> str:
    """Format a share as a whole percentage."""
    return f"{x:.0%}"


def _survey_table(ss: pd.DataFrame) -> str:
    """Return the survey level table."""
    s = ss.assign(
        plot=ss["plot_name"].map(_short),
        date=ss["survey_date"].dt.strftime("%d %b"),
        review=ss["review_state"].replace("", "not reviewed"),
        status=ss["status"].map(STATUS_TEXT),
        qws=ss["quadrats_with_species"].astype(str)
        + " ("
        + ss["quadrats_with_species_reported"].astype(str)
        + ")",
    )
    cols = {
        "plot": "plot",
        "date": "date",
        "recorder": "recorder",
        "duration_min": "minutes",
        "review": "review",
        "n_quadrats": "quadrats",
        "qws": "quadrats with species (form)",
        "richness": "taxa",
        "unknown_morphospecies": "unknown taxa",
        "mean_species_per_quadrat": "taxa per quadrat",
        "median_gps_accuracy_m": "GPS accuracy (m)",
        "median_offset_from_line_m": "distance from line (m)",
        "n_error": "errors",
        "n_warning": "warnings",
        "n_info": "info",
        "status": "status",
    }
    return _html(s[list(cols)].rename(columns=cols), ".1f")


def _plot_table(ps: pd.DataFrame) -> str:
    """Return the plot level table for registered plots."""
    reg = ps[ps["registered"]].assign(
        plot=lambda d: d["plot_name"].map(_short),
        status=lambda d: d["status"].map(STATUS_TEXT),
        top_taxon=lambda d: d["top_taxon"].map(_taxon_label),
    )

    # Show counts and bearings as whole numbers.
    for c in ["richness", "bearing_a_b_deg"]:
        reg[c] = reg[c].round(0).astype("Int64")
    cols = {
        "plot": "plot",
        "design_status": "design",
        "is_viable": "viable",
        "n_surveys": "surveys",
        "mid_to_centroid_m": "midpoint to centroid (m)",
        "len_a_b_m": "A to B (m)",
        "bearing_a_b_deg": "bearing (deg)",
        "richness": "taxa",
        "chao2_richness": "Chao2",
        "sample_coverage": "coverage",
        "mean_species_per_quadrat": "taxa per quadrat",
        "hill_N1": "Hill N1",
        "unknown_share": "unknown share",
        "top_taxon": "most frequent taxon",
        "top_taxon_frequency": "its quadrat share",
        "n_error": "errors",
        "n_warning": "warnings",
        "status": "status",
    }
    return _html(reg[list(cols)].rename(columns=cols), ".2f")


def _check_table(catalogue: pd.DataFrame, flags: pd.DataFrame) -> str:
    """Return one row for each check, with its number of flags."""

    def plot_list(x):
        names = sorted({_short(v).replace("Plot ", "") for v in x.dropna()})
        text = ", ".join(names)
        return text if len(text) <= 60 else text[:57] + "..."

    g = flags.groupby("check_id").agg(
        n=("entity_key", "size"), plots=("plot_name", plot_list)
    )
    c = catalogue.set_index("id").join(g).reset_index()
    c["n"] = c["n"].fillna(0).astype(int)
    c["plots"] = c["plots"].fillna("")
    cols = {
        "id": "id",
        "level": "level",
        "severity": "severity",
        "description": "description",
        "n": "flags",
        "plots": "plots affected",
    }
    return _html(c[list(cols)].rename(columns=cols))


def _error_table(flags: pd.DataFrame) -> str:
    """Return every error flag with its plot and message."""
    e = flags[flags["severity"] == "error"].assign(
        plot=lambda d: d["plot_name"].map(_short)
    )
    e = e.sort_values(["check_id", "plot_name", "quadrat_number"])
    cols = {
        "check_id": "check",
        "level": "level",
        "plot": "plot",
        "quadrat_number": "quadrat",
        "message": "message",
    }
    return _html(e[list(cols)].rename(columns=cols), ".0f")


def tables(res: dict) -> dict:
    """Compute every placeholder value of the template."""
    m, flags = res["model"], res["flags"]
    ss, ps = res["survey_summary"], res["plot_summary"]
    p = m["plots"]
    t = {}

    # Tables.
    t["SURVEY_TABLE"] = _survey_table(ss)
    t["PLOT_TABLE"] = _plot_table(ps)
    t["CHECK_TABLE"] = _check_table(res["catalogue"], flags)
    t["ERROR_TABLE"] = _error_table(flags)
    lv = flags.pivot_table(
        index="level",
        columns="severity",
        values="check_id",
        aggfunc="size",
        fill_value=0,
    )
    levels = ["project", "plot", "survey", "quadrat", "record"]
    t["LEVEL_TABLE"] = _html(
        lv.reindex(levels).fillna(0).astype(int).reset_index()
    )
    t["COVERAGE_TABLE"] = _html(
        res["design_coverage"].rename(
            columns={"stratum_label": "stratum", "design_status": "design"}
        )
    )
    fc = res["field_completeness"].assign(
        completeness=lambda d: d["completeness"].map(_pct)
    )
    t["COMPLETENESS_TABLE"] = _html(fc)
    de = res["daily_effort"].assign(
        survey_date=lambda d: d["survey_date"].dt.strftime("%a %d %b")
    )
    t["EFFORT_TABLE"] = _html(
        de.rename(columns={"survey_date": "date", "hours": "hours in plots"})
    )
    tf = res["taxon_frequency"]
    top = tf.head(12).assign(
        plot_frequency=lambda d: d["plot_frequency"].map(_pct),
        on_species_list=lambda d: np.where(
            d["source"] == "species_list", "yes", "no"
        ),
    )
    t["TOP_TAXA_TABLE"] = _html(
        top[
            [
                "taxon",
                "on_species_list",
                "is_unknown",
                "plots",
                "quadrats",
                "plot_frequency",
            ]
        ].rename(
            columns={
                "on_species_list": "on species list",
                "is_unknown": "unknown",
                "plot_frequency": "share of plots",
            }
        )
    )

    # Design and effort numbers.
    acc_surveys = summaries.analysis_surveys(m)
    unsampled = p.groupby("stratum_label")["registered"].sum()
    unsampled = sorted(unsampled[unsampled == 0].index)
    t["N_PLANNED"] = str(len(p))
    t["N_REGISTERED"] = str(int(p["registered"].sum()))
    t["N_SURVEYED"] = str(acc_surveys["centroid_uuid"].nunique())
    t["N_SUBMISSIONS"] = str(len(m["surveys"]))
    t["N_REJECTED"] = str(
        int((m["surveys"]["review_state"] == "rejected").sum())
    )
    t["UNSAMPLED_STRATA"] = ", ".join(unsampled) if unsampled else "none"
    t["N_UNSAMPLED_LOCATIONS"] = str(
        int(p["stratum_label"].isin(unsampled).sum())
    )
    dates = m["surveys"]["survey_date"]
    t["DATE_FIRST"] = dates.min().strftime("%d %B %Y").lstrip("0")
    t["DATE_LAST"] = dates.max().strftime("%d %B %Y").lstrip("0")
    t["N_RECORDERS"] = str(m["surveys"]["recorder"].nunique())
    t["RECORDERS"] = " and ".join(sorted(m["surveys"]["recorder"].unique()))

    # Transect geometry numbers.
    reg = p[p["registered"]]
    n_flag = flags.groupby("check_id")["entity_key"].size()
    t["N_TRANSECTS"] = str(int(reg["bearing_a_b_deg"].notna().sum()))
    t["N_NOT_NS"] = str(int(n_flag.get("P06", 0)))
    t["BEARING_MIN"] = f"{reg['bearing_a_b_deg'].min():.0f}"
    t["BEARING_MAX"] = f"{reg['bearing_a_b_deg'].max():.0f}"
    t["N_LENGTH_OFF"] = str(int(n_flag.get("P05", 0)))
    t["LEN_MIN"] = f"{reg['len_a_b_m'].min():.0f}"
    t["LEN_MAX"] = f"{reg['len_a_b_m'].max():.0f}"
    t["N_NOT_STRAIGHT"] = str(int(n_flag.get("P07", 0)))
    t["N_OFF_LINE"] = str(int(n_flag.get("S18", 0)))
    t["N_OUTSIDE_BELT"] = str(int(n_flag.get("Q04", 0)))
    t["N_WALK_ORDER"] = str(int(n_flag.get("S19", 0)))
    t["N_QWS_WRONG"] = str(int(n_flag.get("S13", 0)))

    # Survey status.
    status = ss[ss["in_analysis_set"]]["status"].value_counts()
    t["N_SURVEYS_OK"] = str(status.get("OK", 0))
    t["N_SURVEYS_WARN"] = str(status.get("Warning", 0))
    t["N_SURVEYS_ERR"] = str(status.get("Error", 0))
    t["N_FLAGS"] = f"{len(flags):,}"
    t["N_CHECKS"] = str(len(res["catalogue"]))
    for sev in ["error", "warning", "info"]:
        t[f"N_{sev.upper()}"] = f"{(flags['severity'] == sev).sum():,}"

    # Richness and sampling effort numbers.
    pc = summaries.plot_accumulation(m).pivot(
        index="plot_name", columns="units", values="expected_richness"
    )
    _, ch = summaries.project_accumulation(m)
    ok = ps[ps["richness"].notna()]
    t["N_TAXA"] = str(ch["S_obs"])
    t["CHAO2"] = f"{ch['chao2']:.0f}"
    t["COVERAGE"] = f"{ch['coverage']:.2f}"
    t["Q1"] = str(ch["Q1"])
    t["SHARE_AT_10"] = _pct((pc[10] / pc[20]).mean())
    t["GAIN_LAST_5"] = f"{(pc[20] - pc[15]).mean():.1f}"
    t["PLOT_COV_MEDIAN"] = f"{ok['sample_coverage'].median():.2f}"
    t["PLOT_COV_MIN"] = f"{ok['sample_coverage'].min():.2f}"
    t["N_COV_BELOW_090"] = str(int((ok["sample_coverage"] < 0.9).sum()))
    t["N_CHAO_GAP"] = str(
        int((ok["chao2_richness"] > 1.5 * ok["richness"]).sum())
    )
    t["RICH_MEAN"] = f"{ok['richness'].mean():.1f}"
    t["RICH_MIN"] = f"{ok['richness'].min():.0f}"
    t["RICH_MAX"] = f"{ok['richness'].max():.0f}"
    t["N_UNKNOWN_TAXA"] = str(int(tf["is_unknown"].sum()))
    t["UNKNOWN_SHARE"] = _pct(tf["is_unknown"].mean())
    r = m["species_records"]
    r = r[r["survey_key"].isin(acc_surveys["survey_key"])]
    t["SHARE_FREE_RECORDS"] = _pct(
        (r["source"] == "additional_species").mean()
    )
    return t


def render(res: dict | None = None):
    """Fill the template and write the report. Returns the report path.

    Raises ValueError if a placeholder is left without a value.
    """
    res = res or cli.run()
    text = TEMPLATE.read_text(encoding="utf-8")
    for k, v in tables(res).items():
        text = text.replace("{{" + k + "}}", v)
    left = [w.split("}}")[0] for w in text.split("{{")[1:]]
    if left:
        raise ValueError(f"Unfilled placeholders: {left}")
    TARGET.write_text(text, encoding="utf-8")
    return TARGET


if __name__ == "__main__":
    print(render())
