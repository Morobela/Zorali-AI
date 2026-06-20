# Zorali OpenJarvis-Inspired Upgrade Plan

## Current stack assessment
- Frontend: React + Vite (`frontend/src/Zorali.jsx`)
- Backend: FastAPI + WebSocket streaming (`backend/app/main.py`, `backend/app/api/chat.py`)
- Package managers: `pip` for backend, `npm` for frontend
- Storage: JSON repositories + local file storage (`backend/app/db/repositories.py`)
- Current AI integration: Ollama-only streaming client (`backend/app/models/ollama_client.py`)

## Implementation plan
1. Add provider abstraction and router with local-first fallback (Ollama first, cloud optional).
2. Add Ollama health endpoint and better setup error handling/messages.
3. Introduce modular agent orchestrator with chat/research/code/file agents.
4. Add typed tool registry with initial tools and safe file operations.
5. Add persistent memory API (save/search/delete) using existing JSON persistence layer.
6. Extend chat websocket payload support (model, mode/agent, local/cloud, deep_research, attachments).
7. Add command safety guard with denylist for code mode command execution.
8. Upgrade frontend controls (model selector, local/cloud indicator, deep research, code mode, voice/image placeholders).
9. Add/refresh docs and `.env.example` entries for provider routing.
10. Add tests for provider router, tool registry, memory search.
