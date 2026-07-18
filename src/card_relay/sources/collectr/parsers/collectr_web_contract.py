import re
from collections.abc import Mapping
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from card_relay.domain.enums import Finish
from card_relay.exceptions import SourceValidationError
from card_relay.sources.collectr.parsers.browser_fixture_parser import (
    BrowserCaptureBatch,
    BrowserCaptureEnvelope,
    BrowserCaptureRecord,
    BrowserCaptureStrategy,
    BrowserInvalidRecordCounts,
)
from card_relay.sources.collectr.parsers.csv_parser import parse_finish

_COLLECTR_UNGRADED_GRADE_IDS = {"52"}
type _InvalidRecordReason = Literal[
    "capture_error",
    "missing_identity",
    "unsupported_finish",
    "unresolved_condition",
    "unresolved_grading",
    "non_positive_quantity",
]


class CollectrProductRecord(BaseModel):
    """Fields read by Collectr's current portfolio-products web bundle."""

    model_config = ConfigDict(extra="allow")

    product_id: int | str
    user_owned_product_id: int | str | None = None
    product_name: str = Field(min_length=1)
    catalog_category_name: str = Field(min_length=1)
    catalog_group: str = Field(min_length=1)
    card_number: str | None = None
    product_sub_type: str | None = None
    card_condition: int | str | None = None
    quantity: int = Field(ge=0)
    grade_id: int | str | None = None
    rarity: str | None = None
    language: str | None = None
    is_card: bool
    watchlist: bool = False


class CollectrProductsPage(BaseModel):
    model_config = ConfigDict(extra="allow")

    data: list[object]


class CollectrProductKind(BaseModel):
    """The discriminator validated before any card-only fields are required."""

    model_config = ConfigDict(extra="allow")

    is_card: bool


class BrowserGradeDetails(BaseModel):
    company: str = Field(min_length=1)
    grade: Decimal


def build_capture_from_collectr_responses(
    payloads: list[object],
    *,
    visible_total_quantity: int | None,
    condition_names: dict[str, str] | None = None,
    grade_details: dict[str, BrowserGradeDetails] | None = None,
) -> BrowserCaptureEnvelope:
    """Convert ordered API pages into the sanitized browser contract.

    The verified client requests 30 records at a time and continues while the
    preceding page is non-empty. An observed empty terminal page is therefore
    the pagination-completeness signal.
    """

    conditions = condition_names or {}
    grades = grade_details or {}
    batches: list[BrowserCaptureBatch] = []
    invalid_count = 0
    invalid_reasons: dict[_InvalidRecordReason, int] = {}
    skipped_non_card_count = 0
    terminal_page_seen = False
    source_schema_fields: set[str] = set()

    for raw_payload in payloads:
        try:
            page = CollectrProductsPage.model_validate(raw_payload)
        except ValidationError as error:
            raise SourceValidationError(
                "Collectr products response does not match the verified web contract"
            ) from error
        if not page.data:
            terminal_page_seen = True
            break

        records: list[BrowserCaptureRecord] = []
        for raw_product in page.data:
            try:
                kind = CollectrProductKind.model_validate(raw_product)
            except ValidationError:
                invalid_count += 1
                invalid_reasons["capture_error"] = invalid_reasons.get("capture_error", 0) + 1
                continue
            if not kind.is_card:
                skipped_non_card_count += 1
                continue
            try:
                product = CollectrProductRecord.model_validate(raw_product)
            except ValidationError:
                invalid_count += 1
                invalid_reasons["capture_error"] = invalid_reasons.get("capture_error", 0) + 1
                continue
            source_schema_fields.update(
                field
                for field in product.model_fields_set
                if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,63}", field)
            )
            converted, invalid_reason = _convert_product(product, conditions, grades)
            if converted is None:
                invalid_count += 1
                if invalid_reason is not None:
                    invalid_reasons[invalid_reason] = invalid_reasons.get(invalid_reason, 0) + 1
                continue
            if invalid_reason is not None:
                invalid_count += 1
                invalid_reasons[invalid_reason] = invalid_reasons.get(invalid_reason, 0) + 1
            records.append(converted)
        batches.append(
            BrowserCaptureBatch(
                batch_number=len(batches) + 1,
                records=records,
                final_batch=False,
            )
        )

    if not batches:
        batches.append(BrowserCaptureBatch(batch_number=1, records=[], final_batch=False))
    if terminal_page_seen:
        batches[-1] = batches[-1].model_copy(update={"final_batch": True})

    return BrowserCaptureEnvelope(
        contract_version="collectr-browser-v1",
        strategy=BrowserCaptureStrategy.STRUCTURED_RESPONSE,
        batches=batches,
        visible_total_quantity=visible_total_quantity,
        expected_batch_count=len(batches) if terminal_page_seen else None,
        invalid_record_count=invalid_count,
        invalid_record_reasons=BrowserInvalidRecordCounts.model_validate(invalid_reasons),
        skipped_non_card_count=skipped_non_card_count,
        source_schema_fields=sorted(source_schema_fields),
    )


