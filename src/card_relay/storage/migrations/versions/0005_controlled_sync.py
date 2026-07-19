"""Add managed destination scope and recovery snapshots."""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"


def upgrade() -> None:
    op.create_table(
        "destination_backup_snapshots",
        sa.Column("backup_id", sa.String(36), primary_key=True),
        sa.Column("destination_name", sa.String(50), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("plan_confirmation_code", sa.String(20), nullable=False),
        sa.Column("collection_payload", sa.Text(), nullable=False),
    )
    op.create_index(
        "ix_destination_backup_snapshots_destination_name",
        "destination_backup_snapshots",
        ["destination_name"],
    )
    op.create_table(
        "managed_destination_records",
        sa.Column("destination_name", sa.String(50), primary_key=True),
        sa.Column("destination_id", sa.String(255), primary_key=True),
        sa.Column("source_fingerprint", sa.String(80), nullable=False),
        sa.Column("identity_json", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "source_collection_snapshots",
        sa.Column("snapshot_id", sa.String(36), primary_key=True),
        sa.Column("source_application", sa.String(50), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("collection_payload", sa.Text(), nullable=False),
    )
    op.create_index(
        "ix_source_collection_snapshots_source_application",
        "source_collection_snapshots",
        ["source_application"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_source_collection_snapshots_source_application",
        table_name="source_collection_snapshots",
    )
    op.drop_table("source_collection_snapshots")
    op.drop_table("managed_destination_records")
    op.drop_index(
        "ix_destination_backup_snapshots_destination_name",
        table_name="destination_backup_snapshots",
    )
    op.drop_table("destination_backup_snapshots")
