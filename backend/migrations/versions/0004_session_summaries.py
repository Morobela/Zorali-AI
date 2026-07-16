"""Rolling per-session conversation summaries (context-window management).

``session_summaries``: when a chat session's history exceeds the
CONTEXT_MAX_TOKENS budget, turns older than the verbatim window are
compressed into one summary by a single LLM call; the row persists that
summary (plus how many messages it covers) so it is reused on later turns
instead of being recomputed.

Revision ID: 0004_session_summaries
Revises: 0003_memory_graph
Create Date: 2026-07-16
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_session_summaries"
down_revision = "0003_memory_graph"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "session_summaries",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(64), nullable=False, index=True),
        sa.Column("session_id", sa.String(128), nullable=False, index=True),
        sa.Column("owner_id", sa.String(64), nullable=False, index=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("covered_messages", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "session_id", name="uq_session_summary"),
    )


def downgrade() -> None:
    op.drop_table("session_summaries")
