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

from sqlalchemy import delete, select

from app.db.models import Artifact, ChatMessage, Chunk, File, Memory, Project
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


def _memory_dict(row: Memory) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "user_id": row.owner_id,
        "text": row.text,
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

    # ── Projects ────────────────────────────────────────────────────────────

    async def create_project(self, name: str, description: str = "") -> dict[str, Any]:
        async with SessionLocal() as session:
            async with session.begin():
                row = Project(id=str(uuid4()), name=name, description=description)
                session.add(row)
            return _project_dict(row)

    async def list_projects(self) -> list[dict[str, Any]]:
        async with SessionLocal() as session:
            rows = (
                await session.execute(select(Project).order_by(Project.created_at))
            ).scalars().all()
            return [_project_dict(r) for r in rows]

    # ── Chat history ────────────────────────────────────────────────────────

    async def add_chat_message(
        self,
        project_id: str,
        session_id: str,
        role: str,
        content: str,
        citations: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        async with SessionLocal() as session:
            async with session.begin():
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
        self, project_id: str, session_id: str | None = None
    ) -> list[dict[str, Any]]:
        async with SessionLocal() as session:
            stmt = select(ChatMessage).where(ChatMessage.project_id == project_id)
            if session_id:
                stmt = stmt.where(ChatMessage.session_id == session_id)
            rows = (await session.execute(stmt.order_by(ChatMessage.seq))).scalars().all()
            return [_chat_dict(r) for r in rows]

    # ── Files & chunks ──────────────────────────────────────────────────────

    async def save_file(
        self,
        project_id: str,
        filename: str,
        content: bytes,
        extracted_text: str,
        chunks: list[dict[str, Any]],
        indexing_status: str = "ready",
    ) -> dict[str, Any]:
        file_id = str(uuid4())
        upload_root = self.upload_root.resolve()
        project_dir = (upload_root / project_id).resolve()
        if upload_root != project_dir and upload_root not in project_dir.parents:
            raise ValueError("Invalid project_id path")

        async with SessionLocal() as session:
            async with session.begin():
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

    async def get_file(self, file_id: str) -> dict[str, Any] | None:
        async with SessionLocal() as session:
            row = (
                await session.execute(select(File).where(File.id == file_id))
            ).scalar_one_or_none()
            if row is None:
                return None
            chunks = (
                await session.execute(
                    select(Chunk).where(Chunk.file_id == file_id).order_by(Chunk.idx)
                )
            ).scalars().all()
            return _file_dict(row, list(chunks))

    async def update_file_indexing_status(
        self, file_id: str, status: str, chunks: list[dict[str, Any]] | None = None
    ) -> bool:
        """Update indexing_status and optionally replace chunks (with embeddings)."""
        async with SessionLocal() as session:
            async with session.begin():
                row = (
                    await session.execute(select(File).where(File.id == file_id))
                ).scalar_one_or_none()
                if row is None:
                    return False
                row.indexing_status = status
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

    async def list_files(self, project_id: str) -> list[dict[str, Any]]:
        async with SessionLocal() as session:
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

    async def search_chunks(self, project_id: str, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Retrieve the most relevant file chunks for a query.

        Uses the two-stage hybrid retrieval engine (BM25 + TF-IDF fused with
        Reciprocal Rank Fusion, then a cross-encoder-style rerank) over
        contextualised chunks.
        The return shape is unchanged: {file_id, filename, chunk_id, text, score}.
        """
        if not query or not query.strip():
            return []
        from app.memory.hybrid_search import engine, build_chunk_documents
        from app.core.config import settings

        files = await self.list_files(project_id)
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

    async def delete_file(self, file_id: str) -> bool:
        """Remove a file record (and its chunks) and delete its bytes on disk."""
        async with SessionLocal() as session:
            async with session.begin():
                row = (
                    await session.execute(select(File).where(File.id == file_id))
                ).scalar_one_or_none()
                if row is None:
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

    async def create_artifact(self, project_id: str, name: str, content: str) -> dict[str, Any]:
        async with SessionLocal() as session:
            async with session.begin():
                row = Artifact(
                    id=str(uuid4()),
                    project_id=project_id,
                    name=name,
                    versions=[{"version": 1, "content": content, "created_at": _utc_now().isoformat()}],
                )
                session.add(row)
            return _artifact_dict(row)

    async def list_artifacts(self, project_id: str) -> list[dict[str, Any]]:
        async with SessionLocal() as session:
            rows = (
                await session.execute(
                    select(Artifact).where(Artifact.project_id == project_id).order_by(Artifact.created_at)
                )
            ).scalars().all()
            return [_artifact_dict(r) for r in rows]

    async def get_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        async with SessionLocal() as session:
            row = (
                await session.execute(select(Artifact).where(Artifact.id == artifact_id))
            ).scalar_one_or_none()
            return _artifact_dict(row) if row else None

    async def update_artifact(self, artifact_id: str, content: str) -> dict[str, Any] | None:
        async with SessionLocal() as session:
            async with session.begin():
                row = (
                    await session.execute(select(Artifact).where(Artifact.id == artifact_id))
                ).scalar_one_or_none()
                if row is None:
                    return None
                versions = list(row.versions or [])
                versions.append(
                    {"version": len(versions) + 1, "content": content, "created_at": _utc_now().isoformat()}
                )
                row.versions = versions  # reassign so the JSONB change is detected
            return _artifact_dict(row)

    # ── Memories ────────────────────────────────────────────────────────────

    async def save_memory(self, project_id: str, user_id: str, text: str) -> dict[str, Any]:
        async with SessionLocal() as session:
            async with session.begin():
                row = Memory(id=str(uuid4()), project_id=project_id, owner_id=user_id, text=text)
                session.add(row)
            return _memory_dict(row)

    async def list_memories(self, project_id: str, user_id: str) -> list[dict[str, Any]]:
        async with SessionLocal() as session:
            rows = (
                await session.execute(
                    select(Memory)
                    .where(Memory.project_id == project_id, Memory.owner_id == user_id)
                    .order_by(Memory.created_at)
                )
            ).scalars().all()
            return [_memory_dict(r) for r in rows]

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


repo = Repository()
