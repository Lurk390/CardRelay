"""Add normalized destination read snapshots."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"


def upgrade() -> None:
    op.create_table(
        "destination_read_snapshots",
        sa.Column("destination_name", sa.String(50), primary_key=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("catalog_payload", sa.Text(), nullable=False),
        sa.Column("collection_payload", sa.Text(), nullable=False),
        sa.Column("complete", sa.Integer(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("destination_read_snapshots")
