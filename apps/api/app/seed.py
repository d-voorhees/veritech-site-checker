"""Seed / admin-bootstrap command.

Usage:
    python -m app.seed            # create admin (if missing) + synthetic demo scan
    python -m app.seed --admin-only

Idempotent: re-running does not duplicate the admin user, demo organization,
or demo scan.
"""

import argparse
from datetime import datetime, timedelta, timezone

from app.config import get_settings
from app.db import SessionLocal
from app.models.evidence import EvidenceItem
from app.models.finding import Finding, FindingEvidence, FindingRule
from app.models.observation import DNSObservation, HTTPObservation, PerformanceObservation, TechnologyObservation
from app.models.organization import Organization
from app.models.page import Page
from app.models.report import Report
from app.models.scan import (
    JOB_STATUS_SUCCEEDED,
    SCAN_STATUS_COMPLETED,
    ScanEvent,
    ScanJob,
    ScanRequest,
    ScanTarget,
)
from app.models.user import User
from app.security.passwords import hash_password
from app.services.scan_orchestrator import COLLECTION_TASK_NAMES

DEMO_DOMAIN = "example-acquisitiontarget.com"


def ensure_admin(db) -> User:
    settings = get_settings()
    admin = db.query(User).filter(User.email == settings.initial_admin_email.lower()).first()
    if admin:
        print(f"[seed] Admin user already exists: {admin.email}")
        return admin

    org = db.query(Organization).filter(Organization.name == "Veritech Diligence").first()
    if not org:
        org = Organization(name="Veritech Diligence", is_demo=False)
        db.add(org)
        db.flush()

    admin = User(
        organization_id=org.id,
        email=settings.initial_admin_email.lower(),
        hashed_password=hash_password(settings.initial_admin_password),
        full_name="Admin",
        role="admin",
        is_active=True,
    )
    db.add(admin)
    db.commit()
    print(f"[seed] Created admin user: {admin.email}")
    return admin


