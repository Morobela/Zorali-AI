"""Conversation UX parity: first-class chat sessions.

``chat_sessions``: one row per conversation, created with the first
persisted message. Carries the LLM-generated (or user-renamed) title so the
sidebar list no longer scans every message in the project. Existing
conversations are backfilled from ``chat_messages`` so they keep appearing
after the upgrade.

Revision ID: 0006_chat_sessions
Revises: 0005_memory_status
Create Date: 2026-07-18
"""
from uuid import uuid4

from alembic import op
import sqlalchemy as sa

revision = "0006_chat_sessions"
down_revision = "0005_memory_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(64), nullable=False, index=True),
        sa.Column("session_id", sa.String(128), nullable=False, index=True),
        sa.Column("owner_id", sa.String(64), nullable=False, index=True),
        sa.Column("title", sa.String(255), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "session_id", name="uq_chat_session"),
    )
    # Backfill: one session row per (project_id, session_id) seen in
    # chat_messages, owned by the project's owner, timestamped from the
    # session's first and last message.
    conn = op.get_bind()
    rows = conn.execute(sa.text(
        """
        SELECT m.project_id, m.session_id,
               COALESCE(p.owner_id, 'system') AS owner_id,
               MIN(m.created_at) AS first_at, MAX(m.created_at) AS last_at
        FROM chat_messages m
        LEFT JOIN projects p ON p.id = m.project_id
        GROUP BY m.project_id, m.session_id, p.owner_id
        """
    )).fetchall()
    for row in rows:
        conn.execute(
            sa.text(
                "INSERT INTO chat_sessions (id, project_id, session_id, owner_id, title, created_at, updated_at) "
                "VALUES (:id, :pid, :sid, :oid, '', :created, :updated)"
            ),
            {
                "id": str(uuid4()),
                "pid": row.project_id,
                "sid": row.session_id,
                "oid": row.owner_id,
                "created": row.first_at,
                "updated": row.last_at,
            },
        )


def downgrade() -> None:
    op.drop_table("chat_sessions")
