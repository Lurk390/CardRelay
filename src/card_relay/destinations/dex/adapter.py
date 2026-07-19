from sqlalchemy import Engine

from card_relay.destinations.capabilities import DestinationCapabilities
from card_relay.domain.models import (
    DestinationCatalogRecord,
    DestinationCollectionEntry,
    DestinationReadSnapshot,
)
from card_relay.domain.operations import SyncOperation, SyncResult
from card_relay.exceptions import IntegrationUnavailableError
from card_relay.storage.repositories import DestinationReadRepository


class DexAdapter:
    """Read-only Dex adapter backed by a validated local extension capture."""

    destination_name = "dex"

    def __init__(self, engine: Engine | None = None) -> None:
        self.engine = engine

    def get_capabilities(self) -> DestinationCapabilities:
        return DestinationCapabilities(
            supported_games=frozenset({"pokemon"}),
            catalog_retrieval=True,
            collection_retrieval=True,
        )

    def fetch_catalog(self) -> list[DestinationCatalogRecord]:
        return list(self._snapshot().catalog)

    def fetch_collection(self) -> list[DestinationCollectionEntry]:
        return list(self._snapshot().collection)

    def apply_operations(self, operations: list[SyncOperation], *, dry_run: bool) -> SyncResult:
        if not dry_run or operations:
            raise IntegrationUnavailableError("Dex writes are disabled in read-only Milestone 4")
        return SyncResult(results=[], dry_run=True)

    def _snapshot(self) -> DestinationReadSnapshot:
        if self.engine is None:
            raise IntegrationUnavailableError(
                "Dex read snapshot is unavailable; capture Dex with the browser extension first"
            )
        snapshot = DestinationReadRepository(self.engine).get("dex")
        if snapshot is None:
            raise IntegrationUnavailableError(
                "Dex read snapshot is unavailable; capture Dex with the browser extension first"
            )
        return snapshot
