from datetime import datetime, timezone

import pytest

from app.models.evidence import EvidenceItem
from app.models.finding import Finding, FindingEvidence
from app.models.observation import (
    DNSObservation,
    HTTPObservation,
    PerformanceObservation,
    TechnologyObservation,
    ThirdPartyDependency,
)
from app.models.page import Page
from app.rules.engine import run_rules_engine


def _evidence(db, scan, category, source_type, summary="test evidence", payload=None):
    item = EvidenceItem(
        scan_request_id=scan.id,
        category=category,
        source_type=source_type,
        source_url_or_identifier="https://example.com/",
        captured_at=datetime.now(timezone.utc),
        confidence="high",
        normalized_payload_json=payload if payload is not None else {},
        human_readable_summary=summary,
    )
    db.add(item)
    db.flush()
    return item


def _accessibility_evidence(
    db,
    scan,
    image_count=0,
    images_missing_alt_count=0,
    labelable_field_count=0,
    fields_missing_labels_count=0,
    overlay_widget_vendor=None,
):
    return _evidence(
        db,
        scan,
        "accessibility",
        "static_accessibility_scan",
        payload={
            "image_count": image_count,
            "images_missing_alt_count": images_missing_alt_count,
            "labelable_field_count": labelable_field_count,
            "fields_missing_labels_count": fields_missing_labels_count,
            "overlay_widget_vendor": overlay_widget_vendor,
        },
    )


def test_missing_dmarc_and_spf_produce_findings(db, scan_request):
    _evidence(db, scan_request, "email_posture", "spf_dmarc_lookup")
    db.add(DNSObservation(scan_request_id=scan_request.id, record_type="SPF", name="example.com", values=[], lookup_successful=True, spf_record=None))
    db.add(DNSObservation(scan_request_id=scan_request.id, record_type="DMARC", name="_dmarc.example.com", values=[], lookup_successful=True, dmarc_record=None))
    db.commit()

    run_rules_engine(db, scan_request)

    titles = {f.title for f in db.query(Finding).filter(Finding.scan_request_id == scan_request.id).all()}
    assert "No DMARC record found" in titles
    assert "No SPF record found" in titles


def test_dmarc_policy_none_produces_low_severity_finding(db, scan_request):
    _evidence(db, scan_request, "email_posture", "spf_dmarc_lookup")
    db.add(
        DNSObservation(
            scan_request_id=scan_request.id, record_type="DMARC", name="_dmarc.example.com",
            values=["v=DMARC1; p=none"], lookup_successful=True,
            dmarc_record="v=DMARC1; p=none", dmarc_policy="none",
        )
    )
    db.commit()

    run_rules_engine(db, scan_request)

    finding = (
        db.query(Finding)
        .filter(Finding.scan_request_id == scan_request.id, Finding.title == "DMARC policy set to p=none")
        .first()
    )
    assert finding is not None
    assert finding.severity == "low"
    assert finding.confidence == "high"
    assert finding.rule_version == 2


def test_dmarc_record_with_no_policy_tag_fires_as_malformed(db, scan_request):
    """v2 regression test: a DMARC record with no p= tag at all (e.g.
    "v=DMARC1;") used to silently pass — dmarc_policy_none only checked
    `policy != "none"`, which is true for None too, so a malformed record
    with no usable policy never fired anything. It must now fire, and at a
    higher severity than a well-formed p=none."""
    _evidence(db, scan_request, "email_posture", "spf_dmarc_lookup")
    db.add(
        DNSObservation(
            scan_request_id=scan_request.id, record_type="DMARC", name="_dmarc.example.com",
            values=["v=DMARC1;"], lookup_successful=True,
            dmarc_record="v=DMARC1;", dmarc_policy=None,
        )
    )
    db.commit()

    run_rules_engine(db, scan_request)

    finding = (
        db.query(Finding)
        .filter(Finding.scan_request_id == scan_request.id, Finding.title.like("DMARC record is malformed%"))
        .first()
    )
    assert finding is not None
    assert finding.severity == "medium"
    assert finding.rule_version == 2
    assert finding.dollar_impact == "$$"
    assert finding.remediation_timing == "30-day"

    # missing_dmarc must not also fire — the record does exist, it's just malformed.
    assert (
        db.query(Finding)
        .filter(Finding.scan_request_id == scan_request.id, Finding.title == "No DMARC record found")
        .first()
        is None
    )


