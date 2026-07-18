import re
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol, cast
from urllib.parse import parse_qs, urlparse

from pydantic import BaseModel

from card_relay.exceptions import IntegrationUnavailableError
from card_relay.sources.collectr.parsers.browser_fixture_parser import BrowserCaptureEnvelope
from card_relay.sources.collectr.parsers.collectr_web_contract import (
    BrowserGradeDetails,
    build_capture_from_collectr_responses,
    build_capture_from_dom_records,
    build_capture_from_embedded_payload,
)
from card_relay.sources.collectr.parsers.csv_parser import parse_grading

COLLECTR_APP_HOST = "app.getcollectr.com"
COLLECTR_API_HOST = "api-v2.getcollectr.com"
COLLECTR_AUTH_HOST = "auth.getcollectr.com"
COLLECTR_PORTFOLIO_URL = "https://app.getcollectr.com/portfolio"
COLLECTR_PRODUCTS_URL = "https://app.getcollectr.com/portfolio/products"
_PRODUCTS_PATH = re.compile(r"^/collections/[^/]+/products$")
_PRODUCT_PAGE_LIMIT = 30
_KNOWN_CONDITIONS = {
    "mint",
    "near mint",
    "lightly played",
    "moderately played",
    "heavily played",
    "damaged",
}
_KNOWN_GRADERS = {"ace", "bgs", "beckett", "cgc", "psa", "sgc", "tag"}


class CollectrSessionDiagnostics(BaseModel):
    authentication_status: str
    profile_usable: bool
    portfolio_page_reached: bool
    reason: str


class _JsonResponse(Protocol):
    url: str

    def json(self) -> object: ...


class CollectrNetworkCapture:
    """Retain only bounded response data needed to build a canonical capture."""

    def __init__(self) -> None:
        self._product_pages: dict[int, object] = {}
        self.condition_names: dict[str, str] = {}
        self.grade_details: dict[str, BrowserGradeDetails] = {}
        self.capture_error_count = 0
        self._gap_reported = False
        self.exact_view_verified = True

    def observe_response(self, response: object) -> None:
        typed = cast(_JsonResponse, response)
        parsed = urlparse(typed.url)
        if parsed.hostname != COLLECTR_API_HOST:
            return
        if _PRODUCTS_PATH.fullmatch(parsed.path):
            try:
                query = parse_qs(parsed.query)
                limit = int(query.get("limit", [str(_PRODUCT_PAGE_LIMIT)])[0])
                offset = int(query.get("offset", ["0"])[0])
                exact_view = query.get("unstackedView", [""])[0].casefold()
                if exact_view not in {"1", "true"}:
                    self.exact_view_verified = False
                if limit != _PRODUCT_PAGE_LIMIT or offset < 0:
                    self.capture_error_count += 1
                    return
                payload = typed.json()
                existing = self._product_pages.get(offset)
                if existing is not None and existing != payload:
                    self.capture_error_count += 1
                    return
                self._product_pages[offset] = payload
            except Exception:
                self.capture_error_count += 1
        elif parsed.path == "/data/card-conditions":
            try:
                self.condition_names.update(extract_condition_names(typed.json()))
            except Exception:
                return
        elif parsed.path == "/data/grading-scales":
            try:
                self.grade_details.update(extract_grade_details(typed.json()))
            except Exception:
                return

    @property
    def product_response_count(self) -> int:
        return len(self._product_pages)

    @property
    def terminal_page_seen(self) -> bool:
        ordered = self._contiguous_pages()
        return bool(ordered and _is_empty_products_page(ordered[-1]))

    def build(self, visible_total_quantity: int | None) -> BrowserCaptureEnvelope:
        ordered = self._contiguous_pages()
        capture = build_capture_from_collectr_responses(
            ordered,
            visible_total_quantity=visible_total_quantity,
            condition_names=self.condition_names,
            grade_details=self.grade_details,
        )
        if self.capture_error_count:
            capture = capture.model_copy(
                update={
                    "invalid_record_count": (
                        capture.invalid_record_count + self.capture_error_count
                    ),
                    "invalid_record_reasons": capture.invalid_record_reasons.model_copy(
                        update={
                            "capture_error": (
                                capture.invalid_record_reasons.capture_error
                                + self.capture_error_count
                            )
                        }
                    ),
                }
            )
        if not self.exact_view_verified:
            discarded_count = sum(len(batch.records) for batch in capture.batches)
            capture = capture.model_copy(
                update={
                    "batches": [
                        batch.model_copy(update={"records": []}) for batch in capture.batches
                    ],
                    "invalid_record_count": (
                        capture.invalid_record_count + max(discarded_count, 1)
                    ),
                    "invalid_record_reasons": capture.invalid_record_reasons.model_copy(
                        update={
                            "aggregate_view": (
                                capture.invalid_record_reasons.aggregate_view
                                + max(discarded_count, 1)
                            )
                        }
                    ),
                    "warnings": [
                        *capture.warnings,
                        "Collectr returned an aggregate portfolio view; exact condition and "
                        "variant records are required",
                    ],
                }
            )
        return capture

    def _contiguous_pages(self) -> list[object]:
        pages: list[object] = []
        offset = 0
        while offset in self._product_pages:
            payload = self._product_pages[offset]
            pages.append(payload)
            if _is_empty_products_page(payload):
                break
            offset += _PRODUCT_PAGE_LIMIT
        if len(pages) != len(self._product_pages) and not self._gap_reported:
            self.capture_error_count += 1
            self._gap_reported = True
        return pages


