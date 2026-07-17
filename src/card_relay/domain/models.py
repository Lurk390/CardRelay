from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from card_relay.domain.enums import Edition, ExtractionCompleteness, Finish, IngestionMethod
from card_relay.domain.identifiers import (
    normalize_collector_number,
    normalize_text,
    stable_fingerprint,
)


class RawSourceRecord(BaseModel):
    row_number: int
    fields: dict[str, str]


class CanonicalCardIdentity(BaseModel):
    model_config = ConfigDict(frozen=True)
    game: str = "pokemon"
    card_name: str
    set_name: str | None = None
    set_code: str | None = None
    collector_number: str
    printed_set_total: int | None = None
    language: str = "unknown"
    finish: Finish = Finish.UNKNOWN
    edition: Edition = Edition.UNKNOWN
    grading_status: str = "ungraded"
    grading_company: str | None = None
    grade: Decimal | None = None
    promo: bool = False

    @field_validator("game", "card_name", "set_name", "set_code", "language", mode="before")
    @classmethod
    def normalize_strings(cls, value: object) -> object:
        return normalize_text(value) if isinstance(value, str) else value

    @field_validator("collector_number", mode="before")
    @classmethod
    def normalize_number(cls, value: object) -> object:
        return normalize_collector_number(str(value))

    @model_validator(mode="after")
    def require_set(self) -> "CanonicalCardIdentity":
        if not self.set_code and not self.set_name:
            raise ValueError("set_code or set_name is required")
        if self.grading_status == "graded" and not self.grading_company:
            raise ValueError("graded cards require grading_company")
        return self

    @property
    def fingerprint(self) -> str:
        return stable_fingerprint(
            {
                "game": self.game,
                "set": self.set_code or self.set_name,
                "collector_number": self.collector_number,
                "language": self.language,
                "finish": self.finish.value,
                "edition": self.edition.value,
                "grading_status": self.grading_status,
                "grading_company": self.grading_company,
                "grade": str(self.grade) if self.grade is not None else None,
                "promo": self.promo,
            }
        )


class NormalizedSourceRecord(BaseModel):
    identity: CanonicalCardIdentity
    quantity: int = Field(gt=0)
    condition: str | None = None
    rarity: str | None = None
    certification_number: str | None = None
    signed: bool = False
    altered: bool = False
    notes: str | None = None
    source_record_id: str | None = None
    destination_ids: dict[str, str] = Field(default_factory=dict)
    raw_provenance: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class CanonicalCollectionEntry(NormalizedSourceRecord):
    source_application: str = "collectr"
    ingestion_method: IngestionMethod

    @property
    def fingerprint(self) -> str:
        return self.identity.fingerprint


class CanonicalCollection(BaseModel):
    entries: list[CanonicalCollectionEntry]
    completeness: ExtractionCompleteness = ExtractionCompleteness.COMPLETE
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_entries(self) -> "CanonicalCollection":
        fingerprints = [entry.fingerprint for entry in self.entries]
        if len(fingerprints) != len(set(fingerprints)):
            raise ValueError("canonical collection contains duplicate identities")
        return self

    @property
    def total_quantity(self) -> int:
        return sum(entry.quantity for entry in self.entries)


class DestinationCatalogRecord(BaseModel):
    destination_id: str
    identity: CanonicalCardIdentity


class DestinationCollectionEntry(BaseModel):
    destination_id: str
    identity: CanonicalCardIdentity
    quantity: int = Field(ge=0)


class SourceSnapshot(BaseModel):
    snapshot_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source_application: str = "collectr"
    ingestion_method: IngestionMethod
    source_schema_fingerprint: str
    parser_name: str
    parser_version: str
    canonical_fingerprint_version: str = "v1"
    completeness: ExtractionCompleteness
    total_unique_entries: int
    total_quantity: int
    invalid_record_count: int = 0
    duplicate_record_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    collection_fingerprint: str
    previous_snapshot_id: str | None = None
    trusted_for_destructive_planning: bool = False


def collection_fingerprint(collection: CanonicalCollection) -> str:
    return stable_fingerprint(
        {
            entry.fingerprint: entry.quantity
            for entry in sorted(collection.entries, key=lambda x: x.fingerprint)
        }
    )
