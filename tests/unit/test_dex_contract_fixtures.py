import json
from pathlib import Path

FIXTURE_DIRECTORY = Path(__file__).parents[1] / "fixtures" / "dex"
PAGE_KEYS = {"page", "pageSize", "result", "totalItems", "totalPages"}
ENTRY_KEYS = {"card", "cardId", "createdAt", "id", "quantities", "updatedAt", "userId"}


def _load_fixture(name: str) -> dict[str, object]:
    payload = json.loads((FIXTURE_DIRECTORY / name).read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_empty_dex_collection_contract_is_explicitly_empty() -> None:
    payload = _load_fixture("collection_page_empty.json")
    assert set(payload) == PAGE_KEYS
    assert payload["result"] == []
    assert payload["totalItems"] == 0
    assert payload["totalPages"] == 1


def test_one_card_dex_collection_contract_is_fictional_and_quantity_preserving() -> None:
    payload = _load_fixture("collection_page_one_card.json")
    assert set(payload) == PAGE_KEYS
    result = payload["result"]
    assert isinstance(result, list)
    assert len(result) == 1
    entry = result[0]
    assert isinstance(entry, dict)
    assert set(entry) == ENTRY_KEYS
    quantities = entry["quantities"]
    assert isinstance(quantities, dict)
    assert quantities == {"holo": 1}

    serialized = json.dumps(payload)
    assert "example.invalid" in serialized
    assert "fixture-" in serialized
    assert "@" not in serialized
    assert int(quantities["holo"]) >= 0
