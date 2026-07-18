import json

from card_relay.browser.profile import (
    browser_profile_directory,
    browser_profile_present,
    clear_browser_profile,
)
from card_relay.exceptions import IntegrationUnavailableError
from card_relay.sources.collectr.browser_session import (
    BrowserInspectionDiagnostics,
    BrowserSchemaInspectionDiagnostics,
    _classify_browser_launch_error,
    describe_json_lines_shape,
    describe_json_shape,
    validate_cdp_endpoint,
)


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


class FakeJsonResponse(FakeResponse):
    def __init__(
        self,
        payload: object,
        content_type: str = "application/json",
        content_length: str | None = None,
    ) -> None:
        super().__init__(200, content_type)
        if content_length is not None:
            self.headers["content-length"] = content_length
        self.payload = payload

    def json(self) -> object:
        return self.payload

    def text(self) -> str:
        return json.dumps(self.payload)


class FakeUnreadableResponse(FakeJsonResponse):
    def json(self) -> object:
        raise json.JSONDecodeError("private-response-content", "private", 0)

    def text(self) -> str:
        return "private-response-content"


class FakeJsonLinesResponse(FakeUnreadableResponse):
    def text(self) -> str:
        return 'data: {"cardId":"private-id","quantity":1}\n\n'


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


def test_browser_launch_errors_are_actionable_and_safety_preserving() -> None:
    display = _classify_browser_launch_error("Missing X server or $DISPLAY")
    assert "desktop display" in display
    assert "headless authentication is intentionally disabled" in display
    libraries = _classify_browser_launch_error(
        "error while loading shared libraries: libasound.so.2"
    )
    assert "--with-deps" in libraries
    missing = _classify_browser_launch_error("Executable doesn't exist")
    assert "playwright install chromium" in missing


def test_cdp_endpoint_is_restricted_to_loopback() -> None:
    validate_cdp_endpoint("http://127.0.0.1:9222")
    validate_cdp_endpoint("http://localhost:9222")
    try:
        validate_cdp_endpoint("http://192.0.2.1:9222")
    except IntegrationUnavailableError as error:
        assert "loopback" in str(error)
    else:
        raise AssertionError("non-loopback CDP endpoint was accepted")


def test_json_shape_discards_values_and_reports_cardinality() -> None:
    shape = describe_json_shape(
        {
            "result": [
                {
                    "cardId": "private-card-id",
                    "quantity": 1,
                    "foil": False,
                    "note": None,
                }
            ],
            "account": "private-account",
        }
    )
    serialized = json.dumps(shape)
    assert "private-card-id" not in serialized
    assert "private-account" not in serialized
    assert '"cardinality": "one"' in serialized
    assert '"cardId"' in serialized
    assert '"type": "number"' in serialized


def test_json_shape_redacts_dynamic_keys_and_limits_depth() -> None:
    shape = describe_json_shape(
        {
            "550e8400-e29b-41d4-a716-446655440000": {"nested": {"again": {"value": 1}}},
            "name with spaces": "private-card-name",
        },
        depth=4,
    )
    serialized = json.dumps(shape)
    assert "550e8400" not in serialized
    assert "private-card-name" not in serialized
    assert "name with spaces" not in serialized
    assert serialized.count("<redacted-key>") == 2
    assert '"truncated": true' in serialized


def test_schema_inspection_emits_only_safe_shapes() -> None:
    diagnostics = BrowserSchemaInspectionDiagnostics()
    diagnostics.observe_response(
        FakeJsonResponse(
            {"result": [{"name": "private-name", "quantity": 1}]},
            content_length="100",
        )
    )
    diagnostics.observe_response(FakeJsonResponse({}, content_type="text/html"))
    diagnostics.observe_response(FakeJsonResponse({}))
    diagnostics.observe_response(FakeJsonResponse({}, content_length="1000001"))
    serialized = diagnostics.model_dump_json()
    assert "private-name" not in serialized
    assert diagnostics.response_count == 4
    assert diagnostics.structured_response_count == 3
    assert diagnostics.schema_candidate_count == 1
    assert diagnostics.skipped_unbounded_count == 1
    assert diagnostics.skipped_oversized_count == 1
    assert '"status_class":"2xx"' in serialized


def test_completed_chunked_response_uses_measured_size() -> None:
    diagnostics = BrowserSchemaInspectionDiagnostics()
    response = FakeJsonResponse({"result": [{"name": "private-name"}]})
    assert diagnostics.should_capture_response(response, completed_body_size=100)
    diagnostics.capture_response_shape(response)
    serialized = diagnostics.model_dump_json()
    assert "private-name" not in serialized
    assert diagnostics.schema_candidate_count == 1
    assert diagnostics.skipped_unbounded_count == 0


def test_unknown_size_finished_responses_are_count_bounded() -> None:
    diagnostics = BrowserSchemaInspectionDiagnostics()
    responses = [FakeJsonResponse({"safeField": index}) for index in range(4)]
    accepted = [
        diagnostics.should_capture_response(response, completed_body_size=-1)
        for response in responses
    ]
    assert accepted == [True, True, True, False]
    assert diagnostics.unknown_size_candidate_count == 3
    assert diagnostics.skipped_unbounded_count == 1


def test_completed_fetch_can_probe_mislabeled_json() -> None:
    diagnostics = BrowserSchemaInspectionDiagnostics()
    response = FakeJsonResponse(
        {"changes": [{"cardId": "private-id"}]},
        content_type="text/plain",
    )
    assert diagnostics.should_capture_response(
        response,
        completed_body_size=100,
        probe_non_json=True,
    )
    diagnostics.capture_response_shape(response)
    serialized = diagnostics.model_dump_json()
    assert "private-id" not in serialized
    assert diagnostics.non_json_probe_count == 1
    assert diagnostics.schema_candidate_count == 1


def test_schema_candidate_capture_is_count_bounded() -> None:
    diagnostics = BrowserSchemaInspectionDiagnostics()
    responses = [
        FakeJsonResponse({"safeField": index}, content_length="100") for index in range(26)
    ]
    accepted = [diagnostics.should_capture_response(response) for response in responses]
    assert accepted.count(True) == 25
    assert accepted[-1] is False
    assert diagnostics.accepted_response_count == 25


def test_unreadable_response_reports_category_without_error_content() -> None:
    diagnostics = BrowserSchemaInspectionDiagnostics()
    diagnostics.observe_response(FakeUnreadableResponse({}, content_length="100"))
    serialized = diagnostics.model_dump_json()
    assert diagnostics.invalid_json_count == 1
    assert diagnostics.unreadable_structured_count == 1
    assert "private-response-content" not in serialized
    assert "private" not in serialized


def test_json_lines_response_discards_values() -> None:
    diagnostics = BrowserSchemaInspectionDiagnostics()
    diagnostics.observe_response(FakeJsonLinesResponse({}, content_length="100"))
    serialized = diagnostics.model_dump_json()
    assert diagnostics.schema_candidate_count == 1
    assert "private-id" not in serialized
    assert '"type":"json-lines"' in serialized
    assert '"cardId"' in serialized


def test_json_lines_description_rejects_mixed_non_json_content() -> None:
    assert describe_json_lines_shape('{"safe":1}\nprivate-data') is None
