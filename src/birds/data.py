"""Load BirdNET predictions and ornithologist validations, and link them."""

import re

import numpy as np
import pandas as pd

from common.paths import BIRD_DATA

# Validation clips are BirdNET segments named
# <confidence>_<n>_<source file stem>.wav
VALIDATION_NAME = re.compile(
    r"^(?P<conf>\d+\.\d+)_(?P<n>\d+)_(?P<stem>.+)\.wav$", re.IGNORECASE
)


def load_predictions(path=None) -> pd.DataFrame:
    """Read the BirdNET predictions and add recording and clip times.

    The recording start time is parsed from the file name, which ends in
    YYYYMMDD_HHMMSS. The clip start adds the offset of the detection.
    """
    df = pd.read_csv(path or BIRD_DATA / "birdnet_predictions.csv")
    df["file_stem"] = (
        df["begin_path"]
        .str.rsplit("/", n=1)
        .str[-1]
        .str.replace(r"\.wav$", "", case=False, regex=True)
    )
    df["recorder"] = df["folder"]
    stamp = df["file_stem"].str.extract(r"_(\d{8}_\d{6})$")[0]
    df["recording_start"] = pd.to_datetime(stamp, format="%Y%m%d_%H%M%S")
    df["clip_start"] = df["recording_start"] + pd.to_timedelta(
        df["begin_time_s"], unit="s"
    )
    return df


def parse_validation_filename(name: str) -> dict:
    """Split a validation file name into confidence, index and recording.

    Names that do not follow the expected pattern give missing values.
    """
    m = VALIDATION_NAME.match(name)
    if not m:
        return {"name_conf": np.nan, "name_n": np.nan, "file_stem": None}
    return {
        "name_conf": float(m["conf"]),
        "name_n": int(m["n"]),
        "file_stem": m["stem"],
    }


def load_validations(path=None) -> pd.DataFrame:
    """Read the validation results and add the parsed file name fields."""
    df = pd.read_csv(path or BIRD_DATA / "validation_results.csv")
    parsed = pd.DataFrame(
        [parse_validation_filename(f) for f in df["filename"]],
        index=df.index,
    )
    df = pd.concat([df, parsed], axis=1)
    df["recorder"] = df["file_stem"].str.split("_").str[0]
    return df


def link_validations(pred: pd.DataFrame, val: pd.DataFrame) -> pd.DataFrame:
    """Link each validated clip to a prediction row.

    The file name only carries the recording, the species and the
    confidence rounded to 3 decimals. A link is made only when exactly one
    prediction row of that species in that recording has the same rounded
    confidence. Other cases are reported and not guessed.
    """
    p = pred[["file_stem", "common_name", "selection", "confidence"]].copy()
    p["conf3"] = p["confidence"].round(3)
    v = val.reset_index(names="val_row")[
        ["val_row", "file_stem", "commonName", "confidence", "outcome"]
    ]
    v = v.rename(
        columns={"commonName": "common_name", "confidence": "val_confidence"}
    )
    v["conf3"] = v["val_confidence"].round(3)

    # Check whether the recording and species appear in the predictions.
    recordings = p[["file_stem", "common_name"]].drop_duplicates()
    file_hits = v.merge(
        recordings,
        how="left",
        on=["file_stem", "common_name"],
        indicator=True,
    )
    in_file = file_hits.set_index("val_row")["_merge"].eq("both")

    # Count prediction rows that match on recording, species and score.
    m = v.merge(p, on=["file_stem", "common_name", "conf3"], how="left")
    n_cand = m.groupby("val_row")["selection"].count()

    out = v.set_index("val_row")
    out["recording_in_predictions"] = in_file
    out["n_candidates"] = n_cand
    out["link_status"] = np.select(
        [
            ~out["recording_in_predictions"],
            out["n_candidates"] == 0,
            out["n_candidates"] == 1,
        ],
        ["recording_not_in_predictions", "no_matching_confidence", "unique"],
        default="ambiguous",
    )

    # Keep the selection id only for clips with a single match.
    is_unique = out.index[out["link_status"] == "unique"]
    unique = m[m["val_row"].isin(is_unique)]
    out = out.join(unique.set_index("val_row")[["selection"]])
    out = out.reset_index()

    # The same 3 s segment can be exported and reviewed twice, with a
    # different <n> in the name. The second review is marked as duplicate.
    linked = out["link_status"] == "unique"
    dup = out[linked].duplicated(
        ["file_stem", "common_name", "selection"], keep="first"
    )
    out["is_duplicate_review"] = False
    out.loc[dup[dup].index, "is_duplicate_review"] = True
    return out


def fitting_set(val: pd.DataFrame, links: pd.DataFrame) -> pd.DataFrame:
    """Return the validations used to fit the curves.

    Repeat reviews of the same segment are removed so each segment counts
    once.
    """
    dup_rows = links.loc[links["is_duplicate_review"], "val_row"]
    return val.drop(index=dup_rows)
