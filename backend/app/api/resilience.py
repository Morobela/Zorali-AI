"""Backup inspection and on-demand runs (capability map U9).

Admin-gated: backups describe the deployment, not one user's data. The
manifest is metadata only — the dumps themselves are never served over HTTP,
because a database dump is every account's data in one file.
"""
from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.core.config import settings
from app.core.rbac import admin_or_above
from app.resilience.backup import latest_backup, read_manifest, run_backup

router = APIRouter(prefix="/api/backups", tags=["backups"])


@router.get("")
async def list_backups(_user=admin_or_above):
    """The backup manifest, newest first, plus the latest good dump."""
    entries = sorted(read_manifest(), key=lambda e: e.get("name", ""), reverse=True)
    return {"backups": entries, "latest_ok": latest_backup(), "keep": settings.backup_keep}


@router.post("/run", status_code=202)
async def trigger_backup(background_tasks: BackgroundTasks, _user=admin_or_above):
    """Take a backup now, rather than waiting for the nightly run."""
    if not settings.backup_enabled:
        raise HTTPException(status_code=403, detail="Backups are disabled")

    async def _run_and_notify() -> None:
        from app.resilience.backup import notify_backup_result

        entry = await run_backup()
        await notify_backup_result(entry)

    background_tasks.add_task(_run_and_notify)
    return {"status": "started"}
