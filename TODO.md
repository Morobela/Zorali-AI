# Zorali — open work

Current state (2026-07): FastAPI backend with Postgres/pgvector storage
(Alembic-managed), JWT auth + RBAC + per-user isolation, single-use-ticket
WebSocket auth, required caller context across the repository layer,
model-driven tool use in normal chat (with MCP tools/list + tools/call over
the same registry), two-stage hybrid RAG with optional dense embeddings,
context-window summarization, automatic memory extraction with review,
conversation titles/rename/delete/search, async ingestion of
text/PDF/docx/xlsx, deep research, graph memory, vision input, opt-in
`python -I` code sandbox, durable multi-step goals with planning, replanning,
parallel independent steps on the task queue and resume-after-restart (WS
`goal` mode), reality engine + proactive
notifications, React/Vite PWA frontend (react-markdown + KaTeX +
highlight), dev and prod compose stacks, full CI (ruff, backend tests
against real Postgres+Redis, Vitest, docker builds, pip-audit/npm audit).

The security-hardening and tests/CI items that used to live here (WS
tickets, caller context, RBAC/rate-limiter/Alembic tests, CI gates,
non-root pinned Dockerfiles) shipped in PRs #21–#22 and were verified
against the code in the Phase-6 sweep.

## Product roadmap
- [ ] Per-goal cost budgets (capability map U7): wire the still-unused
      `QueuedTask.max_cost_usd` against `inference/energy_scorer` so a goal
      pauses at its ceiling instead of running unbounded.
- [ ] Safety gating (command_guard / prompt_integrity / action_classifier): the unwired stubs were deleted in the truth pass; these remain good ideas to reintroduce properly, wired into the tool registry's execution path.
- [ ] Artifact side-panel live preview/rendering.
- [ ] Local voice stack (whisper.cpp STT + Piper TTS) for duplex voice.
- [ ] Retrieval quality metrics in CI (Recall@5, MRR) on the RAG eval corpus.
- [ ] Iterative deep research (multi-round search → read → re-search).
- [ ] User-configurable proactive routines (the built-in reality-scan routine
      with notifications shipped as U3/U4; custom scans/schedules are next).
