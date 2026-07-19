import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from card_relay.destinations.dex.adapter import DexAdapter
from card_relay.destinations.dex.models import DexCapturedCard
from card_relay.destinations.dex.normalizer import (
    build_dex_write_metadata,
    normalize_dex_catalog,
    normalize_dex_finish,
)
from card_relay.domain.enums import Finish
from card_relay.exceptions import IntegrationUnavailableError
from card_relay.extension.companion import DexExtensionCapture, process_dex_capture
from card_relay.storage.database import create_database
from card_relay.storage.repositories import CatalogCacheRepository, DestinationReadRepository

FIXTURE = Path(__file__).parents[1] / "fixtures" / "dex" / "extension_capture.json"


def _payload() -> dict[str, object]:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_dex_finish_normalization_is_explicit() -> None:
    assert normalize_dex_finish("Reverse_Holo") is Finish.REVERSE_HOLO
    assert normalize_dex_finish("Holofoil") is Finish.HOLO
    assert normalize_dex_finish("reverseHolo") is Finish.REVERSE_HOLO
    assert normalize_dex_finish("unknown treatment") is None


def test_dex_catalog_normalization_expands_variants() -> None:
    request = DexExtensionCapture.model_validate(_payload())
    cards = [card for page in request.catalog_pages for card in page.result]

    records, unsupported = normalize_dex_catalog(cards)

    assert unsupported == []
    assert [record.destination_id for record in records] == [
        "fixture-card-1::holo",
        "fixture-card-1::normal",
    ]
    assert records[0].identity.set_code == "fixture-set-1"
    assert records[0].identity.collector_number == "1"
    assert records[0].identity.language == "unknown"


def test_dex_write_metadata_preserves_record_id_full_map_and_quantity_keys() -> None:
    request = DexExtensionCapture.model_validate(_payload())
    cards = [card for page in request.catalog_pages for card in page.result]
    entries = [entry for page in request.collection_pages for entry in page.result]

    metadata = build_dex_write_metadata(cards, entries)

    record = metadata.collection_records["fixture-card-1"]
    assert record.record_id == "fixture-collection-entry-1"
    assert record.quantities == {"holo": 1}
    assert metadata.quantity_keys == {
        "fixture-card-1::holo": "holo",
        "fixture-card-1::normal": "normal",
    }
    assert metadata.ambiguous_destination_ids == []


def test_dex_unknown_variant_is_reported_not_guessed() -> None:
    card = DexCapturedCard.model_validate(
        _payload()["catalog_pages"][0]["result"][0]  # type: ignore[index]
    )
    changed = card.model_copy(
        update={"variants": [card.variants[0].model_copy(update={"type": "Mystery"})]}
    )

    records, unsupported = normalize_dex_catalog([changed])

    assert records == []
    assert unsupported == ["Mystery"]


def test_dex_uses_nested_finish_label_and_distinct_public_set_code() -> None:
    payload = deepcopy(_payload()["catalog_pages"][0]["result"][0])  # type: ignore[index]
    payload["setId"] = "relational-set-id"  # type: ignore[index]
    payload["set"]["setId"] = "public-set-code"  # type: ignore[index]
    payload["variants"] = [{"type": "default", "name": "Cosmos Holo"}]  # type: ignore[index]
    card = DexCapturedCard.model_validate(payload)

    records, unsupported = normalize_dex_catalog([card])

    assert unsupported == []
    assert len(records) == 1
    assert records[0].identity.finish is Finish.COSMOS_HOLO
    assert records[0].identity.set_code == "public-set-code"


def test_dex_extension_capture_requires_complete_consistent_pagination() -> None:
    payload = deepcopy(_payload())
    payload["catalog_pages"][0]["totalPages"] = 2  # type: ignore[index]

    with pytest.raises(ValidationError, match="every page"):
        DexExtensionCapture.model_validate(payload)


def test_dex_capture_persists_normalized_read_snapshot_and_cache(tmp_path: Path) -> None:
    database_path = tmp_path / "card-relay.db"

    result = process_dex_capture(_payload(), database_path)

    assert result.catalog_records == 2
    assert result.collection_records == 1
    assert result.total_quantity == 1
    assert result.normalization_complete
    assert result.destination_writes_enabled is False
    engine = create_database(database_path)
    snapshot = DestinationReadRepository(engine).get("dex")
    assert snapshot is not None
    assert snapshot.complete
    assert len(snapshot.catalog) == 2
    assert snapshot.collection[0].destination_id == "fixture-card-1::holo"
    assert snapshot.metadata["write_metadata"]["collection_records"]["fixture-card-1"] == {
        "record_id": "fixture-collection-entry-1",
        "card_id": "fixture-card-1",
        "quantities": {"holo": 1},
    }
    cached = CatalogCacheRepository(engine).get("dex")
    assert cached is not None
    assert cached[1] == snapshot.catalog


def test_dex_adapter_is_read_only_and_requires_capture(tmp_path: Path) -> None:
    empty_adapter = DexAdapter(create_database(tmp_path / "empty.db"))
    with pytest.raises(IntegrationUnavailableError, match="capture Dex"):
        empty_adapter.fetch_catalog()

    database_path = tmp_path / "captured.db"
    process_dex_capture(_payload(), database_path)
    adapter = DexAdapter(create_database(database_path))
    assert len(adapter.fetch_catalog()) == 2
    assert len(adapter.fetch_collection()) == 1
    assert adapter.apply_operations([], dry_run=True).succeeded
    with pytest.raises(IntegrationUnavailableError, match="writes are disabled"):
        adapter.apply_operations([], dry_run=False)
