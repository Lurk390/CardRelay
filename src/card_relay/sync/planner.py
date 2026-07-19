from card_relay.destinations.capabilities import DestinationCapabilities
from card_relay.domain.enums import ExtractionCompleteness, MatchStatus, OperationType
from card_relay.domain.models import (
    CanonicalCollection,
    DestinationCollectionEntry,
    collection_fingerprint,
)
from card_relay.domain.operations import (
    SyncOperation,
    SyncPlan,
    destination_collection_fingerprint,
)
from card_relay.domain.results import MatchResult
from card_relay.sync.policy import SyncPolicy


def build_plan(
    source: CanonicalCollection,
    destination: list[DestinationCollectionEntry],
    matches: list[MatchResult],
    capabilities: DestinationCapabilities,
    policy: SyncPolicy,
    destination_name: str = "mock",
    destructive_planning_allowed: bool = True,
    managed_destination_ids: set[str] | None = None,
) -> SyncPlan:
    entries = {entry.fingerprint: entry for entry in source.entries}
    actual = {entry.destination_id: entry for entry in destination}
    matched_ids: set[str] = set()
    operations: list[SyncOperation] = []
    destructive_allowed = (
        source.completeness is ExtractionCompleteness.COMPLETE and destructive_planning_allowed
    )
    for match in sorted(matches, key=lambda item: item.source_fingerprint):
        desired = entries[match.source_fingerprint]
        if not capabilities.supports_game(desired.identity.game):
            operations.append(
                SyncOperation(
                    operation_type=OperationType.UNSUPPORTED,
                    fingerprint=desired.fingerprint,
                    identity=desired.identity,
                    current_quantity=0,
                    desired_quantity=desired.quantity,
                    reason=(f"{destination_name} does not support game: {desired.identity.game}"),
                )
            )
            continue
        if match.status is not MatchStatus.EXACT or match.candidate is None:
            operations.append(
                SyncOperation(
                    operation_type=OperationType.MANUAL_REVIEW,
                    fingerprint=desired.fingerprint,
                    identity=desired.identity,
                    current_quantity=0,
                    desired_quantity=desired.quantity,
                    reason=f"match status: {match.status.value}",
                )
            )
            continue
        destination_id = match.candidate.destination_id
        matched_ids.add(destination_id)
        current = actual.get(destination_id)
        current_quantity = current.quantity if current else 0
        delta = desired.quantity - current_quantity
        if delta == 0:
            kind, executable, reason = OperationType.NO_CHANGE, False, "quantities already match"
        elif delta > 0 and current_quantity == 0:
            kind, executable, reason = (
                OperationType.ADD,
                policy.allow_additions and capabilities.additions,
                "safe addition",
            )
        elif delta > 0:
            kind, executable, reason = (
                OperationType.INCREASE,
                policy.allow_quantity_increases and capabilities.quantity_increases,
                "safe quantity increase",
            )
        else:
            allowed = (
                destructive_allowed
                and policy.allow_quantity_decreases
                and capabilities.quantity_decreases
            )
            kind, executable, reason = (
                OperationType.DECREASE,
                allowed,
                "explicit quantity-decrease policy required"
                if not allowed
                else "approved quantity decrease",
            )
        operations.append(
            SyncOperation(
                operation_type=kind,
                fingerprint=desired.fingerprint,
                destination_id=destination_id,
                identity=desired.identity,
                current_quantity=current_quantity,
                desired_quantity=desired.quantity,
                executable=executable,
                reason=reason,
            )
        )
    supported_actual = [
        entry for entry in actual.values() if capabilities.supports_game(entry.identity.game)
    ]
    managed_ids = managed_destination_ids or set()
    destination_only = [
        entry for entry in supported_actual if entry.destination_id not in matched_ids
    ]
    removal_candidates = [
        entry for entry in destination_only if entry.destination_id in managed_ids
    ]
    removal_percent = (
        len(removal_candidates) / len(supported_actual) * 100 if supported_actual else 0
    )
    removal_threshold_ok = (
        len(removal_candidates) <= policy.maximum_removal_count
        and removal_percent <= policy.maximum_removal_percent
    )
    for current in sorted(removal_candidates, key=lambda item: item.destination_id):
        allowed = (
            destructive_allowed
            and policy.allow_removals
            and capabilities.removals
            and removal_threshold_ok
        )
        operations.append(
            SyncOperation(
                operation_type=OperationType.REMOVE,
                fingerprint=current.identity.fingerprint,
                destination_id=current.destination_id,
                identity=current.identity,
                current_quantity=current.quantity,
                desired_quantity=0,
                executable=allowed,
                reason="approved removal"
                if allowed
                else "removal blocked by safety policy or threshold",
            )
        )
    for current in sorted(
        (entry for entry in destination_only if entry.destination_id not in managed_ids),
        key=lambda item: item.destination_id,
    ):
        operations.append(
            SyncOperation(
                operation_type=OperationType.MANUAL_REVIEW,
                fingerprint=current.identity.fingerprint,
                destination_id=current.destination_id,
                identity=current.identity,
                current_quantity=current.quantity,
                desired_quantity=0,
                reason="destination-only record is not in CardRelay's managed sync scope",
            )
        )
    warnings: list[str] = []
    if not destructive_allowed:
        warning = (
            "source is not complete; all destructive operations are blocked"
            if source.completeness is not ExtractionCompleteness.COMPLETE
            else "source is not approved for destructive planning"
        )
        warnings.append(warning)
    return SyncPlan(
        source_completeness=source.completeness,
        destination=destination_name,
        source_collection_fingerprint=collection_fingerprint(source),
        destination_collection_fingerprint=destination_collection_fingerprint(destination),
        operations=operations,
        warnings=warnings,
    )