def ensure_demo_scan(db, owner: User) -> ScanRequest:
    existing = db.query(ScanRequest).filter(ScanRequest.is_demo.is_(True)).first()
    if existing:
        print(f"[seed] Demo scan already exists: {existing.id}")
        return existing

    demo_org = db.query(Organization).filter(Organization.name == "Fictional Diligence Demo Co.").first()
    if not demo_org:
        demo_org = Organization(name="Fictional Diligence Demo Co.", is_demo=True)
        db.add(demo_org)
        db.flush()

    now = datetime.now(timezone.utc)
    started = now - timedelta(minutes=8)
    scan = ScanRequest(
        user_id=owner.id,
        organization_id=demo_org.id,
        normalized_domain=DEMO_DOMAIN,
        original_input=DEMO_DOMAIN,
        notes="[SYNTHETIC DEMO DATA] Illustrative acquisition target for product walkthroughs.",
        max_pages=10,
        authorization_confirmed_at=started,
        status=SCAN_STATUS_COMPLETED,
        started_at=started,
        completed_at=now,
        is_demo=True,
    )
    db.add(scan)
    db.flush()

    db.add(
        ScanTarget(
            scan_request_id=scan.id,
            hostname=DEMO_DOMAIN,
            canonical_url=f"https://{DEMO_DOMAIN}/",
            resolved_ips=["203.0.113.10"],
        )
    )

    for task_name in COLLECTION_TASK_NAMES:
        db.add(
            ScanJob(
                scan_request_id=scan.id,
                task_name=task_name,
                status=JOB_STATUS_SUCCEEDED,
                attempts=1,
                started_at=started,
                finished_at=now,
            )
        )

    for event_type, message, offset in [
        ("scan_queued", "[DEMO] Scan queued.", 0),
        ("scan_started", "[DEMO] Scan started.", 1),
        ("http_checks_succeeded", "[DEMO] HTTP checks completed.", 2),
        ("crawl_succeeded", "[DEMO] Crawl completed: 10 pages.", 3),
        ("dns_email_posture_succeeded", "[DEMO] DNS/email posture completed.", 4),
        ("browser_render_succeeded", "[DEMO] Browser render completed.", 5),
        ("rules_engine_succeeded", "[DEMO] Rules engine completed: 6 findings.", 6),
        ("scan_completed", "[DEMO] Scan finished with status: completed.", 7),
    ]:
        db.add(
            ScanEvent(
                scan_request_id=scan.id,
                event_type=event_type,
                message=message,
                created_at=started + timedelta(seconds=offset * 20),
            )
        )

    # --- evidence + observations -------------------------------------------------
    http_evidence = EvidenceItem(
        scan_request_id=scan.id,
        category="http",
        source_type="http_response",
        source_url_or_identifier=f"https://{DEMO_DOMAIN}/",
        captured_at=now,
        confidence="high",
        normalized_payload_json={"status_code": 200, "is_https": True},
        human_readable_summary="[DEMO] 200 response over HTTPS. Missing Content-Security-Policy header.",
        raw_response_reference=None,
    )
    db.add(http_evidence)
    db.flush()

    db.add(
        HTTPObservation(
            scan_request_id=scan.id,
            url=f"https://{DEMO_DOMAIN}/",
            final_url=f"https://{DEMO_DOMAIN}/",
            status_code=200,
            redirect_chain=[],
            headers={"server": "nginx", "content-type": "text/html"},
            content_type="text/html",
            server_header="nginx",
            strict_transport_security="max-age=31536000",
            content_security_policy=None,
            x_content_type_options="nosniff",
            x_frame_options="SAMEORIGIN",
            referrer_policy="strict-origin-when-cross-origin",
            response_duration_ms=210,
            is_https=True,
        )
    )

    email_evidence = EvidenceItem(
        scan_request_id=scan.id,
        category="email_posture",
        source_type="spf_dmarc_lookup",
        source_url_or_identifier=f"{DEMO_DOMAIN} / _dmarc.{DEMO_DOMAIN}",
        captured_at=now,
        confidence="high",
        normalized_payload_json={"spf_present": True, "dmarc_present": False},
        human_readable_summary="[DEMO] SPF record present. No DMARC record found.",
        raw_response_reference=None,
    )
    db.add(email_evidence)
    db.flush()

    db.add(
        DNSObservation(
            scan_request_id=scan.id, record_type="SPF", name=DEMO_DOMAIN,
            values=["v=spf1 include:_spf.google.com ~all"], lookup_successful=True,
            spf_record="v=spf1 include:_spf.google.com ~all",
        )
    )
    db.add(
        DNSObservation(
            scan_request_id=scan.id, record_type="DMARC", name=f"_dmarc.{DEMO_DOMAIN}",
            values=[], lookup_successful=True, dmarc_record=None,
        )
    )

    homepage_evidence = EvidenceItem(
        scan_request_id=scan.id,
        category="crawl",
        source_type="page_snapshot",
        source_url_or_identifier=f"https://{DEMO_DOMAIN}/",
        captured_at=now,
        confidence="high",
        normalized_payload_json={"canonical_url": None, "meta_description": None},
        human_readable_summary="[DEMO] Homepage snapshot: no canonical tag, no meta description.",
        raw_response_reference=None,
    )
    db.add(homepage_evidence)
    db.flush()

    crawl_evidence = EvidenceItem(
        scan_request_id=scan.id,
        category="crawl",
        source_type="bounded_crawl",
        source_url_or_identifier=f"https://{DEMO_DOMAIN}/",
        captured_at=now,
        confidence="high",
        normalized_payload_json={"pages_fetched": 10, "max_pages": 10, "error_count": 1},
        human_readable_summary="[DEMO] Crawled 10 of a maximum 10 same-origin pages; 1 returned an error.",
        raw_response_reference=None,
    )
    db.add(crawl_evidence)
    db.flush()

    demo_pages = [
        ("/", 200, "Example Acquisition Target — Home", None, 0),
        ("/about", 200, "About Us", "https://" + DEMO_DOMAIN + "/about", 1),
        ("/pricing", 200, "Pricing", "https://" + DEMO_DOMAIN + "/pricing", 1),
        ("/blog", 200, "Blog", "https://" + DEMO_DOMAIN + "/blog", 1),
        ("/blog/post-1", 200, "First Post", None, 1),
        ("/contact", 200, "Contact", None, 1),
        ("/careers", 404, None, None, 0),
        ("/support", 200, "Support", None, 1),
        ("/features", 200, "Features", None, 1),
        ("/legal/privacy", 200, "Privacy Policy", None, 1),
    ]
    for path, status_code, title, canonical, h1_count in demo_pages:
        db.add(
            Page(
                scan_request_id=scan.id,
                url=f"https://{DEMO_DOMAIN}{path}",
                final_url=f"https://{DEMO_DOMAIN}{path}",
                status_code=status_code,
                content_type="text/html" if status_code == 200 else None,
                canonical_url=canonical,
                title=title,
                meta_description="Demo description." if path != "/" else None,
                h1_count=h1_count,
                first_h1=title,
                html_lang="en",
                meta_viewport_present=True,
                internal_link_count=8,
                external_link_count=2,
                response_duration_ms=180,
            )
        )

    tech_items = [
        ("WordPress", "cms", 'HTML contains "wp-content"', "high"),
        ("Google Analytics", "analytics", 'HTML contains "google-analytics.com"', "high"),
        ("Cloudflare", "cdn_security", "Response header cf-ray is present", "medium"),
        ("Stripe", "payment", 'HTML contains "js.stripe.com"', "high"),
    ]
    for name, category, method, confidence in tech_items:
        tech_evidence = EvidenceItem(
            scan_request_id=scan.id,
            category="technology",
            source_type="technology_detection",
            source_url_or_identifier=name,
            captured_at=now,
            confidence=confidence,
            normalized_payload_json={"technology_name": name, "category": category},
            human_readable_summary=f"[DEMO] Detected {name} via: {method}.",
            raw_response_reference=None,
        )
        db.add(tech_evidence)
        db.flush()
        db.add(
            TechnologyObservation(
                scan_request_id=scan.id,
                technology_name=name,
                category=category,
                detection_method=method,
                confidence=confidence,
                evidence_item_id=tech_evidence.id,
            )
        )

    perf_evidence = EvidenceItem(
        scan_request_id=scan.id,
        category="performance",
        source_type="performance_measurement",
        source_url_or_identifier=f"https://{DEMO_DOMAIN}/",
        captured_at=now,
        confidence="high",
        normalized_payload_json={"response_duration_ms": 210, "html_bytes": 84213},
        human_readable_summary="[DEMO] Local performance measurements recorded. PageSpeed not configured.",
        raw_response_reference=None,
    )
    db.add(perf_evidence)
    db.flush()

    db.add(
        PerformanceObservation(
            scan_request_id=scan.id,
            provider="local",
            configured=False,
            response_duration_ms=210,
            html_bytes=84213,
            third_party_domain_count=12,
            js_resource_count=18,
        )
    )

    # --- findings -------------------------------------------------------------------
    demo_findings = [
        {
            "rule_key": "missing_dmarc", "category": "email_deliverability", "severity": "medium",
            "confidence": "high", "title": "No DMARC record found",
            "impact": "[DEMO] Observation: no _dmarc TXT record found. Interpretation: no policy instruction for unauthenticated mail.",
            "recommended_next_step": "Inventory sending services before publishing a DMARC monitoring policy.",
            "evidence": [email_evidence],
        },
        {
            "rule_key": "missing_csp", "category": "security_posture", "severity": "low",
            "confidence": "high", "title": "No Content-Security-Policy header (hardening opportunity)",
            "impact": "[DEMO] Observation: homepage response has no CSP header. This is a hardening opportunity, not a confirmed vulnerability.",
            "recommended_next_step": "Evaluate introducing a CSP as part of a broader hardening pass.",
            "evidence": [http_evidence],
        },
        {
            "rule_key": "homepage_missing_canonical", "category": "indexability", "severity": "low",
            "confidence": "high", "title": "Homepage has no canonical tag",
            "impact": "[DEMO] Observation: no canonical tag on the homepage.",
            "recommended_next_step": "Add a self-referencing canonical tag.",
            "evidence": [homepage_evidence],
        },
        {
            "rule_key": "homepage_missing_meta_description", "category": "on_page_seo", "severity": "low",
            "confidence": "high", "title": "Homepage missing meta description",
            "impact": "[DEMO] Observation: no meta description tag on the homepage.",
            "recommended_next_step": "Author a concise, unique meta description.",
            "evidence": [homepage_evidence],
        },
        {
            "rule_key": "excessive_third_party_domains", "category": "dependency_management", "severity": "medium",
            "confidence": "medium", "title": "12 third-party request domains observed on the homepage",
            "impact": "[DEMO] Observation: 12 distinct third-party domains requested by the homepage.",
            "recommended_next_step": "Review each dependency for ownership, purpose, and privacy posture.",
            "evidence": [perf_evidence],
        },
        {
            "rule_key": "excessive_crawl_errors", "category": "site_reliability", "severity": "low",
            "confidence": "high", "title": "1 crawled page returned a 4xx/5xx status",
            "impact": "[DEMO] Observation: /careers returned HTTP 404 during the crawl.",
            "recommended_next_step": "Investigate broken links found during the crawl.",
            "evidence": [crawl_evidence],
        },
    ]

    for fd in demo_findings:
        rule_row = (
            db.query(FindingRule)
            .filter(FindingRule.rule_key == fd["rule_key"], FindingRule.version == 1)
            .first()
        )
        if not rule_row:
            rule_row = FindingRule(
                rule_key=fd["rule_key"], version=1, title=fd["title"], category=fd["category"],
                default_severity=fd["severity"], default_confidence=fd["confidence"], description=fd["impact"],
            )
            db.add(rule_row)
            db.flush()

        finding = Finding(
            scan_request_id=scan.id, rule_id=rule_row.id, rule_version=1, category=fd["category"],
            severity=fd["severity"], confidence=fd["confidence"], title=fd["title"], impact=fd["impact"],
            recommended_next_step=fd["recommended_next_step"],
        )
        db.add(finding)
        db.flush()
        for ev in fd["evidence"]:
            db.add(FindingEvidence(finding_id=finding.id, evidence_item_id=ev.id))

    db.add(
        Report(
            scan_request_id=scan.id,
            format="html",
            storage_path=f"{scan.id}/report.html",
            generated_at=now,
        )
    )

    db.commit()
    print(f"[seed] Created synthetic demo scan {scan.id} for domain {DEMO_DOMAIN}")
    return scan


def main() -> None:
    parser = argparse.ArgumentParser(description=f"{get_settings().product_name} seed / admin bootstrap")
    parser.add_argument("--admin-only", action="store_true", help="Only create the admin user, skip demo data")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        admin = ensure_admin(db)
        if not args.admin_only:
            ensure_demo_scan(db, admin)
        print("[seed] Done.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
