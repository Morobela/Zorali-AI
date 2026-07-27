# Code Analysis Report

## Scope

This review covers the backend and frontend structure, with focus on runtime
flow, maintainability, security posture, and engineering readiness. It was
first written against the pre-capability-map codebase and re-checked against
the code after U1–U9 shipped; findings that have since been addressed are
marked, and the ones still open are stated as they now stand.

## High-level Architecture

- Backend is a FastAPI service with modular routers mounted in `app.main`:
  `health`, `auth`, `chat`, `memory`, `ollama`, `providers`, `project`,
  `tools`, `files`, `mcp`, `ws_ticket`, `artifacts`, `a2a`, `notifications`,
  `goals`, `imports`, `webhooks`, `selfcheck`, `resilience`, `skills`,
  `inference`.
- Realtime chat flows through `/ws/chat/{session_id}`, multiplexing `chat`,
  `status`, `task` and `goal` modes, with `stop` as a control frame.
- A second execution path now exists alongside the request path: the
  orchestration task queue running continuous, scheduled and on-demand work.
  See `docs/ARCHITECTURE.md`.
- Frontend uses React + Vite with page/component/store separation and a socket
  client for chat streaming.
- The repository includes phase-oriented extension points (agents, memory
  types, workflows), allowing growth without major tree refactors. (Unwired
  safety- and memory-stub modules that once padded this list were deleted in
  the truth pass; see `TODO.md`.)

## Strengths

1. **Clear separation of concerns**
   - API routers, cognition/memory/tooling modules are split cleanly and are
     easy to evolve independently.
2. **Practical local-first stack**
   - FastAPI + WebSocket + Ollama is lightweight for local deployment.
3. **Enforced caller scoping**
   - `db/repositories.py` requires an explicit caller on every call — a user id
     or a deliberate `SYSTEM` marker. This became load-bearing once background
     tasks started writing rows no user asked for.
4. **Good operational baseline**
   - Docker, nginx, Prometheus config, Alembic migrations, and CI that runs the
     suite against real Postgres and Redis.

## Risks and Gaps

1. **WebSocket protocol contract is implicit** — *still open*
   - `chat.py` dispatches on `mode` without a typed schema or version marker,
     and `goal` mode added `goal_update` frames to the same untyped surface.
   - Risk: frontend/backend drift as modes evolve.

2. **Error handling in the chat loop** — *partly addressed*
   - Explicit `{"type": "error", "content": ...}` frames now cover empty
     messages, disabled goal mode and goal failure.
   - Still missing: a machine-readable `code`, and a single wrapper mapping
     unexpected exceptions rather than per-site handling.

3. **Safety gating is registry-only** — *unchanged by design, tracked*
   - Enforcement lives in the tool registry (role gates, `approval_required`,
     audit log). The standalone safety stubs were unwired and deleted rather
     than left to imply coverage they never had. Reintroducing them properly,
     inside the registry's execution path, is in `TODO.md`.

4. **`backend/app/zorali.py` is dead code** — *corrected finding*
   - An earlier version of this report described a hardcoded `trust_score` as
     if it were in the live chat path. It is not: `zorali.py` defines a
     `ZoraliResponse` dataclass with `trust_score=0.8` and a `respond()` that
     echoes its input, and nothing in `backend/app` or `tests` imports it.
   - The real issue is the module's existence, not its scoring. It is the same
     category the truth pass deleted; it should follow.

5. **Potential CORS/environment drift** — *still open*
   - `allow_origins` is `[frontend_url, localhost:5173, 127.0.0.1:5173]` — the
     localhost entries are unconditional, including in production.

## Recommended Next Steps (Priority Order)

1. **Define a versioned chat message schema** — *not started*
   - Pydantic models for inbound/outbound WS frames (`type`, `mode`,
     `request_id`, `schema_version`, payload), documented in `docs/API.md`.
   - More valuable now than when first written: `goal_update` frames added a
     second producer to the same untyped protocol.

2. **Finish the WS error envelope** — *partly done*
   - Add a `code` field and one exception-mapping wrapper around the loop.

3. **Delete `backend/app/zorali.py`** — *new*
   - Unreferenced echo stub. Removing it also removes finding 4.

4. **Make the localhost CORS origins conditional on `APP_ENV`** — *new*
   - They are development affordances that currently ship to production.

5. **Extend the parity checker beyond one document** — *new*
   - The nightly self-check audits `FEATURE_PARITY.md` only. Every stale claim
     found in the July 2026 docs sweep lived in a file the checker never reads
     (`ARCHITECTURE.md`, the governance docs). Pointing it at those would have
     caught them.

6. **Strengthen test coverage around WS behaviours** — *partly done*
   - Goal mode, resume-after-restart, budget pause and parallel steps are
     covered. Malformed-mode payloads and stream-completion semantics are not.

## Suggested Quality Metrics to Track

- WS request success/failure rate by mode
- P50/P95 end-to-end chat latency
- Token streaming start delay and throughput
- Tool-call approval deny/allow rates
- Goal completion rate, and spend per completed goal
- Notification volume per day (a proactive channel fails by being ignored)

## Summary

The structure held up through the capability-map work: goals, the reality
engine and the resilience routines slotted into existing extension points
without a tree refactor, and the repository layer's required caller context
turned out to be the right call once background tasks began writing rows.

The open items are now narrower than the original report's. The WebSocket
contract is the one piece of real debt — it has gained a second frame producer
while staying untyped. The rest are small: one dead module, one CORS default,
and a self-check that audits a single document when it could audit all of them.
