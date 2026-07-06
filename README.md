# Zorali

Zorali is a **local-first assistant** with a Claude/ChatGPT-style chat UX, project
workspaces, file knowledge retrieval, streaming responses, and artifact versioning.
Authentication and per-user data isolation are enforced, and all state persists in
Postgres (with pgvector for embeddings).

## Features
- WebSocket streaming chat (`/ws/chat/{session_id}`), JWT-authenticated via `?token=`,
  with **stop generation**, **regenerate**, and a per-project **conversation list**
- **Voice mode**: speech-to-text input and spoken replies (Web Speech API, JARVIS-style)
- **Custom instructions per project** (ChatGPT/Claude-style), injected as a system message
- See `docs/FEATURE_PARITY.md` for the ChatGPT / Claude / Grok / JARVIS parity matrix
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
- Non-blocking file indexing: uploads return immediately with an `indexing_status`
  (`queued → indexing → ready | failed`) you can poll
- Native **PDF text extraction** via `pypdf`
- Task-mode commands (`/status`, `/files`, `/search`, `/read`, `/artifact ...`, `/help`)
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
publishes ports (80/443); Postgres, Redis, Ollama and the backend stay on the internal
network. The backend runs `uvicorn` without `--reload` and without source bind mounts;
migrations run automatically on container start.

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

# tests (requires a reachable Postgres)
POSTGRES_HOST=localhost PYTHONPATH=backend pytest tests/backend -q
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

## API overview
- `GET /api/health`, `GET /metrics`
- `POST /api/auth/register`, `POST /api/auth/login`, `POST /api/auth/refresh`
- `POST /api/project`, `GET /api/project`, `GET /api/project/{id}/chats`
- `POST /api/files/upload`, `GET /api/files/list`, `GET /api/files/search`, `GET /api/files/{id}/status`
- `POST /api/artifacts`, `GET /api/artifacts`, `GET/PUT /api/artifacts/{artifact_id}`
- `POST /api/memory`, `GET /api/memory/search`, `DELETE /api/memory/{id}`
- `WS /ws/chat/{session_id}?token=<jwt>`

## Security notes
- JWT authentication and role-based access control on every data route.
- Per-user isolation: users can only see and mutate their own projects and data.
- Upload size limit and extension allowlist; path traversal rejected for `project_id`
  and filename; hidden files like `.env` are blocked from upload.
- Retrieved file context is treated as untrusted evidence in the chat prompt, not as
  instructions.
- Token-bucket rate limiting runs before any compute.
- Dangerous file-write/delete task commands are intentionally not implemented.

## Project structure
- `backend/app/api`: REST + WS routes
- `backend/app/db`: async SQLAlchemy models, session, and the Postgres repository layer
- `backend/migrations`: Alembic migrations (pgvector extension + schema)
- `backend/app/memory`: hybrid retrieval engine, embeddings, vector store
- `frontend/src`: app UI and client wiring
- `infra/`: nginx config, Prometheus config, and operational scripts
- `tests/backend`: backend test coverage

## Known limitations
- Deep Research web search uses a provider interface placeholder unless a real search
  backend is wired in.
- Voice and Image inputs are placeholders.
- Memory search uses hybrid BM25/TF-IDF lexical retrieval with feature reranking;
  dense embeddings currently cover uploaded file chunks, not memories.

## Roadmap
1. Dense embeddings for memories (not just file chunks).
2. Artifact side-panel editing UX.
3. Richer CI and e2e tests including retrieval quality metrics (Recall@5, MRR).
