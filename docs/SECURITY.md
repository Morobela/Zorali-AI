# Security

Controls wired into real request paths today (each verifiable in code):

- **RBAC** — JWT auth with a role hierarchy; every protected route declares a minimum role (`backend/app/core/rbac.py`).
- **Rate limiting** — token-bucket middleware on every HTTP request (`backend/app/core/rate_limiter.py`).
- **Prompt-injection hardening** — retrieved file content and web evidence enter the prompt in explicitly UNTRUSTED blocks the model is told to treat as evidence, not instructions (`backend/app/api/chat.py`).
- **Tool gating and audit** — the tool registry enforces per-tool minimum roles and `approval_required`, and records an audit event for every execution (`backend/app/tools/registry.py`).
- **Argument gating** — role says who may call a tool; `backend/app/safety/argument_guard.py` says what they may call it with. Tools that take a path refuse credential files — `.env`, private keys, `.ssh`/`.aws`/`.kube` contents — checked both lexically and after resolving symlinks, so `ln -s .env innocent.txt` does not launder one. A path that cannot be resolved at all is refused rather than read. The rule is **not** role-exempt: an owner's session is the one a prompt injection would most like to borrow. Every refusal is audited with its reason.
- **Sandboxed code execution** — `python -I` subprocess with clean env, timeout and output caps, double-gated behind `CODE_EXECUTION_ENABLED` plus admin+ role (`backend/app/tools/code_sandbox.py`).
- **WebSocket auth** — single-use Redis-backed tickets; JWTs never appear in WebSocket URLs (`backend/app/core/tickets.py`).
- **Per-user isolation** — every repository read and write is owner-scoped (`backend/app/db/repositories.py`).
- **Inbound webhook verification** — `POST /api/webhooks/github` authenticates with HMAC-SHA256 over the raw body (`X-Hub-Signature-256`), compared in constant time; it refuses every request when no secret is configured, can be pinned to one repository, and dedupes retries by delivery id. Deliveries can only produce event rows, a diagnosis goal and a notification — no write-capable tool is reachable from that path (`backend/app/api/webhooks.py`).
- **Backups and recovery** — dumps are written to local disk only and never served over HTTP; the database password is passed to `pg_dump` through the environment, never in an argv. The single recovery action (restarting a compose service) is allowlisted, refuses `postgres`/`backend` regardless of configuration, rate-limited by a per-service cooldown, and audited (`backend/app/resilience/`). Its code default is off; the shipped `.env.example` turns it on, and it still cannot act unless the deployment also grants the backend a docker socket — which the stock compose stack deliberately does not.
- **Self-improvement is propose-only** — the nightly self-check can open a GitHub issue and nothing else. There is no code to create a branch, push a commit, open a pull request or merge one — absent, not disabled by a flag — and a test asserts the module's single write call targets the issues endpoint (`backend/app/selfcheck/github_issues.py`). Merge authority is human by construction. The nightly run is enabled in the shipped `.env.example`; issue filing additionally requires a token, and without one the run reports in-app and writes nothing anywhere.

- **Arbitrary code execution stays off** — `CODE_EXECUTION_ENABLED` is false in code *and* in the shipped `.env.example`, and is additionally admin-gated at runtime. The sandbox is `python -I` in a subprocess, not a container: it cannot stop network or filesystem access. Enable it only on a trusted single-admin deployment.
- **Repository import** — server-side clones accept github.com `owner/repo` only, run `git` as an argument list with prompts/submodules/hooks disabled under a timeout, and never log or store the optional token (`backend/app/ingestion/github_import.py`).

## The deleted safety stubs

Three unwired modules (command guard, prompt-integrity envelope, action
classifier) were deleted in the truth pass. Revisiting them, only one described
something the codebase was actually missing:

| Stub | Outcome |
|---|---|
| `command_guard` | **Reintroduced** as the argument gate above. It named the real gap: the registry judged the caller and the tool, never the arguments |
| `prompt_integrity` | **Not reintroduced** — retrieved files, fetched web pages and tool output already enter the prompt in explicit UNTRUSTED blocks (`api/chat.py`, `agents/chat_tools.py`). A second implementation would add the appearance of a control, not a control |
| `action_classifier` | **Not reintroduced** — per-action safety class and approval already exist as `ToolSpec.requires_role` and `approval_required`, enforced with an audit record on every decision |

**What the argument gate is not.** A denylist of names is a floor, not a
boundary. It stops an agent reaching the obvious high-value files; it cannot
stop an operator who leaves a secret in `/workspace/notes.txt`. It is worth
having because the pathway it closes — any authenticated account calling
`file_read` over `WS /mcp` — needed no host access at all.
