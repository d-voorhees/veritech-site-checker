"""Shared bounded-crawl policy: what the crawler will never fetch.

This is intentionally conservative. The product is a public-content evidence
collector, not a full crawler — it must never touch anything that looks like
an authenticated or state-changing surface.
"""

import re
from urllib.parse import urlsplit

STATIC_ASSET_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".bmp",
    ".css", ".js", ".mjs", ".map",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".pdf", ".zip", ".tar", ".gz", ".rar", ".7z",
    ".mp3", ".mp4", ".mov", ".avi", ".webm", ".wav",
    ".xml", ".json", ".csv",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
}

EXCLUDED_SCHEMES = {"mailto", "tel", "javascript", "data", "ftp", "file"}

# Path fragments that indicate account/login/checkout/cart/admin/API surfaces.
# The crawler must never traverse into these areas.
EXCLUDED_PATH_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"/wp-login",
        r"/wp-admin",
        r"/admin",
        r"/administrator",
        r"/login",
        r"/logout",
        r"/signin",
        r"/sign-in",
        r"/signup",
        r"/sign-up",
        r"/register",
        r"/account",
        r"/my-account",
        r"/profile",
        r"/dashboard",
        r"/cart",
        r"/checkout",
        r"/basket",
        r"/payment",
        r"/billing",
        r"/order",
        r"/api/",
        r"^/api$",
        r"/graphql",
        r"/webhook",
        r"/\.well-known/",
        r"/oauth",
        r"/sso",
        r"/reset-password",
        r"/forgot-password",
    ]
]


def has_excluded_extension(path: str) -> bool:
    lowered = path.lower()
    return any(lowered.endswith(ext) for ext in STATIC_ASSET_EXTENSIONS)


def has_excluded_path(path: str) -> bool:
    return any(pattern.search(path) for pattern in EXCLUDED_PATH_PATTERNS)


def is_same_origin_hostname(hostname: str, allowed_hostname: str) -> bool:
    """True if hostname matches allowed_hostname, treating `www.` and the bare
    apex domain as the same origin (sites commonly redirect between the two)."""

    def _strip_www(value: str) -> str:
        value = value.lower()
        return value[4:] if value.startswith("www.") else value

    return _strip_www(hostname) == _strip_www(allowed_hostname)


def is_crawlable_url(url: str, allowed_hostname: str) -> bool:
    """True if the crawler is permitted to fetch this URL."""
    parts = urlsplit(url)

    if parts.scheme in EXCLUDED_SCHEMES or not parts.scheme:
        return False
    if parts.scheme not in ("http", "https"):
        return False

    hostname = (parts.hostname or "").lower()
    if not is_same_origin_hostname(hostname, allowed_hostname):
        return False

    if has_excluded_extension(parts.path):
        return False

    if has_excluded_path(parts.path):
        return False

    return True


def normalize_url_no_fragment(url: str) -> str:
    parts = urlsplit(url)
    normalized_path = parts.path or "/"
    return urlsplit("")._replace(
        scheme=parts.scheme, netloc=parts.netloc, path=normalized_path, query=parts.query, fragment=""
    ).geturl()