def test_dkim_selector_found_produces_ok_severity_finding(db, scan_request):
    """dkim_selector_found is a positive observation, not a risk — it uses
    the "ok" severity so report_builder keeps it out of the risk register
    (see REGISTER_SEVERITIES) while still showing it in the rules-coverage
    table."""
    _evidence(db, scan_request, "email_posture", "spf_dmarc_lookup")
    db.add(
        DNSObservation(
            scan_request_id=scan_request.id, record_type="DKIM", name="google._domainkey.example.com",
            values=["v=DKIM1; k=rsa; p=..."], lookup_successful=True, dkim_selector="google",
        )
    )
    db.commit()

    run_rules_engine(db, scan_request)

    finding = (
        db.query(Finding)
        .filter(Finding.scan_request_id == scan_request.id, Finding.title.like("DKIM signing detected%"))
        .first()
    )
    assert finding is not None
    assert finding.severity == "ok"
    assert "google" in finding.title
    assert finding.dollar_impact == "n/a"
    assert finding.remediation_timing == "n/a"


def test_dkim_selector_found_does_not_fire_without_a_hit(db, scan_request):
    _evidence(db, scan_request, "email_posture", "spf_dmarc_lookup")
    db.add(
        DNSObservation(
            scan_request_id=scan_request.id, record_type="DKIM", name="example.com",
            values=[], lookup_successful=True,
            error_message="No DKIM record found under any of 16 common selectors probed.",
        )
    )
    db.commit()

    run_rules_engine(db, scan_request)

    assert (
        db.query(Finding)
        .filter(Finding.scan_request_id == scan_request.id, Finding.category == "email_deliverability")
        .filter(Finding.title.like("DKIM%"))
        .first()
        is None
    )


def test_homepage_not_https_is_high_severity(db, scan_request):
    _evidence(db, scan_request, "http", "http_response")
    db.add(
        HTTPObservation(
            scan_request_id=scan_request.id, url="http://example.com/", final_url="http://example.com/",
            status_code=200, redirect_chain=[], headers={}, is_https=False,
        )
    )
    db.commit()

    run_rules_engine(db, scan_request)

    finding = (
        db.query(Finding)
        .filter(Finding.scan_request_id == scan_request.id, Finding.title == "Homepage served without HTTPS")
        .first()
    )
    assert finding is not None
    assert finding.severity == "high"


def test_https_with_full_security_headers_produces_no_security_findings(db, scan_request):
    _evidence(db, scan_request, "http", "http_response")
    db.add(
        HTTPObservation(
            scan_request_id=scan_request.id, url="https://example.com/", final_url="https://example.com/",
            status_code=200, redirect_chain=[], headers={}, is_https=True,
            strict_transport_security="max-age=63072000", content_security_policy="default-src 'self'",
        )
    )
    db.commit()

    run_rules_engine(db, scan_request)

    findings = db.query(Finding).filter(Finding.scan_request_id == scan_request.id).all()
    security_titles = {f.title for f in findings if f.category == "security_posture"}
    assert security_titles == set()


def test_excessive_third_party_domains_rule(db, scan_request):
    for i in range(11):
        db.add(
            ThirdPartyDependency(
                scan_request_id=scan_request.id, hostname=f"tracker{i}.example", category="uncategorized",
                request_count=1, classification_method="test",
            )
        )
    db.commit()

    run_rules_engine(db, scan_request)

    finding = (
        db.query(Finding)
        .filter(Finding.scan_request_id == scan_request.id, Finding.category == "dependency_management")
        .first()
    )
    assert finding is not None
    assert finding.severity == "medium"


def test_excessive_crawl_errors_rule(db, scan_request):
    crawl_evidence = _evidence(db, scan_request, "crawl", "bounded_crawl")
    for i in range(6):
        db.add(
            Page(
                scan_request_id=scan_request.id, url=f"https://example.com/broken-{i}",
                status_code=404,
            )
        )
    db.add(Page(scan_request_id=scan_request.id, url="https://example.com/", status_code=200))
    db.commit()

    run_rules_engine(db, scan_request)

    finding = (
        db.query(Finding)
        .filter(Finding.scan_request_id == scan_request.id, Finding.category == "site_reliability")
        .first()
    )
    assert finding is not None
    assert finding.evidence_links[0].evidence_item_id == crawl_evidence.id


