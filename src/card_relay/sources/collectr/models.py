from pathlib import Path

from pydantic import BaseModel, Field

from card_relay.domain.enums import CollectrSourceMode

DEFAULT_COLUMN_ALIASES: dict[str, list[str]] = {
    "card_name": ["card", "card name", "name"],
    "set_name": ["set", "set name", "expansion"],
    "set_code": ["set code", "set id"],
    "collector_number": ["number", "card number", "collector number"],
    "quantity": ["quantity", "qty", "count"],
    "condition": ["condition", "card condition"],
    "language": ["language", "lang"],
    "finish": ["finish", "variant", "printing"],
    "edition": ["edition"],
    "grading_company": ["grading company", "grader"],
    "grade": ["grade"],
    "promo": ["promo", "promotional"],
}


class CollectrSourceConfig(BaseModel):
    mode: CollectrSourceMode = CollectrSourceMode.AUTO
    csv_path: Path | None = None
    column_aliases: dict[str, list[str]] = Field(
        default_factory=lambda: DEFAULT_COLUMN_ALIASES.copy()
    )
