import respx
from httpx import Response

from app.collectors.robots_sitemap import _parse_sitemap_xml, _summarize_lastmods, run_robots_and_sitemap_checks
from app.models.evidence import EvidenceItem


@respx.mock
def test_exposure_probes_recorded_as_evidence(db, scan_request):
    respx.get("https://example.com/robots.txt").mock(return_value=Response(404))
    respx.get("https://example.com/sitemap.xml").mock(return_value=Response(404))
    respx.get("https://example.com/xmlrpc.php").mock(
        return_value=Response(405, text="XML-RPC server accepts POST requests only.")
    )
    respx.get("https://example.com/wp-json/").mock(
        return_value=Response(200, json={"name": "Example", "namespaces": ["wp/v2"]})
    )

    summary = run_robots_and_sitemap_checks(db, scan_request.id, "https://example.com/", max_pages=10)

    assert summary["exposure_checks"]["xmlrpc"]["status_code"] == 405
    assert summary["exposure_checks"]["wp_json"]["status_code"] == 200

    evidence = (
        db.query(EvidenceItem)
        .filter(EvidenceItem.scan_request_id == scan_request.id, EvidenceItem.category == "exposure")
        .first()
    )
    assert evidence is not None
    assert "namespaces" in evidence.normalized_payload_json["wp_json"]["body_excerpt"]


@respx.mock
def test_robots_body_excerpt_surfaced_for_technology_detection(db, scan_request):
    respx.get("https://example.com/robots.txt").mock(
        return_value=Response(200, text="User-agent: *\nDisallow: /wc-logs/\n")
    )
    respx.get("https://example.com/sitemap.xml").mock(return_value=Response(404))
    respx.get("https://example.com/xmlrpc.php").mock(return_value=Response(404))
    respx.get("https://example.com/wp-json/").mock(return_value=Response(404))

    summary = run_robots_and_sitemap_checks(db, scan_request.id, "https://example.com/", max_pages=10)

    assert "wc-logs" in summary["robots_body_excerpt"]


# --- Priority 5b: sitemap freshness (<lastmod>) ----------------------------------


def test_parse_sitemap_xml_extracts_lastmod():
    xml = (
        '<?xml version="1.0"?><urlset>'
        '<url><loc>https://example.com/</loc><lastmod>2020-01-01</lastmod></url>'
        '<url><loc>https://example.com/new</loc><lastmod>2026-06-01T12:00:00+00:00</lastmod></url>'
        '<url><loc>https://example.com/no-lastmod</loc></url>'
        "</urlset>"
    )
    kind, urls, lastmods, errors = _parse_sitemap_xml(xml)
    assert kind == "urlset"
    assert urls == ["https://example.com/", "https://example.com/new", "https://example.com/no-lastmod"]
    assert lastmods == ["2020-01-01", "2026-06-01T12:00:00+00:00"]
    assert errors == []


def test_summarize_lastmods_picks_newest_and_oldest_and_drops_unparseable():
    summary = _summarize_lastmods(["2020-01-01", "2026-06-01T12:00:00+00:00", "not-a-date"])
    assert summary == {
        "lastmod_count": 2,
        "newest_lastmod": "2026-06-01T12:00:00+00:00",
        "oldest_lastmod": "2020-01-01",
    }


def test_summarize_lastmods_empty_when_none_present():
    assert _summarize_lastmods([]) == {"lastmod_count": 0, "newest_lastmod": None, "oldest_lastmod": None}


@respx.mock
def test_sitemap_freshness_recorded_in_evidence(db, scan_request):
    respx.get("https://example.com/robots.txt").mock(return_value=Response(404))
    respx.get("https://example.com/sitemap.xml").mock(
        return_value=Response(
            200,
            text=(
                '<?xml version="1.0"?><urlset>'
                '<url><loc>https://example.com/</loc><lastmod>2020-01-01</lastmod></url>'
                '<url><loc>https://example.com/new</loc><lastmod>2026-06-01</lastmod></url>'
                "</urlset>"
            ),
        )
    )
    respx.get("https://example.com/xmlrpc.php").mock(return_value=Response(404))
    respx.get("https://example.com/wp-json/").mock(return_value=Response(404))

    run_robots_and_sitemap_checks(db, scan_request.id, "https://example.com/", max_pages=10)

    sitemap_evidence = (
        db.query(EvidenceItem)
        .filter(EvidenceItem.scan_request_id == scan_request.id, EvidenceItem.source_type == "sitemap_xml")
        .first()
    )
    assert sitemap_evidence.normalized_payload_json["lastmod_count"] == 2
    assert sitemap_evidence.normalized_payload_json["newest_lastmod"] == "2026-06-01"
    assert sitemap_evidence.normalized_payload_json["oldest_lastmod"] == "2020-01-01"
