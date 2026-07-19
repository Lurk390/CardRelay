from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from card_relay.domain.enums import MatchStatus
from card_relay.domain.models import (
    CanonicalCardIdentity,
    CanonicalCollection,
    DestinationCatalogRecord,
)
from card_relay.domain.results import MatchCandidateExplanation, MatchResult
from card_relay.matching.normalization import normalize_destination_catalog

_SCORE_EPSILON = 1e-9


@dataclass(frozen=True)
class _FieldComparison:
    name: str
    matched: bool
    weight: float
    similarity: float = 0.0


def match_collection(
    source: CanonicalCollection,
    catalog: list[DestinationCatalogRecord],
    saved: dict[str, str] | None = None,
    rejected: dict[str, set[str]] | None = None,
    *,
    minimum_probable_score: float = 0.92,
    allow_fuzzy_matching: bool = True,
    require_variant_match: bool = True,
    require_language_match: bool = True,
    ambiguity_score_margin: float = 0.02,
) -> list[MatchResult]:
    if not 0 <= minimum_probable_score <= 1:
        raise ValueError("minimum_probable_score must be between 0 and 1")
    if not 0 <= ambiguity_score_margin <= 1:
        raise ValueError("ambiguity_score_margin must be between 0 and 1")

    saved = saved or {}
    rejected = rejected or {}
    normalized_catalog = normalize_destination_catalog(catalog)
    by_id = {record.destination_id: record for record in normalized_catalog}
    results: list[MatchResult] = []
    for entry in sorted(source.entries, key=lambda item: item.fingerprint):
        fingerprint = entry.fingerprint
        saved_id = saved.get(fingerprint)
        saved_candidate = by_id.get(saved_id) if saved_id is not None else None
        if saved_candidate is not None and _has_strong_anchors(
            entry.identity, saved_candidate.identity
        ):
            candidate = saved_candidate
            explanation = _confirmed_explanation(entry.identity, candidate)
            results.append(
                MatchResult(
                    source_fingerprint=fingerprint,
                    status=MatchStatus.EXACT,
                    candidate=candidate,
                    score=1,
                    reasons=explanation.reasons,
                    matched_fields=explanation.matched_fields,
                    mismatched_fields=explanation.mismatched_fields,
                    candidate_ids=[candidate.destination_id],
                    alternatives=[explanation],
                )
            )
            continue

        excluded_ids = rejected.get(fingerprint, set())
        exact_candidates = [
            record
            for record in normalized_catalog
            if record.identity.fingerprint == entry.identity.fingerprint
            and record.destination_id not in excluded_ids
        ]
        if len(exact_candidates) == 1:
            candidate = exact_candidates[0]
            explanation = _exact_explanation(entry.identity, candidate)
            results.append(
                MatchResult(
                    source_fingerprint=fingerprint,
                    status=MatchStatus.EXACT,
                    candidate=candidate,
                    score=1,
                    reasons=explanation.reasons,
                    matched_fields=explanation.matched_fields,
                    mismatched_fields=explanation.mismatched_fields,
                    candidate_ids=[candidate.destination_id],
                    alternatives=[explanation],
                )
            )
            continue
        if len(exact_candidates) > 1:
            alternatives = [
                _exact_explanation(entry.identity, candidate, duplicate=True)
                for candidate in exact_candidates
            ]
            results.append(
                MatchResult(
                    source_fingerprint=fingerprint,
                    status=MatchStatus.AMBIGUOUS,
                    score=1,
                    reasons=["multiple exact candidates require review"],
                    candidate_ids=[item.candidate.destination_id for item in alternatives],
                    alternatives=alternatives,
                )
            )
            continue

        probable = (
            _probable_candidates(
                entry.identity,
                normalized_catalog,
                excluded_ids,
                require_variant_match=require_variant_match,
                require_language_match=require_language_match,
            )
            if allow_fuzzy_matching
            else []
        )
        qualifying = [item for item in probable if item.score >= minimum_probable_score]
        if qualifying:
            best = qualifying[0]
            competing = [
                item
                for item in qualifying
                if best.score - item.score <= ambiguity_score_margin + _SCORE_EPSILON
            ]
            if len(competing) == 1:
                results.append(
                    MatchResult(
                        source_fingerprint=fingerprint,
                        status=MatchStatus.PROBABLE,
                        candidate=best.candidate,
                        score=best.score,
                        reasons=["highest constrained composite score; confirmation required"],
                        matched_fields=best.matched_fields,
                        mismatched_fields=best.mismatched_fields,
                        candidate_ids=[best.candidate.destination_id],
                        alternatives=qualifying,
                    )
                )
            else:
                results.append(
                    MatchResult(
                        source_fingerprint=fingerprint,
                        status=MatchStatus.AMBIGUOUS,
                        score=best.score,
                        reasons=["top candidate scores are within the ambiguity margin"],
                        candidate_ids=[item.candidate.destination_id for item in competing],
                        alternatives=qualifying,
                    )
                )
            continue

        reasons = ["no exact or sufficiently strong composite match"]
        if saved_id is not None:
            reasons.append("confirmed mapping is absent or no longer satisfies identity anchors")
        if not allow_fuzzy_matching:
            reasons.append("probable matching is disabled")
        status = MatchStatus.REJECTED if excluded_ids else MatchStatus.UNMATCHED
        if status is MatchStatus.REJECTED:
            reasons.append("all previously reviewed candidates remain rejected")
        results.append(
            MatchResult(
                source_fingerprint=fingerprint,
                status=status,
                reasons=reasons,
                alternatives=probable[:5],
                candidate_ids=[item.candidate.destination_id for item in probable[:5]],
            )
        )
    return results


