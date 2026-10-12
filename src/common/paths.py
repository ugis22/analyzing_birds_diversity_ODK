"""Repository paths shared by the notebooks, the command line and tests."""

from pathlib import Path

# This file lives in src/common, so the repository root is two
# folders above it.
ROOT = Path(__file__).resolve().parents[2]

# Raw input files, kept as provided.
DATA = ROOT / "data"
BIRD_DATA = DATA / "Data Birds"
VEG_DATA = DATA / "Data Vegetation"
VEG_EXPORTS = VEG_DATA / "ODK Data Exports"
VEG_ENTITIES = VEG_DATA / "Entity lists"

CONFIG = ROOT / "config"
OUTPUTS = ROOT / "outputs"
FIGURES = ROOT / "reports" / "figures"
