from datetime import datetime, timezone
from urllib.parse import urlsplit

from sqlalchemy.orm import Session, joinedload
from veritech_scan_rules import RULE_CATALOG

from app.collectors.dependency_classification import known_vendor_name
from app.collectors.dns_checks import COMMON_DKIM_SELECTORS
from app.config import get_settings
from app.models.evidence import EvidenceItem
from app.models.finding import Finding, FindingEvidence
from app.models.observation import (
    DNSObservation,
    HTTPObservation,
    PerformanceObservation,
    TechnologyObservation,
    ThirdPartyDependency,
)
from app.models.finding import REGISTER_SEVERITIES
from app.models.page import Page
from app.models.scan import JOB_STATUS_FAILED, ScanJob, ScanRequest
from app.schemas.evidence import EvidenceItemOut, FindingOut
from app.schemas.report import FindingSeverityCounts, LimitationOut, ReportOut

SITEMAP_CROSS_CHECK_SAMPLE_LIMIT = 20

# Platform/CMS/framework-identifying technology categories (see
# collectors/technology.py::DETECTION_RULES) — used to pick out a single
# "what platform is this built on" headline for the Platform and stack
# section, distinct from the full technology/dependency inventory.
PLATFORM_TECHNOLOGY_CATEGORIES = {
    "cms",
    "ecommerce_platform",
    "website_builder",
    "headless_cms",
    "static_site_framework",
}
_CONFIDENCE_RANK = {"high": 0, "medium": 1, "low": 2}

# Hosting/infra signal headers worth surfacing verbatim — not fired on by any
# rule, just displayed (Priority 5c). Keys are lowercase header names; values
# are the human-facing label.
HOSTING_FINGERPRINT_HEADERS = {
    "server": "Server",
    "x-powered-by": "X-Powered-By",
    "cf-ray": "cf-ray (Cloudflare)",
    "x-vercel-id": "X-Vercel-Id",
    "x-nf-request-id": "X-NF-Request-Id (Netlify)",
    "x-amz-cf-id": "X-Amz-Cf-Id (CloudFront)",
}


def _path_key(url: str) -> str:
    """Path identity for cross-referencing crawled pages against sitemap/robots
    URLs — same trailing-slash collapsing as the crawler's own dedupe key,
    plus index-file normalization (index.html/.htm) so e.g. /index.html and
    / are treated as the same page instead of a false-positive mismatch."""
    path = urlsplit(url).path or "/"
    for index_name in ("/index.html", "/index.htm"):
        if path.lower().endswith(index_name):
            path = path[: -len(index_name)] + "/"
            break
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return path or "/"


def _detect_platform(tech_obs: list[TechnologyObservation], pages: list[Page]) -> dict | None:
    """Picks one "what is this site built on" headline (Priority 5d): the
    highest-confidence CMS/ecommerce/website-builder/headless-CMS/static-site
    framework technology already detected, or — when none of those matched —
    a best-effort "looks like static HTML" heuristic from the crawled URLs
    themselves, so a plain static site doesn't just silently show nothing
    under "platform"."""
    candidates = [t for t in tech_obs if t.category in PLATFORM_TECHNOLOGY_CATEGORIES]
    if candidates:
        best = min(candidates, key=lambda t: _CONFIDENCE_RANK.get(t.confidence, 9))
        return {
            "name": best.technology_name,
            "category": best.category,
            "confidence": best.confidence,
            "detection_method": best.detection_method,
            "heuristic": False,
        }

    urls = [p.final_url or p.url for p in pages if p.url]
    static_like = [u for u in urls if urlsplit(u).path.lower().endswith((".html", ".htm"))]
    if urls and static_like:
        pct = round(100 * len(static_like) / len(urls))
        return {
            "name": "Static HTML site (no CMS or framework detected)",
            "category": "static_html",
            "confidence": "medium",
            "detection_method": f"{len(static_like)} of {len(urls)} crawled URL(s) ({pct}%) end in .html/.htm "
            "and no CMS, ecommerce platform, website builder, headless CMS, or static-site-generator marker "
            "was found on the homepage.",
            "heuristic": True,
        }
    return None


