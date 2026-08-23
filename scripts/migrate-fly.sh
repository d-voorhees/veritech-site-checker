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
"$FLY_BIN" machine run "$IMAGE" "migrate" \
  --app "$FLY_APP_NAME" \
  --region "$REGION" \
  --rm

echo "Migrations complete."
