# Changelog

All notable changes to this project are documented in this file.

## v1.10 — 2026-08-21

### Fixed

- **One bad rule result could silently wipe out every finding in a scan.**
  `run_rules_engine` (`apps/api/app/rules/engine.py`) flushed each `Finding`
  row in the same open transaction with no isolation between rules — when a
  single rule returned a result that violated a DB constraint (seen in
  production: a rule left `dollar_impact` null), the whole transaction
  aborted and every finding from rules that had already fired correctly
  earlier in the same run was discarded along with it, silently producing a
  0-finding `completed_with_warnings` scan. Each rule's finding is now
  persisted inside its own savepoint (`db.begin_nested()`); a bad result is
  logged and skipped without affecting any other rule.
- **Scan-completion notification outcomes are now queryable, not just
  logged.** The Slack "Scan Completed" alert and the results-copy email
  (`apps/api/app/runner/run.py`) previously reported failure only via
  `logger.warning`, which lives in an ephemeral log buffer — after the
  fact there was no way to tell whether a given scan's alert actually
  fired. Both now also record a `ScanEvent` (`slack_completion_notification_sent`/`_failed`,
  `results_email_sent`/`_failed`/`_skipped`, `brevo_scan_summary_sync_failed`)
  so the outcome is permanently attached to the scan.

## v1.9 — 2026-08-20

### Added

- **First-time magic-link users are prompted to set a password.**
  `GET /auth/me` now returns `has_password`, and a new
  `POST /auth/set-password` (`apps/api/app/api/v1/auth.py`) lets an
  authenticated user set one — only once, since it 400s if
  `hashed_password` is already set. Password strength is checked
  server-side (`password_strength_error` in
  `apps/api/app/security/passwords.py`): at least 10 characters, with
  both a letter and a number. On the frontend, `AppShell` renders a
  blocking `SetPasswordPrompt` (`apps/web/src/components/set-password-prompt.tsx`)
  over every authenticated page for any signed-in user with
  `has_password === false`, so a magic-link user sets a password the
  first time they land on the dashboard. Once set, they can sign back in
  either through a new magic link or the existing password form on
  `/login`.

## v1.8 — 2026-08-20

### Changed

- **Dashboard now guides first-time users toward their first scan.**
  `apps/web/src/app/dashboard/page.tsx` previously showed the same stats
  grid (Total scans / In progress / Product) and empty "Recent scans" list
  to everyone, including a signed-in user who had never run a scan. When
  `scans.length === 0`, the dashboard now replaces both with a single
  onboarding card — a "Run your first scan" headline, a short explainer of
  what a scan produces, a prominent "Start your first scan" CTA, and a
  preview of the six check categories (site behavior and redirects, email
  and domain posture, crawl and structure, technology stack, third-party
  dependencies, performance) — so a new user's dashboard sets expectations
  instead of showing all-zero stats and "No scans yet." The header's
  redundant "New scan" button is hidden in this state since the CTA already
  covers it; once a user has any scans, the dashboard reverts to the normal
  stats-and-recent-scans view.

## v1.7 — 2026-08-20

### Added

- **Daily scan cap, plus a visible usage counter.**
  `enforce_scan_creation_rate_limit` (`app/core/rate_limit.py`) now checks a
  rolling-24h count per user against `SCAN_CREATE_RATE_LIMIT_PER_DAY`
  (default 3) in addition to the existing rolling-1h burst guard
  (`SCAN_CREATE_RATE_LIMIT_PER_HOUR`, default 10). Hitting the daily cap
  returns a 429 with a message pointing the user to
  danielle@veritechdiligence.com to discuss more usage. `GET /auth/me` now
  also returns `scans_used_today` / `scan_daily_limit`, and the app header
  shows a live `X / Y scans today` counter for every signed-in user (shared
  React Query cache, no extra request).

## v1.6 — 2026-08-19

### Added

