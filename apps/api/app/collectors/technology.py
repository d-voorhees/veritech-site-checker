"""Collector 6: local, rules-based technology detection.

Every positive match is explainable — it cites the exact header, HTML
substring, or script pattern that triggered it — and gets its own evidence
item. No vendor API calls, no unsupported claims.
"""

import re
import uuid
from datetime import datetime, timezone

from app.models.evidence import EvidenceItem
from app.models.observation import TechnologyObservation

# Each rule: (technology_name, category, confidence, detector)
# detector(html, headers_lower) -> matched detection-method string, or None.


def _html_contains(*needles: str):
    def _detector(_html: str, _headers: dict) -> str | None:
        for needle in needles:
            if needle.lower() in _html.lower():
                return f'HTML contains "{needle}"'
        return None

    return _detector


def _header_contains(header_name: str, *needles: str):
    def _detector(_html: str, headers: dict) -> str | None:
        value = headers.get(header_name.lower(), "")
        for needle in needles:
            if needle.lower() in value.lower():
                return f'Response header {header_name} contains "{needle}"'
        return None

    return _detector


def _header_present(header_name: str):
    def _detector(_html: str, headers: dict) -> str | None:
        if header_name.lower() in headers:
            return f"Response header {header_name} is present"
        return None

    return _detector


def _regex(pattern: str, description: str):
    compiled = re.compile(pattern, re.IGNORECASE)

    def _detector(html: str, _headers: dict) -> str | None:
        if compiled.search(html or ""):
            return description
        return None

    return _detector


def _any_of(*detectors):
    def _detector(html: str, headers: dict) -> str | None:
        for d in detectors:
            result = d(html, headers)
            if result:
                return result
        return None

    return _detector


