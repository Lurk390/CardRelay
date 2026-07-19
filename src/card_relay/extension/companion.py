import hmac
import json
import secrets
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

from card_relay.destinations.dex.models import (
    DexCapturedCatalogPage,
    DexCapturedCollectionPage,
)
from card_relay.destinations.dex.normalizer import (
    normalize_dex_catalog,
    normalize_dex_collection,
)
from card_relay.domain.models import DestinationReadSnapshot
from card_relay.exceptions import CardRelayError, SourceValidationError
from card_relay.sources.collectr.browser_capture import (
    extract_condition_names,
    extract_grade_details,
)
from card_relay.sources.collectr.browser_source import CollectrBrowserSource
from card_relay.sources.collectr.parsers.browser_fixture_parser import BrowserInvalidRecordCounts
from card_relay.sources.collectr.parsers.collectr_web_contract import (
    BrowserGradeDetails,
    build_capture_from_collectr_responses,
)
from card_relay.storage.database import create_database
from card_relay.storage.repositories import (
    CatalogCacheRepository,
    DestinationReadRepository,
    SnapshotRepository,
)

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
    invalid_record_reasons: BrowserInvalidRecordCounts
    skipped_watchlist_count: int
    skipped_non_card_count: int
    trusted_for_destructive_planning: Literal[False] = False
    destination_writes_enabled: Literal[False] = False
    warnings: list[str]


class DexExtensionCapture(BaseModel):
    """Minimal, URL-free Dex data emitted by the approved extension boundary."""

    contract_version: Literal["dex-extension-v1"]
    collection_pages: list[DexCapturedCollectionPage] = Field(min_length=1, max_length=1000)
    catalog_pages: list[DexCapturedCatalogPage] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def pagination_is_complete(self) -> "DexExtensionCapture":
        _validate_complete_pages(self.collection_pages, "collection")
        _validate_complete_pages(self.catalog_pages, "catalog")
        return self


class DexExtensionCaptureChunk(BaseModel):
    contract_version: Literal["dex-extension-chunk-v1"]
    upload_id: str = Field(min_length=16, max_length=64, pattern=r"^[A-Za-z0-9-]+$")
    chunk_index: int = Field(ge=0, lt=1000)
    chunk_count: int = Field(gt=0, le=1000)
    collection_pages: list[DexCapturedCollectionPage] = Field(default_factory=list, max_length=1000)
    catalog_pages: list[DexCapturedCatalogPage] = Field(default_factory=list, max_length=10)


class DexChunkAccepted(BaseModel):
    upload_complete: Literal[False] = False
    next_chunk_index: int
    destination_writes_enabled: Literal[False] = False


@dataclass
class DexUploadState:
    chunk_count: int
    next_chunk_index: int = 0
    received_bytes: int = 0
    collection_pages: list[DexCapturedCollectionPage] = field(default_factory=list)
    catalog_pages: list[DexCapturedCatalogPage] = field(default_factory=list)


class DexCompanionCaptureResult(BaseModel):
    catalog_records: int
    collection_records: int
    total_quantity: int
    pagination_complete: Literal[True] = True
    normalization_complete: bool
    unsupported_catalog_variants: list[str]
    unsupported_collection_quantities: list[str]
    destination_writes_enabled: Literal[False] = False


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
        invalid_record_reasons=diagnostics.invalid_record_reasons,
        skipped_watchlist_count=diagnostics.skipped_watchlist_count,
        skipped_non_card_count=diagnostics.skipped_non_card_count,
        warnings=diagnostics.warnings,
    )


def process_dex_capture(payload: object, database_path: Path) -> DexCompanionCaptureResult:
    request = DexExtensionCapture.model_validate(payload)
    catalog_cards = [card for page in request.catalog_pages for card in page.result]
    collection_entries = [entry for page in request.collection_pages for entry in page.result]
    catalog, unsupported_catalog = normalize_dex_catalog(catalog_cards)
    collection, unsupported_collection = normalize_dex_collection(collection_entries)
    normalization_complete = not unsupported_catalog and not unsupported_collection
    engine = create_database(database_path)
    snapshot = DestinationReadSnapshot(
        destination_name="dex",
        catalog=catalog,
        collection=collection,
        complete=normalization_complete,
        metadata={
            "capture_contract": request.contract_version,
            "catalog_pages": len(request.catalog_pages),
            "collection_pages": len(request.collection_pages),
            "unsupported_catalog_variants": unsupported_catalog,
            "unsupported_collection_quantities": unsupported_collection,
            "destination_writes_enabled": False,
        },
    )
    DestinationReadRepository(engine).replace(snapshot)
    CatalogCacheRepository(engine).replace("dex", catalog)
    return DexCompanionCaptureResult(
        catalog_records=len(catalog),
        collection_records=len(collection),
        total_quantity=sum(entry.quantity for entry in collection),
        normalization_complete=normalization_complete,
        unsupported_catalog_variants=unsupported_catalog,
        unsupported_collection_quantities=unsupported_collection,
    )


