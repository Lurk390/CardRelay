from card_relay.exceptions import IntegrationUnavailableError


class CollectrBrowserSource:
    """Milestone 1 fail-closed scaffold; no live selectors or endpoints are assumed."""

    source_name = "collectr"

    def validate_access(self):  # type: ignore[no-untyped-def]
        raise IntegrationUnavailableError(
            "Collectr browser ingestion is scaffolded for Milestone 2"
        )

    def load_collection(self):  # type: ignore[no-untyped-def]
        raise IntegrationUnavailableError(
            "Collectr browser ingestion is scaffolded for Milestone 2"
        )

    def create_snapshot(self):  # type: ignore[no-untyped-def]
        raise IntegrationUnavailableError(
            "Collectr browser ingestion is scaffolded for Milestone 2"
        )
