from card_relay.domain.enums import Edition, Finish, IngestionMethod
from card_relay.domain.models import CanonicalCardIdentity, CanonicalCollectionEntry


def test_fingerprint_is_stable_and_excludes_quantity() -> None:
    identity = CanonicalCardIdentity(
        card_name=" Embermouse ",
        set_name="Mythic Sparks",
        collector_number="001/100",
        language="English",
        finish=Finish.NORMAL,
    )
    first = CanonicalCollectionEntry(
        identity=identity, quantity=1, ingestion_method=IngestionMethod.CSV
    )
    second = first.model_copy(update={"quantity": 99})
    assert first.fingerprint == second.fingerprint
    assert identity.collector_number == "1"
    assert identity.card_name == "embermouse"


def test_variant_and_edition_change_identity() -> None:
    base = dict(card_name="Ancient Bloom", set_name="First Grove", collector_number="12")
    normal = CanonicalCardIdentity(**base, finish=Finish.NORMAL)
    reverse = CanonicalCardIdentity(**base, finish=Finish.REVERSE_HOLO)
    first = CanonicalCardIdentity(**base, finish=Finish.NORMAL, edition=Edition.FIRST)
    assert len({normal.fingerprint, reverse.fingerprint, first.fingerprint}) == 3
