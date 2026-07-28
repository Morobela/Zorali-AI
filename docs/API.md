# API

Every route below is registered in the running app — this list was generated
from the OpenAPI schema, not written by hand.

Unless stated otherwise a route requires a JWT (`Authorization: Bearer …`) and
is **owner-scoped**: it only sees rows belonging to the authenticated account,
and cross-user access returns 404 rather than 403. Roles form a hierarchy
(`owner` > `admin` > `user` > `readonly`); "admin+" means admin or owner.

## Auth

| Method | Path | Notes |
|---|---|---|
| POST | `/api/auth/register` | public |
| POST | `/api/auth/login` | public |
| POST | `/api/auth/refresh` | public (refresh token) |
| POST | `/api/auth/demo-login` | public, **404 when `APP_ENV=production`** |
| POST | `/api/ws-ticket` | exchange the access token for a single-use WebSocket ticket (Redis-backed, ~60s TTL, consumed on connect) |

## Realtime

| Endpoint | Notes |
|---|---|
| `WS /ws/chat/{session_id}?ticket=` | The chat protocol, below. JWTs are **not** accepted in the URL |
| `WS /mcp?ticket=` | MCP server over the tool registry (`tools/list`, `tools/call`), same role gates and caller scoping as chat |

### The chat protocol — schema version 1

Declared in `backend/app/api/ws_protocol.py`, which is the authority; this
section describes it. `tests/backend/test_ws_protocol.py` fails if the two
disagree, so neither can drift alone.

**Client → server.** One JSON object per message. `mode` selects what happens;
an unrecognised mode is refused with an `unknown_mode` error rather than
treated as `chat`. Unknown *fields* are ignored, so a newer client degrades
instead of failing.

| Field | Default | Meaning |
|---|---|---|
| `mode` | `chat` | `chat` · `task` · `goal` · `status` · `stop` |
| `message` | `""` | The turn's text. Required by `chat`, `task` and `goal` |
| `request_id` | generated | Correlation id, echoed on every frame the turn produces |
| `schema_version` | — | The version the client was written against |
| `project_id` | `default` | Scopes retrieval and history |
| `model`, `local_first` | provider default, `true` | Model selection for this turn |
| `tools_enabled` | `true` | Let the model call tools mid-answer |
| `deep_research` | `false` | Route the turn through the research pipeline |
| `regenerate`, `edit_last` | `false` | Replace the previous answer / previous exchange |
| `attachments` | `[]` | Files and images for this turn |

`{"mode": "stop"}` interrupts a streaming answer; `{"type": "stop"}` is the
older spelling and is still accepted.

**Server → client.** Every frame carries `type`, `schema_version`, and the
`request_id` of the turn that caused it. These nine types are the whole set —
the emitter refuses to send anything else:

| `type` | Payload | Sent during |
|---|---|---|
| `token` | `content` | a streaming chat answer |
| `done` | `citations`, `web_citations`, `latency_ms`, `provider`, `fallback_used`, `stopped` | end of a chat turn |
| `tool_use` | the call the model decided to make | a tool-using turn |
| `tool_result` | what the tool returned | a tool-using turn |
| `goal_token` | `content` | a streaming goal step |
| `goal_update` | the goal checklist state | goal mode |
| `task_result` | `data.status`, `data.result`, `data.tools_used`, `data.citations` | task mode |
| `status` | `data` — the project scan | `mode: status` |
| `error` | `code`, `content` | any failure |

**Error codes** (`error.code`), so a client can branch without parsing prose:
`invalid_frame`, `unknown_mode`, `empty_message`, `goal_disabled`,
`goal_failed`, `internal_error`.

An unexpected server-side exception becomes an `internal_error` frame and the
socket stays open. Before version 1 it closed the connection, and the user saw
a silent disconnect mid-answer.

## Projects, chats and files

| Method | Path | Notes |
|---|---|---|
| GET, POST | `/api/project` | |
| PATCH | `/api/project/{project_id}` | rename, system prompt |
| GET | `/api/project/{project_id}/chats` | |
| GET | `/api/project/{project_id}/sessions` | |
| PATCH, DELETE | `/api/project/{project_id}/sessions/{session_id}` | rename / delete a conversation |
| GET | `/api/project/{project_id}/search?q=` | server-side chat search |
| GET | `/api/project/status?path=` | project scanner |
| POST | `/api/files/upload` | ceiling `MAX_UPLOAD_MB` |
| POST | `/api/files/upload-batch?project_id=` | multi-file, per-file accept/reject |
| GET | `/api/files/list`, `/api/files/search` | |
| GET | `/api/files/{file_id}/status` | `queued → indexing → ready \| failed` |
| DELETE | `/api/files/{file_id}` | |

