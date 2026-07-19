from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

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
    DestinationBackupSnapshot,
    DestinationCatalogRecord,
    DestinationCollectionEntry,
    SourceSnapshot,
)
from card_relay.domain.operations import OperationResult, SyncOperation, SyncPlan, SyncResult
from card_relay.domain.results import MatchResult
from card_relay.storage.database import create_database
from card_relay.storage.repositories import (
    CatalogCacheRepository,
    DestinationBackupRepository,
    ManagedDestinationRepository,
    MappingRepository,
    MappingReviewRepository,
    SnapshotRepository,
    SyncAuditRepository,
)


def test_mapping_persistence(tmp_path) -> None:
    engine = create_database(tmp_path / "test.db")
    repository = MappingRepository(engine)
    repository.confirm("v1:abc", "mock", "mock-1")
    assert repository.list_confirmed("mock") == {"v1:abc": "mock-1"}
    repository.reject("v1:abc", "mock", "mock-1")
    assert repository.list_confirmed("mock") == {}
    assert repository.list_rejected("mock") == {"v1:abc": {"mock-1"}}
    assert repository.list_all()[0]["status"] == "rejected"


def test_multiple_rejections_do_not_overwrite_confirmed_mapping(tmp_path) -> None:
    repository = MappingRepository(create_database(tmp_path / "mappings.db"))
    repository.reject("v2:source", "mock", "candidate-a")
    repository.reject("v2:source", "mock", "candidate-b")
    repository.confirm("v2:source", "mock", "candidate-c")

    assert repository.list_confirmed("mock") == {"v2:source": "candidate-c"}
    assert repository.list_rejected("mock") == {"v2:source": {"candidate-a", "candidate-b"}}


def test_mapping_review_queue_persists_explanations_and_clears_resolved_item(tmp_path) -> None:
    engine = create_database(tmp_path / "reviews.db")
    repository = MappingReviewRepository(engine)
    identity = CanonicalCardIdentity(
        card_name="Embermouse", set_name="Mythic Sparks", collector_number="1"
    )
    collection = CanonicalCollection(
        entries=[
            CanonicalCollectionEntry(
                identity=identity, quantity=1, ingestion_method=IngestionMethod.CSV
            )
        ]
    )
    candidate = DestinationCatalogRecord(destination_id="candidate", identity=identity)
    probable = MatchResult(
        source_fingerprint=identity.fingerprint,
        status=MatchStatus.PROBABLE,
        candidate=candidate,
        score=0.97,
        reasons=["confirmation required"],
        candidate_ids=["candidate"],
    )
    repository.update("mock", collection, [probable])

    pending = repository.list_pending("mock")
    assert len(pending) == 1
    assert pending[0]["source_identity"]["card_name"] == "embermouse"
    assert pending[0]["match"]["reasons"] == ["confirmation required"]

    repository.update(
        "mock",
        collection,
        [probable.model_copy(update={"status": MatchStatus.EXACT, "score": 1})],
    )
    assert repository.list_pending("mock") == []


def test_catalog_cache_replaces_records_atomically_and_preserves_empty_cache(tmp_path) -> None:
    repository = CatalogCacheRepository(create_database(tmp_path / "catalog.db"))
    identity = CanonicalCardIdentity(
        card_name="Embermouse", set_name="Mythic Sparks", collector_number="1"
    )
    records = [DestinationCatalogRecord(destination_id="card-1", identity=identity)]

    repository.replace("mock", records)
    cached = repository.get("mock")
    assert cached is not None
    assert cached[1] == records

    repository.replace("mock", [])
    empty = repository.get("mock")
    assert empty is not None
    assert empty[1] == []


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


def test_sync_plan_and_run_audit_round_trip(tmp_path) -> None:
    engine = create_database(tmp_path / "audit.db")
    repository = SyncAuditRepository(engine)
    plan = SyncPlan(
        source_completeness=ExtractionCompleteness.COMPLETE,
        destination="mock",
        operations=[],
    )
    plan_id = repository.add_plan(plan)
    run_id = repository.add_run(plan_id, SyncResult(results=[], dry_run=True))
    assert plan_id > 0
    assert run_id > 0
    assert repository.get_plan(plan_id) == plan


def test_managed_destination_scope_and_recovery_backup_round_trip(tmp_path: Path) -> None:
    engine = create_database(tmp_path / "controlled-sync.db")
    identity = CanonicalCardIdentity(
        card_name="Managed Fixture", set_name="Fixture Set", collector_number="1"
    )
    current = DestinationCollectionEntry(destination_id="managed-1", identity=identity, quantity=2)
    operation = SyncOperation(
        operation_type=OperationType.NO_CHANGE,
        fingerprint=identity.fingerprint,
        destination_id=current.destination_id,
        identity=identity,
        current_quantity=2,
        desired_quantity=2,
        reason="quantities already match",
    )
    plan = SyncPlan(
        source_completeness=ExtractionCompleteness.COMPLETE,
        destination="mock",
        operations=[operation],
    )

    managed = ManagedDestinationRepository(engine)
    managed.reconcile_successful_run(plan, SyncResult(results=[], dry_run=False))
    assert managed.list_ids("mock") == {"managed-1"}

    backup = DestinationBackupSnapshot(
        destination_name="mock",
        plan_confirmation_code=plan.confirmation_code,
        collection=[current],
    )
    backups = DestinationBackupRepository(engine)
    backups.add(backup)
    assert backups.latest("mock") == backup

    removal = operation.model_copy(
        update={
            "operation_type": OperationType.REMOVE,
            "desired_quantity": 0,
            "executable": True,
            "reason": "approved removal",
        }
    )
    removal_plan = plan.model_copy(update={"operations": [removal]})
    managed.reconcile_successful_run(
        removal_plan,
        SyncResult(
            results=[
                OperationResult(
                    operation_id=removal.operation_id,
                    succeeded=True,
                    message="applied",
                )
            ],
            dry_run=False,
        ),
    )
    assert managed.list_ids("mock") == set()


def test_alembic_upgrade_creates_milestone_three_tables(tmp_path: Path) -> None:
    database = tmp_path / "migrations.db"
    root = Path(__file__).parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option(
        "script_location", str(root / "src" / "card_relay" / "storage" / "migrations")
    )
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database.as_posix()}")

    command.upgrade(config, "0002")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO card_mappings "
                "(source_fingerprint, destination_name, destination_id, status) "
                "VALUES ('v2:legacy', 'mock', 'rejected-before-upgrade', 'rejected')"
            )
        )

    command.upgrade(config, "head")

    tables = set(inspect(engine).get_table_names())
    assert {
        "destination_catalog_cache_entries",
        "destination_catalog_cache_state",
        "mapping_reviews",
        "rejected_card_mappings",
        "destination_backup_snapshots",
        "managed_destination_records",
        "source_collection_snapshots",
    } <= tables
    repository = MappingRepository(engine)
    assert repository.list_rejected("mock") == {"v2:legacy": {"rejected-before-upgrade"}}
    repository.confirm("v2:legacy", "mock", "confirmed-after-upgrade")
    assert repository.list_confirmed("mock") == {"v2:legacy": "confirmed-after-upgrade"}
    assert repository.list_rejected("mock") == {"v2:legacy": {"rejected-before-upgrade"}}
