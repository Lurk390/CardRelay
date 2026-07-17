from card_relay.browser.profile import (
    browser_profile_directory,
    browser_profile_present,
    clear_browser_profile,
)
from card_relay.sources.collectr.browser_session import BrowserInspectionDiagnostics


def test_browser_profile_status_and_clear(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CARD_RELAY_DATA_DIRECTORY", str(tmp_path))
    profile = browser_profile_directory()
    assert not browser_profile_present()
    profile.mkdir(parents=True)
    (profile / "fictional-state").write_text("local", encoding="utf-8")
    assert browser_profile_present()
    clear_browser_profile()
    assert not profile.exists()


class FakeResponse:
    def __init__(self, status: int, content_type: str) -> None:
        self.status = status
        self.headers = {"content-type": content_type, "authorization": "never-read"}


def test_inspection_diagnostics_record_only_safe_counts() -> None:
    diagnostics = BrowserInspectionDiagnostics()
    diagnostics.observe_response(FakeResponse(200, "application/json"))
    diagnostics.observe_response(FakeResponse(302, "text/html"))
    diagnostics.observe_response(FakeResponse(503, "application/json"))
    assert diagnostics.model_dump() == {
        "response_count": 3,
        "structured_response_count": 2,
        "successful_response_count": 1,
        "redirect_response_count": 1,
        "client_error_count": 0,
        "server_error_count": 1,
    }
    assert "authorization" not in diagnostics.model_dump_json()
