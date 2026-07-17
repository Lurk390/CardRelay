from card_relay.domain.enums import ExtractionCompleteness, IngestionMethod
from card_relay.domain.models import SourceSnapshot
from card_relay.storage.database import create_database
from card_relay.storage.repositories import MappingRepository, SnapshotRepository


def test_mapping_persistence(tmp_path) -> None:
    engine = create_database(tmp_path / "test.db")
    repository = MappingRepository(engine)
    repository.confirm("v1:abc", "mock", "mock-1")
    assert repository.list_confirmed("mock") == {"v1:abc": "mock-1"}


def test_latest_trusted_snapshot_ignores_untrusted(tmp_path) -> None:
    engine = create_database(tmp_path / "snapshots.db")
    repository = SnapshotRepository(engine)
    trusted = SourceSnapshot(
        ingestion_method=IngestionMethod.CSV,
        source_schema_fingerprint="schema",
        parser_name="fixture",
        parser_version="1",
        completeness=ExtractionCompleteness.COMPLETE,
        total_unique_entries=2,
        total_quantity=2,
        collection_fingerprint="v1:trusted",
        trusted_for_destructive_planning=True,
    )
    repository.add(trusted)
    repository.add(
        trusted.model_copy(
            update={
                "snapshot_id": "untrusted",
                "collection_fingerprint": "v1:untrusted",
                "trusted_for_destructive_planning": False,
            }
        )
    )
    assert repository.latest_trusted() == trusted
