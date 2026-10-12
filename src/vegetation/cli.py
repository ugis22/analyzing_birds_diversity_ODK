"""Command line entry point that runs the vegetation QA/QC pipeline."""

import matplotlib

from common.paths import FIGURES, OUTPUTS
from vegetation import mapping, plots, summaries
from vegetation.checks import check_catalogue, run_checks
from vegetation.model import build_model

# Plots shown in the detail figure of the report. They were chosen by hand
# to show one good plot and three typical problems in this dataset.
DETAIL_PLOTS = {
    "SavMon_LW_Plot_16": "(consistent)",
    "SavMon_LW_Plot_05": "(survey off registered line)",
    "SavMon_LW_Plot_19": "(22 m registered transect)",
    "SavMon_LW_Plot_14": "(midpoint 34 m from centroid)",
}
SUMMARY_TABLES = [
    "survey_summary",
    "plot_summary",
    "design_coverage",
    "field_completeness",
    "taxon_frequency",
    "daily_effort",
    "catalogue",
]


def run() -> dict:
    """Build the joined tables, run all checks and compute the summaries."""
    m = build_model()
    flags = run_checks(m)
    return {
        "model": m,
        "flags": flags,
        "catalogue": check_catalogue(),
        "survey_summary": summaries.survey_summary(m, flags),
        "plot_summary": summaries.plot_summary(m, flags),
        "design_coverage": summaries.design_coverage(m),
        "field_completeness": summaries.field_completeness(m),
        "taxon_frequency": summaries.taxon_frequency(m),
        "daily_effort": summaries.daily_effort(m),
    }


def write_outputs(res: dict, figures: bool = True):
    """Write flags, summaries, clean tables and, if asked, the maps.

    Clean tables keep the values as recorded. List columns are written as
    text with the items separated by a space.
    """
    out = OUTPUTS / "vegetation"
    out.mkdir(parents=True, exist_ok=True)
    m = res["model"]
    res["flags"].to_csv(out / "qa_flags.csv", index=False)
    for k in SUMMARY_TABLES:
        res[k].to_csv(out / f"{k}.csv", index=False)

    m["plots"].to_csv(out / "clean_plots.csv", index=False)
    surveys = m["surveys"].assign(
        team_uuids=m["surveys"]["team_uuids"].str.join(" ")
    )
    surveys.to_csv(out / "clean_surveys.csv", index=False)
    quadrats = m["quadrats"].assign(
        species_uuids=m["quadrats"]["species_uuids"].str.join(" ")
    )
    quadrats.to_csv(out / "clean_quadrats.csv", index=False)
    m["species_records"].to_csv(out / "clean_species_records.csv", index=False)

    if figures:
        FIGURES.mkdir(parents=True, exist_ok=True)
        flags = res["flags"]
        mapping.overview_map(m, FIGURES / "veg_map_overview.png")
        mapping.detail_panels(
            m, flags, DETAIL_PLOTS, FIGURES / "veg_map_plot_details.png"
        )
        mapping.interactive_map(m, flags, FIGURES / "veg_map_interactive.html")
        plots.accumulation_figure(m, FIGURES / "veg_species_accumulation.png")
        plots.bearing_figure(m, path=FIGURES / "veg_transect_bearings.png")


def main():
    """Run the pipeline, write the outputs and print a short summary."""
    # Draw figures to files only, without opening a window.
    matplotlib.use("Agg")
    res = run()
    write_outputs(res)
    f = res["flags"]
    print(f.groupby(["severity", "level"]).size().to_string())
    print(res["survey_summary"]["status"].value_counts().to_string())


if __name__ == "__main__":
    main()