def build_capture_from_embedded_payload(
    payload: object,
    *,
    visible_total_quantity: int | None,
    condition_names: dict[str, str] | None = None,
    grade_details: dict[str, BrowserGradeDetails] | None = None,
) -> BrowserCaptureEnvelope:
    """Parse a products payload embedded in the page without claiming completeness."""

    capture = build_capture_from_collectr_responses(
        [payload],
        visible_total_quantity=visible_total_quantity,
        condition_names=condition_names,
        grade_details=grade_details,
    )
    return capture.model_copy(update={"strategy": BrowserCaptureStrategy.EMBEDDED_DATA})


def build_capture_from_dom_records(
    records: list[object],
    *,
    visible_total_quantity: int | None,
    end_of_scroll_observed: bool,
) -> BrowserCaptureEnvelope:
    """Validate DOM fallback records; missing identity fields are skipped, never guessed."""

    converted: list[BrowserCaptureRecord] = []
    invalid_count = 0
    for raw_record in records:
        if not isinstance(raw_record, Mapping) or not all(
            raw_record.get(field) for field in ("game", "card_name", "collector_number", "quantity")
        ):
            invalid_count += 1
            continue
        try:
            converted.append(BrowserCaptureRecord.model_validate(raw_record))
        except ValidationError:
            invalid_count += 1
    return BrowserCaptureEnvelope(
        contract_version="collectr-browser-v1",
        strategy=BrowserCaptureStrategy.DOM,
        batches=[
            BrowserCaptureBatch(
                batch_number=1,
                records=converted,
                final_batch=end_of_scroll_observed,
            )
        ],
        visible_total_quantity=visible_total_quantity,
        expected_batch_count=1 if end_of_scroll_observed else None,
        invalid_record_count=invalid_count,
        invalid_record_reasons=BrowserInvalidRecordCounts(missing_identity=invalid_count),
        warnings=["DOM fallback was used because the structured response contract was unavailable"],
    )


def _convert_product(
    product: CollectrProductRecord,
    conditions: dict[str, str],
    grades: dict[str, BrowserGradeDetails],
) -> tuple[BrowserCaptureRecord | None, _InvalidRecordReason | None]:
    if product.quantity <= 0 and not product.watchlist:
        return None, "non_positive_quantity"
    if not product.card_number:
        return None, "missing_identity"
    finish_name = product.product_sub_type or "Normal"
    if parse_finish(finish_name) is Finish.APPLICATION_SPECIFIC:
        return None, "unsupported_finish"
    condition = _condition_name(product.card_condition, conditions)
    condition_is_lossy = product.card_condition is not None and condition is None
    grade_identifier = str(product.grade_id) if product.grade_id is not None else None
    is_ungraded = grade_identifier is None or grade_identifier in _COLLECTR_UNGRADED_GRADE_IDS
    grade = None if is_ungraded else grades.get(str(product.grade_id))
    if not is_ungraded and grade is None:
        return None, "unresolved_grading"
    holding_id = product.user_owned_product_id or product.product_id
    source_record_id = (
        f"{holding_id}:{product.grade_id or ''}:"
        f"{product.product_sub_type or ''}:{product.card_condition or ''}"
    )
    return (
        BrowserCaptureRecord(
            game=product.catalog_category_name,
            card_name=product.product_name,
            set_name=product.catalog_group,
            collector_number=product.card_number,
            quantity=product.quantity,
            condition=condition,
            language=product.language or "unknown",
            finish=finish_name,
            grade=str(grade.grade) if grade is not None else "",
            grading_company=grade.company if grade is not None else "",
            rarity=product.rarity,
            watchlist=product.watchlist,
            source_record_id=str(source_record_id),
        ),
        "unresolved_condition" if condition_is_lossy else None,
    )


def _condition_name(value: int | str | None, conditions: dict[str, str]) -> str | None:
    if value is None:
        return None
    mapped = conditions.get(str(value))
    if mapped is not None:
        return mapped
    if isinstance(value, str) and value.casefold() in {
        "mint",
        "near mint",
        "lightly played",
        "moderately played",
        "heavily played",
        "damaged",
    }:
        return value
    return None
