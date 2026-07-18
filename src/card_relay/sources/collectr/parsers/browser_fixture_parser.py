import hashlib
import json
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

from card_relay.domain.enums import ExtractionCompleteness, Finish, IngestionMethod
from card_relay.domain.models import (
    CanonicalCardIdentity,
    CanonicalCollection,
    CanonicalCollectionEntry,
)
from card_relay.exceptions import SourceValidationError
from card_relay.sources.collectr.parsers.csv_parser import (
    parse_boolean,
    parse_edition,
    parse_finish,
    parse_grading,
)


class BrowserCaptureStrategy(StrEnum):
    STRUCTURED_RESPONSE = "structured_response"
    EMBEDDED_DATA = "embedded_data"
    DOM = "dom"


class BrowserCaptureRecord(BaseModel):
    game: str = "pokemon"
    card_name: str = Field(min_length=1)
    set_name: str | None = None
    set_code: str | None = None
    collector_number: str = Field(min_length=1)
    quantity: int | None = Field(default=None, ge=0)
    condition: str | None = None
    language: str = "unknown"
    finish: str = ""
    edition: str = ""
    grade: str = ""
    grading_company: str = ""
    certification_number: str | None = None
    rarity: str | None = None
    promo: bool | str = False
    signed: bool | str = False
    altered: bool | str = False
    watchlist: bool | str = False
    source_record_id: str | None = None

    @model_validator(mode="after")
    def set_name_or_code_required(self) -> "BrowserCaptureRecord":
        if not self.set_name and not self.set_code:
            raise ValueError("set_name or set_code is required")
        return self


class BrowserCaptureBatch(BaseModel):
    batch_number: int = Field(ge=1)
    records: list[BrowserCaptureRecord]
    final_batch: bool = False


class BrowserCaptureEnvelope(BaseModel):
    contract_version: Literal["collectr-browser-v1"]
    strategy: BrowserCaptureStrategy
    batches: list[BrowserCaptureBatch] = Field(min_length=1)
    visible_total_quantity: int | None = Field(default=None, ge=0)
    visible_unique_record_count: int | None = Field(default=None, ge=0)
    expected_batch_count: int | None = Field(default=None, ge=1)
    invalid_record_count: int = Field(default=0, ge=0)
    skipped_non_card_count: int = Field(default=0, ge=0)
    source_schema_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def batch_numbers_are_unique_and_ordered(self) -> "BrowserCaptureEnvelope":
        numbers = [batch.batch_number for batch in self.batches]
        if numbers != list(range(1, len(numbers) + 1)):
            raise ValueError("capture batches must be consecutively numbered from 1")
        if any(batch.final_batch for batch in self.batches[:-1]):
            raise ValueError("only the last capture batch may be final")
        return self


class BrowserExtractionDiagnostics(BaseModel):
    """Completeness evidence retained without private collection payloads."""

    completeness: ExtractionCompleteness = ExtractionCompleteness.UNKNOWN
    observed_record_count: int = Field(default=0, ge=0)
    observed_total_quantity: int = Field(default=0, ge=0)
    visible_total_quantity: int | None = Field(default=None, ge=0)
    visible_unique_record_count: int | None = Field(default=None, ge=0)
    observed_page_count: int = Field(default=0, ge=0)
    expected_page_count: int | None = Field(default=None, ge=1)
    pagination_complete: bool = False
    schema_recognized: bool = False
    reliability_criteria_met: bool = False
    strategy: BrowserCaptureStrategy | None = None
    duplicate_record_count: int = Field(default=0, ge=0)
    skipped_watchlist_count: int = Field(default=0, ge=0)
    invalid_record_count: int = Field(default=0, ge=0)
    skipped_non_card_count: int = Field(default=0, ge=0)
    warnings: list[str] = Field(default_factory=list)

    @property
    def completeness_checks_passed(self) -> bool:
        return (
            self.schema_recognized
            and self.pagination_complete
            and self.visible_total_quantity is not None
            and self.observed_total_quantity == self.visible_total_quantity
            and (
                self.visible_unique_record_count is None
                or self.observed_record_count == self.visible_unique_record_count
            )
            and self.expected_page_count is not None
            and self.observed_page_count == self.expected_page_count
        )

    @property
    def trusted_for_destructive_planning(self) -> bool:
        return (
            self.completeness is ExtractionCompleteness.COMPLETE
            and self.completeness_checks_passed
            and self.reliability_criteria_met
        )

    @model_validator(mode="after")
    def complete_claim_requires_evidence(self) -> "BrowserExtractionDiagnostics":
        if (
            self.completeness is ExtractionCompleteness.COMPLETE
            and not self.completeness_checks_passed
        ):
            raise ValueError("complete browser extraction requires all completeness checks")
        return self


