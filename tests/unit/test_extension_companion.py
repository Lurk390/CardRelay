import http.client
import json
import threading
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from card_relay.extension.companion import (
    CollectrExtensionCapture,
    MappingDecisionUnavailable,
    SyncPreviewUnavailable,
    process_collectr_capture,
    process_dex_capture,
    process_mapping_decision,
    process_sync_preview,
    serve_companion,
)
from card_relay.storage.database import create_database
from card_relay.storage.models import SnapshotRow
from card_relay.storage.repositories import MappingRepository

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


def test_extension_capture_reuses_browser_normalization_and_stores_snapshot(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "card-relay.db"

    result = process_collectr_capture(_payload(), database_path)

    assert result.completeness == "complete"
    assert result.unique_entries == 3
    assert result.total_quantity == 4
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
    assert result.destination_writes_enabled is False
    assert result.destructive_confirmation_code is None
    assert sum(result.change_counts.values()) == len(result.changes)
    assert all(change.card for change in result.changes)
    assert all(change.current_quantity >= 0 for change in result.changes)
    assert result.mapping_review_count == 1
    assert result.mapping_reviews_truncated is False
    review = result.mapping_reviews[0]
    assert review.source_identity.card_name == "fixturemon"
    assert review.status.value == "probable"
    assert [candidate.destination_id for candidate in review.candidates] == ["fixture-card-1::holo"]


def test_mapping_decision_is_current_candidate_bound_and_persistent(tmp_path: Path) -> None:
    database_path = tmp_path / "card-relay.db"
    process_collectr_capture(_payload(), database_path)
    process_dex_capture(json.loads(DEX_FIXTURE.read_text(encoding="utf-8")), database_path)
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


def test_rejecting_mapping_candidate_persists_and_clears_review(tmp_path: Path) -> None:
    database_path = tmp_path / "card-relay.db"
    process_collectr_capture(_payload(), database_path)
    process_dex_capture(json.loads(DEX_FIXTURE.read_text(encoding="utf-8")), database_path)
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
    process_dex_capture(json.loads(DEX_FIXTURE.read_text(encoding="utf-8")), database_path)
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
        assert payload["destination_writes_enabled"] is False
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_sync_preview_reports_which_local_capture_is_missing(tmp_path: Path) -> None:
    database_path = tmp_path / "card-relay.db"

    with pytest.raises(SyncPreviewUnavailable, match="collectr_capture_required"):
        process_sync_preview(database_path)

    process_collectr_capture(_payload(), database_path)
    with pytest.raises(SyncPreviewUnavailable, match="dex_capture_required"):
        process_sync_preview(database_path)


def test_extension_exposes_visual_diff_without_write_controls() -> None:
    popup = (EXTENSION / "popup.js").read_text(encoding="utf-8")
    background = (EXTENSION / "background.js").read_text(encoding="utf-8")
    html = (EXTENSION / "popup.html").read_text(encoding="utf-8")

    assert "Build visual diff" in html
    assert "card-relay-sync-preview" in popup
    assert "/v1/sync/previews" in background
    assert "Match review" in html
    assert "Confirm match" in popup
    assert "Reject candidate" in popup
    assert "card-relay-mapping-decision" in popup
    assert "/v1/mappings/decisions" in background
    assert "confirm-write" not in popup


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
