"""Async SQLAlchemy ORM models backing the Zorali Postgres data layer.

Ownership model:
- ``users.id`` holds the JWT ``sub`` (a UUID for registered accounts, or a
  provisioned id such as ``demo-owner`` for the dev-only demo login).
- ``projects.owner_id`` is a real FK to ``users`` — every project belongs to
  an account. Files, chunks, artifacts and chat history hang off projects.
- ``memories.owner_id`` and ``chat_messages.project_id`` are plain indexed
  strings: memories historically accept caller-supplied user ids ("local")
  and the chat WebSocket accepts a synthetic "default" project, so a strict
  FK would reject data the API contract currently allows.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return str(uuid4())


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    # NULL for provisioned accounts (demo login, test fixtures) that cannot
    # authenticate with a password.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="user")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    owner_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Per-project custom instructions injected as a system message in chat
    # (ChatGPT custom instructions / Claude project instructions parity).
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )

    files: Mapped[list["File"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True
    )
    artifacts: Mapped[list["Artifact"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True
    )


class File(Base):
    __tablename__ = "files"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    # Filesystem location of the raw uploaded bytes (uploads/<project>/<id>.<ext>).
    path: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    indexing_status: Mapped[str] = mapped_column(String(32), nullable=False, default="ready")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )

    project: Mapped["Project"] = relationship(back_populates="files")
    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="file",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Chunk.idx",
    )


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    file_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("files.id", ondelete="CASCADE"), nullable=False, index=True
    )
    idx: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # Dimension left open on purpose: the embedding model is configurable
    # (RAG_EMBEDDING_MODEL) and chunks indexed before embeddings were enabled
    # have no vector at all.
    embedding = mapped_column(Vector(), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(128), nullable=True)

    file: Mapped["File"] = relationship(back_populates="chunks")


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # List of {"version": int, "content": str, "created_at": iso-str}.
    versions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )

    project: Mapped["Project"] = relationship(back_populates="artifacts")


class Memory(Base):
    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # JWT sub of the owning account (or a caller-supplied id, e.g. "local").
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # "active" memories are searchable and feed the knowledge graph;
    # "pending" rows are auto-extracted candidates awaiting the user's
    # Accept/Reject review and are never injected into prompts.
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active", index=True
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # Optional dense vector for semantic recall (mirrors Chunk.embedding);
    # NULL for memories saved while RAG_EMBEDDINGS_ENABLED was off.
    embedding = mapped_column(Vector(), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )


class MemoryTriple(Base):
    """A (subject, relation, object) fact extracted from a saved memory.

    Graph memory: instead of only retrieving memories whose *text* resembles
    the query, triples let retrieval follow relationships between entities
    ("charles —works_at→ acme", "acme —uses→ python") one hop out.
    Triples are deleted with their source memory (FK cascade).
    """

    __tablename__ = "memory_triples"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    memory_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("memories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    relation: Mapped[str] = mapped_column(String(64), nullable=False)
    object: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )


class ChatSession(Base):
    """One conversation (session) inside a project.

    Created automatically with the first persisted message of a session.
    ``title`` starts empty and is filled by a one-shot LLM call after the
    first assistant reply (or by the user renaming the conversation); the
    sidebar falls back to the first user message preview when empty.
    """

    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )

    __table_args__ = (UniqueConstraint("project_id", "session_id", name="uq_chat_session"),)


class SessionSummary(Base):
    """Rolling conversation summary for one chat session.

    When a session's history exceeds the context budget
    (``CONTEXT_MAX_TOKENS``), the turns older than the verbatim window are
    compressed into this summary once and reused on later turns instead of
    being recomputed. ``covered_messages`` records how many messages from the
    start of the session the summary already folds in. Owner-scoped like
    every other row: reads and writes filter on ``owner_id``.
    """

    __tablename__ = "session_summaries"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    # JWT sub of the owning account (same convention as memories.owner_id).
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    covered_messages: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )

    __table_args__ = (UniqueConstraint("project_id", "session_id", name="uq_session_summary"),)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    # Monotonic insertion order — created_at alone can collide at microsecond
    # resolution and prompt reconstruction needs a stable message order.
    seq: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False, unique=True)
    project_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )
