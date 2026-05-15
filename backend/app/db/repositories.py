from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from string import punctuation
from threading import Lock
from typing import Any
from uuid import uuid4

STOPWORDS = {
    "a", "an", "the", "and", "or", "is", "are", "to", "of", "for", "on", "in", "it", "with", "as", "by", "at", "be", "this", "that", "from",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tokens(value: str) -> list[str]:
    cleaned = re.sub(f"[{re.escape(punctuation)}]", " ", value.lower())
    return [tok for tok in cleaned.split() if tok and tok not in STOPWORDS]


@dataclass
class JsonStore:
    file_path: Path

    def __post_init__(self) -> None:
        self._lock = Lock()
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists():
            self._write({"projects": [], "chats": [], "files": [], "artifacts": [], "memories": []})

    def _read(self) -> dict[str, Any]:
        with self.file_path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def _write(self, payload: dict[str, Any]) -> None:
        with self.file_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    def mutate(self, fn):
        with self._lock:
            state = self._read()
            result = fn(state)
            self._write(state)
            return result


class Repository:
    def __init__(self, base_dir: str | None = None) -> None:
        self.base_dir = self._resolve_base_dir(base_dir)
        self.store = JsonStore(self.base_dir / "store.json")
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

    def create_project(self, name: str, description: str = "") -> dict[str, Any]:
        project = {"id": str(uuid4()), "name": name, "description": description, "created_at": _utc_now()}
        self.store.mutate(lambda s: s["projects"].append(project))
        return project

    def list_projects(self) -> list[dict[str, Any]]:
        return self.store.mutate(lambda s: list(s["projects"]))

    def add_chat_message(self, project_id: str, session_id: str, role: str, content: str, citations: list[dict[str, Any]] | None = None):
        msg = {"id": str(uuid4()), "project_id": project_id, "session_id": session_id, "role": role, "content": content, "citations": citations or [], "created_at": _utc_now()}
        self.store.mutate(lambda s: s["chats"].append(msg))
        return msg

    def list_chat_messages(self, project_id: str, session_id: str | None = None):
        def _filter(s):
            rows = [m for m in s["chats"] if m["project_id"] == project_id]
            if session_id:
                rows = [m for m in rows if m["session_id"] == session_id]
            return rows

        return self.store.mutate(_filter)

    def save_file(self, project_id: str, filename: str, content: bytes, extracted_text: str, chunks: list[dict[str, Any]]):
        file_id = str(uuid4())
        upload_root = self.upload_root.resolve()
        project_dir = (upload_root / project_id).resolve()
        if upload_root != project_dir and upload_root not in project_dir.parents:
            raise ValueError("Invalid project_id path")
        project_exists = any(p["id"] == project_id for p in self.list_projects())
        if not project_exists:
            raise ValueError("Unknown project_id")
        project_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(filename).suffix.lower()
        storage_name = f"{file_id}{suffix}"
        full_path = (project_dir / storage_name).resolve()
        if project_dir not in full_path.parents:
            raise ValueError("Invalid upload path")
        full_path.write_bytes(content)
        record = {"id": file_id, "project_id": project_id, "filename": Path(filename).name, "path": str(full_path), "extracted_text": extracted_text, "chunks": chunks, "created_at": _utc_now()}
        self.store.mutate(lambda s: s["files"].append(record))
        return record

    def list_files(self, project_id: str):
        return self.store.mutate(lambda s: [f for f in s["files"] if f["project_id"] == project_id])

    def search_chunks(self, project_id: str, query: str, limit: int = 5):
        q_tokens = set(_tokens(query))
        if not q_tokens:
            return []
        files = self.list_files(project_id)
        scored = []
        for f in files:
            filename_tokens = set(_tokens(f["filename"]))
            filename_boost = 0.25 if q_tokens.intersection(filename_tokens) else 0.0
            for c in f["chunks"]:
                chunk_tokens = set(_tokens(c["text"]))
                overlap = q_tokens.intersection(chunk_tokens)
                if not overlap:
                    continue
                overlap_ratio = len(overlap) / max(len(q_tokens), 1)
                concise_boost = min(0.15, 200 / max(len(c["text"]), 200) * 0.15)
                recency_boost = 0.1
                score = overlap_ratio + filename_boost + concise_boost + recency_boost
                scored.append({"file_id": f["id"], "filename": f["filename"], "chunk_id": c["id"], "text": c["text"], "score": round(score, 4)})
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:limit]

    def create_artifact(self, project_id: str, name: str, content: str):
        artifact = {"id": str(uuid4()), "project_id": project_id, "name": name, "versions": [{"version": 1, "content": content, "created_at": _utc_now()}], "created_at": _utc_now()}
        self.store.mutate(lambda s: s["artifacts"].append(artifact))
        return artifact

    def list_artifacts(self, project_id: str):
        return self.store.mutate(lambda s: [a for a in s["artifacts"] if a["project_id"] == project_id])

    def get_artifact(self, artifact_id: str):
        rows = self.store.mutate(lambda s: [a for a in s["artifacts"] if a["id"] == artifact_id])
        return rows[0] if rows else None

    def update_artifact(self, artifact_id: str, content: str):
        def _update(s):
            for a in s["artifacts"]:
                if a["id"] == artifact_id:
                    next_version = len(a["versions"]) + 1
                    a["versions"].append({"version": next_version, "content": content, "created_at": _utc_now()})
                    return a
            return None

        return self.store.mutate(_update)

    def save_memory(self, project_id: str, user_id: str, text: str):
        memory = {"id": str(uuid4()), "project_id": project_id, "user_id": user_id, "text": text, "created_at": _utc_now()}
        self.store.mutate(lambda s: s["memories"].append(memory))
        return memory

    def search_memories(self, project_id: str, user_id: str, query: str, limit: int = 5):
        q_tokens = set(_tokens(query))
        if not q_tokens:
            return []
        rows = self.store.mutate(lambda s: [m for m in s["memories"] if m["project_id"] == project_id and m["user_id"] == user_id])
        scored = []
        for row in rows:
            t = set(_tokens(row["text"]))
            overlap = q_tokens.intersection(t)
            if overlap:
                scored.append({**row, "score": round(len(overlap) / max(len(q_tokens), 1), 4)})
        scored.sort(key=lambda r: r["score"], reverse=True)
        return scored[:limit]

    def delete_memory(self, memory_id: str, user_id: str) -> bool:
        def _delete(s):
            for i, m in enumerate(s["memories"]):
                if m["id"] == memory_id and m["user_id"] == user_id:
                    s["memories"].pop(i)
                    return True
            return False
        return self.store.mutate(_delete)
    def delete_file(self, file_id: str) -> bool:
        """Remove a file record from the store and delete its bytes on disk."""
        removed: dict | None = None

        def _remove(s):
            nonlocal removed
            for i, f in enumerate(s['files']):
                if f['id'] == file_id:
                    removed = s['files'].pop(i)
                    return True
            return False

        self.store.mutate(_remove)
        if removed is None:
            return False
        try:
            Path(removed['path']).unlink(missing_ok=True)
        except OSError:
            pass
        return True


repo = Repository()
