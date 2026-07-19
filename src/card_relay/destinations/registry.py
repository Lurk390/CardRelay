from dataclasses import dataclass
from typing import Literal

from card_relay.destinations.capabilities import DestinationCapabilities
from card_relay.destinations.dex.adapter import DexAdapter
from card_relay.destinations.experimental import ExperimentalDestinationAdapter
from card_relay.destinations.mock import MockDestinationAdapter


@dataclass(frozen=True)
class DestinationDescriptor:
    name: str
    stability: Literal["production", "read_only", "experimental"]
    capabilities: DestinationCapabilities
    description: str


def destination_descriptors() -> list[DestinationDescriptor]:
    """Return deterministic, data-free capability discovery for shipped adapters."""

    return [
        DestinationDescriptor(
            name="dex",
            stability="read_only",
            capabilities=DexAdapter().get_capabilities(),
            description=(
                "Dex capture-backed adapter; browser extension handles confirmed safe writes."
            ),
        ),
        DestinationDescriptor(
            name="experimental",
            stability="experimental",
            capabilities=ExperimentalDestinationAdapter([]).get_capabilities(),
            description="In-memory Pokémon-only compatibility adapter; no external service calls.",
        ),
        DestinationDescriptor(
            name="mock",
            stability="production",
            capabilities=MockDestinationAdapter([]).get_capabilities(),
            description="Deterministic local file-backed test adapter.",
        ),
    ]
