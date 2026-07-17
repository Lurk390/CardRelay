from uuid import uuid4

from pydantic import BaseModel, Field

from card_relay.domain.enums import ExtractionCompleteness, OperationType


class SyncOperation(BaseModel):
    operation_id: str = Field(default_factory=lambda: str(uuid4()))
    operation_type: OperationType
    fingerprint: str
    destination_id: str | None = None
    current_quantity: int = Field(ge=0)
    desired_quantity: int = Field(ge=0)
    executable: bool = False
    reason: str


class SyncPlan(BaseModel):
    source_completeness: ExtractionCompleteness
    destination: str
    operations: list[SyncOperation]
    warnings: list[str] = Field(default_factory=list)

    @property
    def executable_operations(self) -> list[SyncOperation]:
        return [operation for operation in self.operations if operation.executable]


class OperationResult(BaseModel):
    operation_id: str
    succeeded: bool
    message: str


class SyncResult(BaseModel):
    results: list[OperationResult]
    dry_run: bool

    @property
    def succeeded(self) -> bool:
        return all(result.succeeded for result in self.results)
