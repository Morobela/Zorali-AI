"""User-configurable routines.

``routines``: a schedule plus a prompt, defined by an account rather than
compiled into the deployment. ``routine_runs``: what each execution did, cost
and returned, so "did my routine work?" has an answer beyond the notification.

Both owner-scoped like every other user-facing entity.

Revision ID: 0014_routines
Revises: 0013_step_model_policy
Create Date: 2026-07-28
"""
from alembic import op
import sqlalchemy as sa

revision = "0014_routines"
down_revision = "0013_step_model_policy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "routines",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "owner_id", sa.String(64),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True,
        ),
        sa.Column("project_id", sa.String(64), nullable=False, server_default="default"),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("schedule_kind", sa.String(16), nullable=False, server_default="interval"),
        sa.Column("interval_seconds", sa.Integer(), nullable=False, server_default="3600"),
        sa.Column("hour_utc", sa.Integer(), nullable=False, server_default="8"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true(), index=True),
        sa.Column("max_cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(16), nullable=False, server_default=""),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("disabled_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    # The ticker's hot query: enabled routines whose time has come.
    op.create_index("ix_routines_due", "routines", ["enabled", "next_run_at"])

    op.create_table(
        "routine_runs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "routine_id", sa.String(64),
            sa.ForeignKey("routines.id", ondelete="CASCADE"), nullable=False, index=True,
        ),
        sa.Column("owner_id", sa.String(64), nullable=False, index=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="running", index=True),
        sa.Column("result", sa.Text(), nullable=False, server_default=""),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("routine_runs")
    op.drop_index("ix_routines_due", table_name="routines")
    op.drop_table("routines")
