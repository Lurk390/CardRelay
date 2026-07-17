from card_relay.destinations.capabilities import DestinationCapabilities
from card_relay.exceptions import IntegrationUnavailableError


class DexAdapter:
    """Read/write-disabled Milestone 1 contract scaffold."""

    destination_name = "dex"

    def get_capabilities(self) -> DestinationCapabilities:
        return DestinationCapabilities(catalog_retrieval=False, collection_retrieval=False)

    def fetch_catalog(self):  # type: ignore[no-untyped-def]
        raise IntegrationUnavailableError("Dex catalog behavior has not been researched")

    def fetch_collection(self):  # type: ignore[no-untyped-def]
        raise IntegrationUnavailableError("Dex collection behavior has not been researched")

    def apply_operations(self, operations, *, dry_run):  # type: ignore[no-untyped-def]
        raise IntegrationUnavailableError("Dex writes are disabled pending documented research")
