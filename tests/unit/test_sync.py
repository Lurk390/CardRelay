from card_relay.destinations.capabilities import DestinationCapabilities
from card_relay.destinations.dex.adapter import DexAdapter
from card_relay.domain.enums import (
    ExtractionCompleteness,
    IngestionMethod,
    MatchStatus,
    OperationType,
)
from card_relay.domain.models import (
    CanonicalCardIdentity,
    CanonicalCollection,
    CanonicalCollectionEntry,
    DestinationCatalogRecord,
    DestinationCollectionEntry,
)
from card_relay.domain.results import MatchResult
from card_relay.sync.planner import build_plan
from card_relay.sync.policy import SyncPolicy


def setup(
    quantity: int,
    actual: int,
    completeness: ExtractionCompleteness = ExtractionCompleteness.COMPLETE,
):
    identity = CanonicalCardIdentity(
        card_name="Embermouse", set_name="Mythic Sparks", collector_number="1"
    )
    source = CanonicalCollection(
        entries=[
            CanonicalCollectionEntry(
                identity=identity, quantity=quantity, ingestion_method=IngestionMethod.CSV
            )
        ],
        completeness=completeness,
    )
    catalog = DestinationCatalogRecord(destination_id="mock-1", identity=identity)
    match = MatchResult(
        source_fingerprint=identity.fingerprint, status=MatchStatus.EXACT, candidate=catalog
    )
    destination = (
        []
        if actual == 0
        else [
            DestinationCollectionEntry(destination_id="mock-1", identity=identity, quantity=actual)
        ]
    )
    return source, destination, [match]


def test_default_policy_allows_increase_but_blocks_decrease() -> None:
    capabilities = DestinationCapabilities(
        additions=True, quantity_increases=True, quantity_decreases=True
    )
    source, destination, matches = setup(3, 1)
    assert (
        build_plan(source, destination, matches, capabilities, SyncPolicy())
        .operations[0]
        .executable
    )
    source, destination, matches = setup(1, 3)
    operation = build_plan(source, destination, matches, capabilities, SyncPolicy()).operations[0]
    assert operation.operation_type is OperationType.DECREASE
    assert not operation.executable


def test_incomplete_source_blocks_explicit_destructive_policy() -> None:
    source, destination, matches = setup(1, 3, ExtractionCompleteness.INCOMPLETE)
    capabilities = DestinationCapabilities(quantity_decreases=True)
    operation = build_plan(
        source, destination, matches, capabilities, SyncPolicy(allow_quantity_decreases=True)
    ).operations[0]
    assert not operation.executable


def test_partial_source_allows_observed_increase_but_not_omitted_removal() -> None:
    source, destination, matches = setup(3, 1, ExtractionCompleteness.INCOMPLETE)
    omitted_identity = CanonicalCardIdentity(
        card_name="Omitted Fixture",
        set_name="Fixture Set",
        collector_number="2",
    )
    destination.append(
        DestinationCollectionEntry(
            destination_id="omitted",
            identity=omitted_identity,
            quantity=2,
        )
    )
    capabilities = DestinationCapabilities(quantity_increases=True, removals=True)
    policy = SyncPolicy(
        allow_removals=True,
        maximum_removal_count=1,
        maximum_removal_percent=100,
    )

    operations = build_plan(source, destination, matches, capabilities, policy).operations
    assert operations[0].operation_type is OperationType.INCREASE
    assert operations[0].executable
    assert operations[1].operation_type is OperationType.REMOVE
    assert not operations[1].executable


def test_dex_reports_non_pokemon_source_records_as_unsupported() -> None:
    identity = CanonicalCardIdentity(
        game="Magic: The Gathering",
        card_name="Fixture Spell",
        set_name="Fixture Expansion",
        collector_number="7",
    )
    source = CanonicalCollection(
        entries=[
            CanonicalCollectionEntry(
                identity=identity,
                quantity=1,
                ingestion_method=IngestionMethod.CSV,
            )
        ]
    )
    catalog = DestinationCatalogRecord(destination_id="fixture-spell", identity=identity)
    match = MatchResult(
        source_fingerprint=identity.fingerprint,
        status=MatchStatus.EXACT,
        candidate=catalog,
    )

    operation = build_plan(
        source,
        [],
        [match],
        DexAdapter().get_capabilities(),
        SyncPolicy(),
        destination_name="dex",
    ).operations[0]

    assert DexAdapter().get_capabilities().supports_game("Pokémon")
    assert not DexAdapter().get_capabilities().supports_game("Magic: The Gathering")
    assert operation.operation_type is OperationType.UNSUPPORTED
    assert not operation.executable
    assert operation.reason == "dex does not support game: magic: the gathering"


def test_unsupported_destination_records_are_not_removal_candidates() -> None:
    source, destination, matches = setup(1, 1)
    unsupported_identity = CanonicalCardIdentity(
        game="Riftbound",
        card_name="Unsupported Fixture",
        set_name="Fixture Set",
        collector_number="2",
    )
    destination.append(
        DestinationCollectionEntry(
            destination_id="unsupported",
            identity=unsupported_identity,
            quantity=1,
        )
    )
    capabilities = DestinationCapabilities(
        supported_games=frozenset({"pokemon"}),
        removals=True,
    )
    policy = SyncPolicy(
        allow_removals=True,
        maximum_removal_count=1,
        maximum_removal_percent=100,
    )

    operations = build_plan(source, destination, matches, capabilities, policy).operations
    assert [operation.operation_type for operation in operations] == [OperationType.NO_CHANGE]


def test_removal_requires_separate_flag_and_threshold() -> None:
    source, destination, matches = setup(1, 1)
    extra = CanonicalCardIdentity(
        card_name="Tidalwing", set_name="Ocean Echoes", collector_number="7"
    )
    destination.append(
        DestinationCollectionEntry(destination_id="extra", identity=extra, quantity=1)
    )
    capabilities = DestinationCapabilities(removals=True)
    policy = SyncPolicy(allow_removals=True, maximum_removal_count=1, maximum_removal_percent=50)
    removal = build_plan(source, destination, matches, capabilities, policy).operations[1]
    assert removal.operation_type is OperationType.REMOVE
    assert removal.executable


def test_equivalent_plans_are_fully_deterministic() -> None:
    source, destination, matches = setup(3, 1)
    capabilities = DestinationCapabilities(quantity_increases=True)
    first = build_plan(source, destination, matches, capabilities, SyncPolicy())
    second = build_plan(source, destination, matches, capabilities, SyncPolicy())
    assert first == second
    assert first.operations[0].operation_id.startswith("op-v1:")
