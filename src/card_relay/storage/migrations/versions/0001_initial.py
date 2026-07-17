"""Initial local persistence schema."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None


def upgrade() -> None:
    op.create_table(
        "card_mappings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_fingerprint", sa.String(80), nullable=False),
        sa.Column("destination_name", sa.String(50), nullable=False),
        sa.Column("destination_id", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.UniqueConstraint("source_fingerprint", "destination_name"),
    )
    op.create_table(
        "source_snapshots",
        sa.Column("snapshot_id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_application", sa.String(50), nullable=False),
        sa.Column("ingestion_method", sa.String(20), nullable=False),
        sa.Column("collection_fingerprint", sa.String(80), nullable=False),
        sa.Column("total_unique_entries", sa.Integer(), nullable=False),
        sa.Column("total_quantity", sa.Integer(), nullable=False),
        sa.Column("completeness", sa.String(20), nullable=False),
        sa.Column("trusted", sa.Integer(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
    )
    op.create_table(
        "sync_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("destination_name", sa.String(50), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
    )
    op.create_table(
        "application_schema_version", sa.Column("version", sa.Integer(), primary_key=True)
    )


def downgrade() -> None:
    op.drop_table("application_schema_version")
    op.drop_table("sync_plans")
    op.drop_table("source_snapshots")
    op.drop_table("card_mappings")
