import hashlib
import json

from pydantic import BaseModel, Field, model_validator

from card_relay.domain.enums import ExtractionCompleteness, OperationType
from card_relay.domain.identifiers import stable_fingerprint
from card_relay.domain.models import CanonicalCardIdentity, DestinationCollectionEntry

DESTRUCTIVE_OPERATION_TYPES = frozenset({OperationType.DECREASE, OperationType.REMOVE})
SAFE_WRITE_OPERATION_TYPES = frozenset({OperationType.ADD, OperationType.INCREASE})


class SyncOperation(BaseModel):
    operation_id: str = ""
    operation_type: OperationType
    fingerprint: str
    destination_id: str | None = None
    identity: CanonicalCardIdentity
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
    source_collection_fingerprint: str = ""
    destination_collection_fingerprint: str = ""
    operations: list[SyncOperation]
    warnings: list[str] = Field(default_factory=list)

    @property
    def executable_operations(self) -> list[SyncOperation]:
        return [operation for operation in self.operations if operation.executable]

    @property
    def safe_write_operations(self) -> list[SyncOperation]:
        return [
            operation
            for operation in self.executable_operations
            if operation.operation_type in SAFE_WRITE_OPERATION_TYPES
        ]

    @property
    def destructive_operations(self) -> list[SyncOperation]:
        return [
            operation
            for operation in self.executable_operations
            if operation.operation_type in DESTRUCTIVE_OPERATION_TYPES
        ]

    @property
    def confirmation_code(self) -> str:
        fingerprint = stable_fingerprint(
            {
                "destination": self.destination,
                "source": self.source_collection_fingerprint,
                "destination_state": self.destination_collection_fingerprint,
                "operations": [operation.operation_id for operation in self.operations],
            }
        )
        return fingerprint.split(":", 1)[-1][:12].upper()


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


def destination_collection_fingerprint(
    collection: list[DestinationCollectionEntry],
) -> str:
    return stable_fingerprint(
        {
            entry.destination_id: {
                "identity": entry.identity.fingerprint,
                "quantity": entry.quantity,
            }
            for entry in sorted(collection, key=lambda item: item.destination_id)
        }
    )
