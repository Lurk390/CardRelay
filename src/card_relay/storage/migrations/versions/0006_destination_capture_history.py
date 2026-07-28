"""Add timestamped destination capture history."""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"


def upgrade() -> None:
    op.create_table(
        "destination_capture_snapshots",
        sa.Column("snapshot_id", sa.String(36), primary_key=True),
        sa.Column("destination_name", sa.String(50), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("collection_payload", sa.Text(), nullable=False),
        sa.Column("complete", sa.Integer(), nullable=False),
    )
    op.create_index(
        "ix_destination_capture_snapshots_destination_name",
        "destination_capture_snapshots",
        ["destination_name"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_destination_capture_snapshots_destination_name",
        table_name="destination_capture_snapshots",
    )
    op.drop_table("destination_capture_snapshots")
