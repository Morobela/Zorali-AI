#!/usr/bin/env python3
"""One-shot import of a legacy JSON store (data/store.json) into Postgres.

Usage:
    python infra/scripts/import_json_store.py [path/to/store.json]

Defaults to <repo>/data/store.json. Connects using the same POSTGRES_*
settings as the backend (override via environment, e.g. POSTGRES_HOST=localhost).
Idempotent: rows whose ids already exist in Postgres are skipped, so the
script can be re-run safely.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from sqlalchemy import select, text  # noqa: E402

from app.db.models import Artifact, Base, ChatMessage, Chunk, File, Memory, Project  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402


def _dt(value) -> datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


async def _existing_ids(session, model) -> set[str]:
    return set((await session.execute(select(model.id))).scalars().all())


async def run(store_path: Path) -> None:
    data = json.loads(store_path.read_text(encoding="utf-8"))
    counts: dict[str, int] = {}

    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as session:
        async with session.begin():
            projects = await _existing_ids(session, Project)
            for p in data.get("projects", []):
                if p["id"] in projects:
                    continue
                session.add(Project(
                    id=p["id"], name=p.get("name", ""), description=p.get("description", ""),
                    created_at=_dt(p.get("created_at")),
                ))
                projects.add(p["id"])
                counts["projects"] = counts.get("projects", 0) + 1

            files = await _existing_ids(session, File)
            for f in data.get("files", []):
                if f["id"] in files or f.get("project_id") not in projects:
                    continue
                session.add(File(
                    id=f["id"], project_id=f["project_id"], filename=f.get("filename", ""),
                    path=f.get("path"), extracted_text=f.get("extracted_text", ""),
                    indexing_status=f.get("indexing_status", "ready"),
                    created_at=_dt(f.get("created_at")),
                ))
                for c in f.get("chunks", []):
                    session.add(Chunk(
                        file_id=f["id"], idx=c.get("id", 0), text=c.get("text", ""),
                        embedding=c.get("embedding"),
                        embedding_model=c.get("embedding_model"),
                    ))
                files.add(f["id"])
                counts["files"] = counts.get("files", 0) + 1

            artifacts = await _existing_ids(session, Artifact)
            for a in data.get("artifacts", []):
                if a["id"] in artifacts or a.get("project_id") not in projects:
                    continue
                session.add(Artifact(
                    id=a["id"], project_id=a["project_id"], name=a.get("name", ""),
                    versions=a.get("versions", []), created_at=_dt(a.get("created_at")),
                ))
                counts["artifacts"] = counts.get("artifacts", 0) + 1

            memories = await _existing_ids(session, Memory)
            for m in data.get("memories", []):
                if m["id"] in memories:
                    continue
                session.add(Memory(
                    id=m["id"], project_id=m.get("project_id", "default"),
                    owner_id=m.get("user_id", "local"), text=m.get("text", ""),
                    created_at=_dt(m.get("created_at")),
                ))
                counts["memories"] = counts.get("memories", 0) + 1

            chats = await _existing_ids(session, ChatMessage)
            for c in data.get("chats", []):
                if c["id"] in chats:
                    continue
                session.add(ChatMessage(
                    id=c["id"], project_id=c.get("project_id", "default"),
                    session_id=c.get("session_id", "default"), role=c.get("role", "user"),
                    content=c.get("content", ""), citations=c.get("citations", []),
                    created_at=_dt(c.get("created_at")),
                ))
                counts["chats"] = counts.get("chats", 0) + 1

    await engine.dispose()
    imported = ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "nothing (all rows already present)"
    print(f"Imported: {imported}")


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "data" / "store.json"
    if not path.exists():
        sys.exit(f"Store file not found: {path}")
    asyncio.run(run(path))
