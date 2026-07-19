"""Add persistent matching review, rejected candidates, and catalog cache."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"


def upgrade() -> None:
    op.create_table(
        "rejected_card_mappings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_fingerprint", sa.String(80), nullable=False),
        sa.Column("destination_name", sa.String(50), nullable=False),
        sa.Column("destination_id", sa.String(255), nullable=False),
        sa.UniqueConstraint("source_fingerprint", "destination_name", "destination_id"),
    )
    op.create_table(
        "mapping_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_fingerprint", sa.String(80), nullable=False),
        sa.Column("destination_name", sa.String(50), nullable=False),
        sa.Column("source_identity_json", sa.JSON(), nullable=False),
        sa.Column("result_payload", sa.Text(), nullable=False),
        sa.UniqueConstraint("source_fingerprint", "destination_name"),
    )
    op.create_table(
        "destination_catalog_cache_state",
        sa.Column("destination_name", sa.String(50), primary_key=True),
        sa.Column("cached_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
    )
    op.create_table(
        "destination_catalog_cache_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("destination_name", sa.String(50), nullable=False),
        sa.Column("destination_id", sa.String(255), nullable=False),
        sa.Column("identity_json", sa.JSON(), nullable=False),
        sa.UniqueConstraint("destination_name", "destination_id"),
    )


def downgrade() -> None:
    op.drop_table("destination_catalog_cache_entries")
    op.drop_table("destination_catalog_cache_state")
    op.drop_table("mapping_reviews")
    op.drop_table("rejected_card_mappings")