def test_pagespeed_rule_only_fires_when_configured(db, scan_request):
    db.add(
        PerformanceObservation(
            scan_request_id=scan_request.id, provider="local", configured=False, mobile_performance_score=30,
        )
    )
    db.commit()
    run_rules_engine(db, scan_request)
    assert (
        db.query(Finding)
        .filter(Finding.scan_request_id == scan_request.id, Finding.category == "performance")
        .first()
        is None
    )


def test_pagespeed_rule_fires_when_configured_and_below_threshold(db, scan_request):
    _evidence(db, scan_request, "performance", "performance_measurement")
    db.add(
        PerformanceObservation(
            scan_request_id=scan_request.id, provider="google_pagespeed", configured=True, mobile_performance_score=25,
        )
    )
    db.commit()
    run_rules_engine(db, scan_request)
    finding = (
        db.query(Finding)
        .filter(Finding.scan_request_id == scan_request.id, Finding.category == "performance")
        .first()
    )
    assert finding is not None
    assert finding.severity == "medium"


# --- LCP thresholds (Core Web Vitals), independent of overall PageSpeed score ---


def test_lcp_poor_mobile_fires_above_4000ms(db, scan_request):
    _evidence(db, scan_request, "performance", "performance_measurement")
    db.add(
        PerformanceObservation(
            scan_request_id=scan_request.id, provider="google_pagespeed", configured=True, mobile_lcp_ms=6015,
            mobile_performance_score=73,
        )
    )
    db.commit()
    run_rules_engine(db, scan_request)
    finding = (
        db.query(Finding)
        .filter(Finding.scan_request_id == scan_request.id, Finding.title.like("Mobile Largest Contentful Paint%"))
        .first()
    )
    assert finding is not None
    assert finding.severity == "medium"
    assert "poor" in finding.title
    assert finding.dollar_impact == "$$"
    assert finding.remediation_timing == "60-day"
    # This is the mediumandmessage.com regression: a 6s mobile LCP passing
    # because the overall mobile performance score (73) was above the
    # pagespeed_mobile_below_50 threshold. That rule must not fire here...
    assert (
        db.query(Finding)
        .filter(Finding.scan_request_id == scan_request.id, Finding.category == "performance")
        .filter(Finding.title.like("Mobile PageSpeed%"))
        .first()
        is None
    )
    # ...while the LCP-specific rule does, independent of the overall score.


def test_lcp_needs_improvement_mobile_fires_low_severity(db, scan_request):
    _evidence(db, scan_request, "performance", "performance_measurement")
    db.add(
        PerformanceObservation(
            scan_request_id=scan_request.id, provider="google_pagespeed", configured=True, mobile_lcp_ms=3200,
        )
    )
    db.commit()
    run_rules_engine(db, scan_request)
    finding = (
        db.query(Finding)
        .filter(Finding.scan_request_id == scan_request.id, Finding.title.like("Mobile Largest Contentful Paint%"))
        .first()
    )
    assert finding is not None
    assert finding.severity == "low"
    assert "needs improvement" in finding.title


def test_lcp_poor_desktop_fires_independently_of_mobile(db, scan_request):
    _evidence(db, scan_request, "performance", "performance_measurement")
    db.add(
        PerformanceObservation(
            scan_request_id=scan_request.id, provider="google_pagespeed", configured=True,
            desktop_lcp_ms=4500, mobile_lcp_ms=1200,
        )
    )
    db.commit()
    run_rules_engine(db, scan_request)
    assert (
        db.query(Finding)
        .filter(Finding.scan_request_id == scan_request.id, Finding.title.like("Desktop Largest Contentful Paint%"))
        .first()
        is not None
    )
    assert (
        db.query(Finding)
        .filter(Finding.scan_request_id == scan_request.id, Finding.title.like("Mobile Largest Contentful Paint%"))
        .first()
        is None
    )


def test_lcp_does_not_fire_at_or_below_good_threshold(db, scan_request):
    _evidence(db, scan_request, "performance", "performance_measurement")
    db.add(
        PerformanceObservation(
            scan_request_id=scan_request.id, provider="google_pagespeed", configured=True,
            desktop_lcp_ms=2000, mobile_lcp_ms=2500,
        )
    )
    db.commit()
    run_rules_engine(db, scan_request)
    assert (
        db.query(Finding)
        .filter(Finding.scan_request_id == scan_request.id, Finding.title.like("%Largest Contentful Paint%"))
        .first()
        is None
    )


