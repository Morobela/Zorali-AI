# Deployment

Run `docker compose up --build`. For GPU, use `docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build`.

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

## Recovery actions

One recovery action exists — restarting a compose service — and it is **off
by default**. Detection (the reality scan) and alerting (notifications) came
first and should be trusted before anything is allowed to act on them.

| Setting | Default | Meaning |
|---|---|---|
| `RECOVERY_ACTIONS_ENABLED` | `false` | Alert-only until switched on |
| `RECOVERY_RESTART_SERVICES` | `ollama` | Allowlist of restartable services |
| `RECOVERY_COOLDOWN_MINUTES` | `30` | Minimum gap between attempts per service |

`postgres` and `backend` are refused even if listed: restarting the database
this process is connected to, or the process running the code, is not
recovery. Each attempt is written to the audit log and reported in the same
notification as the outage, so an action Zorali took is never invisible.
