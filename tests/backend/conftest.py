"""
Pytest configuration for backend tests.

- Points the app at a local Postgres (POSTGRES_HOST defaults to localhost;
  CI starts a pgvector/pgvector:pg16 service container and runs the Alembic
  migration before pytest).
- Ensures the schema exists and starts from an empty database, and seeds the
  "test-user" account that the auth override below impersonates (projects.owner_id
  is a foreign key to users).
- Applies a dependency override so all protected HTTP routes accept requests
  without a real JWT. The WebSocket handler validates tokens directly in route
  code (not via FastAPI Depends), so tests that open a WebSocket must supply
  the _WS_TOKEN defined in each test module instead.
"""
import asyncio
import os

os.environ.setdefault("POSTGRES_HOST", "localhost")
# The whole suite shares one unauthenticated client identity (ip:testclient);
# production limits would 429 mid-run, so give tests an effectively unlimited bucket.
os.environ.setdefault("RATE_LIMIT_CAPACITY", "100000")
os.environ.setdefault("RATE_LIMIT_REFILL", "100000")

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