- **Self-serve, passwordless signup — free-launch pass, no invite required.**
  Replaces the invite-only entry point (there was no technical gate to tear
  out — accounts were only ever created by hand — so this is additive, not a
  removal). `POST /auth/request-link` looks up or creates a user by email and
  emails a single-use magic link (`POST /auth/verify` redeems it); tokens are
  SHA-256-hashed at rest (`magic_link_tokens`, migration `b8a2f5d13c90`),
  20-minute expiry, single-use regardless of expiry, and the request endpoint
  is rate-limited per IP (5/hr) to prevent using it to spam arbitrary
  addresses. Password sign-in still works for the existing admin account
  (`/login`'s "Sign in with a password instead" toggle) — `users.hashed_password`
  is now nullable for magic-link-only accounts. Every scan is free for this
  pass; no payment processor or scan cap was added. A `scans_used` counter is
  tracked on each user (incremented per scan, `scan_orchestrator.create_scan`)
  so a cap can be wired in later without another schema change — nothing
  currently reads it to block anything.
- **First Brevo integration in this codebase.** `app/services/brevo_client.py`
  sends the magic-link email (Brevo template if `BREVO_MAGIC_LINK_TEMPLATE_ID`
  is set, otherwise a plain inline-HTML fallback so the flow is testable
  before a template exists) and, on scan completion, pushes a lean summary to
  the user's Brevo contact record as attributes (`LAST_SCAN_URL`,
  `LAST_SCAN_DATE`, `LAST_SCAN_RISK_LEVEL`, `LAST_SCAN_TOP_FINDING`,
  `LAST_SCAN_FINDING_COUNT_RED`, `LAST_SCAN_FINDING_COUNT_YELLOW`) to drive an
  existing post-report email automation. The summary is also persisted
  (`reports.brevo_summary_json`) so it never needs recomputing. Risk level
  and the red/yellow split are new derived logic (high→red, medium→yellow) —
  nothing in the report schema previously carried an "overall risk" concept.
  A Brevo failure never blocks the scan or the auth response; it's logged and
  left to retry out of band.
- **MailerLite group sync.** On a user's *first* successful magic-link
  verification (never on link request, so unverified/mistyped addresses
  never reach MailerLite), `app/services/mailerlite_client.py` upserts the
  contact into the configured group without disturbing any other group
  membership, and stamps `users.mailerlite_synced_at`.
- **Slack notifications for scan start and scan completion**, plus a full
  results-copy email. Both post/send from `app/services/scan_orchestrator.py`
  (scan created) and `app/runner/run.py` (scan completed, alongside the
  Brevo push), each independently try/excepted so a Slack or email outage
  never affects the scan itself. Messages lead with a bold "VERITECH SITE
  CHECKER" title line so they're unmistakable in a shared channel. The
  completion email sends the full rendered report HTML to one configured
  inbox (`RESULTS_NOTIFICATION_EMAIL`) via the same Brevo client.
