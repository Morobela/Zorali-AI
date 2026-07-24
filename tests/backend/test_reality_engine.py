"""Reality engine (capability map U3/U4).

Per-scanner unit tests with probes mocked or run against controlled local
fixtures, plus the two definitions of done:

- U3: a service observed up in one snapshot and down in the next produces a
  ``reality_events`` row ("redis: up → down").
- U4: that event produces an unread notification for the admin/owner
  accounts with no user request involved.
"""
from __future__ import annotations

import asyncio
import subprocess
import time

import pytest

from app.checkpoint.manager import CheckpointManager
from app.db.repositories import repo
from app.reality import service_health
from app.reality.git_scanner import scan_git
from app.reality.log_scanner import scan_logs
from app.reality.state_engine import RealityStateEngine

from conftest import TEST_USER_SUB


# ── service_health ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tcp_probe_up_and_down():
    """A live local listener probes up with a latency; a closed port is down."""
    server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        result = await service_health.check_services({
            "listening": {"kind": "tcp", "host": "127.0.0.1", "port": port},
        })
        assert result["listening"]["status"] == "up"
        assert result["listening"]["latency_ms"] >= 0
    finally:
        server.close()
        await server.wait_closed()

    result = await service_health.check_services({
        "closed": {"kind": "tcp", "host": "127.0.0.1", "port": port},
    })
    assert result["closed"]["status"] == "down"
    assert result["closed"]["latency_ms"] is None


@pytest.mark.asyncio
async def test_http_probe_mocked(monkeypatch):
    async def fake_http(url):
        return {"status": "up", "latency_ms": 12.5, "detail": "HTTP 200"}

    monkeypatch.setattr(service_health, "_probe_http", fake_http)
    result = await service_health.check_services({
        "ollama": {"kind": "http", "url": "http://nowhere.invalid/api/tags"},
    })
    assert result["ollama"] == {"status": "up", "latency_ms": 12.5, "detail": "HTTP 200"}


def test_default_targets_cover_configured_services():
    targets = service_health.default_targets()
    assert set(targets) == {"ollama", "postgres", "redis", "frontend"}


# ── git_scanner ───────────────────────────────────────────────────────────────

