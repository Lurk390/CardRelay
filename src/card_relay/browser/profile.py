from pathlib import Path

from card_relay.paths import data_directory


def browser_profile_directory() -> Path:
    return data_directory() / "browser" / "collectr-profile"


def clear_browser_profile() -> None:
    raise NotImplementedError(
        "session clearing will be implemented with the user-controlled browser workflow"
    )
