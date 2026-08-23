# Threat model

Veritech Scan collects bounded, public technical evidence about a domain the
submitting user has attested authorization to analyze. It is explicitly
**not** a vulnerability scanner, penetration-testing tool, or access-control
bypass system. This document covers what the system defends against, how,
and what's deliberately out of scope.

## SSRF prevention

All target validation lives in `apps/api/app/core/url_safety.py`
(`tests/backend/test_url_safety.py` — 40+ cases).

- **Scheme allowlist**: only `http`/`https` are accepted
  (`normalize_input_to_url`).
- **Hostname blocklist**: `localhost` and known local-DNS aliases are
  rejected before any lookup.
- **DNS resolved before crawling**: `validate_target` resolves A/AAAA
  records and rejects the whole target if *any* resolved IP is disallowed —
  it does not just pick the first "good" one.
- **IP-range rejection** (`is_ip_disallowed`): loopback, RFC1918 private,
  link-local (which covers `169.254.169.254`, but it's also explicitly
  listed for defense in depth), multicast, reserved, unspecified, and a
  small explicit list of known cloud metadata literals (AWS/GCP/Azure/OCI
  and Alibaba Cloud).
- **Redirect revalidation**: `revalidate_redirect_url` re-runs the *entire*
  validation pipeline — not just an IP check — on every redirect hop. This
  is called from three places:
  - `app/collectors/http_checks.py::fetch_with_redirect_revalidation`,
    manually walking redirects (never `httpx`'s `follow_redirects=True`) so
    each hop is checked before it's requested.
  - `app/collectors/crawler.py::run_crawl`, same pattern, plus an
    additional same-origin check (a redirect leaving the scan's hostname is
    recorded as an error and not followed).
  - Anywhere else a redirect Location header is about to be requested.
- **IP literals in the original input** are checked directly
  (`_is_ip_literal` + `is_ip_disallowed`) — a user cannot bypass DNS
  resolution entirely by submitting an IP address directly.

## Crawl boundaries

`apps/api/app/core/crawl_policy.py` (`tests/backend/test_crawl_policy.py`):

- Same-origin only (`is_crawlable_url` checks the resolved hostname exactly).
- Excludes `mailto:`, `tel:`, `javascript:`, `data:`, `ftp:`, `file:`.
- Excludes common static asset extensions (images, fonts, archives, media,
  data files).
- Excludes path patterns for login/admin/account/cart/checkout/API/OAuth/
  password-reset surfaces (`EXCLUDED_PATH_PATTERNS`).
- Hard-capped at the user-selected `max_pages` (10/25/50 — enforced both by
  the Pydantic schema's `Literal[10, 25, 50]` and by the crawler's own loop
  bound).
- One request per `SCAN_DEFAULT_REQUEST_DELAY_SECONDS` (default 1.5s) per
  target, and a 15-second per-page timeout
  (`SCAN_PAGE_TIMEOUT_SECONDS`).

The crawler **never submits a form, authenticates, or interacts with a
CAPTCHA** — it only issues `GET` requests to discovered `<a href>` links,
and Playwright's homepage render likewise only navigates and observes; it
never types into fields or clicks buttons.

## Authorization

`POST /api/v1/scans` requires `authorization_acknowledgment: true` in the
request body, and the Pydantic validator on `ScanCreateRequest` rejects the
request outright if it's `false` (`apps/api/app/schemas/scan.py`). The
acknowledgment timestamp is stored on `scan_requests.authorization_confirmed_at`
and shown on the report. This is a self-attestation, not a technical
enforcement of ownership — see "Non-goals" below.

## User / data isolation

- Every `scan_requests` row has a `user_id` and `organization_id`; there is
  no anonymous or unowned scan.
- `apps/api/app/api/v1/scans.py::_get_owned_scan` enforces that only the
  owning user or an admin (`user.is_admin`) can read a scan, its events,
  findings, evidence, or report — checked on every scan-scoped endpoint, not
  just the list endpoint (`tests/backend/test_api_scans.py`).
- Public signup is not implemented; users are created via the seed/admin
  bootstrap command only (invite-only by design).

## Scan-runner isolation

- The runner runs Playwright in **one ephemeral browser context per scan
  step** (`app/collectors/browser_render.py`) — no `storage_state` is loaded
  or persisted, so cookies set during the visit do not survive past that
  single collection step.
- The runner never stores request bodies, form data, session data, or
  cookies as evidence — only request hostnames, resource types, and
  console/error text.
- **One scan per Machine, by construction.** Each scan gets its own
  on-demand Fly Machine (`app/services/scan_orchestrator.py::
  request_scan_runner`), so there is no shared process/memory between
  scans and no concurrency-limit knob needed — the isolation is structural,
  not configured.
- The scan-runner Machine listens for no inbound HTTP traffic at all — it
  only reads its `SCAN_ID` and writes to Postgres and the target site.
- A runner is guarded against duplicate processing: `app/runner/run.py`
  atomically claims a scan (`UPDATE ... WHERE status IN
  ('queued','starting')`) before doing any work, so two runners racing on
  the same scan ID can't both process it.

## Rate limiting

- **Scan creation**: `apps/api/app/core/rate_limit.py` enforces
  `SCAN_CREATE_RATE_LIMIT_PER_HOUR` (default 10) per user via a rolling
  1-hour count of that user's `scan_requests` rows in Postgres, checked
  before target validation in `POST /api/v1/scans`.
- **Outbound requests to the target**: every collector that makes multiple
  requests (crawler, robots/sitemap) respects
  `SCAN_DEFAULT_REQUEST_DELAY_SECONDS` between requests to the same target.
- **Total scan duration**: `SCAN_MAX_TOTAL_MINUTES` (default 10) bounds
  worst-case load on any single target, checked by the orchestrator before
  starting each collection area.

## Artifact retention

Screenshots and generated HTML reports are written to the artifact storage
directory (`ARTIFACT_STORAGE_LOCAL_PATH`), scoped per-scan by ID
(`app/services/artifact_storage.py::LocalArtifactStorage`), which also
guards against path traversal outside the artifact root. Nothing sensitive
(cookies, form data, credentials) is ever written there — see "Worker
isolation" above.

## Explicit non-goals

Veritech Scan does **not**:

- Confirm or exploit vulnerabilities of any kind.
- Bypass authentication, access controls, or CAPTCHAs.
- Submit forms or otherwise mutate state on the target.
- Implement full `robots.txt` enforcement — it *records* `robots.txt` as
  evidence (see `app/collectors/robots_sitemap.py`) and does not gate crawl
  behavior on `Disallow` rules. The generated report does separately
  cross-reference the crawled page set against `Disallow` rules and the
  declared sitemap (informational only, plain prefix matching against
  `User-agent: *` — no wildcard/end-anchor support), but this is not
  enforcement. This is a known, documented limitation suitable for the
  bounded-evidence MVP, not a security control.
- Verify the authorization attestation technically (e.g. via a DNS TXT
  record or file challenge). The MVP relies on the user's self-attestation,
  logged with a timestamp, plus the product being invite-only. A stronger
  domain-ownership proof (DNS/file-based, similar to ACME challenges) is a
  natural post-MVP hardening step — see `docs/security-hardening.md`.
- Provide high availability or automatic failover for the database — a
  single Postgres instance is the one persistent, paid dependency of this
  architecture (see `docs/fly-deployment.md`).
