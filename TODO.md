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
`goal` mode), per-goal cost budgets that pause a goal at its ceiling,
model-per-kind step routing, reality engine + proactive notifications,
HMAC-verified GitHub event inbox with CI-failure diagnosis, a propose-only
nightly self-check, nightly verified backups with a tested restore path and one
opt-in recovery action, React/Vite PWA frontend (react-markdown + KaTeX +
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
- [ ] Self-improvement phase two (capability map U8): propose patches as
      branches + PRs gated on CI. Phase one (nightly checks → issues) shipped;
      merge authority stays human, permanently — auto-merge is never built.
- [x] ~~Safety gating (command_guard / prompt_integrity / action_classifier).~~
      Done, and only one of the three was a real gap. `command_guard` came back
      as `backend/app/safety/argument_guard.py`, wired into `registry.execute`:
      the registry judged the caller and the tool but never the arguments, so
      `file_read` — `requires_role="user"`, advertised to every account by
      `WS /mcp` — would read the deployment's `.env`. The other two described
      controls that already exist (UNTRUSTED framing in `api/chat.py`;
      `requires_role`/`approval_required` in the registry) and were left alone
      rather than duplicated into something that looks like more security than
      it is. See `docs/SECURITY.md`.
- [ ] Artifact side-panel live preview/rendering.
- [ ] Local voice stack (whisper.cpp STT + Piper TTS) for duplex voice.
- [ ] Retrieval quality metrics in CI (Recall@5, MRR) on the RAG eval corpus.
- [ ] Iterative deep research (multi-round search → read → re-search).
- [ ] User-configurable proactive routines (the built-in reality-scan routine
      with notifications shipped as U3/U4; custom scans/schedules are next).

## Engineering debt (from the 2026-07 docs sweep)
- [x] ~~Versioned WebSocket frame schema.~~ Done — schema version 1 lives in
      `backend/app/api/ws_protocol.py` and is documented in `docs/API.md`.
      Inbound frames are validated (an unknown mode is refused rather than
      silently run as chat), the nine outbound types are a closed set, and one
      emitter stamps `schema_version` + `request_id` on every frame, including
      those built by the goal engine and the tool loop. Error frames carry a
      machine-readable `code`, and an unexpected exception becomes an
      `internal_error` frame instead of a dropped socket. Version 1 is
      deliberately additive, so an older client keeps working.
- [x] ~~Delete the unreferenced echo stub in `backend/app`.~~ Done.
- [x] ~~Make the localhost CORS origins conditional on `APP_ENV`.~~ Done — both
      it and the demo-login route now gate on `core.config.is_dev_env`, so the
      two cannot drift.
- [x] ~~Point the parity checker at more than one document.~~ Done — the nightly
      self-check now audits twelve documents for broken file/route/setting
      references and for stale absence claims, and CI enforces the same check
      so a broken reference fails the PR rather than waiting for 03:00 UTC.

      **Correcting the note that used to be here:** it claimed extending the
      checker "would have caught all of" the stale claims in the sweep. It
      would have caught one. "Ollama/vLLM inference" and "the triple extractor
      is not yet run on chat turns" name nothing a machine can resolve — they
      are wrong about behaviour, not about a symbol. A checker cannot read a
      sentence, and saying otherwise was the same species of overclaim the
      checker exists to catch.
- [ ] **Claims about behaviour remain unverifiable.** The gap above is real and
      open. Narrowing it means writing docs so load-bearing claims name
      something checkable — a setting, a route, a module — rather than
      describing behaviour in prose alone.
