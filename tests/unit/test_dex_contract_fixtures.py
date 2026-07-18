import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from card_relay.destinations.dex.models import DexCollectionPage

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

    page = DexCollectionPage.model_validate(payload)
    assert page.result == []
    assert page.total_items == 0


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


def test_one_card_dex_collection_contract_validates_typed_fields() -> None:
    page = DexCollectionPage.model_validate(_load_fixture("collection_page_one_card.json"))

    assert page.page_size == 20
    assert page.total_items == 1
    assert len(page.result) == 1
    entry = page.result[0]
    assert entry.card_id == "fixture-card-1"
    assert entry.card.card_id == entry.card_id
    assert entry.card.name == "Fixturemon"
    assert entry.card.number == "001"
    assert entry.card.set.name == "Fixture Set"
    assert entry.quantities == {"holo": 1}
    assert entry.total_quantity == 1


@pytest.mark.parametrize("invalid_quantity", [-1, 1.5, "1", True, None])
def test_dex_collection_contract_rejects_invalid_quantities(
    invalid_quantity: object,
) -> None:
    payload = deepcopy(_load_fixture("collection_page_one_card.json"))
    result = payload["result"]
    assert isinstance(result, list)
    entry = result[0]
    assert isinstance(entry, dict)
    entry["quantities"] = {"holo": invalid_quantity}

    with pytest.raises(ValidationError):
        DexCollectionPage.model_validate(payload)


def test_dex_collection_contract_rejects_mismatched_card_identifier() -> None:
    payload = deepcopy(_load_fixture("collection_page_one_card.json"))
    result = payload["result"]
    assert isinstance(result, list)
    entry = result[0]
    assert isinstance(entry, dict)
    entry["cardId"] = "fixture-different-card"

    with pytest.raises(ValidationError, match="cardId must match"):
        DexCollectionPage.model_validate(payload)


def test_dex_collection_contract_rejects_mismatched_set_identifier() -> None:
    payload = deepcopy(_load_fixture("collection_page_one_card.json"))
    result = payload["result"]
    assert isinstance(result, list)
    entry = result[0]
    assert isinstance(entry, dict)
    card = entry["card"]
    assert isinstance(card, dict)
    card["setId"] = "fixture-different-set"

    with pytest.raises(ValidationError, match="setId must match"):
        DexCollectionPage.model_validate(payload)


def test_dex_collection_contract_rejects_unexpected_envelope_fields() -> None:
    payload = _load_fixture("collection_page_empty.json")
    payload["unexpected"] = "contract change"

    with pytest.raises(ValidationError, match="unexpected"):
        DexCollectionPage.model_validate(payload)


def test_dex_collection_contract_rejects_unexpected_entry_fields() -> None:
    payload = deepcopy(_load_fixture("collection_page_one_card.json"))
    result = payload["result"]
    assert isinstance(result, list)
    entry = result[0]
    assert isinstance(entry, dict)
    entry["unexpected"] = "contract change"

    with pytest.raises(ValidationError, match="unexpected"):
        DexCollectionPage.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [("page", 0), ("pageSize", 0), ("totalItems", -1), ("totalPages", 0)],
)
def test_dex_collection_contract_rejects_invalid_pagination(field: str, value: int) -> None:
    payload = _load_fixture("collection_page_empty.json")
    payload[field] = value

    with pytest.raises(ValidationError):
        DexCollectionPage.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [("page", 2), ("totalItems", 0)],
)
def test_dex_collection_contract_rejects_inconsistent_pagination(field: str, value: int) -> None:
    payload = _load_fixture("collection_page_one_card.json")
    payload[field] = value

    with pytest.raises(ValidationError):
        DexCollectionPage.model_validate(payload)


def test_dex_collection_contract_rejects_page_size_overflow() -> None:
    payload = deepcopy(_load_fixture("collection_page_one_card.json"))
    result = payload["result"]
    assert isinstance(result, list)
    result.append(deepcopy(result[0]))
    payload["totalItems"] = 2
    payload["totalPages"] = 2
    payload["pageSize"] = 1

    with pytest.raises(ValidationError, match="result count cannot exceed pageSize"):
        DexCollectionPage.model_validate(payload)
