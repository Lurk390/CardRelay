from card_relay.domain.enums import MatchStatus
from card_relay.domain.models import CanonicalCollection, DestinationCatalogRecord
from card_relay.domain.results import MatchResult


def match_collection(
    source: CanonicalCollection,
    catalog: list[DestinationCatalogRecord],
    saved: dict[str, str] | None = None,
) -> list[MatchResult]:
    saved = saved or {}
    by_id = {record.destination_id: record for record in catalog}
    results: list[MatchResult] = []
    for entry in sorted(source.entries, key=lambda item: item.fingerprint):
        if entry.fingerprint in saved and saved[entry.fingerprint] in by_id:
            candidate = by_id[saved[entry.fingerprint]]
            results.append(
                MatchResult(
                    source_fingerprint=entry.fingerprint,
                    status=MatchStatus.EXACT,
                    candidate=candidate,
                    score=1,
                    reasons=["saved mapping"],
                    candidate_ids=[candidate.destination_id],
                )
            )
            continue
        candidates = [
            record
            for record in catalog
            if record.identity.fingerprint == entry.identity.fingerprint
        ]
        if len(candidates) == 1:
            candidate = candidates[0]
            results.append(
                MatchResult(
                    source_fingerprint=entry.fingerprint,
                    status=MatchStatus.EXACT,
                    candidate=candidate,
                    score=1,
                    reasons=["exact canonical identity"],
                    matched_fields=["identity"],
                    candidate_ids=[candidate.destination_id],
                )
            )
        elif len(candidates) > 1:
            results.append(
                MatchResult(
                    source_fingerprint=entry.fingerprint,
                    status=MatchStatus.AMBIGUOUS,
                    reasons=["multiple exact candidates"],
                    candidate_ids=sorted(c.destination_id for c in candidates),
                )
            )
        else:
            results.append(
                MatchResult(
                    source_fingerprint=entry.fingerprint,
                    status=MatchStatus.UNMATCHED,
                    reasons=["no exact variant-sensitive identity"],
                )
            )
    return results
