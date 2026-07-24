"""Tail configured log files and count error-pattern hits.

Reads only the last ``LOG_SCAN_TAIL_KB`` of each file (a scan cycle must
stay cheap on multi-GB logs) and counts lines matching common error
signatures. Missing or unreadable files report ``exists: False`` with a
zero count instead of raising.
"""
from __future__ import annotations

import re
from pathlib import Path

from app.core.config import settings

# Uppercase level names as whole words, plus the Python traceback header.
ERROR_PATTERN = re.compile(r"\b(ERROR|CRITICAL|FATAL)\b|Traceback \(most recent call last\)")


def _configured_paths() -> list[str]:
    return [p.strip() for p in settings.log_scan_paths.split(",") if p.strip()]


def _tail_text(path: Path, tail_kb: int) -> str:
    with path.open("rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        fh.seek(max(0, size - tail_kb * 1024))
        return fh.read().decode(errors="replace")


def scan_logs(paths: list[str] | None = None, tail_kb: int | None = None) -> dict:
    """Scan each log tail → per-file error counts plus a total."""
    paths = _configured_paths() if paths is None else paths
    tail_kb = settings.log_scan_tail_kb if tail_kb is None else tail_kb

    files = []
    total = 0
    for raw in paths:
        path = Path(raw)
        entry = {"path": str(path), "exists": False, "error_count": 0}
        try:
            if path.is_file():
                entry["exists"] = True
                entry["error_count"] = len(ERROR_PATTERN.findall(_tail_text(path, tail_kb)))
                total += entry["error_count"]
        except OSError:
            pass
        files.append(entry)
    return {"files": files, "total_errors": total}