- New env vars (see `.env.example`, and the README's Fly secrets table):
  `MAGIC_LINK_TOKEN_EXPIRES_MINUTES`, `MAGIC_LINK_REQUEST_RATE_LIMIT_PER_HOUR`,
  `BREVO_API_KEY`, `BREVO_SENDER_EMAIL`, `BREVO_SENDER_NAME`,
  `BREVO_MAGIC_LINK_TEMPLATE_ID`, `MAILERLITE_API_KEY`, `MAILERLITE_GROUP_ID`,
  `SLACK_WEBHOOK_URL`, `RESULTS_NOTIFICATION_EMAIL`. Passwordless sessions
  reuse the existing `JWT_SECRET`/`APP_URL` rather than adding a second
  session secret or base-URL variable for the same purpose.

## v1.5 — 2026-08-18

### Changed

- **Rule catalog extracted to a private package.** The rules engine's
  detection logic — every rule's condition, threshold, and dollar-impact/
  remediation-timing assignment — moved out of this repo into a separate
  private package, `veritech-scan-rules`, pulled in as a normal pip
  dependency (`apps/api/requirements.txt`, pinned to a tag). No behavior
  change: `RuleContext` now carries every piece of evidence a rule might
  need as plain pre-fetched data (several rules previously queried the
  database directly), so rule functions have zero dependency on this app's
  models or database — see `docs/rules-engine.md`'s "Private rule catalog"
  section for the full architecture and how each environment (local, CI,
  Fly build) authenticates to install it.
- **CI hardened against silent hangs.** Rolling out the private-package
  dependency above surfaced two real CI problems on the same day: `git`
  wasn't installed in the Dockerfile's base image (the private dependency
  couldn't resolve during the Fly build), and GitHub's default
  `azure.archive.ubuntu.com` apt mirror hung for 20-30+ minutes mid-`test`-job
  with nothing bounding how long a step could run. Fixed all three:
  `.github/workflows/deploy.yml` now points apt at the standard Ubuntu
  mirror before any apt-get call, caches the Playwright Chromium binary
  (`actions/cache`, keyed on `requirements.txt`) so most runs skip that
  network download entirely, and sets `timeout-minutes` at both the job
  level (`test`: 20, `deploy`: 25) and specifically on the install step that
  hung (5) — so a stuck step now fails loudly within minutes instead of
  silently for half an hour. The Dockerfile's `runtime-base` stage installs
  `git` alongside its existing `curl`/`ca-certificates`/`gnupg` packages.

## v1.4 — 2026-08-13

### Added

- **Dollar impact and remediation timing on every finding.** The risk
  register's Severity/Finding/Category/Confidence columns now also show a
  rough dollar-impact band (`$`/`$$`/`$$$`) and a suggested remediation
  timing (`30-day`/`60-day`/`90-day`/`longer-term`), both set by the rule
  itself, never the reader. `Finding` gained `dollar_impact` and
  `remediation_timing` columns (migration `c3e9a1f7b214`); `RuleResult`
  makes both **required, no-default** fields, so a rule that forgets one
  fails immediately instead of shipping a half-labeled finding. All 26
  rules set both. A few findings (`domain_registration_expiring_soon`,
  `tls_certificate_expiring_or_expired`) intentionally band at `$$$`
  regardless of severity — the direct fix is cheap, but the cost of
  inaction (losing the domain or breaking HTTPS entirely) is severe.
  Methodology documented in `docs/rules-engine.md`.
- **Severity/confidence legend.** A short, linked legend now explains what
  each severity level, confidence level, dollar-impact band, and
  remediation-timing value means — a non-technical reader previously had
  no way to tell why one finding was "medium confidence" and another "high."
- **Redirect chain display and flagging.** The report now shows the full
  redirect chain that got a scan from the requested URL to the final one
  (`http_observations.redirect_chain` was already collected but never
  rendered), and flags chains longer than one hop or that mix http/https
  schemes with a "worth a look" badge.
- **Sitemap freshness.** `<lastmod>` dates are now parsed from every
  sitemap entry (`robots_sitemap.py::_parse_sitemap_xml`/`_summarize_lastmods`)
  and the newest/oldest values shown under Crawl and indexability — a
  sitemap untouched in years is itself a maintenance signal. No new
  collector needed; the sitemap was already being fetched.
- **Hosting fingerprint.** `Server`, `X-Powered-By`, `cf-ray`, and similar
  hosting/infra headers are now surfaced verbatim under Platform and stack
  (no rule fires on this — it's context, not a finding).
- **Platform/CMS detection as its own signal.** Technology detection
  previously only ever reported the libraries/analytics running *on top of*
  a site, never the platform itself. `report_builder._detect_platform` now
  picks the highest-confidence CMS/ecommerce-platform/website-builder/
  headless-CMS/static-site-framework match, or — when none of those fired —
  falls back to a "looks like static HTML" heuristic from the crawled URLs
  (e.g. correctly identified mediumandmessage.com, which has no CMS, as a
  static HTML site).
- **LCP-specific rules, independent of the overall PageSpeed score.**
  `lcp_poor_mobile` and `lcp_poor_desktop` now fire on Largest Contentful
  Paint alone (standard thresholds: good ≤2.5s, needs improvement 2.5-4s,
  poor >4s), catching the case where a real ~6s mobile LCP passed unnoticed
  because the overall mobile Performance score (73) was above the
  `pagespeed_mobile_below_50` threshold.

### Changed

- **Report reordered around acquisition-relevant questions, not collector
  build order.** New order after the risk register: **Business
  continuity** (domain registration + TLS certificate + HTTPS/final-URL/
  redirect chain, grouped under one heading — "will this still be here in
  60 days") → HTTP and security headers → **Platform and stack**
  (technology/CMS, third-party dependencies, xmlrpc.php/wp-json exposure —
  "what am I inheriting") → Crawl and indexability → **Email posture**
  (renamed from "DNS and email posture," domain registration moved out) →
  Performance → Accessibility → Known limitations. Applied to both the
  HTML export (`report.html.jinja`) and the dashboard
  (`apps/web/.../scans/[scanId]/page.tsx`).
- **Rules-coverage table collapsed by default.** The 26-row table (was
  sitting uncollapsed between the risk summary and the risk register,
  interrupting the read) now renders inside a `<details>` labeled "26
  rules checked, N raised a finding or observation — expand for the full
  list," open on demand.
- **"info" severity split: positive observations no longer share a label
  with real (if mild) risks.** Added a fifth severity, `ok`
  (`REGISTER_SEVERITIES` in `app/models/finding.py`), for findings that are
  themselves good news — currently only `dkim_selector_found`. `ok`-severity
  findings still fire and still show in the rules-coverage table (styled as
  "positive"), but `report_builder.build_report` excludes them from the
  risk register and its severity counts. `wp_json_rest_api_exposed` (a mild
  negative) stays at `info` and keeps appearing in the register.
- **Known limitations consolidated.** Three identically-labeled "General:"
  notes (which read as the same note repeated three times) are now one
  lead sentence naming what the scan is (bounded, rate-limited, public-web
  pre-screen) followed by the specific caveats as a short, unlabeled list.
  `ReportOut` gained a `scope_statement` field.
- **Friendlier phrasing reused in the register.** Where a report section
  already had a clearer phrasing of a fact than the register did (e.g.
  Accessibility's "Form fields with labels: 0 of 7" vs. the register's "7
  of 7 ... missing an associated label (100%)"), the register now uses it.
- **Robots.txt Disallow rules: friendlier empty state.** Shows "No Disallow
  rules declared" instead of a bare "none" next to the row label.

### Fixed

- **DMARC record with no `p=` tag silently passed as OK.**
  `dmarc_policy_none` (now **v2**) only checked `dmarc_policy != "none"`,
  which is true for a missing tag too — so a malformed record like
  `v=DMARC1;` (no policy tag at all, functionally equivalent to no DMARC
  record) never fired anything and the "DMARC policy stronger than
  monitor-only" check read as passing. Reproduced live against
  mediumandmessage.com's actual DMARC record. Now fires at `medium`
  severity ("DMARC record is malformed — no policy (p=) tag found"),
  strictly worse than a well-formed `p=none` (`low`).
- **Sitemap cross-check false-positived on `/index.html` vs. `/`.**
  `https://example.com/index.html` was flagged "crawled but not declared
  in sitemap" even when the sitemap already declared `/`, because the
  comparison only normalized trailing slashes, not index-file URLs.
  `report_builder._path_key` now also collapses `/index.html`/`/index.htm`
  to `/`, symmetrically for both the "crawled but not in sitemap" and
  "in sitemap but not crawled" directions.
- **TTFB values near zero looked like a measurement bug.** A PageSpeed
  Insights "server response time" of 1-2ms is almost always a cached/edge
  response, not a broken measurement. Added an explanatory caption under
  the performance table instead of leaving the number unexplained.

## v1.3 — 2026-08-13

### Changed

- **Third-party dependencies: no more duplicate vendor rows.** A vendor
  served from more than one hostname (e.g. Meta Pixel from both
  `facebook.net` and `connect.facebook.net`) previously got a separate
  table row per hostname, all labeled with the same vendor name.
  `report_builder.py` now groups rows by known vendor name (falling back
  to hostname when the vendor is unrecognized), merging hostnames and
  summing request counts into one row. The "N distinct domains observed"
  count is now tracked separately (`hostname_count`) so it still reflects
  the real number of hostnames seen, not the post-merge row count.
- **Added Google Fonts and Cal.com to the known-vendor list.**
  `fonts.googleapis.com`/`fonts.gstatic.com` now resolve to "Google
  Fonts" and `cal.com` (including `app.cal.com`) to "Cal.com" instead of
  showing as uncategorized (`dependency_classification.py`).
- **Page speed performance: dropped INP and CLS, trimmed LCP/FCP
  precision.** Removed the INP and CLS rows from the PageSpeed table
  (HTML export and dashboard). LCP and FCP now render to 3 decimal
  places instead of Lighthouse's raw floating-point value.
- **Renamed two jargon-y section headers.** "Collection tasks" →
  "Scan Collection tasks"; "Rules engine coverage" → "All checks &
  findings," with its description rewritten in plainer language (also
  removed em dashes) in both the HTML export and the dashboard.
- **Accessibility results didn't signal that missing alt text/labels are
  problems.** "8 of 10 images with alt text" read as a neutral stat, not
  a finding that needs action. Both the HTML export and dashboard now
  flag any nonzero missing count with a visible "N missing — needs fix"
  badge/label alongside the existing count.
- **Profile icon hover state didn't match the sign-out button next to
  it.** The nav's profile link only changed text color on hover, while
  the adjacent sign-out button (a ghost-variant `Button`) also got a
  `bg-muted` background — inconsistent affordance for two buttons in the
  same cluster. Profile link now uses the same rounded `hover:bg-muted`
  treatment (`app-shell.tsx`).

## v1.2 — 2026-08-13

### Added

- **Report generation timing.** The scan detail page's "Collection tasks"
  card now shows how long each task took to run, plus a "Total report
  generation time" row once the scan finishes. No backend changes were
  needed — `ScanJob.started_at`/`finished_at` were already recorded and
  returned by the API; this just surfaces them. New `formatDuration()`
  helper in `apps/web/src/lib/utils.ts`.

### Fixed

- **Collection tasks card described a stale, smaller rule catalog.** The
  per-task descriptions and count (`(4 of 13 checks)`, etc.) were written
  when the rules engine had 13 rules; it has since grown to 24
  (`RULE_CATALOG` in `rules/definitions.py`) and several tasks now feed
  checks their label never mentioned — `robots_sitemap` also drives the
  xmlrpc.php/wp-json exposure checks, `dns_email_posture` also drives
  domain-registration expiry, `browser_render` also drives three
  accessibility checks plus mixed-content detection, `http_checks` also
  drives TLS certificate expiry, and `technology_detection` (previously
  labeled purely informational) drives the no-analytics-detected check.
  Rewrote each task's description in `TASK_AREA_MAP`
  (`apps/web/src/app/scans/[scanId]/page.tsx`) to list what it actually
  feeds, and dropped the "(N of 13 checks)" counts — the live "Rules
  engine coverage" table below already shows the real, current total, so
  a second, hardcoded count in the task list served no purpose and would
  only go stale again. Corrected the matching "13 rules"/"all 13 rules"
  references in `README.md` to 24.

## v1.1 — 2026-08-12

### Added

- **Rules engine coverage in every report.** The report previously only
  listed rules that fired — a rule that checked cleanly left no trace, so
  there was no way to see that the deterministic engine actually ran all
  13 rules. Added a static `RULE_CATALOG` (`rules/definitions.py`)
  describing what each rule checks, cross-referenced against a scan's
  actual findings in `report_builder._build_rules_checked()`. Every
  report now shows a "Rules engine coverage" table (HTML export and
  dashboard): all 13 rules, what each one checks, and its outcome — fired
  with severity, or "No finding raised." Also added the DKIM rule's first
  test coverage (`tests/backend/test_rules_engine.py`), which had none.
- **Crawl cross-checked against robots.txt and sitemap.** "Crawl and
  indexability" now reports three things the previous version never
  compared: pages the crawl reached that aren't declared in the sitemap,
  sitemap URLs that weren't reached within the scan's page budget, and
  (informational only, since this scan has never enforced robots.txt)
  pages reached despite matching a `Disallow` rule for `User-agent: *`.
  `robots_sitemap.py` now parses robots.txt Disallow rules and retains the
  full sitemap URL list (previously capped at a 10-URL sample); the
  comparison itself is new in `report_builder._build_sitemap_check`.
- **DKIM discovery.** `dns_checks.py` probes 16 common ESP-default
  selectors (Google Workspace, Microsoft 365, Mailchimp, SendGrid, etc.)
  against `<selector>._domainkey.<domain>` and surfaces any hits in the DNS
  and email posture table plus a new informational
  `dkim_selector_found` rule. A miss is reported as "not proof of
  absence" rather than a false negative, since DKIM — unlike SPF/DMARC —
  has no fixed, well-known record location. Adds `dkim_selector` to
  `dns_observations` (migration `20fcb897e807`).
- **Third-party dependency listing.** The "Third-party dependencies"
  section (previously just a bare count buried in Performance) now lists
  every hostname observed while rendering the homepage, with request
  count, category, and — for ~35 well-known vendors including Meta Pixel,
  Google Analytics/Tag Manager, Stripe, HubSpot, and Intercom — a friendly
  vendor name (`dependency_classification.py`), in both the HTML export
  and the dashboard.
- **Desktop and mobile PageSpeed Insights scores.** The performance
  section, renamed **"Page speed performance,"** now fetches both
  `strategy=desktop` and `strategy=mobile` runs from PageSpeed Insights
  instead of only mobile, and reports Performance/Accessibility/Best
  Practices/SEO scores plus Core Web Vitals for each side by side.
  `PerformanceObservation` gained `desktop_*`/`mobile_*` columns replacing
  the old unprefixed (silently mobile-only) ones (migration
  `a00440335fda`). Lighthouse's new experimental "Agentic Browsing"
  category was investigated and left out for now — confirmed against
  Google's PSI API reference that it isn't exposed by the hosted API yet.
- **CI/CD: push-to-deploy on `main`.** `.github/workflows/deploy.yml` runs
  the full backend (ruff/mypy/pytest) and frontend (eslint/tsc/tests) suite
  on every push to `main`, then — only if that passes — runs
  `flyctl deploy --remote-only`, then `./scripts/migrate-fly.sh` against the
  image just deployed. Migrations are no longer a manual post-deploy step
  in the normal push-to-main flow; `make fly-migrate` remains available for
  out-of-band deploys (e.g. a manual `make fly-deploy`).
- **Public marketing homepage and brand styling.** `/` now renders a
  Veritech Diligence-branded landing page (hero, product explanation, check
  categories, access section) with "Sign in" and "Request access" calls to
  action; the authenticated dashboard moved to `/dashboard`. The login page
  and dashboard were restyled to match veritechdiligence.com's type and
  color system (Inter / JetBrains Mono / Linden Hill, ink/paper/parchment/
  navy palette, sharp corners).

### Changed

- **Docs brought back in sync with the code.** README (rule count 12→13,
  DNS posture description now includes DKIM, non-goals list no longer
  claims DKIM is out of scope, known-limitations wording rewritten to
  match the actual DKIM/robots.txt behavior, test-coverage claim now
  accurate), `docs/threat-model.md` (removed the stale "DKIM discovery is
  a non-goal" bullet, updated the robots.txt non-goal to describe the new
  sitemap/Disallow cross-check), and `docs/rules-engine.md` (added
  `dkim_selector_found` to the rules table, documented `RULE_CATALOG`) —
  all previously described a pre-DKIM, pre-sitemap-cross-check, 12-rule
  version of the product.
- **Landing page technology-stack row.** The "What it checks" table's
  Technology stack description now lists the specific categories detected
  (CMS/website-builder, e-commerce, frontend frameworks, analytics/tag
  managers, advertising/email marketing, support/chat, payments,
  CDN/hosting, fonts/JS libraries, consent management, forms/scheduling,
  search, captcha, embedded video/maps) instead of a one-line summary.
- **Known-limitations text.** Removed the "Google PageSpeed Insights
  metrics are only present when configured" line; rewrote the DKIM line
  to describe the new best-effort selector-probing scope instead of
  claiming DKIM isn't assessed at all; rewrote the robots.txt line to
  describe the new sitemap/Disallow cross-check instead of just stating
  robots.txt isn't enforced.
- **Replaced the Oracle Cloud/systemd/Caddy/Dramatiq+Redis deployment with
  Fly.io.** The app now deploys as one Fly app with two Machine roles: an
  always-deployed web/API Machine (Next.js + FastAPI, autostop/autostart,
  `min_machines_running = 0`) and on-demand scan-runner Machines created
  per scan via the Fly Machines API, which exit and self-destruct when the
  scan finishes. There is no persistent worker and no Redis/Dramatiq/Celery
  anywhere in the stack; scan status, events, evidence, findings, and
  reports all live in PostgreSQL, and the API polls the database rather
  than holding queue/worker state in memory. Added `starting` and
  `cancelled` to the scan status lifecycle, plus `runner_machine_id`,
  `heartbeat_at`, and `retry_count` tracking on `scan_requests`. Rate
  limiting moved from a Redis counter to a Postgres query. See
  `docs/architecture.md` and `docs/fly-deployment.md`.
- **Collection tasks list didn't map to the 13 checks it feeds.** The
  "Collection tasks" card on the scan detail page listed raw pipeline
  stage names (`http_checks`, `dns_email_posture`, ...) with no visible
  link to what they actually investigate, which read as inconsistent with
  the "Rules engine coverage" table's 13 checks below it. Each task now
  shows a one-line description of the check category and count it feeds
  (e.g. "Email deliverability — SPF, DMARC, DKIM (4 of 13 checks)"),
  sourced from the same `RULE_CATALOG` the rules-coverage table reads.

### Fixed

- **Crawl/indexability double-counted trailing-slash URL variants.**
  `/privacy` and `/privacy/` were treated as separate pages when both
  spellings were discovered while crawling, double-counting the same
  page. The crawler (`crawler.py`) now dedupes against a trailing-slash-
  normalized key while still fetching and recording whichever URL variant
  was first discovered.
- **False-positive WooCommerce detection.** The detector matched the bare
  substring "woocommerce" anywhere in a page's HTML, so pages that merely
  *mention* WooCommerce in marketing copy (e.g. describing it as a
  service the business supports) were flagged as running it. Now requires
  actual WooCommerce fingerprints — plugin asset paths, the
  `woocommerce_params` JS object, WooCommerce CSS classes, or the
  `wc-ajax=` endpoint (`technology.py`).
- **Technology tables in the HTML export had inconsistent column
  widths.** Each technology category (analytics, cdn security, marketing,
  ...) rendered as its own `<table>` with browser-computed auto layout,
  so columns didn't line up between categories. Gave them a shared
  `.tech-table` class with fixed 30/50/20% column widths.
- `apps/api/.env` and `apps/web/.env` symlinks to the repo-root `.env`.
  Pydantic-settings (`apps/api/app/config.py`) and Next.js both resolve
  `.env` relative to their own working directory, but `make migrate`,
  `make seed`, and `make dev` all `cd` into `apps/api`/`apps/web` before
  running. Without the symlinks, the root `.env` was silently ignored and
  commands fell back to `config.py`'s hardcoded defaults — including a
  `postgres` hostname that only resolves inside Docker — causing
  `make migrate` to fail with `nodename nor servname provided, or not
  known` even when a correctly filled-out root `.env` was present.
- **Crawl stopped after 1 page whenever the site redirected between apex
  and `www`.** `hostname` comparisons in the crawler and crawl policy used
  strict string equality, so a target entered as `example.com` that
  redirects to `www.example.com` (or vice versa) tripped the
  off-origin-redirect guard on the very first request: the homepage body
  was never fetched, no links were discovered, and the crawl ended having
  fetched exactly 1 page regardless of the selected page budget (10/25/50).
  Added `is_same_origin_hostname()` (`crawl_policy.py`), which treats
  `www.` and the bare apex domain as the same origin, and applied it to
  the redirect-follow check and internal-link classification in
  `crawler.py` in addition to `is_crawlable_url`.
- **Third-party dependency count inflated by the same www/apex mismatch.**
  `browser_render.py`'s third-party classification still compared hostnames
  with strict string equality, so a same-site request served from `www.`
  (when the scan target was the bare apex, or vice versa) was miscounted
  as a third-party dependency — inflating that count and risking a false
  `excessive_third_party_domains` finding. Now reuses the same
  `is_same_origin_hostname()` helper.
- **Technology detection missed real, positively-identified stacks (e.g.
  WordPress/WooCommerce sites behind a CDN or bot-challenge page).**
  Detection only ever scanned the raw pre-JS HTTP response
  (`http_checks`'s `html_text`), which optimizers like Cloudflare Rocket
  Loader (which defers/rewrites `<script>` tags) or a JS-gated
  bot-protection challenge can strip of every fingerprint before a real
  browser ever executes anything. `browser_render.py` now captures the
  fully rendered DOM (`page.content()`) and `technology.py`'s
  `run_technology_detection` scans it — plus a robots.txt excerpt, which
  often reveals platform-specific paths (e.g. `Disallow: /wp-admin/`) even
  when the page itself doesn't — alongside the raw response. Combining
  sources only widens what can be found; each rule still fires at most
  once regardless of how many needles match.
- **Desktop PageSpeed Insights scores were silently blank while mobile
  populated.** `GooglePageSpeedProvider`'s hardcoded 30-second httpx
  timeout was too short for PSI's real-world response times (commonly
  30-60s+, especially on a cold cache), so the desktop `runPagespeed` call
  would time out and fail with no error surfaced anywhere — not in the UI,
  not in logs. Raised the timeout to 90s and added one retry with backoff
  (`performance.py`).
- **Report page showed misleading "clean" results before a scan had
  actually finished collecting evidence** — e.g. "No finding raised" on
  every rule, empty technology/dependency lists — indistinguishable from a
  genuinely clean scan. The dashboard polls `/report` continuously while a
  scan runs, but findings only exist once the `rules_engine` job (the
  last pipeline step) completes, so every section rendered its normal
  "nothing here" state regardless of whether the underlying collection
  task had even started. The scan detail page now checks each section's
  job status and shows a "Pending — hasn't finished collecting yet" state
  instead; the rules-coverage table also now says "OK" rather than "No
  finding raised" for a rule that genuinely ran clean, reserving "Pending"
  for checks that haven't run yet.
