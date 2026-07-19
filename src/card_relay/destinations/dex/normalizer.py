import re

from card_relay.destinations.dex.models import DexCapturedCard, DexCapturedCollectionEntry
from card_relay.domain.enums import Finish
from card_relay.domain.models import (
    CanonicalCardIdentity,
    DestinationCatalogRecord,
    DestinationCollectionEntry,
)

_FINISH_ALIASES = {
    "normal": Finish.NORMAL,
    "non holo": Finish.NORMAL,
    "nonholo": Finish.NORMAL,
    "foil": Finish.FOIL,
    "holo": Finish.HOLO,
    "holofoil": Finish.HOLO,
    "reverse holo": Finish.REVERSE_HOLO,
    "reverse holofoil": Finish.REVERSE_HOLO,
    "master ball reverse holo": Finish.MASTER_BALL_REVERSE_HOLO,
    "cracked ice": Finish.CRACKED_ICE,
    "cosmos holo": Finish.COSMOS_HOLO,
    "stamped": Finish.STAMPED,
    "promo": Finish.PROMO,
}


def normalize_dex_finish(value: str) -> Finish | None:
    key = re.sub(r"[_-]+", " ", value).strip().casefold()
    key = " ".join(key.split())
    return _FINISH_ALIASES.get(key)


def dex_destination_id(card_id: str, finish: Finish) -> str:
    return f"{card_id}::{finish.value}"


def normalize_dex_catalog(
    cards: list[DexCapturedCard],
) -> tuple[list[DestinationCatalogRecord], list[str]]:
    records: dict[str, DestinationCatalogRecord] = {}
    unsupported: set[str] = set()
    for card in cards:
        for variant in card.variants:
            label = variant.name or variant.type
            finish = normalize_dex_finish(label)
            if finish is None:
                unsupported.add(label)
                continue
            identity = _identity(card, finish)
            destination_id = dex_destination_id(card.card_id, finish)
            record = DestinationCatalogRecord(destination_id=destination_id, identity=identity)
            previous = records.get(destination_id)
            if previous is not None and previous != record:
                raise ValueError(
                    f"Dex destination id {destination_id!r} has conflicting identities"
                )
            records[destination_id] = record
    return [records[key] for key in sorted(records)], sorted(unsupported, key=str.casefold)


def normalize_dex_collection(
    entries: list[DexCapturedCollectionEntry],
) -> tuple[list[DestinationCollectionEntry], list[str]]:
    records: dict[str, DestinationCollectionEntry] = {}
    unsupported: set[str] = set()
    for entry in entries:
        for quantity_key, quantity in entry.quantities.items():
            if quantity == 0:
                continue
            finish = normalize_dex_finish(quantity_key)
            if finish is None:
                unsupported.add(quantity_key)
                continue
            destination_id = dex_destination_id(entry.card_id, finish)
            record = DestinationCollectionEntry(
                destination_id=destination_id,
                identity=_identity(entry.card, finish),
                quantity=quantity,
            )
            previous = records.get(destination_id)
            if previous is not None and previous != record:
                raise ValueError(f"Dex collection id {destination_id!r} has conflicting records")
            records[destination_id] = record
    return [records[key] for key in sorted(records)], sorted(unsupported, key=str.casefold)


def _identity(card: DexCapturedCard, finish: Finish) -> CanonicalCardIdentity:
    return CanonicalCardIdentity(
        game="pokemon",
        card_name=card.name,
        set_name=card.set.name,
        set_code=card.set.set_id,
        collector_number=card.number,
        language="unknown",
        finish=finish,
    )
