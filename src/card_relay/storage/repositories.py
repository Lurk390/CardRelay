from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from card_relay.domain.models import SourceSnapshot
from card_relay.storage.models import MappingRow, SnapshotRow


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
            session.commit()

    def list_confirmed(self, destination: str) -> dict[str, str]:
        with Session(self.engine) as session:
            rows = session.scalars(
                select(MappingRow).where(
                    MappingRow.destination_name == destination, MappingRow.status == "confirmed"
                )
            )
            return {row.source_fingerprint: row.destination_id for row in rows}


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
