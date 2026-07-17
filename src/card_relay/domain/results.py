from pydantic import BaseModel, Field

from card_relay.domain.enums import MatchStatus
from card_relay.domain.models import DestinationCatalogRecord


class SourceValidationResult(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    record_count: int = 0


class MatchResult(BaseModel):
    source_fingerprint: str
    status: MatchStatus
    candidate: DestinationCatalogRecord | None = None
    score: float | None = None
    reasons: list[str] = Field(default_factory=list)
    matched_fields: list[str] = Field(default_factory=list)
    mismatched_fields: list[str] = Field(default_factory=list)
    candidate_ids: list[str] = Field(default_factory=list)
