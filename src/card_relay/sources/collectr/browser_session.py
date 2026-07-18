import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, cast
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from card_relay.exceptions import IntegrationUnavailableError


class BrowserSessionManager:
    """Visible, persistent, user-controlled browser session boundary."""

    def __init__(
        self,
        profile_directory: Path,
        navigation_timeout_seconds: int = 30,
    ) -> None:
        self.profile_directory = profile_directory
        self.navigation_timeout_ms = navigation_timeout_seconds * 1000

    def run_visible(
        self,
        url: str,
        wait_for_user: Callable[[], None],
        cdp_url: str | None = None,
    ) -> None:
        self._run(url, wait_for_user, None, cdp_url)

    def inspect_visible(
        self,
        url: str,
        wait_for_user: Callable[[], None],
        cdp_url: str | None = None,
    ) -> "BrowserInspectionDiagnostics":
        diagnostics = BrowserInspectionDiagnostics()
        self._run(url, wait_for_user, diagnostics, cdp_url)
        return diagnostics

    def inspect_active_cdp_page_schema(
        self,
        cdp_url: str,
        expected_hostname: str,
        capture_seconds: int = 5,
    ) -> "BrowserSchemaInspectionDiagnostics":
        """Reload the active CDP page and retain only redacted JSON structure."""
        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            raise IntegrationUnavailableError(
                "Playwright is not installed; run `uv sync --all-extras --dev`"
            ) from error

        validate_cdp_endpoint(cdp_url)
        diagnostics = BrowserSchemaInspectionDiagnostics()
        completed_responses: list[object] = []

        def queue_finished_response(request: object) -> None:
            typed_request = cast(_FinishedRequest, request)
            response = typed_request.response()
            sizes = typed_request.sizes()
            response_body_size = sizes.get("responseBodySize")
            if response is not None and diagnostics.should_capture_response(
                response,
                response_body_size,
                probe_non_json=typed_request.resource_type in {"fetch", "xhr"},
            ):
                completed_responses.append(response)

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.connect_over_cdp(cdp_url)
                if not browser.contexts:
                    raise IntegrationUnavailableError(
                        "the local Chrome instance has no accessible browser context"
                    )
                matching_pages = [
                    page
                    for page in browser.contexts[0].pages
                    if urlparse(page.url).hostname == expected_hostname
                ]
                if not matching_pages:
                    raise IntegrationUnavailableError(
                        "the local Chrome instance has no open page for the expected service"
                    )
                visible_pages = [
                    page
                    for page in matching_pages
                    if page.evaluate("document.visibilityState") == "visible"
                ]
                page = visible_pages[-1] if visible_pages else matching_pages[-1]
                page.on("requestfinished", queue_finished_response)
                try:
                    page.set_default_navigation_timeout(self.navigation_timeout_ms)
                    page.reload(
                        wait_until="commit",
                        timeout=min(self.navigation_timeout_ms, 10_000),
                    )
                    page.wait_for_timeout(capture_seconds * 1000)
                finally:
                    page.remove_listener("requestfinished", queue_finished_response)
                for response in completed_responses:
                    diagnostics.capture_response_shape(response)
        except PlaywrightError as error:
            raise IntegrationUnavailableError(_classify_browser_launch_error(str(error))) from error
        return diagnostics

    def _run(
        self,
        url: str,
        wait_for_user: Callable[[], None],
        diagnostics: "BrowserInspectionDiagnostics | None",
        cdp_url: str | None,
    ) -> None:
        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            raise IntegrationUnavailableError(
                "Playwright is not installed; run `uv sync --all-extras --dev`"
            ) from error

        try:
            with sync_playwright() as playwright:
                if cdp_url is not None:
                    validate_cdp_endpoint(cdp_url)
                    browser = playwright.chromium.connect_over_cdp(cdp_url)
                    if not browser.contexts:
                        raise IntegrationUnavailableError(
                            "the remote Chrome instance has no accessible browser context"
                        )
                    context = browser.contexts[0]
                    page = context.new_page()
                    close_context = False
                else:
                    self.profile_directory.mkdir(parents=True, exist_ok=True)
                    context = playwright.chromium.launch_persistent_context(
                        str(self.profile_directory), headless=False
                    )
                    page = context.pages[0] if context.pages else context.new_page()
                    close_context = True
                try:
                    if diagnostics is not None:
                        page.on("response", diagnostics.observe_response)
                    page.set_default_navigation_timeout(self.navigation_timeout_ms)
                    page.goto(url, wait_until="domcontentloaded")
                    wait_for_user()
                finally:
                    if close_context:
                        context.close()
        except PlaywrightError as error:
            raise IntegrationUnavailableError(_classify_browser_launch_error(str(error))) from error


