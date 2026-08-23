"""One end-to-end happy-path scan, fully offline: no real network or DNS
calls. All HTTP is mocked via respx; DNS is mocked via a fake resolver.

Playwright browser rendering is exercised separately (test_browser_render.py)
using Playwright's own route interception, since respx cannot intercept
Chromium's network stack.
"""

import dns.resolver
import respx
from httpx import Response

from app.collectors import dns_checks, http_checks, robots_sitemap, technology
from app.collectors.crawler import run_crawl
from app.models.evidence import EvidenceItem
from app.models.finding import Finding
from app.models.observation import DNSObservation, HTTPObservation
from app.models.page import Page
from app.rules.engine import run_rules_engine

HOMEPAGE_HTML = """
<html lang="en">
<head>
  <title>Acme Example — Home</title>
  <meta name="description" content="Acme Example is a fictional test site.">
  <link rel="canonical" href="https://example.com/">
</head>
<body>
  <h1>Welcome to Acme Example</h1>
  <a href="/about">About</a>
  <a href="/pricing">Pricing</a>
  <a href="https://external-site.example/">External</a>
</body>
</html>
"""

ABOUT_HTML = """
<html lang="en"><head><title>About</title></head>
<body><h1>About Us</h1><a href="/">Home</a></body></html>
"""

ROBOTS_TXT = "User-agent: *\nDisallow:\nSitemap: https://example.com/sitemap.xml\n"

SITEMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/</loc></url>
  <url><loc>https://example.com/about</loc></url>
  <url><loc>https://example.com/pricing</loc></url>
</urlset>
"""


class FakeDNSRData:
    def __init__(self, text):
        self._text = text

    def to_text(self):
        return self._text


class FakeDNSResolver:
    def __init__(self, records):
        self.records = records
        self.lifetime = 5
        self.timeout = 5

    def resolve(self, name, record_type):
        key = (name, record_type)
        if key not in self.records:
            raise dns.resolver.NoAnswer()
        return [FakeDNSRData(v) for v in self.records[key]]


@respx.mock
def test_end_to_end_happy_path_scan(db, scan_request, monkeypatch):
    respx.get("https://example.com/").mock(
        return_value=Response(
            200,
            headers={
                "content-type": "text/html",
                "strict-transport-security": "max-age=63072000",
                "x-content-type-options": "nosniff",
            },
            html=HOMEPAGE_HTML,
        )
    )
    respx.get("https://example.com/about").mock(
        return_value=Response(200, headers={"content-type": "text/html"}, html=ABOUT_HTML)
    )
    respx.get("https://example.com/pricing").mock(return_value=Response(404))
    respx.get("https://example.com/robots.txt").mock(return_value=Response(200, text=ROBOTS_TXT))
    respx.get("https://example.com/sitemap.xml").mock(return_value=Response(200, text=SITEMAP_XML))
    respx.get("https://example.com/xmlrpc.php").mock(return_value=Response(404))
    respx.get("https://example.com/wp-json/").mock(return_value=Response(404))

    scan_id = scan_request.id
    canonical_url = "https://example.com/"

    http_result = http_checks.run_http_checks(db, scan_id, canonical_url)
    assert http_result["status_code"] == 200
    assert http_result["is_https"] is True

    robots_result = robots_sitemap.run_robots_and_sitemap_checks(db, scan_id, canonical_url, max_pages=10)
    assert robots_result["sitemap_count"] == 1
    assert robots_result["discovered_url_count"] == 3

    crawl_result = run_crawl(db, scan_id, canonical_url, "example.com", max_pages=10)
    assert crawl_result["pages_fetched"] >= 2

    dns_resolver = FakeDNSResolver(
        {
            ("example.com", "A"): ["93.184.216.34"],
            ("example.com", "TXT"): ['"v=spf1 include:_spf.google.com ~all"'],
            ("_dmarc.example.com", "TXT"): ['"v=DMARC1; p=none"'],
        }
    )
    dns_result = dns_checks.run_dns_and_email_checks(
        db,
        scan_id,
        "example.com",
        resolver=dns_resolver,
        rdap_lookup_fn=lambda hostname: {"domain": hostname, "registrar": None, "expiration_date": None},
    )
    assert dns_result["spf_present"] is True
    assert dns_result["dmarc_present"] is True
    assert dns_result["dmarc_policy"] == "none"

    tech_result = technology.run_technology_detection(
        db, scan_id, http_result["html_text"], http_result["headers"]
    )
    assert isinstance(tech_result["count"], int)

    db.commit()

    finding_ids = run_rules_engine(db, scan_request)
    db.commit()

    # --- assertions across the full evidence + findings graph ------------------

    assert db.query(HTTPObservation).filter_by(scan_request_id=scan_id).count() == 1
    assert db.query(Page).filter_by(scan_request_id=scan_id).count() >= 2
    assert db.query(DNSObservation).filter_by(scan_request_id=scan_id).count() >= 6
    assert db.query(EvidenceItem).filter_by(scan_request_id=scan_id).count() >= 5

    findings = db.query(Finding).filter_by(scan_request_id=scan_id).all()
    assert len(findings) == len(finding_ids)
    assert len(findings) > 0

    # DMARC p=none should be flagged; missing CSP should be flagged (hardening
    # opportunity); the pricing page 404 should NOT trigger the >5-errors rule.
    titles = {f.title for f in findings}
    assert "DMARC policy set to p=none" in titles
    assert "No Content-Security-Policy header (hardening opportunity)" in titles
    assert not any("crawled pages returned" in t for t in titles)

    # Every finding must cite real, resolvable evidence.
    for f in findings:
        assert len(f.evidence_links) >= 1
        for link in f.evidence_links:
            evidence = db.get(EvidenceItem, link.evidence_item_id)
            assert evidence is not None
            assert evidence.scan_request_id == scan_id
