# Fly.io deployment

Step-by-step production deployment for Veritech Scan on Fly.io. See
`docs/architecture.md` for why the app is split into a web/API Machine and
on-demand scan-runner Machines, and `docs/fly-operations.md` for
day-two operations (logs, failed scans, cleaning up Machines, secret
rotation).

## Prerequisites

- A Fly.io account and org.
- A [Neon](https://neon.tech) account and project. Veritech Scan's database
  is **not** hosted on Fly — it's a Neon Postgres project, reached over TLS
  from whichever Fly Machine needs it (see `docs/architecture.md`'s "Data
  flow"). Neon's own CLI (`npx neonctl`) or dashboard both work for
  provisioning; no Docker needed either way.
- [`flyctl`](https://fly.io/docs/flyctl/install/) installed locally.
  **No Docker or Docker Desktop is required anywhere in this workflow** —
  `fly deploy --remote-only` builds the image on Fly's own infrastructure.
- `jq` (used by `scripts/migrate-fly.sh` and
  `scripts/fly-scan-runner-test.sh`).
- A fine-grained GitHub PAT with read-only access to the private
  `veritech-scan-rules` repo, exported as `RULES_REPO_TOKEN` — needed only
  for a manual/local `make fly-deploy` (CI already has this as a repository
  secret and doesn't need anything from you). See `docs/rules-engine.md`'s
  "Private rule catalog" section for what it's for and how to generate one.

## 1. Create the app (`make fly-init`)

```bash
export FLY_APP_NAME=veritech-scan   # pick your own app name
flyctl auth login
make fly-init                       # flyctl apps create "$FLY_APP_NAME"
```

## 2. Provision Postgres (Neon)

The app only needs a `postgresql+psycopg://...` connection string in
`DATABASE_URL` — it doesn't care that the database isn't on Fly.

```bash
npx neonctl projects create --name veritech-scan
npx neonctl connection-string --project-id <project-id-from-above>
```

Take that connection string and rewrite its scheme from `postgresql://` to
`postgresql+psycopg://` (SQLAlchemy needs the driver in the scheme; keep
`?sslmode=require` and any `channel_binding` param as-is), then set it:

```bash
flyctl secrets set \
  DATABASE_URL="postgresql+psycopg://<user>:<password>@<host>/<db>?sslmode=require&channel_binding=require" \
  --app "$FLY_APP_NAME"
```

(`app/config.py`'s `resolved_database_url` also accepts `FLY_DATABASE_URL`
as an alternate name — useful if you ever move to Fly Postgres or another
provider that sets that name automatically, e.g. via `fly postgres attach`.
Neither this deployment nor the steps above use that path.)

## 3. Set required secrets

```bash
flyctl secrets set \
  FLY_APP_NAME="$FLY_APP_NAME" \
  FLY_API_TOKEN="$(flyctl tokens create deploy -x 999999h -a "$FLY_APP_NAME")" \
  FLY_PRIMARY_REGION="iad" \
  APP_URL="https://${FLY_APP_NAME}.fly.dev" \
  MARKETING_SITE_URL="https://veritechdiligence.com" \
  NEXT_PUBLIC_PRODUCT_NAME="Veritech Site Checker" \
  PARENT_BRAND="Veritech Diligence" \
  JWT_SECRET="$(openssl rand -hex 32)" \
  INITIAL_ADMIN_EMAIL="you@example.com" \
  INITIAL_ADMIN_PASSWORD="$(openssl rand -base64 24)" \
  GOOGLE_PAGESPEED_API_KEY="" \
  SENTRY_DSN="" \
  --app "$FLY_APP_NAME"
```

Notes:

- `FLY_API_TOKEN` is what the API process uses to call the Fly Machines API
  and create scan-runner Machines — scope it to this app
  (`flyctl tokens create deploy -a "$FLY_APP_NAME"`), not a full personal
  token. It is read server-side only and never reaches the browser.
- `FLY_DATABASE_URL` isn't listed above because step 2 sets it (directly or
  as `DATABASE_URL`) — don't overwrite it here.
- Save the generated `INITIAL_ADMIN_PASSWORD` somewhere safe; it's only
  used the first time `app.seed` runs.

## 4. Deploy (`make fly-deploy`)

```bash
export RULES_REPO_TOKEN=...   # see "Prerequisites" above
make fly-deploy
```

This runs `scripts/deploy-fly.sh`, which does two remote builds — the
default `web` target (Chromium-free, deployed to the web/API Machine per
`fly.toml`) and, separately, the `scan-runner` target (Playwright/Chromium
included, pushed to the fixed `scan-runner-latest` tag that
`scan_orchestrator.py` references when creating each scan's on-demand
Machine — see the Dockerfile's top-of-file comment). Both build on Fly's
remote builder, not on your machine.

## 5. Run migrations (`make fly-migrate`)

```bash
make fly-migrate
```

Runs Alembic (`upgrade head`) in a one-off Fly Machine built from the image
you just deployed, then exits — the same "create it, run it, it goes away"
pattern scan-runners use (see `scripts/migrate-fly.sh`). Run this after
every deploy that includes a schema change.

## 6. Seed the initial admin

Same one-off-Machine pattern as migrations, using `scripts/entrypoint.sh`'s
`seed` role. `--admin-only` is passed via an environment variable rather
than a command-line flag, since `flyctl machine run`'s own flag parser
would otherwise swallow a bare `--admin-only`:

```bash
IMAGE="$(flyctl machine list --app "$FLY_APP_NAME" --json | jq -r '.[0].config.image')"
flyctl machine run "$IMAGE" seed --env SEED_ADMIN_ONLY=1 --app "$FLY_APP_NAME" --rm
```

This creates only the admin user from `INITIAL_ADMIN_EMAIL`/
`INITIAL_ADMIN_PASSWORD` — no synthetic demo scan (that's what
`--admin-only` skips), which is what you want in production.

## 7. Verify

```bash
make fly-status                 # flyctl status + flyctl machine list
curl https://${FLY_APP_NAME}.fly.dev/health
make fly-scan-runner-test       # creates a real synthetic scan end-to-end
```

`fly-scan-runner-test` needs `APP_URL`, `SCAN_RUNNER_TEST_EMAIL`, and
`SCAN_RUNNER_TEST_PASSWORD` set (use the admin account from step 6). It
confirms the full loop for real: the API requests a Fly Machine, the
Machine claims and processes one scan, and it's cleaned up afterward.

## Point a custom domain at the app (optional)

```bash
flyctl certs create sitechecker.veritechdiligence.com --app "$FLY_APP_NAME"
# then add the DNS records flyctl prints, and update APP_URL accordingly
flyctl secrets set APP_URL="https://sitechecker.veritechdiligence.com" --app "$FLY_APP_NAME"
```

## Subsequent deploys

```bash
make fly-deploy
make fly-migrate   # only if this deploy changed the schema
```
