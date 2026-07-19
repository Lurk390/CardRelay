from collections.abc import Iterable

from card_relay.domain.models import DestinationCatalogRecord


def normalize_destination_catalog(
    records: Iterable[DestinationCatalogRecord],
) -> list[DestinationCatalogRecord]:
    """Validate, deduplicate, and deterministically order destination catalog records."""
    by_id: dict[str, DestinationCatalogRecord] = {}
    for supplied in records:
        record = DestinationCatalogRecord.model_validate(supplied.model_dump())
        previous = by_id.get(record.destination_id)
        if previous is not None and previous.identity != record.identity:
            raise ValueError(
                f"destination catalog id {record.destination_id!r} has conflicting identities"
            )
        by_id[record.destination_id] = record
    return [by_id[destination_id] for destination_id in sorted(by_id)]
