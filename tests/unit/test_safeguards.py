from card_relay.domain.enums import ExtractionCompleteness, IngestionMethod
from card_relay.domain.models import SourceSnapshot
from card_relay.sync.policy import SyncPolicy
from card_relay.sync.safeguards import assess_source_snapshot


def snapshot(quantity: int, completeness: ExtractionCompleteness) -> SourceSnapshot:
    return SourceSnapshot(
        ingestion_method=IngestionMethod.CSV,
        source_schema_fingerprint="schema",
        parser_name="fixture",
        parser_version="1",
        completeness=completeness,
        total_unique_entries=quantity,
        total_quantity=quantity,
        collection_fingerprint=f"v1:{quantity}",
        trusted_for_destructive_planning=completeness is ExtractionCompleteness.COMPLETE,
    )


def test_large_collection_drop_blocks_destructive_planning() -> None:
    assessment = assess_source_snapshot(
        snapshot(70, ExtractionCompleteness.COMPLETE),
        snapshot(100, ExtractionCompleteness.COMPLETE),
        SyncPolicy(),
    )
    assert assessment.collection_drop_percent == 30
    assert not assessment.destructive_planning_allowed
    assert any("failure threshold" in warning for warning in assessment.warnings)


def test_incomplete_source_is_never_trusted_without_history() -> None:
    assessment = assess_source_snapshot(
        snapshot(10, ExtractionCompleteness.INCOMPLETE), None, SyncPolicy()
    )
    assert not assessment.destructive_planning_allowed


def test_small_drop_remains_allowed() -> None:
    assessment = assess_source_snapshot(
        snapshot(95, ExtractionCompleteness.COMPLETE),
        snapshot(100, ExtractionCompleteness.COMPLETE),
        SyncPolicy(),
    )
    assert assessment.destructive_planning_allowed
    assert not assessment.warnings


def test_complete_browser_snapshot_remains_blocked_pending_reliability_approval() -> None:
    current = snapshot(100, ExtractionCompleteness.COMPLETE).model_copy(
        update={
            "ingestion_method": IngestionMethod.BROWSER,
            "trusted_for_destructive_planning": False,
        }
    )

    assessment = assess_source_snapshot(current, None, SyncPolicy())

    assert not assessment.destructive_planning_allowed
    assert any("not approved" in warning for warning in assessment.warnings)
