import hmac
import json
import secrets
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

from card_relay.exceptions import CardRelayError, SourceValidationError
from card_relay.sources.collectr.browser_capture import (
    extract_condition_names,
    extract_grade_details,
)
from card_relay.sources.collectr.browser_source import CollectrBrowserSource
from card_relay.sources.collectr.parsers.collectr_web_contract import (
    BrowserGradeDetails,
    build_capture_from_collectr_responses,
)
from card_relay.storage.database import create_database
from card_relay.storage.repositories import SnapshotRepository

MAX_CAPTURE_BYTES = 16 * 1024 * 1024
PRODUCT_PAGE_SIZE = 30


class ExtensionProductPage(BaseModel):
    offset: int = Field(ge=0)
    payload: object


class CollectrExtensionCapture(BaseModel):
    """Untrusted extension payload retained only long enough to normalize it."""

    contract_version: Literal["collectr-extension-v1"]
    product_pages: list[ExtensionProductPage] = Field(min_length=1, max_length=501)
    visible_total_quantity: int | None = Field(default=None, ge=0)
    condition_payloads: list[object] = Field(default_factory=list, max_length=5)
    grading_payloads: list[object] = Field(default_factory=list, max_length=5)
    exact_view_verified: bool

    @model_validator(mode="after")
    def pages_are_contiguous(self) -> "CollectrExtensionCapture":
        offsets = [page.offset for page in self.product_pages]
        expected = list(range(0, PRODUCT_PAGE_SIZE * len(offsets), PRODUCT_PAGE_SIZE))
        if offsets != expected:
            raise ValueError("product page offsets must be contiguous from zero")
        if not self.exact_view_verified:
            raise ValueError("aggregate portfolio captures are not accepted")
        return self


class CompanionCaptureResult(BaseModel):
    snapshot_id: str
    completeness: str
    unique_entries: int
    total_quantity: int
    pagination_complete: bool
    invalid_record_count: int
    skipped_watchlist_count: int
    skipped_non_card_count: int
    trusted_for_destructive_planning: Literal[False] = False
    destination_writes_enabled: Literal[False] = False
    warnings: list[str]


def process_collectr_capture(
    payload: object,
    database_path: Path,
) -> CompanionCaptureResult:
    request = CollectrExtensionCapture.model_validate(payload)
    condition_names: dict[str, str] = {}
    for condition_payload in request.condition_payloads:
        condition_names.update(extract_condition_names(condition_payload))
    grade_details: dict[str, BrowserGradeDetails] = {}
    for grading_payload in request.grading_payloads:
        grade_details.update(extract_grade_details(grading_payload))

    capture = build_capture_from_collectr_responses(
        [page.payload for page in request.product_pages],
        visible_total_quantity=request.visible_total_quantity,
        condition_names=condition_names,
        grade_details=grade_details,
    )
    source = CollectrBrowserSource(lambda: capture)
    collection = source.load_collection()
    diagnostics = source.diagnostics()
    snapshot = source.create_snapshot()
    SnapshotRepository(create_database(database_path)).add(snapshot)
    return CompanionCaptureResult(
        snapshot_id=snapshot.snapshot_id,
        completeness=collection.completeness.value,
        unique_entries=len(collection.entries),
        total_quantity=collection.total_quantity,
        pagination_complete=diagnostics.pagination_complete,
        invalid_record_count=diagnostics.invalid_record_count,
        skipped_watchlist_count=diagnostics.skipped_watchlist_count,
        skipped_non_card_count=diagnostics.skipped_non_card_count,
        warnings=diagnostics.warnings,
    )


class CompanionServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        token: str,
        database_path: Path,
    ) -> None:
        self.token = token
        self.database_path = database_path
        super().__init__(address, CompanionRequestHandler)


class CompanionRequestHandler(BaseHTTPRequestHandler):
    server: CompanionServer
    server_version = "CardRelayCompanion"
    sys_version = ""

    def do_GET(self) -> None:
        if self.path != "/v1/health":
            self._write_json(404, {"error": "not_found"})
            return
        if not self._loopback_host_header():
            self._write_json(400, {"error": "invalid_host"})
            return
        self._write_json(
            200,
            {
                "service": "card-relay-extension-companion",
                "capture_contract": "collectr-extension-v1",
                "destination_writes_enabled": False,
            },
        )

    def do_POST(self) -> None:
        if self.path != "/v1/collectr/captures":
            self._write_json(404, {"error": "not_found"})
            return
        if not self._loopback_host_header():
            self._write_json(400, {"error": "invalid_host"})
            return
        if not self._authenticated():
            self._write_json(401, {"error": "unauthorized"})
            return
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().casefold()
        if content_type != "application/json":
            self._write_json(415, {"error": "json_required"})
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._write_json(400, {"error": "invalid_content_length"})
            return
        if content_length <= 0 or content_length > MAX_CAPTURE_BYTES:
            self._write_json(413, {"error": "capture_too_large"})
            return
        try:
            body = self.rfile.read(content_length)
            payload = json.loads(body)
            result = process_collectr_capture(payload, self.server.database_path)
        except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, SourceValidationError):
            self._write_json(400, {"error": "invalid_capture"})
            return
        except CardRelayError:
            self._write_json(422, {"error": "capture_rejected"})
            return
        self._write_json(201, result.model_dump(mode="json"))

    def log_message(self, format: str, *args: Any) -> None:
        # Request paths are fixed and capture data is private; default access logs add no value.
        return

    def _authenticated(self) -> bool:
        authorization = self.headers.get("Authorization", "")
        prefix = "Bearer "
        return authorization.startswith(prefix) and hmac.compare_digest(
            authorization[len(prefix) :], self.server.token
        )

    def _loopback_host_header(self) -> bool:
        host = self.headers.get("Host", "").rsplit(":", 1)[0].strip("[]").casefold()
        return host in {"127.0.0.1", "localhost", "::1"}

    def _write_json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)


def serve_companion(
    database_path: Path,
    port: int = 8765,
    token_factory: Callable[[], str] | None = None,
) -> tuple[CompanionServer, str]:
    token = (token_factory or (lambda: secrets.token_urlsafe(32)))()
    server = CompanionServer(("127.0.0.1", port), token, database_path)
    return server, token
