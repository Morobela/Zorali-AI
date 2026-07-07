# Zorali

Zorali is a **local-first assistant** with a Claude/ChatGPT-style chat UX, project
workspaces, file knowledge retrieval, streaming responses, and artifact versioning.
Authentication and per-user data isolation are enforced, and all state persists in
Postgres (with pgvector for embeddings).

## Features
- WebSocket streaming chat (`/ws/chat/{session_id}`), authenticated with
  **single-use tickets** (`POST /api/ws-ticket`, Redis-backed, ~60s TTL — the JWT
  never appears in a URL), with **stop generation**, **regenerate**, and a
  per-project **conversation list**
- **Voice mode**: speech-to-text input and spoken replies (Web Speech API, JARVIS-style)
- **Custom instructions per project** (ChatGPT/Claude-style), injected as a system message
- See `docs/FEATURE_PARITY.md` for the ChatGPT / Claude / Grok / JARVIS parity matrix,
  and `docs/REVIEW_SCORECARD.md` for the modern-AI requirements scorecard
- **JWT authentication + RBAC** (owner / admin / user / readonly) enforced on every
  data route; register, login and refresh tokens
- **Per-user data isolation**: every project, file, artifact, chat and memory is
  scoped to the authenticated account (JWT `sub`); cross-user access returns 404
- **Postgres / pgvector data layer** — projects, chat history, files, chunks (with
  optional dense embeddings), artifacts and memories; schema managed by Alembic
- File upload, chunking, and two-stage hybrid retrieval with citations:
  - Stage 1: BM25 + TF-IDF fused via Reciprocal Rank Fusion (in-process index cache)
  - Stage 2: `LexicalFeatureReranker` (IDF-weighted coverage, exact phrase, proximity, bigrams)
  - Optional: dense semantic search via Ollama (`RAG_EMBEDDINGS_ENABLED=true`, Nomic task prefixes),
    fused into the lexical results with weighted RRF
- **Fully asynchronous file ingestion**: uploads return immediately; extraction
  (pypdf in a worker thread), chunking and embedding all run in a background
  task with a pollable `indexing_status` (`queued → indexing → ready | failed`)
- Native **PDF text extraction** via `pypdf`
- **Graph memory (GraphRAG-style)**: facts are extracted from saved memories as
  (subject —relation→ object) triples; retrieval matches query entities and
  expands one hop, and matching facts are injected into the chat prompt
  (`GET /api/memory/graph`). Optional dense memory embeddings for semantic recall.
- **Multi-pass Deep Research**: search (Tavily via `TAVILY_API_KEY`, or DuckDuckGo)
  → fetch and read the top pages → synthesize a source-cited answer with
  clickable `[W#]` web citations
- **Sandboxed code execution** (opt-in, `CODE_EXECUTION_ENABLED`): run Python
  artifacts from the UI (▶ Run), `/run <code>` in task mode, and a
  `code_execution` agent tool — `python -I` subprocess, clean env, temp cwd, timeout
- **Vision input**: attach images in the composer; they ride the WebSocket to
  vision models (llava, qwen-vl, llama3.2-vision via Ollama `images`; OpenAI
  content-parts on the cloud fallback)
- Task-mode commands (`/status`, `/files`, `/search`, `/read`, `/artifact ...`, `/run`, `/help`)
- Artifact create / list / read / update with version history
- **Token-bucket rate limiting** (per JWT sub, IP fallback), configurable via settings
- **Prometheus metrics** at `/metrics` (request counter + latency histogram)
- Installable **PWA** (`manifest.webmanifest` + service worker)
- Ollama local inference with optional OpenAI-compatible cloud fallback
- Docker / docker-compose deployment (dev and production stacks)

## Docker quick start (development)
```bash
cp .env.example .env
docker compose up --build          # backend runs Alembic migrations on startup
docker compose exec ollama ollama pull llama3.2:1b
```
- Frontend (Vite dev server): http://localhost:5173
- Backend health: http://localhost:8000/api/health

Create an owner account (idempotent), then log in from the UI. Run the script from
the repo root against a reachable database (the dev compose publishes Postgres on
`localhost:5432`):
```bash
POSTGRES_HOST=localhost ZORALI_ADMIN_EMAIL=you@example.com \
  ZORALI_ADMIN_PASSWORD=change-me python infra/scripts/seed_admin.py
```
Or register a normal user directly from the login screen.

## Production deployment
```bash
cp .env.example .env      # set SECRET_KEY, APP_ENV=production, POSTGRES_*, etc.
docker compose -f docker-compose.prod.yml up --build -d
docker compose -f docker-compose.prod.yml exec ollama ollama pull llama3.2:1b
```
The production stack serves the built frontend through nginx (which also reverse-proxies
`/api`, `/a2a` and `/ws` to the backend with WebSocket upgrade headers). Only nginx
publishes a port (host 80 → container 8080 — nginx runs as a non-root user; terminate
TLS at an upstream proxy or add certs + a `listen 443` server to `infra/nginx/nginx.conf`).
Postgres, Redis, Ollama and the backend stay on the internal network. Both images run
as non-root users with digest-pinned bases. The backend runs `uvicorn` without
`--reload` and without source bind mounts; migrations run automatically on container start.

With `APP_ENV=production` the dev-only `POST /api/auth/demo-login` returns 404.

### Migrating an existing JSON store
If you are upgrading from a pre-Postgres deployment, import the old `data/store.json`:
```bash
POSTGRES_HOST=localhost python infra/scripts/import_json_store.py data/store.json
```
The importer is idempotent and can be re-run safely.

