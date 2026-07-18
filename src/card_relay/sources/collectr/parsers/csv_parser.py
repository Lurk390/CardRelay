import csv
import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from functools import partial
from pathlib import Path

from pydantic import ValidationError

from card_relay.domain.enums import Edition, ExtractionCompleteness, Finish, IngestionMethod
from card_relay.domain.models import (
    CanonicalCardIdentity,
    CanonicalCollection,
    CanonicalCollectionEntry,
)
from card_relay.exceptions import SourceValidationError

PARSER_VERSION = "1.1"


@dataclass(frozen=True)
class ParseDiagnostics:
    schema_fingerprint: str
    duplicate_count: int
    invalid_record_count: int
    warnings: list[str]


def normalized_label(value: str) -> str:
    return " ".join(value.strip().casefold().replace("_", " ").split())


def _map_headers(headers: Sequence[str], aliases: dict[str, list[str]]) -> dict[str, str]:
    actual = {normalized_label(header): header for header in headers}
    result: dict[str, str] = {}
    for canonical, candidates in aliases.items():
        for candidate in [canonical, *candidates]:
            if normalized_label(candidate) in actual:
                result[canonical] = actual[normalized_label(candidate)]
                break
    missing = [name for name in ("card_name", "collector_number", "quantity") if name not in result]
    if missing or ("set_name" not in result and "set_code" not in result):
        raise SourceValidationError(
            f"missing required CSV identity columns: {', '.join(missing or ['set_name/set_code'])}"
        )
    return result


def parse_finish(value: str) -> Finish:
    normalized = normalized_label(value)
    known = {
        "normal": Finish.NORMAL,
        "foil": Finish.FOIL,
        "holo": Finish.HOLO,
        "holofoil": Finish.HOLO,
        "reverse holo": Finish.REVERSE_HOLO,
        "reverse holofoil": Finish.REVERSE_HOLO,
        "master ball reverse holo": Finish.MASTER_BALL_REVERSE_HOLO,
        "cracked ice": Finish.CRACKED_ICE,
        "cosmos holo": Finish.COSMOS_HOLO,
        "stamped": Finish.STAMPED,
        "promo": Finish.PROMO,
        "first edition": Finish.NORMAL,
        "1st edition": Finish.NORMAL,
        "unlimited": Finish.NORMAL,
        "limited": Finish.NORMAL,
    }
    return known.get(normalized, Finish.UNKNOWN if not normalized else Finish.APPLICATION_SPECIFIC)


def _row_value(row: dict[str, str | None], mapped: dict[str, str], key: str) -> str:
    return (row.get(mapped[key], "") or "").strip() if key in mapped else ""


def parse_boolean(value: str) -> bool:
    return normalized_label(value) in {"yes", "true", "1"}


def parse_edition(value: str) -> Edition:
    normalized = normalized_label(value)
    if "first" in normalized or normalized == "1st edition":
        return Edition.FIRST
    if normalized == "limited":
        return Edition.LIMITED
    if normalized == "unlimited":
        return Edition.UNLIMITED
    return Edition.UNKNOWN


def parse_grading(value: str, grader: str) -> tuple[str, str | None, Decimal | None]:
    normalized = normalized_label(value)
    if not value or normalized in {"raw", "ungraded"}:
        if grader:
            raise ValueError("grading company requires a numeric grade")
        return "ungraded", None, None
    if grader:
        try:
            return "graded", grader, Decimal(value)
        except ArithmeticError as error:
            raise ValueError("grade must be numeric when grading company is separate") from error
    combined = re.fullmatch(
        r"(?P<company>[A-Za-z][A-Za-z0-9 .&+-]*?)\s+"
        r"(?P<grade>\d+(?:\.\d+)?)(?:\s+.*)?",
        value,
    )
    if combined is None:
        raise ValueError("grade must identify a grading company and numeric grade")
    return "graded", combined.group("company"), Decimal(combined.group("grade"))


def _validation_summary(error: ValidationError) -> str:
    parts: list[str] = []
    for detail in error.errors(include_url=False, include_input=False):
        location = ".".join(str(item) for item in detail["loc"])
        parts.append(f"{location}: {detail['msg']}")
    return "; ".join(parts)


