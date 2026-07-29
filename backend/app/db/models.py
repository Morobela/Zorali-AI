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
    Boolean,
    DateTime,
    Float,
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


class Goal(Base):
    """A durable multi-step objective (capability map U1).

    The goal, its tasks and their steps all live in Postgres, so work in
    flight survives a restart: on boot the engine picks up goals still
    marked ``running`` and continues from the first step that is not yet
    completed. Owner-scoped like every other entity.

    Statuses: ``planning`` → ``running`` → ``completed`` / ``failed``.
    """

    __tablename__ = "goals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="planning", server_default="planning", index=True
    )
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Budget (capability map U7). ``cost_usd`` accumulates what the goal's
    # steps actually spent on inference; ``max_cost_usd`` is its ceiling, and
    # 0 means no ceiling. A goal that reaches the warning ratio of its cap
    # parks in ``paused`` with the explanation in ``pause_reason`` — it is
    # never auto-resumed, only a human resumes or raises the cap.
    cost_usd: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0"
    )
    max_cost_usd: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0"
    )
    pause_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Routing the goal was started with. Persisted because a goal outlives the
    # request that created it: a resume (by API, or by the boot sweep) must
    # continue on the same model it began on, or its accumulated spend would
    # be measured against different prices than the ones it was capped for.
    model: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    local_first: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )

    tasks: Mapped[list["Task"]] = relationship(
        back_populates="goal", cascade="all, delete-orphan", passive_deletes=True,
        order_by="Task.idx",
    )


class Task(Base):
    """One unit of a goal's plan, ordered by ``idx`` within the goal."""

    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    goal_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("goals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    idx: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    result: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )

    goal: Mapped["Goal"] = relationship(back_populates="tasks")
    steps: Mapped[list["TaskStep"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", passive_deletes=True,
        order_by="TaskStep.idx",
    )


class TaskStep(Base):
    """One executable step of a task — the unit the goal engine runs.

    ``depends_on`` holds the ``idx`` values of sibling steps that must
    complete first; an empty list means the step is independent (U2 uses
    that to run independent steps in parallel). ``result`` carries the
    step's answer text and ``error`` the failure reason, so a resumed goal
    can feed earlier results into later steps without replaying any work.
    """

    __tablename__ = "task_steps"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Denormalized so the engine can order and pick steps across a whole goal
    # without joining through tasks on every poll.
    goal_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    idx: Mapped[int] = mapped_column(Integer, nullable=False)
    instruction: Mapped[str] = mapped_column(Text, nullable=False)
    # What sort of work this is, as labelled by the planner. Mechanical kinds
    # can be routed to a smaller model (STEP_MODEL_POLICY); ``model`` records
    # what the step actually ran on, so a goal's spend can be explained.
    kind: Mapped[str] = mapped_column(
        String(32), nullable=False, default="general", server_default="general"
    )
    model: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    depends_on: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending", index=True
    )
    result: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # What this step's inference actually cost (capability map U7).
    cost_usd: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0"
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    task: Mapped["Task"] = relationship(back_populates="steps")


class SelfCheck(Base):
    """One nightly self-check run (capability map U8).

    Records what the run found and how many issues it filed, so a human can
    see the history without reading the tracker. System-scoped: this describes
    the codebase, not a user's data.

    Statuses: ``running`` → ``clean`` / ``findings`` / ``failed``.
    """

    __tablename__ = "self_checks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="running", server_default="running", index=True
    )
    findings: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    issues_filed: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now, index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class InboundEvent(Base):
    """One event delivered to Zorali from outside (capability map U5).

    System-scoped, like ``reality_events``: these describe the world, not a
    user's data. ``delivery_id`` is unique so a webhook redelivery (GitHub
    retries) can never double-record or re-trigger a routine. ``payload``
    holds a trimmed summary, never the whole delivery body.

    Statuses: ``received`` → ``handled`` / ``ignored`` / ``failed``.
    """

    __tablename__ = "inbound_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="github", index=True)
    # X-GitHub-Delivery — the idempotency key for redelivery.
    delivery_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    repo: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    ref: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="received", server_default="received", index=True
    )
    # The goal this event opened, when a routine converted it into one.
    goal_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now, index=True
    )


class RepoImport(Base):
    """One repository import into a project (capability map U6).

    Records what was imported, how far it got and why files were skipped, so
    a caller can poll progress and see afterwards exactly what entered the
    project. Owner-scoped like every other entity. ``files`` holds a capped
    per-file list (a large repo would otherwise bloat the row); the counts
    always cover the whole import.

    Statuses: ``queued`` → ``cloning`` → ``importing`` → ``completed`` /
    ``failed``.
    """

    __tablename__ = "repo_imports"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # "owner/repo" — never the authenticated clone URL, which would carry a token.
    source: Mapped[str] = mapped_column(String(512), nullable=False)
    ref: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="queued", server_default="queued", index=True
    )
    imported_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    skipped_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    failed_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    files: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )


class Notification(Base):
    """A proactive message from Zorali to one account (capability map U4).

    Rows are created by background routines (the reality engine's diff),
    never by user requests. Owner-scoped like every other entity: reads and
    mark-read filter on ``owner_id``. ``read_at`` is NULL while unread.
    """

    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )


class RealityEvent(Base):
    """One observed change between consecutive reality snapshots.

    System-scoped (no owner): events describe infrastructure state — a
    service transition, a log error jump, aging uncommitted changes — not
    user data. Notable events additionally fan out as ``notifications``.
    """

    __tablename__ = "reality_events"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="info")
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now, index=True
    )


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


class Routine(Base):
    """A schedule and a prompt, defined by a user, that runs without them.

    The built-in routines (reality scan, nightly self-check, nightly backup)
    are compiled in and owned by the deployment. This is the same idea handed
    to an account: "every morning, tell me what changed in my project."

    Bounded on purpose, because a thing that runs unattended and spends money
    is a money pump if it is not: ``interval_seconds`` has a floor,
    ``max_cost_usd`` caps a single run, and ``consecutive_failures`` disables
    a routine that keeps failing rather than letting it notify forever.

    Schedules are deliberately small — ``interval`` (every N seconds) or
    ``daily`` (at ``hour_utc``). Cron is a parser and a footgun; these two
    cover what the feature is for.
    """

    __tablename__ = "routines"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[str] = mapped_column(String(64), nullable=False, default="default")
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    schedule_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="interval")
    interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=3600)
    hour_utc: Mapped[int] = mapped_column(Integer, nullable=False, default=8)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    # 0 means "use the deployment default"; the runner never resolves it to
    # uncapped, because an unattended prompt with no ceiling is the failure
    # mode this whole feature has to avoid.
    max_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    next_run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now, index=True
    )
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    disabled_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now, onupdate=_utc_now
    )


class RoutineRun(Base):
    """One execution of a routine — kept so "did it work?" has an answer.

    The notification carries the result to the user; this carries the record,
    including what the run cost and why it failed.
    """

    __tablename__ = "routine_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    routine_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("routines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running", index=True)
    result: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now, index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