## Repository import (U6)

| Method | Path | Notes |
|---|---|---|
| POST | `/api/project/{project_id}/import/github` | `{repo, ref?, token?}` → 202 + import id. github.com `owner/repo` only; the token is never logged or stored |
| GET | `/api/project/{project_id}/imports` | |
| GET | `/api/project/{project_id}/imports/{import_id}` | per-file status |

## Artifacts and memory

| Method | Path | Notes |
|---|---|---|
| GET, POST | `/api/artifacts` | |
| GET, PUT | `/api/artifacts/{artifact_id}` | version history |
| POST | `/api/artifacts/{artifact_id}/run` | **admin+** and `CODE_EXECUTION_ENABLED` |
| POST | `/api/memory` | |
| GET | `/api/memory/search`, `/api/memory/semantic-search`, `/api/memory/graph` | |
| GET | `/api/memory/pending` | auto-extracted candidates awaiting review |
| POST | `/api/memory/{memory_id}/accept`, `/api/memory/{memory_id}/reject` | |
| DELETE | `/api/memory/{memory_id}` | |

## Goals (U1, U2, U7)

| Method | Path | Notes |
|---|---|---|
| GET | `/api/goals?project_id=` | |
| GET | `/api/goals/{goal_id}` | steps, per-step model and spend |
| PATCH | `/api/goals/{goal_id}/budget` | `{max_cost_usd}`, 0 = uncapped |
| POST | `/api/goals/{goal_id}/resume` | optional `{max_cost_usd}` raises the cap in the same call. A paused goal never resumes itself |

## Notifications (U4)

| Method | Path | Notes |
|---|---|---|
| GET | `/api/notifications?unread_only=true` | |
| GET | `/api/notifications/unread-count` | |
| POST | `/api/notifications/{id}/read`, `/api/notifications/read-all` | |

## Inbound events (U5)

| Method | Path | Notes |
|---|---|---|
| POST | `/api/webhooks/github` | **no JWT** — HMAC-SHA256 `X-Hub-Signature-256` over the raw body *is* the authentication. 503 when `GITHUB_WEBHOOK_SECRET` is unset, 401 on a bad signature, deliveries deduped by `X-GitHub-Delivery` |
| GET | `/api/webhooks/github/events` | **admin+**; recent deliveries |

## Operations (U8, U9)

| Method | Path | Notes |
|---|---|---|
| GET | `/api/self-check` | **admin+**; nightly self-check history |
| POST | `/api/self-check/run` | **admin+**; run now, reports only — never changes code |
| GET | `/api/backups` | **admin+**; manifest only — dumps are never served over HTTP |
| POST | `/api/backups/run` | **admin+** |

## Introspection

| Method | Path | Notes |
|---|---|---|
| GET | `/api/health`, `/`, `/metrics` | public; `/` lists wired features, `/metrics` is Prometheus |
| GET | `/api/tools` | registry, with role and approval metadata |
| GET | `/api/ollama/health`, `/api/providers/status` | |
| GET | `/api/skills`, `/api/skills/capabilities` | |
| POST | `/api/skills/reload` | **owner** |
| POST | `/api/skills/{skill_name}/invoke` | |
| GET | `/api/inference/queue`, `/batch`, `/memory`, `/energy`, `/checkpoints`, `/learning` | runtime stats |
| POST | `/api/inference/learning/run` | **owner** |

## A2A

| Method | Path | Notes |
|---|---|---|
| GET | `/a2a/.well-known/agent.json` | public agent card |
| POST | `/a2a/tasks/send` | runs the task through the agent orchestrator in the background — poll for the result |
| GET | `/a2a/tasks/{task_id}` | `submitted → running → completed \| failed` |
| GET | `/a2a/tasks` | |

---

WebSockets authenticate with single-use tickets from `POST /api/ws-ticket`
(Redis-backed, ~60s TTL, consumed on first connect). JWTs are never accepted in
WebSocket URLs. See `docs/SECURITY.md`.
