import json
from pathlib import Path

import pytest

from card_relay.domain.enums import ExtractionCompleteness
from card_relay.exceptions import IntegrationUnavailableError
from card_relay.sources.collectr.browser_capture import (
    CollectrNetworkCapture,
    _require_authenticated_portfolio,
    _wait_for_visible_card_total,
)
from card_relay.sources.collectr.parsers.browser_fixture_parser import (
    CollectrBrowserFixtureParser,
)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "collectr"


class FakeResponse:
    def __init__(self, url: str, payload: object) -> None:
        self.url = url
        self.payload = payload

    def json(self) -> object:
        return self.payload


def _pages() -> list[object]:
    value = json.loads((FIXTURES / "web_products_pages.json").read_text(encoding="utf-8"))
    assert isinstance(value, list)
    return value


def _product_url(offset: int) -> str:
    return (
        "https://api-v2.getcollectr.com/collections/fictional/products"
        f"?offset={offset}&limit=30&currency=USD&unstackedView=true"
    )


def test_network_capture_orders_pages_and_normalizes_lookup_metadata() -> None:
    capture = CollectrNetworkCapture()
    capture.observe_response(
        FakeResponse(
            "https://api-v2.getcollectr.com/data/card-conditions",
            {"scale": [{"id": 1, "display_name": "Near Mint"}]},
        )
    )
    capture.observe_response(
        FakeResponse(
            "https://api-v2.getcollectr.com/data/grading-scales",
            {"data": [{"company": "CGC", "grades": [{"id": 10, "grade": "10.0"}]}]},
        )
    )
    for offset, payload in zip((0, 30, 60), _pages(), strict=True):
        capture.observe_response(FakeResponse(_product_url(offset), payload))

    envelope = capture.build(visible_total_quantity=4)
    result = CollectrBrowserFixtureParser().parse(envelope)

    assert capture.product_response_count == 3
    assert capture.terminal_page_seen
    assert capture.condition_names == {"1": "Near Mint"}
    assert capture.grade_details["10"].company == "CGC"
    assert result.collection.completeness is ExtractionCompleteness.COMPLETE
    assert result.collection.total_quantity == 4


def test_network_capture_with_missing_offset_fails_closed_as_partial() -> None:
    pages = _pages()
    capture = CollectrNetworkCapture()
    capture.observe_response(FakeResponse(_product_url(0), pages[0]))
    capture.observe_response(FakeResponse(_product_url(60), pages[2]))

    result = CollectrBrowserFixtureParser().parse(capture.build(visible_total_quantity=3))

    assert not capture.terminal_page_seen
    assert result.collection.total_quantity == 3
    assert result.collection.completeness is ExtractionCompleteness.INCOMPLETE
    assert result.diagnostics.invalid_record_count >= 1


def test_missing_condition_lookup_keeps_safe_partial_records() -> None:
    pages = _pages()
    capture = CollectrNetworkCapture()
    capture.observe_response(FakeResponse(_product_url(0), pages[0]))
    capture.observe_response(FakeResponse(_product_url(30), {"data": []}))

    result = CollectrBrowserFixtureParser().parse(capture.build(visible_total_quantity=3))

    assert result.collection.total_quantity == 3
    assert {entry.condition for entry in result.collection.entries} == {None}
    assert result.collection.completeness is ExtractionCompleteness.INCOMPLETE
    assert result.diagnostics.invalid_record_count == 2
    assert result.diagnostics.invalid_record_reasons.unresolved_condition == 2


def test_collectr_grade_52_is_the_verified_ungraded_sentinel() -> None:
    pages = _pages()
    capture = CollectrNetworkCapture()
    capture.observe_response(
        FakeResponse(
            "https://api-v2.getcollectr.com/data/card-conditions",
            {"scale": [{"id": 1, "display_name": "Near Mint"}]},
        )
    )
    capture.observe_response(FakeResponse(_product_url(0), pages[0]))
    capture.observe_response(FakeResponse(_product_url(30), {"data": []}))

    result = CollectrBrowserFixtureParser().parse(capture.build(visible_total_quantity=3))

    assert result.collection.total_quantity == 3
    assert {entry.identity.grading_status for entry in result.collection.entries} == {"ungraded"}
    assert result.diagnostics.invalid_record_count == 0
    assert result.diagnostics.invalid_record_reasons.total == 0


def test_network_capture_ignores_unrelated_responses() -> None:
    capture = CollectrNetworkCapture()
    capture.observe_response(FakeResponse("https://example.com/private", {"data": []}))

    assert capture.product_response_count == 0


def test_aggregate_portfolio_response_cannot_produce_safe_records() -> None:
    pages = _pages()
    capture = CollectrNetworkCapture()
    aggregate_url = _product_url(0).replace("unstackedView=true", "unstackedView=false")
    terminal_url = _product_url(30).replace("unstackedView=true", "unstackedView=false")
    capture.observe_response(FakeResponse(aggregate_url, pages[0]))
    capture.observe_response(FakeResponse(terminal_url, {"data": []}))

    result = CollectrBrowserFixtureParser().parse(capture.build(visible_total_quantity=3))

    assert result.collection.entries == []
    assert result.collection.completeness is ExtractionCompleteness.INCOMPLETE
    assert any("aggregate portfolio view" in warning for warning in result.collection.warnings)
    assert result.diagnostics.invalid_record_reasons.aggregate_view == 2


class FakePage:
    def __init__(self, values: list[object]) -> None:
        self.values = iter(values)
        self.waits: list[float] = []

    def evaluate(self, expression: str) -> object:
        assert "Cards" in expression
        return next(self.values)

    def wait_for_timeout(self, timeout: float) -> None:
        self.waits.append(timeout)


def test_visible_card_total_waits_for_verified_overview_value() -> None:
    page = FakePage([None, None, 2299])

    assert _wait_for_visible_card_total(page, 250) == 2299
    assert page.waits == [250, 250]


def test_authentication_redirect_and_unexpected_pages_fail_closed() -> None:
    with pytest.raises(IntegrationUnavailableError, match="sign-in is required"):
        _require_authenticated_portfolio("https://auth.getcollectr.com/")
    with pytest.raises(IntegrationUnavailableError, match="verified portfolio"):
        _require_authenticated_portfolio("https://app.getcollectr.com/sets")
    _require_authenticated_portfolio("https://app.getcollectr.com/portfolio/products")
