"""Alembic upgrade → downgrade round trip on a clean, throwaway database.

Proves every migration's downgrade actually reverses its upgrade (a broken
downgrade otherwise only surfaces during an emergency rollback).
"""
import asyncio
import os
import subprocess
from pathlib import Path

import asyncpg
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

import app as _app_package
from app.core.config import settings

# The directory that holds alembic.ini/migrations — the parent of the `app`
# package. Works in the repo layout (backend/) and inside the image (/app).
BACKEND_DIR = Path(_app_package.__file__).resolve().parents[1]
SCRATCH_DB = "zorali_alembic_roundtrip"


def _run_alembic(command: list[str]) -> subprocess.CompletedProcess:
    env = {**os.environ, "POSTGRES_DB": SCRATCH_DB, "PYTHONPATH": str(BACKEND_DIR)}
    return subprocess.run(
        ["alembic", *command],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=120,
    )


async def _recreate_scratch_db() -> None:
    conn = await asyncpg.connect(
        user=settings.postgres_user, password=settings.postgres_password,
        host=settings.postgres_host, port=settings.postgres_port, database="postgres",
    )
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{SCRATCH_DB}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{SCRATCH_DB}"')
    finally:
        await conn.close()


async def _table_names() -> set[str]:
    url = (
        f"postgresql+asyncpg://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{SCRATCH_DB}"
    )
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(text(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            ))
            return {r[0] for r in rows}
    finally:
        await engine.dispose()


def test_upgrade_then_downgrade_round_trip_on_clean_database():
    asyncio.run(_recreate_scratch_db())

    up = _run_alembic(["upgrade", "head"])
    assert up.returncode == 0, f"upgrade failed:\n{up.stderr}"
    tables_after_up = asyncio.run(_table_names())
    assert "projects" in tables_after_up and "users" in tables_after_up

    down = _run_alembic(["downgrade", "base"])
    assert down.returncode == 0, f"downgrade failed:\n{down.stderr}"
    tables_after_down = asyncio.run(_table_names())
    # Only alembic's own bookkeeping table may remain.
    assert tables_after_down <= {"alembic_version"}, tables_after_down

    # And the cycle is repeatable: upgrade again on the downgraded database.
    up2 = _run_alembic(["upgrade", "head"])
    assert up2.returncode == 0, f"re-upgrade failed:\n{up2.stderr}"