class CollectrPortfolioCaptureSession:
    """Visible, persistent browser extraction using Collectr's verified web contract."""

    def __init__(
        self,
        profile_directory: Path,
        navigation_timeout_seconds: int = 30,
        request_delay_seconds: float = 1,
        maximum_batches: int = 200,
    ) -> None:
        self.profile_directory = profile_directory
        self.navigation_timeout_ms = navigation_timeout_seconds * 1000
        self.request_delay_ms = max(100, int(request_delay_seconds * 1000))
        self.maximum_batches = maximum_batches

    def capture_visible(self) -> BrowserCaptureEnvelope:
        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            raise IntegrationUnavailableError(
                "Playwright is not installed; run `uv sync --all-extras --dev`"
            ) from error

        network = CollectrNetworkCapture()
        fallback_capture: BrowserCaptureEnvelope | None = None
        try:
            with sync_playwright() as playwright:
                self.profile_directory.mkdir(parents=True, exist_ok=True)
                context = playwright.chromium.launch_persistent_context(
                    str(self.profile_directory), headless=False
                )
                page = context.pages[0] if context.pages else context.new_page()
                page.on("response", network.observe_response)
                try:
                    page.set_default_navigation_timeout(self.navigation_timeout_ms)
                    page.goto(COLLECTR_PORTFOLIO_URL, wait_until="domcontentloaded")
                    _require_authenticated_portfolio(page.url)
                    visible_total = _wait_for_visible_card_total(page, self.request_delay_ms)
                    page.goto(COLLECTR_PRODUCTS_URL, wait_until="domcontentloaded")
                    _require_authenticated_portfolio(page.url)
                    end_of_scroll_observed = self._load_all_batches(page, network)
                    if network.product_response_count == 0:
                        embedded = _embedded_products_payload(page)
                        if embedded is not None:
                            fallback_capture = build_capture_from_embedded_payload(
                                embedded,
                                visible_total_quantity=visible_total,
                                condition_names=network.condition_names,
                                grade_details=network.grade_details,
                            )
                        else:
                            fallback_capture = build_capture_from_dom_records(
                                _dom_product_records(page),
                                visible_total_quantity=visible_total,
                                end_of_scroll_observed=end_of_scroll_observed,
                            )
                finally:
                    page.remove_listener("response", network.observe_response)
                    context.close()
        except PlaywrightError as error:
            raise IntegrationUnavailableError(
                "unable to capture the visible Collectr portfolio; browser state was preserved"
            ) from error
        return fallback_capture or network.build(visible_total)

    def session_status(self) -> CollectrSessionDiagnostics:
        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            raise IntegrationUnavailableError(
                "Playwright is not installed; run `uv sync --all-extras --dev`"
            ) from error

        try:
            with sync_playwright() as playwright:
                self.profile_directory.mkdir(parents=True, exist_ok=True)
                context = playwright.chromium.launch_persistent_context(
                    str(self.profile_directory), headless=False
                )
                page = context.pages[0] if context.pages else context.new_page()
                try:
                    page.set_default_navigation_timeout(self.navigation_timeout_ms)
                    page.goto(COLLECTR_PORTFOLIO_URL, wait_until="domcontentloaded")
                    final_url = page.url
                finally:
                    context.close()
        except PlaywrightError as error:
            raise IntegrationUnavailableError(
                "unable to inspect the local Collectr browser session"
            ) from error

        parsed = urlparse(final_url)
        if parsed.hostname == COLLECTR_AUTH_HOST:
            return CollectrSessionDiagnostics(
                authentication_status="signed_out",
                profile_usable=True,
                portfolio_page_reached=False,
                reason="Collectr redirected the verified portfolio route to sign-in.",
            )
        if parsed.hostname == COLLECTR_APP_HOST and parsed.path.startswith("/portfolio"):
            return CollectrSessionDiagnostics(
                authentication_status="authenticated",
                profile_usable=True,
                portfolio_page_reached=True,
                reason="The verified portfolio route remained accessible.",
            )
        return CollectrSessionDiagnostics(
            authentication_status="unknown",
            profile_usable=True,
            portfolio_page_reached=False,
            reason="The browser reached neither the verified portfolio nor sign-in route.",
        )

    def _load_all_batches(self, page: object, network: CollectrNetworkCapture) -> bool:
        typed_page = cast(_BrowserPage, page)
        stable_iterations = 0
        previous_response_count = -1
        for _ in range(self.maximum_batches + 2):
            typed_page.wait_for_timeout(self.request_delay_ms)
            if network.terminal_page_seen:
                return True
            if network.product_response_count == previous_response_count:
                stable_iterations += 1
            else:
                stable_iterations = 0
                previous_response_count = network.product_response_count
            if stable_iterations >= 3:
                return network.product_response_count == 0
            typed_page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
        return False


