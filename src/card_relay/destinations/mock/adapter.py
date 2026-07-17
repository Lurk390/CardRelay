import json
from pathlib import Path

from card_relay.destinations.capabilities import DestinationCapabilities
from card_relay.domain.enums import OperationType
from card_relay.domain.models import DestinationCatalogRecord, DestinationCollectionEntry
from card_relay.domain.operations import OperationResult, SyncOperation, SyncResult


class MockDestinationAdapter:
    destination_name = "mock"

    def __init__(
        self,
        catalog: list[DestinationCatalogRecord],
        collection: list[DestinationCollectionEntry] | None = None,
    ) -> None:
        self.catalog = catalog
        self.collection = {entry.destination_id: entry for entry in collection or []}
        self.operation_log: list[SyncOperation] = []

    def get_capabilities(self) -> DestinationCapabilities:
        return DestinationCapabilities(
            additions=True, quantity_increases=True, quantity_decreases=True, removals=True
        )

    def fetch_catalog(self) -> list[DestinationCatalogRecord]:
        return list(self.catalog)

    def fetch_collection(self) -> list[DestinationCollectionEntry]:
        return list(self.collection.values())

    def apply_operations(self, operations: list[SyncOperation], *, dry_run: bool) -> SyncResult:
        results: list[OperationResult] = []
        catalog = {record.destination_id: record for record in self.catalog}
        for operation in operations:
            if not operation.executable:
                results.append(
                    OperationResult(
                        operation_id=operation.operation_id,
                        succeeded=False,
                        message="operation blocked",
                    )
                )
                continue
            if not dry_run and operation.destination_id:
                destination_id = operation.destination_id
                if operation.operation_type is OperationType.REMOVE:
                    self.collection.pop(destination_id, None)
                else:
                    record = catalog[destination_id]
                    self.collection[destination_id] = DestinationCollectionEntry(
                        destination_id=destination_id,
                        identity=record.identity,
                        quantity=operation.desired_quantity,
                    )
                self.operation_log.append(operation)
            results.append(
                OperationResult(
                    operation_id=operation.operation_id,
                    succeeded=True,
                    message="simulated" if dry_run else "applied",
                )
            )
        return SyncResult(results=results, dry_run=dry_run)


class FileBackedMockDestinationAdapter(MockDestinationAdapter):
    """A deterministic local adapter for CLI and end-to-end workflows."""

    def __init__(self, catalog: list[DestinationCatalogRecord], state_path: Path) -> None:
        self.state_path = state_path
        collection: list[DestinationCollectionEntry] = []
        if state_path.exists():
            payload = json.loads(state_path.read_text(encoding="utf-8"))
            collection = [DestinationCollectionEntry.model_validate(item) for item in payload]
        super().__init__(catalog, collection)

    def apply_operations(self, operations: list[SyncOperation], *, dry_run: bool) -> SyncResult:
        result = super().apply_operations(operations, dry_run=dry_run)
        if not dry_run and result.succeeded:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            payload = [
                entry.model_dump(mode="json")
                for entry in sorted(self.fetch_collection(), key=lambda item: item.destination_id)
            ]
            self.state_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return result
