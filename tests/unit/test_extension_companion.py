import http.client
import json
import threading
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from card_relay.domain.enums import ExtractionCompleteness, IngestionMethod
from card_relay.domain.models import CanonicalCollection, SourceSnapshot, collection_fingerprint
from card_relay.extension.companion import (
    CollectrExtensionCapture,
    CompanionSafetyOptions,
    DexWriteObservationCapture,
    MappingDecisionUnavailable,
    RemovalTestUnavailable,
    SafeWriteUnavailable,
    SyncPreviewUnavailable,
    process_collectr_backup_status,
    process_collectr_capture,
    process_dex_backup_status,
    process_dex_capture,
    process_dex_write_observations,
    process_mapping_decision,
    process_mapping_decisions,
    process_removal_prepare,
    process_removal_report,
    process_safe_write_prepare,
    process_safe_write_report,
    process_sync_preview,
    serve_companion,
)
from card_relay.storage.database import create_database
from card_relay.storage.models import DestinationCaptureSnapshotRow, SnapshotRow
from card_relay.storage.repositories import (
    DestinationBackupRepository,
    ManagedDestinationRepository,
    MappingRepository,
    SourceCollectionRepository,
)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "collectr"
DEX_FIXTURE = Path(__file__).parents[1] / "fixtures" / "dex" / "extension_capture.json"
EXTENSION = Path(__file__).parents[2] / "extension"


def _payload() -> dict[str, object]:
    pages = json.loads((FIXTURES / "web_products_pages.json").read_text(encoding="utf-8"))
    return {
        "contract_version": "collectr-extension-v1",
        "product_pages": [
            {"offset": offset, "payload": page}
            for offset, page in zip((0, 30, 60), pages, strict=True)
        ],
        "visible_total_quantity": 4,
        "condition_payloads": [{"scale": [{"id": 1, "display_name": "Near Mint"}]}],
        "grading_payloads": [
            {"data": [{"company": "CGC", "grades": [{"id": 10, "grade": "10.0"}]}]}
        ],
        "exact_view_verified": True,
    }


def _reviewable_dex_payload() -> dict[str, object]:
    payload = json.loads(DEX_FIXTURE.read_text(encoding="utf-8"))
    payload["collection_pages"][0]["result"][0]["card"]["name"] = "Fixturemo"
    payload["catalog_pages"][0]["result"][0]["name"] = "Fixturemo"
    return payload


def _write_observation_payload() -> dict[str, object]:
    return {
        "contract_version": "dex-write-observation-v1",
        "observations": [
            {
                "method": "PATCH",
                "origin_host": "api.dextcg.com",
                "route_template": "/api/collections/{segment}/cards/{segment}",
                "query_keys": ["account"],
                "path_parameter_bindings": [{"segment_index": 4, "source": "request.cardId"}],
                "request_shape": {
                    "kind": "object",
                    "fields": {
                        "cardId": {"kind": "string", "format": "uuid"},
                        "quantities": {
                            "kind": "object",
                            "fields": {"reverse_holo": {"kind": "integer"}},
                        },
                    },
                },
                "response_status": 200,
                "response_shape": {
                    "kind": "object",
                    "fields": {"updated": {"kind": "boolean"}},
                },
            }
        ],
    }


