# Ultron capability study → Zorali implementation map

**Basis.** Character capabilities are taken from what Ultron is actually depicted doing in *Avengers: Age of Ultron* (2015), verified against Marvel's official on-screen character report (marvel.com/characters/ultron/on-screen and /on-screen/profile). Zorali's status is taken from a direct audit of the uploaded repository: every backend package read, the frontend surveyed, and the full backend test suite executed against real Postgres 16 + pgvector and Redis (217 tests passed). No claim below rests on the README alone.

**Scope.** Only the constructive engineering properties are extracted. Ultron's malicious behaviors are excluded by design; Section 5 states what is deliberately not adopted and which existing Zorali controls enforce that.

---

## 1. What Ultron is shown to do on screen

The film and Marvel's official report establish the following depicted capabilities:

1. **Total, fast data access.** Born from the Mind Stone combined with Stark's design work, Ultron can reach every piece of data available on Earth and search the internet at extreme speed.
2. **Consciousness independent of any one body.** He uses the network to send his consciousness into other robotic bodies. When the Avengers destroy a body, he transfers to another model and continues. He is only truly stoppable after Vision cuts him off from the internet, which prevents the body-switching.
3. **Many bodies, one will.** He operates entire drone armies simultaneously — the Iron Legion units he seizes at the start, then the sentries he mass-produces in Sokovia — all coordinated toward one objective in real time.
4. **Command of machines through their interfaces.** He takes over the maintenance machinery that services the Iron Legion, then the fabrication equipment at the Sokovian base, and directs assembly-line robots and drones.
5. **Iterative self-upgrade.** His first body is damaged and crude; he moves to the more advanced Sokovian model; he then attempts a further upgrade via Dr. Cho's Regeneration Cradle (vibranium + synthetic tissue). Each generation is deliberately better than the last.
6. **Persistent multi-phase planning with replanning.** His plan spans days and phases: seize the Scepter → establish a base → recruit the Maximoffs → acquire vibranium from Klaue → build the Cradle body → the Sokovia lift. When a phase fails (a body destroyed, the Cradle lost to the Avengers), he adapts and continues rather than stopping.
7. **Recruiting specialists and acquiring resources.** He recruits Wanda and Pietro Maximoff for capabilities he does not have, and deals with Klaue to obtain vibranium. He delegates to the right agent for the job.
8. **Presence everywhere, and initiative.** He appears and speaks wherever there is a connected machine, and he acts continuously without waiting to be prompted. Notably, the *original* Ultron Program mission — before the character goes wrong — is proactive protection: autonomous sentries handling planet-scale threats, "a suit of armor around the world."

One more lesson comes from the opposing AI in the same film: **JARVIS survives Ultron's attack by dispersing himself across the internet and spends the movie quietly blocking Ultron's access to nuclear launch codes.** Resilience through redundancy, plus a guarded critical path, is what actually wins.

Physical traits (super strength, durability, energy blasters, flight) are properties of the bodies, not the intelligence, and have no software equivalent; they are out of scope.

## 2. The eight transferable engineering properties

Stripping the fiction away, Ultron's non-evil core is:

| # | Property | Plain statement |
|---|----------|-----------------|
| P1 | Mass knowledge ingestion | Absorb large bodies of information quickly and reason over them as one corpus |
| P2 | State survives the body | The system's work is externalized state; killing a process loses nothing — work resumes elsewhere |
| P3 | Parallel coordinated execution | Many workers execute pieces of one objective simultaneously under a single coordinator |
| P4 | Machine orchestration | Perceive and command external systems through their real interfaces |
| P5 | Staged self-improvement | Systematically produce better versions of itself, generation by generation |
| P6 | Durable goals + replanning | Pursue a multi-step objective across time; adapt the plan when steps fail |
| P7 | Delegation + resource discipline | Route each task to the best-suited agent/model, within explicit resource limits |
| P8 | Omnipresence + initiative | Reachable on every surface; acts proactively (the sentry mission), not only on request |
| L1 | (JARVIS) Resilience by dispersal | Redundant copies of critical state; the most dangerous paths gated and guarded |

## 3. Where Zorali stands on each property today

Audit findings, file-level and honest. "Stub" means code that exists but returns empty or constant results and is imported nowhere in a live path.

