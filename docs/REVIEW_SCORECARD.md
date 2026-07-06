# Modern-AI requirements scorecard

Two independent reviews rated Zorali ~8/10 against modern AI applications and
listed the gaps holding it back. This document maps every gap they named to
its current status in the codebase, so the claims stay verifiable.

Legend: ✅ shipped · 🟡 partial · 🗺 roadmap

## Gaps named by the reviews

| # | Review claim | Status | Where / evidence |
|---|---|---|---|
| 1 | "Synchronous RAG ingestion — a 500-page manual will block the API" | ✅ fixed | Upload returns `202` immediately; extraction (pypdf on a worker thread), chunking and embeddings run in a background task with pollable `indexing_status` (`backend/app/api/files.py`, `tests/backend/test_async_ingestion.py`) |
| 2 | "Deep Research is just a placeholder" | ✅ fixed | Multi-pass pipeline: search (Tavily via `TAVILY_API_KEY`, DuckDuckGo fallback) → concurrent page fetch with size caps → evidence injected as UNTRUSTED context with `[W#]` markers → cited answer + clickable web citations in the UI (`backend/app/agents/deep_research.py`, `backend/app/providers/web_fetcher.py`, `tests/backend/test_deep_research.py`) |
| 3 | "No sandboxed code execution — more a responder than an agent" | ✅ shipped (opt-in) | Artifact ▶ Run button, `/run` task command, `code_execution` agent tool; `python -I` subprocess with clean env, temp cwd, timeout and output caps; double-gated behind `CODE_EXECUTION_ENABLED=false` default + admin role (`backend/app/tools/code_sandbox.py`, `tests/backend/test_code_execution.py`) |
| 4 | "Basic memory vs graph memory (GraphRAG / Mem0)" | ✅ shipped | (subject —relation→ object) triples extracted at memory-save time, stored in Postgres, retrieved by entity match + one-hop expansion, injected into the chat prompt; `GET /api/memory/graph` (`backend/app/memory/knowledge_graph.py`, `tests/backend/test_knowledge_graph.py`) |
| 5 | "Memory lacks semantic recall" | ✅ shipped | Optional dense memory embeddings (`RAG_EMBEDDINGS_ENABLED`), cosine-ranked semantic search with lexical hybrid fallback (`backend/app/memory/vector_store.py`) |
| 6 | "Voice and image inputs are placeholders" | ✅ voice / ✅ image input | Voice shipped earlier (Web Speech API STT + TTS). Image input now rides the WebSocket to vision models: Ollama `images` field locally, OpenAI content parts on the cloud fallback (`backend/app/multimodal/vision.py`, `tests/backend/test_vision.py`) |
| 7 | "Wire in an active web-search API (like Tavily)" | ✅ shipped | `TavilySearchProvider` selected automatically when `TAVILY_API_KEY` is set; the `web_search` agent tool now calls the real provider (`backend/app/providers/search_provider.py`) |

## Claims that were already true (stale review data)

- **WebSocket streaming, stop-generation, regenerate** — shipped.
- **pgvector + Postgres data layer, Alembic migrations** — shipped.
- **JWT auth + RBAC + per-user isolation** — shipped.
- **Docker dev + production stacks (nginx, internal-only services)** — shipped.
- **Artifacts with version history** — shipped (live preview still roadmap).
- **Reranked multi-stage retrieval with citations** — shipped.

## Honest remaining deltas vs frontier products

- **Autonomous multi-step tool loops** — the graph agent executes single tool
  calls with retry; it does not yet plan chains of tool calls.
- **Automatic memory extraction from conversations** — memories are saved
  explicitly; the triple extractor exists but is not yet run on chat turns.
- **Iterative research refinement** — deep research does one search round
  (search → read → synthesize), not repeated query refinement.
- **Duplex voice** — browser Web Speech API today; local whisper.cpp + Piper
  stack planned.
- **Sandbox strength** — process isolation (`python -I`, clean env, timeout),
  not container/VM isolation; hence disabled by default.
- **Image generation / video** — out of scope for a local-first assistant until
  a production-grade local image model integration exists.
