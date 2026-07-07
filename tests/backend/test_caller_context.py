"""Required caller context (user id | SYSTEM) on the data-access layer.

The old convention — ``owner_id=None`` silently meaning "trusted caller" —
is gone. Every repository/retrieval/tool call must state who it acts for;
``None`` (e.g. a missing JWT ``sub``) raises instead of disabling scoping.
"""
import asyncio

import pytest
from fastapi.testclient import TestClient

from app.core.caller import SYSTEM
from app.db.models import User
from app.db.repositories import repo
from app.db.session import SessionLocal
from app.main import app
from app.memory.retrieval import hybrid_retriever
from app.tools.registry import registry

client = TestClient(app)

OTHER_SUB = "caller-ctx-other-user"


def _ensure_other_user():
    async def _seed():
        async with SessionLocal() as session:
            async with session.begin():
                if await session.get(User, OTHER_SUB) is None:
                    session.add(User(id=OTHER_SUB, email=f"{OTHER_SUB}@zorali.local", role="user"))
    asyncio.run(_seed())


def _other_users_project() -> str:
    _ensure_other_user()
    project = asyncio.run(repo.create_project("caller-ctx-proj", owner_id=OTHER_SUB))
    asyncio.run(repo.save_file(
        project_id=project["id"], filename="secret.md", content=b"x",
        extracted_text="the secret launch date is friday",
        chunks=[{"id": 0, "text": "the secret launch date is friday"}],
        owner_id=OTHER_SUB,
    ))
    return project["id"]


# ── Unscoped calls are impossible ────────────────────────────────────────────

def test_repo_rejects_missing_owner_id():
    with pytest.raises(TypeError):
        asyncio.run(repo.list_files("any-project"))


def test_repo_rejects_none_owner_id():
    """A missing JWT sub must never turn into trusted-caller mode."""
    with pytest.raises(TypeError):
        asyncio.run(repo.list_files("any-project", owner_id=None))
    with pytest.raises(TypeError):
        asyncio.run(repo.search_chunks("any-project", "q", owner_id=None))


def test_retriever_rejects_missing_and_none_owner():
    with pytest.raises(TypeError):
        asyncio.run(hybrid_retriever.retrieve("q", project_id="any"))
    with pytest.raises(TypeError):
        asyncio.run(hybrid_retriever.retrieve("q", project_id="any", owner_id=None))


def test_registry_execute_requires_caller():
    with pytest.raises(TypeError):
        asyncio.run(registry.execute("calculator", {"expression": "1+1"}))


# ── Scoping is enforced for real callers ─────────────────────────────────────

def test_repo_scopes_out_other_users_rows():
    pid = _other_users_project()
    # The owner sees the file; a different user sees "no such project".
    assert asyncio.run(repo.list_files(pid, owner_id=OTHER_SUB))
    assert asyncio.run(repo.list_files(pid, owner_id="test-user")) is None
    assert asyncio.run(repo.search_chunks(pid, "secret launch", owner_id="test-user")) is None


def test_document_search_tool_is_scoped_to_caller():
    pid = _other_users_project()
    hits_as_owner = asyncio.run(registry.execute(
        "document_search", {"project_id": pid, "query": "secret launch"}, caller=OTHER_SUB,
    ))
    assert hits_as_owner["hits"], "owner should retrieve their own chunks"
    hits_as_stranger = asyncio.run(registry.execute(
        "document_search", {"project_id": pid, "query": "secret launch"}, caller="test-user",
    ))
    assert hits_as_stranger["hits"] == [], "another user's project must look empty"


def test_system_marker_bypasses_scoping_explicitly():
    pid = _other_users_project()
    files = asyncio.run(repo.list_files(pid, owner_id=SYSTEM))
    assert files and files[0]["filename"] == "secret.md"
