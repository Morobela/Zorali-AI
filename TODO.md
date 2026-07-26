# Zorali — open work

Current state (2026-07): FastAPI backend with Postgres/pgvector storage
(Alembic-managed), JWT auth + RBAC + per-user isolation, single-use-ticket
WebSocket auth, required caller context across the repository layer,
model-driven tool use in normal chat (with MCP tools/list + tools/call over
the same registry), two-stage hybrid RAG with optional dense embeddings,
context-window summarization, automatic memory extraction with review,
conversation titles/rename/delete/search, async ingestion of
text/PDF/docx/xlsx, multi-file upload and GitHub repository import,
deep research, graph memory, vision input, opt-in
`python -I` code sandbox, durable multi-step goals with planning, replanning,
parallel independent steps on the task queue and resume-after-restart (WS
`goal` mode), reality engine + proactive notifications, HMAC-verified GitHub
event inbox with CI-failure diagnosis, React/Vite PWA frontend (react-markdown + KaTeX +
highlight), dev and prod compose stacks, full CI (ruff, backend tests
against real Postgres+Redis, Vitest, docker builds, pip-audit/npm audit).

The security-hardening and tests/CI items that used to live here (WS
tickets, caller context, RBAC/rate-limiter/Alembic tests, CI gates,
non-root pinned Dockerfiles) shipped in PRs #21–#22 and were verified
against the code in the Phase-6 sweep.

## Product roadmap
- [ ] More inbound event sources (capability map U5 shipped one: HMAC-verified
      GitHub webhooks → CI-failure diagnosis goals + notifications). Issues,
      deploys and review requests are the obvious next ones.
- [ ] Backup/restore routine (capability map U9): scheduled `pg_dump` with
      keep-last-N rotation and a documented restore path.
- [ ] Self-improvement phase two (capability map U8): propose patches as
      branches + PRs gated on CI. Phase one (nightly checks → issues) shipped;
      merge authority stays human, permanently — auto-merge is never built.
- [ ] Model-per-task-type routing (the optional half of capability map U7):
      let the planner assign a small local model to mechanical steps and a
      stronger one to synthesis. Budgets and pausing shipped; this did not.
- [ ] Safety gating (command_guard / prompt_integrity / action_classifier): the unwired stubs were deleted in the truth pass; these remain good ideas to reintroduce properly, wired into the tool registry's execution path.
- [ ] Artifact side-panel live preview/rendering.
- [ ] Local voice stack (whisper.cpp STT + Piper TTS) for duplex voice.
- [ ] Retrieval quality metrics in CI (Recall@5, MRR) on the RAG eval corpus.
- [ ] Iterative deep research (multi-round search → read → re-search).
- [ ] User-configurable proactive routines (the built-in reality-scan routine
      with notifications shipped as U3/U4; custom scans/schedules are next).
