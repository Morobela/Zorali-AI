# AI Risk Register

| Risk | Control (wired today) |
|---|---|
| Prompt injection | File and web content enter prompts as UNTRUSTED evidence blocks with explicit do-not-follow framing (`backend/app/api/chat.py`) |
| Excessive agency | Tool registry role gates + `approval_required` + audit log on every execution (`backend/app/tools/registry.py`); code sandbox double-gated (env opt-in + admin role) |
| Credential disclosure through a tool | Role decides who may call a tool; `backend/app/safety/argument_guard.py` decides what they may call it with. Path-taking tools refuse `.env`, private keys and `.ssh`/`.aws`/`.kube` contents, resolving symlinks so the check cannot be laundered. Not role-exempt — an owner's session is the one a prompt injection would most like to borrow |
| Credential leakage | JWTs only in Authorization headers; WebSockets use single-use Redis tickets; every repository access is owner-scoped. The optional GitHub token is never logged or stored, and the repo importer never writes it into an import record |
| Hallucination | Answers grounded in retrieval carry citations (`[filename#chunk]` for files, `[W#]` for web sources); no automated verification engine yet |

## Risks introduced by autonomy

Capability map U1–U9 gave Zorali work that outlives a request. These rows exist
because "a human is watching" stopped being a control.

| Risk | Control (wired today) |
|---|---|
| Runaway spend on unattended work | Every provider call is priced by `inference/energy_scorer` and attributed to the step that made it via a `contextvars` meter stack. A goal pauses itself at `GOAL_BUDGET_WARN_RATIO` (80%) of `GOAL_MAX_COST_USD`, explains the numbers, and notifies its owner. It is never auto-resumed (`backend/app/agents/goal_engine.py`) |
| Uncontrolled self-modification | The nightly self-check can open a GitHub issue and nothing else. No code exists to create a branch, push a commit, open a pull request or merge one — absent, not disabled by a flag. A test asserts the module's single write call targets the issues endpoint (`backend/app/selfcheck/github_issues.py`) |
| Autonomous action on infrastructure | One action: restart an allowlisted compose service. `postgres` and `backend` are refused regardless of configuration; per-service cooldown; every attempt audited and surfaced on the outage notification. Off in code, on in the shipped `.env.example`, and still inert without a docker socket the stock stack does not mount (`backend/app/resilience/recovery.py`) |
| Hostile or forged inbound events | HMAC-SHA256 over the raw body, constant-time compare, refuses everything when no secret is set, optional single-repository pin, retries deduped by delivery id. A delivery can produce event rows, a diagnosis goal and a notification — no write-capable tool is reachable from that path (`backend/app/api/webhooks.py`) |
| Backups concentrating every account's data | Dumps stay on local disk and are never served over HTTP — the manifest is the only thing `GET /api/backups` returns. The password reaches `pg_dump` through the environment, never argv (`backend/app/resilience/backup.py`) |
| Background work failing invisibly | A failed backup notifies (a successful one deliberately does not — a nightly "ok" trains people to ignore the channel). Imports interrupted by a restart are reconciled to `failed` on boot instead of claiming to run forever. Goals record why they stopped |
| Notification fatigue defeating the channel | Only changes for the worse notify, and only on a state *diff* — a service that is still down does not re-notify each scan |
| Background writes escaping owner scoping | `db/repositories.py` requires an explicit caller on every call: a user id, or a deliberate `SYSTEM` marker. An unscoped query cannot happen by omission, which is what makes autonomous writes auditable to an owner |
