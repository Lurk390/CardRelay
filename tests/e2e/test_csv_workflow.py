from pathlib import Path

from card_relay.destinations.mock.adapter import MockDestinationAdapter
from card_relay.domain.models import DestinationCatalogRecord
from card_relay.matching.matcher import match_collection
from card_relay.sources.collectr.csv_source import CollectrCsvSource
from card_relay.sync.executor import execute_plan
from card_relay.sync.planner import build_plan
from card_relay.sync.policy import SyncPolicy


def test_safe_sync_is_idempotent() -> None:
    path = Path(__file__).parents[1] / "fixtures" / "collectr" / "alternate_export.csv"
    source = CollectrCsvSource(path).load_collection()
    catalog = [
        DestinationCatalogRecord(destination_id=f"mock-{index}", identity=entry.identity)
        for index, entry in enumerate(source.entries)
    ]
    destination = MockDestinationAdapter(catalog)
    matches = match_collection(source, destination.fetch_catalog())
    plan = build_plan(
        source,
        destination.fetch_collection(),
        matches,
        destination.get_capabilities(),
        SyncPolicy(),
    )
    assert len(plan.executable_operations) == 2
    assert execute_plan(plan, destination, dry_run=False).succeeded
    second = build_plan(
        source,
        destination.fetch_collection(),
        matches,
        destination.get_capabilities(),
        SyncPolicy(),
    )
    assert not second.executable_operations
