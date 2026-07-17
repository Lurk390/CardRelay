from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class MappingRow(Base):
    __tablename__ = "card_mappings"
    __table_args__ = (UniqueConstraint("source_fingerprint", "destination_name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    source_fingerprint: Mapped[str] = mapped_column(String(80))
    destination_name: Mapped[str] = mapped_column(String(50))
    destination_id: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="confirmed")


class SnapshotRow(Base):
    __tablename__ = "source_snapshots"
    snapshot_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_application: Mapped[str] = mapped_column(String(50))
    ingestion_method: Mapped[str] = mapped_column(String(20))
    collection_fingerprint: Mapped[str] = mapped_column(String(80))
    total_unique_entries: Mapped[int] = mapped_column(Integer)
    total_quantity: Mapped[int] = mapped_column(Integer)
    completeness: Mapped[str] = mapped_column(String(20))
    trusted: Mapped[int] = mapped_column(Integer, default=0)
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSON)


class SyncPlanRow(Base):
    __tablename__ = "sync_plans"
    id: Mapped[int] = mapped_column(primary_key=True)
    destination_name: Mapped[str] = mapped_column(String(50))
    payload: Mapped[str] = mapped_column(Text)


class SchemaVersionRow(Base):
    __tablename__ = "application_schema_version"
    version: Mapped[int] = mapped_column(primary_key=True)