def _build_sitemap_check(
    pages: list[Page], robots_evidence: EvidenceItem | None, sitemap_evidence: EvidenceItem | None
) -> dict:
    """Cross-references the crawled page set against what robots.txt and the
    sitemap claim. All three collectors run independently, so this comparison
    only happens here, once all their evidence is available together."""
    disallow_rules: list[str] = (robots_evidence.normalized_payload_json.get("disallow_rules") if robots_evidence else None) or []
    sitemap_urls: list[str] = (sitemap_evidence.normalized_payload_json.get("discovered_urls") if sitemap_evidence else None) or []
    sitemap_file_count = (sitemap_evidence.normalized_payload_json.get("sitemap_count") if sitemap_evidence else None) or 0

    crawled_by_path = {
        _path_key(p.final_url or p.url): (p.final_url or p.url) for p in pages if p.status_code and p.status_code < 400
    }
    sitemap_by_path = {_path_key(u): u for u in sitemap_urls}

    crawled_not_in_sitemap = sorted(url for key, url in crawled_by_path.items() if key not in sitemap_by_path)
    sitemap_not_crawled = sorted(url for key, url in sitemap_by_path.items() if key not in crawled_by_path)
    crawled_but_disallowed = sorted(
        url for key, url in crawled_by_path.items() if any(rule and key.startswith(rule) for rule in disallow_rules)
    )

    return {
        "sitemap_declared_count": len(sitemap_urls),
        "sitemap_file_count": sitemap_file_count,
        "disallow_rule_count": len(disallow_rules),
        "disallow_rules": disallow_rules,
        "crawled_not_in_sitemap_count": len(crawled_not_in_sitemap),
        "crawled_not_in_sitemap_sample": crawled_not_in_sitemap[:SITEMAP_CROSS_CHECK_SAMPLE_LIMIT],
        "sitemap_not_crawled_count": len(sitemap_not_crawled),
        "sitemap_not_crawled_sample": sitemap_not_crawled[:SITEMAP_CROSS_CHECK_SAMPLE_LIMIT],
        "crawled_but_disallowed_count": len(crawled_but_disallowed),
        "crawled_but_disallowed_sample": crawled_but_disallowed[:SITEMAP_CROSS_CHECK_SAMPLE_LIMIT],
        # Priority 5b: sitemap freshness — newest/oldest <lastmod> across
        # every sitemap entry that declared one.
        "lastmod_count": (sitemap_evidence.normalized_payload_json.get("lastmod_count") if sitemap_evidence else 0) or 0,
        "newest_lastmod": sitemap_evidence.normalized_payload_json.get("newest_lastmod") if sitemap_evidence else None,
        "oldest_lastmod": sitemap_evidence.normalized_payload_json.get("oldest_lastmod") if sitemap_evidence else None,
    }


def _build_coverage(findings: list[Finding]) -> dict:
    """Surfaces the scan-coverage state (full/partial/blocked) as its own
    report field — backed by the same scan_blocked/scan_coverage_partial
    Finding rows the rules engine already produces, just pulled out so the
    UI can render it as a top-of-report banner rather than a risk-register
    row a reader could miss.
    """
    coverage_finding = next((f for f in findings if f.category == "scan_coverage"), None)
    if not coverage_finding:
        return {
            "state": "full",
            "message": "Full coverage — no indication this scan was blocked or degraded.",
            "finding_id": None,
        }
    state = "blocked" if coverage_finding.rule and coverage_finding.rule.rule_key == "scan_blocked" else "partial"
    return {
        "state": state,
        "message": coverage_finding.title,
        "detail": coverage_finding.impact,
        "finding_id": str(coverage_finding.id),
    }


def _build_rules_checked(findings: list[Finding]) -> dict:
    """Maps every rule in the static RULE_CATALOG against this scan's actual
    findings, so the report can show "N rules checked, M raised a finding"
    instead of only ever listing the rules that happened to fire. Includes
    "ok"-severity (positive-observation) findings too — those never appear
    in the risk register, but they did fire, and this table's job is to
    account for every rule's actual outcome."""
    fired_by_rule_key = {f.rule.rule_key: f for f in findings if f.rule}

    rules: list[dict] = []
    for rule_key, meta in RULE_CATALOG.items():
        finding = fired_by_rule_key.get(rule_key)
        rules.append(
            {
                "rule_key": rule_key,
                "category": meta["category"],
                "check": meta["check"],
                "fired": finding is not None,
                "severity": finding.severity if finding else None,
                "title": finding.title if finding else None,
                "finding_id": str(finding.id) if finding else None,
                "positive_observation": finding.severity == "ok" if finding else False,
            }
        )

    return {
        "total_count": len(rules),
        "fired_count": sum(1 for r in rules if r["fired"]),
        "rules": rules,
    }


