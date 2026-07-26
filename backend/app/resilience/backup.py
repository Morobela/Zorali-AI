"""Database backups with rotation (capability map U9).

A scheduled ``pg_dump`` into the data directory, keeping the last N dumps —
the same keep-last-N shape as ``checkpoint/manager.py``, with a JSON manifest
beside the files so the set is inspectable without stat-ing the directory.

Two details that matter more than the code length:

- **The password never appears in an argv.** It goes in the child's
  environment, so it cannot be read out of the process table.
- **A dump is verified before it counts.** pg_dump can exit 0 having written
  something useless; the file must exist, be non-trivial, and carry
  PostgreSQL's own header. A backup you have not checked is a rumour.

The restore path is documented in ``docs/DEPLOYMENT.md`` and exercised by
``tests/backend/test_backup_restore.py``, which restores a dump into a
scratch database and logs in against it.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings

_log = logging.getLogger(__name__)

MANIFEST_NAME = "manifest.json"
_DUMP_PREFIX = "zorali-"
_DUMP_SUFFIX = ".sql"
# A dump smaller than this is not a real schema, whatever pg_dump's exit code.
_MIN_PLAUSIBLE_BYTES = 2048
_HEADER_MARKER = b"PostgreSQL database dump"


def backup_dir() -> Path:
    """Where dumps live: ``$ZORALI_DATA_DIR/backups`` (matching checkpoints)."""
    base = Path(os.environ.get("ZORALI_DATA_DIR", "/app/data"))
    path = base / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _manifest_path() -> Path:
    return backup_dir() / MANIFEST_NAME


def read_manifest() -> list[dict]:
    path = _manifest_path()
    if not path.exists():
        return []
    try:
        entries = json.loads(path.read_text())
        return entries if isinstance(entries, list) else []
    except Exception:
        return []


def _write_manifest(entries: list[dict]) -> None:
    _manifest_path().write_text(json.dumps(entries, indent=2))


def _pg_env() -> dict[str, str]:
    """Child environment carrying the password out of the command line."""
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/local/bin"),
        "PGPASSWORD": settings.postgres_password,
        # Keep pg_dump's messages parseable regardless of the host locale.
        "LC_ALL": "C",
    }


def verify_dump(path: Path) -> str | None:
    """Reason the dump is unusable, or ``None`` when it looks sound."""
    if not path.exists():
        return "dump file was not created"
    size = path.stat().st_size
    if size < _MIN_PLAUSIBLE_BYTES:
        return f"dump is implausibly small ({size} bytes)"
    with path.open("rb") as handle:
        head = handle.read(4096)
    if _HEADER_MARKER not in head:
        return "dump does not carry a PostgreSQL dump header"
    return None


def rotate(keep: int) -> list[str]:
    """Delete all but the newest ``keep`` dumps. Returns the removed names.

    Mirrors the checkpoint manager: newest kept, oldest pruned, manifest
    rewritten to match what is actually on disk.
    """
    directory = backup_dir()
    dumps = sorted(
        (p for p in directory.glob(f"{_DUMP_PREFIX}*{_DUMP_SUFFIX}") if p.is_file()),
        key=lambda p: p.name,
        reverse=True,
    )
    removed: list[str] = []
    for stale in dumps[max(0, keep):]:
        try:
            stale.unlink()
            removed.append(stale.name)
        except OSError:
            continue

    # Successful entries track the files; failure entries have no file and
    # must survive anyway — a manifest that silently forgot last night's
    # failure would be worse than no manifest at all. Failures are capped so
    # the list cannot grow without bound.
    surviving = {p.name for p in directory.glob(f"{_DUMP_PREFIX}*{_DUMP_SUFFIX}")}
    entries = read_manifest()
    kept_ok = [e for e in entries if e.get("name") in surviving]
    failures = [e for e in entries if e.get("status") != "ok"][-keep:]
    kept_names = {id(e) for e in kept_ok}
    merged = kept_ok + [e for e in failures if id(e) not in kept_names]
    merged.sort(key=lambda e: e.get("created_at", ""))
    _write_manifest(merged)
    return removed


async def run_backup(*, keep: int | None = None) -> dict:
    """Take one dump, verify it, rotate the set. Never raises.

    Returns the manifest entry, with ``status`` ``"ok"`` or ``"failed"``.
    """
    keep = settings.backup_keep if keep is None else keep
    started = datetime.now(timezone.utc)
    name = f"{_DUMP_PREFIX}{started.strftime('%Y%m%dT%H%M%SZ')}{_DUMP_SUFFIX}"
    target = backup_dir() / name
    entry: dict = {
        "name": name,
        "created_at": started.isoformat(),
        "database": settings.postgres_db,
        "status": "failed",
        "bytes": 0,
        "error": "",
    }

    if shutil.which("pg_dump") is None:
        entry["error"] = "pg_dump is not installed"
        _record(entry, keep)
        return entry

    args = [
        "pg_dump",
        "--host", settings.postgres_host,
        "--port", str(settings.postgres_port),
        "--username", settings.postgres_user,
        "--dbname", settings.postgres_db,
        # Restorable into a fresh database owned by whoever runs the restore.
        "--no-owner", "--no-privileges",
        "--file", str(target),
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, env=_pg_env(),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await asyncio.wait_for(
            proc.communicate(), timeout=settings.backup_timeout_seconds
        )
        if proc.returncode != 0:
            entry["error"] = out.decode(errors="replace").strip()[:500] or "pg_dump failed"
            target.unlink(missing_ok=True)
            _record(entry, keep)
            return entry
    except asyncio.TimeoutError:
        entry["error"] = f"pg_dump timed out after {settings.backup_timeout_seconds:.0f}s"
        target.unlink(missing_ok=True)
        _record(entry, keep)
        return entry
    except Exception as exc:
        entry["error"] = f"{type(exc).__name__}: {exc}"
        target.unlink(missing_ok=True)
        _record(entry, keep)
        return entry

    problem = verify_dump(target)
    if problem:
        entry["error"] = problem
        target.unlink(missing_ok=True)
        _record(entry, keep)
        return entry

    entry["status"] = "ok"
    entry["bytes"] = target.stat().st_size
    _record(entry, keep)
    return entry


def _record(entry: dict, keep: int) -> None:
    """Append to the manifest, prune, and tell someone when it went wrong."""
    entries = read_manifest()
    entries.append(entry)
    _write_manifest(entries)
    rotate(keep)
    if entry["status"] != "ok":
        _log.warning("Backup failed: %s", entry["error"])


async def notify_backup_result(entry: dict) -> None:
    """A failed backup is worth waking someone for; a good one is not.

    Silence on success is deliberate: a nightly "backup ok" notification
    trains people to ignore the channel that also carries "backup failed".
    """
    if entry.get("status") == "ok":
        return
    try:
        from app.db.repositories import repo

        for user_id in await repo.list_admin_user_ids():
            await repo.create_notification(
                user_id, "backup_failed",
                "Database backup failed",
                body=f"{entry.get('name', 'backup')}: {entry.get('error', 'unknown error')}",
            )
    except Exception:
        return


def latest_backup() -> dict | None:
    """Newest successful dump in the manifest."""
    ok = [e for e in read_manifest() if e.get("status") == "ok"]
    return sorted(ok, key=lambda e: e.get("name", ""))[-1] if ok else None
