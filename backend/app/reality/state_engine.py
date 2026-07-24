"""Reality state engine: snapshot → persist → diff → events → notifications.

Each scan cycle assembles the scanner outputs (service health, git state,
log error counts) into one snapshot, persists it through the checkpoint
manager, and diffs it against the previous snapshot. Differences become
``reality_events`` rows; the notable ones — a service going down, an
error-count jump, uncommitted changes aging past the threshold — also post
an unread notification to every admin/owner account (capability map U4).

Runs as the first CONTINUOUS task on the orchestration task queue, submitted
at boot (see ``app.main``).
"""
from __future__ import annotations

import time

from app.checkpoint.manager import CheckpointManager, checkpoint_manager
from app.core.config import settings
from app.db.repositories import repo
from app.reality.git_scanner import scan_git
from app.reality.log_scanner import scan_logs
from app.reality.service_health import check_services

CHECKPOINT_NAME = "reality_state"

# Event kinds that also produce a notification, mapped to severity.
_NOTIFY_KINDS = {"service_down": "warning", "log_error_jump": "warning", "dirty_changes_aging": "info"}


class RealityStateEngine:
    def __init__(self, checkpoints: CheckpointManager | None = None):
        self._checkpoints = checkpoints or checkpoint_manager

    async def snapshot(self) -> dict:
        """Assemble the current reality snapshot from all scanners."""
        return {
            "taken_at": time.time(),
            "services": await check_services(),
            "git": await scan_git(settings.project_root),
            "logs": scan_logs(),
            # Since when the working tree has been continuously dirty;
            # carried across snapshots by run_scan().
            "dirty_since": None,
        }

    @staticmethod
    def _carry_dirty_since(prev: dict | None, curr: dict) -> None:
        if curr["git"]["dirty_files"] <= 0:
            curr["dirty_since"] = None
            return
        if prev and prev.get("dirty_since") and prev.get("git", {}).get("dirty_files", 0) > 0:
            curr["dirty_since"] = prev["dirty_since"]
        else:
            curr["dirty_since"] = curr["taken_at"]

    @staticmethod
    def diff(prev: dict, curr: dict) -> list[dict]:
        """Differences between two consecutive snapshots, as event dicts."""
        events: list[dict] = []

        prev_services = prev.get("services", {})
        for name, state in curr.get("services", {}).items():
            before = prev_services.get(name, {}).get("status")
            after = state.get("status")
            if before is not None and before != after:
                kind = "service_down" if after == "down" else "service_recovered"
                events.append({
                    "kind": kind,
                    "subject": name,
                    "severity": "warning" if after == "down" else "info",
                    "detail": f"{name}: {before} → {after}",
                    "data": {"before": before, "after": after, "latency_ms": state.get("latency_ms")},
                })

        prev_errors = prev.get("logs", {}).get("total_errors", 0)
        curr_errors = curr.get("logs", {}).get("total_errors", 0)
        jump = curr_errors - prev_errors
        if jump >= settings.log_error_jump_threshold:
            events.append({
                "kind": "log_error_jump",
                "subject": "logs",
                "severity": "warning",
                "detail": f"log error count jumped by {jump} (from {prev_errors} to {curr_errors})",
                "data": {"before": prev_errors, "after": curr_errors},
            })

        threshold_s = settings.dirty_age_threshold_hours * 3600
        prev_age = (prev.get("taken_at", 0) - prev["dirty_since"]) if prev.get("dirty_since") else 0
        curr_age = (curr["taken_at"] - curr["dirty_since"]) if curr.get("dirty_since") else 0
        if prev_age < threshold_s <= curr_age:
            hours = curr_age / 3600
            dirty = curr.get("git", {}).get("dirty_files", 0)
            events.append({
                "kind": "dirty_changes_aging",
                "subject": "git",
                "severity": "info",
                "detail": f"{dirty} uncommitted change(s) sitting for {hours:.1f}h "
                          f"(threshold {settings.dirty_age_threshold_hours:g}h)",
                "data": {"dirty_files": dirty, "age_hours": round(hours, 2)},
            })

        return events

    async def run_scan(self) -> dict:
        """One full cycle: snapshot, diff against the previous one, persist.

        The first cycle establishes the baseline and emits no events. This is
        the ``fn`` of the CONTINUOUS queue task, so it must return normally
        on partial failure — the scanners already degrade instead of raising.
        """
        prev = self._checkpoints.restore(CHECKPOINT_NAME)
        curr = await self.snapshot()
        self._carry_dirty_since(prev, curr)

        events = self.diff(prev, curr) if prev else []
        for event in events:
            await repo.create_reality_event(
                event["kind"], event["subject"],
                severity=event["severity"], detail=event["detail"], data=event["data"],
            )
        await self._notify(events)

        self._checkpoints.save(CHECKPOINT_NAME, curr)
        return {"snapshot": curr, "events": events}

    @staticmethod
    async def _notify(events: list[dict]) -> None:
        """Post notable events as unread notifications to admin+ accounts."""
        notable = [e for e in events if e["kind"] in _NOTIFY_KINDS]
        if not notable:
            return
        recipients = await repo.list_admin_user_ids()
        for event in notable:
            title = f"[{event['subject']}] {event['kind'].replace('_', ' ')}"
            for user_id in recipients:
                await repo.create_notification(user_id, event["kind"], title, body=event["detail"])


reality_engine = RealityStateEngine()
