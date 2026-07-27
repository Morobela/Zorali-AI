# Feature parity study — ChatGPT · Claude · Grok · J.A.R.V.I.S. → Zorali

A study of the signature features of the leading assistants (and the fictional
benchmark Zorali is named after), mapped against what Zorali ships today.
Zorali's positioning is different from all four: **local-first and self-hosted**.
It cannot match frontier-scale model quality, but it can match the *product
experience* around the model — that is what this document tracks.

Legend: ✅ shipped · 🟡 partial · 🗺 roadmap · ✖ out of scope for a local-first app

## Feature matrix

| Feature | Reference assistant | Zorali status | Where |
|---|---|---|---|
| Streaming chat with markdown + code blocks + copy | All | ✅ | WS `/ws/chat/{session}`; react-markdown + GFM (tables, task lists) + syntax highlighting + KaTeX math, raw HTML never rendered, copy button on code blocks |
| Conversation history list: titles, rename, delete, search | ChatGPT/Claude/Grok | ✅ | `chat_sessions` table + one-shot LLM titles (`AUTO_TITLES_ENABLED`); PATCH/DELETE `/api/project/{id}/sessions/{sid}`; debounced server-side search (`GET /api/project/{id}/search?q=`) |
| Stop generation mid-answer | All | ✅ | WS `{"mode":"stop"}`, ⏹ Stop button |
| Regenerate last response | All | ✅ | WS `regenerate: true`, ↻ button |
| Edit & resend last message | ChatGPT/Claude | ✅ | ✎ on the last user message; replaces the last exchange (full branching out of scope) |
| Copy message | All | ✅ | message action row |
| Projects / workspaces | ChatGPT Projects, Claude Projects | ✅ | projects + files + artifacts + chats per project |
| Custom instructions / project instructions / personas | ChatGPT, Claude, Grok | ✅ | `projects.system_prompt`, ⚙ on project, threaded as system msg |
| File uploads + retrieval with citations (RAG) | ChatGPT, Claude | ✅ | hybrid BM25/TF-IDF/RRF + optional dense (pgvector) |
| Bulk ingestion + repository import | ChatGPT/Claude project knowledge, Grok code context | ✅ | multi-file upload in one request with per-file accept/reject (`POST /api/files/upload-batch`), plus `POST /api/project/{id}/import/github` (capability map U6): clones a public or token-authenticated GitHub repo, filters build output/dependencies/lockfiles/binaries, and streams source files through the normal extract → chunk → index pipeline with repo-relative paths as citations and a pollable per-file import record |
| PDF / Word / Excel understanding | ChatGPT, Claude | ✅ | pypdf, python-docx (paragraphs + tables), openpyxl (sheet headers + tab-separated rows); upload ceiling configurable via `MAX_UPLOAD_MB` (default 25) |
| Artifacts (versioned side documents) | Claude Artifacts, ChatGPT Canvas | 🟡 | create/edit/version/▶ Run panel; no live preview/rendering |
| Memory (user-curated + automatic, searchable) | ChatGPT Memory, Claude Memory | ✅ | save/search/delete + **graph memory** (triples, 1-hop retrieval, prompt injection) + optional dense embeddings + **automatic extraction from chat** (`AUTO_MEMORY_ENABLED`): pattern extractor + LLM fallback stores pending candidates for Accept/Reject review; pending rows never enter prompts |
| Voice input (speech-to-text) | ChatGPT Voice, Grok Voice, JARVIS | ✅ | Web Speech API mic (Chrome/Edge; browser-dependent) |
| Spoken replies (text-to-speech) | ChatGPT Voice, Grok companions, JARVIS | ✅ | speechSynthesis toggle + per-message 🔊 |
| Full-duplex conversational voice (interruptible, emotive) | ChatGPT Advanced Voice, Grok companions | 🗺 | needs local STT/TTS models (whisper.cpp + Piper) |
| Live web search | ChatGPT Search, Grok real-time | ✅ | Tavily (`TAVILY_API_KEY`) or DuckDuckGo behind `WEB_SEARCH_ENABLED`; real `web_search` tool |
| Deep research (multi-pass, source-cited reports) | Grok DeepSearch, ChatGPT/Claude deep research | ✅ | search → fetch top pages → synthesize with clickable `[W#]` citations; iterative query refinement on roadmap |
| Multi-user accounts, auth, private data | All (hosted) | ✅ | JWT + RBAC + per-user isolation, Postgres |
| Model picker | All | ✅ | picker lists models installed in Ollama |
| Reasoning display (thinking models) | Claude, Grok Think, ChatGPT o-series | ✅ for supported models | `<think>…</think>` output (deepseek-r1, qwen3 via Ollama) renders as a collapsible Thinking block, excluded from TTS and stored messages |
| Vision (image understanding in chat) | All | ✅ | 🖼 attach in composer → Ollama `images` field (llava/qwen-vl/llama3.2-vision) or OpenAI content parts on cloud fallback |
| Image generation | ChatGPT (DALL·E), Grok (Aurora) | ✖ for now | no production-grade local image model integration; would need SD/ComfyUI service |
| Video generation | Grok Imagine | ✖ | out of scope |
| Canvas-style collaborative editor | ChatGPT Canvas | 🗺 | artifact editor is the seed for this |
| Multi-step goals that survive a restart | ChatGPT Tasks, Claude/Grok agents | ✅ | WS `goal` mode (capability map U1): one planning call decomposes an objective into persisted `goals`/`tasks`/`task_steps`, each step executes through the same model-driven tool loop as chat, failures trigger a replan of the remaining steps, and `goal_update` frames stream the live checklist. State lives in Postgres, so a killed backend resumes from the next incomplete step on boot |
| Backup + restore | All (hosted, invisibly) | ✅ | nightly verified `pg_dump` with keep-last-N rotation and a manifest (capability map U9, `BACKUP_ENABLED`/`BACKUP_KEEP`), a restore path documented in `docs/DEPLOYMENT.md` and exercised by the suite (restore into a scratch database, then log in against it), and one opt-in recovery action — restarting an allowlisted compose service, alert-only by default, with a cooldown and audit trail |
| Self-monitoring codebase health | — (no assistant ships this) | 🟡 | nightly self-check (capability map U8, phase one, `SELF_IMPROVEMENT_ENABLED`, off by default): runs the backend suite and ruff, and verifies this document's own shipped rows against the codebase — cited files must exist, cited routes must be registered, cited settings must be defined — then opens one deduped GitHub issue per finding and notifies admins. Propose-only: it never changes code, and phase two (patches as PRs) is not implemented |
| Model routing by kind of work | — (assistants pick one model per chat) | ✅ | the planner labels every step `classification`/`extraction`/`research`/`synthesis`/`code`, and `STEP_MODEL_POLICY` (e.g. `classification=llama3.2:1b,synthesis=gpt-4o`) routes mechanical steps to a smaller model while synthesis gets the strong one; each step records what it actually ran on, so a goal's spend can be explained per step. A model chosen for the goal always outranks the policy |
| Spend limits on autonomous work | ChatGPT/Claude usage caps | ✅ | per-goal budgets (capability map U7): every provider call is priced by `inference/energy_scorer` and attributed to the step that made it via a context-scoped meter, so a goal accumulates real spend. At `GOAL_BUDGET_WARN_RATIO` (default 80%) of `GOAL_MAX_COST_USD` the goal pauses itself, explains the numbers and notifies its owner; it is never auto-resumed — a human resumes it or raises the cap (`POST /api/goals/{id}/resume`, `PATCH /api/goals/{id}/budget`) |
| Parallel execution within a plan | ChatGPT/Claude agent tool-calling | ✅ | independent steps of a task (`depends_on: []`) are submitted to the orchestration task queue and run concurrently under a configurable cap (`GOAL_MAX_PARALLEL_STEPS`, default 2 — realistic against a local Ollama), with results joined back into goal state (capability map U2); tasks remain sequential phases, and dependent steps still wait |
| Tool use / agents | All (function calling), JARVIS | ✅ | model-driven tool use in normal chat (default ON, `TOOL_CALL:` protocol, ≤5 calls/turn, tool-step chips in the UI): `web_search`, `document_search`, `calculator`, plus admin-gated `code_execution`; task mode (`/status`, `/files`, `/search`, `/read`, `/artifact`, `/run`), agent orchestrator, **MCP tool server** (tools/list + tools/call over the ticket-authenticated `/mcp` socket, same registry + role gates), A2A endpoint |
| System/project awareness ("reality scan") | JARVIS | ✅ | project scanner (`/status`), async service health probes (Ollama/Postgres/Redis/frontend, TCP+HTTP with latency), git scanner (branch, ahead/behind, dirty count, last commit), log tail scanner (error-pattern counts); the state engine snapshots all of it via the checkpoint store and diffs consecutive snapshots into `reality_events` rows, running as the first CONTINUOUS task on the queue (capability map U3) |
| Proactive routines (wake-ups, monitoring, alerts) | JARVIS | 🟡 | two routines shipped, both ending in a notification with no user request: the continuous reality scan (U4 — service down, log-error jumps, aging uncommitted changes) and the CI-failure routine (U5 — an HMAC-verified GitHub webhook turns a failed run into a diagnosis goal whose notification names the failing test). User-configurable routines still roadmap |
| Inbound event inbox | ChatGPT/Claude connectors, JARVIS | 🟡 | one source: HMAC-verified GitHub webhooks (`POST /api/webhooks/github`) recording push and CI events as deduped `inbound_events` rows (capability map U5). Read-only by construction — a delivery can open a goal and post a notification, never write to a repository; more sources (issues, deploys, calendars) are roadmap |
| Personality / persona | JARVIS wit, Grok companions | ✅ via custom instructions | set per-project (e.g. "address me as Commander, dry wit") |
| Mobile/PWA install | All apps | ✅ | manifest + service worker |
| 2M-token context (Grok 4) | Grok | ✖ | bounded by the local model's context window |
| Long-conversation memory (rolling summarization) | ChatGPT/Claude context management | ✅ | histories over `CONTEXT_MAX_TOKENS` (chars/4 estimate) fold older turns into one persisted per-session summary ("Conversation summary so far: …"), reused across turns; last `CONTEXT_KEEP_MESSAGES` stay verbatim |