def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.mark.asyncio
async def test_git_scanner_reports_branch_dirty_and_last_commit(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _git(repo_dir, "init", "-b", "main")
    _git(repo_dir, "config", "user.email", "t@example.com")
    _git(repo_dir, "config", "user.name", "t")
    (repo_dir / "a.txt").write_text("one\n")
    _git(repo_dir, "add", "a.txt")
    _git(repo_dir, "commit", "-m", "first commit")
    (repo_dir / "b.txt").write_text("dirty\n")

    state = await scan_git(str(repo_dir))
    assert state["available"] is True
    assert state["branch"] == "main"
    assert state["dirty_files"] == 1
    assert state["last_commit"]["subject"] == "first commit"
    # No upstream configured → ahead/behind unknown, not an exception.
    assert state["ahead"] is None and state["behind"] is None


@pytest.mark.asyncio
async def test_git_scanner_degrades_outside_a_repo(tmp_path):
    state = await scan_git(str(tmp_path))
    assert state["available"] is False
    assert state["dirty_files"] == 0
    assert state["last_commit"] is None


# ── log_scanner ───────────────────────────────────────────────────────────────

def test_log_scanner_counts_error_patterns(tmp_path):
    log = tmp_path / "app.log"
    log.write_text(
        "INFO started\n"
        "ERROR db connect failed\n"
        "WARNING slow\n"
        "CRITICAL out of memory\n"
        "Traceback (most recent call last):\n"
        "  raise ValueError\n"
    )
    result = scan_logs([str(log)], tail_kb=64)
    assert result["total_errors"] == 3
    assert result["files"][0]["exists"] is True
    assert result["files"][0]["error_count"] == 3


def test_log_scanner_missing_file_is_soft(tmp_path):
    result = scan_logs([str(tmp_path / "nope.log")])
    assert result["total_errors"] == 0
    assert result["files"][0]["exists"] is False


def test_log_scanner_reads_only_the_tail(tmp_path):
    log = tmp_path / "big.log"
    # 2 KB of old ERROR lines, then a clean recent tail larger than the window.
    log.write_text("ERROR old\n" * 200 + "INFO fine\n" * 200)
    result = scan_logs([str(log)], tail_kb=1)
    assert result["total_errors"] == 0


# ── state engine: diff logic (pure) ──────────────────────────────────────────

def _snapshot(taken_at, services=None, dirty_files=0, dirty_since=None, total_errors=0):
    return {
        "taken_at": taken_at,
        "services": services or {},
        "git": {"available": True, "branch": "main", "ahead": 0, "behind": 0,
                "dirty_files": dirty_files, "last_commit": None},
        "logs": {"files": [], "total_errors": total_errors},
        "dirty_since": dirty_since,
    }


def test_diff_emits_service_down_and_recovered():
    up = {"redis": {"status": "up", "latency_ms": 1.0}}
    down = {"redis": {"status": "down", "latency_ms": None}}
    events = RealityStateEngine.diff(_snapshot(0, up), _snapshot(60, down))
    assert [e["kind"] for e in events] == ["service_down"]
    assert events[0]["subject"] == "redis"
    assert "up → down" in events[0]["detail"]

    events = RealityStateEngine.diff(_snapshot(60, down), _snapshot(120, up))
    assert [e["kind"] for e in events] == ["service_recovered"]


def test_diff_emits_error_jump_only_at_threshold(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "log_error_jump_threshold", 5)
    below = RealityStateEngine.diff(
        _snapshot(0, total_errors=0), _snapshot(60, total_errors=4)
    )
    assert below == []
    at = RealityStateEngine.diff(
        _snapshot(0, total_errors=0), _snapshot(60, total_errors=5)
    )
    assert [e["kind"] for e in at] == ["log_error_jump"]


def test_diff_emits_dirty_aging_once_when_crossing_threshold(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "dirty_age_threshold_hours", 1.0)
    t0 = 1_000_000.0
    hour = 3600.0
    # 30 min dirty → no event.
    events = RealityStateEngine.diff(
        _snapshot(t0, dirty_files=1, dirty_since=t0),
        _snapshot(t0 + hour / 2, dirty_files=1, dirty_since=t0),
    )
    assert events == []
    # Crossing 1h → event fires.
    events = RealityStateEngine.diff(
        _snapshot(t0 + hour / 2, dirty_files=1, dirty_since=t0),
        _snapshot(t0 + hour + 60, dirty_files=1, dirty_since=t0),
    )
    assert [e["kind"] for e in events] == ["dirty_changes_aging"]
    # Already past the threshold on both sides → no repeat notification spam.
    events = RealityStateEngine.diff(
        _snapshot(t0 + hour + 60, dirty_files=1, dirty_since=t0),
        _snapshot(t0 + 2 * hour, dirty_files=1, dirty_since=t0),
    )
    assert events == []


# ── U3 + U4 definitions of done ──────────────────────────────────────────────

def _make_engine(tmp_path):
    return RealityStateEngine(checkpoints=CheckpointManager(tmp_path / "ckpt"))


def _mock_scanners(monkeypatch, engine_module, services):
    async def fake_services(targets=None):
        return services

    async def fake_git(path):
        return {"available": True, "branch": "main", "ahead": 0, "behind": 0,
                "dirty_files": 0, "last_commit": None}

    monkeypatch.setattr(engine_module, "check_services", fake_services)
    monkeypatch.setattr(engine_module, "scan_git", fake_git)
    monkeypatch.setattr(engine_module, "scan_logs", lambda: {"files": [], "total_errors": 0})


@pytest.mark.asyncio
async def test_down_service_produces_event_row_and_unread_notification(tmp_path, monkeypatch):
    """U3 DoD: a service going down between scans produces a "redis: up →
    down" event row. U4 DoD: that event produces an unread notification for
    the owner account — no user request involved anywhere in this flow."""
    import app.reality.state_engine as engine_module

    engine = _make_engine(tmp_path)
    _mock_scanners(monkeypatch, engine_module, {"redis": {"status": "up", "latency_ms": 0.4}})
    first = await engine.run_scan()
    assert first["events"] == []  # first scan is the baseline

    before = await repo.list_notifications(owner_id=TEST_USER_SUB, unread_only=True)

    _mock_scanners(monkeypatch, engine_module, {"redis": {"status": "down", "latency_ms": None}})
    second = await engine.run_scan()
    assert [e["kind"] for e in second["events"]] == ["service_down"]

    # U3: the event row exists in the database.
    events = await repo.list_reality_events()
    down = [e for e in events if e["kind"] == "service_down" and e["subject"] == "redis"]
    assert down, f"no redis service_down event row in {events!r}"
    assert "up → down" in down[0]["detail"]

    # U4: the owner account has a new unread notification about it.
    after = await repo.list_notifications(owner_id=TEST_USER_SUB, unread_only=True)
    new = [n for n in after if n["id"] not in {b["id"] for b in before}]
    assert any(n["kind"] == "service_down" and "redis" in n["title"] for n in new), (
        f"no unread redis notification in {new!r}"
    )


@pytest.mark.asyncio
async def test_scan_persists_snapshot_and_carries_dirty_since(tmp_path, monkeypatch):
    """Consecutive scans restore the previous snapshot from the checkpoint
    store and keep the original dirty_since while the tree stays dirty."""
    import app.reality.state_engine as engine_module

    engine = _make_engine(tmp_path)

    async def fake_services(targets=None):
        return {"redis": {"status": "up", "latency_ms": 0.4}}

    async def fake_git(path):
        return {"available": True, "branch": "main", "ahead": 0, "behind": 0,
                "dirty_files": 2, "last_commit": None}

    monkeypatch.setattr(engine_module, "check_services", fake_services)
    monkeypatch.setattr(engine_module, "scan_git", fake_git)
    monkeypatch.setattr(engine_module, "scan_logs", lambda: {"files": [], "total_errors": 0})

    first = await engine.run_scan()
    started = first["snapshot"]["dirty_since"]
    assert started is not None
    assert started <= time.time()

    second = await engine.run_scan()
    assert second["snapshot"]["dirty_since"] == started
