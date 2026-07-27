"""Model routing per step kind (capability map U7, optional half).

A plan is not homogeneous work: deciding which of three buckets a sentence
falls into does not need the model that writes the final report. The planner
labels each step with a kind and ``STEP_MODEL_POLICY`` turns that into a
model.

The property that matters most is precedence — a user who picked a model must
not have it silently overridden by a policy — and the payoff test at the
bottom shows what the feature is actually for: the mechanical steps of a goal
costing nothing while the synthesis step carries the spend.
"""
from __future__ import annotations

import pytest

from app.agents.goal_engine import GoalEngine
from app.agents.goal_planner import normalize_plan
from app.agents.model_policy import (
    CLASSIFICATION,
    GENERAL,
    SYNTHESIS,
    describe_policy,
    model_for_step,
    normalize_kind,
    parse_policy,
)
from app.core.config import settings
from app.db.repositories import repo
from app.inference.cost_meter import record_cost

from conftest import TEST_USER_SUB

CHEAP = "llama3.2:1b"
STRONG = "gpt-4o"
POLICY = f"classification={CHEAP},extraction={CHEAP},synthesis={STRONG}"


# ── the policy string ────────────────────────────────────────────────────────

def test_policy_parses_pairs_and_ignores_junk():
    parsed = parse_policy(f"classification={CHEAP}, synthesis={STRONG} ,garbage,=nothing,code=")
    assert parsed == {CLASSIFICATION: CHEAP, SYNTHESIS: STRONG}


def test_empty_policy_is_simply_off():
    assert parse_policy("") == {}
    assert parse_policy(None if False else "") == {}
    assert model_for_step(CLASSIFICATION, policy={}) is None


def test_unknown_kinds_fall_back_rather_than_routing_somewhere_unintended():
    """A label the model invented must not select a model by accident."""
    assert normalize_kind("interpretive dance") == GENERAL
    assert normalize_kind(None) == GENERAL
    assert normalize_kind("") == GENERAL
    # Near-misses still route sensibly.
    assert normalize_kind("Summarise") == SYNTHESIS
    assert normalize_kind("classify") == CLASSIFICATION

    policy = parse_policy(POLICY)
    assert model_for_step("interpretive dance", policy=policy) is None
    assert model_for_step("summarise", policy=policy) == STRONG


# ── precedence ───────────────────────────────────────────────────────────────

def test_explicit_model_beats_everything():
    policy = parse_policy(POLICY)
    chosen = model_for_step(
        CLASSIFICATION, explicit_model="qwen3:8b", goal_model=STRONG, policy=policy
    )
    assert chosen == "qwen3:8b"


def test_the_goal_s_own_model_beats_the_policy():
    """A user who picked a model in the UI meant it."""
    policy = parse_policy(POLICY)
    assert model_for_step(CLASSIFICATION, goal_model=STRONG, policy=policy) == STRONG


def test_policy_applies_only_when_nothing_was_chosen():
    policy = parse_policy(POLICY)
    assert model_for_step(CLASSIFICATION, policy=policy) == CHEAP
    assert model_for_step(SYNTHESIS, policy=policy) == STRONG
    assert model_for_step("research", policy=policy) is None  # not in the policy


def test_describe_policy_reports_the_current_configuration(monkeypatch):
    monkeypatch.setattr(settings, "step_model_policy", POLICY)
    described = describe_policy()
    assert described["enabled"] is True
    assert described["by_kind"][SYNTHESIS] == STRONG
    assert CLASSIFICATION in described["kinds"]

    monkeypatch.setattr(settings, "step_model_policy", "")
    assert describe_policy()["enabled"] is False


# ── the planner ──────────────────────────────────────────────────────────────

def test_planner_carries_the_kind_through():
    plan = normalize_plan({"tasks": [{"title": "t", "steps": [
        {"instruction": "sort the tickets", "kind": "classification"},
        {"instruction": "write the summary", "kind": "synthesis"},
    ]}]}, "objective")
    kinds = [s["kind"] for s in plan[0]["steps"]]
    assert kinds == [CLASSIFICATION, SYNTHESIS]


def test_steps_without_a_kind_are_general():
    plan = normalize_plan({"steps": ["do a thing"]}, "objective")
    assert plan[0]["steps"][0]["kind"] == GENERAL


def test_the_unparseable_fallback_is_treated_as_synthesis():
    """The fallback step carries the whole objective — that is real work, and
    must not be routed to the cheapest model by accident."""
    plan = normalize_plan(None, "write a report on local LLM hosting")
    assert plan[0]["steps"][0]["kind"] == SYNTHESIS


