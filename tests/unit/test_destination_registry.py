from card_relay.destinations.experimental import ExperimentalDestinationAdapter
from card_relay.destinations.registry import destination_descriptors
from card_relay.domain.enums import Finish, OperationType
from card_relay.domain.models import CanonicalCardIdentity, DestinationCatalogRecord
from card_relay.domain.operations import SyncOperation


def test_destination_discovery_is_deterministic_and_data_free() -> None:
    descriptors = destination_descriptors()

    assert [item.name for item in descriptors] == ["dex", "experimental", "mock"]
    assert descriptors[0].stability == "read_only"
    assert descriptors[1].stability == "experimental"
    assert descriptors[1].capabilities.additions
    assert descriptors[1].capabilities.quantity_increases
    assert not descriptors[1].capabilities.quantity_decreases
    assert not descriptors[1].capabilities.removals


def test_experimental_adapter_supports_only_safe_pokemon_operations() -> None:
    identity = CanonicalCardIdentity(
        game="pokemon",
        card_name="Fixturemon",
        set_name="Fixture Set",
        set_code="FIX",
        collector_number="1",
        finish=Finish.NORMAL,
    )
    catalog = [DestinationCatalogRecord(destination_id="fixture-1", identity=identity)]
    adapter = ExperimentalDestinationAdapter(catalog)
    operation = SyncOperation(
        operation_type=OperationType.ADD,
        fingerprint=identity.fingerprint,
        destination_id="fixture-1",
        identity=identity,
        current_quantity=0,
        desired_quantity=2,
        executable=True,
        reason="safe addition",
    )

    result = adapter.apply_operations([operation], dry_run=False)

    assert result.succeeded
    assert adapter.fetch_collection()[0].quantity == 2
    assert adapter.get_capabilities().supports_game("Pokémon")
    assert not adapter.get_capabilities().supports_game("Magic: The Gathering")
