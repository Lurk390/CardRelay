import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from card_relay.domain.enums import ExtractionCompleteness, IngestionMethod
from card_relay.domain.models import (
    CanonicalCardIdentity,
    CanonicalCollection,
    CanonicalCollectionEntry,
)
from card_relay.exceptions import SourceValidationError
from card_relay.sources.collectr.browser_source import CollectrBrowserSource
from card_relay.sources.collectr.csv_source import CollectrCsvSource
from card_relay.sources.collectr.parsers.browser_fixture_parser import (
    BrowserExtractionDiagnostics,
    BrowserFixtureParseResult,
    CollectrBrowserFixtureParser,
)
from card_relay.sources.collectr.parsers.collectr_web_contract import (
    BrowserGradeDetails,
    build_capture_from_collectr_responses,
    build_capture_from_dom_records,
    build_capture_from_embedded_payload,
)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "collectr"


def _fixture(name: str) -> object:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


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
        observed_total_quantity=1,
        visible_total_quantity=2,
        visible_unique_record_count=2,
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
            observed_total_quantity=1,
            visible_total_quantity=2,
            visible_unique_record_count=2,
            observed_page_count=1,
            expected_page_count=2,
            pagination_complete=False,
            schema_recognized=True,
        )


def test_complete_browser_diagnostics_remain_untrusted_until_reliability_is_approved() -> None:
    diagnostics = BrowserExtractionDiagnostics(
        completeness=ExtractionCompleteness.COMPLETE,
        observed_record_count=2,
        observed_total_quantity=2,
        visible_total_quantity=2,
        visible_unique_record_count=2,
        observed_page_count=1,
        expected_page_count=1,
        pagination_complete=True,
        schema_recognized=True,
    )

    assert diagnostics.completeness_checks_passed
    assert not diagnostics.trusted_for_destructive_planning


def test_browser_fixture_parser_remains_fail_closed_without_contract() -> None:
    with pytest.raises(SourceValidationError, match="collectr-browser-v1"):
        CollectrBrowserFixtureParser().parse({"records": []})


def test_complete_structured_browser_fixture_matches_csv_canonical_collection() -> None:
    browser = CollectrBrowserFixtureParser().parse(_fixture("browser_structured_complete.json"))
    csv = CollectrCsvSource(FIXTURES / "portfolio_export.csv").load_collection()

    def comparable(collection: CanonicalCollection) -> set[tuple[str, int, str | None, str | None]]:
        return {
            (entry.fingerprint, entry.quantity, entry.condition, entry.rarity)
            for entry in collection.entries
        }

    assert comparable(browser.collection) == comparable(csv)
    assert browser.diagnostics.completeness_checks_passed
    assert browser.diagnostics.skipped_watchlist_count == 1
    assert browser.collection.completeness is ExtractionCompleteness.COMPLETE
    assert not browser.diagnostics.trusted_for_destructive_planning


def test_partial_dom_fixture_preserves_positive_facts_and_omissions_are_unknown() -> None:
    result = CollectrBrowserFixtureParser().parse(_fixture("browser_partial.json"))

    assert len(result.collection.entries) == 1
    assert result.collection.total_quantity == 2
    assert result.collection.completeness is ExtractionCompleteness.INCOMPLETE
    assert not result.diagnostics.pagination_complete
    assert any("omitted cards remain unknown" in warning for warning in result.diagnostics.warnings)


def test_browser_source_snapshot_is_repeatable_and_never_destructive() -> None:
    calls = 0

    def provide() -> object:
        nonlocal calls
        calls += 1
        return _fixture("browser_structured_complete.json")

    source = CollectrBrowserSource(provide)
    collection = source.load_collection()
    snapshot = source.create_snapshot()

    assert calls == 1
    assert snapshot.total_unique_entries == len(collection.entries) == 3
    assert snapshot.ingestion_method is IngestionMethod.BROWSER
    assert snapshot.completeness is ExtractionCompleteness.COMPLETE
    assert not snapshot.trusted_for_destructive_planning
    assert snapshot.source_schema_fingerprint == source.create_snapshot().source_schema_fingerprint


def test_conflicting_repeated_browser_record_id_fails_closed() -> None:
    payload = _fixture("browser_structured_complete.json")
    assert isinstance(payload, dict)
    batches = payload["batches"]
    assert isinstance(batches, list)
    repeated = dict(batches[0]["records"][0])
    repeated["quantity"] = 99
    batches[1]["records"].append(repeated)
    payload["visible_unique_record_count"] = 4

    with pytest.raises(SourceValidationError, match="conflicting data"):
        CollectrBrowserFixtureParser().parse(payload)