class _BrowserPage(Protocol):
    url: str

    def evaluate(self, expression: str) -> object: ...

    def wait_for_timeout(self, timeout: float) -> None: ...


def _require_authenticated_portfolio(url: str) -> None:
    parsed = urlparse(url)
    if parsed.hostname == COLLECTR_AUTH_HOST:
        raise IntegrationUnavailableError(
            "Collectr sign-in is required; run `card-relay collectr login` first"
        )
    if parsed.hostname != COLLECTR_APP_HOST or not parsed.path.startswith("/portfolio"):
        raise IntegrationUnavailableError("Collectr did not remain on a verified portfolio page")


def _wait_for_visible_card_total(page: object, delay_ms: int) -> int | None:
    typed_page = cast(_BrowserPage, page)
    expression = r"""
    () => {
      for (const element of document.querySelectorAll('*')) {
        if (element.children.length !== 0) continue;
        const text = (element.textContent || '').trim();
        if (!/^Cards\s*\([^)]*\)$/i.test(text)) continue;
        const container = element.parentElement;
        const match = (container?.textContent || '').match(/Cards\s*\([^)]*\)\s*([\d,]+)/i);
        if (match) return Number(match[1].replaceAll(',', ''));
      }
      return null;
    }
    """
    for _ in range(10):
        value = typed_page.evaluate(expression)
        if isinstance(value, int) and value >= 0:
            return value
        typed_page.wait_for_timeout(delay_ms)
    return None


def _embedded_products_payload(page: object) -> object | None:
    typed_page = cast(_BrowserPage, page)
    result = typed_page.evaluate(
        r"""
        () => {
          const candidates = [];
          const visit = (value, depth = 0) => {
            if (!value || typeof value !== 'object' || depth > 6) return;
            if (Array.isArray(value)) {
              for (const child of value.slice(0, 500)) visit(child, depth + 1);
              return;
            }
            if (Array.isArray(value.data) && value.data.some(
              item => item && typeof item === 'object' && 'product_id' in item
            )) candidates.push(value);
            for (const child of Object.values(value).slice(0, 100)) visit(child, depth + 1);
          };
          for (const script of Array.from(
            document.querySelectorAll('script[type="application/json"]')
          ).slice(0, 20)) {
            try { visit(JSON.parse(script.textContent || '')); } catch {}
          }
          return candidates.length === 1 ? candidates[0] : null;
        }
        """
    )
    return result


