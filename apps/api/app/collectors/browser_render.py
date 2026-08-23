"""Collector 5: browser rendering, third-party dependency inventory, and a
static accessibility/mixed-content pass over the rendered homepage.

Homepage only, one ephemeral browser context per scan. Never submits forms,
authenticates, retains cookies beyond the context's lifetime, or stores
request bodies / user data. See docs/threat-model.md.
"""

import re
import uuid
from datetime import datetime, timezone
from urllib.parse import urlsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright
from selectolax.parser import HTMLParser

from app.collectors.dependency_classification import classify_hostname
from app.collectors.user_agent import USER_AGENT
from app.config import get_settings
from app.core.crawl_policy import is_same_origin_hostname
from app.models.evidence import EvidenceItem
from app.models.observation import ThirdPartyDependency
from app.services.artifact_storage import get_artifact_storage

# Known accessibility-overlay widget vendors, matched against script `src`.
# Per Veritech Diligence's own positioning, an overlay's presence is a
# signal to report, not a control that satisfies the underlying a11y check.
OVERLAY_WIDGET_VENDORS = {
    "accessibe": ("acsbap.com", "accessibe.com"),
    "UserWay": ("userway.org",),
    "AudioEye": ("audioeye.com",),
    "EqualWeb": ("equalweb.com",),
    "Recite Me": ("reciteme.com",),
    "AccessiBe (AccessWidget)": ("accessibe-widget.com",),
}

# Input types that never need a label (their own presence/semantics is the label).
NON_LABELABLE_INPUT_TYPES = {"hidden", "submit", "button", "reset", "image"}

# Hardcoded http:// resource references in the rendered markup. Detected via
# the static markup rather than actual network requests: modern Chromium
# auto-upgrades passive mixed content (img/audio/video) to https and blocks
# active mixed content (script/link) outright before it ever reaches the
# network layer, so `requests_seen` would systematically under-report this.
_MIXED_CONTENT_RE = re.compile(r'(?:src|href)=["\']http://([^"\'#\s]+)', re.IGNORECASE)


def _detect_mixed_content(html: str) -> list[str]:
    return sorted({f"http://{path}" for path in _MIXED_CONTENT_RE.findall(html or "")})


def _accessibility_scan(html: str) -> dict:
    tree = HTMLParser(html)

    images = tree.css("img")
    images_missing_alt = [img for img in images if img.attributes.get("alt") is None]

    label_targets: set[str] = set()
    for label in tree.css("label"):
        target = label.attributes.get("for")
        if target:
            label_targets.add(target)

    labelable_fields = []
    for tag in ("input", "select", "textarea"):
        for node in tree.css(tag):
            input_type = (node.attributes.get("type") or "text").lower()
            if tag == "input" and input_type in NON_LABELABLE_INPUT_TYPES:
                continue
            labelable_fields.append(node)

    def _has_label(node) -> bool:
        if node.attributes.get("aria-label") or node.attributes.get("aria-labelledby"):
            return True
        node_id = node.attributes.get("id")
        if node_id and node_id in label_targets:
            return True
        parent = node.parent
        while parent is not None:
            if parent.tag == "label":
                return True
            parent = parent.parent
        return False

    fields_missing_labels = [f for f in labelable_fields if not _has_label(f)]

    overlay_detected = None
    for script in tree.css("script[src]"):
        src = (script.attributes.get("src") or "").lower()
        for vendor, needles in OVERLAY_WIDGET_VENDORS.items():
            if any(needle in src for needle in needles):
                overlay_detected = vendor
                break
        if overlay_detected:
            break

    return {
        "image_count": len(images),
        "images_missing_alt_count": len(images_missing_alt),
        "labelable_field_count": len(labelable_fields),
        "fields_missing_labels_count": len(fields_missing_labels),
        "overlay_widget_vendor": overlay_detected,
    }


def run_browser_render(
    db, scan_request_id: uuid.UUID, canonical_url: str, hostname: str, route_handler=None
) -> dict:
    """`route_handler`, when provided, is registered via `page.route("**/*", ...)`
    before navigation. Production callers never pass it; tests use it to
    render a fully offline fixture page through the real Chromium engine.
    """
    settings = get_settings()
    console_errors: list[str] = []
    requests_seen: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        # Ephemeral context: no storage_state loaded or saved, discarded at
        # the end of this scan step. Cookies set during the visit exist only
        # for the lifetime of this context.
        context = browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1366, "height": 900},
            ignore_https_errors=False,
        )
        page = context.new_page()
        page.set_default_timeout(settings.scan_page_timeout_seconds * 1000)

        if route_handler is not None:
            page.route("**/*", route_handler)

        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on(
            "request",
            lambda req: requests_seen.append({"url": req.url, "resource_type": req.resource_type}),
        )

        fetch_error = None
        final_title = None
        final_url = canonical_url
        screenshot_bytes = None
        rendered_html = None
        try:
            page.goto(canonical_url, wait_until="networkidle")
            final_url = page.url
            final_title = page.title()
            rendered_html = page.content()
            screenshot_bytes = page.screenshot(full_page=False)
        except PlaywrightError as exc:
            fetch_error = str(exc)

        context.close()
        browser.close()

    client_side_redirect = final_url != canonical_url

    js_resource_count = sum(1 for r in requests_seen if r["resource_type"] == "script")
    request_hostnames: dict[str, int] = {}
    for r in requests_seen:
        h = urlsplit(r["url"]).hostname
        if h:
            request_hostnames[h] = request_hostnames.get(h, 0) + 1

    # www./apex are the same origin (sites commonly redirect between the
    # two) — a strict-equality check here would misclassify same-site
    # requests as third-party whenever the scan target and the rendered
    # page's actual host differ only by a "www." prefix.
    third_party_hosts = {
        h: count for h, count in request_hostnames.items() if not is_same_origin_hostname(h, hostname)
    }

    mixed_content_urls: list[str] = []
    if final_url.startswith("https://") and rendered_html:
        mixed_content_urls = _detect_mixed_content(rendered_html)

    screenshot_reference = None
    if screenshot_bytes:
        storage = get_artifact_storage()
        screenshot_reference = storage.save(
            f"{scan_request_id}/homepage-screenshot.png", screenshot_bytes
        )

    for host, count in third_party_hosts.items():
        category, method = classify_hostname(host)
        db.add(
            ThirdPartyDependency(
                scan_request_id=scan_request_id,
                hostname=host,
                category=category,
                request_count=count,
                classification_method=method,
            )
        )

    evidence = EvidenceItem(
        scan_request_id=scan_request_id,
        category="browser_render",
        source_type="playwright_render",
        source_url_or_identifier=canonical_url,
        captured_at=datetime.now(timezone.utc),
        confidence="high" if not fetch_error else "low",
        normalized_payload_json={
            "final_url": final_url,
            "final_title": final_title,
            "client_side_redirect": client_side_redirect,
            "console_error_count": len(console_errors),
            "console_errors": console_errors[:20],
            "js_resource_count": js_resource_count,
            "third_party_domain_count": len(third_party_hosts),
            "third_party_domains": third_party_hosts,
            "screenshot_reference": screenshot_reference,
            "fetch_error": fetch_error,
            "mixed_content_count": len(mixed_content_urls),
            "mixed_content_urls": mixed_content_urls[:20],
        },
        human_readable_summary=(
            f"Rendered homepage in an ephemeral browser context; observed {len(third_party_hosts)} "
            f"third-party request domain(s), {len(console_errors)} JavaScript console error(s), "
            f"and {len(mixed_content_urls)} plain-HTTP subresource request(s) on an HTTPS page."
            if not fetch_error
            else f"Browser rendering failed: {fetch_error}"
        ),
        raw_response_reference=screenshot_reference,
    )
    db.add(evidence)
    db.flush()

    accessibility_evidence_id = None
    if rendered_html and not fetch_error:
        a11y = _accessibility_scan(rendered_html)
        accessibility_evidence = EvidenceItem(
            scan_request_id=scan_request_id,
            category="accessibility",
            source_type="static_accessibility_scan",
            source_url_or_identifier=final_url,
            captured_at=datetime.now(timezone.utc),
            confidence="medium",
            normalized_payload_json=a11y,
            human_readable_summary=(
                f"{a11y['images_missing_alt_count']} of {a11y['image_count']} image(s) missing alt text; "
                f"{a11y['fields_missing_labels_count']} of {a11y['labelable_field_count']} form field(s) missing "
                "an associated label. "
                + (
                    f"Accessibility overlay widget detected: {a11y['overlay_widget_vendor']}."
                    if a11y["overlay_widget_vendor"]
                    else "No known accessibility overlay widget detected."
                )
            ),
            raw_response_reference=None,
        )
        db.add(accessibility_evidence)
        db.flush()
        accessibility_evidence_id = accessibility_evidence.id

    return {
        "final_url": final_url,
        "final_title": final_title,
        "client_side_redirect": client_side_redirect,
        "js_resource_count": js_resource_count,
        "third_party_domain_count": len(third_party_hosts),
        "mixed_content_count": len(mixed_content_urls),
        "screenshot_reference": screenshot_reference,
        "fetch_error": fetch_error,
        "evidence_id": evidence.id,
        "accessibility_evidence_id": accessibility_evidence_id,
        # Not persisted to evidence (would bloat normalized_payload_json) —
        # only used transiently downstream by technology_detection, which
        # otherwise only ever sees the pre-JS httpx response and misses
        # anything a real browser reveals (deferred/rewritten script tags
        # from optimizers like Cloudflare Rocket Loader, JS-gated bot
        # challenges, client-rendered markup, etc.).
        "rendered_html": rendered_html,
    }