# ── the engine ───────────────────────────────────────────────────────────────

class _RecordingEngine(GoalEngine):
    """Captures the model each step was actually run with."""

    def __init__(self):
        super().__init__()
        self.seen: list[tuple[str, str | None]] = []

    async def _run_step(self, step, *, model=None, **kwargs):  # type: ignore[override]
        self.seen.append((step["instruction"], model))
        return f"result of {step['instruction']}", None


MIXED_PLAN = [{"title": "mixed", "steps": [
    {"instruction": "bucket the feedback", "kind": CLASSIFICATION, "depends_on": []},
    {"instruction": "write the brief", "kind": SYNTHESIS, "depends_on": [0]},
]}]


async def _goal(*, model="", policy_objective="policy goal"):
    return await repo.create_goal(
        policy_objective, MIXED_PLAN, project_id="default",
        owner_id=TEST_USER_SUB, status="running", model=model,
    )


@pytest.mark.asyncio
async def test_each_step_runs_on_the_model_its_kind_selects(monkeypatch):
    monkeypatch.setattr(settings, "step_model_policy", POLICY)
    goal = await _goal()
    engine = _RecordingEngine()
    final = await engine.execute_goal(goal["id"], owner_id=TEST_USER_SUB)

    assert final["status"] == "completed"
    assert engine.seen == [("bucket the feedback", CHEAP), ("write the brief", STRONG)]

    # And what each step ran on is recorded, so spend can be explained later.
    steps = {s["instruction"]: s for t in final["tasks"] for s in t["steps"]}
    assert steps["bucket the feedback"]["model"] == CHEAP
    assert steps["bucket the feedback"]["kind"] == CLASSIFICATION
    assert steps["write the brief"]["model"] == STRONG


@pytest.mark.asyncio
async def test_a_goal_with_its_own_model_ignores_the_policy(monkeypatch):
    monkeypatch.setattr(settings, "step_model_policy", POLICY)
    goal = await _goal(model="qwen3:8b", policy_objective="user picked a model")
    engine = _RecordingEngine()
    await engine.execute_goal(goal["id"], owner_id=TEST_USER_SUB)

    assert [m for _, m in engine.seen] == ["qwen3:8b", "qwen3:8b"]


@pytest.mark.asyncio
async def test_no_policy_leaves_routing_exactly_as_before(monkeypatch):
    monkeypatch.setattr(settings, "step_model_policy", "")
    goal = await _goal(policy_objective="unrouted goal")
    engine = _RecordingEngine()
    await engine.execute_goal(goal["id"], owner_id=TEST_USER_SUB)

    assert [m for _, m in engine.seen] == [None, None]


# ── what the feature is for ──────────────────────────────────────────────────

class _PricedByModelEngine(GoalEngine):
    """Bills like the real providers do: the local model is free."""

    def __init__(self, prices: dict[str | None, float]):
        super().__init__()
        self.prices = prices

    async def _run_step(self, step, *, model=None, **kwargs):  # type: ignore[override]
        record_cost(self.prices.get(model, 0.0), "openai" if model == STRONG else "ollama")
        return "ok", None


@pytest.mark.asyncio
async def test_routing_mechanical_steps_locally_puts_the_spend_on_synthesis(monkeypatch):
    """The point of the feature: the cheap steps cost nothing, and the goal's
    total is just the step that needed the strong model."""
    monkeypatch.setattr(settings, "step_model_policy", POLICY)
    goal = await _goal(policy_objective="mixed cost goal")
    engine = _PricedByModelEngine({CHEAP: 0.0, STRONG: 0.05})
    final = await engine.execute_goal(goal["id"], owner_id=TEST_USER_SUB)

    steps = {s["instruction"]: s for t in final["tasks"] for s in t["steps"]}
    assert steps["bucket the feedback"]["cost_usd"] == pytest.approx(0.0)
    assert steps["write the brief"]["cost_usd"] == pytest.approx(0.05)
    assert final["cost_usd"] == pytest.approx(0.05)


@pytest.mark.asyncio
async def test_without_the_policy_the_same_goal_costs_more(monkeypatch):
    """The comparison that justifies the setting: every step on the strong
    model bills for every step."""
    monkeypatch.setattr(settings, "step_model_policy", "")
    goal = await _goal(model=STRONG, policy_objective="all-strong goal")
    engine = _PricedByModelEngine({CHEAP: 0.0, STRONG: 0.05})
    final = await engine.execute_goal(goal["id"], owner_id=TEST_USER_SUB)

    assert final["cost_usd"] == pytest.approx(0.10), "both steps billed at the strong model"
