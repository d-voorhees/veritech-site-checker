#!/usr/bin/env bash
# Runs Alembic migrations against the production database, using a one-off
# Fly Machine (the same "create it, run it, it exits and is destroyed"
# pattern as a scan-runner Machine — see scripts/entrypoint.sh's `migrate`
# role) instead of a long-lived box. Requires flyctl; no Docker needed.
#
# Usage: FLY_APP_NAME=veritech-scan ./scripts/migrate-fly.sh
set -euo pipefail

: "${FLY_APP_NAME:?Set FLY_APP_NAME (see docs/fly-deployment.md)}"
REGION="${FLY_PRIMARY_REGION:-iad}"

if ! command -v flyctl >/dev/null 2>&1 && ! command -v fly >/dev/null 2>&1; then
  echo "flyctl is required (https://fly.io/docs/flyctl/install/) — no Docker needed." >&2
  exit 1
fi
FLY_BIN="$(command -v flyctl || command -v fly)"

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required to read the currently deployed image reference." >&2
  exit 1
fi

echo "Looking up the currently deployed image for $FLY_APP_NAME..."
IMAGE="$("$FLY_BIN" machine list --app "$FLY_APP_NAME" --json | jq -r '.[0].config.image // empty')"
if [ -z "$IMAGE" ]; then
  echo "Could not determine the deployed image from 'fly machine list --json'." >&2
  echo "Make sure at least one Machine exists (run 'make fly-deploy' first)." >&2
  exit 1
fi
echo "Using image: $IMAGE"

echo "Running migrations in a one-off Machine (region: $REGION)..."
# The image's ENTRYPOINT is already /app/scripts/entrypoint.sh (see
# Dockerfile) — "migrate" becomes its argument, not a second copy of the
# script path.
#
# `flyctl machine run`'s default behavior blocks waiting to *observe* the
# Machine reach "started" via polling. `alembic upgrade head` against an
# already-current schema exits almost immediately, and with --rm the
# Machine self-destructs right after — the whole create->start->exit->
# destroy lifecycle can finish in ~15s. That's often faster than flyctl's
# poll interval, so it never catches the transient "started" state and
# times out after its full 5-minute default wait, reporting a false
# failure even though the migration already succeeded (verified in
# production on 2026-09-02: exit_code=0 in the Machine's own event log
# while flyctl reported "timeout ... to reach 'started'").
#
# --detach skips that unreliable wait. We then use `machine wait`, which
# checks the Machine's *current* state (and returns immediately if it's
# already there) instead of watching for a transition — so a Machine that
# finished before we even got here still passes. Waiting for "destroyed"
# specifically (not "stopped") avoids racing the --rm cleanup, which
# follows within milliseconds of exit.
RUN_OUTPUT="$("$FLY_BIN" machine run "$IMAGE" "migrate" \
  --app "$FLY_APP_NAME" \
  --region "$REGION" \
  --rm \
  --detach 2>&1)" || { echo "$RUN_OUTPUT" >&2; exit 1; }
echo "$RUN_OUTPUT"

MACHINE_ID="$(echo "$RUN_OUTPUT" | grep -oE 'Machine ID: [0-9a-f]+' | head -1 | awk '{print $NF}')"
if [ -z "$MACHINE_ID" ]; then
  echo "Could not determine the migration Machine's ID from 'flyctl machine run' output." >&2
  exit 1
fi

echo "Waiting for migration Machine $MACHINE_ID to finish (up to 5m)..."
"$FLY_BIN" machine wait "$MACHINE_ID" --app "$FLY_APP_NAME" --state destroyed --wait-timeout 5m

STATUS_OUTPUT="$("$FLY_BIN" machine status "$MACHINE_ID" --app "$FLY_APP_NAME" 2>&1 || true)"
echo "$STATUS_OUTPUT"

EXIT_CODE="$(echo "$STATUS_OUTPUT" | grep -oE 'exit_code=-?[0-9]+' | head -1 | cut -d= -f2)"
if [ "$EXIT_CODE" != "0" ]; then
  echo "Migration Machine exited with code ${EXIT_CODE:-unknown} — see output above." >&2
  exit 1
fi

echo "Migrations complete."