def test_extension_capture_reuses_browser_normalization_and_stores_snapshot(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "card-relay.db"

    result = process_collectr_capture(_payload(), database_path)

    assert result.completeness == "complete"
    assert result.unique_entries == 2
    assert result.total_quantity == 3
    assert result.filtered_non_pokemon_count == 1
    assert len(result.collection_fingerprint) >= 16
    assert result.pagination_complete
    assert result.skipped_non_card_count == 1
    assert result.invalid_record_reasons.total == 0
    assert result.trusted_for_destructive_planning is False
    assert result.destination_writes_enabled is False
    with Session(create_database(database_path)) as session:
        row = session.scalar(select(SnapshotRow))
        assert row is not None
        serialized = json.dumps(row.metadata_json)
        assert "Fixturemon" not in serialized
        assert "fictional-holding" not in serialized
    saved = SourceCollectionRepository(create_database(database_path)).latest()
    assert saved is not None
    assert {entry.identity.game for entry in saved.entries} == {"pokemon"}


def test_collectr_captures_are_timestamped_reusable_backups(tmp_path: Path) -> None:
    database_path = tmp_path / "card-relay.db"

    first = process_collectr_capture(_payload(), database_path)
    first_status = process_collectr_backup_status(database_path)

    assert first_status.backup_count == 1
    assert first_status.latest is not None
    assert first_status.latest.snapshot_id == first.snapshot_id
    assert first_status.latest.captured_at == first.captured_at
    assert first_status.latest.unique_entries == 2
    assert first_status.latest.total_quantity == 3

    second = process_collectr_capture(_payload(), database_path)
    second_status = process_collectr_backup_status(database_path)

    assert second_status.backup_count == 2
    assert second_status.latest is not None
    assert second_status.latest.snapshot_id == second.snapshot_id


def test_dex_captures_are_timestamped_reusable_backups(tmp_path: Path) -> None:
    database_path = tmp_path / "card-relay.db"
    payload = json.loads(DEX_FIXTURE.read_text(encoding="utf-8"))

    first = process_dex_capture(payload, database_path)
    first_status = process_dex_backup_status(database_path)

    assert first_status.backup_count == 1
    assert first_status.latest is not None
    assert first_status.latest.snapshot_id == first.snapshot_id
    assert first_status.latest.captured_at == first.captured_at
    assert first_status.latest.unique_entries == 1
    assert first_status.latest.total_quantity == first.total_quantity

    second = process_dex_capture(payload, database_path)
    second_status = process_dex_backup_status(database_path)

    assert second_status.backup_count == 2
    assert second_status.latest is not None
    assert second_status.latest.snapshot_id == second.snapshot_id


def test_dex_backup_status_preserves_a_legacy_latest_snapshot(tmp_path: Path) -> None:
    database_path = tmp_path / "card-relay.db"
    payload = json.loads(DEX_FIXTURE.read_text(encoding="utf-8"))
    captured = process_dex_capture(payload, database_path)
    with Session(create_database(database_path)) as session:
        session.execute(delete(DestinationCaptureSnapshotRow))
        session.commit()

    status = process_dex_backup_status(database_path)

    assert status.backup_count == 1
    assert status.latest is not None
    assert status.latest.captured_at == captured.captured_at
    assert status.latest.total_quantity == captured.total_quantity


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("exact_view_verified", False, "aggregate portfolio"),
        (
            "product_pages",
            [{"offset": 30, "payload": {"data": []}}],
            "contiguous",
        ),
    ],
)
def test_extension_capture_rejects_unsafe_capture_shapes(
    field: str, value: object, message: str
) -> None:
    payload = _payload()
    payload[field] = value

    with pytest.raises(ValidationError, match=message):
        CollectrExtensionCapture.model_validate(payload)


