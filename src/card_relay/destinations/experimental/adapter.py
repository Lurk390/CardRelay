"""Small in-memory adapter used to prove destination compatibility boundaries."""

from card_relay.destinations.capabilities import DestinationCapabilities
from card_relay.destinations.mock.adapter import MockDestinationAdapter
from card_relay.domain.models import DestinationCatalogRecord, DestinationCollectionEntry


class ExperimentalDestinationAdapter(MockDestinationAdapter):
    """A non-persistent Pokémon-only adapter with safe writes enabled.

    This is intentionally not an integration with a third-party service. It exercises
    adapter discovery and compatibility tests without adding another external contract.
    """

    destination_name = "experimental"

    def __init__(
        self,
        catalog: list[DestinationCatalogRecord],
        collection: list[DestinationCollectionEntry] | None = None,
    ) -> None:
        super().__init__(catalog, collection)

    def get_capabilities(self) -> DestinationCapabilities:
        return DestinationCapabilities(
            supported_games=frozenset({"pokemon"}),
            additions=True,
            quantity_increases=True,
            quantity_decreases=False,
            removals=False,
            rollback=False,
        )
