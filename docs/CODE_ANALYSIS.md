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

1. **WebSocket protocol contract** — *resolved*
   - `backend/app/api/ws_protocol.py` declares schema version 1: a validated
     inbound frame, a closed set of nine outbound types, and an emitter that
     stamps `schema_version` and the turn's `request_id` on everything —
     including frames built inside the goal engine and the tool loop, which
     receive it in place of a raw `send_json`.
   - Drift is now a test failure rather than a surprise: a frame type not in
     `OUTBOUND_TYPES`, or not documented in `docs/API.md`, fails CI.

2. **Error handling in the chat loop** — *resolved*
   - Error frames carry a machine-readable `code` (`invalid_frame`,
     `unknown_mode`, `empty_message`, `goal_disabled`, `goal_failed`,
     `internal_error`) alongside the human `content` the UI renders.
   - One wrapper around the loop body maps an unexpected exception to an
     `internal_error` frame and keeps the socket open. Previously it closed
     the connection and the user saw the answer stop with no explanation.

3. **Safety gating is registry-only** — *unchanged by design, tracked*
   - Enforcement lives in the tool registry (role gates, `approval_required`,
     audit log). The standalone safety stubs were unwired and deleted rather
     than left to imply coverage they never had. Reintroducing them properly,
     inside the registry's execution path, is in `TODO.md`.

4. **A dead echo-stub module** — *resolved*
   - An earlier version of this report described a hardcoded `trust_score` as
     if it were in the live chat path. It was not: the module defined a
     response dataclass and a `respond()` that echoed its input, and nothing
     imported it. The real issue was the module's existence, not its scoring.
   - Deleted, as the truth pass deleted its siblings.

5. **CORS/environment drift** — *resolved*
   - The Vite dev-server origins were unconditional, so a production
     deployment allowed `http://localhost:5173` to make credentialed requests.
     Both they and the demo-login route now gate on `core.config.is_dev_env`,
     one definition rather than two.

## Recommended Next Steps (Priority Order)

1. **Verify claims about behaviour, not just references** — *open, and hard*
   - The nightly self-check now audits twelve documents for broken
     file/route/setting references and for stale absence claims, with CI
     enforcing the same check. That covers reference rot and one narrow class
     of false claim.
   - It does not cover the rest. Of the three stale claims in the July 2026
     sweep, only `QueuedTask.max_cost_usd` named something resolvable; the
     other two were wrong about behaviour in sentences naming nothing. The
     practical mitigation is editorial rather than mechanical: write
     load-bearing claims so they cite a setting, route or module.

2. **Strengthen test coverage around WS behaviours** — *largely done*
   - Goal mode, resume-after-restart, budget pause and parallel steps were
     already covered; schema version 1 added malformed frames, unknown modes,
     and an unexpected server error, each asserted from a real client socket.
   - Stream-completion semantics under a mid-turn disconnect remain uncovered.

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

Every item the original report raised is now closed. The dead module is gone,
the CORS origins are gated, the self-check audits the documentation rather than
one document of it, and the WebSocket protocol — the last and largest piece of
debt — is declared, versioned and enforced by tests on both sides of the wire.

The harder residue is that a checker can verify references but not sentences.
Two of the three stale claims found in July 2026 named nothing resolvable, and
no amount of tooling reads prose. That is an editorial discipline — make
load-bearing claims cite something — rather than a backlog item.
