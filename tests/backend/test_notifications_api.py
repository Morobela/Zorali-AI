"""Notifications API (capability map U4): owner-scoped list, unread count,
mark-read and read-all. Creation happens only through background routines,
so tests seed rows via the repository, never via HTTP."""
import asyncio

from fastapi.testclient import TestClient

from app.db.models import User
from app.db.repositories import repo
from app.db.session import SessionLocal
from app.main import app

from conftest import TEST_USER_SUB

client = TestClient(app)


def _seed(kind="service_down", title="[redis] service down", user=TEST_USER_SUB):
    return asyncio.run(repo.create_notification(user, kind, title, body="redis: up → down"))


def test_list_unread_count_and_mark_read():
    note = _seed()
    assert client.get("/api/notifications/unread-count").json()["unread"] >= 1

    unread = client.get("/api/notifications?unread_only=true").json()
    assert any(n["id"] == note["id"] for n in unread)

    assert client.post(f"/api/notifications/{note['id']}/read").json()["read"] is True
    unread = client.get("/api/notifications?unread_only=true").json()
    assert all(n["id"] != note["id"] for n in unread)

    # The full list still shows it, now flagged read with a timestamp.
    row = next(n for n in client.get("/api/notifications").json() if n["id"] == note["id"])
    assert row["read"] is True and row["read_at"]


def test_notifications_are_owner_scoped():
    async def _other_user_note():
        async with SessionLocal() as session:
            async with session.begin():
                session.add(User(id="other-notif-user", email="other-notif@zorali.local", role="user"))
        return await repo.create_notification("other-notif-user", "service_down", "[redis] service down")

    note = asyncio.run(_other_user_note())
    # Someone else's notification behaves like a nonexistent one.
    assert client.post(f"/api/notifications/{note['id']}/read").json()["read"] is False
    assert all(n["id"] != note["id"] for n in client.get("/api/notifications").json())


def test_read_all_clears_the_badge():
    _seed(kind="log_error_jump", title="[logs] log error jump")
    _seed(kind="dirty_changes_aging", title="[git] dirty changes aging")
    assert client.post("/api/notifications/read-all").json()["marked"] >= 2
    assert client.get("/api/notifications/unread-count").json()["unread"] == 0