## What was added in this batch (modern-AI requirements release)

1. **Multi-pass Deep Research** — search (Tavily or DuckDuckGo) → fetch and
   read the top pages → synthesize with clickable `[W#]` source citations.
   Fetched pages are injected as UNTRUSTED evidence (prompt-injection safe).
2. **Sandboxed code execution** — artifact ▶ Run button, `/run` task command
   and a `code_execution` agent tool; `python -I` subprocess with clean env +
   timeout, double-gated behind `CODE_EXECUTION_ENABLED` + admin role.
3. **Graph memory** — (subject —relation→ object) triples extracted from saved
   memories, 1-hop graph retrieval wired into the chat prompt and
   `GET /api/memory/graph`; optional dense memory embeddings for semantic recall.
4. **Vision input** — 🖼 attach images in the composer; delivered to vision
   models via Ollama's `images` field or OpenAI content parts on the cloud path.
5. **Fully asynchronous ingestion** — extraction (pypdf on a worker thread),
   chunking and embeddings all run after the upload response returns.

## Previous batch (assistant-parity release)

1. **Voice mode (JARVIS-style)** — mic button does real speech-to-text (Web
   Speech API); a "Speak replies" toggle reads answers aloud, and every
   assistant message has a 🔊 Speak action. Auto-sends when you finish talking.