def test_lcp_does_not_fire_when_pagespeed_not_configured(db, scan_request):
    db.add(
        PerformanceObservation(
            scan_request_id=scan_request.id, provider="local", configured=False, mobile_lcp_ms=9000,
        )
    )
    db.commit()
    run_rules_engine(db, scan_request)
    assert (
        db.query(Finding)
        .filter(Finding.scan_request_id == scan_request.id, Finding.title.like("%Largest Contentful Paint%"))
        .first()
        is None
    )


# --- Priority 3: every rule sets dollar_impact and remediation_timing ------------


def test_domain_and_tls_expiration_use_risk_of_inaction_dollar_band(db, scan_request):
    """domain_registration_expiring_soon and tls_certificate_expiring_or_expired
    both have a trivial direct fix cost but a severe cost of inaction — both
    should band as $$$/30-day regardless of severity branch."""
    _evidence(
        db, scan_request, "tls", "tls_certificate",
        payload={"issuer": "Let's Encrypt", "not_after": "2026-01-01T00:00:00+00:00", "days_until_expiry": 10},
    )
    _evidence(
        db, scan_request, "domain_registration", "rdap_lookup",
        payload={"registrar": "GoDaddy", "expiration_date": "2026-09-01T00:00:00Z", "days_until_expiration": 20},
    )
    db.commit()

    run_rules_engine(db, scan_request)

    tls_finding = (
        db.query(Finding).filter(Finding.scan_request_id == scan_request.id, Finding.title.like("TLS certificate%")).first()
    )
    domain_finding = (
        db.query(Finding)
        .filter(Finding.scan_request_id == scan_request.id, Finding.category == "domain_registration")
        .first()
    )
    for finding in (tls_finding, domain_finding):
        assert finding is not None
        assert finding.dollar_impact == "$$$"
        assert finding.remediation_timing == "30-day"


def test_rule_result_requires_dollar_impact_and_remediation_timing():
    """dollar_impact/remediation_timing have no dataclass default (see
    RuleResult), so a rule that forgets to set one fails immediately at
    call time instead of silently shipping a half-labeled finding —
    Priority 3 explicitly asks that every rule get both fields or the
    whole priority be held."""
    from veritech_scan_rules import RuleResult

    with pytest.raises(TypeError):
        RuleResult(
            rule_key="x", version=1, category="x", severity="low", confidence="high",
            title="x", impact="x", recommended_next_step="x",
        )


def test_every_finding_links_to_at_least_one_evidence_item(db, scan_request):
    _evidence(db, scan_request, "email_posture", "spf_dmarc_lookup")
    db.add(DNSObservation(scan_request_id=scan_request.id, record_type="SPF", name="example.com", values=[], lookup_successful=True, spf_record=None))
    db.commit()

    run_rules_engine(db, scan_request)

    findings = db.query(Finding).filter(Finding.scan_request_id == scan_request.id).all()
    assert len(findings) > 0
    for f in findings:
        links = db.query(FindingEvidence).filter(FindingEvidence.finding_id == f.id).all()
        assert len(links) >= 1


def test_rules_engine_is_idempotent_on_rerun(db, scan_request):
    _evidence(db, scan_request, "email_posture", "spf_dmarc_lookup")
    db.add(DNSObservation(scan_request_id=scan_request.id, record_type="SPF", name="example.com", values=[], lookup_successful=True, spf_record=None))
    db.commit()

    first_ids = set(run_rules_engine(db, scan_request))
    db.commit()
    second_ids = set(run_rules_engine(db, scan_request))
    db.commit()

    findings = db.query(Finding).filter(Finding.scan_request_id == scan_request.id).all()
    assert len(findings) == len(second_ids)
    assert first_ids != second_ids  # old findings were cleared and recreated


# --- Priority 1: scan coverage status -----------------------------------------


def test_scan_blocked_fires_on_non_2xx_homepage_status(db, scan_request):
    _evidence(db, scan_request, "http", "http_response")
    db.add(
        HTTPObservation(
            scan_request_id=scan_request.id, url="https://example.com/", final_url="https://example.com/",
            status_code=403, redirect_chain=[], headers={}, is_https=True,
        )
    )
    db.commit()

    run_rules_engine(db, scan_request)

    finding = (
        db.query(Finding)
        .filter(Finding.scan_request_id == scan_request.id, Finding.category == "scan_coverage")
        .first()
    )
    assert finding is not None
    assert finding.severity == "high"
    assert "blocked" in finding.title.lower()


