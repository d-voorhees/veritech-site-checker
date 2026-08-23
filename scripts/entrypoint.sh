#!/usr/bin/env bash
# Role dispatcher for the single Veritech Scan production image (see
# Dockerfile). The same deployed image runs three different things
# depending on the first argument:
#
#   web          Next.js + FastAPI, autostop/autostart Fly Machine (fly.toml)
#   scan-runner  one-off Machine that processes exactly one scan and exits
#                (created via the Fly Machines API — see
#                apps/api/app/services/scan_orchestrator.py); reads SCAN_ID
#                from the environment
#   migrate      runs Alembic migrations, used by scripts/migrate-fly.sh via
#                `fly machine run ... --rm`
#   seed         runs app.seed, used for the one-time production admin
#                bootstrap — see docs/fly-deployment.md. Set env var
#                SEED_ADMIN_ONLY=1 for `app.seed --admin-only` (a bare
#                `--admin-only` positional arg gets swallowed by `flyctl
#                machine run`'s own flag parser, so this goes through the
#                environment instead)
#
# No Docker Compose, no persistent worker process — the runner and migrate
# roles both start, do one thing, and exit.
set -euo pipefail

ROLE="${1:-web}"
APP_DIR="/app/apps/api"

case "$ROLE" in
  web)
    export API_INTERNAL_URL="${API_INTERNAL_URL:-http://127.0.0.1:8000}"
    export PORT="${PORT:-8080}"

    (cd "$APP_DIR" && exec python -m uvicorn app.main:app --host 127.0.0.1 --port 8000) &
    API_PID=$!

    (cd /app/apps/web && exec node server.js) &
    WEB_PID=$!

    trap 'kill -TERM "$API_PID" "$WEB_PID" 2>/dev/null || true' TERM INT

    # If either process exits, the Machine should exit too so Fly notices
    # and restarts it — a half-alive container (API up, web down, or vice
    # versa) is worse than a clean restart.
    wait -n "$API_PID" "$WEB_PID"
    EXIT_CODE=$?
    kill -TERM "$API_PID" "$WEB_PID" 2>/dev/null || true
    exit "$EXIT_CODE"
    ;;

  scan-runner)
    cd "$APP_DIR"
    exec python -m app.runner
    ;;

  migrate)
    cd "$APP_DIR"
    exec python -m alembic upgrade head
    ;;

  seed)
    cd "$APP_DIR"
    if [ "${SEED_ADMIN_ONLY:-}" = "1" ]; then
      exec python -m app.seed --admin-only
    else
      exec python -m app.seed
    fi
    ;;

  *)
    echo "[entrypoint] Unknown role: $ROLE (expected web|scan-runner|migrate|seed)" >&2
    exit 1
    ;;
esac
