from typing import Protocol

from card_relay.destinations.capabilities import DestinationCapabilities
from card_relay.domain.models import DestinationCatalogRecord, DestinationCollectionEntry
from card_relay.domain.operations import SyncOperation, SyncResult


class DestinationAdapter(Protocol):
    destination_name: str

    def get_capabilities(self) -> DestinationCapabilities: ...
    def fetch_catalog(self) -> list[DestinationCatalogRecord]: ...
    def fetch_collection(self) -> list[DestinationCollectionEntry]: ...
    def apply_operations(self, operations: list[SyncOperation], *, dry_run: bool) -> SyncResult: ...
