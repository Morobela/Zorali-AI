# OWASP LLM Mapping

| OWASP LLM risk | Zorali control (wired today) |
|---|---|
| LLM01 Prompt injection | UNTRUSTED evidence blocks for file/web content in the chat prompt (`backend/app/api/chat.py`). Inbound webhook payloads reach a diagnosis prompt under the same framing, and that path has no write-capable tool |
| LLM02 Insecure output handling | The frontend never renders raw HTML from the model (react-markdown without `rehype-raw`, no `dangerouslySetInnerHTML`) |
| LLM06 Excessive agency | Registry role gates, `approval_required`, audit log; sandbox behind env opt-in + admin role. Arguments are gated as well as identity: path-taking tools refuse credential files (`backend/app/safety/argument_guard.py`), so a tool a user may legitimately call cannot be pointed at the deployment's secrets. Autonomous work is bounded separately — see below |
| LLM10 Unbounded consumption | HTTP rate limiting, an upload size ceiling (`MAX_UPLOAD_MB`), and per-goal cost budgets enforced in the goal engine and the task queue: every provider call is priced and attributed to the step that made it, `QueuedTask.max_cost_usd` short-circuits a task whose remaining budget is gone (`budget_exhausted`), and a goal pauses itself at `GOAL_BUDGET_WARN_RATIO` of `GOAL_MAX_COST_USD` rather than spending to the ceiling (capability map U7) |

## Autonomy-specific risks

The list above assumes a request/response assistant. Zorali also acts without
being asked (capability map U1–U9), which the OWASP categories cover only
loosely, so those bounds are stated here rather than forced into a numbered row.

| Risk | Bound |
|---|---|
| Work continues unattended after a restart | Goals resume, but each step is still priced against the goal's cap and the goal pauses itself at 80% of it. A paused goal is never auto-resumed — a human resumes it or raises the cap |
| Self-modification | Propose-only **by construction**, not by a flag: no code exists to create a branch, push a commit or open a pull request. The nightly self-check's single write call targets the issues endpoint, and a test asserts it |
| Autonomous infrastructure action | One action exists (restart an allowlisted compose service). Off in code, on in the shipped template, and inert without a docker socket the stock stack does not mount. `postgres` and `backend` are refused regardless of configuration; one attempt per cooldown; every attempt audited and reported on the same notification as the outage |
| Unauthenticated inbound events | `POST /api/webhooks/github` verifies HMAC-SHA256 over the raw body in constant time, refuses every request when no secret is configured, can be pinned to one repository, and dedupes retries by delivery id |
| Data concentrated by backups | Dumps are written to local disk and never served over HTTP; the database password reaches `pg_dump` through the environment, never argv |
| Silent failure of a background task | A failed backup notifies; interrupted imports are reconciled to `failed` on boot rather than claiming to be importing forever; a goal that cannot proceed records why. The design rule is that nothing unattended is allowed to fail quietly |
