"""Add sync execution audit records."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"


def upgrade() -> None:
    op.create_table(
        "sync_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("dry_run", sa.Integer(), nullable=False),
        sa.Column("succeeded", sa.Integer(), nullable=False),
        sa.Column("result_payload", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("sync_runs")
