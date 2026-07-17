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
