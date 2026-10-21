"""User-configurable routines.

The built-in routines (reality scan, nightly self-check, nightly backup) are
compiled into the deployment. This hands the same idea to an account, which
means the bounds stop being the deployment's problem and start being the
feature's: a user-defined thing that runs unattended and spends money is a
money pump without them.

The DoD: a routine a user created fires on its own and produces an unread
notification, with no user request in between.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.db.repositories import repo
from app.main import app
from conftest import TEST_USER_SUB as OWNER

client = TestClient(app)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def clean_slate():
    """Each test starts with no routines for this account.

    Routines persist by design, so without this the per-user cap test trips
    over what earlier tests left behind — an isolation problem, not a product
    one.
    """
    for existing in client.get("/api/routines").json():
        client.delete(f"/api/routines/{existing['id']}")
    yield
    for existing in client.get("/api/routines").json():
        client.delete(f"/api/routines/{existing['id']}")


@pytest.fixture
def fake_model(monkeypatch):
    """A provider that answers without touching Ollama."""
    import app.agents.routine_runner as runner_module

    async def fake_stream(_messages, **_kwargs):
        yield "Two files changed since yesterday."

    monkeypatch.setattr(runner_module, "stream_llm", fake_stream)
    return fake_stream


def make_routine(**overrides) -> dict:
    body = {
        "name": f"morning-brief-{uuid4().hex[:6]}",
        "prompt": "What changed in my project?",
        "interval_seconds": max(settings.routine_min_interval_seconds, 300),
    }
    body.update(overrides)
    resp = client.post("/api/routines", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── the definition of done ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_user_routine_fires_on_its_own_and_notifies(fake_model) -> None:
    """The definition of done.

    Nothing between creating the routine and being told something: no user
    request, no manual run. Only the clock moves.
    """
    from app.agents.routine_runner import tick

    routine = make_routine()
    # The clock is the only nudge — pretend its time arrived.
    await repo.update_routine(
        routine["id"], owner_id=OWNER, next_run_at=_utc_now() - timedelta(seconds=1)
    )
    before = client.get("/api/notifications?unread_only=true").json()

    ran = await tick()

    after = client.get("/api/notifications?unread_only=true").json()
    assert ran["ran"] >= 1
    assert len(after) > len(before)
    mine = [n for n in after if n["title"] == routine["name"]]
    assert mine, f"no notification titled {routine['name']!r} in {after!r}"
    assert "Two files changed" in mine[0]["body"]
    assert mine[0]["read"] is False


# ── the schedule ─────────────────────────────────────────────────────────────

def test_the_next_run_is_set_when_a_routine_is_created() -> None:
    routine = make_routine()

    assert routine["next_run_at"]
    assert routine["enabled"] is True


def test_a_daily_routine_lands_on_its_hour() -> None:
    from app.agents.routine_runner import next_run_after

    now = datetime(2026, 7, 28, 10, 30, tzinfo=timezone.utc)
    nxt = next_run_after({"schedule_kind": "daily", "hour_utc": 8}, now=now)

    # 08:00 has passed today, so tomorrow.
    assert nxt == datetime(2026, 7, 29, 8, 0, tzinfo=timezone.utc)


def test_an_interval_routine_counts_from_now_not_from_when_it_was_due() -> None:
    """A late routine must not fire repeatedly to catch up."""
    from app.agents.routine_runner import next_run_after

    now = _utc_now()
    nxt = next_run_after({"schedule_kind": "interval", "interval_seconds": 600}, now=now)

    assert abs((nxt - now).total_seconds() - 600) < 1


# ── the bounds ───────────────────────────────────────────────────────────────

def test_an_interval_below_the_floor_is_refused() -> None:
    # "Every 10 seconds" is a legal way to bill a deployment continuously.
    resp = client.post("/api/routines", json={
        "name": "too-eager", "prompt": "hi", "interval_seconds": 5,
    })

    assert resp.status_code == 422
    assert "at least" in resp.text


def test_an_unknown_schedule_kind_is_refused() -> None:
    resp = client.post("/api/routines", json={
        "name": "cron-please", "prompt": "hi", "schedule_kind": "cron",
    })

    assert resp.status_code == 422


def test_a_user_cannot_exceed_the_enabled_routine_cap(monkeypatch) -> None:
    monkeypatch.setattr(settings, "routine_max_per_user", 1)
    first = make_routine()

    resp = client.post("/api/routines", json={
        "name": "second", "prompt": "hi",
        "interval_seconds": settings.routine_min_interval_seconds,
    })

    assert resp.status_code == 409
    client.delete(f"/api/routines/{first['id']}")


@pytest.mark.asyncio
async def test_a_run_that_overspends_disables_the_routine(monkeypatch, fake_model) -> None:
    """The cap bounds repetition: one overspend and the routine stops."""
    import app.agents.routine_runner as runner_module

    monkeypatch.setattr(settings, "routine_max_cost_usd", 0.001)
    routine = make_routine()

    async def expensive(_messages, **_kwargs):
        from app.inference.cost_meter import record_cost

        record_cost(5.0, "cloud")
        yield "an expensive answer"

    monkeypatch.setattr(runner_module, "stream_llm", expensive)
    outcome = await runner_module.run_routine(
        await repo.get_routine(routine["id"], owner_id=OWNER),
        owner_id=OWNER,
    )

    assert outcome["status"] == "over_budget"
    after = await repo.get_routine(routine["id"], owner_id=OWNER)
    assert after["enabled"] is False
    assert "ceiling" in after["disabled_reason"] or "ceiling" in outcome["error"]


@pytest.mark.asyncio
async def test_a_repeatedly_failing_routine_disables_itself(monkeypatch) -> None:
    """A routine that fails hourly and notifies hourly trains its owner to
    ignore the channel that also carries real work."""
    import app.agents.routine_runner as runner_module

    monkeypatch.setattr(settings, "routine_failure_limit", 2)
    routine = make_routine()

    async def broken(_messages, **_kwargs):
        raise RuntimeError("provider down")
        yield  # pragma: no cover

    monkeypatch.setattr(runner_module, "stream_llm", broken)
    owner = OWNER
    for _ in range(2):
        current = await repo.get_routine(routine["id"], owner_id=owner)
        await runner_module.run_routine(current, owner_id=owner)

    after = await repo.get_routine(routine["id"], owner_id=owner)
    assert after["enabled"] is False
    assert "consecutive failures" in after["disabled_reason"]


def test_re_enabling_clears_the_strike_count() -> None:
    routine = make_routine()
    client.patch(f"/api/routines/{routine['id']}", json={"enabled": False})

    resp = client.patch(f"/api/routines/{routine['id']}", json={"enabled": True})

    assert resp.status_code == 200
    assert resp.json()["consecutive_failures"] == 0
    assert resp.json()["disabled_reason"] == ""


# ── ownership ────────────────────────────────────────────────────────────────

def test_another_accounts_routine_is_not_visible() -> None:
    routine = make_routine()

    # The repository refuses to hand it over under a different owner.
    import asyncio

    other = asyncio.get_event_loop_policy().new_event_loop()
    try:
        found = other.run_until_complete(
            repo.get_routine(routine["id"], owner_id="somebody-else")
        )
    finally:
        other.close()

    assert found is None


def test_a_missing_routine_is_404() -> None:
    assert client.get(f"/api/routines/{uuid4().hex}").status_code == 404
    assert client.delete(f"/api/routines/{uuid4().hex}").status_code == 404


# ── run history ──────────────────────────────────────────────────────────────

def test_run_now_records_a_run(fake_model) -> None:
    routine = make_routine()

    outcome = client.post(f"/api/routines/{routine['id']}/run")
    runs = client.get(f"/api/routines/{routine['id']}/runs").json()

    assert outcome.status_code == 200
    assert outcome.json()["status"] == "completed"
    assert len(runs) == 1
    assert runs[0]["status"] == "completed"
    assert "Two files changed" in runs[0]["result"]