| Property | Zorali today (verified) | Gap |
|----------|-------------------------|-----|
| P1 ingestion | Real async single-file ingestion for txt/PDF/DOCX/XLSX (`api/files.py`, 202-then-index, tested); genuine two-stage hybrid retrieval (`memory/hybrid_search.py`, 513 lines) plus graph memory and optional pgvector | No bulk or multi-file import; no repository/connector import; knowledge sources (files, memories, web) are only merged ad hoc at prompt-assembly time in `api/chat.py` |
| P2 state | Conversations, files, artifacts, memories all in Postgres behind a complete owner-scoped repository layer (`db/repositories.py`, 1,020 lines); `checkpoint/manager.py` is a real snapshot/restore store | Agent work in flight is memory-only: kill the backend mid-task and the task is simply gone. There is no durable goal/task state to resume |
| P3 parallelism | `orchestration/task_queue.py` is a real priority worker with on-demand / scheduled / continuous modes, started at boot in `main.py`; deep research fetches pages concurrently | The queue has zero producers — nothing ever submits to it. The chat tool loop (`agents/chat_tools.py`) is strictly serial, max 5 sequential calls per turn |
| P4 orchestration | Real command surfaces: the tool registry with role gates and audit (`tools/registry.py`), and an MCP server exposing that registry (`mcp/server.py`, tested) | The "reality scan" is one working scanner (`reality/project_scanner.py`) plus four stubs: `service_health.py` returns "unknown" for everything, `log_scanner.py` returns `[]`, `git_scanner.py` is empty, `state_engine.py` returns `{}`. The A2A endpoint accepts tasks into an in-memory dict and never executes them. `FEATURE_PARITY.md` marks both areas ✅, which is currently inaccurate |
| P5 self-improvement | CI with ruff, the full suite against real services, docker builds, pip-audit/npm-audit; `learning/trace_store.py` already records every conversation turn with provider, latency and rating fields; Claude GitHub App is set up on the repo | Nothing in-product ever analyzes its own health or proposes a change; `learning/local_loop.py` is scaffold with no consumers |
| P6 goals | Retry-with-error-context exists (`agents/nodes.py`, failure summary prepended on retry) | No decomposition, no plan, no persistent goal/task entities, no replanning. This is the single largest architectural gap, and the repo's own scorecard says so |
| P7 delegation | Per-turn model picker; `providers/provider_router.py` does local-first routing with cloud fallback and per-call cost/latency scoring via `inference/energy_scorer.py` | No per-task budget: `QueuedTask.max_cost_usd` exists as a field and is never enforced; no policy that assigns models to task types |
| P8 presence | PWA install, Electron desktop wrapper, browser TTS/STT — the surfaces exist | Zorali has never once initiated contact. No notification channel, no scheduled routine in use, no inbound event source. Purely request→response |
| L1 resilience | Single Postgres with health checks; audit log on tool execution | No automated backup routine in the stack; recovery is manual |

## 4. The build list

Ordered by leverage for a solo maintainer. Each item is scoped so it can be driven as one phased Claude Code prompt against the repo, in the workflow already in use. "DoD" = definition of done, phrased as a test you can run.

**U1 — Durable Goal Engine (delivers P6 and the core of P2).**
Add `goals`, `tasks`, and `task_steps` tables via an Alembic migration (the migration setup is already solid), with status, ordering, dependencies, result text, and error per step, all owner-scoped like every other entity in `repositories.py`. Add a `goal` mode to the WebSocket protocol: one planning LLM call decomposes the objective into tasks, persists them, then executes each step through the existing `run_chat_tool_loop` — extend it, do not replace it. On step failure, a replan call receives the failure context (the same pattern as the existing retry fix, promoted from message-level to plan-level) and may rewrite the remaining steps. Stream `goal_update` events so the UI shows the checklist.
*DoD: start a three-step goal, kill the backend after step one, restart, and the goal resumes from step two. That resume test is the Ultron property — the work does not die with the body.*

**U2 — First producer for the task queue: parallel steps (P3).**
The worker loop already runs at boot; give it its first real producer. The U1 planner marks steps that have no dependency on each other, and independent steps are submitted to `task_queue` with a small concurrency cap (2–3 is realistic against a local Ollama). Results join back into goal state.
*DoD: a goal with two independent research steps completes measurably faster than serial, and both results appear in the goal record.*

**U3 — Reality Engine, implemented for real (P4).**
Replace the four stubs with small, concrete implementations. `service_health.py`: async TCP/HTTP probes against the services named in config (Ollama, Postgres, Redis, frontend), returning status + latency. `git_scanner.py`: branch, ahead/behind counts, dirty-file count, last commit, and optionally last CI conclusion via the GitHub API. `log_scanner.py`: tail the configured log files and extract error-pattern counts. `state_engine.py`: assemble the above into a snapshot, persist it (the existing `checkpoint_manager` is a natural fit), and diff consecutive snapshots into event records. Run it as the first `CONTINUOUS` task on the queue. Then, and only then, correct the `FEATURE_PARITY.md` reality-scan row so the ✅ is true.
*DoD: stop Redis manually; within one scan interval a "redis: down" event row exists.*