def test_scan_blocked_fires_on_challenge_page_signature_with_2xx_status(db, scan_request):
    _evidence(
        db, scan_request, "http", "http_response",
        payload={"body_excerpt": "<html><head><title>Just a moment...</title></head></html>"},
    )
    db.add(
        HTTPObservation(
            scan_request_id=scan_request.id, url="https://example.com/", final_url="https://example.com/",
            status_code=200, redirect_chain=[], headers={}, is_https=True,
        )
    )
    db.commit()

    run_rules_engine(db, scan_request)

    finding = (
        db.query(Finding)
        .filter(Finding.scan_request_id == scan_request.id, Finding.category == "scan_coverage")
        .first()
    )
    assert finding is not None
    assert finding.severity == "high"


def test_scan_blocked_does_not_fire_on_clean_200_response(db, scan_request):
    # A shallow (0-page) crawl would independently trip scan_coverage_partial,
    # which isn't what this test is isolating — give it a full crawl so only
    # scan_blocked's own condition (status/content) is under test.
    _evidence(db, scan_request, "http", "http_response", payload={"body_excerpt": "<html>Welcome</html>"})
    db.add(
        HTTPObservation(
            scan_request_id=scan_request.id, url="https://example.com/", final_url="https://example.com/",
            status_code=200, redirect_chain=[], headers={}, is_https=True,
        )
    )
    for i in range(10):
        db.add(Page(scan_request_id=scan_request.id, url=f"https://example.com/p{i}", status_code=200))
    db.commit()

    run_rules_engine(db, scan_request)

    assert (
        db.query(Finding)
        .filter(Finding.scan_request_id == scan_request.id, Finding.category == "scan_coverage")
        .first()
        is None
    )


def test_scan_coverage_partial_fires_on_shallow_crawl(db, scan_request):
    # scan_request fixture has max_pages=10; 2 crawled is well under half.
    _evidence(db, scan_request, "http", "http_response")
    _evidence(db, scan_request, "crawl", "bounded_crawl")
    db.add(
        HTTPObservation(
            scan_request_id=scan_request.id, url="https://example.com/", final_url="https://example.com/",
            status_code=200, redirect_chain=[], headers={}, is_https=True,
        )
    )
    db.add(Page(scan_request_id=scan_request.id, url="https://example.com/", status_code=200))
    db.add(Page(scan_request_id=scan_request.id, url="https://example.com/about", status_code=200))
    db.commit()

    run_rules_engine(db, scan_request)

    finding = (
        db.query(Finding)
        .filter(Finding.scan_request_id == scan_request.id, Finding.category == "scan_coverage")
        .first()
    )
    assert finding is not None
    assert finding.severity == "medium"


def test_scan_coverage_partial_does_not_fire_on_full_crawl_with_no_failed_tasks(db, scan_request):
    _evidence(db, scan_request, "http", "http_response")
    _evidence(db, scan_request, "crawl", "bounded_crawl")
    db.add(
        HTTPObservation(
            scan_request_id=scan_request.id, url="https://example.com/", final_url="https://example.com/",
            status_code=200, redirect_chain=[], headers={}, is_https=True,
        )
    )
    for i in range(10):
        db.add(Page(scan_request_id=scan_request.id, url=f"https://example.com/p{i}", status_code=200))
    db.commit()

    run_rules_engine(db, scan_request)

    assert (
        db.query(Finding)
        .filter(Finding.scan_request_id == scan_request.id, Finding.category == "scan_coverage")
        .first()
        is None
    )


# --- Priority 2: crawl error rate (ratio + floor) -------------------------------


def test_excessive_crawl_errors_fires_on_high_ratio_small_crawl(db, scan_request):
    """The hallofframes.com scenario: 1 page crawled, that page 403s — a
    100% failure rate that the old absolute-count-only rule (threshold: >5)
    missed entirely."""
    crawl_evidence = _evidence(db, scan_request, "crawl", "bounded_crawl")
    db.add(Page(scan_request_id=scan_request.id, url="https://example.com/", status_code=403))
    db.commit()

    run_rules_engine(db, scan_request)

    finding = (
        db.query(Finding)
        .filter(Finding.scan_request_id == scan_request.id, Finding.category == "site_reliability")
        .first()
    )
    assert finding is not None
    assert finding.rule_version == 2
    assert finding.evidence_links[0].evidence_item_id == crawl_evidence.id


