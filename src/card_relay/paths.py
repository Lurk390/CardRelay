import os
from pathlib import Path


def data_directory() -> Path:
    if override := os.getenv("CARD_RELAY_DATA_DIRECTORY"):
        return Path(override)
    root = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return root / "card-relay"


def config_path() -> Path:
    return Path(
        os.getenv("CARD_RELAY_CONFIG", Path.home() / ".config" / "card-relay" / "config.yaml")
    )
