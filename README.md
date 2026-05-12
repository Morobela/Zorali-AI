# Charlie AI

Charlie AI is a local-first, J.A.R.V.I.S.-style AI assistant platform for chat, software development, research, project awareness, safe tool use, and long-term memory.

This repository is intentionally structured in **4 build phases**. Phase 1 is a working deployable app. Phases 2-4 are included as production-ready extension points and skeleton modules so the project can grow without changing the architecture.

## What Charlie AI Should Be

Charlie AI should feel like a mix of ChatGPT, Claude, and a local J.A.R.V.I.S. interface:

- **ChatGPT/Claude style UI**: clean sidebar, chats, projects, streaming messages, file controls, artifacts panel, and status area.
- **Claude-inspired project workspace**: project-aware memory, artifacts, GitHub/code context, and safe code review flows.
- **Emergent-style app builder direction**: prompt-to-project flow, app diagnostics, generated fixes, and deployable web/app output.
- **J.A.R.V.I.S. mode**: status scans, task execution, tool routing, safety gates, and situational awareness.
- **Local-first deployment**: runs with Ollama locally first; can later upgrade to vLLM.
- **Website + App**: deployable as a normal website and installable as a PWA app.

## Brand Identity

Use the provided Charlie AI logo:

```txt
frontend/src/assets/charlie-logo.png
```

Theme:

```css
:root {
  --charlie-white: #FFFFFF;
  --charlie-bg: #F8FFF4;
  --charlie-card: #FFFFFF;
  --charlie-green-dark: #006B2E;
  --charlie-green: #11A63A;
  --charlie-lime: #9DDB00;
  --charlie-yellow: #FFD400;
  --charlie-text: #102014;
  --charlie-muted: #667A6B;
}
```

White is a core theme color because the logo uses a clean white background.

---

## Phase Plan

### Phase 1 — Make Charlie Talk

Working app:

- FastAPI backend
- WebSocket chat streaming
- Ollama local model connection
- Basic health endpoints
- Short-term memory
- Project status scanner
- React + Vite frontend
- PWA manifest/service worker
- Docker Compose deployment

### Phase 2 — Safe Tools

Adds:

- File reader/writer tools
- Git tools
- Code sandbox
- Prompt integrity
- Action safety classification
- Domain isolation
- Tool registry

### Phase 3 — Smart Memory

Adds:

- Episodic memory
- Semantic memory
- Knowledge graph memory
- Causal memory
- Context pruning
- Memory compression
- Trust and calibration

### Phase 4 — J.A.R.V.I.S. Runtime

Adds:

- Unified `CharlieAI` runtime
- Agents
- Blackboard cognition
- Durable workflows
- MCP support
- A2A support
- OpenTelemetry GenAI spans
- Background scheduler

---

## Quick Start

### 1. Create `.env`

```bash
cp .env.example .env
```

### 2. Start everything

```bash
docker compose up --build
```

### 3. Pull a local model

```bash
docker compose exec ollama ollama pull llama3.1
```

### 4. Open the website

```txt
http://localhost:5173
```

The frontend is also installable as an app because it includes a PWA manifest and service worker.

---

## Local Development

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

---

## Main API

### Health

```txt
GET /api/health
```

### Project status

```txt
GET /api/project/status?path=/app
```

### WebSocket chat

```txt
WS /ws/chat/{session_id}
```

Payloads:

```json
{"mode":"chat","message":"Hello Charlie"}
```

```json
{"mode":"status","project_path":"/app"}
```

```json
{"mode":"task","message":"Scan this project and suggest fixes"}
```

---

## Repository Structure

```txt
charlie-ai/
├── backend/                  # FastAPI backend
├── frontend/                 # React + Vite PWA frontend
├── docs/                     # Architecture, API, deployment, security
├── infra/                    # Prometheus, nginx, scripts
├── tests/                    # Backend/frontend tests
├── docker-compose.yml        # Phase 1 local deployment
├── docker-compose.gpu.yml    # Optional GPU override
├── Makefile
└── README.md
```

---

## Build Rules

1. Build Phase 1 first.
2. Do not add autonomous agents until chat works.
3. Do not add smart memory until tools work.
4. Do not allow file writes/deletes without safety gating.
5. Every tool call must be logged.
6. Every dangerous action must require approval.
7. Every long workflow must checkpoint state.
8. Every response should expose trust score metadata.
9. Keep the green/yellow/white brand consistent.
10. The UI should stay clean like ChatGPT/Claude: sidebar, main chat, composer, artifacts/status panel.

---

## Current Honest Status

```txt
Architecture: complete
Phase 1 app: included and runnable
Advanced phases: included as extension modules
Battle testing: still required with real workloads
```

Charlie AI is ready to build, deploy locally, and improve phase by phase.
