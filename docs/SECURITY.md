# Security

Controls wired into real request paths today (each verifiable in code):

- **RBAC** — JWT auth with a role hierarchy; every protected route declares a minimum role (`backend/app/core/rbac.py`).
- **Rate limiting** — token-bucket middleware on every HTTP request (`backend/app/core/rate_limiter.py`).
- **Prompt-injection hardening** — retrieved file content and web evidence enter the prompt in explicitly UNTRUSTED blocks the model is told to treat as evidence, not instructions (`backend/app/api/chat.py`).
- **Tool gating and audit** — the tool registry enforces per-tool minimum roles and `approval_required`, and records an audit event for every execution (`backend/app/tools/registry.py`).
- **Sandboxed code execution** — `python -I` subprocess with clean env, timeout and output caps, double-gated behind `CODE_EXECUTION_ENABLED` plus admin+ role (`backend/app/tools/code_sandbox.py`).
- **WebSocket auth** — single-use Redis-backed tickets; JWTs never appear in WebSocket URLs (`backend/app/core/tickets.py`).
- **Per-user isolation** — every repository read and write is owner-scoped (`backend/app/db/repositories.py`).

The standalone safety stubs (command guard, prompt-integrity envelope, action
classifier) were unwired and deleted in the truth pass; reintroducing them
properly, inside the registry's execution path, is tracked in `TODO.md`.