DETECTION_RULES = [
    ("WordPress", "cms", "high", _any_of(
        _html_contains("wp-content", "wp-includes"),
        _regex(r'name=["\']generator["\']\s+content=["\']WordPress', "meta generator tag references WordPress"),
    )),
    ("Shopify", "ecommerce_platform", "high", _any_of(
        _html_contains("cdn.shopify.com", "Shopify.theme"),
        _header_present("x-shopify-stage"),
    )),
    ("Webflow", "website_builder", "high", _any_of(
        _html_contains("webflow.com", "w-webflow-badge"),
        _regex(r'name=["\']generator["\']\s+content=["\']Webflow', "meta generator tag references Webflow"),
    )),
    ("Wix", "website_builder", "high", _any_of(
        _html_contains("wixstatic.com", "static.parastorage.com"),
        _regex(r'name=["\']generator["\']\s+content=["\']Wix', "meta generator tag references Wix"),
    )),
    ("Squarespace", "website_builder", "high", _html_contains("static1.squarespace.com", "squarespace-cdn.com")),
    ("Drupal", "cms", "high", _any_of(
        _html_contains("/sites/default/files", "Drupal.settings"),
        _regex(r'name=["\']generator["\']\s+content=["\']Drupal', "meta generator tag references Drupal"),
    )),
    ("Ghost", "cms", "high", _any_of(
        _html_contains("/ghost/api/", "ghost.io/edition"),
        _regex(r'name=["\']generator["\']\s+content=["\']Ghost', "meta generator tag references Ghost"),
    )),
    ("Astro", "static_site_framework", "high", _any_of(
        _regex(r"astro-island|data-astro-cid", "Astro runtime marker (astro-island/data-astro-cid) found"),
        _regex(r'name=["\']generator["\']\s+content=["\']Astro', "meta generator tag references Astro"),
    )),
    ("Sanity", "headless_cms", "high", _html_contains("cdn.sanity.io")),
    ("Contentful", "headless_cms", "high", _html_contains("images.ctfassets.net", "cdn.contentful.com")),
    ("WooCommerce", "ecommerce_platform", "high", _any_of(
        _html_contains(
            "wp-content/plugins/woocommerce",
            "woocommerce_params",
            "woocommerce-page",
            "wc-ajax=",
            "wc-logs",
        ),
        _regex(r'class=["\'][^"\']*\bwoocommerce\b[^"\']*["\']', "HTML element has a woocommerce class"),
    )),
    ("BigCommerce", "ecommerce_platform", "high", _html_contains("cdn11.bigcommerce.com", "bigcommerce.com/s-")),
    ("Magento", "ecommerce_platform", "high", _html_contains("/skin/frontend/", "Mage.Cookies")),
    ("Next.js", "frontend_framework", "high", _html_contains("/_next/static", "__NEXT_DATA__")),
    ("React", "frontend_framework", "medium", _html_contains("data-reactroot", "react-dom")),
    ("Vue", "frontend_framework", "medium", _regex(r"data-v-[0-9a-f]{6,}|__vue__", "Vue-style scoped attribute or runtime marker found")),
    ("Angular", "frontend_framework", "high", _regex(r"\bng-version=", "ng-version attribute found")),
    ("Google Analytics", "analytics", "high", _html_contains(
        "google-analytics.com", "gtag(", "ga('create'", "googletagmanager.com/gtag/js"
    )),
    ("Google Tag Manager", "tag_manager", "high", _html_contains("googletagmanager.com/gtm.js")),
    ("Cloudflare", "cdn_security", "medium", _any_of(
        _header_contains("server", "cloudflare"),
        _header_present("cf-ray"),
    )),
    ("Stripe", "payment", "high", _html_contains("js.stripe.com")),
    ("HubSpot", "marketing", "high", _html_contains(
        "hs-scripts.com", "js.hubspot.com", "hsforms.net", "hs-analytics.net", "_hsq.push"
    )),
    ("Intercom", "customer_support_chat", "high", _html_contains("widget.intercom.io", "Intercom(")),
    ("Segment", "analytics", "medium", _html_contains("cdn.segment.com")),
    ("Meta Pixel", "analytics", "high", _html_contains("connect.facebook.net", "fbevents.js", "fbq(")),
    ("Microsoft Clarity", "analytics", "high", _html_contains("clarity.ms/tag")),
    ("Hotjar", "analytics", "high", _html_contains("static.hotjar.com", "hotjar.com/c/hotjar-")),
    ("LinkedIn Insight Tag", "advertising", "high", _html_contains("snap.licdn.com/li.lms-analytics")),
    ("TikTok Pixel", "advertising", "high", _html_contains("analytics.tiktok.com/i18n/pixel")),
    ("Google Ads Conversion Tracking", "advertising", "medium", _html_contains("googleadservices.com", "/pagead/conversion")),
    ("Mailchimp", "email_marketing", "high", _html_contains("list-manage.com", "chimpstatic.com")),
    ("Klaviyo", "email_marketing", "high", _html_contains("static.klaviyo.com", "_learnq.push")),
    ("Drift", "customer_support_chat", "high", _html_contains("js.driftt.com", "drift.com/embeds")),
    ("Zendesk", "customer_support_chat", "high", _html_contains("static.zdassets.com", "zendesk.com/embeddable")),
    ("PayPal", "payment", "high", _html_contains("paypal.com/sdk/js", "paypalobjects.com")),
    ("Vercel", "hosting_paas", "medium", _header_present("x-vercel-id")),
    ("Netlify", "hosting_paas", "medium", _any_of(_header_present("x-nf-request-id"), _header_contains("server", "netlify"))),
    ("Amazon CloudFront", "cdn_security", "medium", _any_of(_header_present("x-amz-cf-id"), _header_contains("via", "cloudfront"))),
    ("Fastly", "cdn_security", "medium", _header_present("x-fastly-request-id")),
    ("Google Fonts", "fonts", "medium", _html_contains("fonts.googleapis.com", "fonts.gstatic.com")),
    ("Adobe Fonts", "fonts", "medium", _html_contains("use.typekit.net")),
    ("Font Awesome", "fonts", "low", _html_contains("fontawesome.com", "font-awesome")),
    ("jQuery", "javascript_library", "medium", _regex(r"jquery(?:-|\.min|\.slim)?\.js", "jQuery script filename pattern found")),
    ("Bootstrap", "javascript_library", "low", _html_contains("bootstrap.min.css", "bootstrap.min.js", "bootstrap.bundle.js")),
    ("OneTrust", "consent_management", "high", _html_contains("cdn.cookielaw.org", "onetrust.com")),
    ("Cookiebot", "consent_management", "high", _html_contains("consent.cookiebot.com")),
    ("Typeform", "forms", "high", _html_contains("embed.typeform.com")),
    ("Calendly", "scheduling", "high", _html_contains("calendly.com/assets", "Calendly.initInlineWidget")),
    ("Cal.com", "scheduling", "high", _html_contains("app.cal.com/embed", "data-cal-link")),
    ("Algolia", "search", "medium", _html_contains("algolia.net", "algolianet.com")),
    ("reCAPTCHA", "captcha", "high", _html_contains("google.com/recaptcha", "grecaptcha")),
    ("hCaptcha", "captcha", "high", _html_contains("hcaptcha.com")),
    ("YouTube embed", "video", "medium", _html_contains("youtube.com/embed", "youtube-nocookie.com")),
    ("Vimeo embed", "video", "medium", _html_contains("player.vimeo.com")),
    ("Google Maps", "maps", "medium", _html_contains("maps.googleapis.com", "maps.google.com/maps")),
]