class BrowserInspectionDiagnostics(BaseModel):
    """Non-sensitive response metadata; deliberately excludes URLs and payloads."""

    response_count: int = 0
    structured_response_count: int = 0
    successful_response_count: int = 0
    redirect_response_count: int = 0
    client_error_count: int = 0
    server_error_count: int = 0

    def observe_response(self, response: object) -> None:
        status = int(getattr(response, "status", 0))
        headers = getattr(response, "headers", {})
        content_type = str(headers.get("content-type", "")).casefold()
        self.response_count += 1
        self.structured_response_count += int("json" in content_type or "graphql" in content_type)
        self.successful_response_count += int(200 <= status < 300)
        self.redirect_response_count += int(300 <= status < 400)
        self.client_error_count += int(400 <= status < 500)
        self.server_error_count += int(status >= 500)


class _ResponseMetadata(Protocol):
    status: int
    headers: dict[str, str]


class _JsonResponse(_ResponseMetadata, Protocol):
    def json(self) -> object: ...

    def text(self) -> str: ...


class _FinishedRequest(Protocol):
    resource_type: str

    def response(self) -> object | None: ...

    def sizes(self) -> dict[str, int]: ...


_SAFE_FIELD_NAME = re.compile(r"^[a-z_][A-Za-z0-9_-]{0,63}$")
_UUID_FIELD_NAME = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)
_LONG_OPAQUE_FIELD_NAME = re.compile(r"^[A-Za-z0-9_-]{24,}$")
_MAX_SCHEMA_DEPTH = 6
_MAX_OBJECT_FIELDS = 50
_MAX_SCHEMA_CANDIDATES = 25
_MAX_JSON_LINES = 50
_MAX_NON_JSON_PROBES = 10
_MAX_UNKNOWN_SIZE_CANDIDATES = 3
_MAX_DECLARED_RESPONSE_BYTES = 1_000_000


def describe_json_shape(value: object, depth: int = 0) -> dict[str, object]:
    """Describe JSON structure without retaining scalar values."""
    if depth >= _MAX_SCHEMA_DEPTH:
        return {"type": _json_type(value), "truncated": True}
    if isinstance(value, dict):
        mapping = cast(dict[object, object], value)
        sorted_items = sorted(mapping.items(), key=lambda item: _redact_field_name(item[0]))
        fields = [
            {
                "name": _redact_field_name(key),
                "shape": describe_json_shape(child, depth + 1),
            }
            for key, child in sorted_items[:_MAX_OBJECT_FIELDS]
        ]
        shape: dict[str, object] = {"type": "object", "fields": fields}
        if len(sorted_items) > _MAX_OBJECT_FIELDS:
            shape["truncated_fields"] = True
        return shape
    if isinstance(value, list):
        cardinality = "empty" if not value else "one" if len(value) == 1 else "many"
        shape = {"type": "array", "cardinality": cardinality}
        if value:
            shape["items"] = describe_json_shape(value[0], depth + 1)
        return shape
    return {"type": _json_type(value)}


