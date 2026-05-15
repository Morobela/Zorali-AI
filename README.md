# Zorali AI

Zorali AI is a **local-first assistant MVP** with Claude/ChatGPT-style chat UX, project workspaces, file knowledge retrieval, streaming responses, and artifact versioning.

## Working now
- Zorali branding and UI shell (sidebar/chat/panel composer)
- WebSocket streaming chat (`/ws/chat/{session_id}`)
- Project create/list + chat history
- File upload, chunking, and lightweight token-overlap retrieval with citations
- Task mode commands (`/status`, `/files`, `/search`, `/read`, `/artifact ...`, `/help`)
- Artifact create/list/read/update with versions
- JSON persistence via `ZORALI_DATA_DIR` (defaults to `/data`)
- Docker and docker-compose deployment

## Not yet built
- Full autonomous tool execution
- Advanced embeddings/vector DB
- Multi-user RBAC hardening
- Native PDF parsing

## Docker quick start
```bash
cp .env.example .env
docker compose up --build
docker compose exec ollama ollama pull llama3.2:1b
docker compose restart backend
```
- Frontend: http://localhost:5173
- Backend health: http://localhost:8000/api/health

## Local development
```bash
# backend
pip install -r backend/requirements.txt
PYTHONPATH=backend uvicorn app.main:app --reload --port 8000

# frontend
cd frontend
npm ci
npm run dev
```

## API overview
- `GET /api/health`
- `POST /api/project`, `GET /api/project`
- `POST /api/files/upload`, `GET /api/files/list`, `GET /api/files/search`
- `POST /api/artifacts`, `GET /api/artifacts`, `GET/PUT /api/artifacts/{artifact_id}`
- `WS /ws/chat/{session_id}`

## Security notes
- Upload size limit and extension allowlist enabled.
- Path traversal rejected for `project_id` and filename.
- Hidden files like `.env` are blocked from upload.
- Dangerous file-write/delete task commands are intentionally not implemented.
- Advanced tool execution should use explicit approval gates.

## Project structure
- `backend/app/api`: REST + WS routes
- `backend/app/db/repositories.py`: JSON persistence and retrieval
- `frontend/src`: app UI and client wiring
- `tests/backend`: backend test coverage

## Current limitations
- Deep Search is UI-only for now
- Voice and Image are placeholders
- PDF extraction is basic and should be upgraded with pypdf
- Persistence is JSON-based, not Postgres-backed yet

## Roadmap
1. Add optional embedding retrieval mode.
2. Add artifact side-panel editing UX.
3. Add auth/RBAC hardening and audit logging.
4. Add richer CI and e2e tests.
