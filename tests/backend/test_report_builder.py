from datetime import datetime, timezone

from app.models.evidence import EvidenceItem
from app.models.observation import DNSObservation, HTTPObservation, TechnologyObservation
from app.models.page import Page
from app.rules.engine import run_rules_engine
from app.services.report_builder import _detect_platform, _path_key, build_report


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


# --- Priority 4c: "ok"-severity findings never reach the risk register -----------


def test_ok_severity_finding_excluded_from_register_but_shown_in_rules_checked(db, scan_request):
    _evidence(db, scan_request, "email_posture", "spf_dmarc_lookup")
    db.add(
        DNSObservation(
            scan_request_id=scan_request.id, record_type="DKIM", name="google._domainkey.example.com",
            values=["v=DKIM1; k=rsa; p=..."], lookup_successful=True, dkim_selector="google",
        )
    )
    db.commit()
    run_rules_engine(db, scan_request)
    db.commit()

    report = build_report(db, scan_request)

    assert not any(f.title.startswith("DKIM signing detected") for f in report.findings)
    assert report.severity_counts.info == 0

    coverage_row = next(r for r in report.rules_checked["rules"] if r["rule_key"] == "dkim_selector_found")
    assert coverage_row["fired"] is True
    assert coverage_row["positive_observation"] is True


# --- Priority 6b: URL normalization (index.html <-> /) ---------------------------


def test_path_key_normalizes_index_html_and_trailing_slash():
    assert _path_key("https://example.com/") == "/"
    assert _path_key("https://example.com/index.html") == "/"
    assert _path_key("https://example.com/index.htm") == "/"
    assert _path_key("https://example.com/about/") == "/about"
    assert _path_key("https://example.com/about/index.html") == "/about"


def test_sitemap_cross_check_treats_index_html_as_declared(db, scan_request):
    robots_evidence = _evidence(
        db, scan_request, "robots_sitemap", "robots_txt",
        payload={"disallow_rules": []},
    )
    sitemap_evidence = _evidence(
        db, scan_request, "robots_sitemap", "sitemap_xml",
        payload={"discovered_urls": ["https://example.com/"]},
    )
    db.add(Page(scan_request_id=scan_request.id, url="https://example.com/index.html", status_code=200))
    db.add(
        HTTPObservation(
            scan_request_id=scan_request.id, url="https://example.com/", final_url="https://example.com/index.html",
            status_code=200, redirect_chain=[], headers={}, is_https=True,
        )
    )
    db.commit()
    run_rules_engine(db, scan_request)
    db.commit()

    report = build_report(db, scan_request)

    sc = report.crawl_indexability["sitemap_check"]
    assert sc["crawled_not_in_sitemap_count"] == 0
    assert sc["sitemap_not_crawled_count"] == 0
    assert robots_evidence.id and sitemap_evidence.id  # sanity: fixtures were used


# --- Priority 5d: platform/CMS detection ------------------------------------------


def test_detect_platform_prefers_highest_confidence_cms_match(db, scan_request):
    tech_obs = [
        TechnologyObservation(
            scan_request_id=scan_request.id, technology_name="React", category="frontend_framework",
            detection_method="x", confidence="medium",
        ),
        TechnologyObservation(
            scan_request_id=scan_request.id, technology_name="WordPress", category="cms",
            detection_method="wp-content path found", confidence="high",
        ),
    ]
    platform = _detect_platform(tech_obs, pages=[])
    assert platform["name"] == "WordPress"
    assert platform["heuristic"] is False


def test_detect_platform_falls_back_to_static_html_heuristic(db, scan_request):
    pages = [
        Page(scan_request_id=scan_request.id, url="https://example.com/index.html"),
        Page(scan_request_id=scan_request.id, url="https://example.com/services.html"),
    ]
    platform = _detect_platform([], pages)
    assert platform is not None
    assert platform["category"] == "static_html"
    assert platform["heuristic"] is True


def test_detect_platform_returns_none_when_no_signal(db, scan_request):
    pages = [Page(scan_request_id=scan_request.id, url="https://example.com/app")]
    assert _detect_platform([], pages) is None


# --- Priority 5a: redirect chain flagging -----------------------------------------


def test_redirect_chain_flagged_when_it_mixes_schemes(db, scan_request):
    _evidence(db, scan_request, "http", "http_response")
    db.add(
        HTTPObservation(
            scan_request_id=scan_request.id, url="http://example.com/", final_url="https://example.com/",
            status_code=200, is_https=True, headers={},
            redirect_chain=[{"from_url": "http://example.com/", "status_code": 301, "to_url": "https://example.com/"}],
        )
    )
    db.commit()
    run_rules_engine(db, scan_request)
    db.commit()

    report = build_report(db, scan_request)

    assert report.http_security["redirect_hop_count"] == 1
    assert report.http_security["redirect_mixes_schemes"] is True
    assert report.http_security["redirect_worth_flagging"] is True


def test_redirect_chain_not_flagged_for_direct_response(db, scan_request):
    _evidence(db, scan_request, "http", "http_response")
    db.add(
        HTTPObservation(
            scan_request_id=scan_request.id, url="https://example.com/", final_url="https://example.com/",
            status_code=200, is_https=True, headers={}, redirect_chain=[],
        )
    )
    db.commit()
    run_rules_engine(db, scan_request)
    db.commit()

    report = build_report(db, scan_request)

    assert report.http_security["redirect_hop_count"] == 0
    assert report.http_security["redirect_worth_flagging"] is False


# --- Priority 5c: hosting fingerprint ----------------------------------------------


def test_hosting_fingerprint_surfaces_known_headers(db, scan_request):
    _evidence(db, scan_request, "http", "http_response")
    db.add(
        HTTPObservation(
            scan_request_id=scan_request.id, url="https://example.com/", final_url="https://example.com/",
            status_code=200, is_https=True, redirect_chain=[],
            headers={"Server": "nginx", "CF-RAY": "abc123-SJC", "X-Powered-By": "Express"},
        )
    )
    db.commit()
    run_rules_engine(db, scan_request)
    db.commit()

    report = build_report(db, scan_request)

    fingerprint = report.http_security["hosting_fingerprint"]
    assert fingerprint["Server"] == "nginx"
    assert fingerprint["cf-ray (Cloudflare)"] == "abc123-SJC"
    assert fingerprint["X-Powered-By"] == "Express"


# --- Priority 6d: known-limitations consolidation ---------------------------------


def test_limitations_include_scope_statement_and_unlabeled_caveats(db, scan_request):
    run_rules_engine(db, scan_request)
    db.commit()

    report = build_report(db, scan_request)

    assert report.scope_statement.startswith("This is a bounded, rate-limited public-web pre-screen")
    assert all(l.task_name == "" for l in report.limitations)
    assert len(report.limitations) == 3
