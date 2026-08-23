import respx
from httpx import Response

from app.collectors.http_checks import fetch_tls_certificate, run_http_checks
from app.models.evidence import EvidenceItem


def test_fetch_tls_certificate_without_resolved_ips_returns_error():
    result = fetch_tls_certificate("example.com", resolved_ips=[])
    assert "error" in result


def test_fetch_tls_certificate_rejects_disallowed_ip():
    # A private/loopback IP must never be dialed, even if somehow passed in —
    # defense in depth alongside the SSRF validation already performed when
    # the scan target was resolved.
    result = fetch_tls_certificate("example.com", resolved_ips=["127.0.0.1"])
    assert "error" in result


@respx.mock
def test_run_http_checks_records_body_excerpt_in_evidence(db, scan_request):
    respx.get("https://example.com/").mock(
        return_value=Response(200, headers={"content-type": "text/html"}, html="<html><body>Hello</body></html>")
    )

    result = run_http_checks(db, scan_request.id, "https://example.com/")
    assert result["status_code"] == 200

    evidence = (
        db.query(EvidenceItem)
        .filter(EvidenceItem.scan_request_id == scan_request.id, EvidenceItem.category == "http")
        .first()
    )
    assert "Hello" in evidence.normalized_payload_json["body_excerpt"]


@respx.mock
def test_run_http_checks_skips_tls_when_hostname_not_provided(db, scan_request):
    respx.get("https://example.com/").mock(return_value=Response(200, headers={"content-type": "text/html"}, html="<html></html>"))

    result = run_http_checks(db, scan_request.id, "https://example.com/")
    assert result["tls_evidence_id"] is None

    tls_evidence = (
        db.query(EvidenceItem)
        .filter(EvidenceItem.scan_request_id == scan_request.id, EvidenceItem.category == "tls")
        .first()
    )
    assert tls_evidence is None
