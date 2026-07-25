"""Durable goal engine: goals, tasks, task_steps (capability map U1).

Agent work in flight used to be memory-only — killing the backend mid-task
lost it. These three tables externalize the plan: a goal owns ordered tasks,
a task owns ordered steps, and each step carries its status, dependencies,
result text and error. On boot the engine resumes goals still marked
``running`` from the first step that is not yet completed.

Revision ID: 0008_durable_goals
Revises: 0007_reality_notifications
Create Date: 2026-07-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0008_durable_goals"
down_revision = "0007_reality_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "goals",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "owner_id", sa.String(64),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True,
        ),
        sa.Column("project_id", sa.String(64), nullable=False, index=True),
        sa.Column("session_id", sa.String(128), nullable=False, server_default=""),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="planning", index=True),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "tasks",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "goal_id", sa.String(64),
            sa.ForeignKey("goals.id", ondelete="CASCADE"), nullable=False, index=True,
        ),
        sa.Column("owner_id", sa.String(64), nullable=False, index=True),
        sa.Column("idx", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("result", sa.Text(), nullable=False, server_default=""),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "task_steps",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "task_id", sa.String(64),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True,
        ),
        sa.Column("goal_id", sa.String(64), nullable=False, index=True),
        sa.Column("owner_id", sa.String(64), nullable=False, index=True),
        sa.Column("idx", sa.Integer(), nullable=False),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("depends_on", JSONB(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending", index=True),
        sa.Column("result", sa.Text(), nullable=False, server_default=""),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("task_steps")
    op.drop_table("tasks")
    op.drop_table("goals")