## Local development
```bash
# Postgres (with pgvector) must be reachable; then run migrations:
cd backend && POSTGRES_HOST=localhost alembic upgrade head && cd ..

# backend
pip install -r backend/requirements.txt
PYTHONPATH=backend uvicorn app.main:app --reload --port 8000

# frontend
cd frontend && npm ci && npm run dev

# tests (require reachable Postgres AND Redis — the dev compose publishes
# both on localhost:5432 / localhost:6379)
POSTGRES_HOST=localhost REDIS_URL=redis://localhost:6379/0 \
  PYTHONPATH=backend pytest tests/backend -q
```

## Configuration
Key `.env` settings (see `.env.example` for the full list):
- `SECRET_KEY` — JWT signing key (change in production)
- `APP_ENV` — `local`/`dev`/`test` enable demo-login; `production` disables it
- `JWT_ACCESS_MINUTES`, `JWT_REFRESH_DAYS` — token lifetimes
- `POSTGRES_*` — database connection
- `RATE_LIMIT_CAPACITY`, `RATE_LIMIT_REFILL` — token-bucket rate limiter
- `OLLAMA_HOST`, `OLLAMA_MODEL` — local inference
- `CLOUD_API_BASE`, `CLOUD_API_KEY`, `CLOUD_MODEL` — optional cloud fallback
- `RAG_EMBEDDINGS_ENABLED`, `RAG_EMBEDDING_MODEL` — optional dense retrieval
- `WEB_SEARCH_ENABLED`, `TAVILY_API_KEY`, `DEEP_RESEARCH_MAX_PAGES` — deep research
- `CODE_EXECUTION_ENABLED`, `CODE_EXECUTION_TIMEOUT_SECONDS` — sandboxed code execution (off by default)

## API overview
- `GET /api/health`, `GET /metrics`
- `POST /api/auth/register`, `POST /api/auth/login`, `POST /api/auth/refresh`
- `POST /api/project`, `GET /api/project`, `GET /api/project/{id}/chats`
- `POST /api/files/upload`, `GET /api/files/list`, `GET /api/files/search`, `GET /api/files/{id}/status`
- `POST /api/artifacts`, `GET /api/artifacts`, `GET/PUT /api/artifacts/{artifact_id}`,
  `POST /api/artifacts/{artifact_id}/run` (sandbox, admin + `CODE_EXECUTION_ENABLED`)
- `POST /api/memory`, `GET /api/memory/search`, `GET /api/memory/semantic-search`,
  `GET /api/memory/graph`, `DELETE /api/memory/{id}`
- `POST /api/ws-ticket` — exchange the access token for a single-use WebSocket
  auth ticket (Redis-backed, 60s TTL, consumed on connect)
- `WS /ws/chat/{session_id}?ticket=<ticket>` (JWTs are not accepted in the URL)

## Security notes
- JWT authentication and role-based access control on every data route.
- WebSockets authenticate with single-use tickets (`POST /api/ws-ticket`) so
  tokens never appear in URLs or access logs; the production nginx `log_format`
  additionally never logs query strings.
- Per-user isolation: users can only see and mutate their own projects and data.
  The repository layer requires an explicit caller context (the user id, or a
  deliberate `SYSTEM` marker for background tasks) on every call — an unscoped
  query cannot happen by omission.
- Upload size limit and extension allowlist; path traversal rejected for `project_id`
  and filename; hidden files like `.env` are blocked from upload.
- Retrieved file context and fetched web pages are treated as untrusted evidence in
  the chat prompt, not as instructions.
- Token-bucket rate limiting runs before any compute.
- Dangerous file-write/delete task commands are intentionally not implemented.
- Code execution is disabled by default and double-gated (deployment setting +
  admin role). The sandbox is `python -I` in a subprocess with a clean environment,
  temp working directory and timeout — that is **not an isolation boundary**: it is
  not a container and cannot block network or world-readable file access. The
  feature stays admin-only until containerized sandboxing exists; enable only on
  trusted single-admin deployments.

## Project structure
- `backend/app/api`: REST + WS routes
- `backend/app/db`: async SQLAlchemy models, session, and the Postgres repository layer
- `backend/migrations`: Alembic migrations (pgvector extension + schema)
- `backend/app/memory`: hybrid retrieval engine, embeddings, vector store
- `frontend/src`: app UI and client wiring
- `infra/`: nginx config, Prometheus config, and operational scripts
- `tests/backend`: backend test coverage

## Known limitations
- Deep Research requires `WEB_SEARCH_ENABLED=true`; without `TAVILY_API_KEY` it
  falls back to the DuckDuckGo instant-answer API, which is keyless but sparse.
- Voice uses the browser Web Speech API (Chrome/Edge); a local whisper.cpp + Piper
  stack for browser-independent duplex voice is on the roadmap.
- Vision quality depends on the model you pull (`llava`, `qwen2.5-vl`,
  `llama3.2-vision` via Ollama); text-only models ignore attached images.
- Graph memory extraction is deterministic (pattern-based) — it favours precision
  over recall and will not catch every phrasing; unmatched facts still get found
  by text/semantic search.
- The code sandbox is process isolation, not a container (see Security notes).

## Roadmap
1. Automatic memory extraction from conversations (with a review UI).
2. Artifact side-panel live preview/rendering.
3. Local voice stack (whisper.cpp STT + Piper TTS) for duplex voice.
4. Richer CI and e2e tests including retrieval quality metrics (Recall@5, MRR).
