# Rules engine

## Why deterministic rules, not an LLM

Veritech Scan never uses an LLM to decide what a finding is. A due-diligence
risk register has to be **reproducible** — the same evidence must always
produce the same finding, with the same severity and confidence, so a buyer
(and their counsel) can trust that re-running a scan against unchanged
evidence won't silently change the verdict. LLM-generated findings would
also make it much harder to guarantee the observation/interpretation and
evidence/confidence distinctions the product is built around. Every rule is
a plain Python function: `(RuleContext) -> RuleResult | None`, with no
network calls and no randomness.

## Private rule catalog

The rule implementations themselves — every detection condition, threshold,
and the dollar-impact/remediation-timing assignment logic — live in a
separate private package, **`veritech-scan-rules`**, not in this repo. This
app depends on it like any other pip dependency (pinned to a tag in
`apps/api/requirements.txt`); it has no visibility into this app's database
or models, and this app has no visibility into its detection logic beyond
the `RuleContext -> RuleResult | None` contract described below. This split
exists so this repo can be public without exposing the methodology behind
the paid product — see the "Implemented rules" and "How dollar impact and
remediation timing are set" sections below for what's intentionally still
documented here (the *what*, not the *how*).

Installing/updating it requires SSH (or token) access to the private repo,
in three places: local dev (your own GitHub SSH key, if you're a
collaborator), CI (`.github/workflows/deploy.yml`, via a scoped
deploy-key/PAT secret), and the Fly remote build (via a Docker BuildKit
secret passed to `fly deploy --build-secret`, since Fly's remote builders
don't have a local SSH agent to forward). Bumping a rule's logic means:
commit + tag a new version in `veritech-scan-rules`, bump the pinned tag in
`apps/api/requirements.txt`, redeploy — there is no way to change rule
behavior by editing this repo alone.

## Architecture

- **`apps/api/app/rules/context.py`** — `build_rule_context(db, scan)` reads
  the already-persisted observation tables (`dns_observations`,
  `http_observations`, `pages`, `third_party_dependencies`,
  `performance_observations`) plus several evidence-item lookups (sitemap,
  TLS, domain registration, accessibility, exposure probes, browser
  rendering) and looks up the relevant `evidence_items` IDs for citation,
  into one `RuleContext`. Every field on `RuleContext` is plain, pre-fetched
  data — rule functions never query the database themselves, which is what
  lets `veritech-scan-rules` depend on nothing but this dataclass's shape.
- **`veritech-scan-rules` (private)** — each rule is registered via the
  `@rule` decorator into a module-level list. A rule returns `None` when it
  doesn't fire, or a `RuleResult` (title, category, severity, confidence,
  impact, recommended next step, dollar impact, remediation timing, and the
  evidence item ID(s) it cites).
- **`apps/api/app/rules/engine.py`** — `run_rules_engine(db, scan)`:
  1. Deletes any prior `findings` for this scan (so re-running always
     reflects the current evidence — see
     `tests/backend/test_rules_engine.py::test_rules_engine_is_idempotent_on_rerun`).
  2. Gets-or-creates a `finding_rules` catalog row per `(rule_key, version)`.
  3. Runs every registered rule (`veritech_scan_rules.all_rules()`) against
     the context.
  4. Persists a `Finding` + one `FindingEvidence` row per cited evidence
     item for every match.
- **`RULE_CATALOG`** (in `veritech-scan-rules`, re-exported and imported here
  as `from veritech_scan_rules import RULE_CATALOG`) — a static `rule_key ->
  {category, check}` map covering every registered rule, independent of any
  single scan's outcome. `report_builder._build_rules_checked()` cross-
  references it against a scan's actual `Finding` rows so every report shows
  a full "N rules checked, M raised a finding" table — including the rules
  that ran and found nothing — not just the ones that happened to fire.
  Keeping a rule out of `RULE_CATALOG` after adding it to the registry (or
  vice versa) is a bug; nothing enforces they stay in sync automatically.

## Rule versioning

`finding_rules` is keyed on `(rule_key, version)`. A rule's `version` is a
plain integer set in its `RuleResult`. Bumping `version` when you change a
rule's logic or thresholds means:

- Old `findings` rows keep pointing at the `finding_rules` row for the
  version that actually produced them — historical findings never silently
  change meaning underneath a report that already exists.
- A new scan run against the new code creates (or reuses) the new
  `(rule_key, new_version)` catalog row.

Changing a rule's severity/confidence/wording **without** changing its
detection logic does not require a version bump; changing what evidence
triggers it, or how severity is computed, does.

## Implemented rules