def parse_csv(
    path: Path, aliases: dict[str, list[str]]
) -> tuple[CanonicalCollection, ParseDiagnostics]:
    try:
        handle = path.open(encoding="utf-8-sig", newline="")
    except (OSError, UnicodeError) as error:
        raise SourceValidationError(f"unable to read CSV as UTF-8: {error}") from error
    with handle:
        reader = csv.DictReader(handle)
        try:
            rows = list(reader)
        except UnicodeError as error:
            raise SourceValidationError(f"unable to read CSV as UTF-8: {error}") from error
        headers = reader.fieldnames
        if not headers:
            raise SourceValidationError("CSV has no header row")
        mapped = _map_headers(headers, aliases)
        schema = hashlib.sha256(
            "|".join(sorted(normalized_label(h) for h in headers)).encode()
        ).hexdigest()
        aggregated: dict[str, CanonicalCollectionEntry] = {}
        duplicates = 0
        invalid_records = 0
        lossy_records = 0
        skipped_watchlist_rows = 0
        warnings: list[str] = []
        errors: list[str] = []
        for row_number, row in enumerate(rows, start=2):
            if not any((value or "").strip() for value in row.values()):
                continue

            value = partial(_row_value, row, mapped)

            if not value("quantity") and parse_boolean(value("watchlist")):
                skipped_watchlist_rows += 1
                continue
            if not value("collector_number"):
                invalid_records += 1
                warnings.append(
                    f"row {row_number} skipped: collector number is missing; source is incomplete"
                )
                continue
            finish = parse_finish(value("finish"))
            if finish is Finish.APPLICATION_SPECIFIC:
                invalid_records += 1
                warnings.append(
                    f"row {row_number} skipped: finish is unsupported; source is incomplete"
                )
                continue

            try:
                quantity = int(value("quantity"))
                if quantity <= 0:
                    raise ValueError("quantity must be greater than zero")
                grader = value("grading_company") or None
                grading_status, grading_company, grade = parse_grading(value("grade"), grader or "")
                identity = CanonicalCardIdentity(
                    game=value("game") or "pokemon",
                    card_name=value("card_name"),
                    set_name=value("set_name") or None,
                    set_code=value("set_code") or None,
                    collector_number=value("collector_number"),
                    printed_set_total=(
                        int(value("printed_set_total")) if value("printed_set_total") else None
                    ),
                    language=value("language") or "unknown",
                    finish=finish,
                    edition=parse_edition(value("edition") or value("finish")),
                    grading_status=grading_status,
                    grading_company=grading_company,
                    grade=grade,
                    certification_number=value("certification_number") or None,
                    promo=parse_boolean(value("promo"))
                    or normalized_label(value("finish")) in {"promo", "promotional"},
                    signed=parse_boolean(value("signed")),
                    altered=parse_boolean(value("altered")),
                )
                entry = CanonicalCollectionEntry(
                    identity=identity,
                    quantity=quantity,
                    condition=value("condition") or None,
                    rarity=value("rarity") or None,
                    notes=value("notes") or None,
                    source_record_id=value("source_record_id") or None,
                    ingestion_method=IngestionMethod.CSV,
                    raw_provenance={key: mapped[key] for key in mapped},
                )
            except ValidationError as error:
                errors.append(f"row {row_number}: {_validation_summary(error)}")
                continue
            except ValueError as error:
                errors.append(f"row {row_number}: {error}")
                continue
            if entry.fingerprint in aggregated:
                previous = aggregated[entry.fingerprint]
                conditions_conflict = (
                    previous.condition is not None
                    and entry.condition is not None
                    and previous.condition != entry.condition
                )
                if conditions_conflict:
                    lossy_records += 1
                    warnings.append(
                        f"row {row_number}: combined duplicate identity with multiple "
                        "conditions; condition recorded as mixed and source is incomplete"
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
                duplicates += 1
            else:
                aggregated[entry.fingerprint] = entry
        if errors:
            raise SourceValidationError("; ".join(errors))
    if duplicates:
        warnings.append(f"aggregated {duplicates} duplicate row(s)")
    if skipped_watchlist_rows:
        warnings.append(f"skipped {skipped_watchlist_rows} watchlist-only row(s) without quantity")
    return CanonicalCollection(
        entries=list(aggregated.values()),
        completeness=(
            ExtractionCompleteness.INCOMPLETE
            if invalid_records or lossy_records
            else ExtractionCompleteness.COMPLETE
        ),
        warnings=warnings,
    ), ParseDiagnostics(schema, duplicates, invalid_records, warnings)
