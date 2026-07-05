#!/bin/sh
# Run database migrations (waiting for Postgres to come up), then start the app.
set -e

attempts=0
until alembic upgrade head; do
  attempts=$((attempts + 1))
  if [ "$attempts" -ge 30 ]; then
    echo "Database migrations failed after ${attempts} attempts" >&2
    exit 1
  fi
  echo "Postgres not ready (attempt ${attempts}); retrying in 2s..."
  sleep 2
done

exec "$@"
