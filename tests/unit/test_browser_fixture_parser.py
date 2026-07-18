import pytest
from pydantic import ValidationError

from card_relay.domain.enums import ExtractionCompleteness, IngestionMethod
from card_relay.domain.models import (
    CanonicalCardIdentity,
    CanonicalCollection,
    CanonicalCollectionEntry,
)
from card_relay.exceptions import IntegrationUnavailableError
from card_relay.sources.collectr.parsers.browser_fixture_parser import (
    BrowserExtractionDiagnostics,
    BrowserFixtureParseResult,
    CollectrBrowserFixtureParser,
)


def _partial_collection() -> CanonicalCollection:
    return CanonicalCollection(
        entries=[
            CanonicalCollectionEntry(
                identity=CanonicalCardIdentity(
                    card_name="Fixturemon",
                    set_name="Fixture Set",
                    collector_number="1",
                ),
                quantity=1,
                ingestion_method=IngestionMethod.BROWSER,
            )
        ],
        completeness=ExtractionCompleteness.INCOMPLETE,
    )


def test_partial_browser_diagnostics_can_never_authorize_destruction() -> None:
    diagnostics = BrowserExtractionDiagnostics(
        completeness=ExtractionCompleteness.INCOMPLETE,
        observed_record_count=1,
        visible_total=2,
        observed_page_count=1,
        expected_page_count=2,
        pagination_complete=False,
        schema_recognized=True,
    )
    result = BrowserFixtureParseResult(collection=_partial_collection(), diagnostics=diagnostics)

    assert not result.diagnostics.completeness_checks_passed
    assert not result.diagnostics.trusted_for_destructive_planning


def test_complete_browser_claim_requires_count_and_pagination_evidence() -> None:
    with pytest.raises(ValidationError, match="requires all completeness checks"):
        BrowserExtractionDiagnostics(
            completeness=ExtractionCompleteness.COMPLETE,
            observed_record_count=1,
            visible_total=2,
            observed_page_count=1,
            expected_page_count=2,
            pagination_complete=False,
            schema_recognized=True,
        )


def test_complete_browser_diagnostics_are_trusted_only_when_checks_pass() -> None:
    diagnostics = BrowserExtractionDiagnostics(
        completeness=ExtractionCompleteness.COMPLETE,
        observed_record_count=2,
        visible_total=2,
        observed_page_count=1,
        expected_page_count=1,
        pagination_complete=True,
        schema_recognized=True,
    )

    assert diagnostics.completeness_checks_passed
    assert diagnostics.trusted_for_destructive_planning


def test_browser_fixture_parser_remains_fail_closed_without_contract() -> None:
    with pytest.raises(IntegrationUnavailableError, match="sanitized, verified"):
        CollectrBrowserFixtureParser().parse({"records": []})