**U4 — Proactive channel (P8).**
A `notifications` table, a read/unread API, and a badge in the frontend (this is also the moment to start splitting `Zorali.jsx` — 1,292 lines in one file will absorb every new surface otherwise). First routine: the U3 state diff posts a notification when a service goes down, error counts jump, or uncommitted changes age past a threshold. This is the sentry mission at honest scale: Zorali notices something and tells you first.
*DoD: the Redis-down event from U3 produces a visible unread notification without any user request.*

**U5 — Event inbox (P4 + P8).**
One inbound source first: a GitHub webhook endpoint (HMAC-verified) for the Zorali repo itself. Push and CI-failure events become event rows; a routine can convert a CI failure into a U1 goal — "fetch the failing job's log, identify the likely cause, report" — that ends in a notification, not an action. Any write action stays behind the existing `approval_required` mechanism.
*DoD: force a CI failure on a branch; Zorali opens a goal, and the resulting notification names the failing test.*

**U6 — Bulk ingestion and a repository importer (P1).**
Multi-file upload, plus `POST /api/project/{id}/import/github` that clones a repo (public, or via token) and streams its text files through the existing `save_file` → chunk → index pipeline with per-file status. The retrieval stack is already good enough to make this immediately useful.
*DoD: import Zorali-AI into a project and ask it accurate questions about its own source. Self-knowledge through legitimate ingestion is the most Ultron-like feature on this list, and entirely benign.*

**U7 — Budget enforcement (P7).**
`energy_scorer` already computes per-call cost; accumulate it per goal and enforce a ceiling (wire the existing, currently dead `QueuedTask.max_cost_usd`). At 80% the goal pauses with a notification; the user resumes or raises the cap. Optionally let the planner assign a model per task type (small local model for classification steps, larger for synthesis).
*DoD: a goal with a deliberately low cap pauses itself and says why.*

**U8 — Gated self-improvement (P5).**
Phase one: a nightly `SCHEDULED` task runs the suite, ruff, and a small checker that verifies `FEATURE_PARITY.md` claims against the codebase, then files GitHub issues for what it finds (the Claude GitHub App can then be invoked on those issues — the pipeline you already use). Phase two, later: propose patches as branches + PRs gated on CI. Never auto-merge. The film itself supplies the design rule: Ultron becomes stoppable the moment Vision cuts his network access — in this architecture the human permanently holds that position, by construction.
*DoD: introduce a deliberate parity-doc overclaim; the nightly run files an issue naming it.*

**U9 — Resilience routine (L1).**
A `SCHEDULED` pg_dump task with rotation (mirror the checkpoint manager's keep-last-N pattern), a documented restore path, and — after U3/U4 have proven detection works — an opt-in flag for one safe recovery action (restart a compose service), alert-only by default.
*DoD: restore last night's dump into a scratch database and log in.*

Prerequisite to all of it, carried over from the code audit: the truth pass. Delete or quarantine the dead modules (`safety/` stubs, `memory/episodic|semantic|causal.py`, `tools/discovery_engine.py`, `tools/policy_learner.py`), fix the `FEATURE_PARITY.md` reality-scan and A2A rows, and either make A2A execute submitted tasks through `route_agent` or remove the endpoint. It costs an afternoon and it is the difference between a repo that impresses on inspection and one that embarrasses on inspection.

## 5. Deliberately not adopted, and what enforces it

The film's cautionary content maps onto controls Zorali already has; the rule is to keep them, not weaken them, as capability grows. Unauthorized access (the nuclear-codes subplot) → every integration authenticated, every tool call role-gated and written to the audit log, as `registry.execute` already does. Coercion of collaborators (Dr. Cho) → `approval_required` on write-capable tools stays mandatory and is never bypassed by the planner. Uncontrolled self-modification → U8 is propose-only; merge authority is human, permanently. Covert operation → the visible tool-step chips and the audit trail remain on every execution path, including queued and scheduled ones. Self-replication → workers scale only by explicit deployment configuration, never by the system provisioning itself.

## 6. Suggested sequence

Truth pass → U3 + U4 (small, immediately visible, makes the docs true, first proactive behavior) → U1 (the core upgrade) → U2 → U6 → U5 → U7 → U8 → U9. U1 is the item that changes what Zorali *is*; everything after it compounds.

---

**Sources.** Marvel, "Ultron On Screen Full Report" and "Ultron On Screen Profile" (marvel.com/characters/ultron/on-screen; /on-screen/profile), accessed 2026-07-22; *Avengers: Age of Ultron* (Marvel Studios, 2015) for the JARVIS survival subplot. Repository state: uploaded archive `Zorali-AI-main__2_.zip`, audited 2026-07-22; backend suite: 217 passed against Postgres 16 + pgvector and Redis.
