# Phase 0 — Root-files audit report

Date: 2026-07-07 · Branch: `claude/zorali-root-audit-cgm4df` · Scope: verify the
12-item external review list against the actual source. **No code changes in
this phase** — this report is the only deliverable. Line numbers reference the
tree at commit `c55a5e0`.

Verdict legend: **CONFIRMED** (defect exists as described) · **ALREADY FIXED**
(current main already resolves it) · **DIFFERENT** (real, but manifests
differently than the reviewer described).

Summary: 1 ✅ already fixed · 2 ✅ already fixed (one small residue) ·
3 ❗ confirmed · 4 ❗ confirmed · 5 🔀 different (build is sound; verified here
with a sandbox-CA workaround) · 6 ❗ confirmed (both PRs open, superseded) ·
7 ❗ confirmed (bigger than described: second WS endpoint; Redis unused) ·
8 ❗ confirmed (live unscoped call path found) · 9 🔀 partially present ·
10 🔀 partially present · 11 ❗ confirmed · 12 ✅ already fixed in substance.

---

## Item 1 — Postgres port vs. seed_admin docs — **ALREADY FIXED**

- `docker-compose.yml:49-51` — the dev compose **does** publish Postgres:
  `ports: ["5432:5432"]`, with the comment *"Published for host-side
  migrations, tests and seed_admin.py (dev only)."*
- `README.md:60-66` — documents running the seeder from the repo root with
  `POSTGRES_HOST=localhost` and states *"the dev compose publishes Postgres on
  `localhost:5432`"*. Compose and docs already agree.
- The prod compose correctly does **not** publish Postgres
  (`docker-compose.prod.yml:47-61`, no `ports:`).

**Flow executed end to end in this audit** (pgvector container on
localhost:5432, backend image booted, migrations applied by
`docker-entrypoint.sh`):

```
$ POSTGRES_HOST=localhost ZORALI_ADMIN_EMAIL=audit-test@example.com \
    ZORALI_ADMIN_PASSWORD=audit-password-123 python3 infra/scripts/seed_admin.py
Created owner account: audit-test@example.com
exit: 0

$ curl -X POST http://localhost:8000/api/auth/login \
    -d '{"email":"audit-test@example.com","password":"audit-password-123"}'
{"access_token":"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...","role":"owner",...}
```

Minor wart observed (non-fatal, trapped by passlib): `(trapped) error reading
bcrypt version … module 'bcrypt' has no attribute '__about__'` — passlib 1.7.4
probing bcrypt ≥ 4.1. Cosmetic today; pinning/migrating away from passlib can
ride along in Phase 3's dependency work.

**Phase 1 residue: none** (item can be dropped from Phase 1).

## Item 2 — `.env.example` missing documented keys — **ALREADY FIXED** (one small residue)

All four named keys are present with comments and safe defaults:

- `TAVILY_API_KEY` — `.env.example:31`
- `DEEP_RESEARCH_MAX_PAGES` — `.env.example:33`
- `CODE_EXECUTION_ENABLED` — `.env.example:41`
- `CODE_EXECUTION_TIMEOUT_SECONDS` — `.env.example:42`

Full sweep performed: every field of `Settings`
(`backend/app/core/config.py:5-83`) has a matching `.env.example` entry
(verified name-by-name). Direct `os.getenv`/`os.environ` reads outside
`Settings`:

| Variable | Read at | In `.env.example`? |
|---|---|---|
| `ZORALI_DATA_DIR` | `backend/app/checkpoint/manager.py:22`, `backend/app/db/repositories.py:140`, `backend/app/learning/trace_store.py:18` | **No** — Phase 1: add with default `/app/data` + one-line comment |
| `ZORALI_ADMIN_EMAIL` / `ZORALI_ADMIN_PASSWORD` | `infra/scripts/seed_admin.py:31-32` | No — script-scoped one-shots, documented in README:64-65; acceptable to leave out |

**Phase 1 residue: add `ZORALI_DATA_DIR` only.**

## Item 3 — Makefile pulls the wrong model — **CONFIRMED**

- `Makefile:13` — `docker compose exec ollama ollama pull llama3.1`
- Stack default is `llama3.2:1b`: `.env.example:13`, `Settings.ollama_model`
  (`backend/app/core/config.py:15`), README quick start (`README.md:55`) and
  prod instructions (`README.md:73`).

**Phase 1: change `Makefile:13` to `llama3.2:1b`.**