def _probable_candidates(
    source: CanonicalCardIdentity,
    catalog: list[DestinationCatalogRecord],
    rejected_ids: set[str],
    *,
    require_variant_match: bool,
    require_language_match: bool,
) -> list[MatchCandidateExplanation]:
    candidates: list[MatchCandidateExplanation] = []
    for record in catalog:
        if record.destination_id in rejected_ids:
            continue
        destination = record.identity
        if not _has_strong_anchors(source, destination):
            continue
        if require_language_match and source.language != destination.language:
            continue
        if require_variant_match and _variant_tuple(source) != _variant_tuple(destination):
            continue
        candidates.append(_score_candidate(source, record))
    return sorted(candidates, key=lambda item: (-item.score, item.candidate.destination_id))


def _has_strong_anchors(source: CanonicalCardIdentity, destination: CanonicalCardIdentity) -> bool:
    if source.game != destination.game or source.collector_number != destination.collector_number:
        return False
    if source.set_code and destination.set_code:
        return source.set_code == destination.set_code
    return source.set_name is not None and source.set_name == destination.set_name


def _variant_tuple(identity: CanonicalCardIdentity) -> tuple[Any, ...]:
    return (
        identity.finish,
        identity.edition,
        identity.grading_status,
        identity.grading_company,
        identity.grade,
        identity.certification_number,
        identity.promo,
        identity.signed,
        identity.altered,
    )


def _score_candidate(
    source: CanonicalCardIdentity, record: DestinationCatalogRecord
) -> MatchCandidateExplanation:
    destination = record.identity
    name_similarity = SequenceMatcher(None, source.card_name, destination.card_name).ratio()
    comparisons = [
        _FieldComparison("game", source.game == destination.game, 0.10),
        _FieldComparison("set", _same_set(source, destination), 0.20),
        _FieldComparison(
            "collector_number", source.collector_number == destination.collector_number, 0.25
        ),
        _FieldComparison(
            "card_name", source.card_name == destination.card_name, 0.20, name_similarity
        ),
        _FieldComparison("language", source.language == destination.language, 0.05),
        _FieldComparison("finish", source.finish == destination.finish, 0.08),
        _FieldComparison("edition", source.edition == destination.edition, 0.03),
        _FieldComparison("grading", _grading_tuple(source) == _grading_tuple(destination), 0.06),
        _FieldComparison("special_flags", _flag_tuple(source) == _flag_tuple(destination), 0.03),
    ]
    score = sum(item.weight * (1 if item.matched else item.similarity) for item in comparisons)
    matched = [item.name for item in comparisons if item.matched]
    mismatched = [item.name for item in comparisons if not item.matched]
    reasons = ["game, set, and collector number are exact required anchors"]
    if "card_name" in mismatched:
        reasons.append(f"normalized card-name similarity is {name_similarity:.3f}")
    return MatchCandidateExplanation(
        candidate=record,
        score=round(score, 6),
        reasons=reasons,
        matched_fields=matched,
        mismatched_fields=mismatched,
    )


def _same_set(source: CanonicalCardIdentity, destination: CanonicalCardIdentity) -> bool:
    if source.set_code and destination.set_code:
        return source.set_code == destination.set_code
    return source.set_name is not None and source.set_name == destination.set_name


def _grading_tuple(identity: CanonicalCardIdentity) -> tuple[Any, ...]:
    return (
        identity.grading_status,
        identity.grading_company,
        identity.grade,
        identity.certification_number,
    )


def _flag_tuple(identity: CanonicalCardIdentity) -> tuple[bool, bool, bool]:
    return identity.promo, identity.signed, identity.altered


def _exact_explanation(
    source: CanonicalCardIdentity,
    candidate: DestinationCatalogRecord,
    *,
    duplicate: bool = False,
) -> MatchCandidateExplanation:
    differences = _identity_differences(source, candidate.identity)
    reasons = [
        "duplicate exact canonical fingerprint" if duplicate else "exact canonical fingerprint"
    ]
    if differences:
        reasons.append("non-fingerprint catalog metadata differs: " + ", ".join(differences))
    return MatchCandidateExplanation(
        candidate=candidate,
        score=1,
        reasons=reasons,
        matched_fields=["canonical_fingerprint"],
        mismatched_fields=differences,
    )


def _confirmed_explanation(
    source: CanonicalCardIdentity, candidate: DestinationCatalogRecord
) -> MatchCandidateExplanation:
    differences = _identity_differences(source, candidate.identity)
    reasons = ["user-confirmed persistent mapping"]
    if differences:
        reasons.append("confirmed identity fields differ: " + ", ".join(differences))
    return MatchCandidateExplanation(
        candidate=candidate,
        score=1,
        reasons=reasons,
        matched_fields=["persistent_mapping"],
        mismatched_fields=differences,
    )


def _identity_differences(
    source: CanonicalCardIdentity, destination: CanonicalCardIdentity
) -> list[str]:
    source_fields = source.model_dump(mode="json")
    destination_fields = destination.model_dump(mode="json")
    return sorted(
        field for field, value in source_fields.items() if destination_fields[field] != value
    )