def test_excessive_crawl_errors_does_not_fire_on_low_ratio_low_count(db, scan_request):
    _evidence(db, scan_request, "crawl", "bounded_crawl")
    db.add(Page(scan_request_id=scan_request.id, url="https://example.com/broken", status_code=404))
    for i in range(9):
        db.add(Page(scan_request_id=scan_request.id, url=f"https://example.com/p{i}", status_code=200))
    db.commit()

    run_rules_engine(db, scan_request)

    assert (
        db.query(Finding)
        .filter(Finding.scan_request_id == scan_request.id, Finding.category == "site_reliability")
        .first()
        is None
    )


# --- Priority 3a: analytics detection -------------------------------------------


def test_no_analytics_detected_fires_without_ga_gtm_or_meta_pixel(db, scan_request):
    _evidence(db, scan_request, "crawl", "page_snapshot")
    db.commit()

    run_rules_engine(db, scan_request)

    finding = (
        db.query(Finding)
        .filter(Finding.scan_request_id == scan_request.id, Finding.category == "analytics")
        .first()
    )
    assert finding is not None
    assert finding.severity == "medium"


def test_no_analytics_detected_does_not_fire_when_google_analytics_present(db, scan_request):
    _evidence(db, scan_request, "crawl", "page_snapshot")
    db.add(
        TechnologyObservation(
            scan_request_id=scan_request.id, technology_name="Google Analytics", category="analytics",
            detection_method="test", confidence="high",
        )
    )
    db.commit()

    run_rules_engine(db, scan_request)

    assert (
        db.query(Finding)
        .filter(Finding.scan_request_id == scan_request.id, Finding.category == "analytics")
        .first()
        is None
    )


# --- Priority 4a: TLS certificate expiration ------------------------------------


def test_tls_certificate_expiring_or_expired_fires_within_30_days(db, scan_request):
    _evidence(
        db, scan_request, "tls", "tls_certificate",
        payload={"issuer": "Let's Encrypt", "not_after": "2026-01-01T00:00:00+00:00", "days_until_expiry": 10},
    )
    db.commit()

    run_rules_engine(db, scan_request)

    finding = (
        db.query(Finding)
        .filter(Finding.scan_request_id == scan_request.id, Finding.category == "security_posture")
        .filter(Finding.title.like("TLS certificate%"))
        .first()
    )
    assert finding is not None
    assert finding.severity == "medium"


def test_tls_certificate_does_not_fire_when_valid_for_months(db, scan_request):
    _evidence(
        db, scan_request, "tls", "tls_certificate",
        payload={"issuer": "Let's Encrypt", "not_after": "2027-01-01T00:00:00+00:00", "days_until_expiry": 300},
    )
    db.commit()

    run_rules_engine(db, scan_request)

    assert (
        db.query(Finding)
        .filter(Finding.scan_request_id == scan_request.id, Finding.title.like("TLS certificate%"))
        .first()
        is None
    )


# --- Priority 4b: platform exposure (xmlrpc.php, wp-json) -----------------------


def test_xmlrpc_php_exposed_fires_when_endpoint_responds_as_active(db, scan_request):
    _evidence(
        db, scan_request, "exposure", "endpoint_probe",
        payload={
            "xmlrpc": {
                "url": "https://example.com/xmlrpc.php", "status_code": 405,
                "body_excerpt": "XML-RPC server accepts POST requests only.",
            },
            "wp_json": {"url": "https://example.com/wp-json/", "status_code": 404, "body_excerpt": ""},
        },
    )
    db.commit()

    run_rules_engine(db, scan_request)

    finding = (
        db.query(Finding)
        .filter(Finding.scan_request_id == scan_request.id, Finding.title.like("WordPress xmlrpc%"))
        .first()
    )
    assert finding is not None
    assert finding.severity == "low"


def test_xmlrpc_php_exposed_does_not_fire_when_not_found(db, scan_request):
    _evidence(
        db, scan_request, "exposure", "endpoint_probe",
        payload={
            "xmlrpc": {"url": "https://example.com/xmlrpc.php", "status_code": 404, "body_excerpt": "Not Found"},
            "wp_json": {"url": "https://example.com/wp-json/", "status_code": 404, "body_excerpt": ""},
        },
    )
    db.commit()

    run_rules_engine(db, scan_request)

    assert (
        db.query(Finding)
        .filter(Finding.scan_request_id == scan_request.id, Finding.title.like("WordPress xmlrpc%"))
        .first()
        is None
    )


