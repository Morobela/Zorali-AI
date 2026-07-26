"""Per-goal cost budgets (capability map U7).

``energy_scorer`` prices every provider call; these columns give that number
somewhere to live. ``goals.cost_usd`` accumulates what a goal's steps spent,
``goals.max_cost_usd`` is its ceiling (0 = uncapped), and ``pause_reason``
explains a goal parked at the ceiling. ``task_steps.cost_usd`` records the
per-step spend so a pause can point at where the budget went.

Revision ID: 0011_goal_budgets
Revises: 0010_inbound_events
Create Date: 2026-07-26
"""
from alembic import op
import sqlalchemy as sa

revision = "0011_goal_budgets"
down_revision = "0010_inbound_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("goals", sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"))
    op.add_column("goals", sa.Column("max_cost_usd", sa.Float(), nullable=False, server_default="0"))
    op.add_column("goals", sa.Column("pause_reason", sa.Text(), nullable=False, server_default=""))
    # Routing is persisted with the goal so a resume continues on the model it
    # started on — otherwise spend would be priced differently after a pause.
    op.add_column("goals", sa.Column("model", sa.String(128), nullable=False, server_default=""))
    op.add_column(
        "goals", sa.Column("local_first", sa.Boolean(), nullable=False, server_default="true")
    )
    op.add_column("task_steps", sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("task_steps", "cost_usd")
    op.drop_column("goals", "local_first")
    op.drop_column("goals", "model")
    op.drop_column("goals", "pause_reason")
    op.drop_column("goals", "max_cost_usd")
    op.drop_column("goals", "cost_usd")
