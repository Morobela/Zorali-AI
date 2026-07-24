"""Reality engine events + proactive notifications (capability map U3/U4).

``reality_events``: system-scoped rows produced by diffing consecutive
reality snapshots (service transitions, log error jumps, aging uncommitted
changes). ``notifications``: owner-scoped proactive messages fanned out to
admin/owner accounts for the notable events; ``read_at`` NULL means unread.

Revision ID: 0007_reality_notifications
Revises: 0006_chat_sessions
Create Date: 2026-07-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0007_reality_notifications"
down_revision = "0006_chat_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "owner_id", sa.String(64),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True,
        ),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "reality_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("kind", sa.String(64), nullable=False, index=True),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False, server_default="info"),
        sa.Column("detail", sa.Text(), nullable=False, server_default=""),
        sa.Column("data", JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True),
    )


def downgrade() -> None:
    op.drop_table("reality_events")
    op.drop_table("notifications")
