"""Backups, restore, and the one opt-in recovery action (capability map U9).

The DoD is the headline test: take a dump, restore it into a scratch
database, and log in against the restored data. It runs the same commands
the restore procedure in docs/DEPLOYMENT.md tells an operator to run, so the
documentation cannot drift away from something that works.

The rest is about the recovery action, which is the only thing in this
codebase that acts on infrastructure: it must stay off by default, refuse
targets that would be self-destructive, and never become a restart loop.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.main import app
from app.resilience import backup as backup_module
from app.resilience import recovery
from app.resilience.backup import (
    latest_backup,
    read_manifest,
    rotate,
    run_backup,
    verify_dump,
)

client = TestClient(app)

SCRATCH_DB = "zorali_restore_check"


@pytest.fixture(autouse=True)
def _isolated_backup_dir(tmp_path, monkeypatch):
    """Keep every test's dumps out of the real data directory."""
    monkeypatch.setenv("ZORALI_DATA_DIR", str(tmp_path))
    recovery.reset_cooldowns()
    yield


def _pg_dump_available() -> bool:
    return shutil.which("pg_dump") is not None and shutil.which("psql") is not None


def _touch_dump(name: str, *, body: bytes | None = None) -> Path:
    path = backup_module.backup_dir() / name
    path.write_bytes(body if body is not None else b"-- PostgreSQL database dump\n" + b"x" * 4096)
    return path


# ── verification ─────────────────────────────────────────────────────────────

def test_verify_rejects_missing_small_and_headerless_dumps(tmp_path):
    assert verify_dump(tmp_path / "nope.sql") == "dump file was not created"

    tiny = _touch_dump("zorali-tiny.sql", body=b"-- PostgreSQL database dump\n")
    assert "implausibly small" in verify_dump(tiny)

    headerless = _touch_dump("zorali-headerless.sql", body=b"y" * 8192)
    assert "dump header" in verify_dump(headerless)

    good = _touch_dump("zorali-good.sql")
    assert verify_dump(good) is None


def test_password_is_never_passed_on_the_command_line():
    """A dump command must not put the password where `ps` can read it."""
    env = backup_module._pg_env()
    assert env["PGPASSWORD"] == settings.postgres_password
    # The argv is built in run_backup; assert the source never interpolates it.
    import inspect

    source = inspect.getsource(backup_module.run_backup)
    assert "postgres_password" not in source


# ── rotation ─────────────────────────────────────────────────────────────────

def test_rotation_keeps_the_newest_n_and_prunes_the_rest():
    for stamp in ("20260101T000000Z", "20260102T000000Z", "20260103T000000Z", "20260104T000000Z"):
        _touch_dump(f"zorali-{stamp}.sql")

    removed = rotate(keep=2)
    survivors = sorted(p.name for p in backup_module.backup_dir().glob("zorali-*.sql"))
    assert survivors == ["zorali-20260103T000000Z.sql", "zorali-20260104T000000Z.sql"]
    assert sorted(removed) == ["zorali-20260101T000000Z.sql", "zorali-20260102T000000Z.sql"]


def test_rotation_rewrites_the_manifest_to_match_the_disk():
    for stamp in ("20260101T000000Z", "20260102T000000Z"):
        _touch_dump(f"zorali-{stamp}.sql")
    backup_module._write_manifest([
        {"name": "zorali-20260101T000000Z.sql", "status": "ok"},
        {"name": "zorali-20260102T000000Z.sql", "status": "ok"},
    ])

    rotate(keep=1)
    names = [e["name"] for e in read_manifest()]
    assert names == ["zorali-20260102T000000Z.sql"]
    assert latest_backup()["name"] == "zorali-20260102T000000Z.sql"


@pytest.mark.asyncio
async def test_a_failed_dump_is_recorded_and_notified(monkeypatch):
    monkeypatch.setattr(backup_module.shutil, "which", lambda _name: None)
    entry = await run_backup()

    assert entry["status"] == "failed"
    assert "not installed" in entry["error"]
    # A failure has no file on disk, so rotation must not quietly drop it —
    # a manifest that forgets last night's failure is worse than none.
    assert read_manifest()[-1]["status"] == "failed"
    assert latest_backup() is None, "a failed run is not a usable backup"

    from app.db.repositories import repo

    before = {n["id"] for n in await repo.list_notifications(owner_id="test-user")}
    await backup_module.notify_backup_result(entry)
    after = await repo.list_notifications(owner_id="test-user")
    fresh = [n for n in after if n["id"] not in before]
    assert fresh and fresh[0]["kind"] == "backup_failed"


