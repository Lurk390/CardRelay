import re

from card_relay.destinations.dex.models import (
    DexCapturedCard,
    DexCapturedCollectionEntry,
    DexWriteCollectionRecord,
    DexWriteMetadata,
)
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
    value = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value)
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


def build_dex_write_metadata(
    cards: list[DexCapturedCard],
    entries: list[DexCapturedCollectionEntry],
) -> DexWriteMetadata:
    collection_records: dict[str, DexWriteCollectionRecord] = {}
    quantity_key_candidates: dict[str, set[str]] = {}
    for entry in entries:
        record = DexWriteCollectionRecord(
            record_id=entry.id,
            card_id=entry.card_id,
            quantities=dict(entry.quantities),
        )
        previous = collection_records.get(entry.card_id)
        if previous is not None and previous != record:
            raise ValueError(f"Dex card id {entry.card_id!r} has conflicting collection records")
        collection_records[entry.card_id] = record
        for raw_key in entry.quantities:
            finish = normalize_dex_finish(raw_key)
            if finish is not None:
                destination_id = dex_destination_id(entry.card_id, finish)
                quantity_key_candidates.setdefault(destination_id, set()).add(raw_key)
    for card in cards:
        for variant in card.variants:
            label = variant.name or variant.type
            finish = normalize_dex_finish(label)
            if finish is None:
                continue
            destination_id = dex_destination_id(card.card_id, finish)
            quantity_key_candidates.setdefault(destination_id, set()).add(_lower_camel(label))
    quantity_keys = {
        destination_id: next(iter(candidates))
        for destination_id, candidates in quantity_key_candidates.items()
        if len(candidates) == 1
    }
    ambiguous = sorted(
        destination_id
        for destination_id, candidates in quantity_key_candidates.items()
        if len(candidates) > 1
    )
    return DexWriteMetadata(
        collection_records=collection_records,
        quantity_keys=quantity_keys,
        ambiguous_destination_ids=ambiguous,
    )


def _lower_camel(value: str) -> str:
    expanded = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value)
    words: list[str] = re.findall(r"[A-Za-z0-9]+", expanded)
    if not words:
        raise ValueError("Dex variant label cannot produce a quantity key")
    return words[0].casefold() + "".join(word[:1].upper() + word[1:] for word in words[1:])


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
