from card_relay.domain.enums import Finish, IngestionMethod, MatchStatus
from card_relay.domain.models import (
    CanonicalCardIdentity,
    CanonicalCollection,
    CanonicalCollectionEntry,
    DestinationCatalogRecord,
)
from card_relay.matching.matcher import match_collection
from card_relay.matching.normalization import normalize_destination_catalog


def _collection(identity: CanonicalCardIdentity) -> CanonicalCollection:
    return CanonicalCollection(
        entries=[
            CanonicalCollectionEntry(
                identity=identity, quantity=1, ingestion_method=IngestionMethod.CSV
            )
        ]
    )


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


def test_exact_fingerprint_explains_non_identity_name_difference() -> None:
    identity = CanonicalCardIdentity(
        card_name="Embermouse", set_name="Mythic Sparks", collector_number="1"
    )
    renamed = DestinationCatalogRecord(
        destination_id="renamed",
        identity=identity.model_copy(update={"card_name": "catalog display correction"}),
    )

    result = match_collection(_collection(identity), [renamed])[0]

    assert result.status is MatchStatus.EXACT
    assert result.matched_fields == ["canonical_fingerprint"]
    assert result.mismatched_fields == ["card_name"]
    assert "non-fingerprint catalog metadata differs" in result.reasons[-1]


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


def test_stale_confirmed_mapping_does_not_override_changed_catalog_identity() -> None:
    source_identity = CanonicalCardIdentity(
        card_name="Embermouse", set_name="Mythic Sparks", collector_number="1"
    )
    reused_id = DestinationCatalogRecord(
        destination_id="reused",
        identity=CanonicalCardIdentity(
            card_name="Different Card", set_name="Other Set", collector_number="99"
        ),
    )

    result = match_collection(
        _collection(source_identity),
        [reused_id],
        saved={source_identity.fingerprint: "reused"},
    )[0]

    assert result.status is MatchStatus.UNMATCHED
    assert result.candidate is None
    assert result.reasons[-1] == (
        "confirmed mapping is absent or no longer satisfies identity anchors"
    )


def test_probable_match_uses_strong_anchors_and_explains_score() -> None:
    source_identity = CanonicalCardIdentity(
        card_name="Embermouse", set_name="Mythic Sparks", collector_number="1"
    )
    candidate = DestinationCatalogRecord(
        destination_id="probable",
        identity=source_identity.model_copy(update={"card_name": "embermous", "set_code": "MSP"}),
    )

    result = match_collection(_collection(source_identity), [candidate])[0]

    assert result.status is MatchStatus.PROBABLE
    assert result.candidate is not None
    assert result.candidate.destination_id == candidate.destination_id
    assert result.candidate.identity.set_code == "msp"
    assert result.score is not None and result.score >= 0.92
    assert result.mismatched_fields == ["card_name"]
    assert "collector_number" in result.matched_fields
    assert result.alternatives[0].reasons[-1].startswith("normalized card-name similarity")


def test_probable_matching_never_uses_card_name_without_set_and_number_anchors() -> None:
    source_identity = CanonicalCardIdentity(
        card_name="Embermouse", set_name="Mythic Sparks", collector_number="1"
    )
    wrong_printing = DestinationCatalogRecord(
        destination_id="wrong-printing",
        identity=source_identity.model_copy(
            update={"set_name": "Other Set", "collector_number": "99"}
        ),
    )

    result = match_collection(_collection(source_identity), [wrong_printing])[0]

    assert result.status is MatchStatus.UNMATCHED
    assert result.candidate_ids == []


def test_near_tied_probable_candidates_are_ambiguous_and_deterministic() -> None:
    source_identity = CanonicalCardIdentity(
        card_name="Embermouse", set_name="Mythic Sparks", collector_number="1"
    )
    catalog = [
        DestinationCatalogRecord(
            destination_id=destination_id,
            identity=source_identity.model_copy(
                update={"card_name": name, "set_code": f"MSP-{destination_id}"}
            ),
        )
        for destination_id, name in (("b", "embermous"), ("a", "embermousee"))
    ]

    result = match_collection(_collection(source_identity), catalog, ambiguity_score_margin=0.02)[0]

    assert result.status is MatchStatus.AMBIGUOUS
    assert result.candidate is None
    assert result.candidate_ids == ["a", "b"]
    assert [item.candidate.destination_id for item in result.alternatives] == ["a", "b"]


def test_variant_mismatch_is_not_a_probable_match_by_default() -> None:
    source_identity = CanonicalCardIdentity(
        card_name="Embermouse",
        set_name="Mythic Sparks",
        collector_number="1",
        finish=Finish.NORMAL,
    )
    reverse = DestinationCatalogRecord(
        destination_id="reverse",
        identity=source_identity.model_copy(
            update={"card_name": "embermous", "finish": Finish.REVERSE_HOLO}
        ),
    )

    result = match_collection(_collection(source_identity), [reverse])[0]

    assert result.status is MatchStatus.UNMATCHED


def test_rejected_probable_candidate_is_skipped_for_next_review() -> None:
    source_identity = CanonicalCardIdentity(
        card_name="Embermouse", set_name="Mythic Sparks", collector_number="1"
    )
    catalog = [
        DestinationCatalogRecord(
            destination_id=destination_id,
            identity=source_identity.model_copy(
                update={"card_name": name, "set_code": f"MSP-{destination_id}"}
            ),
        )
        for destination_id, name in (("best", "embermous"), ("next", "embermousee"))
    ]

    result = match_collection(
        _collection(source_identity),
        catalog,
        rejected={source_identity.fingerprint: {"best"}},
    )[0]

    assert result.status is MatchStatus.PROBABLE
    assert result.candidate is not None
    assert result.candidate.destination_id == "next"


def test_catalog_normalization_deduplicates_and_rejects_conflicting_ids() -> None:
    identity = CanonicalCardIdentity(
        card_name="Embermouse", set_name="Mythic Sparks", collector_number="1"
    )
    duplicate = DestinationCatalogRecord(destination_id="same", identity=identity)
    assert normalize_destination_catalog([duplicate, duplicate]) == [duplicate]

    conflict = DestinationCatalogRecord(
        destination_id="same", identity=identity.model_copy(update={"collector_number": "2"})
    )
    try:
        normalize_destination_catalog([duplicate, conflict])
    except ValueError as error:
        assert "conflicting identities" in str(error)
    else:
        raise AssertionError("conflicting destination ids must be rejected")