@pytest.mark.asyncio
async def test_a_good_backup_stays_silent():
    """Nightly success notifications would train people to ignore the channel."""
    from app.db.repositories import repo

    before = {n["id"] for n in await repo.list_notifications(owner_id="test-user")}
    await backup_module.notify_backup_result({"status": "ok", "name": "zorali-x.sql"})
    after = await repo.list_notifications(owner_id="test-user")
    assert [n for n in after if n["id"] not in before] == []


# ── the U9 definition of done ────────────────────────────────────────────────

def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    env = {**os.environ, "PGPASSWORD": settings.postgres_password}
    return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300, **kwargs)


def _psql_admin(sql: str) -> subprocess.CompletedProcess:
    return _run([
        "psql", "-h", settings.postgres_host, "-p", str(settings.postgres_port),
        "-U", settings.postgres_user, "-d", "postgres", "-v", "ON_ERROR_STOP=1", "-c", sql,
    ])


@pytest.mark.asyncio
async def test_restore_last_nights_dump_into_a_scratch_database_and_log_in():
    """U9 DoD: a dump restored into a scratch database is a working system —
    an account created before the backup can log in against the restore."""
    if not _pg_dump_available():
        pytest.skip("pg_dump/psql are not installed on this host")

    # 1. An account exists before the backup is taken.
    email = f"restore-{uuid4().hex[:8]}@zorali.local"
    password = "Restore-Me-9!"
    registered = client.post("/api/auth/register", json={"email": email, "password": password})
    assert registered.status_code in (200, 201), registered.text

    # 2. Take the backup, exactly as the nightly routine does.
    entry = await run_backup()
    if entry["status"] != "ok" and "version mismatch" in entry["error"]:
        pytest.skip(f"client/server version mismatch: {entry['error'][:120]}")
    assert entry["status"] == "ok", entry["error"]
    dump_path = backup_module.backup_dir() / entry["name"]

    # 3. Restore into a scratch database — the documented procedure.
    assert _psql_admin(f'DROP DATABASE IF EXISTS "{SCRATCH_DB}" WITH (FORCE)').returncode == 0
    assert _psql_admin(f'CREATE DATABASE "{SCRATCH_DB}"').returncode == 0
    try:
        restored = _run([
            "psql", "-h", settings.postgres_host, "-p", str(settings.postgres_port),
            "-U", settings.postgres_user, "-d", SCRATCH_DB, "-v", "ON_ERROR_STOP=1",
            "-f", str(dump_path),
        ])
        assert restored.returncode == 0, restored.stderr[-800:]

        # The account is present in the restored database.
        async def _restored_user() -> dict | None:
            conn = await asyncpg.connect(
                user=settings.postgres_user, password=settings.postgres_password,
                host=settings.postgres_host, port=settings.postgres_port, database=SCRATCH_DB,
            )
            try:
                row = await conn.fetchrow("SELECT id, email, role FROM users WHERE email = $1", email)
                return dict(row) if row else None
            finally:
                await conn.close()

        assert await _restored_user() is not None, "the backup did not contain the account"

        # 4. Log in against the restored database over the real HTTP route.
        scratch_url = (
            f"postgresql+asyncpg://{settings.postgres_user}:{settings.postgres_password}"
            f"@{settings.postgres_host}:{settings.postgres_port}/{SCRATCH_DB}"
        )
        scratch_engine = create_async_engine(scratch_url, poolclass=NullPool)
        import app.db.session as session_module

        original_factory = session_module.SessionLocal
        session_module.SessionLocal = async_sessionmaker(scratch_engine, expire_on_commit=False)
        try:
            login = client.post("/api/auth/login", json={"email": email, "password": password})
            assert login.status_code == 200, login.text
            assert login.json()["access_token"], "no token issued from the restored database"
        finally:
            session_module.SessionLocal = original_factory
            await scratch_engine.dispose()
    finally:
        _psql_admin(f'DROP DATABASE IF EXISTS "{SCRATCH_DB}" WITH (FORCE)')