def test_companion_requires_pairing_token_and_returns_only_preview(tmp_path: Path) -> None:
    server, token = serve_companion(tmp_path / "card-relay.db", 0, lambda: "test-token")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    body = json.dumps(_payload())
    try:
        connection.request(
            "POST",
            "/v1/collectr/captures",
            body=body,
            headers={"Content-Type": "application/json"},
        )
        unauthorized = connection.getresponse()
        assert unauthorized.status == 401
        unauthorized.read()

        connection.request(
            "POST",
            "/v1/collectr/captures",
            body=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        accepted = connection.getresponse()
        payload = json.loads(accepted.read())
        assert accepted.status == 201
        assert payload["destination_writes_enabled"] is False
        assert len(payload["collection_fingerprint"]) >= 16
        assert payload["trusted_for_destructive_planning"] is False
        assert payload["invalid_record_reasons"] == {
            "capture_error": 0,
            "aggregate_view": 0,
            "missing_identity": 0,
            "unsupported_finish": 0,
            "unresolved_condition": 0,
            "unresolved_grading": 0,
            "non_positive_quantity": 0,
            "conflicting_condition": 0,
        }
        assert "entries" not in payload
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_companion_accepts_only_validated_dex_read_capture(tmp_path: Path) -> None:
    server, token = serve_companion(tmp_path / "card-relay.db", 0, lambda: "test-token")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    body = DEX_FIXTURE.read_text(encoding="utf-8")
    try:
        connection.request(
            "POST",
            "/v1/dex/captures",
            body=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        response = connection.getresponse()
        payload = json.loads(response.read())
        assert response.status == 201
        assert payload["catalog_records"] == 2
        assert payload["collection_records"] == 1
        assert payload["destination_writes_enabled"] is False
        assert "catalog" not in payload
        assert "collection" not in payload

        connection.request(
            "POST",
            "/v1/dex/backups/status",
            body="{}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        status_response = connection.getresponse()
        status_payload = json.loads(status_response.read())
        assert status_response.status == 201
        assert status_payload["backup_count"] == 1
        assert status_payload["latest"]["snapshot_id"] == payload["snapshot_id"]
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        thread.join(timeout=5)


def test_dex_write_observation_contract_is_schema_only_and_keeps_writes_disabled() -> None:
    result = process_dex_write_observations(_write_observation_payload())

    assert result.observation_count == 1
    assert result.destination_writes_enabled is False
    assert result.observations[0].method == "PATCH"
    assert result.observations[0].request_shape.fields["cardId"].format == "uuid"
    assert result.observations[0].path_parameter_bindings[0].source == "request.cardId"
    serialized = result.model_dump_json()
    assert "value" not in serialized
    assert "authorization" not in serialized.casefold()


def test_dex_write_observation_rejects_scalar_values_and_unbounded_routes() -> None:
    payload = _write_observation_payload()
    observation = payload["observations"][0]  # type: ignore[index]
    observation["request_shape"]["value"] = "must-not-cross"  # type: ignore[index]

    with pytest.raises(ValidationError, match="extra_forbidden"):
        DexWriteObservationCapture.model_validate(payload)

    payload = _write_observation_payload()
    observation = payload["observations"][0]  # type: ignore[index]
    observation["route_template"] = "https://private.invalid/user-id"  # type: ignore[index]
    with pytest.raises(ValidationError, match="string_pattern_mismatch"):
        DexWriteObservationCapture.model_validate(payload)


def test_companion_accepts_only_validated_dex_write_observations(tmp_path: Path) -> None:
    server, token = serve_companion(tmp_path / "card-relay.db", 0, lambda: "test-token")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        connection.request(
            "POST",
            "/v1/dex/write-observations",
            body=json.dumps(_write_observation_payload()),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        response = connection.getresponse()
        payload = json.loads(response.read())
        assert response.status == 201
        assert payload["observation_count"] == 1
        assert payload["destination_writes_enabled"] is False
        assert "value" not in json.dumps(payload)
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_companion_builds_card_level_read_only_sync_preview(tmp_path: Path) -> None:
    database_path = tmp_path / "card-relay.db"
    process_collectr_capture(_payload(), database_path)
    process_dex_capture(json.loads(DEX_FIXTURE.read_text(encoding="utf-8")), database_path)

    result = process_sync_preview(database_path)

    assert result.destination == "dex"
    assert result.changes
    assert result.destination_writes_enabled is True
    assert result.destructive_confirmation_code is None
    assert sum(result.change_counts.values()) == len(result.changes)
    assert all(change.card for change in result.changes)
    assert all(change.current_quantity >= 0 for change in result.changes)
    assert result.mapping_review_count == 0
    assert result.mapping_reviews == []
    assert result.mapping_reviews_truncated is False


def test_mapping_decision_is_current_candidate_bound_and_persistent(tmp_path: Path) -> None:
    database_path = tmp_path / "card-relay.db"
    process_collectr_capture(_payload(), database_path)
    process_dex_capture(_reviewable_dex_payload(), database_path)
    preview = process_sync_preview(database_path)
    review = preview.mapping_reviews[0]
    destination_id = review.candidates[0].destination_id

    with pytest.raises(MappingDecisionUnavailable, match="mapping_candidate_not_offered"):
        process_mapping_decision(
            {
                "action": "confirm",
                "source_fingerprint": review.source_fingerprint,
                "destination_id": "unoffered-card",
            },
            database_path,
        )

    refreshed = process_mapping_decision(
        {
            "action": "confirm",
            "source_fingerprint": review.source_fingerprint,
            "destination_id": destination_id,
        },
        database_path,
    )

    assert refreshed.mapping_review_count == 0
    assert MappingRepository(create_database(database_path)).list_confirmed("dex") == {
        review.source_fingerprint: destination_id
    }
    with pytest.raises(MappingDecisionUnavailable, match="mapping_review_stale"):
        process_mapping_decision(
            {
                "action": "confirm",
                "source_fingerprint": review.source_fingerprint,
                "destination_id": destination_id,
            },
            database_path,
        )


def test_bulk_mapping_decisions_validate_then_refresh_once(tmp_path: Path) -> None:
    database_path = tmp_path / "card-relay.db"
    process_collectr_capture(_payload(), database_path)
    process_dex_capture(_reviewable_dex_payload(), database_path)
    review = process_sync_preview(database_path).mapping_reviews[0]
    destination_id = review.candidates[0].destination_id

    refreshed = process_mapping_decisions(
        {
            "decisions": [
                {
                    "action": "confirm",
                    "source_fingerprint": review.source_fingerprint,
                    "destination_id": destination_id,
                }
            ]
        },
        database_path,
    )

    assert refreshed.mapping_review_count == 0
    assert MappingRepository(create_database(database_path)).list_confirmed("dex") == {
        review.source_fingerprint: destination_id
    }


def test_rejecting_mapping_candidate_persists_and_clears_review(tmp_path: Path) -> None:
    database_path = tmp_path / "card-relay.db"
    process_collectr_capture(_payload(), database_path)
    process_dex_capture(_reviewable_dex_payload(), database_path)
    review = process_sync_preview(database_path).mapping_reviews[0]
    destination_id = review.candidates[0].destination_id

    refreshed = process_mapping_decision(
        {
            "action": "reject",
            "source_fingerprint": review.source_fingerprint,
            "destination_id": destination_id,
        },
        database_path,
    )

    assert refreshed.mapping_review_count == 0
    assert MappingRepository(create_database(database_path)).list_rejected("dex") == {
        review.source_fingerprint: {destination_id}
    }


def test_companion_mapping_endpoint_rejects_unoffered_id_then_refreshes_preview(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "card-relay.db"
    process_collectr_capture(_payload(), database_path)
    process_dex_capture(_reviewable_dex_payload(), database_path)
    review = process_sync_preview(database_path).mapping_reviews[0]
    server, token = serve_companion(database_path, 0, lambda: "test-token")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        invalid = {
            "action": "confirm",
            "source_fingerprint": review.source_fingerprint,
            "destination_id": "unoffered-card",
        }
        connection.request("POST", "/v1/mappings/decisions", json.dumps(invalid), headers)
        rejected = connection.getresponse()
        rejected_payload = json.loads(rejected.read())
        assert rejected.status == 409
        assert rejected_payload == {
            "error": "mapping_decision_rejected",
            "reason": "mapping_candidate_not_offered",
        }

        accepted = invalid | {"destination_id": review.candidates[0].destination_id}
        connection.request("POST", "/v1/mappings/decisions", json.dumps(accepted), headers)
        response = connection.getresponse()
        payload = json.loads(response.read())
        assert response.status == 201
        assert payload["mapping_review_count"] == 0
        assert payload["destination_writes_enabled"] is True
    finally:
        connection.close()
        server.shutdown()
        server.server_close()


def test_safe_dex_write_batch_is_confirmation_bound_and_requires_recapture(tmp_path: Path) -> None:
    database_path = tmp_path / "card-relay.db"
    process_collectr_capture(_payload(), database_path)
    dex_capture = json.loads(DEX_FIXTURE.read_text(encoding="utf-8"))
    dex_capture["collection_pages"][0]["result"][0]["quantities"]["friendBallHolo"] = 3
    process_dex_capture(dex_capture, database_path)
    preview = process_sync_preview(database_path)

    assert preview.destination_writes_enabled is True
    assert preview.safe_write_count == 1
    assert preview.safe_write_confirmation_code is not None
    with pytest.raises(SafeWriteUnavailable, match="confirmation_mismatch"):
        process_safe_write_prepare(
            {"confirmation_code": "A" * 12, "operation_ids": preview.safe_write_operation_ids},
            database_path,
        )

    batch = process_safe_write_prepare(
        {
            "confirmation_code": preview.safe_write_confirmation_code,
            "operation_ids": preview.safe_write_operation_ids,
        },
        database_path,
    )

    assert batch.commands[0].method == "PATCH"
    assert batch.commands[0].origin == "https://clients.dextcg.com"
    assert batch.commands[0].path == "/api/user/cards/fixture-collection-entry-1"
    assert batch.commands[0].body.card_id == "fixture-card-1"
    assert batch.commands[0].body.quantities["holo"] == 2
    assert batch.commands[0].body.quantities["friendBallHolo"] == 3

    report = process_safe_write_report(
        {
            "contract_version": "dex-safe-write-report-v1",
            "plan_id": batch.plan_id,
            "confirmation_code": batch.confirmation_code,
            "results": [
                {
                    "operation_id": batch.commands[0].operation_id,
                    "succeeded": True,
                    "outcome": "succeeded",
                    "status": 200,
                    "attempts": 1,
                }
            ],
        },
        database_path,
    )

    assert report.fully_succeeded
    blocked = process_sync_preview(database_path)
    assert blocked.destination_writes_enabled is False
    assert blocked.safe_write_block_reason == "dex_recapture_required_after_write_attempt"


def test_controlled_removal_zeroes_only_managed_finish_and_requires_recapture(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "card-relay.db"
    process_collectr_capture(_payload(), database_path)
    dex_capture = json.loads(DEX_FIXTURE.read_text(encoding="utf-8"))
    quantities = dex_capture["collection_pages"][0]["result"][0]["quantities"]
    quantities["normal"] = 3
    process_dex_capture(dex_capture, database_path)
    safe_preview = process_sync_preview(database_path)

    safe_batch = process_safe_write_prepare(
        {
            "confirmation_code": safe_preview.safe_write_confirmation_code,
            "operation_ids": safe_preview.safe_write_operation_ids,
        },
        database_path,
    )
    process_safe_write_report(
        {
            "contract_version": "dex-safe-write-report-v1",
            "plan_id": safe_batch.plan_id,
            "confirmation_code": safe_batch.confirmation_code,
            "results": [
                {
                    "operation_id": safe_batch.commands[0].operation_id,
                    "succeeded": True,
                    "outcome": "succeeded",
                    "status": 200,
                    "attempts": 1,
                }
            ],
        },
        database_path,
    )

    quantities["holo"] = 2
    process_dex_capture(dex_capture, database_path)
    empty_collection = CanonicalCollection(entries=[], completeness=ExtractionCompleteness.COMPLETE)
    SourceCollectionRepository(create_database(database_path)).add(
        SourceSnapshot(
            ingestion_method=IngestionMethod.BROWSER,
            source_schema_fingerprint="controlled-removal-test",
            parser_name="controlled-removal-test",
            parser_version="1",
            completeness=ExtractionCompleteness.COMPLETE,
            total_unique_entries=0,
            total_quantity=0,
            collection_fingerprint=collection_fingerprint(empty_collection),
            trusted_for_destructive_planning=False,
        ),
        empty_collection,
    )

    default_preview = process_sync_preview(database_path)
    assert default_preview.removal_test_enabled is False
    assert default_preview.removal_writes_enabled is False
    assert default_preview.destructive_confirmation_code is None

    options = CompanionSafetyOptions(
        allow_removal_test=True,
        maximum_removal_count=1,
        maximum_removal_percent=100,
    )
    preview = process_sync_preview(database_path, options)
    assert preview.removal_test_enabled is True
    assert preview.removal_writes_enabled is True
    assert preview.removal_count == 1
    assert preview.destructive_confirmation_code is not None
    with pytest.raises(RemovalTestUnavailable, match="removal_test_not_enabled"):
        process_removal_prepare(
            {
                "confirmation_code": preview.destructive_confirmation_code,
                "operation_ids": preview.removal_operation_ids,
            },
            database_path,
        )
    with pytest.raises(RemovalTestUnavailable, match="removal_confirmation_mismatch"):
        process_removal_prepare(
            {
                "confirmation_code": "A" * 12,
                "operation_ids": preview.removal_operation_ids,
            },
            database_path,
            options,
        )

    batch = process_removal_prepare(
        {
            "confirmation_code": preview.destructive_confirmation_code,
            "operation_ids": preview.removal_operation_ids,
        },
        database_path,
        options,
    )

    assert batch.contract_version == "dex-removal-batch-v1"
    assert batch.commands[0].method == "PATCH"
    assert batch.commands[0].path == "/api/user/cards/fixture-collection-entry-1"
    assert batch.commands[0].body.quantities["holo"] == 0
    assert batch.commands[0].body.quantities["normal"] == 3
    backup = DestinationBackupRepository(create_database(database_path)).latest("dex")
    assert backup is not None
    assert backup.backup_id == batch.backup_snapshot_id
    assert any(entry.quantity == 2 for entry in backup.collection)

    report = process_removal_report(
        {
            "contract_version": "dex-removal-report-v1",
            "plan_id": batch.plan_id,
            "confirmation_code": batch.confirmation_code,
            "backup_snapshot_id": batch.backup_snapshot_id,
            "results": [
                {
                    "operation_id": batch.commands[0].operation_id,
                    "succeeded": True,
                    "outcome": "succeeded",
                    "status": 200,
                    "attempts": 1,
                }
            ],
        },
        database_path,
        options,
    )

    assert report.fully_succeeded
    assert report.backup_snapshot_id == batch.backup_snapshot_id
    assert ManagedDestinationRepository(create_database(database_path)).list_ids("dex") == set()
    blocked = process_sync_preview(database_path, options)
    assert blocked.removal_writes_enabled is False
    assert blocked.removal_block_reason == "dex_recapture_required_after_write_attempt"


def test_sync_preview_reports_which_local_capture_is_missing(tmp_path: Path) -> None:
    database_path = tmp_path / "card-relay.db"

    with pytest.raises(SyncPreviewUnavailable, match="collectr_capture_required"):
        process_sync_preview(database_path)

    process_collectr_capture(_payload(), database_path)
    with pytest.raises(SyncPreviewUnavailable, match="dex_capture_required"):
        process_sync_preview(database_path)


def test_extension_exposes_polished_guided_sync_controls() -> None:
    popup = (EXTENSION / "popup.js").read_text(encoding="utf-8")
    background = (EXTENSION / "background.js").read_text(encoding="utf-8")
    html = (EXTENSION / "popup.html").read_text(encoding="utf-8")

    assert "Keep your Pokémon collection in sync." in html
    assert "other TCG ignored" in popup
    assert "Save connection" in html
    assert "Capture destination" in popup
    assert "Capture source" in popup
    assert "Collectr → Dex" in html
    assert "card-relay-sync-preview" in popup
    assert "/v1/sync/previews" in background
    assert "await loadSyncPreview(false)" in popup
    assert "View ${totalChanges} card change" in popup
    assert "Match review" in html
    assert "Confirm selected" in html
    assert "Reject selected" in html
    assert "Select suggested" in html
    assert "card-relay-mapping-decision" in popup
    assert "/v1/mappings/decisions" in background
    assert "card-relay-mapping-decisions" in popup
    assert "/v1/mappings/decisions/batch" in background
    assert "card-relay-collectr-backup-status" in popup
    assert "/v1/collectr/backups/status" in background
    assert "Using saved Collectr scan" in popup
    assert "card-relay-dex-backup-status" in popup
    assert "/v1/dex/backups/status" in background
    assert "Using saved Dex snapshot" in popup
    assert "Capturing Dex catalog… ${status.catalogPageCount} of" in popup
    assert "scheduleStatusRefresh(status.activeTarget)" in popup
    assert "companion_update_required" in background
    assert "Restart the CardRelay companion" in popup
    assert "Ready to sync" in html
    assert "card-relay-safe-write-prepare" in popup
    assert "card-relay-dex-safe-write-execute" in popup
    assert "/v1/dex/safe-write-batches" in background
    assert "safe-write-confirmation" not in html
    assert "safeWriteConfirmation" not in popup
    assert "Approve removals" in html
    assert "removal-confirmation" in html
    assert "card-relay-removal-prepare" in popup
    assert "dex-removal-report-v1" in popup
    assert "/v1/dex/removal-batches" in background
    assert "/v1/dex/removal-reports" in background
    assert "Developer tools" not in html
    assert "Milestone 6 reliability evidence" not in html
    assert "Dex write-contract research" not in html
    assert "Pages observed:" not in popup
    assert "Dex catalog records:" not in popup
    assert "Reload the ${page} tab once, then reopen CardRelay." in popup
    safe_handler = popup[popup.index("applySafeWriteButton.addEventListener") :]
    assert safe_handler.index('if (service !== "dex")') < safe_handler.index(
        'type: "card-relay-safe-write-prepare"'
    )
    removal_handler = popup[popup.index("applyRemovalButton.addEventListener") :]
    assert removal_handler.index('if (service !== "dex")') < removal_handler.index(
        'type: "card-relay-removal-prepare"'
    )


def test_companion_accepts_dex_capture_in_bounded_contiguous_chunks(tmp_path: Path) -> None:
    server, token = serve_companion(tmp_path / "card-relay.db", 0, lambda: "test-token")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    fixture = json.loads(DEX_FIXTURE.read_text(encoding="utf-8"))
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        first = {
            "contract_version": "dex-extension-chunk-v1",
            "upload_id": "fixture-upload-01",
            "chunk_index": 0,
            "chunk_count": 2,
            "collection_pages": fixture["collection_pages"],
            "catalog_pages": [],
        }
        connection.request("POST", "/v1/dex/capture-chunks", json.dumps(first), headers)
        interim = connection.getresponse()
        interim_payload = json.loads(interim.read())
        assert interim.status == 201
        assert interim_payload["upload_complete"] is False
        assert interim_payload["next_chunk_index"] == 1

        second = {
            "contract_version": "dex-extension-chunk-v1",
            "upload_id": "fixture-upload-01",
            "chunk_index": 1,
            "chunk_count": 2,
            "collection_pages": [],
            "catalog_pages": fixture["catalog_pages"],
        }
        connection.request("POST", "/v1/dex/capture-chunks", json.dumps(second), headers)
        accepted = connection.getresponse()
        accepted_payload = json.loads(accepted.read())
        assert accepted.status == 201
        assert accepted_payload["catalog_records"] == 2
        assert accepted_payload["collection_records"] == 1
        assert accepted_payload["destination_writes_enabled"] is False
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize(
    ("body", "expected_error"),
    [
        ("{", "invalid_capture_json"),
        (json.dumps({"contract_version": "collectr-extension-v1"}), "invalid_capture_contract"),
    ],
)
def test_companion_reports_safe_capture_rejection_stage(
    tmp_path: Path, body: str, expected_error: str
) -> None:
    server, token = serve_companion(tmp_path / "card-relay.db", 0, lambda: "test-token")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        connection.request(
            "POST",
            "/v1/collectr/captures",
            body=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        response = connection.getresponse()
        payload = json.loads(response.read())

        assert response.status == 400
        assert payload["error"] == expected_error
        if expected_error == "invalid_capture_contract":
            assert payload["issues"] == [
                {"location": "product_pages", "type": "missing"},
                {"location": "exact_view_verified", "type": "missing"},
            ]
            assert "collectr-extension-v1" not in json.dumps(payload)
        else:
            assert payload == {"error": expected_error}
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_extension_manifest_permissions_remain_narrow() -> None:
    manifest = json.loads((EXTENSION / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["permissions"] == ["activeTab", "storage"]
    assert manifest["host_permissions"] == [
        "https://app.getcollectr.com/*",
        "https://app.dextcg.com/*",
        "http://127.0.0.1/*",
    ]
    serialized = json.dumps(manifest)
    for forbidden in ("<all_urls>", "cookies", "debugger", "webRequest", "downloads"):
        assert forbidden not in serialized


def test_extension_dex_capture_is_manual_and_strips_sensitive_fields() -> None:
    observer = (EXTENSION / "dex-page-observer.js").read_text(encoding="utf-8")

    assert "let captureTarget = null;" in observer
    assert 'message.type !== "capture-control"' in observer
    assert "userId" not in observer
    assert "createdAt" not in observer
    assert "markets" not in observer
    assert "imageUrl" not in observer


def test_extension_preserves_only_lookup_metadata_across_navigation() -> None:
    content_script = (EXTENSION / "content.js").read_text(encoding="utf-8")

    assert "conditionPayloads," in content_script
    assert "gradingPayloads" in content_script
    assert (
        "productPages"
        not in content_script.split("async function persistSessionState", 1)[1].split("}", 1)[0]
    )


def test_extension_reads_only_verified_cached_lookup_keys() -> None:
    observer = (EXTENSION / "page-observer.js").read_text(encoding="utf-8")

    assert '["cardConditions", "conditions"]' in observer
    assert '["gradedCardScales", "grading"]' in observer
    assert "localStorage.getItem(key)" in observer
    assert "lookup-request" in observer
    assert "Object.keys(localStorage)" not in observer
    assert "localStorage.key(" not in observer