# Priority 6d: one lead sentence naming what this scan is, followed by the
# specific caveats as a short list — replaces three identically-labeled
# "General:" rows that used to read as the same note repeated.
SCAN_SCOPE_STATEMENT = (
    "This is a bounded, rate-limited public-web pre-screen, not a penetration test or vulnerability scan "
    "— absence of a finding here is not proof of absence of risk."
)
KNOWN_LIMITATION_CAVEATS = [
    "The crawler does not enforce robots.txt while fetching pages; it separately cross-references the "
    "crawled page set against robots.txt Disallow rules (plain prefix matching only) and declared sitemap "
    "URLs — see Crawl and indexability.",
    f"DKIM discovery probes {len(COMMON_DKIM_SELECTORS)} common ESP-default selectors (Google Workspace, "
    "Microsoft 365, Mailchimp, SendGrid, etc.); a domain signing only with a custom selector will not be "
    "found, so a missing DKIM result is not proof of absence.",
    "The browser renderer inspects only the homepage, not the full crawled page set.",
]


def build_report(db: Session, scan: ScanRequest) -> ReportOut:
    settings = get_settings()

    severity_rank = {"high": 0, "medium": 1, "low": 2, "info": 3, "ok": 4}
    findings = (
        db.query(Finding)
        .options(
            joinedload(Finding.evidence_links).joinedload(FindingEvidence.evidence_item),
            joinedload(Finding.rule),
        )
        .filter(Finding.scan_request_id == scan.id)
        .all()
    )
    findings.sort(key=lambda f: (severity_rank.get(f.severity, 9), f.created_at))
    # "ok"-severity findings (positive observations, e.g. DKIM signing found)
    # fired and are accounted for in the rules-coverage table below, but they
    # are not risks — they never appear in the risk register or its counts.
    register_findings = [f for f in findings if f.severity in REGISTER_SEVERITIES]
    rules_checked = _build_rules_checked(findings)

    severity_counts = FindingSeverityCounts()
    finding_outs: list[FindingOut] = []
    for f in register_findings:
        evidence = [link.evidence_item for link in f.evidence_links]
        finding_outs.append(
            FindingOut(
                id=f.id,
                category=f.category,
                severity=f.severity,
                confidence=f.confidence,
                title=f.title,
                impact=f.impact,
                recommended_next_step=f.recommended_next_step,
                dollar_impact=f.dollar_impact,
                remediation_timing=f.remediation_timing,
                status=f.status,
                rule_version=f.rule_version,
                created_at=f.created_at,
                evidence=[EvidenceItemOut.model_validate(e) for e in evidence],
            )
        )
        if f.severity in severity_counts.model_fields:
            setattr(severity_counts, f.severity, getattr(severity_counts, f.severity) + 1)

    pages = db.query(Page).filter(Page.scan_request_id == scan.id).all()
    http_obs = (
        db.query(HTTPObservation)
        .filter(HTTPObservation.scan_request_id == scan.id)
        .order_by(HTTPObservation.created_at)
        .first()
    )
    dns_obs = db.query(DNSObservation).filter(DNSObservation.scan_request_id == scan.id).all()
    tech_obs = db.query(TechnologyObservation).filter(TechnologyObservation.scan_request_id == scan.id).all()
    third_party_obs = (
        db.query(ThirdPartyDependency)
        .filter(ThirdPartyDependency.scan_request_id == scan.id)
        .order_by(ThirdPartyDependency.request_count.desc())
        .all()
    )
    robots_evidence = (
        db.query(EvidenceItem)
        .filter(
            EvidenceItem.scan_request_id == scan.id,
            EvidenceItem.category == "robots_sitemap",
            EvidenceItem.source_type == "robots_txt",
        )
        .order_by(EvidenceItem.captured_at)
        .first()
    )
    sitemap_evidence = (
        db.query(EvidenceItem)
        .filter(
            EvidenceItem.scan_request_id == scan.id,
            EvidenceItem.category == "robots_sitemap",
            EvidenceItem.source_type == "sitemap_xml",
        )
        .order_by(EvidenceItem.captured_at)
        .first()
    )
    perf_obs = (
        db.query(PerformanceObservation)
        .filter(PerformanceObservation.scan_request_id == scan.id)
        .order_by(PerformanceObservation.created_at)
        .first()
    )
    tls_evidence = (
        db.query(EvidenceItem)
        .filter(
            EvidenceItem.scan_request_id == scan.id,
            EvidenceItem.category == "tls",
            EvidenceItem.source_type == "tls_certificate",
        )
        .order_by(EvidenceItem.captured_at)
        .first()
    )
    exposure_evidence = (
        db.query(EvidenceItem)
        .filter(
            EvidenceItem.scan_request_id == scan.id,
            EvidenceItem.category == "exposure",
            EvidenceItem.source_type == "endpoint_probe",
        )
        .order_by(EvidenceItem.captured_at)
        .first()
    )
    domain_registration_evidence = (
        db.query(EvidenceItem)
        .filter(
            EvidenceItem.scan_request_id == scan.id,
            EvidenceItem.category == "domain_registration",
            EvidenceItem.source_type == "rdap_lookup",
        )
        .order_by(EvidenceItem.captured_at)
        .first()
    )
    accessibility_evidence = (
        db.query(EvidenceItem)
        .filter(
            EvidenceItem.scan_request_id == scan.id,
            EvidenceItem.category == "accessibility",
            EvidenceItem.source_type == "static_accessibility_scan",
        )
        .order_by(EvidenceItem.captured_at)
        .first()
    )
    browser_render_evidence = (
        db.query(EvidenceItem)
        .filter(
            EvidenceItem.scan_request_id == scan.id,
            EvidenceItem.category == "browser_render",
            EvidenceItem.source_type == "playwright_render",
        )
        .order_by(EvidenceItem.captured_at)
        .first()
    )

    failed_jobs = (
        db.query(ScanJob)
        .filter(ScanJob.scan_request_id == scan.id, ScanJob.status == JOB_STATUS_FAILED)
        .all()
    )
    limitations = [
        LimitationOut(task_name=job.task_name, message=job.error_message or "This collection task failed.")
        for job in failed_jobs
    ] + [LimitationOut(task_name="", message=msg) for msg in KNOWN_LIMITATION_CAVEATS]

    dns_email = {
        "records": [
            {
                "record_type": o.record_type,
                "name": o.name,
                "record_values": o.values,
                "lookup_successful": o.lookup_successful,
                "error_message": o.error_message,
            }
            for o in dns_obs
            if o.record_type not in ("SPF", "DMARC", "DKIM")
        ],
        "dkim_selectors_found": [o.dkim_selector for o in dns_obs if o.record_type == "DKIM" and o.dkim_selector],
        "dkim_probed_count": len(COMMON_DKIM_SELECTORS),
        "spf": next(
            (
                {"record": o.spf_record, "lookup_successful": o.lookup_successful, "error_message": o.error_message}
                for o in dns_obs
                if o.record_type == "SPF"
            ),
            None,
        ),
        "dmarc": next(
            (
                {
                    "record": o.dmarc_record,
                    "policy": o.dmarc_policy,
                    "pct": o.dmarc_pct,
                    "rua": o.dmarc_rua,
                    "lookup_successful": o.lookup_successful,
                    "error_message": o.error_message,
                }
                for o in dns_obs
                if o.record_type == "DMARC"
            ),
            None,
        ),
    }

    http_security = {}
    if http_obs:
        redirect_chain = http_obs.redirect_chain or []
        # Priority 5a: surface the full redirect chain (not just the final
        # URL) and flag anything worth a second look — more than one hop, or
        # a chain that crosses http/https along the way.
        schemes_seen = {urlsplit(hop.get("from_url", "")).scheme for hop in redirect_chain if hop.get("from_url")}
        schemes_seen.add(urlsplit(http_obs.final_url).scheme)
        headers_lower = {k.lower(): v for k, v in (http_obs.headers or {}).items()}
        hosting_fingerprint = {
            label: headers_lower[header]
            for header, label in HOSTING_FINGERPRINT_HEADERS.items()
            if header in headers_lower
        }
        http_security = {
            "final_url": http_obs.final_url,
            "status_code": http_obs.status_code,
            "is_https": http_obs.is_https,
            "redirect_chain": redirect_chain,
            "redirect_hop_count": len(redirect_chain),
            "redirect_mixes_schemes": len(schemes_seen - {""}) > 1,
            "redirect_worth_flagging": len(redirect_chain) > 1 or len(schemes_seen - {""}) > 1,
            "strict_transport_security": http_obs.strict_transport_security,
            "content_security_policy": http_obs.content_security_policy,
            "x_content_type_options": http_obs.x_content_type_options,
            "x_frame_options": http_obs.x_frame_options,
            "referrer_policy": http_obs.referrer_policy,
            "permissions_policy": http_obs.permissions_policy,
            "server_header": http_obs.server_header,
            "hosting_fingerprint": hosting_fingerprint,
            "response_duration_ms": http_obs.response_duration_ms,
            "mixed_content_count": (
                browser_render_evidence.normalized_payload_json.get("mixed_content_count")
                if browser_render_evidence
                else None
            ),
            "mixed_content_urls": (
                browser_render_evidence.normalized_payload_json.get("mixed_content_urls", [])
                if browser_render_evidence
                else []
            ),
        }

    error_pages = [p for p in pages if p.status_code and p.status_code >= 400]
    crawl_indexability = {
        "pages_scanned": len(pages),
        "error_page_count": len(error_pages),
        "pages": [
            {
                "url": p.url,
                "status_code": p.status_code,
                "title": p.title,
                "canonical_url": p.canonical_url,
                "meta_description_present": bool(p.meta_description),
                "h1_count": p.h1_count,
                "fetch_error": p.fetch_error,
            }
            for p in pages
        ],
        "sitemap_check": _build_sitemap_check(pages, robots_evidence, sitemap_evidence),
    }

    technology = {
        "platform": _detect_platform(tech_obs, pages),
        "technologies": [
            {
                "technology_name": t.technology_name,
                "category": t.category,
                "detection_method": t.detection_method,
                "confidence": t.confidence,
            }
            for t in tech_obs
        ],
    }

    third_party_rows: dict[str, dict] = {}
    for d in third_party_obs:
        vendor_name = known_vendor_name(d.hostname)
        key = vendor_name or d.hostname
        row = third_party_rows.get(key)
        if row is None:
            third_party_rows[key] = {
                "hostname": d.hostname,
                "vendor_name": vendor_name,
                "category": d.category,
                "request_count": d.request_count,
                "classification_method": d.classification_method,
            }
        else:
            if d.hostname not in row["hostname"].split(", "):
                row["hostname"] = ", ".join(sorted({*row["hostname"].split(", "), d.hostname}))
            row["request_count"] += d.request_count
    third_party_dependencies = {
        "domains": sorted(third_party_rows.values(), key=lambda r: r["request_count"], reverse=True),
        "hostname_count": len(third_party_obs),
    }

    performance = {}
    if perf_obs:
        performance = {
            "provider": perf_obs.provider,
            "configured": perf_obs.configured,
            "response_duration_ms": perf_obs.response_duration_ms,
            "html_bytes": perf_obs.html_bytes,
            "third_party_domain_count": perf_obs.third_party_domain_count,
            "js_resource_count": perf_obs.js_resource_count,
            "desktop": {
                "lcp_ms": perf_obs.desktop_lcp_ms,
                "cls": perf_obs.desktop_cls,
                "inp_ms": perf_obs.desktop_inp_ms,
                "fcp_ms": perf_obs.desktop_fcp_ms,
                "ttfb_ms": perf_obs.desktop_ttfb_ms,
                "performance_score": perf_obs.desktop_performance_score,
                "accessibility_score": perf_obs.desktop_accessibility_score,
                "best_practices_score": perf_obs.desktop_best_practices_score,
                "seo_score": perf_obs.desktop_seo_score,
            },
            "mobile": {
                "lcp_ms": perf_obs.mobile_lcp_ms,
                "cls": perf_obs.mobile_cls,
                "inp_ms": perf_obs.mobile_inp_ms,
                "fcp_ms": perf_obs.mobile_fcp_ms,
                "ttfb_ms": perf_obs.mobile_ttfb_ms,
                "performance_score": perf_obs.mobile_performance_score,
                "accessibility_score": perf_obs.mobile_accessibility_score,
                "best_practices_score": perf_obs.mobile_best_practices_score,
                "seo_score": perf_obs.mobile_seo_score,
            },
        }

    return ReportOut(
        scan_id=scan.id,
        product_name=settings.product_name,
        parent_brand=settings.parent_brand,
        report_name=settings.report_name,
        domain=scan.normalized_domain,
        original_input=scan.original_input,
        notes=scan.notes,
        status=scan.status,
        max_pages=scan.max_pages,
        authorization_confirmed_at=scan.authorization_confirmed_at,
        started_at=scan.started_at,
        completed_at=scan.completed_at,
        pages_scanned=len(pages),
        is_demo=scan.is_demo,
        severity_counts=severity_counts,
        findings=finding_outs,
        rules_checked=rules_checked,
        coverage=_build_coverage(findings),
        dns_email=dns_email,
        http_security=http_security,
        crawl_indexability=crawl_indexability,
        technology=technology,
        third_party_dependencies=third_party_dependencies,
        performance=performance,
        tls=tls_evidence.normalized_payload_json if tls_evidence else {},
        platform_exposure=exposure_evidence.normalized_payload_json if exposure_evidence else {},
        domain_registration=domain_registration_evidence.normalized_payload_json if domain_registration_evidence else {},
        accessibility=accessibility_evidence.normalized_payload_json if accessibility_evidence else {},
        scope_statement=SCAN_SCOPE_STATEMENT,
        limitations=limitations,
        generated_at=datetime.now(timezone.utc),
    )
