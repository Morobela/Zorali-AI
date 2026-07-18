# Zorali — open work

Current state (2026-07): FastAPI backend with Postgres/pgvector storage
(Alembic-managed), JWT auth + RBAC + per-user isolation, WebSocket streaming
chat, two-stage hybrid RAG with optional dense embeddings, async file
ingestion, deep research, graph memory, vision input, opt-in `python -I` code
sandbox, React/Vite PWA frontend, dev and prod compose stacks. The
OpenJarvis-inspired upgrade plan that used to live in this file shipped in PRs
#8–#18; see `docs/audit/PHASE0_ROOT_AUDIT.md` for the latest full audit.

## Security hardening (audit Phase 2)
- [ ] Replace `?token=` WebSocket auth with single-use Redis-backed tickets
      (`POST /api/ws-ticket`, ~60s TTL, bound to user id) on **both** WS
      endpoints (`/ws/chat/{session_id}` and the MCP socket); stop nginx from
      logging query strings.
- [ ] Replace the `owner_id=None` trusted-caller convention with a required
      caller context (user id or explicit SYSTEM marker) across the repository
      layer; scope the `document_search` tool to the requesting user.

## Tests & CI (audit Phase 3)
- [ ] Token-expiry rejection test; RBAC matrix test per role (owner / admin /
      user / readonly); rate-limiter behavior tests (per-sub buckets, IP
      fallback); Alembic upgrade→downgrade round trip on a clean database.
- [ ] CI: linter (none configured yet), docker builds for both images,
      `pip-audit` + `npm audit --audit-level=high`, Redis service.
- [ ] Dockerfiles: non-root users, pinned base images.

## Product roadmap (from README)
- [ ] Artifact side-panel live preview/rendering.
- [ ] Local voice stack (whisper.cpp STT + Piper TTS) for duplex voice.
- [ ] Retrieval quality metrics in CI (Recall@5, MRR) on the RAG eval corpus.