def _dom_product_records(page: object) -> list[object]:
    typed_page = cast(_BrowserPage, page)
    result = typed_page.evaluate(
        r"""
        () => Array.from(document.querySelectorAll('ul > li')).map(item => {
          const leaves = Array.from(item.querySelectorAll('*'))
            .filter(element => element.children.length === 0)
            .map(element => ({
              text: (element.textContent || '').trim(),
              classes: typeof element.className === 'string' ? element.className : ''
            }));
          const text = leaves.map(item => item.text).filter(Boolean);
          const named = className => leaves.find(item => item.classes.includes(className))?.text;
          const number = text.find(value => /^\S+\/\S+$/.test(value));
          const quantity = text.map(value => value.match(/^Qty:\s*(\d+)$/i))
            .find(match => match)?.[1];
          const conditionNames = new Set([
            'mint', 'near mint', 'lightly played', 'moderately played',
            'heavily played', 'damaged'
          ]);
          const finishNames = new Set([
            'normal', 'foil', 'holofoil', 'reverse holofoil',
            'master ball reverse holo', 'cracked ice', 'cosmos holo',
            'stamped', 'promo'
          ]);
          const condition = text.find(value => conditionNames.has(value.toLowerCase()));
          const finish = text.find(value => finishNames.has(value.toLowerCase()));
          return {
            card_name: named('text-card-foreground'),
            set_name: named('underline'),
            collector_number: number,
            quantity: quantity ? Number(quantity) : null,
            condition: condition || null,
            finish: finish || '',
          };
        })
        """
    )
    return cast(list[object], result) if isinstance(result, list) else []


def _is_empty_products_page(payload: object) -> bool:
    return isinstance(payload, Mapping) and payload.get("data") == []


def extract_condition_names(payload: object) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in _walk_mappings(payload):
        identifier = item.get("id")
        if identifier is None:
            continue
        labels = [value for value in item.values() if isinstance(value, str)]
        matches = [label for label in labels if label.casefold() in _KNOWN_CONDITIONS]
        if len(set(matches)) == 1:
            result[str(identifier)] = matches[0]
    return result


def extract_grade_details(payload: object) -> dict[str, BrowserGradeDetails]:
    result: dict[str, BrowserGradeDetails] = {}
    _walk_grade_mappings(payload, None, result)
    return result


def _walk_grade_mappings(
    value: object,
    company_hint: str | None,
    result: dict[str, BrowserGradeDetails],
    depth: int = 0,
) -> None:
    if depth > 8:
        return
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        strings = [item for item in mapping.values() if isinstance(item, str)]
        company = company_hint or next(
            (item for item in strings if item.casefold() in _KNOWN_GRADERS), None
        )
        identifier = mapping.get("id")
        if identifier is not None:
            for label in strings:
                try:
                    status, parsed_company, grade = parse_grading(label, company or "")
                except ValueError:
                    continue
                if status == "graded" and parsed_company and grade is not None:
                    result[str(identifier)] = BrowserGradeDetails(
                        company=parsed_company, grade=grade
                    )
                    break
        for child in mapping.values():
            _walk_grade_mappings(child, company, result, depth + 1)
    elif isinstance(value, list):
        for child in value:
            _walk_grade_mappings(child, company_hint, result, depth + 1)


def _walk_mappings(value: object, depth: int = 0) -> list[Mapping[object, object]]:
    if depth > 8:
        return []
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        nested = [mapping]
        for child in mapping.values():
            nested.extend(_walk_mappings(child, depth + 1))
        return nested
    if isinstance(value, list):
        nested = []
        for child in value:
            nested.extend(_walk_mappings(child, depth + 1))
        return nested
    return []
