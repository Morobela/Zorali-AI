"""Inbound event inbox (capability map U5).

``inbound_events``: events delivered to Zorali from outside — currently
HMAC-verified GitHub webhooks. System-scoped like ``reality_events``, with a
unique ``delivery_id`` so a webhook redelivery cannot double-record an event
or re-trigger the routine attached to it.

Revision ID: 0010_inbound_events
Revises: 0009_repo_imports
Create Date: 2026-07-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0010_inbound_events"
down_revision = "0009_repo_imports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inbound_events",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("source", sa.String(32), nullable=False, server_default="github", index=True),
        sa.Column("delivery_id", sa.String(128), nullable=False, unique=True),
        sa.Column("event_type", sa.String(64), nullable=False, index=True),
        sa.Column("action", sa.String(64), nullable=False, server_default=""),
        sa.Column("repo", sa.String(255), nullable=False, server_default=""),
        sa.Column("ref", sa.String(255), nullable=False, server_default=""),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("payload", JSONB(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(16), nullable=False, server_default="received", index=True),
        sa.Column("goal_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True),
    )


def downgrade() -> None:
    op.drop_table("inbound_events")
