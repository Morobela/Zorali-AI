"""Graph memory (subject–relation–object triples) + dense memory embeddings.

- ``memory_triples``: facts extracted from saved memories, so retrieval can
  follow relationships ("charles —works_at→ acme") instead of only matching
  similar text chunks.
- ``memories.embedding`` / ``memories.embedding_model``: optional dense
  vectors (mirrors the ``chunks`` table) for semantic memory recall when
  RAG_EMBEDDINGS_ENABLED is on.

Revision ID: 0003_memory_graph
Revises: 0002_project_system_prompt
Create Date: 2026-07-06
"""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision = "0003_memory_graph"
down_revision = "0002_project_system_prompt"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("memories", sa.Column("embedding", Vector(), nullable=True))
    op.add_column("memories", sa.Column("embedding_model", sa.String(128), nullable=True))
    op.create_table(
        "memory_triples",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "memory_id",
            sa.String(64),
            sa.ForeignKey("memories.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("project_id", sa.String(64), nullable=False, index=True),
        sa.Column("owner_id", sa.String(64), nullable=False, index=True),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("relation", sa.String(64), nullable=False),
        sa.Column("object", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("memory_triples")
    op.drop_column("memories", "embedding_model")
    op.drop_column("memories", "embedding")
