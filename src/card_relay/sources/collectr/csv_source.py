from pathlib import Path

from card_relay.domain.enums import ExtractionCompleteness, IngestionMethod
from card_relay.domain.models import CanonicalCollection, SourceSnapshot, collection_fingerprint
from card_relay.domain.results import SourceValidationResult
from card_relay.exceptions import SourceValidationError
from card_relay.sources.collectr.models import DEFAULT_COLUMN_ALIASES
from card_relay.sources.collectr.parsers.csv_parser import (
    PARSER_VERSION,
    ParseDiagnostics,
    parse_csv,
)


class CollectrCsvSource:
    source_name = "collectr"

    def __init__(self, path: Path, aliases: dict[str, list[str]] | None = None) -> None:
        self.path = path
        self.aliases = aliases or DEFAULT_COLUMN_ALIASES
        self._loaded: tuple[CanonicalCollection, ParseDiagnostics] | None = None

    def validate_access(self) -> SourceValidationResult:
        try:
            collection, _ = self._load()
        except SourceValidationError as error:
            return SourceValidationResult(valid=False, errors=[str(error)])
        return SourceValidationResult(
            valid=True, record_count=len(collection.entries), warnings=collection.warnings
        )

    def _load(self) -> tuple[CanonicalCollection, ParseDiagnostics]:
        if self._loaded is None:
            self._loaded = parse_csv(self.path, self.aliases)
        return self._loaded

    def load_collection(self) -> CanonicalCollection:
        return self._load()[0]

    def create_snapshot(self) -> SourceSnapshot:
        collection, diagnostics = self._load()
        return SourceSnapshot(
            ingestion_method=IngestionMethod.CSV,
            source_schema_fingerprint=diagnostics.schema_fingerprint,
            parser_name="collectr_csv",
            parser_version=PARSER_VERSION,
            completeness=collection.completeness,
            total_unique_entries=len(collection.entries),
            total_quantity=collection.total_quantity,
            invalid_record_count=diagnostics.invalid_record_count,
            duplicate_record_count=diagnostics.duplicate_count,
            warnings=diagnostics.warnings,
            collection_fingerprint=collection_fingerprint(collection),
            trusted_for_destructive_planning=(
                collection.completeness is ExtractionCompleteness.COMPLETE
            ),
        )
