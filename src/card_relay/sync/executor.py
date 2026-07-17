from card_relay.destinations.base import DestinationAdapter
from card_relay.domain.operations import SyncPlan, SyncResult


def execute_plan(
    plan: SyncPlan, destination: DestinationAdapter, *, dry_run: bool = True
) -> SyncResult:
    return destination.apply_operations(plan.executable_operations, dry_run=dry_run)