def test_distinct_browser_records_with_conflicting_conditions_are_lossy() -> None:
    payload = _fixture("browser_structured_complete.json")
    assert isinstance(payload, dict)
    batches = payload["batches"]
    assert isinstance(batches, list)
    duplicate = dict(batches[0]["records"][0])
    duplicate["source_record_id"] = "fictional-holding-duplicate-condition"
    duplicate["condition"] = "Lightly Played"
    duplicate["quantity"] = 1
    batches[1]["records"].append(duplicate)
    payload["visible_total_quantity"] = 5

    result = CollectrBrowserFixtureParser().parse(payload)

    fixturemon = next(
        entry for entry in result.collection.entries if entry.identity.card_name == "fixturemon"
    )
    assert fixturemon.quantity == 3
    assert fixturemon.condition == "mixed"
    assert result.diagnostics.invalid_record_count == 1
    assert result.collection.completeness is ExtractionCompleteness.INCOMPLETE


def test_verified_web_response_contract_builds_complete_equivalent_capture() -> None:
    payloads = _fixture("web_products_pages.json")
    assert isinstance(payloads, list)
    capture = build_capture_from_collectr_responses(
        payloads,
        visible_total_quantity=4,
        condition_names={"1": "Near Mint"},
        grade_details={"10": BrowserGradeDetails(company="CGC", grade="10.0")},
    )
    result = CollectrBrowserFixtureParser().parse(capture)
    csv = CollectrCsvSource(FIXTURES / "portfolio_export.csv").load_collection()

    assert {
        (entry.fingerprint, entry.quantity, entry.condition, entry.rarity)
        for entry in result.collection.entries
    } == {
        (entry.fingerprint, entry.quantity, entry.condition, entry.rarity) for entry in csv.entries
    }
    assert result.collection.completeness is ExtractionCompleteness.COMPLETE
    assert result.diagnostics.skipped_non_card_count == 1
    assert not result.diagnostics.trusted_for_destructive_planning


def test_web_response_without_terminal_page_is_partial() -> None:
    payloads = _fixture("web_products_pages.json")
    assert isinstance(payloads, list)
    capture = build_capture_from_collectr_responses(
        payloads[:1],
        visible_total_quantity=4,
        condition_names={"1": "Near Mint"},
    )

    result = CollectrBrowserFixtureParser().parse(capture)

    assert result.collection.completeness is ExtractionCompleteness.INCOMPLETE
    assert not result.diagnostics.pagination_complete


def test_unknown_grading_mapping_is_skipped_and_forces_incomplete_source() -> None:
    payloads = _fixture("web_products_pages.json")
    assert isinstance(payloads, list)
    capture = build_capture_from_collectr_responses(
        payloads,
        visible_total_quantity=3,
        condition_names={"1": "Near Mint"},
    )

    result = CollectrBrowserFixtureParser().parse(capture)

    assert result.diagnostics.invalid_record_count == 1
    assert result.collection.completeness is ExtractionCompleteness.INCOMPLETE


def test_embedded_products_payload_is_parsed_but_never_assumed_complete() -> None:
    payloads = _fixture("web_products_pages.json")
    assert isinstance(payloads, list)
    capture = build_capture_from_embedded_payload(
        payloads[0],
        visible_total_quantity=4,
        condition_names={"1": "Near Mint"},
    )

    result = CollectrBrowserFixtureParser().parse(capture)

    assert result.diagnostics.strategy == "embedded_data"
    assert result.collection.completeness is ExtractionCompleteness.INCOMPLETE


def test_dom_fallback_requires_explicit_game_and_identity_fields() -> None:
    capture = build_capture_from_dom_records(
        [
            {
                "game": "Pokemon",
                "card_name": "Fixturemon",
                "set_name": "Fixture Set",
                "collector_number": "001/100",
                "quantity": 2,
                "condition": "Near Mint",
                "finish": "Holofoil",
            },
            {
                "card_name": "Game is not visible",
                "set_name": "Fixture Set",
                "quantity": 1,
            },
        ],
        visible_total_quantity=3,
        end_of_scroll_observed=True,
    )

    result = CollectrBrowserFixtureParser().parse(capture)

    assert len(result.collection.entries) == 1
    assert result.diagnostics.invalid_record_count == 1
    assert result.collection.completeness is ExtractionCompleteness.INCOMPLETE