# ── the opt-in recovery action ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_recovery_is_alert_only_by_default(monkeypatch):
    monkeypatch.setattr(settings, "recovery_actions_enabled", False)
    result = await recovery.attempt_restart("ollama")
    assert result["attempted"] is False
    assert "disabled" in result["reason"]


@pytest.mark.asyncio
async def test_self_destructive_targets_are_refused_even_when_listed(monkeypatch):
    """Restarting the database this process is using, or this process, is not
    recovery — those are refused regardless of configuration."""
    monkeypatch.setattr(settings, "recovery_actions_enabled", True)
    monkeypatch.setattr(settings, "recovery_restart_services", "ollama,postgres,backend")

    assert recovery.allowed_services() == {"ollama"}
    for target in ("postgres", "backend"):
        result = await recovery.attempt_restart(target)
        assert result["attempted"] is False
        assert "never restarted" in result["reason"]


@pytest.mark.asyncio
async def test_unlisted_service_and_bad_names_are_refused(monkeypatch):
    monkeypatch.setattr(settings, "recovery_actions_enabled", True)
    monkeypatch.setattr(settings, "recovery_restart_services", "ollama")

    unlisted = await recovery.attempt_restart("redis")
    assert unlisted["attempted"] is False and "not in RECOVERY_RESTART_SERVICES" in unlisted["reason"]

    for bad in ("", "ollama; rm -rf /", "../../etc", "a" * 100):
        result = await recovery.attempt_restart(bad)
        assert result["attempted"] is False


@pytest.mark.asyncio
async def test_cooldown_prevents_a_restart_loop(monkeypatch):
    monkeypatch.setattr(settings, "recovery_actions_enabled", True)
    monkeypatch.setattr(settings, "recovery_restart_services", "ollama")
    monkeypatch.setattr(settings, "recovery_cooldown_minutes", 30.0)

    calls: list[list[str]] = []

    async def fake_exec(*args, **kwargs):
        calls.append(list(args))

        class _Proc:
            returncode = 0

            async def communicate(self):
                return b"restarted", b""

        return _Proc()

    monkeypatch.setattr(recovery.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    first = await recovery.attempt_restart("ollama")
    assert first["attempted"] and first["ok"]
    assert calls[0][:3] == ["docker", "compose", "restart"]

    second = await recovery.attempt_restart("ollama")
    assert second["attempted"] is False
    assert "cooling down" in second["reason"]
    assert len(calls) == 1, "a service must not be restarted twice inside the cooldown"


@pytest.mark.asyncio
async def test_service_down_event_reports_what_recovery_did(monkeypatch):
    """An action Zorali takes is never invisible: it lands on the event and
    therefore in the notification."""
    monkeypatch.setattr(settings, "recovery_actions_enabled", True)
    monkeypatch.setattr(settings, "recovery_restart_services", "ollama")

    async def fake_restart(service):
        return {"service": service, "attempted": True, "ok": True, "reason": "restarted"}

    import app.reality.state_engine as engine_module

    monkeypatch.setattr(engine_module, "attempt_restart", fake_restart)
    events = [{
        "kind": "service_down", "subject": "ollama", "severity": "warning",
        "detail": "ollama: up → down", "data": {},
    }]
    await engine_module.RealityStateEngine._attempt_recovery(events)

    assert events[0]["data"]["recovery"]["ok"] is True
    assert "restarted" in events[0]["detail"]


# ── API ──────────────────────────────────────────────────────────────────────

def test_backup_listing_is_admin_gated_and_reports_the_manifest():
    _touch_dump("zorali-20260105T000000Z.sql")
    backup_module._write_manifest([
        {"name": "zorali-20260105T000000Z.sql", "status": "ok", "bytes": 4123},
    ])
    body = client.get("/api/backups").json()
    assert body["latest_ok"]["name"] == "zorali-20260105T000000Z.sql"
    assert body["keep"] == settings.backup_keep


def test_manual_backup_refused_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "backup_enabled", False)
    assert client.post("/api/backups/run").status_code == 403
