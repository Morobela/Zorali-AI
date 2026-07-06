"""Add projects.system_prompt for per-project custom instructions.

Revision ID: 0002_project_system_prompt
Revises: 0001_initial
Create Date: 2026-07-05
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_project_system_prompt"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("system_prompt", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("projects", "system_prompt")
