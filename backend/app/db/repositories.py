"""Postgres-backed repository layer.

Replaces the previous JSON-file store. Public method names, parameters and
returned dict shapes are unchanged so routers and the retrieval layer keep
working; the only caller-visible difference is that every method is now a
coroutine and must be awaited.

Uploaded file bytes still live on the local filesystem (uploads/<project>/);
everything else — projects, chat history, file metadata, chunks (with
pgvector embeddings), artifacts and memories — lives in Postgres.
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import re
from string import punctuation
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, func, select

from app.core.caller import Caller, resolve_owner_filter
from app.db.models import (
    Artifact,
    ChatMessage,
    ChatSession,
    Chunk,
    File,
    Memory,
    MemoryTriple,
    Notification,
    Project,
    RealityEvent,
    SessionSummary,
    User,
)
from app.db.session import SessionLocal

STOPWORDS = {
    "a", "an", "the", "and", "or", "is", "are", "to", "of", "for", "on", "in", "it", "with", "as", "by", "at", "be", "this", "that", "from",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _tokens(value: str) -> list[str]:
    cleaned = re.sub(f"[{re.escape(punctuation)}]", " ", value.lower())
    return [tok for tok in cleaned.split() if tok and tok not in STOPWORDS]


def _project_dict(row: Project) -> dict[str, Any]:
    return {
        "id": row.id,
        "owner_id": row.owner_id,
        "name": row.name,
        "description": row.description,
        "system_prompt": row.system_prompt,
        "created_at": _iso(row.created_at),
    }


def _chunk_dict(row: Chunk) -> dict[str, Any]:
    chunk: dict[str, Any] = {"id": row.idx, "text": row.text}
    if row.embedding is not None:
        chunk["embedding"] = list(row.embedding)
        chunk["embedding_model"] = row.embedding_model
    return chunk


def _file_dict(row: File, chunks: list[Chunk]) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "filename": row.filename,
        "path": row.path,
        "extracted_text": row.extracted_text,
        "chunks": [_chunk_dict(c) for c in chunks],
        "indexing_status": row.indexing_status,
        "created_at": _iso(row.created_at),
    }


def _artifact_dict(row: Artifact) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "name": row.name,
        "versions": list(row.versions or []),
        "created_at": _iso(row.created_at),
    }


def _memory_dict(row: Memory, include_embedding: bool = False) -> dict[str, Any]:
    memory = {
        "id": row.id,
        "project_id": row.project_id,
        "user_id": row.owner_id,
        "text": row.text,
        "status": row.status,
        "created_at": _iso(row.created_at),
    }
    # Embeddings are large float arrays for the retrieval layer only — they
    # must never leak into API responses (mirrors _public_file for chunks).
    if include_embedding and row.embedding is not None:
        memory["embedding"] = list(row.embedding)
        memory["embedding_model"] = row.embedding_model
    return memory


def _triple_dict(row: MemoryTriple) -> dict[str, Any]:
    return {
        "id": row.id,
        "memory_id": row.memory_id,
        "subject": row.subject,
        "relation": row.relation,
        "object": row.object,
    }


def _notification_dict(row: Notification) -> dict[str, Any]:
    return {
        "id": row.id,
        "kind": row.kind,
        "title": row.title,
        "body": row.body,
        "read": row.read_at is not None,
        "read_at": _iso(row.read_at),
        "created_at": _iso(row.created_at),
    }


def _reality_event_dict(row: RealityEvent) -> dict[str, Any]:
    return {
        "id": row.id,
        "kind": row.kind,
        "subject": row.subject,
        "severity": row.severity,
        "detail": row.detail,
        "data": dict(row.data or {}),
        "created_at": _iso(row.created_at),
    }


def _chat_dict(row: ChatMessage) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "session_id": row.session_id,
        "role": row.role,
        "content": row.content,
        "citations": list(row.citations or []),
        "created_at": _iso(row.created_at),
    }


class Repository:
    def __init__(self, base_dir: str | None = None) -> None:
        self.base_dir = self._resolve_base_dir(base_dir)
        self.upload_root = self.base_dir / "uploads"
        self.artifacts_root = self.base_dir / "artifacts"
        self.memory_root = self.base_dir / "memory"
        self.upload_root.mkdir(parents=True, exist_ok=True)
        self.artifacts_root.mkdir(parents=True, exist_ok=True)
        self.memory_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _resolve_base_dir(base_dir: str | None) -> Path:
        if base_dir:
            return Path(base_dir)

        env_dir = os.getenv("ZORALI_DATA_DIR")
        if env_dir:
            return Path(env_dir)

        docker_data_dir = Path("/data")
        try:
            docker_data_dir.mkdir(parents=True, exist_ok=True)
            probe = docker_data_dir / ".zorali-write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return docker_data_dir
        except OSError:
            pass

        repo_data_dir = Path(__file__).resolve().parents[3] / "data"
        return repo_data_dir

    # ── Ownership ───────────────────────────────────────────────────────────

    @staticmethod
    async def _project_owned(session, project_id: str, owner_id: Caller) -> bool:
        """Whether the caller may access ``project_id``.

        ``owner_id`` is a required caller context: the authenticated user's id
        (JWT ``sub``) or the explicit ``SYSTEM`` marker for internal callers
        (background ingestion, maintenance scripts), which skips the check.
        Anything else — including ``None`` — raises ``TypeError`` so an
        ownership check can never be skipped by accident.
        """
        owner_filter = resolve_owner_filter(owner_id)
        if owner_filter is None:
            return True
        found = (
            await session.execute(
                select(Project.id).where(Project.id == project_id, Project.owner_id == owner_filter)
            )
        ).scalar_one_or_none()
        return found is not None

    # ── Projects ────────────────────────────────────────────────────────────

    async def create_project(
        self, name: str, description: str = "", *, owner_id: Caller
    ) -> dict[str, Any]:
        owner_filter = resolve_owner_filter(owner_id)
        async with SessionLocal() as session:
            async with session.begin():
                row = Project(id=str(uuid4()), name=name, description=description, owner_id=owner_filter)
                session.add(row)
            return _project_dict(row)

    async def list_projects(self, *, owner_id: Caller) -> list[dict[str, Any]]:
        owner_filter = resolve_owner_filter(owner_id)
        async with SessionLocal() as session:
            stmt = select(Project)
            if owner_filter is not None:
                stmt = stmt.where(Project.owner_id == owner_filter)
            rows = (await session.execute(stmt.order_by(Project.created_at))).scalars().all()
            return [_project_dict(r) for r in rows]

    async def get_project(self, project_id: str, *, owner_id: Caller) -> dict[str, Any] | None:
        owner_filter = resolve_owner_filter(owner_id)
        async with SessionLocal() as session:
            row = (
                await session.execute(select(Project).where(Project.id == project_id))
            ).scalar_one_or_none()
            if row is None:
                return None
            if owner_filter is not None and row.owner_id != owner_filter:
                return None
            return _project_dict(row)

    async def update_project(
        self,
        project_id: str,
        *,
        owner_id: Caller,
        name: str | None = None,
        description: str | None = None,
        system_prompt: str | None = None,
    ) -> dict[str, Any] | None:
        """Update project fields (only the ones provided). Returns ``None``
        when the project does not exist or is not owned by ``owner_id``."""
        owner_filter = resolve_owner_filter(owner_id)
        async with SessionLocal() as session:
            async with session.begin():
                row = (
                    await session.execute(select(Project).where(Project.id == project_id))
                ).scalar_one_or_none()
                if row is None:
                    return None
                if owner_filter is not None and row.owner_id != owner_filter:
                    return None
                if name is not None:
                    row.name = name
                if description is not None:
                    row.description = description
                if system_prompt is not None:
                    row.system_prompt = system_prompt
            return _project_dict(row)

    # ── Chat history ────────────────────────────────────────────────────────

    async def add_chat_message(
        self,
        project_id: str,
        session_id: str,
        role: str,
        content: str,
        citations: list[dict[str, Any]] | None = None,
        *,
        owner_id: Caller,
    ) -> dict[str, Any]:
        async with SessionLocal() as session:
            async with session.begin():
                if not await self._project_owned(session, project_id, owner_id):
                    raise LookupError("Unknown project_id")
                await self._ensure_chat_session(session, project_id, session_id, owner_id)
                row = ChatMessage(
                    id=str(uuid4()),
                    project_id=project_id,
                    session_id=session_id,
                    role=role,
                    content=content,
                    citations=citations or [],
                )
                session.add(row)
            return _chat_dict(row)

    async def list_chat_messages(
        self, project_id: str, session_id: str | None = None, *, owner_id: Caller
    ) -> list[dict[str, Any]] | None:
        """Return a project's chat history, or ``None`` when ``owner_id`` does
        not own the project (routers translate ``None`` to 404)."""
        async with SessionLocal() as session:
            if not await self._project_owned(session, project_id, owner_id):
                return None
            stmt = select(ChatMessage).where(ChatMessage.project_id == project_id)
            if session_id:
                stmt = stmt.where(ChatMessage.session_id == session_id)
            rows = (await session.execute(stmt.order_by(ChatMessage.seq))).scalars().all()
            return [_chat_dict(r) for r in rows]

    async def get_session_summary(
        self, project_id: str, session_id: str, *, owner_id: Caller
    ) -> dict[str, Any] | None:
        """Rolling conversation summary for one session, or ``None`` when
        there is none yet or ``owner_id`` does not own the row."""
        owner_filter = resolve_owner_filter(owner_id)
        async with SessionLocal() as session:
            if not await self._project_owned(session, project_id, owner_id):
                return None
            stmt = select(SessionSummary).where(
                SessionSummary.project_id == project_id,
                SessionSummary.session_id == session_id,
            )
            if owner_filter is not None:
                stmt = stmt.where(SessionSummary.owner_id == owner_filter)
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                return None
            return {
                "project_id": row.project_id,
                "session_id": row.session_id,
                "summary": row.summary,
                "covered_messages": row.covered_messages,
                "updated_at": row.updated_at.isoformat(),
            }

    async def upsert_session_summary(
        self,
        project_id: str,
        session_id: str,
        summary: str,
        covered_messages: int,
        *,
        owner_id: Caller,
    ) -> None:
        """Create or update the rolling summary row for a session.

        Stored owner-scoped: the row records the caller's account id (for the
        SYSTEM marker, the project owner's id) and reads filter on it.
        """
        owner_filter = resolve_owner_filter(owner_id)
        async with SessionLocal() as session:
            async with session.begin():
                if not await self._project_owned(session, project_id, owner_id):
                    raise LookupError("Unknown project_id")
                if owner_filter is None:
                    project = (
                        await session.execute(select(Project).where(Project.id == project_id))
                    ).scalar_one_or_none()
                    owner_filter = (project.owner_id if project else None) or "system"
                row = (
                    await session.execute(
                        select(SessionSummary).where(
                            SessionSummary.project_id == project_id,
                            SessionSummary.session_id == session_id,
                        )
                    )
                ).scalar_one_or_none()
                if row is None:
                    session.add(SessionSummary(
                        project_id=project_id,
                        session_id=session_id,
                        owner_id=owner_filter,
                        summary=summary,
                        covered_messages=covered_messages,
                    ))
                else:
                    if row.owner_id != owner_filter:
                        raise LookupError("Unknown project_id")
                    row.summary = summary
                    row.covered_messages = covered_messages
                    row.updated_at = datetime.now(timezone.utc)

    @staticmethod
    async def _ensure_chat_session(session, project_id: str, session_id: str, owner_id: Caller) -> None:
        """Create the chat_sessions row for a conversation if missing (called
        inside an open transaction, after the ownership check passed)."""
        exists = (
            await session.execute(
                select(ChatSession.id).where(
                    ChatSession.project_id == project_id,
                    ChatSession.session_id == session_id,
                )
            )
        ).scalar_one_or_none()
        if exists is not None:
            return
        owner_filter = resolve_owner_filter(owner_id)
        if owner_filter is None:
            project = (
                await session.execute(select(Project).where(Project.id == project_id))
            ).scalar_one_or_none()
            owner_filter = (project.owner_id if project else None) or "system"
        session.add(ChatSession(project_id=project_id, session_id=session_id, owner_id=owner_filter))

    async def list_chat_sessions(
        self, project_id: str, *, owner_id: Caller
    ) -> list[dict[str, Any]] | None:
        """List a project's chat sessions (ChatGPT-style conversation list),
        newest-activity first, from the chat_sessions table plus per-session
        message aggregates. Each entry: {session_id, title, preview,
        message_count, last_at}. ``None`` when ``owner_id`` does not own the
        project."""
        async with SessionLocal() as session:
            if not await self._project_owned(session, project_id, owner_id):
                return None
            sessions = (
                await session.execute(
                    select(ChatSession).where(ChatSession.project_id == project_id)
                )
            ).scalars().all()
            stats = {
                sid: {"message_count": count, "last_at": _iso(last_at)}
                for sid, count, last_at in (
                    await session.execute(
                        select(
                            ChatMessage.session_id,
                            func.count(ChatMessage.id),
                            func.max(ChatMessage.created_at),
                        )
                        .where(ChatMessage.project_id == project_id)
                        .group_by(ChatMessage.session_id)
                    )
                ).all()
            }
            # Iterating newest→oldest means the last write per session_id is
            # its oldest user message — the conversation opener as preview.
            previews = {
                sid: content[:80]
                for sid, content in (
                    await session.execute(
                        select(ChatMessage.session_id, ChatMessage.content)
                        .where(ChatMessage.project_id == project_id, ChatMessage.role == "user")
                        .order_by(ChatMessage.seq.desc())
                    )
                ).all()
            }
            entries = []
            for row in sessions:
                stat = stats.get(row.session_id)
                if stat is None:
                    continue  # session row without messages (all deleted)
                entries.append({
                    "session_id": row.session_id,
                    "title": row.title,
                    "preview": previews.get(row.session_id, ""),
                    **stat,
                })
            entries.sort(key=lambda s: s["last_at"] or "", reverse=True)
            return entries

    async def rename_chat_session(
        self, project_id: str, session_id: str, title: str, *, owner_id: Caller
    ) -> bool:
        """Set a conversation's title. Returns False when the caller does not
        own the project or the session does not exist (routers → 404)."""
        async with SessionLocal() as session:
            async with session.begin():
                if not await self._project_owned(session, project_id, owner_id):
                    return False
                row = (
                    await session.execute(
                        select(ChatSession).where(
                            ChatSession.project_id == project_id,
                            ChatSession.session_id == session_id,
                        )
                    )
                ).scalar_one_or_none()
                if row is None:
                    return False
                row.title = title.strip()[:255]
                row.updated_at = datetime.now(timezone.utc)
                return True

    async def set_session_title_if_empty(
        self, project_id: str, session_id: str, title: str, *, owner_id: Caller
    ) -> bool:
        """Store an auto-generated title, but never clobber a user rename."""
        async with SessionLocal() as session:
            async with session.begin():
                if not await self._project_owned(session, project_id, owner_id):
                    return False
                row = (
                    await session.execute(
                        select(ChatSession).where(
                            ChatSession.project_id == project_id,
                            ChatSession.session_id == session_id,
                        )
                    )
                ).scalar_one_or_none()
                if row is None or row.title:
                    return False
                row.title = title.strip()[:255]
                row.updated_at = datetime.now(timezone.utc)
                return True

    async def delete_chat_session(
        self, project_id: str, session_id: str, *, owner_id: Caller
    ) -> bool:
        """Delete a conversation: its messages, rolling summary and session
        row. Returns False when the caller does not own the project or the
        session does not exist (routers → 404)."""
        async with SessionLocal() as session:
            async with session.begin():
                if not await self._project_owned(session, project_id, owner_id):
                    return False
                row = (
                    await session.execute(
                        select(ChatSession).where(
                            ChatSession.project_id == project_id,
                            ChatSession.session_id == session_id,
                        )
                    )
                ).scalar_one_or_none()
                if row is None:
                    return False
                await session.execute(
                    delete(ChatMessage).where(
                        ChatMessage.project_id == project_id,
                        ChatMessage.session_id == session_id,
                    )
                )
                await session.execute(
                    delete(SessionSummary).where(
                        SessionSummary.project_id == project_id,
                        SessionSummary.session_id == session_id,
                    )
                )
                await session.delete(row)
                return True

    async def search_chat_messages(
        self, project_id: str, query: str, *, owner_id: Caller, limit: int = 20
    ) -> list[dict[str, Any]] | None:
        """Case-insensitive substring search over a project's chat messages,
        newest first. ``None`` when the caller does not own the project."""
        async with SessionLocal() as session:
            if not await self._project_owned(session, project_id, owner_id):
                return None
            if not query or not query.strip():
                return []
            rows = (
                await session.execute(
                    select(ChatMessage)
                    .where(
                        ChatMessage.project_id == project_id,
                        ChatMessage.content.ilike(f"%{query.strip()}%"),
                    )
                    .order_by(ChatMessage.seq.desc())
                    .limit(limit)
                )
            ).scalars().all()
            return [
                {
                    "session_id": m.session_id,
                    "role": m.role,
                    "snippet": m.content[:160],
                    "created_at": _iso(m.created_at),
                }
                for m in rows
            ]

    async def delete_last_exchange(
        self, project_id: str, session_id: str, *, owner_id: Caller
    ) -> bool:
        """Edit-and-resend support: drop the last user message and everything
        after it (its assistant reply). Full branching is out of scope — the
        old exchange is gone once edited."""
        async with SessionLocal() as session:
            async with session.begin():
                if not await self._project_owned(session, project_id, owner_id):
                    return False
                last_user = (
                    await session.execute(
                        select(ChatMessage)
                        .where(
                            ChatMessage.project_id == project_id,
                            ChatMessage.session_id == session_id,
                            ChatMessage.role == "user",
                        )
                        .order_by(ChatMessage.seq.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if last_user is None:
                    return False
                await session.execute(
                    delete(ChatMessage).where(
                        ChatMessage.project_id == project_id,
                        ChatMessage.session_id == session_id,
                        ChatMessage.seq >= last_user.seq,
                    )
                )
                return True

    async def delete_last_assistant_message(
        self, project_id: str, session_id: str, *, owner_id: Caller
    ) -> bool:
        """Drop the most recent assistant message in a session (regenerate)."""
        async with SessionLocal() as session:
            async with session.begin():
                if not await self._project_owned(session, project_id, owner_id):
                    return False
                row = (
                    await session.execute(
                        select(ChatMessage)
                        .where(
                            ChatMessage.project_id == project_id,
                            ChatMessage.session_id == session_id,
                            ChatMessage.role == "assistant",
                        )
                        .order_by(ChatMessage.seq.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if row is None:
                    return False
                await session.delete(row)
                return True

    # ── Files & chunks ──────────────────────────────────────────────────────

    async def save_file(
        self,
        project_id: str,
        filename: str,
        content: bytes,
        extracted_text: str,
        chunks: list[dict[str, Any]],
        indexing_status: str = "ready",
        *,
        owner_id: Caller,
    ) -> dict[str, Any]:
        file_id = str(uuid4())
        upload_root = self.upload_root.resolve()
        project_dir = (upload_root / project_id).resolve()
        if upload_root != project_dir and upload_root not in project_dir.parents:
            raise ValueError("Invalid project_id path")

        async with SessionLocal() as session:
            async with session.begin():
                # A project the caller does not own is indistinguishable from
                # one that does not exist → LookupError (404).
                if not await self._project_owned(session, project_id, owner_id):
                    raise LookupError("Unknown project_id")
                exists = (
                    await session.execute(select(Project.id).where(Project.id == project_id))
                ).scalar_one_or_none()
                if not exists:
                    raise ValueError("Unknown project_id")

                project_dir.mkdir(parents=True, exist_ok=True)
                suffix = Path(filename).suffix.lower()
                storage_name = f"{file_id}{suffix}"
                full_path = (project_dir / storage_name).resolve()
                if project_dir not in full_path.parents:
                    raise ValueError("Invalid upload path")
                full_path.write_bytes(content)

                row = File(
                    id=file_id,
                    project_id=project_id,
                    filename=Path(filename).name,
                    path=str(full_path),
                    extracted_text=extracted_text,
                    indexing_status=indexing_status,
                )
                session.add(row)
                chunk_rows = [
                    Chunk(
                        file_id=file_id,
                        idx=c["id"],
                        text=c["text"],
                        embedding=c.get("embedding"),
                        embedding_model=c.get("embedding_model"),
                    )
                    for c in chunks
                ]
                session.add_all(chunk_rows)
            return _file_dict(row, chunk_rows)

    async def get_file(self, file_id: str, *, owner_id: Caller) -> dict[str, Any] | None:
        async with SessionLocal() as session:
            row = (
                await session.execute(select(File).where(File.id == file_id))
            ).scalar_one_or_none()
            if row is None:
                return None
            if not await self._project_owned(session, row.project_id, owner_id):
                return None
            chunks = (
                await session.execute(
                    select(Chunk).where(Chunk.file_id == file_id).order_by(Chunk.idx)
                )
            ).scalars().all()
            return _file_dict(row, list(chunks))

    async def update_file_indexing_status(
        self,
        file_id: str,
        status: str,
        chunks: list[dict[str, Any]] | None = None,
        extracted_text: str | None = None,
        *,
        owner_id: Caller,
    ) -> bool:
        """Update indexing_status and optionally replace extracted text and
        chunks (with embeddings). Used by the background ingestion task
        (which passes ``SYSTEM``)."""
        async with SessionLocal() as session:
            async with session.begin():
                row = (
                    await session.execute(select(File).where(File.id == file_id))
                ).scalar_one_or_none()
                if row is None:
                    return False
                if not await self._project_owned(session, row.project_id, owner_id):
                    return False
                row.indexing_status = status
                if extracted_text is not None:
                    row.extracted_text = extracted_text
                if chunks is not None:
                    await session.execute(delete(Chunk).where(Chunk.file_id == file_id))
                    session.add_all(
                        Chunk(
                            file_id=file_id,
                            idx=c["id"],
                            text=c["text"],
                            embedding=c.get("embedding"),
                            embedding_model=c.get("embedding_model"),
                        )
                        for c in chunks
                    )
                return True

    async def list_files(
        self, project_id: str, *, owner_id: Caller
    ) -> list[dict[str, Any]] | None:
        """List a project's files, or ``None`` when ``owner_id`` does not own
        the project (routers translate ``None`` to 404). With ``SYSTEM``
        (trusted internal callers) it always returns a list."""
        async with SessionLocal() as session:
            if not await self._project_owned(session, project_id, owner_id):
                return None
            files = (
                await session.execute(
                    select(File).where(File.project_id == project_id).order_by(File.created_at)
                )
            ).scalars().all()
            if not files:
                return []
            file_ids = [f.id for f in files]
            chunk_rows = (
                await session.execute(
                    select(Chunk).where(Chunk.file_id.in_(file_ids)).order_by(Chunk.idx)
                )
            ).scalars().all()
            by_file: dict[str, list[Chunk]] = {fid: [] for fid in file_ids}
            for c in chunk_rows:
                by_file[c.file_id].append(c)
            return [_file_dict(f, by_file[f.id]) for f in files]

    async def search_chunks(
        self, project_id: str, query: str, limit: int = 5, *, owner_id: Caller
    ) -> list[dict[str, Any]] | None:
        """Retrieve the most relevant file chunks for a query.

        Uses the two-stage hybrid retrieval engine (BM25 + TF-IDF fused with
        Reciprocal Rank Fusion, then a cross-encoder-style rerank) over
        contextualised chunks.
        The return shape is unchanged: {file_id, filename, chunk_id, text, score}.
        Returns ``None`` when ``owner_id`` does not own the project.
        """
        from app.memory.hybrid_search import engine, build_chunk_documents
        from app.core.config import settings

        files = await self.list_files(project_id, owner_id=owner_id)
        if files is None:
            return None
        if not query or not query.strip():
            return []
        documents = build_chunk_documents(files, contextual=settings.rag_contextual_enabled)
        results = engine.search(query, documents, top_k=limit)
        return [
            {
                "file_id": r.doc["file_id"],
                "filename": r.doc["filename"],
                "chunk_id": r.doc["chunk_id"],
                "text": r.doc["text"],
                "score": round(r.score, 4),
            }
            for r in results
        ]

    async def delete_file(self, file_id: str, *, owner_id: Caller) -> bool:
        """Remove a file record (and its chunks) and delete its bytes on disk.
        Returns ``False`` when the file does not exist or ``owner_id`` does not
        own its project."""
        async with SessionLocal() as session:
            async with session.begin():
                row = (
                    await session.execute(select(File).where(File.id == file_id))
                ).scalar_one_or_none()
                if row is None:
                    return False
                if not await self._project_owned(session, row.project_id, owner_id):
                    return False
                path = row.path
                await session.delete(row)
        if path:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                pass
        return True

    # ── Artifacts ───────────────────────────────────────────────────────────

    async def create_artifact(
        self, project_id: str, name: str, content: str, *, owner_id: Caller
    ) -> dict[str, Any]:
        async with SessionLocal() as session:
            async with session.begin():
                if not await self._project_owned(session, project_id, owner_id):
                    raise LookupError("Unknown project_id")
                row = Artifact(
                    id=str(uuid4()),
                    project_id=project_id,
                    name=name,
                    versions=[{"version": 1, "content": content, "created_at": _utc_now().isoformat()}],
                )
                session.add(row)
            return _artifact_dict(row)

    async def list_artifacts(
        self, project_id: str, *, owner_id: Caller
    ) -> list[dict[str, Any]] | None:
        """List a project's artifacts, or ``None`` when ``owner_id`` does not
        own the project (routers translate ``None`` to 404)."""
        async with SessionLocal() as session:
            if not await self._project_owned(session, project_id, owner_id):
                return None
            rows = (
                await session.execute(
                    select(Artifact).where(Artifact.project_id == project_id).order_by(Artifact.created_at)
                )
            ).scalars().all()
            return [_artifact_dict(r) for r in rows]

    async def get_artifact(self, artifact_id: str, *, owner_id: Caller) -> dict[str, Any] | None:
        async with SessionLocal() as session:
            row = (
                await session.execute(select(Artifact).where(Artifact.id == artifact_id))
            ).scalar_one_or_none()
            if row is None:
                return None
            if not await self._project_owned(session, row.project_id, owner_id):
                return None
            return _artifact_dict(row)

    async def update_artifact(
        self, artifact_id: str, content: str, *, owner_id: Caller
    ) -> dict[str, Any] | None:
        async with SessionLocal() as session:
            async with session.begin():
                row = (
                    await session.execute(select(Artifact).where(Artifact.id == artifact_id))
                ).scalar_one_or_none()
                if row is None:
                    return None
                if not await self._project_owned(session, row.project_id, owner_id):
                    return None
                versions = list(row.versions or [])
                versions.append(
                    {"version": len(versions) + 1, "content": content, "created_at": _utc_now().isoformat()}
                )
                row.versions = versions  # reassign so the JSONB change is detected
            return _artifact_dict(row)

    # ── Memories ────────────────────────────────────────────────────────────

    async def save_memory(
        self,
        project_id: str,
        user_id: str,
        text: str,
        embedding: list[float] | None = None,
        embedding_model: str | None = None,
        status: str = "active",
    ) -> dict[str, Any]:
        async with SessionLocal() as session:
            async with session.begin():
                row = Memory(
                    id=str(uuid4()),
                    project_id=project_id,
                    owner_id=user_id,
                    text=text,
                    embedding=embedding,
                    embedding_model=embedding_model,
                    status=status,
                )
                session.add(row)
            return _memory_dict(row)

    async def list_memories(
        self,
        project_id: str,
        user_id: str,
        include_embedding: bool = False,
        status: str | None = "active",
    ) -> list[dict[str, Any]]:
        """List a user's memories. Defaults to ``status="active"`` so search,
        semantic recall and prompt paths never see pending candidates; pass
        ``status="pending"`` for the review queue or ``None`` for all rows."""
        async with SessionLocal() as session:
            stmt = select(Memory).where(
                Memory.project_id == project_id, Memory.owner_id == user_id
            )
            if status is not None:
                stmt = stmt.where(Memory.status == status)
            rows = (await session.execute(stmt.order_by(Memory.created_at))).scalars().all()
            return [_memory_dict(r, include_embedding=include_embedding) for r in rows]

    async def activate_memory(
        self,
        memory_id: str,
        user_id: str,
        embedding: list[float] | None = None,
        embedding_model: str | None = None,
    ) -> dict[str, Any] | None:
        """Promote a pending candidate to a normal (active) memory.

        Owner-scoped: another account's id returns ``None``. Optionally
        attaches the embedding computed at accept time.
        """
        async with SessionLocal() as session:
            async with session.begin():
                row = (
                    await session.execute(
                        select(Memory).where(Memory.id == memory_id, Memory.owner_id == user_id)
                    )
                ).scalar_one_or_none()
                if row is None:
                    return None
                row.status = "active"
                if embedding is not None:
                    row.embedding = embedding
                    row.embedding_model = embedding_model
            return _memory_dict(row)

    # ── Memory graph (triples) ──────────────────────────────────────────────

    async def save_memory_triples(
        self,
        memory_id: str,
        project_id: str,
        owner_id: str,
        triples: list[tuple[str, str, str]],
    ) -> list[dict[str, Any]]:
        """Persist (subject, relation, object) facts extracted from a memory."""
        if not triples:
            return []
        async with SessionLocal() as session:
            async with session.begin():
                rows = [
                    MemoryTriple(
                        memory_id=memory_id,
                        project_id=project_id,
                        owner_id=owner_id,
                        subject=s[:255],
                        relation=r[:64],
                        object=o[:255],
                    )
                    for s, r, o in triples
                ]
                session.add_all(rows)
            return [_triple_dict(row) for row in rows]

    async def list_memory_triples(
        self, project_id: str, owner_id: str, limit: int = 500
    ) -> list[dict[str, Any]]:
        async with SessionLocal() as session:
            rows = (
                await session.execute(
                    select(MemoryTriple)
                    .where(
                        MemoryTriple.project_id == project_id,
                        MemoryTriple.owner_id == owner_id,
                    )
                    .order_by(MemoryTriple.id)
                    .limit(limit)
                )
            ).scalars().all()
            return [_triple_dict(r) for r in rows]

    async def search_memories(
        self, project_id: str, user_id: str, query: str, limit: int = 5
    ) -> list[dict[str, Any]]:
        q_tokens = set(_tokens(query))
        if not q_tokens:
            return []
        rows = await self.list_memories(project_id, user_id)
        scored = []
        for row in rows:
            t = set(_tokens(row["text"]))
            overlap = q_tokens.intersection(t)
            if overlap:
                scored.append({**row, "score": round(len(overlap) / max(len(q_tokens), 1), 4)})
        scored.sort(key=lambda r: r["score"], reverse=True)
        return scored[:limit]

    async def delete_memory(self, memory_id: str, user_id: str) -> bool:
        async with SessionLocal() as session:
            async with session.begin():
                row = (
                    await session.execute(
                        select(Memory).where(Memory.id == memory_id, Memory.owner_id == user_id)
                    )
                ).scalar_one_or_none()
                if row is None:
                    return False
                await session.delete(row)
                return True

    # ── Notifications (U4) ──────────────────────────────────────────────────

    async def create_notification(
        self, user_id: str, kind: str, title: str, body: str = ""
    ) -> dict[str, Any]:
        async with SessionLocal() as session:
            async with session.begin():
                row = Notification(id=str(uuid4()), owner_id=user_id, kind=kind, title=title, body=body)
                session.add(row)
            return _notification_dict(row)

    async def list_notifications(
        self, *, owner_id: str, unread_only: bool = False, limit: int = 50
    ) -> list[dict[str, Any]]:
        async with SessionLocal() as session:
            stmt = select(Notification).where(Notification.owner_id == owner_id)
            if unread_only:
                stmt = stmt.where(Notification.read_at.is_(None))
            stmt = stmt.order_by(Notification.created_at.desc()).limit(limit)
            rows = (await session.execute(stmt)).scalars().all()
            return [_notification_dict(r) for r in rows]

    async def unread_notification_count(self, *, owner_id: str) -> int:
        async with SessionLocal() as session:
            stmt = select(func.count()).select_from(Notification).where(
                Notification.owner_id == owner_id, Notification.read_at.is_(None)
            )
            return int((await session.execute(stmt)).scalar_one())

    async def mark_notification_read(self, notification_id: str, *, owner_id: str) -> bool:
        """Mark one of the caller's notifications read. A notification owned
        by someone else behaves like a nonexistent one."""
        async with SessionLocal() as session:
            async with session.begin():
                row = (
                    await session.execute(
                        select(Notification).where(
                            Notification.id == notification_id, Notification.owner_id == owner_id
                        )
                    )
                ).scalar_one_or_none()
                if row is None:
                    return False
                if row.read_at is None:
                    row.read_at = _utc_now()
                return True

    async def mark_all_notifications_read(self, *, owner_id: str) -> int:
        async with SessionLocal() as session:
            async with session.begin():
                rows = (
                    await session.execute(
                        select(Notification).where(
                            Notification.owner_id == owner_id, Notification.read_at.is_(None)
                        )
                    )
                ).scalars().all()
                now = _utc_now()
                for row in rows:
                    row.read_at = now
                return len(rows)

    async def list_admin_user_ids(self) -> list[str]:
        """Accounts that receive system notifications (admin and owner roles)."""
        async with SessionLocal() as session:
            stmt = select(User.id).where(User.role.in_(("admin", "owner")))
            return list((await session.execute(stmt)).scalars().all())

    # ── Reality events (U3) ─────────────────────────────────────────────────

    async def create_reality_event(
        self, kind: str, subject: str, *, severity: str = "info", detail: str = "", data: dict | None = None
    ) -> dict[str, Any]:
        async with SessionLocal() as session:
            async with session.begin():
                row = RealityEvent(kind=kind, subject=subject, severity=severity, detail=detail, data=data or {})
                session.add(row)
            return _reality_event_dict(row)

    async def list_reality_events(self, limit: int = 100) -> list[dict[str, Any]]:
        async with SessionLocal() as session:
            stmt = select(RealityEvent).order_by(RealityEvent.created_at.desc(), RealityEvent.id.desc()).limit(limit)
            rows = (await session.execute(stmt)).scalars().all()
            return [_reality_event_dict(r) for r in rows]


repo = Repository()
