from app.collectors.technology import _detect_wp_asset_versions, run_technology_detection
from app.models.evidence import EvidenceItem


def _detected_names(db, scan_request, html_text, headers=None, rendered_html=None, robots_body_excerpt=None):
    run_technology_detection(db, scan_request.id, html_text, headers or {}, rendered_html, robots_body_excerpt)
    db.flush()
    rows = (
        db.query(EvidenceItem)
        .filter(EvidenceItem.scan_request_id == scan_request.id, EvidenceItem.category == "technology")
        .all()
    )
    return {row.normalized_payload_json["technology_name"] for row in rows}


def test_hubspot_does_not_fire_on_prose_mention(db, scan_request):
    # A page merely discussing HubSpot (e.g. "we review sites built on Shopify,
    # HubSpot, ...") must not be reported as actually running HubSpot.
    html = "<p>Our review covers Salesforce, HubSpot, Cloudinary, and SAML SSO patterns.</p>"
    assert "HubSpot" not in _detected_names(db, scan_request, html)


def test_hubspot_fires_on_real_embed():
    from app.collectors.technology import DETECTION_RULES

    detector = next(d for name, _, _, d in DETECTION_RULES if name == "HubSpot")
    assert detector('<script src="https://js.hs-scripts.com/12345.js"></script>', {}) is not None
    assert detector("<script>_hsq.push(['setPath', '/']);</script>", {}) is not None
    assert detector("<p>We use HubSpot for CRM.</p>", {}) is None


def test_woocommerce_detected_via_robots_txt_wc_logs_disclosure(db, scan_request):
    # This exact scenario is what hallofframes.com's robots.txt revealed:
    # WooCommerce paths with no trace of it in the (WAF-stripped) HTML itself.
    robots_excerpt = "User-agent: *\nDisallow: /cart/\nDisallow: /checkout/\nDisallow: /wc-logs/\n"
    names = _detected_names(db, scan_request, html_text="<html></html>", robots_body_excerpt=robots_excerpt)
    assert "WooCommerce" in names


def test_ga4_gtag_script_tag_detected_as_google_analytics():
    from app.collectors.technology import DETECTION_RULES

    detector = next(d for name, _, _, d in DETECTION_RULES if name == "Google Analytics")
    assert detector('<script src="https://www.googletagmanager.com/gtag/js?id=G-ABC123"></script>', {}) is not None


def test_wp_asset_version_extraction_finds_plugin_and_theme():
    html = (
        '<link rel="stylesheet" href="/wp-content/plugins/contact-form-7/style.css?ver=5.8.4">'
        '<script src="/wp-content/themes/astra/js/main.js?ver=3.1.0"></script>'
    )
    results = _detect_wp_asset_versions(html)
    assert {"name": "contact-form-7", "type": "plugin", "version": "5.8.4"} in results
    assert {"name": "astra", "type": "theme", "version": "3.1.0"} in results


def test_wp_asset_version_extraction_ignores_assets_without_version():
    html = '<link rel="stylesheet" href="/wp-content/plugins/contact-form-7/style.css">'
    assert _detect_wp_asset_versions(html) == []


def test_wp_asset_version_creates_technology_evidence(db, scan_request):
    html = '<script src="/wp-content/plugins/woocommerce/assets/js/frontend.js?ver=8.2.1"></script>'
    result = run_technology_detection(db, scan_request.id, html, {})
    labels = {d["technology_name"] for d in result["detected"]}
    assert any("woocommerce 8.2.1" in label.lower() for label in labels)
