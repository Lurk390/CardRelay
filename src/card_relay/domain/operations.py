import hashlib
import json

from pydantic import BaseModel, Field, model_validator

from card_relay.domain.enums import ExtractionCompleteness, OperationType


class SyncOperation(BaseModel):
    operation_id: str = ""
    operation_type: OperationType
    fingerprint: str
    destination_id: str | None = None
    current_quantity: int = Field(ge=0)
    desired_quantity: int = Field(ge=0)
    executable: bool = False
    reason: str

    @model_validator(mode="after")
    def create_deterministic_id(self) -> "SyncOperation":
        if self.operation_id:
            return self
        payload = json.dumps(
            {
                "operation_type": self.operation_type.value,
                "fingerprint": self.fingerprint,
                "destination_id": self.destination_id,
                "current_quantity": self.current_quantity,
                "desired_quantity": self.desired_quantity,
                "executable": self.executable,
                "reason": self.reason,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        self.operation_id = f"op-v1:{hashlib.sha256(payload.encode()).hexdigest()}"
        return self


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
