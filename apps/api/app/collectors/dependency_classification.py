"""Explainable heuristics for classifying third-party request domains.

Deliberately simple substring matching against well-known hostnames — no
vendor API calls, no unsupported claims. Anything unmatched is reported as
"uncategorized" rather than guessed.
"""

CATEGORY_PATTERNS: dict[str, list[str]] = {
    "analytics": [
        "google-analytics.com", "analytics.google.com", "googletagmanager.com/gtag",
        "segment.io", "segment.com", "mixpanel.com", "amplitude.com", "hotjar.com",
        "plausible.io", "matomo",
    ],
    "tag_manager": ["googletagmanager.com"],
    "advertising": [
        "doubleclick.net", "googlesyndication.com", "googleadservices.com",
        "facebook.net", "connect.facebook.net", "ads-twitter.com", "bing.com/bat",
        "criteo.com", "taboola.com", "outbrain.com",
    ],
    "payment": ["stripe.com", "js.stripe.com", "paypal.com", "paypalobjects.com", "squareup.com"],
    "customer_support_chat": [
        "intercom.io", "widget.intercom.io", "drift.com", "zendesk.com", "zdassets.com",
        "livechatinc.com", "crisp.chat", "tawk.to", "helpscout",
    ],
    "cdn": [
        "cloudflare.com", "cdn.jsdelivr.net", "unpkg.com", "cdnjs.cloudflare.com",
        "akamai", "fastly.net", "cloudfront.net",
    ],
    "social_embeds": [
        "platform.twitter.com", "connect.facebook.net", "instagram.com/embed",
        "youtube.com/embed", "player.vimeo.com", "linkedin.com/embed",
    ],
    "tag_hosting_ecommerce": ["shopify.com", "cdn.shopify.com"],
    "forms_marketing": ["hubspot.com", "hs-scripts.com", "hsforms.com", "mailchimp.com"],
}

# Human-readable vendor names for well-known hostnames, so a report reader sees
# "Meta Pixel" or "Google Tag Manager" instead of having to recognize the raw
# hostname themselves. Not every third-party hostname will have an entry here —
# unmatched hostnames are still reported, just without a friendly name.
VENDOR_NAMES: dict[str, str] = {
    "google-analytics.com": "Google Analytics",
    "analytics.google.com": "Google Analytics",
    "googletagmanager.com": "Google Tag Manager",
    "doubleclick.net": "Google Ads (DoubleClick)",
    "googlesyndication.com": "Google AdSense",
    "googleadservices.com": "Google Ads Conversion Tracking",
    "connect.facebook.net": "Meta Pixel",
    "facebook.net": "Meta Pixel",
    "ads-twitter.com": "Twitter/X Ads",
    "criteo.com": "Criteo",
    "taboola.com": "Taboola",
    "outbrain.com": "Outbrain",
    "js.stripe.com": "Stripe",
    "stripe.com": "Stripe",
    "paypal.com": "PayPal",
    "paypalobjects.com": "PayPal",
    "squareup.com": "Square",
    "widget.intercom.io": "Intercom",
    "intercom.io": "Intercom",
    "drift.com": "Drift",
    "zdassets.com": "Zendesk",
    "zendesk.com": "Zendesk",
    "livechatinc.com": "LiveChat",
    "crisp.chat": "Crisp",
    "tawk.to": "Tawk.to",
    "helpscout": "Help Scout",
    "cloudflare.com": "Cloudflare",
    "cdn.jsdelivr.net": "jsDelivr CDN",
    "unpkg.com": "unpkg CDN",
    "cdnjs.cloudflare.com": "cdnjs CDN",
    "fastly.net": "Fastly CDN",
    "cloudfront.net": "Amazon CloudFront",
    "platform.twitter.com": "Twitter/X embed",
    "instagram.com": "Instagram embed",
    "youtube.com": "YouTube embed",
    "player.vimeo.com": "Vimeo embed",
    "linkedin.com": "LinkedIn embed",
    "cdn.shopify.com": "Shopify",
    "shopify.com": "Shopify",
    "hs-scripts.com": "HubSpot",
    "hsforms.com": "HubSpot",
    "hubspot.com": "HubSpot",
    "list-manage.com": "Mailchimp",
    "chimpstatic.com": "Mailchimp",
    "mailchimp.com": "Mailchimp",
    "hotjar.com": "Hotjar",
    "mixpanel.com": "Mixpanel",
    "amplitude.com": "Amplitude",
    "segment.io": "Segment",
    "segment.com": "Segment",
    "plausible.io": "Plausible Analytics",
    "fonts.googleapis.com": "Google Fonts",
    "fonts.gstatic.com": "Google Fonts",
    "cal.com": "Cal.com",
}


def known_vendor_name(hostname: str) -> str | None:
    """Best-effort friendly vendor name for a hostname, or None if unrecognized."""
    lowered = hostname.lower()
    for pattern, name in VENDOR_NAMES.items():
        if pattern in lowered:
            return name
    return None


def classify_hostname(hostname: str) -> tuple[str, str]:
    """Returns (category, detection_method)."""
    lowered = hostname.lower()
    for category, patterns in CATEGORY_PATTERNS.items():
        for pattern in patterns:
            if pattern in lowered:
                return category, f"hostname matched known pattern {pattern!r}"
    return "uncategorized", "no known third-party pattern matched"