# WordPress asset URLs commonly carry a `?ver=X.Y.Z` cache-busting query
# string that discloses the exact plugin/theme version with no
# authentication required — this is the version data a future CVE
# cross-reference (see docs/rules-engine.md) would key off of.
_WP_ASSET_VERSION_RE = re.compile(
    r"wp-content/(plugins|themes)/([a-zA-Z0-9_\-]+)/[^\s\"'<>]*?\?[^\s\"'<>]*?\bver=([0-9][0-9a-zA-Z.\-]*)",
    re.IGNORECASE,
)


def _detect_wp_asset_versions(html: str) -> list[dict]:
    seen: set[tuple[str, str]] = set()
    results: list[dict] = []
    for kind, name, version in _WP_ASSET_VERSION_RE.findall(html or ""):
        key = (name.lower(), version)
        if key in seen:
            continue
        seen.add(key)
        results.append(
            {
                "name": name,
                "type": "plugin" if kind.lower() == "plugins" else "theme",
                "version": version,
            }
        )
    return results


def run_technology_detection(
    db,
    scan_request_id: uuid.UUID,
    html_text: str | None,
    headers: dict,
    rendered_html: str | None = None,
    robots_body_excerpt: str | None = None,
) -> dict:
    # Three sources are combined: the raw pre-JS httpx response, the
    # browser-rendered DOM, and a robots.txt excerpt. Relying on the raw
    # response alone misses anything a real browser reveals that a bare
    # HTTP GET doesn't — script tags deferred/rewritten by optimizers
    # (e.g. Cloudflare Rocket Loader), JS-gated bot-protection challenge
    # pages, or markup injected client-side — and robots.txt often names
    # platform-specific paths (e.g. "Disallow: /wp-admin/") even when a
    # WAF or CDN strips every other marker from the page itself. Detection
    # is substring/regex matching, so combining sources only widens what
    # can be found, never causes duplicates (each rule fires at most once
    # regardless of how many needles match).
    combined_html = "\n".join(t for t in (html_text, rendered_html, robots_body_excerpt) if t)
    headers_lower = {k.lower(): v for k, v in (headers or {}).items()}

    detected: list[dict] = []
    for name, category, confidence, detector in DETECTION_RULES:
        method = detector(combined_html, headers_lower)
        if not method:
            continue

        evidence = EvidenceItem(
            scan_request_id=scan_request_id,
            category="technology",
            source_type="technology_detection",
            source_url_or_identifier=name,
            captured_at=datetime.now(timezone.utc),
            confidence=confidence,
            normalized_payload_json={"technology_name": name, "category": category, "detection_method": method},
            human_readable_summary=f"Detected {name} ({category}) via: {method}.",
            raw_response_reference=None,
        )
        db.add(evidence)
        db.flush()

        db.add(
            TechnologyObservation(
                scan_request_id=scan_request_id,
                technology_name=name,
                category=category,
                detection_method=method,
                confidence=confidence,
                evidence_item_id=evidence.id,
            )
        )
        detected.append({"technology_name": name, "category": category, "confidence": confidence})

    wp_assets = _detect_wp_asset_versions(combined_html)
    for asset in wp_assets:
        label = f"{asset['name']} {asset['version']} ({asset['type']})"
        method = f"Asset URL wp-content/{asset['type']}s/{asset['name']}/... contains ?ver={asset['version']}"
        evidence = EvidenceItem(
            scan_request_id=scan_request_id,
            category="technology",
            source_type="wp_asset_version",
            source_url_or_identifier=label,
            captured_at=datetime.now(timezone.utc),
            confidence="high",
            normalized_payload_json={
                "technology_name": label,
                "category": f"wordpress_{asset['type']}",
                "detection_method": method,
                "plugin_or_theme_name": asset["name"],
                "plugin_or_theme_type": asset["type"],
                "version": asset["version"],
            },
            human_readable_summary=f"Detected WordPress {asset['type']} \"{asset['name']}\" version {asset['version']} via: {method}.",
            raw_response_reference=None,
        )
        db.add(evidence)
        db.flush()

        db.add(
            TechnologyObservation(
                scan_request_id=scan_request_id,
                technology_name=label,
                category=f"wordpress_{asset['type']}",
                detection_method=method,
                confidence="high",
                evidence_item_id=evidence.id,
            )
        )
        detected.append({"technology_name": label, "category": f"wordpress_{asset['type']}", "confidence": "high"})

    db.flush()
    return {"detected": detected, "count": len(detected), "wp_asset_versions": wp_assets}
