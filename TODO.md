# Zorali — open work

Current state (2026-07): FastAPI backend with Postgres/pgvector storage
(Alembic-managed), JWT auth + RBAC + per-user isolation, single-use-ticket
WebSocket auth, required caller context across the repository layer,
model-driven tool use in normal chat (with MCP tools/list + tools/call over
the same registry), two-stage hybrid RAG with optional dense embeddings,
context-window summarization, automatic memory extraction with review,
conversation titles/rename/delete/search, async ingestion of
text/PDF/docx/xlsx, deep research, graph memory, vision input, opt-in
`python -I` code sandbox, React/Vite PWA frontend (react-markdown + KaTeX +
highlight), dev and prod compose stacks, full CI (ruff, backend tests
against real Postgres+Redis, Vitest, docker builds, pip-audit/npm audit).

The security-hardening and tests/CI items that used to live here (WS
tickets, caller context, RBAC/rate-limiter/Alembic tests, CI gates,
non-root pinned Dockerfiles) shipped in PRs #21–#22 and were verified
against the code in the Phase-6 sweep.

## Product roadmap
- [ ] Artifact side-panel live preview/rendering.
- [ ] Local voice stack (whisper.cpp STT + Piper TTS) for duplex voice.
- [ ] Retrieval quality metrics in CI (Recall@5, MRR) on the RAG eval corpus.
- [ ] Iterative deep research (multi-round search → read → re-search).
- [ ] Proactive routines (scheduled project scans + notifications).
