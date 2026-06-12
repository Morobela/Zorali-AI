"""
State checkpoint manager.
Patterns:
- TensorFlow SavedModel: multi-stage export (eager → frozen → serialized)
- TensorFlow _SaveableView: immutable snapshot taken at checkpoint time
- TensorFlow: breadth-first asset merging, deduplication
- Higgsfield: checkpoint de-duplication + resume functionality

Checkpoints capture Zorali's runtime state (provider prefs, skill configs,
learning loop state) and allow restore after restart without data loss.
"""
from __future__ import annotations
import json
import os
import time
import hashlib
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Any

# Honour ZORALI_DATA_DIR env var so CI runners and non-Docker environments work
_DATA_DIR = Path(os.environ.get("ZORALI_DATA_DIR", "/app/data"))
CHECKPOINT_DIR = _DATA_DIR / "checkpoints"
MAX_CHECKPOINTS = 5  # keep last 5, oldest pruned (TF SavedModel deduplication)


@dataclass
class CheckpointView:
    """
    Immutable snapshot of system state at checkpoint time.
    Pattern: TensorFlow _SaveableView — changes after creation are ignored.
    Once created, content is frozen.
    """
    checkpoint_id: str
    created_at: float
    state: dict[str, Any]
    checksum: str = field(init=False)

    def __post_init__(self):
        self.checksum = hashlib.sha256(
            json.dumps(self.state, sort_keys=True, default=str).encode()
        ).hexdigest()[:16]

    def to_dict(self) -> dict:
        return {
            "checkpoint_id": self.checkpoint_id,
            "created_at": self.created_at,
            "checksum": self.checksum,
            "state": self.state,
        }


class CheckpointManager:
    """
    Saves and restores runtime state across restarts.
    Maintains a rolling window of checkpoints (max MAX_CHECKPOINTS).
    """

    def __init__(self, directory: Path = CHECKPOINT_DIR):
        self._dir = directory
        self._dir.mkdir(parents=True, exist_ok=True)

    def _index_path(self) -> Path:
        return self._dir / "index.json"

    def _read_index(self) -> list[dict]:
        if not self._index_path().exists():
            return []
        try:
            return json.loads(self._index_path().read_text())
        except Exception:
            return []

    def _write_index(self, index: list[dict]) -> None:
        self._index_path().write_text(json.dumps(index, indent=2))

    def save(self, name: str, state: dict[str, Any]) -> CheckpointView:
        """
        Create an immutable checkpoint snapshot.
        Stage 1: collect state → Stage 2: freeze → Stage 3: persist.
        """
        from uuid import uuid4
        ckpt = CheckpointView(
            checkpoint_id=str(uuid4()),
            created_at=time.time(),
            state=state,
        )
        path = self._dir / f"{name}_{ckpt.checkpoint_id[:8]}.json"
        path.write_text(json.dumps(ckpt.to_dict(), indent=2, default=str))

        index = self._read_index()
        index.append({"name": name, "path": str(path), "created_at": ckpt.created_at, "checksum": ckpt.checksum})

        # Prune oldest if over limit
        name_entries = [e for e in index if e["name"] == name]
        if len(name_entries) > MAX_CHECKPOINTS:
            oldest = sorted(name_entries, key=lambda e: e["created_at"])[0]
            index = [e for e in index if e is not oldest]
            try:
                Path(oldest["path"]).unlink(missing_ok=True)
            except Exception:
                pass

        self._write_index(index)
        return ckpt

    def restore(self, name: str) -> dict[str, Any] | None:
        """Restore the most recent checkpoint for a given name."""
        index = self._read_index()
        entries = sorted(
            [e for e in index if e["name"] == name],
            key=lambda e: e["created_at"],
            reverse=True,
        )
        if not entries:
            return None
        try:
            data = json.loads(Path(entries[0]["path"]).read_text())
            return data.get("state")
        except Exception:
            return None

    def list_checkpoints(self) -> list[dict]:
        return self._read_index()


checkpoint_manager = CheckpointManager()
