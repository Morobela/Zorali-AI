# Deployment

Run `docker compose up --build`. For GPU, use `docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build`.

## Turning the autonomous features on

The shipped `.env.example` enables everything that is safe and self-contained.
Copying it (`cp .env.example .env`) gives you a deployment where Zorali scans
its own infrastructure, notifies you, runs durable goals under a spend cap,
routes mechanical steps to a small local model, backs itself up nightly, and
audits its own documentation. **An existing `.env` does not gain these
automatically** — diff it against `.env.example` and copy the new block over.

Three things need something only you can provide:

| Feature | Works out of the box? | What it needs from you |
|---|---|---|
| Reality scan, goals, budgets, model routing, backups, nightly self-check | yes | nothing |
| Self-check **filing issues** | reports in-app only | `GITHUB_TOKEN` (fine-grained PAT, Issues:write) |
| GitHub event inbox (U5) | refuses everything (503) | `GITHUB_WEBHOOK_SECRET` here *and* in the repo's webhook settings |
| Recovery restart (U9) | reports "docker is not available" | a docker socket mounted into the backend — see below |
| Sandboxed code execution | off, deliberately | `CODE_EXECUTION_ENABLED=true`, only on a trusted single-admin host |

### Letting recovery actually restart a service

`RECOVERY_ACTIONS_ENABLED=true` is set, but the backend container has no
docker socket, so an attempt degrades to "docker is not available in this
environment" — recorded on the outage notification rather than swallowed. To
let it act, mount the socket into the backend service:

```yaml
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock   # root-equivalent on the host
```

That grant is root-equivalent control of the host machine, which is why it is
not in the stock compose stack. The bounds still hold — allowlist,
`postgres`/`backend` refused, one restart per cooldown, every attempt audited
— but decide it deliberately.

### Verifying

```bash
curl -s localhost:8000/ | jq '.features'          # what this build has wired
curl -sH "Authorization: Bearer $TOKEN" localhost:8000/api/self-check   # nightly runs
curl -sH "Authorization: Bearer $TOKEN" localhost:8000/api/backups      # dumps + manifest
curl -sH "Authorization: Bearer $TOKEN" localhost:8000/api/notifications
```

To turn any of it back off, set the flag to `false` and restart the backend;
nothing needs unwinding.

## Backups

A nightly `pg_dump` runs at `BACKUP_HOUR_UTC` (default 02:00 UTC) and keeps
the last `BACKUP_KEEP` dumps (default 7), writing to `$ZORALI_DATA_DIR/backups`
alongside a `manifest.json`. Every dump is verified before it counts — the
file must exist, be non-trivial and carry PostgreSQL's dump header — and a
**failed** backup notifies the admin accounts. A successful one is silent on
purpose: a nightly "backup ok" trains people to ignore the channel that also
carries "backup failed".

| Setting | Default | Meaning |
|---|---|---|
| `BACKUP_ENABLED` | `true` | Run the nightly dump |
| `BACKUP_HOUR_UTC` | `2` | Hour (UTC) the dump runs |
| `BACKUP_KEEP` | `7` | How many dumps to retain |
| `BACKUP_TIMEOUT_SECONDS` | `900` | Give up on a stuck `pg_dump` |

Inspect them with `GET /api/backups` (admin), or take one now with
`POST /api/backups/run`. The dumps themselves are never served over HTTP — a
database dump is every account's data in one file.

## Restore

This is the procedure `tests/backend/test_backup_restore.py` runs, so it
cannot drift away from something that works. Restore into a **scratch**
database first and check it there; never restore over a live database you
have not finished investigating.

```bash
# 1. Pick a dump (newest last).
ls -1 "$ZORALI_DATA_DIR"/backups/zorali-*.sql

# 2. Create a scratch database.
export PGPASSWORD="$POSTGRES_PASSWORD"
psql -h "$POSTGRES_HOST" -U "$POSTGRES_USER" -d postgres \
     -c 'CREATE DATABASE zorali_restore_check'

# 3. Restore into it. ON_ERROR_STOP turns a partial restore into a failure
#    rather than a half-populated database that looks fine.
psql -h "$POSTGRES_HOST" -U "$POSTGRES_USER" -d zorali_restore_check \
     -v ON_ERROR_STOP=1 -f "$ZORALI_DATA_DIR/backups/zorali-<timestamp>.sql"

# 4. Check it holds what you expect before trusting it.
psql -h "$POSTGRES_HOST" -U "$POSTGRES_USER" -d zorali_restore_check \
     -c 'SELECT count(*) FROM users; SELECT count(*) FROM chat_messages;'
```

To bring the restored data into service, stop the backend, point
`POSTGRES_DB` at the scratch database (or rename it into place), and start
again. Dumps are taken with `--no-owner --no-privileges`, so they restore
cleanly under whichever role runs the restore.

The `vector` extension must exist in the target database; the dump includes
its `CREATE EXTENSION`, which requires the restoring role to be a superuser
on that database (the default `zorali` role in the compose stack is).

## Model routing for goal steps

A plan is not homogeneous work. `STEP_MODEL_POLICY` routes each step by the
kind the planner gave it, so mechanical steps can run on a small local model
while synthesis gets the strong one:

```bash
STEP_MODEL_POLICY="classification=llama3.2:1b,extraction=llama3.2:1b,synthesis=gpt-4o"
```

Kinds are `classification`, `extraction`, `research`, `synthesis`, `code` and
`general`; anything else the planner invents is treated as `general` rather
than routed somewhere unintended. Unlisted kinds use the default model, and an
empty policy (the default) keeps every step on the default model exactly as
before.

Precedence, strongest first: a model passed into the run, then the model the
goal was started with — a user who picked a model in the UI meant it, and the
policy never overrides that — then the policy, then the provider default. Each
step records what it actually ran on, so a goal's spend can be explained per
step rather than guessed at.

## Recovery actions

One recovery action exists — restarting a compose service. The code default is
**off**; the shipped `.env.example` turns it on, and even then it cannot act
without a docker socket the stock compose stack does not mount (above).
Detection (the reality scan) and alerting (notifications) came first and should
be trusted before anything is allowed to act on them.

| Setting | Code default | `.env.example` | Meaning |
|---|---|---|---|
| `RECOVERY_ACTIONS_ENABLED` | `false` | `true` | Alert-only until switched on |
| `RECOVERY_RESTART_SERVICES` | `ollama` | `ollama` | Allowlist of restartable services |
| `RECOVERY_COOLDOWN_MINUTES` | `30` | `30` | Minimum gap between attempts per service |

`postgres` and `backend` are refused even if listed: restarting the database
this process is connected to, or the process running the code, is not
recovery. Each attempt is written to the audit log and reported in the same
notification as the outage, so an action Zorali took is never invisible.
