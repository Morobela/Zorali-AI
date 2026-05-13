from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class JsonStore:
    file_path: Path

    def __post_init__(self) -> None:
        self._lock = Lock()
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists():
            self._write({"projects": [], "chats": [], "files": [], "artifacts": []})

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
    def __init__(self, base_dir: str = "backend/data") -> None:
        self.store = JsonStore(Path(base_dir) / "store.json")
        self.upload_root = Path(base_dir) / "uploads"
        self.upload_root.mkdir(parents=True, exist_ok=True)

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
        project_dir = (self.upload_root / project_id).resolve()
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
        q = query.lower()
        files = self.list_files(project_id)
        scored = []
        for f in files:
            for c in f["chunks"]:
                text = c["text"]
                score = text.lower().count(q)
                if score > 0:
                    scored.append({"file_id": f["id"], "filename": f["filename"], "chunk_id": c["id"], "text": text, "score": score})
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


repo = Repository()
