"""Planning and replanning for the durable goal engine (capability map U1).

Two single-shot LLM calls, deliberately kept in their own module so they are
patchable independently of execution:

``plan_goal``   decomposes an objective into ordered tasks and steps.
``replan``      receives the failure context of a step that failed and may
                rewrite the goal's remaining steps.

Local models produce untidy JSON, so parsing is forgiving: fenced code
blocks, prose preambles and several plausible shapes are all accepted, and a
plan that cannot be parsed at all degrades to a single step carrying the
original objective. A goal therefore always has something to execute — the
planner can never leave it stuck.
"""
from __future__ import annotations

import json
import re

from app.agents.model_policy import GENERAL, SYNTHESIS, normalize_kind
from app.models.llm import stream_llm

MAX_TASKS = 8
MAX_STEPS_PER_TASK = 8
MAX_REPLAN_STEPS = 8

_PLAN_PROMPT = """You are Zorali's planner. Decompose the user's objective into a short, ordered plan.

Reply with JSON ONLY, in exactly this shape:
{"tasks": [{"title": "short task name", "steps": [{"instruction": "one concrete action", "kind": "synthesis", "depends_on": []}]}]}

Rules:
- 1 to 4 tasks, each with 1 to 4 steps. Fewer is better.
- "kind" is what sort of work the step is, one of: classification (deciding
  which category something falls into), extraction (pulling stated facts out
  of text), research (finding information), synthesis (writing, summarising,
  reasoning across sources), code (writing or changing code). Label honestly:
  mechanical steps may be routed to a smaller, cheaper model, so calling
  routine work "synthesis" wastes money and calling real synthesis
  "classification" produces a worse answer.
- Each step's "instruction" must be a self-contained action an assistant can
  carry out in one turn (research something, draft something, summarize
  something). Never reference "the previous step" implicitly — say what is needed.
- "depends_on" lists the indices (0-based, within the same task) of sibling
  steps that must finish first. Use [] when a step needs nothing from its
  siblings — independent steps are executed in parallel, so mark them
  accurately: list a dependency only when the step genuinely needs that
  step's output, and leave it empty otherwise.
- No prose, no code fences, no explanation. JSON only."""

_REPLAN_PROMPT = """You are Zorali's planner, fixing a plan that just failed.

A step of the current goal failed. Decide how the remaining work should
proceed, given what already succeeded and how the step failed.

Reply with JSON ONLY, in exactly this shape:
{"steps": [{"instruction": "one concrete action", "kind": "synthesis", "depends_on": []}]}

Rules:
- 0 to 4 steps. Return {"steps": []} if the goal cannot sensibly continue.
- Do NOT repeat work that already succeeded — it is listed as completed.
- Address the failure: work around it, or split it into smaller actions.
- No prose, no code fences. JSON only."""


