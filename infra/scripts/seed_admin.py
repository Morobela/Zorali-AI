#!/usr/bin/env python3
"""Create the owner (admin) account from environment variables — idempotent.

Usage:
    ZORALI_ADMIN_EMAIL=admin@example.com ZORALI_ADMIN_PASSWORD=... \
        python infra/scripts/seed_admin.py

Connects using the same POSTGRES_* settings as the backend (override via
environment, e.g. POSTGRES_HOST=localhost). Re-running is a no-op when the
account already exists.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from passlib.context import CryptContext  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.db.models import User  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402


async def run() -> None:
    email = os.environ.get("ZORALI_ADMIN_EMAIL", "").strip().lower()
    password = os.environ.get("ZORALI_ADMIN_PASSWORD", "")
    if not email or not password:
        sys.exit("Set ZORALI_ADMIN_EMAIL and ZORALI_ADMIN_PASSWORD in the environment")
    if len(password) < 8:
        sys.exit("ZORALI_ADMIN_PASSWORD must be at least 8 characters")

    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    async with SessionLocal() as session:
        async with session.begin():
            existing = (
                await session.execute(select(User).where(User.email == email))
            ).scalar_one_or_none()
            if existing:
                print(f"Owner account already exists: {email} (role={existing.role}) — nothing to do")
                return
            session.add(
                User(id=str(uuid4()), email=email, password_hash=pwd_context.hash(password), role="owner")
            )
            print(f"Created owner account: {email}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
