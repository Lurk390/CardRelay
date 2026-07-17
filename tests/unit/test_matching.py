from card_relay.domain.enums import Finish, IngestionMethod, MatchStatus
from card_relay.domain.models import (
    CanonicalCardIdentity,
    CanonicalCollection,
    CanonicalCollectionEntry,
    DestinationCatalogRecord,
)
from card_relay.matching.matcher import match_collection


def test_exact_matching_is_variant_sensitive() -> None:
    identity = CanonicalCardIdentity(
        card_name="Embermouse", set_name="Mythic Sparks", collector_number="1", finish=Finish.NORMAL
    )
    source = CanonicalCollection(
        entries=[
            CanonicalCollectionEntry(
                identity=identity, quantity=1, ingestion_method=IngestionMethod.CSV
            )
        ]
    )
    reverse = identity.model_copy(update={"finish": Finish.REVERSE_HOLO})
    result = match_collection(
        source, [DestinationCatalogRecord(destination_id="reverse", identity=reverse)]
    )
    assert result[0].status is MatchStatus.UNMATCHED


def test_duplicate_exact_candidates_are_ambiguous() -> None:
    identity = CanonicalCardIdentity(
        card_name="Embermouse", set_name="Mythic Sparks", collector_number="1"
    )
    source = CanonicalCollection(
        entries=[
            CanonicalCollectionEntry(
                identity=identity, quantity=1, ingestion_method=IngestionMethod.CSV
            )
        ]
    )
    catalog = [
        DestinationCatalogRecord(destination_id=value, identity=identity) for value in ("a", "b")
    ]
    assert match_collection(source, catalog)[0].status is MatchStatus.AMBIGUOUS


def test_rejected_candidate_is_not_reselected() -> None:
    identity = CanonicalCardIdentity(
        card_name="Embermouse", set_name="Mythic Sparks", collector_number="1"
    )
    source = CanonicalCollection(
        entries=[
            CanonicalCollectionEntry(
                identity=identity, quantity=1, ingestion_method=IngestionMethod.CSV
            )
        ]
    )
    candidate = DestinationCatalogRecord(destination_id="rejected", identity=identity)
    result = match_collection(source, [candidate], rejected={identity.fingerprint: {"rejected"}})
    assert result[0].status is MatchStatus.REJECTED
    assert result[0].candidate is None
