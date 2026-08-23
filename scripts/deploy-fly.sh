#!/usr/bin/env bash
# Deploys Veritech Scan to Fly.io using Fly's remote builder — the image is
# built on Fly's infrastructure, not locally, so this never requires Docker
# or Docker Desktop on the developer's machine. See docs/fly-deployment.md.
#
# Two images come out of this, both built from the one Dockerfile (see its
# top-of-file comment): the default `web` target gets deployed to the
# web/API Machine as usual, and the `scan-runner` target (Playwright/
# Chromium included) is separately built and pushed to a fixed tag
# (`scan-runner-latest`) that apps/api/app/services/scan_orchestrator.py
# references explicitly when creating each scan's on-demand Machine — see
# _scan_runner_image_ref() there for why this can't just reuse
# FLY_IMAGE_REF.
#
# Usage: FLY_APP_NAME=veritech-scan RULES_REPO_TOKEN=... ./scripts/deploy-fly.sh [extra flyctl args]
set -euo pipefail

: "${FLY_APP_NAME:?Set FLY_APP_NAME (see docs/fly-deployment.md)}"
# Read-only, repo-scoped fine-grained PAT for the private veritech-scan-rules
# dependency (Dockerfile's pip install needs it) — see docs/rules-engine.md's
# "Private rule catalog" section. In CI this comes from the RULES_REPO_TOKEN
# Actions secret automatically; a manual/local deploy needs it exported first.
: "${RULES_REPO_TOKEN:?Set RULES_REPO_TOKEN (see docs/rules-engine.md)}"

if ! command -v flyctl >/dev/null 2>&1 && ! command -v fly >/dev/null 2>&1; then
  echo "flyctl is required (https://fly.io/docs/flyctl/install/) — no Docker needed." >&2
  exit 1
fi
FLY_BIN="$(command -v flyctl || command -v fly)"

"$FLY_BIN" deploy --remote-only --app "$FLY_APP_NAME" \
  --build-secret rules_token="$RULES_REPO_TOKEN" "$@"

echo "Building and pushing the scan-runner image (Playwright/Chromium)..."
"$FLY_BIN" deploy --remote-only --build-only --push --app "$FLY_APP_NAME" \
  --build-target scan-runner --image-label scan-runner-latest \
  --build-secret rules_token="$RULES_REPO_TOKEN"

cat <<EOF

Deployed. This build ran on Fly's remote builder, not locally.
Run 'make fly-migrate' if this deploy included a schema change.
EOF