class BrowserFixtureParseResult(BaseModel):
    collection: CanonicalCollection
    diagnostics: BrowserExtractionDiagnostics

    @model_validator(mode="after")
    def completeness_matches_collection(self) -> "BrowserFixtureParseResult":
        if self.collection.completeness is not self.diagnostics.completeness:
            raise ValueError("collection and browser diagnostics completeness must match")
        return self


class CollectrBrowserParser:
    """Parse the versioned, sanitized boundary produced by browser capture strategies."""

    parser_name = "collectr_browser"
    parser_version = "2.0"

    def parse(self, payload: object) -> BrowserFixtureParseResult:
        try:
            capture = BrowserCaptureEnvelope.model_validate(payload)
        except ValidationError as error:
            raise SourceValidationError(
                "browser capture does not match the collectr-browser-v1 contract"
            ) from error

        aggregated: dict[str, CanonicalCollectionEntry] = {}
        seen_source_ids: dict[str, CanonicalCollectionEntry] = {}
        duplicate_count = 0
        lossy_record_count = 0
        skipped_watchlist_count = 0
        warnings = list(capture.warnings)

        for batch in capture.batches:
            for record in batch.records:
                if not record.quantity and _as_boolean(record.watchlist):
                    skipped_watchlist_count += 1
                    continue
                if not record.quantity:
                    raise SourceValidationError(
                        "browser capture contains a held record without a positive quantity"
                    )
                entry = _canonical_entry(record, capture.strategy)
                if record.source_record_id and record.source_record_id in seen_source_ids:
                    if seen_source_ids[record.source_record_id] != entry:
                        raise SourceValidationError(
                            "browser capture reused a source record id with conflicting data"
                        )
                    duplicate_count += 1
                    continue
                if record.source_record_id:
                    seen_source_ids[record.source_record_id] = entry
                if entry.fingerprint in aggregated:
                    previous = aggregated[entry.fingerprint]
                    conditions_conflict = (
                        previous.condition is not None
                        and entry.condition is not None
                        and previous.condition != entry.condition
                    )
                    if conditions_conflict:
                        lossy_record_count += 1
                        warnings.append(
                            "combined a duplicate browser identity with multiple conditions; "
                            "condition recorded as mixed and source is incomplete"
                        )
                    aggregated[entry.fingerprint] = previous.model_copy(
                        update={
                            "quantity": previous.quantity + entry.quantity,
                            "condition": (
                                "mixed"
                                if previous.condition == "mixed" or conditions_conflict
                                else previous.condition or entry.condition
                            ),
                        }
                    )
                    duplicate_count += 1
                else:
                    aggregated[entry.fingerprint] = entry

        observed_record_count = len(aggregated)
        observed_total_quantity = sum(entry.quantity for entry in aggregated.values())
        pagination_complete = bool(capture.batches[-1].final_batch)
        checks_passed = (
            pagination_complete
            and capture.invalid_record_count + lossy_record_count == 0
            and capture.visible_total_quantity is not None
            and capture.visible_total_quantity == observed_total_quantity
            and (
                capture.visible_unique_record_count is None
                or capture.visible_unique_record_count == observed_record_count
            )
            and capture.expected_batch_count is not None
            and capture.expected_batch_count == len(capture.batches)
        )
        completeness = (
            ExtractionCompleteness.COMPLETE if checks_passed else ExtractionCompleteness.INCOMPLETE
        )
        if skipped_watchlist_count:
            warnings.append(
                f"skipped {skipped_watchlist_count} watchlist-only record(s) without quantity"
            )
        effective_invalid_count = capture.invalid_record_count + lossy_record_count
        if effective_invalid_count:
            warnings.append(
                f"encountered {effective_invalid_count} invalid or lossy browser record(s); "
                "source is incomplete"
            )
        if capture.skipped_non_card_count:
            warnings.append(
                f"skipped {capture.skipped_non_card_count} non-card portfolio product(s)"
            )
        if not checks_passed:
            warnings.append(
                "browser observation is partial or lacks completeness evidence; omitted cards "
                "remain unknown"
            )
        collection = CanonicalCollection(
            entries=list(aggregated.values()),
            completeness=completeness,
            warnings=warnings,
        )
        diagnostics = BrowserExtractionDiagnostics(
            completeness=completeness,
            observed_record_count=observed_record_count,
            observed_total_quantity=observed_total_quantity,
            visible_total_quantity=capture.visible_total_quantity,
            visible_unique_record_count=capture.visible_unique_record_count,
            observed_page_count=len(capture.batches),
            expected_page_count=capture.expected_batch_count,
            pagination_complete=pagination_complete,
            schema_recognized=True,
            reliability_criteria_met=False,
            strategy=capture.strategy,
            duplicate_record_count=duplicate_count,
            skipped_watchlist_count=skipped_watchlist_count,
            invalid_record_count=effective_invalid_count,
            skipped_non_card_count=capture.skipped_non_card_count,
            warnings=warnings,
        )
        return BrowserFixtureParseResult(collection=collection, diagnostics=diagnostics)

    def schema_fingerprint(self, payload: object) -> str:
        capture = BrowserCaptureEnvelope.model_validate(payload)
        field_names = sorted(
            {
                field
                for batch in capture.batches
                for record in batch.records
                for field in record.model_fields_set
            }
        )
        structure = {
            "contract_version": capture.contract_version,
            "strategy": capture.strategy,
            "record_fields": field_names,
            "source_schema_fields": sorted(capture.source_schema_fields),
        }
        return hashlib.sha256(
            json.dumps(structure, sort_keys=True, default=str).encode()
        ).hexdigest()


