from pydantic import BaseModel, Field

from card_relay.domain.enums import ExtractionCompleteness
from card_relay.domain.models import SourceSnapshot
from card_relay.sync.policy import SyncPolicy


class SourceSafetyAssessment(BaseModel):
    destructive_planning_allowed: bool
    collection_drop_percent: float = 0
    warnings: list[str] = Field(default_factory=list)


def assess_source_snapshot(
    current: SourceSnapshot,
    previous: SourceSnapshot | None,
    policy: SyncPolicy,
) -> SourceSafetyAssessment:
    warnings = list(current.warnings)
    complete = current.completeness is ExtractionCompleteness.COMPLETE
    allowed = complete and current.trusted_for_destructive_planning
    if not complete:
        warnings.append("source extraction is not complete")
    elif not current.trusted_for_destructive_planning:
        warnings.append("source extraction is not approved for destructive planning")
    if previous is None or previous.total_quantity == 0:
        return SourceSafetyAssessment(
            destructive_planning_allowed=allowed,
            warnings=warnings,
        )
    reduction = max(previous.total_quantity - current.total_quantity, 0)
    drop_percent = reduction / previous.total_quantity * 100
    if drop_percent >= policy.collection_drop_warning_percent and reduction:
        warnings.append(
            f"source quantity dropped {drop_percent:.1f}% from the latest trusted snapshot"
        )
    if drop_percent >= policy.collection_drop_failure_percent and reduction:
        allowed = False
        warnings.append("collection-drop failure threshold reached; destructive planning blocked")
    return SourceSafetyAssessment(
        destructive_planning_allowed=allowed,
        collection_drop_percent=drop_percent,
        warnings=warnings,
    )
