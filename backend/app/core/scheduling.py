"""Small scheduling helper shared by the nightly routines.

Both the self-check (U8) and the backup (U9) run at a configured UTC hour and
re-arm themselves after each run, so the "when is the next one" calculation
lives here rather than in either feature.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


def seconds_until_next_run(now_epoch: float, hour_utc: int) -> float:
    """Seconds from ``now`` until the next occurrence of ``hour_utc``."""
    now = datetime.fromtimestamp(now_epoch, tz=timezone.utc)
    target = now.replace(hour=hour_utc % 24, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()