## Item 4 — TODO.md describes the old JSON architecture — **CONFIRMED**

- `TODO.md:7` — *"Storage: JSON repositories + local file storage"*;
  `TODO.md:15` — *"using existing JSON persistence layer"*. The store has been
  Postgres/pgvector since PR #16 (`backend/app/db/models.py`,
  `backend/migrations/versions/0001_initial.py`, README:19-20).
- Every one of the 10 plan items in `TODO.md:11-20` is already implemented on
  main (provider router, agents/orchestrator, tool registry, memory API, WS
  payload extensions, command guard, frontend controls, docs, tests).

**Phase 1: rewrite TODO.md around actual open work (see README:165-169
roadmap) or delete it.**

## Item 5 — Prod compose build — **DIFFERENT: build is sound; sandbox network blocks a clean run**

`docker compose -f docker-compose.prod.yml build` cannot complete unmodified
**in this audit sandbox** because all egress passes through a TLS-intercepting
proxy: Docker Hub's CDN and `deb.debian.org` return `403 Forbidden`, and npm
sees `SELF_SIGNED_CERT_IN_CHAIN`. These are environment failures, not repo
defects. With the sandbox's CA injected into otherwise-identical Dockerfiles
(verification only — not committed), both images were proven sound:

- **Frontend multi-stage build succeeds and nginx serves the assets:**
  ```
  #11 2.334 added 23 packages, and audited 24 packages in 2s
  #13 0.654 vite v8.0.12 building client environment for production...
  #13 0.840 ✓ built in 184ms
  #16 naming to docker.io/library/zorali-frontend-verify:latest done
  $ curl -o /dev/null -w "HTTP %{http_code}, %{size_download} bytes" localhost:8080/
  HTTP 200, 1021 bytes    (index.html of the built SPA)
  ```
- **Backend image builds** (apt layer skipped — the only environment-blocked
  step), **boots, runs Alembic migrations via the entrypoint, and reports
  healthy:**
  ```
  #10 16.13 Successfully installed ... fastapi-0.139.0 ... uvicorn-0.50.2 ...
  $ curl http://localhost:8000/api/health
  {"status":"ok","app":"Zorali","env":"local"}
  ```
- **The full 139-test suite passes inside that image** against a real
  pgvector Postgres: `139 passed, 3 warnings in 13.16s`.

Two real repo-side observations to carry into later phases:

1. `frontend/package.json:12-17` pins every dependency to `"latest"`. The
   lockfile makes `npm ci` reproducible, but any `npm install` refresh floats
   all versions at once. Worth pinning real ranges (Phase 3 dependency work).
2. Layer-cache poisoning hazard observed: when `npm ci` dies mid-flight, npm's
   long-standing *"Exit handler never called!"* bug exits 0, Docker caches the
   broken layer, and the build fails later with the misleading
   `sh: vite: not found`. Nothing to fix in-repo; noted for anyone debugging
   CI builds.

**Phase 1: run the unmodified prod build in GitHub CI (clean network) for the
formal proof; no Dockerfile fix is expected to be needed.**

## Item 6 — PRs #8 and #9 — **CONFIRMED: both open and superseded**

