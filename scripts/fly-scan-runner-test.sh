#!/usr/bin/env bash
# Creates one synthetic scan against the deployed app and polls it to
# completion, to verify the full on-demand runner lifecycle for real: the
# API requests a Fly Machine, the Machine claims and runs the scan, and it
# exits/is destroyed. Talks only to the public HTTPS API — no flyctl,
# Docker, or direct DB access required, so it also works as a smoke test
# from CI.
#
# Usage:
#   APP_URL=https://veritech-scan.fly.dev \
#   SCAN_RUNNER_TEST_EMAIL=admin@example.com \
#   SCAN_RUNNER_TEST_PASSWORD=... \
#   ./scripts/fly-scan-runner-test.sh
set -euo pipefail

: "${APP_URL:?Set APP_URL to the deployed app base URL, e.g. https://veritech-scan.fly.dev}"
: "${SCAN_RUNNER_TEST_EMAIL:?Set SCAN_RUNNER_TEST_EMAIL to an active user email}"
: "${SCAN_RUNNER_TEST_PASSWORD:?Set SCAN_RUNNER_TEST_PASSWORD to the password for that user}"

TARGET="${SCAN_RUNNER_TEST_TARGET:-example.com}"
MAX_WAIT_SECONDS="${SCAN_RUNNER_TEST_TIMEOUT:-300}"
POLL_INTERVAL_SECONDS=5

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required." >&2
  exit 1
fi

COOKIE_JAR="$(mktemp)"
trap 'rm -f "$COOKIE_JAR"' EXIT

echo "Logging in to $APP_URL as $SCAN_RUNNER_TEST_EMAIL..."
LOGIN_STATUS="$(curl -sS -o /dev/null -w '%{http_code}' -c "$COOKIE_JAR" \
  -X POST "$APP_URL/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$SCAN_RUNNER_TEST_EMAIL\",\"password\":\"$SCAN_RUNNER_TEST_PASSWORD\"}")"
if [ "$LOGIN_STATUS" != "200" ]; then
  echo "Login failed (HTTP $LOGIN_STATUS)." >&2
  exit 1
fi

echo "Creating a synthetic scan for $TARGET (max_pages=10)..."
CREATE_RESPONSE="$(curl -sS -b "$COOKIE_JAR" \
  -X POST "$APP_URL/api/v1/scans" \
  -H "Content-Type: application/json" \
  -d "{\"target_input\":\"$TARGET\",\"notes\":\"[fly-scan-runner-test] synthetic verification scan\",\"max_pages\":10,\"authorization_acknowledgment\":true}")"

SCAN_ID="$(echo "$CREATE_RESPONSE" | jq -r '.id // empty')"
if [ -z "$SCAN_ID" ]; then
  echo "Scan creation failed:" >&2
  echo "$CREATE_RESPONSE" >&2
  exit 1
fi
echo "Scan created: $SCAN_ID (status: $(echo "$CREATE_RESPONSE" | jq -r '.status'))"

echo "Polling for the on-demand runner to pick it up and finish (timeout: ${MAX_WAIT_SECONDS}s)..."
ELAPSED=0
STATUS="unknown"
RUNNER_MACHINE_ID=""
while [ "$ELAPSED" -lt "$MAX_WAIT_SECONDS" ]; do
  SCAN_RESPONSE="$(curl -sS -b "$COOKIE_JAR" "$APP_URL/api/v1/scans/$SCAN_ID")"
  STATUS="$(echo "$SCAN_RESPONSE" | jq -r '.status')"
  echo "  [$ELAPSED s] status: $STATUS"

  case "$STATUS" in
    completed|completed_with_warnings|failed|cancelled)
      break
      ;;
  esac

  sleep "$POLL_INTERVAL_SECONDS"
  ELAPSED=$((ELAPSED + POLL_INTERVAL_SECONDS))
done

echo
echo "Recent scan events:"
curl -sS -b "$COOKIE_JAR" "$APP_URL/api/v1/scans/$SCAN_ID/events" | jq -r '.[] | "  \(.created_at)  \(.event_type)  \(.message)"'

case "$STATUS" in
  completed|completed_with_warnings)
    echo
    echo "PASS: scan $SCAN_ID finished with status '$STATUS'."
    echo "Check 'fly machine list' / docs/fly-operations.md if you want to confirm the runner Machine was cleaned up."
    exit 0
    ;;
  *)
    echo
    echo "FAIL: scan $SCAN_ID did not complete successfully (final status: '$STATUS')." >&2
    exit 1
    ;;
esac
