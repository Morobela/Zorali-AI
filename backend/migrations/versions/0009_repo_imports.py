"""Repository imports (capability map U6).

``repo_imports``: one row per repository import into a project — what was
imported, how far it got, and a capped per-file record of what was skipped
and why. Owner-scoped; the ``source`` column stores "owner/repo", never an
authenticated clone URL (which would carry a token).

Revision ID: 0009_repo_imports
Revises: 0008_durable_goals
Create Date: 2026-07-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0009_repo_imports"
down_revision = "0008_durable_goals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "repo_imports",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "owner_id", sa.String(64),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True,
        ),
        sa.Column("project_id", sa.String(64), nullable=False, index=True),
        sa.Column("source", sa.String(512), nullable=False),
        sa.Column("ref", sa.String(255), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued", index=True),
        sa.Column("imported_files", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_files", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_files", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("files", JSONB(), nullable=False, server_default="[]"),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("repo_imports")
