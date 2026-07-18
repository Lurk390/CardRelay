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
    process_collectr_capture,
    serve_companion,
)
from card_relay.storage.database import create_database
from card_relay.storage.models import SnapshotRow

FIXTURES = Path(__file__).parents[1] / "fixtures" / "collectr"
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
        assert "entries" not in payload
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
        "http://127.0.0.1/*",
    ]
    serialized = json.dumps(manifest)
    for forbidden in ("<all_urls>", "cookies", "debugger", "webRequest", "downloads"):
        assert forbidden not in serialized


def test_extension_preserves_only_lookup_metadata_across_navigation() -> None:
    content_script = (EXTENSION / "content.js").read_text(encoding="utf-8")

    assert "conditionPayloads," in content_script
    assert "gradingPayloads" in content_script
    assert (
        "productPages"
        not in content_script.split("async function persistSessionState", 1)[1].split("}", 1)[0]
    )