| Rule key | Category | Severity | Confidence |
|---|---|---|---|
| `scan_blocked` | scan_coverage | high | high |
| `scan_coverage_partial` | scan_coverage | medium | high |
| `missing_dmarc` | email_deliverability | medium | high |
| `dmarc_policy_none` (v2) | email_deliverability | medium / low | high |
| `dkim_selector_found` | email_deliverability | ok | medium |
| `missing_spf` | email_deliverability | medium | high |
| `homepage_not_https` | security_posture | high | high |
| `missing_hsts` | security_posture | low | high |
| `missing_csp` | security_posture | low | high |
| `no_sitemap_found` | discoverability | low | medium |
| `homepage_missing_canonical` | indexability | low | high |
| `homepage_missing_meta_description` | on_page_seo | low | high |
| `excessive_third_party_domains` | dependency_management | medium | medium |
| `pagespeed_mobile_below_50` | performance | medium | high (only when `GOOGLE_PAGESPEED_API_KEY` is configured) |
| `lcp_poor_mobile` | performance | medium / low | high (only when `GOOGLE_PAGESPEED_API_KEY` is configured) |
| `lcp_poor_desktop` | performance | medium / low | high (only when `GOOGLE_PAGESPEED_API_KEY` is configured) |
| `excessive_crawl_errors` (v2) | site_reliability | medium | high |
| `no_analytics_detected` | analytics | medium | medium |
| `xmlrpc_php_exposed` | platform_exposure | low | high |
| `wp_json_rest_api_exposed` | platform_exposure | info | high |
| `tls_certificate_expiring_or_expired` | security_posture | high/medium | high |
| `domain_registration_expiring_soon` | domain_registration | high/medium | high |
| `homepage_images_missing_alt` | accessibility | low | medium |
| `homepage_form_inputs_missing_labels` | accessibility | low | medium |
| `accessibility_overlay_widget_detected` | accessibility | info | high |
| `mixed_content_on_https_page` | security_posture | medium | high |

### Severity: "ok" vs. register severities

`SEVERITIES` (`apps/api/app/models/finding.py`) includes a fifth level, `ok`,
alongside the usual `high`/`medium`/`low`/`info`. `ok` is for a rule whose
firing is itself a *positive* observation (currently only
`dkim_selector_found`) — evidence worth citing, not a risk. `ok`-severity
findings still fire, still get a `Finding` row, and still show up in the
rules-coverage table (`report.rules_checked`), but `report_builder.build_report`
excludes them from the risk register and its severity counts
(`REGISTER_SEVERITIES = ("info", "low", "medium", "high")`). Everything from
`info` up is a register-eligible risk level; only `ok` is carved out. A new
rule that's reporting a favorable/neutral fact rather than a risk should use
`ok`; a rule reporting anything a buyer should weigh — even a mild one like
`wp_json_rest_api_exposed` — stays at `info` or above.

### How dollar impact and remediation timing are set

Every `RuleResult` sets `dollar_impact` (`"n/a"` / `"$"` / `"$$"` / `"$$$"`)
and `remediation_timing` (`"n/a"` / `"30-day"` / `"60-day"` / `"90-day"` /
`"longer-term"`) — see `DOLLAR_IMPACT_LEVELS` / `REMEDIATION_TIMINGS` in
`apps/api/app/models/finding.py`. Both are set by the rule, never left for a
report reader to infer. The assignment logic itself — including when it
departs from a severity-based default — is part of the private rule catalog
and isn't documented here; see `veritech-scan-rules`.

Changing only a rule's `dollar_impact`/`remediation_timing` (with detection
logic and severity computation unchanged) does not require a version bump,
by the same logic as severity/confidence/wording changes described above.

`scan_blocked` / `scan_coverage_partial` are produced by a coverage-status
evaluation that runs as part of the same rules pass, using the homepage's
final HTTP status, a bot-challenge/WAF-block content-signature match, and
crawled-page-count vs. `max_pages`. `report_builder._build_coverage()` pulls
whichever of the two fired (if either) into `ReportOut.coverage`, rendered as
a top-of-report banner in both the web UI and the HTML export — the same
underlying Finding, just surfaced with more visual weight than a normal risk-
register row so a blocked/partial scan can never read as a clean result.

`missing_csp` is deliberately worded as a **hardening opportunity**, not a
vulnerability — see the `impact` text in `veritech-scan-rules`'s
`missing_csp` rule. This phrasing convention (observation → interpretation,
hardening opportunity vs. confirmed issue) applies to every rule's `impact`
field.

## Evidence linkage

Every `RuleResult.evidence_ids` must be non-empty for the finding to be
meaningful, and `run_rules_engine` writes one `FindingEvidence` row per ID.
`tests/backend/test_rules_engine.py::test_every_finding_links_to_at_least_one_evidence_item`
and the end-to-end test in `test_e2e_scan.py` assert this holds for real
collected evidence, not just fixtures.

## How to add a rule safely

1. In the **`veritech-scan-rules`** repo, write a new function decorated
   with `@rule`, following the existing signature. Pick a new, stable
   `rule_key` — it's the join key for historical findings, never rename it;
   add a new rule instead if the concept truly changes.
2. Set `version=1` for a new rule. Cite real evidence item ID(s) from
   `ctx.evidence_ids` or the other pre-fetched `RuleContext` fields — if the
   rule needs evidence `RuleContext` doesn't carry yet, that means editing
   `build_rule_context` **in this repo** first (a new eager-fetch field),
   then referencing it from the new rule in `veritech-scan-rules`.
3. Write the `impact` field as *observation, then interpretation* —
   describe exactly what was observed before saying what it might mean.
   Never claim a confirmed vulnerability; this product doesn't do
   vulnerability confirmation.
4. Add a unit test in `veritech-scan-rules` covering both the firing and
   non-firing case (construct a `RuleContext` directly there — it no longer
   needs a real database, just plain objects matching the fields it reads).
5. If you change an *existing* rule's detection logic or severity
   computation, bump its `version` rather than editing it in place.
6. Tag a new release in `veritech-scan-rules`, bump the pinned tag in this
   repo's `apps/api/requirements.txt`, and re-run
   `tests/backend/test_rules_engine.py` here (still the source of truth for
   end-to-end behavior against real evidence) before deploying.
