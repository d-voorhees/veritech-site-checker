# Fly.io operations

Day-two operations for a deployed Veritech Scan. See `docs/fly-deployment.md`
for initial setup.

## Logs

```bash
make fly-logs                                    # flyctl logs --app "$FLY_APP_NAME"
flyctl logs --app "$FLY_APP_NAME" --region iad    # filter by region
```

Scan-runner Machines log to the same Fly log stream as the web/API
Machine — filter by the scan ID (printed in every `[scan-runner]`/
structured log line) or by Machine ID (`flyctl logs -i <machine_id>`) to
isolate one scan's output.

## Inspecting app + Machine status

```bash
make fly-status
# equivalent to:
flyctl status --app "$FLY_APP_NAME"
flyctl machine list --app "$FLY_APP_NAME"
```

The web/API Machine(s) show up permanently (started/stopped depending on
recent traffic — `min_machines_running = 0` means it's normal to see
`stopped` between requests). Scan-runner Machines appear only while a scan
is in flight or shortly after (see "Cleaning up scan-runner Machines"
below).

## Inspecting a failed scan

Every scan's full timeline is in `scan_events`, and its terminal state is
on `scan_requests`. Two ways to look:

**Via the API** (as the owning user or an admin):

```bash
curl -s -b cookies.txt "$APP_URL/api/v1/scans/<scan_id>" | jq '.status, .failure_summary'
curl -s -b cookies.txt "$APP_URL/api/v1/scans/<scan_id>/events" | jq -r '.[] | "\(.created_at)  \(.event_type)  \(.message)"'
```

**Via direct SQL** (the database is Neon, external to Fly — connect with
`psql "$DATABASE_URL"`, `npx neonctl connection-string --project-id
<id> | xargs psql`, or Neon's dashboard SQL editor):

```sql
select id, status, failure_summary, runner_machine_id, retry_count, started_at, completed_at
from scan_requests
where status in ('failed', 'completed_with_warnings')
order by created_at desc
limit 20;

select event_type, message, created_at
from scan_events
where scan_request_id = '<scan_id>'
order by created_at;
```

A `runner_creation_failed` event means the Fly Machines API call itself
failed (check `FLY_API_TOKEN` validity/scope and Fly's own status page). A
`runner_failed` event means the runner Machine started but hit an
unrecoverable error mid-scan — check its logs by Machine ID
(`scan_requests.runner_machine_id`).

## Cleaning up stopped scan-runner Machines

Scan-runner Machines are created with `config.auto_destroy = true`, so Fly
destroys them automatically once they stop — for a normal (zero) exit, this
happens promptly; **for a non-zero exit, Fly keeps the Machine around for
about two hours before destroying it**, specifically so you can inspect its
logs/state to debug the failure. You shouldn't normally need to clean
anything up by hand, but if you want to:

```bash
# list all Machines, including recently-stopped ones
flyctl machine list --app "$FLY_APP_NAME"

# inspect one before destroying it
flyctl machine status <machine_id> --app "$FLY_APP_NAME"

# force-destroy a stopped scan-runner Machine immediately
flyctl machine destroy <machine_id> --app "$FLY_APP_NAME" --force
```

If you ever see a scan-runner Machine that's been `started` for far longer
than `SCAN_MAX_TOTAL_MINUTES` (default 10) plus a few minutes of startup
overhead, that's a stuck Machine — check its logs, then
`flyctl machine stop <machine_id>` (it will then auto-destroy).

## Rotating secrets

```bash
flyctl secrets set JWT_SECRET="$(openssl rand -hex 32)" --app "$FLY_APP_NAME"
```

`flyctl secrets set` restarts the web/API Machine(s) automatically to pick
up the new value. Rotating `FLY_API_TOKEN` does **not** require restarting
anything running — new scan-runner Machine creations just pick up the new
token from the environment on their next request.

## Cost and scaling notes

- The web/API Machine now runs always-on (`min_machines_running = 1`,
  `auto_stop_machines = "off"`) at the smallest VM tier
  (`shared-cpu-1x`/256mb) — see README's "Known limitations" for why
  scale-to-zero was dropped here (a fixed ~13-18s Fly platform boot cost,
  not something CPU/memory/image-size/region changes could fix).
- Each scan-runner Machine bills only for the scan's actual duration (a few
  seconds to `SCAN_MAX_TOTAL_MINUTES`), then is destroyed — these remain
  scale-to-zero.
- Postgres is the other always-on, always-billed dependency in this
  architecture — size it for your actual data volume, not scan traffic.
- Scan-runner Machines are sized larger than the web/API Machine (more
  CPU/memory, for Chromium) — see the `guest` config in
  `request_scan_runner` (`apps/api/app/services/scan_orchestrator.py`) if
  you need to tune this.