def test_wp_json_rest_api_exposed_fires_when_root_enumerable(db, scan_request):
    _evidence(
        db, scan_request, "exposure", "endpoint_probe",
        payload={
            "xmlrpc": {"url": "https://example.com/xmlrpc.php", "status_code": 404, "body_excerpt": ""},
            "wp_json": {
                "url": "https://example.com/wp-json/", "status_code": 200,
                "body_excerpt": '{"name":"Example","namespaces":["wp/v2"]}',
            },
        },
    )
    db.commit()

    run_rules_engine(db, scan_request)

    finding = (
        db.query(Finding)
        .filter(Finding.scan_request_id == scan_request.id, Finding.title.like("WordPress REST API%"))
        .first()
    )
    assert finding is not None
    assert finding.severity == "info"


def test_wp_json_rest_api_exposed_does_not_fire_when_not_found(db, scan_request):
    _evidence(
        db, scan_request, "exposure", "endpoint_probe",
        payload={
            "xmlrpc": {"url": "https://example.com/xmlrpc.php", "status_code": 404, "body_excerpt": ""},
            "wp_json": {"url": "https://example.com/wp-json/", "status_code": 404, "body_excerpt": "Not Found"},
        },
    )
    db.commit()

    run_rules_engine(db, scan_request)

    assert (
        db.query(Finding)
        .filter(Finding.scan_request_id == scan_request.id, Finding.title.like("WordPress REST API%"))
        .first()
        is None
    )


# --- Priority 4c: domain registration -------------------------------------------


def test_domain_registration_expiring_soon_fires_within_60_days(db, scan_request):
    _evidence(
        db, scan_request, "domain_registration", "rdap_lookup",
        payload={"registrar": "GoDaddy", "expiration_date": "2026-09-01T00:00:00Z", "days_until_expiration": 20},
    )
    db.commit()

    run_rules_engine(db, scan_request)

    finding = (
        db.query(Finding)
        .filter(Finding.scan_request_id == scan_request.id, Finding.category == "domain_registration")
        .first()
    )
    assert finding is not None
    assert finding.severity == "medium"


def test_domain_registration_does_not_fire_when_far_from_expiring(db, scan_request):
    _evidence(
        db, scan_request, "domain_registration", "rdap_lookup",
        payload={"registrar": "GoDaddy", "expiration_date": "2028-01-01T00:00:00Z", "days_until_expiration": 700},
    )
    db.commit()

    run_rules_engine(db, scan_request)

    assert (
        db.query(Finding)
        .filter(Finding.scan_request_id == scan_request.id, Finding.category == "domain_registration")
        .first()
        is None
    )


# --- Priority 4d: accessibility pass ---------------------------------------------


def test_homepage_images_missing_alt_fires(db, scan_request):
    _accessibility_evidence(db, scan_request, image_count=5, images_missing_alt_count=2)
    db.commit()

    run_rules_engine(db, scan_request)

    finding = (
        db.query(Finding)
        .filter(Finding.scan_request_id == scan_request.id, Finding.title.like("%missing alt text%"))
        .first()
    )
    assert finding is not None
    assert finding.severity == "low"


def test_homepage_images_missing_alt_does_not_fire_when_all_have_alt(db, scan_request):
    _accessibility_evidence(db, scan_request, image_count=5, images_missing_alt_count=0)
    db.commit()

    run_rules_engine(db, scan_request)

    assert (
        db.query(Finding)
        .filter(Finding.scan_request_id == scan_request.id, Finding.title.like("%missing alt text%"))
        .first()
        is None
    )


def test_homepage_form_inputs_missing_labels_fires(db, scan_request):
    _accessibility_evidence(db, scan_request, labelable_field_count=3, fields_missing_labels_count=1)
    db.commit()

    run_rules_engine(db, scan_request)

    finding = (
        db.query(Finding)
        .filter(Finding.scan_request_id == scan_request.id, Finding.title.like("%missing an associated label%"))
        .first()
    )
    assert finding is not None
    assert finding.severity == "low"


