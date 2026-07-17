from collections.abc import Callable
from pathlib import Path

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

    def run_visible(self, url: str, wait_for_user: Callable[[], None]) -> None:
        self._run(url, wait_for_user, None)

    def inspect_visible(
        self, url: str, wait_for_user: Callable[[], None]
    ) -> "BrowserInspectionDiagnostics":
        diagnostics = BrowserInspectionDiagnostics()
        self._run(url, wait_for_user, diagnostics)
        return diagnostics

    def _run(
        self,
        url: str,
        wait_for_user: Callable[[], None],
        diagnostics: "BrowserInspectionDiagnostics | None",
    ) -> None:
        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            raise IntegrationUnavailableError(
                "Playwright is not installed; run `uv sync --all-extras --dev`"
            ) from error

        self.profile_directory.mkdir(parents=True, exist_ok=True)
        try:
            with sync_playwright() as playwright:
                context = playwright.chromium.launch_persistent_context(
                    str(self.profile_directory), headless=False
                )
                try:
                    page = context.pages[0] if context.pages else context.new_page()
                    if diagnostics is not None:
                        page.on("response", diagnostics.observe_response)
                    page.set_default_navigation_timeout(self.navigation_timeout_ms)
                    page.goto(url, wait_until="domcontentloaded")
                    wait_for_user()
                finally:
                    context.close()
        except PlaywrightError as error:
            raise IntegrationUnavailableError(
                "unable to launch Chromium; run `uv run playwright install chromium`"
            ) from error


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