def process_dex_capture_chunk(
    payload: object,
    database_path: Path,
    uploads: dict[str, DexUploadState],
    content_length: int,
) -> DexChunkAccepted | DexCompanionCaptureResult:
    request = DexExtensionCaptureChunk.model_validate(payload)
    state = uploads.get(request.upload_id)
    if state is None:
        if request.chunk_index != 0 or not request.collection_pages:
            raise ValueError("first Dex chunk must include the collection")
        state = DexUploadState(chunk_count=request.chunk_count)
        uploads[request.upload_id] = state
    if request.chunk_count != state.chunk_count or request.chunk_index != state.next_chunk_index:
        uploads.pop(request.upload_id, None)
        raise ValueError("Dex chunks must be contiguous and share a chunk count")
    if request.chunk_index > 0 and request.collection_pages:
        uploads.pop(request.upload_id, None)
        raise ValueError("only the first Dex chunk may include collection pages")
    state.received_bytes += content_length
    if state.received_bytes > MAX_CAPTURE_BYTES:
        uploads.pop(request.upload_id, None)
        raise ValueError("Dex chunked capture exceeds the total size limit")
    state.collection_pages.extend(request.collection_pages)
    state.catalog_pages.extend(request.catalog_pages)
    state.next_chunk_index += 1
    if state.next_chunk_index < state.chunk_count:
        return DexChunkAccepted(next_chunk_index=state.next_chunk_index)
    uploads.pop(request.upload_id, None)
    return process_dex_capture(
        DexExtensionCapture(
            contract_version="dex-extension-v1",
            collection_pages=state.collection_pages,
            catalog_pages=state.catalog_pages,
        ),
        database_path,
    )


def _validate_complete_pages(
    pages: Sequence[DexCapturedCollectionPage | DexCapturedCatalogPage], label: str
) -> None:
    numbered = sorted(pages, key=lambda item: item.page)
    first = numbered[0]
    total_pages = first.total_pages
    total_items = first.total_items
    if len(numbered) != total_pages:
        raise ValueError(f"Dex {label} capture must contain every page")
    for index, page in enumerate(numbered, start=1):
        if page.page != index:
            raise ValueError(f"Dex {label} pages must be contiguous from one")
        if page.total_pages != total_pages or page.total_items != total_items:
            raise ValueError(f"Dex {label} pagination metadata must be consistent")
    captured_items = sum(len(page.result) for page in numbered)
    if captured_items != total_items:
        raise ValueError(f"Dex {label} captured item count must equal totalItems")


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
        self.dex_uploads: dict[str, DexUploadState] = {}
        self.dex_upload_lock = threading.Lock()
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
                "capture_contracts": ["collectr-extension-v1", "dex-extension-v1"],
                "destination_writes_enabled": False,
            },
        )

    def do_POST(self) -> None:
        if self.path not in {
            "/v1/collectr/captures",
            "/v1/dex/captures",
            "/v1/dex/capture-chunks",
        }:
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
            result: BaseModel
            if self.path == "/v1/dex/capture-chunks":
                with self.server.dex_upload_lock:
                    result = process_dex_capture_chunk(
                        payload,
                        self.server.database_path,
                        self.server.dex_uploads,
                        content_length,
                    )
            elif self.path == "/v1/dex/captures":
                result = process_dex_capture(payload, self.server.database_path)
            else:
                result = process_collectr_capture(payload, self.server.database_path)
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._write_json(400, {"error": "invalid_capture_json"})
            return
        except ValidationError as error:
            issues = [
                {
                    "location": ".".join(str(part) for part in issue["loc"]),
                    "type": issue["type"],
                }
                for issue in error.errors(include_input=False, include_url=False)
            ]
            self._write_json(
                400,
                {"error": "invalid_capture_contract", "issues": issues[:20]},
            )
            return
        except ValueError:
            self._write_json(
                400,
                {
                    "error": "invalid_capture_contract",
                    "reason": "capture_consistency_validation_failed",
                },
            )
            return
        except SourceValidationError:
            self._write_json(400, {"error": "invalid_capture_source"})
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
