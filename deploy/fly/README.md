# Fly.io deployment — quick reference

Veritech Scan deploys as one Fly.io app with two Machine roles built from
the same image (root `Dockerfile`, dispatched by `scripts/entrypoint.sh`):

- **Web/API Machine** (`fly.toml`) — Next.js + FastAPI, autostop/autostart,
  `min_machines_running = 0`.
- **Scan-runner Machine** — created on demand per scan via the Fly Machines
  API (`apps/api/app/services/fly_machines.py`), runs one scan, exits, and
  is destroyed (`config.auto_destroy = true`).

No Docker or Docker Desktop is required locally — `fly deploy --remote-only`
builds the image on Fly's own infrastructure.

```bash
export FLY_APP_NAME=veritech-scan
make fly-init      # create the app + walk through required secrets
make fly-deploy     # remote-build deploy
make fly-migrate    # run Alembic migrations in a one-off Machine
make fly-status      # app + Machine status
make fly-logs         # stream logs
make fly-scan-runner-test  # end-to-end synthetic scan against the deployed app
```

Full detail:

- **[../../docs/fly-deployment.md](../../docs/fly-deployment.md)** — initial
  setup: app creation, Postgres provisioning, every required secret,
  first deploy, migrations, seeding the admin user, verification.
- **[../../docs/fly-operations.md](../../docs/fly-operations.md)** — day-two
  operations: logs, inspecting failed scans, cleaning up stopped
  scan-runner Machines, secret rotation, cost/scaling notes.
- **[../../docs/architecture.md](../../docs/architecture.md)** — why the app
  is split this way and the full scan initiation flow.
