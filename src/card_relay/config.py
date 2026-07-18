from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from card_relay.paths import config_path
from card_relay.sources.collectr.models import DEFAULT_COLUMN_ALIASES
from card_relay.sync.policy import SyncPolicy


class ApplicationConfig(BaseModel):
    data_directory: Path | None = None
    log_level: str = "INFO"


class CsvConfig(BaseModel):
    column_aliases: dict[str, list[str]] = Field(
        default_factory=lambda: DEFAULT_COLUMN_ALIASES.copy()
    )


class BrowserConfig(BaseModel):
    headless: bool = False
    profile_directory: Path | None = None
    navigation_timeout_seconds: int = Field(default=30, gt=0)
    request_delay_seconds: float = Field(default=1, ge=0)
    maximum_batches: int = Field(default=200, ge=1, le=500)
    require_complete_extraction: bool = True
    research_url: str = "https://app.getcollectr.com/portfolio"


class CollectrConfig(BaseModel):
    mode: str = "auto"
    csv: CsvConfig = Field(default_factory=CsvConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)


class MatchingConfig(BaseModel):
    minimum_probable_score: float = Field(default=0.92, ge=0, le=1)
    allow_fuzzy_matching: bool = True
    require_variant_match: bool = True
    require_language_match: bool = True


class Settings(BaseModel):
    application: ApplicationConfig = Field(default_factory=ApplicationConfig)
    collectr: CollectrConfig = Field(default_factory=CollectrConfig)
    sync: SyncPolicy = Field(default_factory=SyncPolicy)
    matching: MatchingConfig = Field(default_factory=MatchingConfig)


def load_settings(path: Path | None = None) -> Settings:
    selected = path or config_path()
    if not selected.exists():
        return Settings()
    data: Any = yaml.safe_load(selected.read_text(encoding="utf-8")) or {}
    return Settings.model_validate(data)
