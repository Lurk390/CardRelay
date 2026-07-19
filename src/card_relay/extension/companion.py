import hmac
import json
import re
import secrets
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from card_relay.destinations.capabilities import DestinationCapabilities
from card_relay.destinations.dex.models import (
    DexCapturedCatalogPage,
    DexCapturedCollectionPage,
    DexWriteMetadata,
)
from card_relay.destinations.dex.normalizer import (
    build_dex_write_metadata,
    normalize_dex_catalog,
    normalize_dex_collection,
)
from card_relay.domain.enums import MatchStatus, OperationType
from card_relay.domain.models import CanonicalCardIdentity, DestinationReadSnapshot
from card_relay.domain.operations import OperationResult, SyncPlan, SyncResult
from card_relay.domain.results import MatchResult
from card_relay.exceptions import CardRelayError, SourceValidationError
from card_relay.matching import match_collection
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
    ManagedDestinationRepository,
    MappingRepository,
    MappingReviewRepository,
    SnapshotRepository,
    SourceCollectionRepository,
    SyncAuditRepository,
)
from card_relay.sync.planner import build_plan
from card_relay.sync.policy import SyncPolicy
from card_relay.sync.preview import SyncPreviewChange, preview_changes

MAX_CAPTURE_BYTES = 16 * 1024 * 1024
PRODUCT_PAGE_SIZE = 30


class SyncPreviewUnavailable(CardRelayError):
    pass


class MappingDecisionUnavailable(CardRelayError):
    pass


class SafeWriteUnavailable(CardRelayError):
    pass


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
    collection_fingerprint: str = Field(min_length=16, max_length=128)
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