def test_homepage_form_inputs_missing_labels_does_not_fire_when_all_labeled(db, scan_request):
    _accessibility_evidence(db, scan_request, labelable_field_count=3, fields_missing_labels_count=0)
    db.commit()

    run_rules_engine(db, scan_request)

    assert (
        db.query(Finding)
        .filter(Finding.scan_request_id == scan_request.id, Finding.title.like("%missing an associated label%"))
        .first()
        is None
    )


def test_accessibility_overlay_widget_detected_fires(db, scan_request):
    _accessibility_evidence(db, scan_request, overlay_widget_vendor="UserWay")
    db.commit()

    run_rules_engine(db, scan_request)

    finding = (
        db.query(Finding)
        .filter(Finding.scan_request_id == scan_request.id, Finding.title.like("Accessibility overlay widget%"))
        .first()
    )
    assert finding is not None
    assert finding.severity == "info"
    assert "UserWay" in finding.title


def test_accessibility_overlay_widget_detected_does_not_fire_when_absent(db, scan_request):
    _accessibility_evidence(db, scan_request, overlay_widget_vendor=None)
    db.commit()

    run_rules_engine(db, scan_request)

    assert (
        db.query(Finding)
        .filter(Finding.scan_request_id == scan_request.id, Finding.title.like("Accessibility overlay widget%"))
        .first()
        is None
    )


# --- Priority 4e: mixed content --------------------------------------------------


def test_mixed_content_fires_on_https_page_with_http_subresource(db, scan_request):
    db.add(
        HTTPObservation(
            scan_request_id=scan_request.id, url="https://example.com/", final_url="https://example.com/",
            status_code=200, redirect_chain=[], headers={}, is_https=True,
        )
    )
    _evidence(
        db, scan_request, "browser_render", "playwright_render",
        payload={"mixed_content_count": 1, "mixed_content_urls": ["http://example.com/tracker.js"]},
    )
    db.commit()

    run_rules_engine(db, scan_request)

    finding = (
        db.query(Finding)
        .filter(Finding.scan_request_id == scan_request.id, Finding.title.like("%plain-HTTP subresource%"))
        .first()
    )
    assert finding is not None
    assert finding.severity == "medium"


def test_mixed_content_does_not_fire_when_none_observed(db, scan_request):
    db.add(
        HTTPObservation(
            scan_request_id=scan_request.id, url="https://example.com/", final_url="https://example.com/",
            status_code=200, redirect_chain=[], headers={}, is_https=True,
        )
    )
    _evidence(
        db, scan_request, "browser_render", "playwright_render",
        payload={"mixed_content_count": 0, "mixed_content_urls": []},
    )
    db.commit()

    run_rules_engine(db, scan_request)

    assert (
        db.query(Finding)
        .filter(Finding.scan_request_id == scan_request.id, Finding.title.like("%plain-HTTP subresource%"))
        .first()
        is None
    )


def test_one_bad_rule_result_does_not_wipe_out_other_findings(db, scan_request, monkeypatch):
    """Regression test: a rule that returns a RuleResult violating a DB
    constraint (e.g. a missing required field) used to abort the whole
    transaction, silently discarding every finding from rules that had
    already fired correctly earlier in the same run.
    """
    import app.rules.engine as engine_module
    from veritech_scan_rules import RuleResult

    def broken_rule(context):
        return RuleResult(
            rule_key="test_broken_rule",
            version=1,
            category="email_deliverability",
            severity="info",
            confidence="medium",
            title="Broken test rule",
            impact="n/a",
            recommended_next_step="n/a",
            dollar_impact=None,  # violates the NOT NULL constraint on findings.dollar_impact
            remediation_timing="n/a",
        )

    def good_rule(context):
        return RuleResult(
            rule_key="test_good_rule",
            version=1,
            category="email_deliverability",
            severity="info",
            confidence="medium",
            title="Good test rule",
            impact="n/a",
            recommended_next_step="n/a",
            dollar_impact="$0",
            remediation_timing="n/a",
        )

    monkeypatch.setattr(engine_module, "all_rules", lambda: [broken_rule, good_rule])

    created_ids = run_rules_engine(db, scan_request)

    titles = {f.title for f in db.query(Finding).filter(Finding.scan_request_id == scan_request.id).all()}
    assert "Good test rule" in titles
    assert "Broken test rule" not in titles
    assert len(created_ids) == 1
