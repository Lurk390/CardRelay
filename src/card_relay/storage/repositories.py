import json
from datetime import UTC, datetime

from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from card_relay.domain.enums import MatchStatus
from card_relay.domain.models import (
    CanonicalCardIdentity,
    CanonicalCollection,
    DestinationCatalogRecord,
    DestinationCollectionEntry,
    DestinationReadSnapshot,
    SourceSnapshot,
)
from card_relay.domain.operations import SyncPlan, SyncResult
from card_relay.domain.results import MatchResult
from card_relay.matching.normalization import normalize_destination_catalog
from card_relay.storage.models import (
    CatalogCacheEntryRow,
    CatalogCacheStateRow,
    DestinationReadSnapshotRow,
    MappingReviewRow,
    MappingRow,
    RejectedMappingRow,
    SnapshotRow,
    SyncPlanRow,
    SyncRunRow,
)


class MappingRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def confirm(self, fingerprint: str, destination: str, destination_id: str) -> None:
        with Session(self.engine) as session:
            row = session.scalar(
                select(MappingRow).where(
                    MappingRow.source_fingerprint == fingerprint,
                    MappingRow.destination_name == destination,
                )
            )
            if row and row.status == "rejected" and row.destination_id != destination_id:
                self._add_rejection(session, fingerprint, destination, row.destination_id)
            if row:
                row.destination_id, row.status = destination_id, "confirmed"
            else:
                session.add(
                    MappingRow(
                        source_fingerprint=fingerprint,
                        destination_name=destination,
                        destination_id=destination_id,
                    )
                )
            session.execute(
                delete(RejectedMappingRow).where(
                    RejectedMappingRow.source_fingerprint == fingerprint,
                    RejectedMappingRow.destination_name == destination,
                    RejectedMappingRow.destination_id == destination_id,
                )
            )
            self._clear_review(session, fingerprint, destination)
            session.commit()

    def list_confirmed(self, destination: str) -> dict[str, str]:
        with Session(self.engine) as session:
            rows = session.scalars(
                select(MappingRow).where(
                    MappingRow.destination_name == destination, MappingRow.status == "confirmed"
                )
            )
            return {row.source_fingerprint: row.destination_id for row in rows}

    def reject(self, fingerprint: str, destination: str, destination_id: str) -> None:
        with Session(self.engine) as session:
            row = session.scalar(
                select(MappingRow).where(
                    MappingRow.source_fingerprint == fingerprint,
                    MappingRow.destination_name == destination,
                )
            )
            if row and row.status == "rejected":
                self._add_rejection(session, fingerprint, destination, row.destination_id)
                session.delete(row)
            elif row and row.destination_id == destination_id:
                session.delete(row)
            self._add_rejection(session, fingerprint, destination, destination_id)
            self._clear_review(session, fingerprint, destination)
            session.commit()

    def list_rejected(self, destination: str) -> dict[str, set[str]]:
        with Session(self.engine) as session:
            rows = session.scalars(
                select(RejectedMappingRow).where(RejectedMappingRow.destination_name == destination)
            )
            result: dict[str, set[str]] = {}
            for row in rows:
                result.setdefault(row.source_fingerprint, set()).add(row.destination_id)
            legacy_rows = session.scalars(
                select(MappingRow).where(
                    MappingRow.destination_name == destination,
                    MappingRow.status == "rejected",
                )
            )
            for legacy_row in legacy_rows:
                result.setdefault(legacy_row.source_fingerprint, set()).add(
                    legacy_row.destination_id
                )
            return result

    def list_all(self) -> list[dict[str, str]]:
        with Session(self.engine) as session:
            records = [
                {
                    "source_fingerprint": row.source_fingerprint,
                    "destination": row.destination_name,
                    "destination_id": row.destination_id,
                    "status": row.status,
                }
                for row in session.scalars(select(MappingRow))
            ]
            records.extend(
                {
                    "source_fingerprint": row.source_fingerprint,
                    "destination": row.destination_name,
                    "destination_id": row.destination_id,
                    "status": "rejected",
                }
                for row in session.scalars(select(RejectedMappingRow))
            )
            return sorted(
                records,
                key=lambda item: (
                    item["destination"],
                    item["source_fingerprint"],
                    item["status"],
                    item["destination_id"],
                ),
            )

    @staticmethod
    def _add_rejection(
        session: Session, fingerprint: str, destination: str, destination_id: str
    ) -> None:
        exists = session.scalar(
            select(RejectedMappingRow.id).where(
                RejectedMappingRow.source_fingerprint == fingerprint,
                RejectedMappingRow.destination_name == destination,
                RejectedMappingRow.destination_id == destination_id,
            )
        )
        if exists is None:
            session.add(
                RejectedMappingRow(
                    source_fingerprint=fingerprint,
                    destination_name=destination,
                    destination_id=destination_id,
                )
            )

    @staticmethod
    def _clear_review(session: Session, fingerprint: str, destination: str) -> None:
        session.execute(
            delete(MappingReviewRow).where(
                MappingReviewRow.source_fingerprint == fingerprint,
                MappingReviewRow.destination_name == destination,
            )
        )


class MappingReviewRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def update(
        self,
        destination: str,
        collection: CanonicalCollection,
        results: list[MatchResult],
    ) -> None:
        identities = {entry.fingerprint: entry.identity for entry in collection.entries}
        with Session(self.engine) as session:
            for result in results:
                session.execute(
                    delete(MappingReviewRow).where(
                        MappingReviewRow.source_fingerprint == result.source_fingerprint,
                        MappingReviewRow.destination_name == destination,
                    )
                )
                if result.status not in {MatchStatus.PROBABLE, MatchStatus.AMBIGUOUS}:
                    continue
                identity = identities[result.source_fingerprint]
                session.add(
                    MappingReviewRow(
                        source_fingerprint=result.source_fingerprint,
                        destination_name=destination,
                        source_identity_json=identity.model_dump(mode="json"),
                        result_payload=result.model_dump_json(),
                    )
                )
            session.commit()

    def list_pending(self, destination: str | None = None) -> list[dict[str, object]]:
        with Session(self.engine) as session:
            statement = select(MappingReviewRow)
            if destination is not None:
                statement = statement.where(MappingReviewRow.destination_name == destination)
            rows = session.scalars(
                statement.order_by(
                    MappingReviewRow.destination_name, MappingReviewRow.source_fingerprint
                )
            )
            return [
                {
                    "source_fingerprint": row.source_fingerprint,
                    "destination": row.destination_name,
                    "source_identity": CanonicalCardIdentity.model_validate(
                        row.source_identity_json
                    ).model_dump(mode="json"),
                    "match": MatchResult.model_validate_json(row.result_payload).model_dump(
                        mode="json"
                    ),
                }
                for row in rows
            ]


class CatalogCacheRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def replace(self, destination: str, records: list[DestinationCatalogRecord]) -> datetime:
        normalized = normalize_destination_catalog(records)
        cached_at = datetime.now(UTC)
        with Session(self.engine) as session:
            session.execute(
                delete(CatalogCacheEntryRow).where(
                    CatalogCacheEntryRow.destination_name == destination
                )
            )
            state = session.get(CatalogCacheStateRow, destination)
            if state is None:
                session.add(
                    CatalogCacheStateRow(
                        destination_name=destination,
                        cached_at=cached_at,
                        record_count=len(normalized),
                    )
                )
            else:
                state.cached_at = cached_at
                state.record_count = len(normalized)
            session.add_all(
                [
                    CatalogCacheEntryRow(
                        destination_name=destination,
                        destination_id=record.destination_id,
                        identity_json=record.identity.model_dump(mode="json"),
                    )
                    for record in normalized
                ]
            )
            session.commit()
        return cached_at

    def get(self, destination: str) -> tuple[datetime, list[DestinationCatalogRecord]] | None:
        with Session(self.engine) as session:
            state = session.get(CatalogCacheStateRow, destination)
            if state is None:
                return None
            rows = session.scalars(
                select(CatalogCacheEntryRow)
                .where(CatalogCacheEntryRow.destination_name == destination)
                .order_by(CatalogCacheEntryRow.destination_id)
            )
            records = [
                DestinationCatalogRecord(
                    destination_id=row.destination_id,
                    identity=CanonicalCardIdentity.model_validate(row.identity_json),
                )
                for row in rows
            ]
            if len(records) != state.record_count:
                raise ValueError("destination catalog cache record count is inconsistent")
            cached_at = state.cached_at
            if cached_at.tzinfo is None:
                cached_at = cached_at.replace(tzinfo=UTC)
            return cached_at, records


class DestinationReadRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def replace(self, snapshot: DestinationReadSnapshot) -> None:
        catalog_payload = json.dumps(
            [record.model_dump(mode="json") for record in snapshot.catalog],
            sort_keys=True,
            separators=(",", ":"),
        )
        collection_payload = json.dumps(
            [record.model_dump(mode="json") for record in snapshot.collection],
            sort_keys=True,
            separators=(",", ":"),
        )
        with Session(self.engine) as session:
            row = session.get(DestinationReadSnapshotRow, snapshot.destination_name)
            if row is None:
                session.add(
                    DestinationReadSnapshotRow(
                        destination_name=snapshot.destination_name,
                        captured_at=snapshot.captured_at,
                        catalog_payload=catalog_payload,
                        collection_payload=collection_payload,
                        complete=int(snapshot.complete),
                        metadata_json=snapshot.metadata,
                    )
                )
            else:
                row.captured_at = snapshot.captured_at
                row.catalog_payload = catalog_payload
                row.collection_payload = collection_payload
                row.complete = int(snapshot.complete)
                row.metadata_json = snapshot.metadata
            session.commit()

    def get(self, destination: str) -> DestinationReadSnapshot | None:
        with Session(self.engine) as session:
            row = session.get(DestinationReadSnapshotRow, destination)
            if row is None:
                return None
            captured_at = row.captured_at
            if captured_at.tzinfo is None:
                captured_at = captured_at.replace(tzinfo=UTC)
            return DestinationReadSnapshot(
                destination_name=row.destination_name,
                captured_at=captured_at,
                catalog=[
                    DestinationCatalogRecord.model_validate(item)
                    for item in json.loads(row.catalog_payload)
                ],
                collection=[
                    DestinationCollectionEntry.model_validate(item)
                    for item in json.loads(row.collection_payload)
                ],
                complete=bool(row.complete),
                metadata=row.metadata_json,
            )


class SnapshotRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def add(self, snapshot: SourceSnapshot) -> None:
        with Session(self.engine) as session:
            session.add(
                SnapshotRow(
                    snapshot_id=snapshot.snapshot_id,
                    created_at=snapshot.created_at,
                    source_application=snapshot.source_application,
                    ingestion_method=snapshot.ingestion_method.value,
                    collection_fingerprint=snapshot.collection_fingerprint,
                    total_unique_entries=snapshot.total_unique_entries,
                    total_quantity=snapshot.total_quantity,
                    completeness=snapshot.completeness.value,
                    trusted=int(snapshot.trusted_for_destructive_planning),
                    metadata_json=snapshot.model_dump(mode="json"),
                )
            )
            session.commit()

    def latest_trusted(self, source_application: str = "collectr") -> SourceSnapshot | None:
        with Session(self.engine) as session:
            row = session.scalar(
                select(SnapshotRow)
                .where(
                    SnapshotRow.source_application == source_application,
                    SnapshotRow.trusted == 1,
                )
                .order_by(SnapshotRow.created_at.desc())
                .limit(1)
            )
            if row is None:
                return None
            return SourceSnapshot.model_validate(row.metadata_json)


class SyncAuditRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def add_plan(self, plan: SyncPlan) -> int:
        with Session(self.engine) as session:
            row = SyncPlanRow(
                destination_name=plan.destination,
                payload=plan.model_dump_json(),
            )
            session.add(row)
            session.commit()
            return row.id

    def add_run(self, plan_id: int, result: SyncResult) -> int:
        with Session(self.engine) as session:
            row = SyncRunRow(
                plan_id=plan_id,
                dry_run=int(result.dry_run),
                succeeded=int(result.succeeded),
                result_payload=result.model_dump_json(),
            )
            session.add(row)
            session.commit()
            return row.id

    def get_plan(self, plan_id: int) -> SyncPlan:
        with Session(self.engine) as session:
            row = session.get(SyncPlanRow, plan_id)
            if row is None:
                raise KeyError(f"sync plan {plan_id} does not exist")
            return SyncPlan.model_validate(json.loads(row.payload))
