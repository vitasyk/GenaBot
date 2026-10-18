#!/usr/bin/env bash
# Build, apply database migrations, then (re)start the bot. See DEPLOY.md.
set -euo pipefail

if [ ! -f .env ]; then
    echo "Error: .env not found (copy .env.example and fill it in)." >&2
    exit 1
fi

docker compose build
# Migrate in a one-off container first, so new code never starts against an old schema
docker compose run --rm bot alembic upgrade head
docker compose up -d

echo "Deployed. Logs: docker compose logs -f bot"
