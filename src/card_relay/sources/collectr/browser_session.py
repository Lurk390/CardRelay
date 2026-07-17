from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel

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
