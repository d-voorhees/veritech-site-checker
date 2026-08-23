# Veritech Site Checker

**Evidence-linked technical pre-screening for web-based business acquisitions.**

Veritech Site Checker is a product of [Veritech Diligence](https://veritechdiligence.com). A user enters a public web domain, confirms they're authorized to assess it, and receives a structured, evidence-linked **Technical Acquisition Brief**: a prioritized risk register where every finding is traceable back to the exact evidence that produced it.

It answers one practical question for a prospective buyer of a web-based business:

> Is this web property worth deeper technical diligence, and what should I investigate next?

Current version: v1.10. Release history in [CHANGELOG.md](CHANGELOG.md). Build story: [A Technical Due Diligence Scanner for Web-Business Buyers](https://dvoorhees.com/2026/08/15/building-a-technical-due-diligence-scanner-for-web-business-buyers/). Live app: [sitechecker.veritechdiligence.com](https://sitechecker.veritechdiligence.com).

**At a glance**
- Stack: Next.js, FastAPI, PostgreSQL (Neon), Playwright/Chromium, Fly.io Machines
- Rules engine: 26 versioned, deterministic rules; zero LLM involvement in findings
- Compute model: an on-demand Fly Machine per scan, no persistent worker or queue
- Turnaround: a scan returns a full report in minutes

## What it does

Findings come from a deterministic, versioned rules engine reading a normalized evidence layer, not from a language model. The engine currently runs 26 rules across DNS and email posture, HTTP and security headers, crawl and indexability, technology and dependency exposure, TLS and domain registration, performance, and accessibility. Every rule's outcome shows in the report, not only the ones that fired, so a buyer can see what was checked as well as what was found.

## Architecture: two Fly Machine roles, one source of truth

Veritech Site Checker runs as a single Fly.io app with two Machine roles, built from one Dockerfile as two separate images: `web` (Chromium-free) and `scan-runner` (adds Playwright/Chromium), with the runtime role in each selected by `scripts/entrypoint.sh`. See the Dockerfile's top-of-file comment and `scripts/deploy-fly.sh` for how both get built and pushed. (The web/scan-runner split was originally an attempt to fix web cold-start latency. It didn't, see Known limitations, but it's kept since a Chromium-free web image is good practice regardless.)

**Web/API Machine.** Next.js + FastAPI, serving the browser and the API. Runs always-on (`min_machines_running = 1`, `auto_stop_machines = "off"` in `fly.toml`) rather than scale-to-zero; see Known limitations for why. It never runs a scan itself and never runs a permanent queue worker.

**Scan-runner Machine.** Created on demand, exactly one per scan, through the Fly Machines API (`apps/api/app/services/fly_machines.py`). It receives the scan ID via the `SCAN_ID` environment variable, claims the scan, runs every collection stage, persists evidence, findings, and events, sets the final status, and exits. The Machine is then destroyed (`config.auto_destroy = true`).

**Why on-demand instead of an always-on worker.** A scan's compute need is bursty and short: a few seconds up to `SCAN_MAX_TOTAL_MINUTES` (default 10). Running a worker continuously to handle that would mean paying for idle time between scans. There's no Redis, no Dramatiq, no Celery, and no persistent queue anywhere in this architecture. The API asks Fly to create a Machine per scan, and PostgreSQL, not memory and not a queue, is the single source of truth for scan status. The API layer only ever polls the database. Full flow and diagram in `docs/architecture.md`.

### Data flow

The database is a [Neon](https://neon.tech) Postgres project, external to the Fly app, reached over a TLS connection (`sslmode=require`) from whichever Machine needs it:

```
Browser
  │ HTTPS
  ▼
Web/API Machine (Fly, autostop/autostart)
  │ reads/writes scan state           │ POST /apps/{app}/machines
  ▼                                   ▼ (Fly Machines API)
Neon Postgres (external) ◄──────── Scan-runner Machine (Fly, on-demand)
  ▲ persists evidence/findings/events, then exits
  └───────────────────────────────────┘
```

Both Machine roles connect to the same Neon database independently; there's no proxy or connection-sharing between them. Fly and the database also scale and bill independently: both Machine roles scale to zero when idle, while Neon is the one component that's always provisioned (see Known limitations).

## Evidence first, rules second

Collector functions never decide that something is a finding. Five feed the pipeline: the HTTP/redirect checker, the DNS/email posture check, the crawler, the Playwright renderer, and the performance adapter. Each one only ever writes normalized `EvidenceItem` rows:

```python
class EvidenceItem(Base, UUIDMixin, TimestampMixin):
    """The normalized evidence layer. This, not raw responses, is the
    product's core data model. Every finding cites one or more of these.
    """
    category: Mapped[str]                  # e.g. "email_posture", "tls", "performance"
    source_type: Mapped[str]                # e.g. "http_response", "dns_txt", "playwright_render"
    source_url_or_identifier: Mapped[str]
    captured_at: Mapped[datetime]
    confidence: Mapped[str]                 # low | medium | high
    normalized_payload_json: Mapped[dict]
    human_readable_summary: Mapped[str]
```

A separate rules engine reads only from this evidence layer, never from a collector directly. That separation lets a finding cite the exact evidence behind it, with a visible chain back to what was actually observed.

Reproducibility matters for a tool a buyer is trusting: the same evidence has to produce the same finding every time, with a version number attached so a change in behavior shows up as a traceable code change. Each rule is a pure function returning a typed result:

```python
@dataclass
class RuleResult:
    rule_key: str
    version: int
    severity: str
    confidence: str
    title: str
    impact: str
    recommended_next_step: str
    dollar_impact: str          # rough band: $, $$, $$$ (no default)
    remediation_timing: str     # 30-day, 60-day, 90-day, longer-term (no default)
    evidence_ids: list[uuid.UUID]
```

`dollar_impact` and `remediation_timing` have no default value in that dataclass. A rule that forgets to set either one fails immediately in testing, before it can ship a finding with a blank column a buyer would have to guess the meaning of.

## The app

### Access and scanning

A public marketing homepage at `/`, branded to match veritechdiligence.com (type, color, layout), carries the primary call to action to start a scan. The authenticated app lives at `/dashboard`.

Signup is self-serve and passwordless: enter an email at `/login`, get a single-use magic link, and start scanning. No invite needed. Every scan is free for now: no payment processor, no enforced cap (a `scans_used` counter is tracked per user so a cap can be added later without a schema change). Password sign-in remains available for existing accounts.

Starting a scan means submitting a domain or URL, optional business notes, a crawl depth (10, 25, or 50 pages), and a required authorization acknowledgment.

An on-demand scan pipeline (no persistent worker, no Redis; see Architecture above) covers HTTP and redirect checks, robots.txt and sitemap discovery (cross-checked against the actual crawled page set), a bounded same-origin crawl, DNS/SPF/DMARC/DKIM posture, Playwright homepage rendering plus third-party dependency inventory, local rules-based technology detection, and a performance adapter (local metrics always, Google PageSpeed Insights optionally for both desktop and mobile when configured).

### The report

The report UI follows the order a buyer actually reads in: status and a task panel (with per-task and total generation timing), a risk summary, a collapsed-by-default rules-coverage table, and the prioritized risk register itself (severity, confidence, a rough dollar-impact band, and remediation timing per finding, with a linked legend). Below that: business continuity (domain registration, TLS certificate, HTTPS and redirect chain), HTTP and security headers, platform and stack (technology and CMS detection, third-party dependencies, hosting fingerprint, xmlrpc.php/wp-json exposure), crawl and indexability (including sitemap freshness), email posture, performance, accessibility, and known limitations. A clean HTML export is built for "Print → Save as PDF."

## What it doesn't do

Veritech Site Checker is not:

- A vulnerability scanner or penetration-testing tool.
- An access-control bypass, credential-testing, or exploitation system.
- A scraping proxy for arbitrary or bulk use.
- A source of confirmed vulnerabilities. Findings distinguish observation from interpretation, and a hardening opportunity from a confirmed vulnerability; the product never claims the latter.

Full list of technical non-goals (full robots.txt enforcement, high availability, etc.) in `docs/threat-model.md`.

## Local development

Prerequisites: PostgreSQL 16+ running locally, Python 3.12 (3.11 also works), and Node.js 22. No Docker, no Redis, and no Fly.io account are required for local development: starting a scan locally runs the same runner code as a plain background subprocess on your own machine instead of calling the Fly Machines API (see `request_scan_runner` in `apps/api/app/services/scan_orchestrator.py`).

Install Postgres with your platform's package manager (e.g. `brew install postgresql@16` on macOS, `sudo apt install postgresql` on Ubuntu), then create the database and role (still named `veritech_scan`, the project's original slug):

```bash
createdb veritech_scan
createuser veritech_scan --pwprompt   # set password to match .env
```

```bash
cp .env.example .env
# edit .env: DATABASE_URL defaults to 127.0.0.1; set the password to match
# the role you just created. Leave the FLY_* variables unset for local dev.

cd apps/api && python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt && playwright install chromium
cd ../web && npm install
cd ../..

make migrate       # alembic upgrade head
make seed          # creates the dev admin user + a synthetic demo scan
make dev           # starts uvicorn --reload and next dev together
```

Open http://localhost:3000 and sign in with `INITIAL_ADMIN_EMAIL` / `INITIAL_ADMIN_PASSWORD` from your `.env` (defaults: `admin@example.com` / `change-me`; change these even for local dev if your machine is at all shared).

`make dev` runs both processes in the foreground (Ctrl+C stops both). To run them separately instead (e.g. in different terminals):

```bash
cd apps/api && PYTHONPATH=. .venv/bin/uvicorn app.main:app --reload --port 8000
cd apps/web && npm run dev
```

## Environment configuration

All configuration is via environment variables; see [`.env.example`](./.env.example) for the full list with defaults, including product identity (`NEXT_PUBLIC_PRODUCT_NAME`, `PARENT_BRAND`, `APP_DOMAIN`, ...), scan safety limits (`SCAN_MAX_PAGES`, `SCAN_DEFAULT_REQUEST_DELAY_SECONDS`, `SCAN_MAX_TOTAL_MINUTES`, `SCAN_CREATE_RATE_LIMIT_PER_HOUR`, `SCAN_CREATE_RATE_LIMIT_PER_DAY`), and optional providers (`GOOGLE_PAGESPEED_API_KEY`, `SENTRY_DSN`). Never commit `.env` or any `.env.*` file; all are gitignored.

### Required Fly secrets (production only)

Set these with `flyctl secrets set`; see `docs/fly-deployment.md` for the full walkthrough of every value:

| Variable | Purpose |
|---|---|
| `FLY_APP_NAME` | The Fly app name; used by both `flyctl` commands and the app's own Fly Machines API calls. |
| `FLY_API_TOKEN` | Lets the API create scan-runner Machines. Server-side only, never sent to the browser. |
| `FLY_PRIMARY_REGION` | Region new scan-runner Machines are created in. |
| `DATABASE_URL` | The Neon Postgres connection string (`postgresql+psycopg://...?sslmode=require`), set by hand from the Neon dashboard/CLI, not by Fly. `FLY_DATABASE_URL` is an alternate name the app also accepts, for the (unused here) case of `fly postgres attach` setting it automatically instead. |
| `APP_URL` | The app's public URL. |
| `MARKETING_SITE_URL`, `NEXT_PUBLIC_PRODUCT_NAME`, `PARENT_BRAND` | Product identity shown in the UI/API. |
| `JWT_SECRET` | Session signing secret. |
| `INITIAL_ADMIN_EMAIL`, `INITIAL_ADMIN_PASSWORD` | Bootstrap admin account (`make seed`/`app.seed --admin-only`). |
| `GOOGLE_PAGESPEED_API_KEY` | Optional. Enables PageSpeed Insights metrics in the performance section. |
| `SENTRY_DSN` | Optional. Error reporting. |
| `BREVO_API_KEY` | Sends the magic-link email and the post-scan contact-attribute sync. Must be paired with a `BREVO_SENDER_EMAIL` that's a verified sender in the Brevo account. |
| `BREVO_SENDER_EMAIL`, `BREVO_SENDER_NAME` | Sender identity on every Brevo send. |
| `BREVO_MAGIC_LINK_TEMPLATE_ID` | Optional. A Brevo transactional template ID for the magic-link email. Unset falls back to plain inline HTML. |
| `MAILERLITE_API_KEY`, `MAILERLITE_GROUP_ID` | Adds a verified signup to this MailerLite group on first magic-link verification. |
| `SLACK_WEBHOOK_URL` | Optional. A Slack Incoming Webhook URL. Posts a notification on scan start and scan completion; unset means no notification is sent. |
| `RESULTS_NOTIFICATION_EMAIL` | Optional. Inbox that gets a full copy of each completed scan's report via Brevo. Unset means no email is sent. |

## Database requirements

PostgreSQL is the only persistent dependency: scan status, events, evidence, findings, and reports are all Postgres rows. There is no Redis and no other stateful service. Production uses [Neon](https://neon.tech) (project `veritech-scan`), external to Fly, not Fly's own Postgres offering. `app/config.py`'s `resolved_database_url` also accepts `FLY_DATABASE_URL` as a fallback name, which would let a future move to Fly Postgres (or any other provider) work by just changing the secret value, but nothing in this deployment relies on that today. See `docs/fly-deployment.md` for provisioning and `docs/fly-operations.md` for backup guidance.

## Migrations

```bash
make migrate                 # alembic upgrade head, using apps/api/.venv (local dev)
make fly-migrate              # same, against production, via a one-off Fly Machine
```

In production, migrations run automatically as the last step of the `Deploy` GitHub Actions workflow (`.github/workflows/deploy.yml`): a push to `main` that passes the test suite triggers `flyctl deploy`, then `./scripts/migrate-fly.sh` against the image just deployed. Use `make fly-migrate` by hand for anything outside that pipeline: a manual `make fly-deploy`, or a one-off fix.

To generate a new migration after changing SQLAlchemy models:

```bash
cd apps/api && .venv/bin/alembic revision --autogenerate -m "describe the change"
```

Review the generated file before committing; autogenerate is a starting point, not a guarantee.

## Seed data

```bash
make seed                    # admin user + fictional org + fully synthetic demo scan
make seed ARGS=--admin-only  # (or: cd apps/api && .venv/bin/python -m app.seed --admin-only)
```

The synthetic demo scan is clearly labeled everywhere it appears (`is_demo` flag on the organization and scan, `[SYNTHETIC DEMO DATA]` in its notes, a visible "Synthetic demo data" badge in the UI, and the same disclosure in the HTML export). It exists to let you see a fully populated report without running a real scan.

## Testing

```bash
make test           # backend pytest suite + frontend tests (if present)
make lint            # ruff + mypy (backend), eslint (frontend)
```

The backend suite (`tests/backend/`) covers URL normalization, SSRF/private-IP/redirect-revalidation protections, crawl URL filtering and max-page limits, SPF/DMARC/DKIM parsing, all 26 rules (firing and non-firing cases), finding-to-evidence linkage, the scan creation/retrieval API and ownership authorization, scan status transitions, duplicate-runner prevention, Fly Machine creation failure handling, partial-completion behavior after a simulated task failure, database-backed scan-event history, a real Chromium launch and render check, and one fully mocked end-to-end happy-path scan (`test_e2e_scan.py`). All Fly Machines API calls are mocked in tests. The test suite never needs Docker, Redis, Oracle, live Fly credentials, or a real Fly app.

`make test` runs `apps/api/.venv/bin/python -m pytest` from the repo root (picking up `pytest.ini`'s `testpaths = tests/backend`) against whatever `DATABASE_URL` is set in your environment/`.env`, then `npm run test --if-present` in `apps/web`. To point it at a dedicated test database instead of your dev one:

```bash
createdb veritech_scan_test
PYTHONPATH=apps/api DATABASE_URL=postgresql+psycopg://$(whoami)@localhost:5432/veritech_scan_test \
  apps/api/.venv/bin/python -m pytest tests/backend -q
```

## Running an authorized scan

1. Sign in.
2. **New scan.** Enter a domain or URL you own or are authorized to analyze, optional notes, a crawl depth (10/25/50 pages), and check the authorization acknowledgment (required; the form won't submit without it, and the API rejects the request server-side too).
3. You're redirected to the scan's status page, which polls automatically while the scan is `queued`/`starting`/`running` and shows each collection task's status live.
4. Once `completed` or `completed_with_warnings`, review the risk register, click into any finding to see its exact linked evidence, and use **Export HTML report** for a print-ready Technical Acquisition Brief.

## Safety boundaries

Summarized here; full detail in `docs/threat-model.md`:

- Only `http`/`https`, only public IPs (loopback/private/link-local/multicast/reserved/cloud-metadata all rejected, before and after every redirect).
- Same-origin crawl only, excluding login/admin/cart/checkout/API paths, static assets, and non-http(s) schemes.
- Hard page-count cap (10/25/50), 1.5s/request delay, 15s/page timeout, 10-minute total scan timeout.
- Never submits forms, authenticates, solves CAPTCHAs, or bypasses access controls.
- Ephemeral browser context per scan; no cookie/session persistence.
- Scan creation is rate-limited per user: 10/hr as a burst guard, and 3/day (rolling 24h) as the real cap now that scans are free and self-serve. A signed-in user sees their live `X / Y scans today` count in the app header (`GET /auth/me`); hitting the daily cap returns a message pointing them to danielle@veritechdiligence.com to discuss more usage. Magic-link requests are rate-limited per IP (5/hr) to prevent using signup as an email-spam vector.

## Known limitations

- **Web/API cold starts.** The web/API Machine runs always-on (`min_machines_running = 1`, `auto_stop_machines = "off"` in `fly.toml`), not scale-to-zero. A 2026-08-13 investigation found cold starts here ran roughly 13 to 18 seconds regardless of VM size, image size, or region, pointing to a fixed Fly platform boot cost rather than anything fixable app-side. Always-on trades a small continuous compute cost for eliminating that wait entirely. It runs on the smallest VM tier (`shared-cpu-1x`/256mb) since a bigger VM didn't help the cold start anyway; watch for OOM restarts under real traffic as the first sign that tier is too small for steady-state load.
- **Scan-runner cold starts.** Every scan waits for its Fly Machine to boot before processing starts; there's no "warm" runner. These remain scale-to-zero since they only run for the duration of a scan.
- **One scan per runner.** Each scan gets its own Machine; there is no batching or sharing, by design (see Architecture above).
- **The database is a persistent, paid dependency**, billed and managed separately from Fly (a different provider, a different invoice). Neon Postgres doesn't scale to zero at the tier this project uses.
- **No enforced scan cap.** `scans_used` is tracked per user but nothing currently reads it to block a scan. Every scan is free for now; there is no payment processor or paywall.
- **Finite scan resource/time limits.** `SCAN_MAX_TOTAL_MINUTES` (default 10) and the 10/25/50 page caps bound every scan; browser rendering covers the homepage only, not every crawled page.
- `robots.txt` is not enforced against the crawler, but the crawled page set is cross-referenced against robots.txt `Disallow` rules and the declared sitemap, both reported in the Crawl and indexability section.
- DKIM discovery is best-effort: it probes 16 common ESP-default selectors (Google Workspace, Microsoft 365, Mailchimp, SendGrid, etc.) rather than the domain's actual selector, which isn't discoverable without an authenticated mail sample. A miss is not proof of absence.
- Google PageSpeed Insights metrics only appear when `GOOGLE_PAGESPEED_API_KEY` is configured; otherwise the report says so explicitly rather than silently omitting the section.

## Fly.io deployment

Full step-by-step in [`docs/fly-deployment.md`](docs/fly-deployment.md); day-two operations (logs, failed scans, cleaning up Machines, secret rotation) in [`docs/fly-operations.md`](docs/fly-operations.md). Short version: no Docker or Docker Desktop required on your machine, since `fly deploy --remote-only` builds on Fly's own infrastructure:

```bash
export FLY_APP_NAME=veritech-scan
flyctl auth login
make fly-init                # create the app
# create a Neon project, get its connection string, and set every secret
# listed above (DATABASE_URL included): see docs/fly-deployment.md
make fly-deploy               # fly deploy --remote-only
make fly-migrate              # alembic upgrade head, via a one-off Fly Machine
make fly-status                # app + Machine status
make fly-scan-runner-test       # creates a real synthetic scan end-to-end
```

### Inspecting failed scans

Query `scan_requests`/`scan_events` directly, or use the API (`GET /scans/{id}`, `GET /scans/{id}/events`); see `docs/fly-operations.md`'s "Inspecting a failed scan".

### Inspecting and cleaning up stopped scan-runner Machines

```bash
flyctl machine list --app "$FLY_APP_NAME"
flyctl machine destroy <machine_id> --app "$FLY_APP_NAME" --force
```

Scan-runner Machines self-destruct after a scan (`config.auto_destroy`); Fly keeps a Machine around for roughly 2 hours after a non-zero exit specifically so you can inspect it before it's cleaned up automatically. See `docs/fly-operations.md` for detail.

## License

Proprietary. All rights reserved. Veritech Site Checker is a commercial product of [Veritech Diligence](https://veritechdiligence.com); this source is not licensed for reuse, redistribution, or derivative works.

The rules engine's actual rule catalog (every detection condition, threshold, and the dollar-impact/remediation-timing methodology) lives in a separate private package (`veritech-scan-rules`), not in this repo. This app depends on it like any other pip package; it isn't publicly installable. See [`docs/rules-engine.md`](docs/rules-engine.md) for the architecture this plugs into.

## Changelog

See [`CHANGELOG.md`](CHANGELOG.md) for notable fixes and changes.

## Documentation index

- [`docs/architecture.md`](docs/architecture.md): system diagram, why scan-runners are on-demand Fly Machines instead of a persistent worker, the full scan initiation flow, collection/evidence/rules/report flow.
- [`docs/rules-engine.md`](docs/rules-engine.md): rule architecture, the versioning scheme, how to add a rule safely, and why the actual rule catalog is a private dependency, not in this repo.
- [`docs/threat-model.md`](docs/threat-model.md): SSRF prevention, crawl boundaries, authorization, isolation, rate limiting, explicit non-goals.
- [`docs/fly-deployment.md`](docs/fly-deployment.md): exact Fly.io initial setup and deployment commands.
- [`docs/fly-operations.md`](docs/fly-operations.md): logs, failed-scan inspection, scan-runner Machine cleanup, secret rotation, cost notes.
- [`docs/security-hardening.md`](docs/security-hardening.md): what's already hardened and what to add before handling real client data.
- [`deploy/fly/README.md`](deploy/fly/README.md): quick command reference for the Fly deployment.