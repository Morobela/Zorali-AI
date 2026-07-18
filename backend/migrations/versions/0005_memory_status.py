"""Automatic memory extraction: review status on memories.

``memories.status``: "active" rows are searchable and feed the knowledge
graph (all pre-existing rows backfill to active); "pending" rows are
candidates auto-extracted from chat turns, shown in the Memory panel for
Accept/Reject, and never injected into prompts.

Revision ID: 0005_memory_status
Revises: 0004_session_summaries
Create Date: 2026-07-18
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_memory_status"
down_revision = "0004_session_summaries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "memories",
        sa.Column("status", sa.String(16), nullable=False, server_default="active", index=True),
    )


def downgrade() -> None:
    op.drop_column("memories", "status")