- **PR #8** (open, non-draft): "Add provider router, agent orchestrator,
  memory API, tool registry, and frontend provider controls". Base is
  `main@60a4442` — five major PRs behind (#14-#18). Everything it adds already
  exists on main in evolved form (`backend/app/agents/`,
  `backend/app/tools/registry.py`, memory API, provider router). Superseded.
- **PR #9** (open, draft): "Fix runtime errors: Pydantic v2 config and
  async/sync mismatch". Same stale base. Both of its fixes are moot on main:
  - `file_tools.read_file/write_file` are **intentionally** `async` now
    (`backend/app/tools/file_tools.py:11,14`); the registry awaits coroutine
    handlers (`backend/app/tools/registry.py:131` — *"read_file is async — the
    registry awaits coroutines automatically"*).
  - `config.py` still uses class-based `Config`
    (`backend/app/core/config.py:89-91`) — pydantic-settings accepts it; the
    suite passes with only deprecation-class warnings. PR #9's
    `SettingsConfigDict` migration never landed and nothing is broken.

**Phase 1: close both with a one-line "superseded by #14-#18" comment.**
(Not done in Phase 0 — the instruction to close is a Phase 1 action.)

## Item 7 — JWT in WebSocket query string — **CONFIRMED, broader than described**

- `backend/app/api/chat.py:39-45` — `chat_ws(..., token: str = Query(default=None))`,
  decoded via `decode_token(token)`.
- **Second endpoint the review missed:** `backend/app/api/mcp.py:10-15` — the
  MCP WebSocket authenticates the same way. The Phase 2 ticket design must
  cover both (or the MCP endpoint's auth must be otherwise replaced).
- `frontend/src/api/zoraliSocket.js:4` — client appends
  `?token=${encodeURIComponent(token)}`.
- Documented in `README.md:9` and `README.md:128` (`WS /ws/chat/{session_id}?token=<jwt>`)
  — both need updating in Phase 2.
- `infra/nginx/nginx.conf` — no `log_format`/`access_log` directives at all,
  so nginx's default `combined` format logs the full request line **including
  the query string**. Defense-in-depth gap confirmed.
- **Planning constraint for Phase 2:** Redis is currently *entirely unused* by
  the backend — `settings.redis_url` (`backend/app/core/config.py:13`) is the
  only reference; no module imports a Redis client, although `redis>=5.0.0` is
  installed (`backend/requirements.txt:8`) and both compose files run a Redis
  service. The ticket store will be the first real Redis consumer; Phase 2
  needs to add the client wiring (connection lifecycle, failure mode when
  Redis is down), not just the ticket logic.

## Item 8 — `owner_id=None` trusted-caller convention — **CONFIRMED**

- Codified: `backend/app/db/repositories.py:160-166` — *"``owner_id=None``
  means a trusted internal caller (background tasks, system agents): no
  ownership filter is applied."* Roughly 20 repository methods default
  `owner_id: str | None = None` (`repositories.py:180-558`);
  `backend/app/memory/retrieval.py:38` mirrors the pattern.
- **Live unscoped call path, reachable below admin:**
  `backend/app/tools/registry.py:167-180` — the `document_search` tool calls
  `repo.search_chunks(project_id, query, limit=5)` with **no `owner_id`**, and
  is registered with `requires_role="user"`. Its caller
  (`backend/app/agents/nodes.py:246`) invokes `registry.execute(call.name,
  call.inputs)` without passing actor identity, so the search runs unscoped
  across all owners' chunks for whatever `project_id` the tool receives.
- Background ingestion (`backend/app/api/files.py:94,116,121`) updates records
  by bare `file_id` — a legitimate system path today, but nothing in the type
  system distinguishes it from an accidental unscoped call, which is exactly
  the reviewer's point.

Routes themselves consistently pass `owner_id=_user["sub"]`
(e.g. `files.py:143-186`, `chat.py:95-159`), and cross-user isolation at the
HTTP layer is test-covered (see item 9) — the risk is concentrated in
internal/tool call paths. **Phase 2 item stands as designed** (required caller
context: user id or explicit SYSTEM marker + test).

## Item 9 — Test suite against real services — **PARTIALLY PRESENT**

Baseline: the whole suite runs against **real Postgres** (pgvector) — no DB
mocking — locally and in CI (`tests/backend/conftest.py:4-6,18`,
`.github/workflows/ci.yml` pgvector service). Verified in this audit:
`139 passed, 3 warnings in 13.16s`.

| Required coverage | Status | Evidence |
|---|---|---|
| Cross-user access returns 404 | **Present** | `tests/backend/test_auth_enforcement.py:109-183` — full matrix over files/artifacts/chats/search/delete |
| Token refresh flow | **Present** | `test_auth_flow.py:27-56` incl. token-type confusion (refresh≠access) |
| Token expiry | **Missing** | lifetimes asserted arithmetically (`test_auth_flow.py:91-93`) but no test that an *expired* token is rejected (no "expired" hits in `tests/`) |
| RBAC matrix per role | **Missing** | no `readonly`-role test anywhere in `tests/backend/`; RBAC helpers exist (`backend/app/core/rbac.py`) but only owner-role paths are exercised |
| Rate limiter per-sub + IP fallback | **Missing** | implementation exists (`backend/app/core/rate_limiter.py:38-59`); only settings plumbing is tested (`test_metrics_and_pdf.py:39-42`); conftest raises limits to avoid 429s (`conftest.py:19-22`) |
| Ingestion status transitions | **Present** | `test_async_ingestion.py:9-49` — queued→ready, bad-PDF isolation |
| Redis-backed anything | **N/A today** | backend does not use Redis (see item 7); becomes testable in Phase 2 |
| Alembic upgrade→downgrade round trip | **Missing** | no test references alembic; note `migrations/versions/0001_initial.py` downgrade must drop cleanly on pgvector |

**Phase 3 scope: expiry test, RBAC matrix, rate-limiter behavior tests,
alembic round trip, plus Redis service once Phase 2 lands.**

## Item 10 — CI on every PR — **PARTIALLY PRESENT**

`.github/workflows/ci.yml` (single job, triggers `on: [push, pull_request]`):

| Required | Status |
|---|---|
| pytest with Postgres service | ✅ pgvector service + `alembic upgrade head` + `pytest tests/backend -q` |
| Redis service | ❌ (moot until Phase 2 makes the app use Redis) |
| `npm ci && npm run build` | ✅ |
| Linter | ❌ — and **no linter is configured anywhere** (no `pyproject.toml`, `ruff.toml`, `.flake8`, no eslint config); Phase 3 must introduce one, not just invoke it |
| Type check "if configured" | ❌ none configured (no mypy/pyright config) — same |
| Docker builds for both images | ❌ only `docker compose config` (syntax validation, builds nothing) |
| pip-audit / npm audit | ❌ absent |

## Item 11 — Dockerfile hardening — **CONFIRMED**

- `backend/Dockerfile:1` — `FROM python:3.12-slim`: tag-pinned only, no
  digest; **no `USER` directive** — app runs as root.
- `frontend/Dockerfile:7,15` — `node:20-alpine` / `nginx:alpine`, no digests;
  nginx master runs as root (stock image).
- Compose images likewise floating: `ollama/ollama:latest`
  (`docker-compose.yml:37` — worst offender), `pgvector/pgvector:pg16`,
  `redis:7-alpine`.
- No `pip-audit` or `npm audit --audit-level=high` anywhere in CI.

## Item 12 — Code execution double-gating + README security note — **ALREADY FIXED in substance**

Double gate verified on **all three** invocation paths:

1. Artifact ▶ Run: `backend/app/api/artifacts.py:53-60` — `admin_or_above`
   dependency **and** `settings.code_execution_enabled` check.
2. `/run` task command over WS: `backend/app/api/chat.py:123-126` — checks the
   setting **and** `user["role"] in ("admin", "owner")`.
3. Agent tool: `backend/app/tools/registry.py:148-149` (setting check inside
   the handler) **and** `requires_role="admin"` (`registry.py:163`) enforced by
   `execute()` (`registry.py:50-55`) with an audit event on denial.

README security documentation already exists: `README.md:130-142` ("Security
notes") states the sandbox is `python -I` in a subprocess, **"not a container
and cannot block network or world-readable file access"**, disabled by
default, admin-gated. `.env.example:37-40` repeats the warning at the setting
itself. Phase 3 residue is wording-only, if desired: add the literal phrase
"not an isolation boundary" and the "stays admin-only until containerized
sandboxing exists" commitment.

---

## Verification commands run for this audit

```bash
# Item 1 flow (pgvector on localhost:5432; backend image ran migrations):
docker run -d --name zorali-pg -e POSTGRES_USER=zorali -e POSTGRES_PASSWORD=zorali \
  -e POSTGRES_DB=zorali_ai -p 5432:5432 pgvector/pgvector:pg16
POSTGRES_HOST=localhost ZORALI_ADMIN_EMAIL=audit-test@example.com \
  ZORALI_ADMIN_PASSWORD=audit-password-123 python3 infra/scripts/seed_admin.py
# → Created owner account: audit-test@example.com ; login returned JWT (owner)

# Item 5 (sandbox-CA-injected variants of the committed Dockerfiles):
docker build -f <fe-verify.Dockerfile> .   # → vite ✓ built in 184ms; image ok
docker run -p 8080:80 zorali-frontend-verify && curl localhost:8080/  # → HTTP 200 SPA
docker build -f <be-verify.Dockerfile> .   # → ok minus env-blocked apt layer
curl localhost:8000/api/health             # → {"status":"ok",...}

# Item 9 baseline (inside the built backend image, real Postgres):
python -m pytest tests/backend -q          # → 139 passed, 3 warnings in 13.16s
```

Environment caveat: this sandbox's egress proxy blocks Docker Hub's CDN and
deb.debian.org and intercepts TLS, so the *unmodified* `docker compose -f
docker-compose.prod.yml build` cannot run here; Phase 1 should produce that
proof in GitHub CI.
