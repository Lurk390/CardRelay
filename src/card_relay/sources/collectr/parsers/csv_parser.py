import csv
import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from functools import partial
from pathlib import Path

from pydantic import ValidationError

from card_relay.domain.enums import Edition, Finish, IngestionMethod
from card_relay.domain.models import (
    CanonicalCardIdentity,
    CanonicalCollection,
    CanonicalCollectionEntry,
)
from card_relay.exceptions import SourceValidationError

PARSER_VERSION = "1.0"


@dataclass(frozen=True)
class ParseDiagnostics:
    schema_fingerprint: str
    duplicate_count: int
    warnings: list[str]


def _header_key(value: str) -> str:
    return " ".join(value.strip().casefold().replace("_", " ").split())


def _map_headers(headers: Sequence[str], aliases: dict[str, list[str]]) -> dict[str, str]:
    actual = {_header_key(header): header for header in headers}
    result: dict[str, str] = {}
    for canonical, candidates in aliases.items():
        for candidate in [canonical, *candidates]:
            if _header_key(candidate) in actual:
                result[canonical] = actual[_header_key(candidate)]
                break
    missing = [name for name in ("card_name", "collector_number", "quantity") if name not in result]
    if missing or ("set_name" not in result and "set_code" not in result):
        raise SourceValidationError(
            f"missing required CSV identity columns: {', '.join(missing or ['set_name/set_code'])}"
        )
    return result


def _finish(value: str) -> Finish:
    normalized = _header_key(value)
    known = {
        "normal": Finish.NORMAL,
        "holo": Finish.HOLO,
        "holofoil": Finish.HOLO,
        "reverse holo": Finish.REVERSE_HOLO,
        "reverse holofoil": Finish.REVERSE_HOLO,
        "cracked ice": Finish.CRACKED_ICE,
        "cosmos holo": Finish.COSMOS_HOLO,
        "stamped": Finish.STAMPED,
        "promo": Finish.PROMO,
    }
    return known.get(normalized, Finish.UNKNOWN if not normalized else Finish.APPLICATION_SPECIFIC)


def _row_value(row: dict[str, str | None], mapped: dict[str, str], key: str) -> str:
    return (row.get(mapped[key], "") or "").strip() if key in mapped else ""


def parse_csv(
    path: Path, aliases: dict[str, list[str]]
) -> tuple[CanonicalCollection, ParseDiagnostics]:
    try:
        handle = path.open(encoding="utf-8-sig", newline="")
    except (OSError, UnicodeError) as error:
        raise SourceValidationError(f"unable to read CSV as UTF-8: {error}") from error
    with handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise SourceValidationError("CSV has no header row")
        mapped = _map_headers(reader.fieldnames, aliases)
        schema = hashlib.sha256(
            "|".join(sorted(_header_key(h) for h in reader.fieldnames)).encode()
        ).hexdigest()
        aggregated: dict[str, CanonicalCollectionEntry] = {}
        duplicates = 0
        warnings: list[str] = []
        errors: list[str] = []
        for row_number, row in enumerate(reader, start=2):
            if not any((value or "").strip() for value in row.values()):
                continue

            value = partial(_row_value, row, mapped)

            try:
                quantity = int(value("quantity"))
                if quantity <= 0:
                    raise ValueError("quantity must be greater than zero")
                edition_value = _header_key(value("edition"))
                edition = (
                    Edition.FIRST
                    if "first" in edition_value
                    else Edition.UNLIMITED
                    if edition_value == "unlimited"
                    else Edition.UNKNOWN
                )
                grader = value("grading_company") or None
                identity = CanonicalCardIdentity(
                    card_name=value("card_name"),
                    set_name=value("set_name") or None,
                    set_code=value("set_code") or None,
                    collector_number=value("collector_number"),
                    language=value("language") or "unknown",
                    finish=_finish(value("finish")),
                    edition=edition,
                    grading_status="graded" if grader else "ungraded",
                    grading_company=grader,
                    grade=Decimal(value("grade")) if value("grade") else None,
                    promo=_header_key(value("promo")) in {"yes", "true", "1"},
                )
                entry = CanonicalCollectionEntry(
                    identity=identity,
                    quantity=quantity,
                    condition=value("condition") or None,
                    ingestion_method=IngestionMethod.CSV,
                    raw_provenance={key: mapped[key] for key in mapped},
                    warnings=[f"unrecognized finish: {value('finish')}"]
                    if identity.finish is Finish.APPLICATION_SPECIFIC
                    else [],
                )
            except (ValueError, ValidationError) as error:
                errors.append(f"row {row_number}: {error}")
                continue
            if entry.fingerprint in aggregated:
                previous = aggregated[entry.fingerprint]
                aggregated[entry.fingerprint] = previous.model_copy(
                    update={"quantity": previous.quantity + entry.quantity}
                )
                duplicates += 1
            else:
                aggregated[entry.fingerprint] = entry
        if errors:
            raise SourceValidationError("; ".join(errors))
    if duplicates:
        warnings.append(f"aggregated {duplicates} duplicate row(s)")
    return CanonicalCollection(
        entries=list(aggregated.values()), warnings=warnings
    ), ParseDiagnostics(schema, duplicates, warnings)
