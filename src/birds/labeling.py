"""Turn BirdNET predictions into observations."""

import numpy as np
import pandas as pd

STATUS_HUMAN_TRUE = "validated_correct"
STATUS_HUMAN_FALSE = "validated_incorrect"
STATUS_ABOVE = "above_threshold"
STATUS_BELOW = "below_threshold"
STATUS_NO_THRESHOLD = "no_threshold_for_species"


def label_predictions(
    pred: pd.DataFrame,
    thresholds: pd.DataFrame,
    fits: dict,
    links: pd.DataFrame,
    clip: float = 1e-4,
) -> pd.DataFrame:
    """Add the observation column and the columns that explain it.

    A human validation always decides the row. Otherwise the species
    threshold decides. Species without a threshold give no observation.
    """
    out = pred.copy()
    thr = thresholds.set_index("common_name")
    out["threshold_used"] = out["common_name"].map(thr["threshold"])
    out["threshold_status"] = (
        out["common_name"]
        .map(thr["threshold_status"])
        .fillna("species_not_validated")
    )

    # Fitted probability that each prediction is correct.
    out["p_correct"] = np.nan
    for species, fit in fits.items():
        mask = out["common_name"] == species
        if np.isfinite(fit.b1):
            out.loc[mask, "p_correct"] = fit.predict(
                out.loc[mask, "confidence"], clip
            )

    # Human label per segment. Two reviews of the same segment that
    # disagree give no label.
    key = ["file_stem", "common_name", "selection"]
    linked = links[links["link_status"] == "unique"]
    human = linked.groupby(key)["outcome"].agg(["min", "max"]).reset_index()
    human["validated_outcome"] = human["min"].where(
        human["min"] == human["max"]
    )
    out = out.merge(human[key + ["validated_outcome"]], on=key, how="left")

    # The first matching condition sets the status of each row.
    has_thr = out["threshold_used"].notna()
    above = has_thr & (out["confidence"] >= out["threshold_used"])
    out["observation_status"] = np.select(
        [
            out["validated_outcome"] == 1,
            out["validated_outcome"] == 0,
            above,
            has_thr,
        ],
        [STATUS_HUMAN_TRUE, STATUS_HUMAN_FALSE, STATUS_ABOVE, STATUS_BELOW],
        default=STATUS_NO_THRESHOLD,
    )
    is_obs = out["observation_status"].isin([STATUS_HUMAN_TRUE, STATUS_ABOVE])
    out["observation"] = out["common_name"].where(is_obs)
    out["decision_source"] = np.select(
        [out["validated_outcome"].notna(), has_thr],
        ["human_validation", "probabilistic_threshold"],
        default="none",
    )
    return out
