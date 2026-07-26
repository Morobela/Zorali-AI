"""Nightly self-check runs (capability map U8).

``self_checks``: what each nightly run found (failing tests, lint errors,
FEATURE_PARITY.md claims the codebase does not support) and how many GitHub
issues it filed. System-scoped — it describes the codebase, not a user.

Revision ID: 0012_self_checks
Revises: 0011_goal_budgets
Create Date: 2026-07-26
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0012_self_checks"
down_revision = "0011_goal_budgets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "self_checks",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="running", index=True),
        sa.Column("findings", JSONB(), nullable=False, server_default="[]"),
        sa.Column("issues_filed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("self_checks")
