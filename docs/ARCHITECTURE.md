# Architecture

A monorepo: React/Vite frontend, FastAPI backend, Postgres 16 + pgvector,
Redis, and Ollama for local inference with an optional OpenAI-compatible cloud
fallback. Everything runs on one host through `docker compose`.

Two things run inside the backend process, and keeping them straight explains
most of the codebase:

- **The request path** — HTTP and WebSocket handlers answering a user.
- **The autonomous runtime** — an asyncio task queue that acts without being
  asked. This is what the capability map (U1–U9) added, and it is the part a
  reader coming from the original chat app will not expect.

## The request path

```
browser ──HTTP──▶ nginx (prod) ──▶ FastAPI routers ──▶ repositories ──▶ Postgres
        ──WS───▶ /ws/chat/{session} ──▶ chat loop ──▶ provider router ──▶ Ollama | cloud
```

`backend/app/api/` holds the routers, mounted in `app.main`. The chat WebSocket
multiplexes modes on one socket: `chat` (streaming answer with model-driven
tool use), `task` (slash commands), `status` (project scan), `goal` (durable
multi-step work), and `stop` as a control frame. Deep research appears as a
resolved mode within `chat`.

Retrieval, tool results and web evidence converge on one prompt-assembly step
in `api/chat.py`, which is also where untrusted content is fenced — see
`docs/SECURITY.md`.

## The autonomous runtime

`orchestration/task_queue.py` starts at boot and runs three kinds of work:

| Mode | Used by | Cadence |
|---|---|---|
| `CONTINUOUS` | reality scan (U3) | every `REALITY_SCAN_INTERVAL_SECONDS` |
| `SCHEDULED` | nightly self-check (U8), nightly backup (U9) | re-armed after each run |
| `ON_DEMAND` | parallel goal steps (U2) | submitted by the goal engine |

The queue sat in the repo without a producer until U3 gave it its first.

Everything unprompted flows one way and ends at a person:

```
reality scan ──┐
               ├──▶ reality_events ──▶ notifications ──▶ badge in the UI
GitHub webhook ┘                  └──▶ diagnosis goal (U5)

nightly self-check ──▶ findings ──▶ GitHub issue (propose-only) + notification
nightly backup ──────▶ dump + manifest ──▶ notification only on failure
```

No autonomous path writes code, merges anything, or calls a write-capable
tool. The one action that touches infrastructure — restarting an allowlisted
compose service — is off in code, on in the shipped template, and inert without
a docker socket the stock stack does not mount.

### Durable goals

`agents/goal_planner.py` decomposes an objective into `goals` → `tasks` →
`task_steps` rows; `agents/goal_engine.py` executes each step through the same
`run_chat_tool_loop` that normal chat uses. State lives in Postgres rather than
in memory, which is what lets a killed backend resume from the next incomplete
step on boot (`main.lifespan` → `resume_unfinished_goals`).

Two concerns ride along with every step. `inference/cost_meter.py` attributes
each provider call's cost to the step that made it, through a `contextvars`
meter stack that nests correctly when a step spawns sub-work. `agents/model_policy.py`
picks the model from the step's declared kind. A goal that reaches
`GOAL_BUDGET_WARN_RATIO` of its cap pauses itself and waits for a human; it is
never auto-resumed.

## Data layer

Async SQLAlchemy 2.0 over asyncpg, schema managed by Alembic. Every read and
write goes through `db/repositories.py`, which requires an explicit caller: a
user id, or the `SYSTEM` marker for background work (`core/caller.py`).
`resolve_owner_filter` raises `TypeError` on anything else — most importantly
on `None` from a missing JWT `sub` — so an unscoped query cannot happen by
omission. That matters more once background tasks write rows no user asked for.

## Inference

`providers/` routes to Ollama first and falls back to an OpenAI-compatible
endpoint when one is configured. `inference/memory_pool.py` and
`batch_processor.py` are *inspired by* vLLM's PagedAttention and fan-out
patterns — vLLM itself is not a dependency and is not an inference backend
here.

## Frontend

React + Vite, with `frontend/src/components/` split by surface. The notification
bell and panel, goal checklist, budget controls and import panel are separate
component files rather than additions to one screen — a deliberate reversal of
the 1,292-line `Zorali.jsx` the capability map called out.

## Boundaries worth knowing

- The code sandbox is `python -I` in a subprocess. Not a container, not an
  isolation boundary. Off in code and in the shipped template.
- Self-improvement is propose-only by construction: no code exists to create a
  branch, push a commit or open a pull request.
- The GitHub webhook can produce event rows, a goal and a notification. Nothing
  on that path can write to a repository.
