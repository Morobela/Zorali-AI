"""
Pytest configuration for backend tests.

- Points the app at a local Postgres (POSTGRES_HOST defaults to localhost;
  CI starts a pgvector/pgvector:pg16 service container and runs the Alembic
  migration before pytest).
- Ensures the schema exists and starts from an empty database, and seeds the
  "test-user" account that the auth override below impersonates (projects.owner_id
  is a foreign key to users).
- Applies a dependency override so all protected HTTP routes accept requests
  without a real JWT. WebSocket handlers authenticate with single-use tickets
  (POST /api/ws-ticket, Redis-backed), so tests that open a WebSocket call the
  ws_ticket() helper below for a fresh ticket per connection.
"""
import asyncio
import os

os.environ.setdefault("POSTGRES_HOST", "localhost")
# WS auth tickets live in Redis (CI starts a redis:7 service; locally the dev
# compose publishes 6379).
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
# The whole suite shares one unauthenticated client identity (ip:testclient);
# production limits would 429 mid-run, so give tests an effectively unlimited bucket.
os.environ.setdefault("RATE_LIMIT_CAPACITY", "100000")
os.environ.setdefault("RATE_LIMIT_REFILL", "100000")
# Automatic memory extraction can fall back to a real LLM call after any chat
# turn; keep it off suite-wide so unrelated WS tests never touch a provider.
# test_auto_memory.py re-enables it per-test with monkeypatched fakes.
os.environ.setdefault("AUTO_MEMORY_ENABLED", "false")
# Same reasoning for one-shot conversation titles (LLM call after the first
# assistant reply); test_conversation_ux.py re-enables it with fakes.
os.environ.setdefault("AUTO_TITLES_ENABLED", "false")

from sqlalchemy import delete, text

from app.main import app
from app.core.rbac import get_current_user
from app.db.models import Base, User
from app.db.session import SessionLocal, engine

TEST_USER_SUB = "test-user"


async def _prepare_database() -> None:
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        # No-op when the Alembic migration has already run (CI); creates the
        # schema directly for local runs against a fresh database.
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as session:
        async with session.begin():
            for table in reversed(Base.metadata.sorted_tables):
                await session.execute(delete(table))
            session.add(User(id=TEST_USER_SUB, email="test-user@zorali.local", role="owner"))


asyncio.run(_prepare_database())


def _test_user() -> dict:
    return {"sub": TEST_USER_SUB, "role": "owner"}


app.dependency_overrides[get_current_user] = _test_user


def ws_ticket(client) -> str:
    """Fresh single-use WebSocket auth ticket for the impersonated test user."""
    resp = client.post("/api/ws-ticket")
    assert resp.status_code == 200, resp.text
    return resp.json()["ticket"]
