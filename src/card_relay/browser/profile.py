import shutil
from pathlib import Path

from card_relay.paths import data_directory


def browser_profile_directory(service: str = "collectr") -> Path:
    return data_directory() / "browser" / f"{service}-profile"


def clear_browser_profile(service: str = "collectr", profile_directory: Path | None = None) -> None:
    profile = profile_directory or browser_profile_directory(service)
    if profile.exists():
        shutil.rmtree(profile)


def browser_profile_present(
    service: str = "collectr", profile_directory: Path | None = None
) -> bool:
    profile = profile_directory or browser_profile_directory(service)
    return profile.exists() and any(profile.iterdir())