class DexJsonShape(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal[
        "object",
        "array",
        "string",
        "integer",
        "number",
        "boolean",
        "null",
        "truncated",
        "unsupported",
    ]
    format: Literal["uuid", "url", "opaque", "text"] | None = None
    fields: dict[str, "DexJsonShape"] = Field(default_factory=dict, max_length=50)
    items: list["DexJsonShape"] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def shape_is_structural_only(self) -> "DexJsonShape":
        if any(
            not key
            or len(key) > 64
            or re.fullmatch(r"(?:[A-Za-z][A-Za-z0-9_-]*|\{dynamic_key\})", key) is None
            for key in self.fields
        ):
            raise ValueError("shape property names must be bounded identifiers")
        if self.kind != "object" and self.fields:
            raise ValueError("only object shapes may contain fields")
        if self.kind != "array" and self.items:
            raise ValueError("only array shapes may contain items")
        if self.kind != "string" and self.format is not None:
            raise ValueError("only string shapes may contain a format")
        return self


DexObservationKey = Annotated[
    str,
    Field(min_length=1, max_length=64, pattern=r"^(?:[A-Za-z][A-Za-z0-9_-]*|\{dynamic_key\})$"),
]


class DexWritePathBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_index: int = Field(ge=0, le=20)
    source: str = Field(
        min_length=9,
        max_length=400,
        pattern=r"^(?:request|response)(?:\.[A-Za-z][A-Za-z0-9_-]{0,63}){1,6}$",
    )


class DexWriteObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: Literal["POST", "PUT", "PATCH", "DELETE"]
    origin_host: str = Field(
        min_length=10,
        max_length=253,
        pattern=r"^(?:[a-z0-9-]+\.)*dextcg\.com$",
    )
    route_template: str = Field(
        min_length=1,
        max_length=512,
        pattern=r"^/(?:[a-z0-9_-]+|\{segment\})(?:/(?:[a-z0-9_-]+|\{segment\}))*$",
    )
    query_keys: list[DexObservationKey] = Field(default_factory=list, max_length=50)
    path_parameter_bindings: list[DexWritePathBinding] = Field(default_factory=list, max_length=20)
    request_shape: DexJsonShape
    response_status: int = Field(ge=100, le=599)
    response_shape: DexJsonShape | None = None

    @model_validator(mode="after")
    def path_bindings_target_redacted_segments(self) -> "DexWriteObservation":
        segments = self.route_template.removeprefix("/").split("/")
        for binding in self.path_parameter_bindings:
            if (
                binding.segment_index >= len(segments)
                or segments[binding.segment_index] != "{segment}"
            ):
                raise ValueError("path bindings must target redacted route segments")
        return self


class DexWriteObservationCapture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["dex-write-observation-v1"]
    observations: list[DexWriteObservation] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def observations_are_bounded(self) -> "DexWriteObservationCapture":
        nodes = 0

        def visit(shape: DexJsonShape, depth: int = 0) -> None:
            nonlocal nodes
            if depth > 6:
                raise ValueError("write observation shape exceeds the depth limit")
            nodes += 1
            if nodes > 2000:
                raise ValueError("write observation shape exceeds the node limit")
            for child in shape.fields.values():
                visit(child, depth + 1)
            for child in shape.items:
                visit(child, depth + 1)

        for observation in self.observations:
            visit(observation.request_shape)
            if observation.response_shape is not None:
                visit(observation.response_shape)
        return self


class DexWriteObservationResult(BaseModel):
    observations: list[DexWriteObservation]
    observation_count: int
    destination_writes_enabled: Literal[False] = False
    warning: str = "Schema-only research does not authorize or implement Dex writes."


class CompanionMappingCandidate(BaseModel):
    destination_id: str
    identity: CanonicalCardIdentity
    score: float = Field(ge=0, le=1)
    reasons: list[str]
    matched_fields: list[str]
    mismatched_fields: list[str]


class CompanionMappingReview(BaseModel):
    source_fingerprint: str
    source_identity: CanonicalCardIdentity
    status: MatchStatus
    reasons: list[str]
    candidates: list[CompanionMappingCandidate]


class MappingDecisionRequest(BaseModel):
    action: Literal["confirm", "reject"]
    source_fingerprint: str = Field(
        min_length=10,
        max_length=100,
        pattern=r"^[A-Za-z0-9]+:[a-f0-9]{64}$",
    )
    destination_id: str = Field(min_length=1, max_length=512)


class CompanionSyncPreviewResult(BaseModel):
    destination: Literal["dex"] = "dex"
    source_completeness: str
    changes: list[SyncPreviewChange]
    change_counts: dict[str, int]
    blocked_changes: int
    truncated: bool
    destructive_confirmation_code: None = None
    destination_writes_enabled: bool
    safe_write_confirmation_code: str | None
    safe_write_operation_ids: list[str]
    safe_write_count: int
    safe_write_block_reason: str | None
    mapping_reviews: list[CompanionMappingReview]
    mapping_review_count: int
    mapping_reviews_truncated: bool
    warnings: list[str]


class DexSafeWriteBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    card_id: str = Field(alias="cardId", min_length=1, max_length=256)
    quantities: dict[str, int] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def quantities_are_safe(self) -> "DexSafeWriteBody":
        if any(
            not key
            or len(key) > 64
            or re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", key) is None
            or type(value) is not int
            or value < 0
            or value > 1_000_000
            for key, value in self.quantities.items()
        ):
            raise ValueError("Dex quantities must use bounded keys and non-negative integers")
        return self


class DexSafeWriteCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: str = Field(min_length=10, max_length=100)
    method: Literal["POST", "PATCH"]
    origin: Literal["https://clients.dextcg.com"] = "https://clients.dextcg.com"
    path: str = Field(min_length=15, max_length=512)
    body: DexSafeWriteBody

    @model_validator(mode="after")
    def route_matches_method(self) -> "DexSafeWriteCommand":
        if self.method == "POST" and self.path != "/api/user/cards":
            raise ValueError("Dex additions must use the verified collection route")
        if (
            self.method == "PATCH"
            and re.fullmatch(r"/api/user/cards/[A-Za-z0-9_-]{1,256}", self.path) is None
        ):
            raise ValueError("Dex quantity updates require a safe collection record ID")
        return self


class DexSafeWritePrepareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation_code: str = Field(min_length=12, max_length=12, pattern=r"^[A-F0-9]{12}$")
    operation_ids: list[str] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def operation_ids_are_unique(self) -> "DexSafeWritePrepareRequest":
        if len(self.operation_ids) != len(set(self.operation_ids)):
            raise ValueError("operation IDs must be unique")
        return self


class DexSafeWriteBatch(BaseModel):
    contract_version: Literal["dex-safe-write-batch-v1"] = "dex-safe-write-batch-v1"
    plan_id: int = Field(gt=0)
    confirmation_code: str
    commands: list[DexSafeWriteCommand] = Field(min_length=1, max_length=50)
    recapture_required_after_attempt: Literal[True] = True


class DexSafeWriteExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: str = Field(min_length=10, max_length=100)
    succeeded: bool
    outcome: Literal[
        "succeeded",
        "http_error",
        "network_error",
        "uncertain_addition",
        "invalid_response",
    ]
    status: int | None = Field(default=None, ge=100, le=599)
    attempts: int = Field(ge=1, le=3)


class DexSafeWriteReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["dex-safe-write-report-v1"]
    plan_id: int = Field(gt=0)
    confirmation_code: str = Field(min_length=12, max_length=12, pattern=r"^[A-F0-9]{12}$")
    results: list[DexSafeWriteExecutionResult] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def result_ids_are_unique(self) -> "DexSafeWriteReportRequest":
        ids = [result.operation_id for result in self.results]
        if len(ids) != len(set(ids)):
            raise ValueError("operation result IDs must be unique")
        return self


class DexSafeWriteReportResult(BaseModel):
    plan_id: int
    succeeded: int
    failed: int
    fully_succeeded: bool
    recapture_required: Literal[True] = True


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
    engine = create_database(database_path)
    SnapshotRepository(engine).add(snapshot)
    SourceCollectionRepository(engine).add(snapshot, collection)
    return CompanionCaptureResult(
        snapshot_id=snapshot.snapshot_id,
        collection_fingerprint=snapshot.collection_fingerprint,
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
    write_metadata = build_dex_write_metadata(catalog_cards, collection_entries)
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
            "write_metadata": write_metadata.model_dump(mode="json"),
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


def process_dex_write_observations(payload: object) -> DexWriteObservationResult:
    request = DexWriteObservationCapture.model_validate(payload)
    return DexWriteObservationResult(
        observations=request.observations,
        observation_count=len(request.observations),
    )


def _build_dex_sync_plan(database_path: Path) -> tuple[SyncPlan, DestinationReadSnapshot]:
    engine = create_database(database_path)
    source = SourceCollectionRepository(engine).latest()
    destination = DestinationReadRepository(engine).get("dex")
    if source is None:
        raise SyncPreviewUnavailable("collectr_capture_required")
    if destination is None:
        raise SyncPreviewUnavailable("dex_capture_required")
    mappings = MappingRepository(engine)
    matches = match_collection(
        source,
        destination.catalog,
        mappings.list_confirmed("dex"),
        mappings.list_rejected("dex"),
    )
    review_repository = MappingReviewRepository(engine)
    review_repository.update("dex", source, matches)
    plan = build_plan(
        source,
        destination.collection,
        matches,
        DestinationCapabilities(
            supported_games=frozenset({"pokemon"}),
            additions=True,
            quantity_increases=True,
        ),
        SyncPolicy(),
        "dex",
        destructive_planning_allowed=False,
        managed_destination_ids=ManagedDestinationRepository(engine).list_ids("dex"),
    )
    if not destination.complete:
        plan.warnings.append("Dex normalization is incomplete; destructive writes remain blocked")
    return plan, destination


def _safe_write_commands(
    plan: SyncPlan,
    destination: DestinationReadSnapshot,
) -> list[DexSafeWriteCommand]:
    metadata = DexWriteMetadata.model_validate(destination.metadata.get("write_metadata"))
    commands: list[DexSafeWriteCommand] = []
    for operation in plan.safe_write_operations:
        destination_id = operation.destination_id
        if destination_id is None:
            raise SafeWriteUnavailable("safe_write_missing_destination_id")
        if destination_id in metadata.ambiguous_destination_ids:
            raise SafeWriteUnavailable("safe_write_ambiguous_quantity_key")
        quantity_key = metadata.quantity_keys.get(destination_id)
        if quantity_key is None:
            raise SafeWriteUnavailable("safe_write_quantity_key_unavailable")
        card_id, separator, _finish = destination_id.partition("::")
        if not separator or not card_id:
            raise SafeWriteUnavailable("safe_write_invalid_destination_id")
        existing = metadata.collection_records.get(card_id)
        if existing is None:
            commands.append(
                DexSafeWriteCommand(
                    operation_id=operation.operation_id,
                    method="POST",
                    path="/api/user/cards",
                    body=DexSafeWriteBody(
                        cardId=card_id,
                        quantities={quantity_key: operation.desired_quantity},
                    ),
                )
            )
            continue
        quantities = dict(existing.quantities)
        quantities[quantity_key] = operation.desired_quantity
        commands.append(
            DexSafeWriteCommand(
                operation_id=operation.operation_id,
                method="PATCH",
                path=f"/api/user/cards/{existing.record_id}",
                body=DexSafeWriteBody(cardId=card_id, quantities=quantities),
            )
        )
    return commands


def _safe_write_preview(
    plan: SyncPlan,
    destination: DestinationReadSnapshot,
    audit: SyncAuditRepository,
) -> tuple[list[DexSafeWriteCommand], str | None]:
    if len(plan.safe_write_operations) > 50:
        return [], "safe_write_batch_limit_exceeded"
    if audit.has_write_attempt_for_state("dex", plan.destination_collection_fingerprint):
        return [], "dex_recapture_required_after_write_attempt"
    try:
        return _safe_write_commands(plan, destination), None
    except (SafeWriteUnavailable, ValidationError):
        return [], "safe_write_metadata_unavailable"


def process_sync_preview(database_path: Path) -> CompanionSyncPreviewResult:
    engine = create_database(database_path)
    plan, destination = _build_dex_sync_plan(database_path)
    changes = preview_changes(plan)
    maximum_changes = 2000
    counts = {kind.value: 0 for kind in OperationType}
    for change in changes:
        counts[change.change] += 1
    pending_reviews = MappingReviewRepository(engine).list_pending("dex")
    maximum_reviews = 500
    safe_commands, safe_write_block_reason = _safe_write_preview(
        plan,
        destination,
        SyncAuditRepository(engine),
    )
    return CompanionSyncPreviewResult(
        source_completeness=plan.source_completeness.value,
        changes=changes[:maximum_changes],
        change_counts=counts,
        blocked_changes=sum(
            change.change != OperationType.NO_CHANGE.value and not change.executable
            for change in changes
        ),
        truncated=len(changes) > maximum_changes,
        destination_writes_enabled=bool(safe_commands),
        safe_write_confirmation_code=plan.confirmation_code if safe_commands else None,
        safe_write_operation_ids=[command.operation_id for command in safe_commands],
        safe_write_count=len(safe_commands),
        safe_write_block_reason=safe_write_block_reason,
        mapping_reviews=[
            _companion_mapping_review(item) for item in pending_reviews[:maximum_reviews]
        ],
        mapping_review_count=len(pending_reviews),
        mapping_reviews_truncated=len(pending_reviews) > maximum_reviews,
        warnings=plan.warnings,
    )


def process_safe_write_prepare(
    payload: object,
    database_path: Path,
) -> DexSafeWriteBatch:
    request = DexSafeWritePrepareRequest.model_validate(payload)
    engine = create_database(database_path)
    plan, destination = _build_dex_sync_plan(database_path)
    audit = SyncAuditRepository(engine)
    commands, block_reason = _safe_write_preview(plan, destination, audit)
    if block_reason is not None or not commands:
        raise SafeWriteUnavailable(block_reason or "safe_write_unavailable")
    if request.confirmation_code != plan.confirmation_code:
        raise SafeWriteUnavailable("safe_write_confirmation_mismatch")
    command_ids = [command.operation_id for command in commands]
    if request.operation_ids != command_ids:
        raise SafeWriteUnavailable("safe_write_operations_changed")
    plan_id = audit.add_plan(plan)
    audit.add_run(
        plan_id,
        SyncResult(
            dry_run=False,
            results=[
                OperationResult(
                    operation_id=command.operation_id,
                    succeeded=False,
                    message="safe write batch prepared; execution report pending",
                )
                for command in commands
            ],
        ),
    )
    return DexSafeWriteBatch(
        plan_id=plan_id,
        confirmation_code=plan.confirmation_code,
        commands=commands,
    )


def process_safe_write_report(
    payload: object,
    database_path: Path,
) -> DexSafeWriteReportResult:
    request = DexSafeWriteReportRequest.model_validate(payload)
    engine = create_database(database_path)
    audit = SyncAuditRepository(engine)
    plan = audit.get_plan(request.plan_id)
    if plan.destination != "dex" or request.confirmation_code != plan.confirmation_code:
        raise SafeWriteUnavailable("safe_write_report_not_authorized")
    expected_ids = [operation.operation_id for operation in plan.safe_write_operations]
    reported_ids = [item.operation_id for item in request.results]
    if reported_ids != expected_ids:
        raise SafeWriteUnavailable("safe_write_report_operations_changed")
    result = SyncResult(
        dry_run=False,
        results=[
            OperationResult(
                operation_id=item.operation_id,
                succeeded=item.succeeded,
                message=item.outcome,
            )
            for item in request.results
        ],
    )
    audit.add_run(request.plan_id, result)
    ManagedDestinationRepository(engine).reconcile_successful_run(plan, result)
    succeeded = sum(item.succeeded for item in request.results)
    return DexSafeWriteReportResult(
        plan_id=request.plan_id,
        succeeded=succeeded,
        failed=len(request.results) - succeeded,
        fully_succeeded=result.succeeded,
    )


def process_mapping_decision(
    payload: object,
    database_path: Path,
) -> CompanionSyncPreviewResult:
    request = MappingDecisionRequest.model_validate(payload)
    # Rebuild first so a decision can only target a candidate offered by the latest
    # source and destination snapshots, never a stale popup or arbitrary ID.
    process_sync_preview(database_path)
    engine = create_database(database_path)
    pending = MappingReviewRepository(engine).list_pending("dex")
    review = next(
        (item for item in pending if item["source_fingerprint"] == request.source_fingerprint),
        None,
    )
    if review is None:
        raise MappingDecisionUnavailable("mapping_review_stale")
    match = MatchResult.model_validate(review["match"])
    if request.destination_id not in match.candidate_ids:
        raise MappingDecisionUnavailable("mapping_candidate_not_offered")
    mappings = MappingRepository(engine)
    if request.action == "confirm":
        mappings.confirm(request.source_fingerprint, "dex", request.destination_id)
    else:
        mappings.reject(request.source_fingerprint, "dex", request.destination_id)
    return process_sync_preview(database_path)


def _companion_mapping_review(item: dict[str, object]) -> CompanionMappingReview:
    match = MatchResult.model_validate(item["match"])
    offered_ids = set(match.candidate_ids)
    candidates = sorted(
        (
            CompanionMappingCandidate(
                destination_id=alternative.candidate.destination_id,
                identity=alternative.candidate.identity,
                score=alternative.score,
                reasons=alternative.reasons,
                matched_fields=alternative.matched_fields,
                mismatched_fields=alternative.mismatched_fields,
            )
            for alternative in match.alternatives
            if alternative.candidate.destination_id in offered_ids
        ),
        key=lambda candidate: (-candidate.score, candidate.destination_id),
    )
    return CompanionMappingReview(
        source_fingerprint=str(item["source_fingerprint"]),
        source_identity=CanonicalCardIdentity.model_validate(item["source_identity"]),
        status=match.status,
        reasons=match.reasons,
        candidates=candidates,
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
                "capture_contracts": [
                    "collectr-extension-v1",
                    "dex-extension-v1",
                    "dex-write-observation-v1",
                    "dex-safe-write-batch-v1",
                ],
                "destination_writes_enabled": True,
            },
        )

    def do_POST(self) -> None:
        if self.path not in {
            "/v1/collectr/captures",
            "/v1/dex/captures",
            "/v1/dex/capture-chunks",
            "/v1/dex/write-observations",
            "/v1/dex/safe-write-batches",
            "/v1/dex/safe-write-reports",
            "/v1/sync/previews",
            "/v1/mappings/decisions",
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
            elif self.path == "/v1/dex/write-observations":
                result = process_dex_write_observations(payload)
            elif self.path == "/v1/dex/safe-write-batches":
                result = process_safe_write_prepare(payload, self.server.database_path)
            elif self.path == "/v1/dex/safe-write-reports":
                result = process_safe_write_report(payload, self.server.database_path)
            elif self.path == "/v1/sync/previews":
                result = process_sync_preview(self.server.database_path)
            elif self.path == "/v1/mappings/decisions":
                result = process_mapping_decision(payload, self.server.database_path)
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
        except SyncPreviewUnavailable as error:
            self._write_json(
                409,
                {"error": "preview_unavailable", "reason": str(error)},
            )
            return
        except MappingDecisionUnavailable as error:
            self._write_json(
                409,
                {"error": "mapping_decision_rejected", "reason": str(error)},
            )
            return
        except SafeWriteUnavailable as error:
            self._write_json(
                409,
                {"error": "safe_write_rejected", "reason": str(error)},
            )
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
