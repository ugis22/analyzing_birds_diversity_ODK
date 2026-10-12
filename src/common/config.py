"""Load YAML configuration files."""

from pathlib import Path

import yaml

from common.paths import CONFIG


def load_config(name: str) -> dict:
    """Read a YAML file and return its content as a dictionary.

    A relative name is looked up in the config folder. An absolute path is
    used as given.
    """
    path = Path(name)
    if not path.is_absolute():
        path = CONFIG / name
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)