def _json_type(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "unsupported"


def _redact_field_name(field_name: object) -> str:
    if not isinstance(field_name, str):
        return "<redacted-key>"
    if (
        not _SAFE_FIELD_NAME.fullmatch(field_name)
        or _UUID_FIELD_NAME.fullmatch(field_name)
        or _LONG_OPAQUE_FIELD_NAME.fullmatch(field_name)
        or any(character.isdigit() for character in field_name)
    ):
        return "<redacted-key>"
    return field_name


class BrowserSchemaInspectionDiagnostics(BaseModel):
    """Explicitly gated in-memory JSON shape capture with no scalar values."""

    response_count: int = 0
    structured_response_count: int = 0
    schema_candidate_count: int = 0
    accepted_response_count: int = 0
    skipped_unbounded_count: int = 0
    skipped_oversized_count: int = 0
    unreadable_structured_count: int = 0
    invalid_json_count: int = 0
    unavailable_body_count: int = 0
    unknown_size_candidate_count: int = 0
    non_json_probe_count: int = 0
    schema_candidates: list[dict[str, object]] = Field(default_factory=list)

    def observe_response(self, response: object) -> None:
        if not self.should_capture_response(response):
            return
        self.capture_response_shape(response)

    def should_capture_response(
        self,
        response: object,
        completed_body_size: int | None = None,
        probe_non_json: bool = False,
    ) -> bool:
        typed_response = cast(_ResponseMetadata, response)
        return self._should_read(typed_response, completed_body_size, probe_non_json)

    def capture_response_shape(self, response: object) -> None:
        typed_response = cast(_JsonResponse, response)
        try:
            payload = typed_response.json()
        except Exception as error:
            if isinstance(error, json.JSONDecodeError):
                try:
                    json_lines_shape = describe_json_lines_shape(typed_response.text())
                except Exception:
                    json_lines_shape = None
                if json_lines_shape is not None:
                    self._append_shape(typed_response.status, json_lines_shape)
                    return
                self.invalid_json_count += 1
            else:
                self.unavailable_body_count += 1
            self.unreadable_structured_count += 1
            return
        self._record_shape(typed_response.status, payload)

    def _should_read(
        self,
        response: _ResponseMetadata,
        completed_body_size: int | None = None,
        probe_non_json: bool = False,
    ) -> bool:
        self.response_count += 1
        content_type = response.headers.get("content-type", "").casefold()
        if "json" not in content_type and "graphql" not in content_type:
            if not probe_non_json or self.non_json_probe_count >= _MAX_NON_JSON_PROBES:
                return False
            self.non_json_probe_count += 1
        else:
            self.structured_response_count += 1
        if self.accepted_response_count >= _MAX_SCHEMA_CANDIDATES:
            return False
        if completed_body_size is not None:
            if completed_body_size < 0:
                if self.unknown_size_candidate_count >= _MAX_UNKNOWN_SIZE_CANDIDATES:
                    self.skipped_unbounded_count += 1
                    return False
                self.unknown_size_candidate_count += 1
            if completed_body_size > _MAX_DECLARED_RESPONSE_BYTES:
                self.skipped_oversized_count += 1
                return False
        else:
            declared_length = response.headers.get("content-length")
            if declared_length is None:
                self.skipped_unbounded_count += 1
                return False
            try:
                if int(declared_length) > _MAX_DECLARED_RESPONSE_BYTES:
                    self.skipped_oversized_count += 1
                    return False
            except ValueError:
                self.unreadable_structured_count += 1
                return False
        self.accepted_response_count += 1
        return True

    def _record_shape(self, status: int, payload: object) -> None:
        self._append_shape(status, describe_json_shape(payload))

    def _append_shape(self, status: int, shape: dict[str, object]) -> None:
        self.schema_candidates.append(
            {
                "candidate": len(self.schema_candidates) + 1,
                "status_class": f"{status // 100}xx",
                "shape": shape,
            }
        )
        self.schema_candidate_count = len(self.schema_candidates)


def describe_json_lines_shape(text: str) -> dict[str, object] | None:
    """Describe bounded newline-delimited JSON without retaining scalar values."""
    records: list[object] = []
    for raw_line in text.splitlines()[:_MAX_JSON_LINES]:
        line = raw_line.strip()
        if line.startswith("data:"):
            line = line.removeprefix("data:").strip()
        if not line or line == "[DONE]":
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            return None
    if not records:
        return None
    cardinality = "one" if len(records) == 1 else "many"
    return {
        "type": "json-lines",
        "cardinality": cardinality,
        "records": describe_json_shape(records[0]),
    }


def _classify_browser_launch_error(message: str) -> str:
    normalized = message.casefold()
    if "missing x server" in normalized or "$display" in normalized:
        return (
            "unable to launch the required visible browser: no desktop display is available. "
            "Run CardRelay on the desktop host or configure explicit X11/Wayland forwarding "
            "for the container; headless authentication is intentionally disabled"
        )
    if "error while loading shared libraries" in normalized:
        return (
            "Chromium system libraries are missing; run "
            "`uv run playwright install --with-deps chromium`"
        )
    if "executable doesn't exist" in normalized:
        return "Chromium is not installed; run `uv run playwright install chromium`"
    return "unable to launch the visible Chromium session; see verbose logs for diagnostics"


def validate_cdp_endpoint(endpoint: str) -> None:
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
        "127.0.0.1",
        "localhost",
        "::1",
    }:
        raise IntegrationUnavailableError(
            "CDP endpoint must use HTTP(S) on loopback; expose it only through an SSH tunnel"
        )
