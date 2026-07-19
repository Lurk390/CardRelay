from pydantic import BaseModel

from card_relay.domain.operations import SyncPlan


class SyncPreviewChange(BaseModel):
    operation_id: str
    change: str
    card: str
    set: str | None
    set_code: str | None
    collector_number: str
    finish: str
    current_quantity: int
    collectr_quantity: int
    quantity_delta: int
    executable: bool
    reason: str


def preview_changes(plan: SyncPlan) -> list[SyncPreviewChange]:
    return [
        SyncPreviewChange(
            operation_id=operation.operation_id,
            change=operation.operation_type.value,
            card=operation.identity.card_name,
            set=operation.identity.set_name,
            set_code=operation.identity.set_code,
            collector_number=operation.identity.collector_number,
            finish=operation.identity.finish.value,
            current_quantity=operation.current_quantity,
            collectr_quantity=operation.desired_quantity,
            quantity_delta=operation.desired_quantity - operation.current_quantity,
            executable=operation.executable,
            reason=operation.reason,
        )
        for operation in plan.operations
    ]