def _as_boolean(value: bool | str) -> bool:
    return value if isinstance(value, bool) else parse_boolean(value)


# Backward-compatible import name for Milestone 1 fixture tests and callers.
CollectrBrowserFixtureParser = CollectrBrowserParser


def _canonical_entry(
    record: BrowserCaptureRecord, strategy: BrowserCaptureStrategy
) -> CanonicalCollectionEntry:
    finish = parse_finish(record.finish)
    if finish is Finish.APPLICATION_SPECIFIC:
        raise SourceValidationError("browser capture contains an unsupported finish")
    try:
        grading_status, grading_company, grade = parse_grading(record.grade, record.grading_company)
        identity = CanonicalCardIdentity(
            game=record.game,
            card_name=record.card_name,
            set_name=record.set_name,
            set_code=record.set_code,
            collector_number=record.collector_number,
            language=record.language,
            finish=finish,
            edition=parse_edition(record.edition or record.finish),
            grading_status=grading_status,
            grading_company=grading_company,
            grade=grade,
            certification_number=record.certification_number,
            promo=_as_boolean(record.promo),
            signed=_as_boolean(record.signed),
            altered=_as_boolean(record.altered),
        )
        return CanonicalCollectionEntry(
            identity=identity,
            quantity=record.quantity or 0,
            condition=record.condition,
            rarity=record.rarity,
            source_record_id=record.source_record_id,
            ingestion_method=IngestionMethod.BROWSER,
            raw_provenance={"capture_strategy": strategy.value},
        )
    except (ValueError, ValidationError) as error:
        raise SourceValidationError("browser capture contains an invalid card record") from error
