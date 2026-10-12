"""Read the ODK exports and entity lists exactly as delivered.

No value is changed here. Every later step works on these tables.
"""

import pandas as pd

from common.paths import VEG_ENTITIES, VEG_EXPORTS

EXPORTS = {
    "survey": "herbaceous_veg_survey.csv",
    "quadrat": "herbaceous_veg_survey-quadrat_repeat.csv",
    "additional": "herbaceous_veg_survey-additional_species_repeat.csv",
    "registration": "register_vegetation_plots.csv",
}
ENTITIES = [
    "areas",
    "centroids",
    "ecosystem_types",
    "project_team",
    "projects",
    "species",
    "species_extra",
    "species_extra_ids",
    "surveys",
    "transport",
    "vegplots",
]


def load_raw(
    exports_dir=VEG_EXPORTS, entities_dir=VEG_ENTITIES
) -> dict[str, pd.DataFrame]:
    """Return every raw table, keyed by a short name.

    Form exports use the keys in EXPORTS. Entity lists use the prefix
    ent_, for example ent_species.
    """
    raw = {k: pd.read_csv(exports_dir / f) for k, f in EXPORTS.items()}
    for name in ENTITIES:
        raw[f"ent_{name}"] = pd.read_csv(entities_dir / f"{name}.csv")
    return raw
