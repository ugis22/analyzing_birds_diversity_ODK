"""Command line entry point that runs the full bird pipeline."""

import argparse

from birds import data, labeling, thresholds
from common.config import load_config
from common.paths import OUTPUTS

DERIVED_COLUMNS = ["file_stem", "recorder", "recording_start", "clip_start"]
LABEL_COLUMNS = [
    "observation",
    "observation_status",
    "decision_source",
    "threshold_used",
    "threshold_status",
    "p_correct",
    "validated_outcome",
]


def run(config_name: str = "bird_thresholds.yaml", bootstrap: bool = True):
    """Load the data, fit the thresholds and label every prediction.

    Returns a dictionary with the config, the inputs, the links, the
    threshold table, the fits and the labelled predictions.
    """
    cfg = load_config(config_name)
    pred = data.load_predictions()
    val = data.load_validations()
    links = data.link_validations(pred, val)
    fit_val = data.fitting_set(val, links)
    table, fits = thresholds.fit_all(fit_val, cfg, bootstrap=bootstrap)
    table.insert(0, "birdnet_version", cfg["birdnet_version"])
    table.insert(1, "target_precision", cfg["target_precision"])
    labelled = labeling.label_predictions(
        pred, table, fits, links, cfg["logit_clip"]
    )
    return {
        "cfg": cfg,
        "pred": pred,
        "val": val,
        "fit_val": fit_val,
        "links": links,
        "table": table,
        "fits": fits,
        "labelled": labelled,
    }


def write_outputs(res: dict):
    """Write the threshold table, the links and the labelled predictions.

    The labelled file keeps the original prediction columns and adds the
    label columns.
    """
    out = OUTPUTS / "birds"
    out.mkdir(parents=True, exist_ok=True)
    res["table"].to_csv(out / "species_thresholds.csv", index=False)
    res["links"].to_csv(out / "validation_links.csv", index=False)
    cols = list(res["pred"].columns.drop(DERIVED_COLUMNS)) + LABEL_COLUMNS
    res["labelled"][cols].to_csv(
        out / "birdnet_predictions_with_observations.csv", index=False
    )


def main():
    """Parse the command line, run the pipeline and print a summary."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default="bird_thresholds.yaml")
    ap.add_argument("--no-bootstrap", action="store_true")
    args = ap.parse_args()
    res = run(args.config, bootstrap=not args.no_bootstrap)
    write_outputs(res)
    summary_cols = ["common_name", "threshold", "threshold_status"]
    print(res["table"][summary_cols].to_string(index=False))
    counts = res["labelled"].groupby(["common_name", "observation_status"])
    print(counts.size().to_string())


if __name__ == "__main__":
    main()
