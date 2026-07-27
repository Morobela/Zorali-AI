"""Per-step kind and resolved model (capability map U7, optional half).

``task_steps.kind`` is what the planner said the work is (classification,
extraction, research, synthesis, code); ``task_steps.model`` is what the step
actually ran on once STEP_MODEL_POLICY was applied — recorded so a goal's
spend can be explained after the fact rather than inferred.

Revision ID: 0013_step_model_policy
Revises: 0012_self_checks
Create Date: 2026-07-26
"""
from alembic import op
import sqlalchemy as sa

revision = "0013_step_model_policy"
down_revision = "0012_self_checks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "task_steps",
        sa.Column("kind", sa.String(32), nullable=False, server_default="general"),
    )
    op.add_column(
        "task_steps",
        sa.Column("model", sa.String(128), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("task_steps", "model")
    op.drop_column("task_steps", "kind")
