"""Exercises the real Chromium render path end-to-end via Playwright route
interception (no real network) — a live counterpart to
test_worker_check.py's bare launch check.
"""

from app.collectors.browser_render import run_browser_render
from app.models.evidence import EvidenceItem
from app.models.observation import ThirdPartyDependency

FIXTURE_HTML = """
<html><head><title>Acme Example</title></head>
<body>
  <h1>Acme Example</h1>
  <script src="https://www.googletagmanager.com/gtag/js?id=G-TEST"></script>
  <script src="https://js.stripe.com/v3/"></script>
</body></html>
"""


def _offline_route_handler(route):
    url = route.request.url
    if url == "https://example.com/":
        route.fulfill(status=200, content_type="text/html", body=FIXTURE_HTML)
    elif "googletagmanager.com" in url or "js.stripe.com" in url:
        route.fulfill(status=200, content_type="application/javascript", body="// stub")
    else:
        route.abort()


def test_browser_render_captures_and_classifies_third_party_domains(db, scan_request):
    result = run_browser_render(
        db, scan_request.id, "https://example.com/", "example.com", route_handler=_offline_route_handler
    )

    assert result["fetch_error"] is None
    assert result["final_title"] == "Acme Example"
    assert result["js_resource_count"] >= 2

    deps = {d.hostname: d.category for d in db.query(ThirdPartyDependency).filter_by(scan_request_id=scan_request.id)}
    assert deps.get("www.googletagmanager.com") == "tag_manager"
    assert deps.get("js.stripe.com") == "payment"

    evidence = (
        db.query(EvidenceItem)
        .filter_by(scan_request_id=scan_request.id, category="browser_render")
        .first()
    )
    assert evidence is not None
    assert evidence.normalized_payload_json["third_party_domain_count"] >= 2


WWW_FIXTURE_HTML = """
<html><head><title>Acme Example</title></head>
<body>
  <script src="https://www.example.com/assets/app.js"></script>
  <script src="https://js.stripe.com/v3/"></script>
</body></html>
"""


def _www_apex_route_handler(route):
    url = route.request.url
    if url in ("https://example.com/", "https://www.example.com/assets/app.js"):
        content_type = "text/html" if url == "https://example.com/" else "application/javascript"
        route.fulfill(status=200, content_type=content_type, body=WWW_FIXTURE_HTML if url == "https://example.com/" else "// stub")
    elif "js.stripe.com" in url:
        route.fulfill(status=200, content_type="application/javascript", body="// stub")
    else:
        route.abort()


def test_www_subdomain_request_not_misclassified_as_third_party(db, scan_request):
    """A same-site request from the www. subdomain (common when a site
    redirects/serves assets between apex and www) must not be counted as a
    third-party dependency just because it doesn't string-match the scan's
    `hostname` exactly."""
    result = run_browser_render(
        db, scan_request.id, "https://example.com/", "example.com", route_handler=_www_apex_route_handler
    )

    assert result["fetch_error"] is None

    deps = {d.hostname for d in db.query(ThirdPartyDependency).filter_by(scan_request_id=scan_request.id)}
    assert "www.example.com" not in deps
    assert "js.stripe.com" in deps


def test_run_browser_render_handles_navigation_failure_gracefully(db, scan_request):
    """A target that cannot be reached must produce a low-confidence
    evidence item rather than raising and crashing the scan.
    """

    def abort_everything(route):
        route.abort()

    result = run_browser_render(
        db, scan_request.id, "https://example.com/", "example.com", route_handler=abort_everything
    )
    assert result["fetch_error"] is not None

    deps = db.query(ThirdPartyDependency).filter_by(scan_request_id=scan_request.id).all()
    assert deps == []

    evidence = (
        db.query(EvidenceItem)
        .filter_by(scan_request_id=scan_request.id, category="browser_render")
        .first()
    )
    assert evidence.confidence == "low"


ACCESSIBILITY_FIXTURE_HTML = """
<html><head><title>Acme Example</title></head>
<body>
  <img src="/hero.png">
  <img src="/logo.png" alt="Acme logo">
  <form>
    <input type="text" name="q">
    <input type="email" name="email" aria-label="Email address">
    <label for="name-field">Name</label>
    <input type="text" id="name-field" name="name">
  </form>
  <script src="https://acsbap.com/apps/app/dist/js/app.js"></script>
  <img src="http://example.com/mixed.png">
</body></html>
"""


def _accessibility_route_handler(route):
    url = route.request.url
    if url == "https://example.com/":
        route.fulfill(status=200, content_type="text/html", body=ACCESSIBILITY_FIXTURE_HTML)
    elif "acsbap.com" in url:
        route.fulfill(status=200, content_type="application/javascript", body="// stub")
    elif url == "http://example.com/mixed.png":
        route.fulfill(status=200, content_type="image/png", body="")
    else:
        route.abort()


def test_browser_render_records_accessibility_scan_and_mixed_content(db, scan_request):
    result = run_browser_render(
        db, scan_request.id, "https://example.com/", "example.com", route_handler=_accessibility_route_handler
    )

    assert result["mixed_content_count"] == 1

    evidence = (
        db.query(EvidenceItem)
        .filter_by(scan_request_id=scan_request.id, category="accessibility")
        .first()
    )
    assert evidence is not None
    payload = evidence.normalized_payload_json
    assert payload["image_count"] == 3
    assert payload["images_missing_alt_count"] == 2  # hero.png and mixed.png have no alt
    assert payload["labelable_field_count"] == 3
    assert payload["fields_missing_labels_count"] == 1  # only the unlabeled "q" input
    assert payload["overlay_widget_vendor"] == "accessibe"
