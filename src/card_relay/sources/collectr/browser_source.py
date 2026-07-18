from collections.abc import Callable

from card_relay.domain.enums import IngestionMethod
from card_relay.domain.models import CanonicalCollection, SourceSnapshot, collection_fingerprint
from card_relay.domain.results import SourceValidationResult
from card_relay.exceptions import IntegrationUnavailableError, SourceValidationError
from card_relay.sources.collectr.parsers.browser_fixture_parser import (
    BrowserExtractionDiagnostics,
    BrowserFixtureParseResult,
    CollectrBrowserFixtureParser,
)


class CollectrBrowserSource:
    """Browser source boundary fed by an in-memory, sanitized capture provider."""

    source_name = "collectr"

    def __init__(self, capture_provider: Callable[[], object]) -> None:
        self.capture_provider = capture_provider
        self.parser = CollectrBrowserFixtureParser()
        self._payload: object | None = None
        self._loaded: BrowserFixtureParseResult | None = None

    def validate_access(self) -> SourceValidationResult:
        try:
            result = self._load()
        except (SourceValidationError, IntegrationUnavailableError) as error:
            return SourceValidationResult(valid=False, errors=[str(error)])
        return SourceValidationResult(
            valid=True,
            record_count=len(result.collection.entries),
            warnings=result.diagnostics.warnings,
        )

    def load_collection(self) -> CanonicalCollection:
        return self._load().collection

    def create_snapshot(self) -> SourceSnapshot:
        result = self._load()
        collection = result.collection
        diagnostics = result.diagnostics
        return SourceSnapshot(
            ingestion_method=IngestionMethod.BROWSER,
            source_schema_fingerprint=self.parser.schema_fingerprint(self._capture()),
            parser_name=self.parser.parser_name,
            parser_version=self.parser.parser_version,
            completeness=collection.completeness,
            total_unique_entries=len(collection.entries),
            total_quantity=collection.total_quantity,
            invalid_record_count=diagnostics.invalid_record_count,
            duplicate_record_count=diagnostics.duplicate_record_count,
            warnings=diagnostics.warnings,
            collection_fingerprint=collection_fingerprint(collection),
            trusted_for_destructive_planning=False,
        )

    def diagnostics(self) -> BrowserExtractionDiagnostics:
        return self._load().diagnostics

    def _capture(self) -> object:
        if self._payload is None:
            self._payload = self.capture_provider()
        return self._payload

    def _load(self) -> BrowserFixtureParseResult:
        if self._loaded is None:
            self._loaded = self.parser.parse(self._capture())
        return self._loaded