def _extract_json_object(raw: str) -> dict | None:
    """Best-effort JSON object extraction from a model reply."""
    text = raw.strip()
    if not text:
        return None
    # Strip ``` / ```json fences when present.
    fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i, ch in enumerate(text[start:], start=start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return None
                return parsed if isinstance(parsed, dict) else None
    return None


def _normalize_steps(raw_steps: object, *, limit: int) -> list[dict]:
    """Accept ["do x", ...] or [{"instruction": "do x", "depends_on": [0]}, ...]."""
    if not isinstance(raw_steps, list):
        return []
    steps: list[dict] = []
    for entry in raw_steps[:limit]:
        kind = GENERAL
        if isinstance(entry, str):
            instruction, depends = entry, []
        elif isinstance(entry, dict):
            instruction = entry.get("instruction") or entry.get("step") or entry.get("action") or ""
            kind = normalize_kind(entry.get("kind") or entry.get("type"))
            raw_depends = entry.get("depends_on")
            depends = [
                int(d) for d in raw_depends
                if isinstance(raw_depends, list) and isinstance(d, (int, float, str)) and str(d).lstrip("-").isdigit()
            ] if isinstance(raw_depends, list) else []
        else:
            continue
        instruction = str(instruction).strip()
        if not instruction:
            continue
        # A dependency can only point at an earlier sibling step.
        position = len(steps)
        steps.append({
            "instruction": instruction,
            "kind": kind,
            "depends_on": sorted({d for d in depends if 0 <= d < position}),
        })
    return steps


def normalize_plan(parsed: dict | None, objective: str) -> list[dict]:
    """Turn a parsed planner reply into the repository's plan shape.

    Falls back to one task with a single step (the objective itself) whenever
    the reply is missing, malformed or empty.
    """
    # The fallback carries the whole objective, so it is synthesis work — not
    # something to route to the cheapest model by accident.
    fallback = [{
        "title": objective[:200],
        "steps": [{"instruction": objective, "kind": SYNTHESIS, "depends_on": []}],
    }]
    if not isinstance(parsed, dict):
        return fallback

    raw_tasks = parsed.get("tasks")
    plan: list[dict] = []
    if isinstance(raw_tasks, list):
        for entry in raw_tasks[:MAX_TASKS]:
            if not isinstance(entry, dict):
                continue
            steps = _normalize_steps(entry.get("steps"), limit=MAX_STEPS_PER_TASK)
            title = str(entry.get("title") or "").strip()
            if not steps:
                # A task with a title but no steps still describes work to do.
                if not title:
                    continue
                steps = [{"instruction": title, "depends_on": []}]
            plan.append({"title": (title or steps[0]["instruction"])[:200], "steps": steps})
    elif isinstance(parsed.get("steps"), list):
        # Flat {"steps": [...]} shape — one implicit task.
        steps = _normalize_steps(parsed["steps"], limit=MAX_STEPS_PER_TASK)
        if steps:
            plan.append({"title": objective[:200], "steps": steps})

    return plan or fallback


async def plan_goal(
    objective: str, *, model: str | None = None, local_first: bool = True
) -> list[dict]:
    """One planning call → the plan in repository shape. Never raises."""
    messages = [
        {"role": "system", "content": _PLAN_PROMPT},
        {"role": "user", "content": f"Objective: {objective}"},
    ]
    try:
        chunks: list[str] = []
        async for token in stream_llm(messages, model=model, local_first=local_first):
            chunks.append(token)
        return normalize_plan(_extract_json_object("".join(chunks)), objective)
    except Exception:
        # Provider down mid-plan: still give the goal one executable step.
        return normalize_plan(None, objective)


async def replan(
    objective: str,
    *,
    failed_instruction: str,
    error: str,
    completed: list[dict],
    remaining: list[dict],
    model: str | None = None,
    local_first: bool = True,
) -> list[dict]:
    """Rewrite the remaining steps after a failure.

    This is the message-level retry pattern in ``agents/nodes.py`` (a failure
    summary prepended before the next attempt) promoted to plan level: the
    planner sees what succeeded, what failed and how, and returns the new
    remaining steps. An empty list means "stop" — the caller fails the goal.
    Never raises; on any error the remaining steps are left untouched.
    """
    completed_block = "\n".join(
        f"- {c['instruction']} → {(c.get('result') or '')[:300]}" for c in completed
    ) or "(nothing completed yet)"
    remaining_block = "\n".join(f"- {r['instruction']}" for r in remaining) or "(none)"
    context = (
        f"Objective: {objective}\n\n"
        f"Completed so far:\n{completed_block}\n\n"
        f"FAILED step: {failed_instruction}\n"
        f"Failure: {error[:600]}\n\n"
        f"Remaining steps in the old plan:\n{remaining_block}"
    )
    messages = [
        {"role": "system", "content": _REPLAN_PROMPT},
        {"role": "user", "content": context},
    ]
    try:
        chunks: list[str] = []
        async for token in stream_llm(messages, model=model, local_first=local_first):
            chunks.append(token)
        parsed = _extract_json_object("".join(chunks))
    except Exception:
        return list(remaining)
    if not isinstance(parsed, dict) or "steps" not in parsed:
        return list(remaining)
    return _normalize_steps(parsed.get("steps"), limit=MAX_REPLAN_STEPS)