2. **Stop generation** — the send button becomes ⏹ Stop while streaming; the
   backend cancels the model stream and keeps the partial answer.
3. **Regenerate** — ↻ on the last answer re-asks the same question; the backend
   replaces the previous assistant message instead of duplicating history.
4. **Real conversation list** — the sidebar "Recent" section now lists actual
   conversations (preview + recency) per project; click to resume, `+ New chat`
   starts a fresh session.
5. **Custom instructions per project** — ⚙ on the active project opens an
   instructions editor; instructions are injected as a trusted system message
   in every chat in that project.
6. **Dynamic model picker** — lists whatever models are installed in Ollama
   instead of a hardcoded pair.

## Honest positioning

- **Model quality**: ChatGPT/Claude/Grok run frontier models in datacenters.
  Zorali runs whatever fits your hardware via Ollama, with optional cloud
  fallback. The app layer is at parity for the features above; raw
  intelligence is a function of the model you pull.
- **Advanced voice**: browser speech APIs give JARVIS-style voice command today;
  human-grade duplex voice needs local whisper.cpp (STT) + Piper (TTS)
  services — planned, not shipped.
- **Where Zorali wins**: your data never leaves your machine — full-stack
  self-hosting, per-user isolation, auditable retrieval, no vendor lock-in.

## Recommended next steps (priority order)

1. **Iterative deep research** — refine queries across multiple search rounds
   (search → read → re-search) on top of the shipped single-round pipeline.
2. **Local voice stack** — whisper.cpp + Piper containers for duplex voice
   independent of browser support.
3. **User-configurable routines** — the built-in reality-scan routine and the
   notification surface shipped (U3/U4); letting users define their own
   scans/schedules is the next step.
