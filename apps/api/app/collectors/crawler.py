"""Collector 3: bounded, same-origin, breadth-first crawler.

Never submits forms, authenticates, solves CAPTCHAs, or bypasses access
controls. Only follows same-origin links that pass the exclusion policy in
app/core/crawl_policy.py, up to the user-selected page budget, at the
configured per-target request delay.

When the robots_sitemap collector found sitemap URLs, they are seeded into
the queue right after the homepage — ahead of any links discovered by
crawling — so a declared sitemap takes priority over whatever the homepage
happens to link to.
"""

import time
import uuid
from collections import deque
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit

import httpx
from selectolax.parser import HTMLParser

from app.collectors.user_agent import USER_AGENT
from app.config import get_settings
from app.core.crawl_policy import is_crawlable_url, is_same_origin_hostname, normalize_url_no_fragment
from app.core.url_safety import UnsafeTargetError, revalidate_redirect_url
from app.models.evidence import EvidenceItem
from app.models.page import Page


def _extract_page_data(html: str, page_url: str, allowed_hostname: str) -> dict:
    tree = HTMLParser(html)

    title_node = tree.css_first("title")
    title = title_node.text(strip=True) if title_node else None

    meta_description = None
    meta_desc_node = tree.css_first('meta[name="description"]')
    if meta_desc_node:
        meta_description = meta_desc_node.attributes.get("content")

    robots_directives = None
    robots_node = tree.css_first('meta[name="robots"]')
    if robots_node:
        robots_directives = robots_node.attributes.get("content")

    canonical_url = None
    canonical_node = tree.css_first('link[rel="canonical"]')
    if canonical_node:
        canonical_url = canonical_node.attributes.get("href")

    html_node = tree.css_first("html")
    html_lang = html_node.attributes.get("lang") if html_node else None

    meta_viewport_present = tree.css_first('meta[name="viewport"]') is not None

    h1_nodes = tree.css("h1")
    h1_count = len(h1_nodes)
    first_h1 = h1_nodes[0].text(strip=True) if h1_nodes else None

    structured_data_types: list[str] = []
    for script in tree.css('script[type="application/ld+json"]'):
        structured_data_types.append("application/ld+json")
    if tree.css_first("[itemscope]"):
        structured_data_types.append("microdata")

    internal_links: set[str] = set()
    external_links: set[str] = set()
    discovered_links: list[str] = []
    for a in tree.css("a[href]"):
        href = a.attributes.get("href")
        if not href:
            continue
        absolute = urljoin(page_url, href)
        absolute = normalize_url_no_fragment(absolute)
        hostname = (urlsplit(absolute).hostname or "").lower()
        if is_same_origin_hostname(hostname, allowed_hostname):
            internal_links.add(absolute)
            discovered_links.append(absolute)
        elif hostname:
            external_links.add(absolute)

    return {
        "title": title,
        "meta_description": meta_description,
        "robots_directives": robots_directives,
        "canonical_url": canonical_url,
        "html_lang": html_lang,
        "meta_viewport_present": meta_viewport_present,
        "h1_count": h1_count,
        "first_h1": first_h1,
        "structured_data_types": sorted(set(structured_data_types)),
        "internal_link_count": len(internal_links),
        "external_link_count": len(external_links),
        "discovered_links": discovered_links,
    }


def _dedupe_key(url: str) -> str:
    """Collapses trailing-slash variants (`/privacy` vs `/privacy/`) to the same
    identity so a page discovered under both spellings is only crawled/reported
    once. Used only for the visited-set check — the actual URL fetched and
    recorded is whichever spelling was first discovered."""
    parts = urlsplit(url)
    path = parts.path
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return urlsplit("")._replace(
        scheme=parts.scheme, netloc=parts.netloc.lower(), path=path, query=parts.query, fragment=""
    ).geturl()


def run_crawl(
    db,
    scan_request_id: uuid.UUID,
    canonical_url: str,
    hostname: str,
    max_pages: int,
    sitemap_urls: list[str] | None = None,
) -> dict:
    settings = get_settings()
    delay = settings.scan_default_request_delay_seconds
    timeout = settings.scan_page_timeout_seconds

    homepage_url = normalize_url_no_fragment(canonical_url)
    queue: deque[str] = deque([homepage_url])
    visited: set[str] = set()
    pages_fetched = 0
    error_count = 0
    homepage_evidence_id = None

    # Seed the queue with sitemap URLs (in sitemap order) before any
    # homepage-discovered links are appended, so they're fetched first.
    seeded_keys: set[str] = {_dedupe_key(homepage_url)}
    sitemap_seeded_count = 0
    for sitemap_url in sitemap_urls or []:
        normalized = normalize_url_no_fragment(sitemap_url)
        if not is_crawlable_url(normalized, hostname):
            continue
        key = _dedupe_key(normalized)
        if key in seeded_keys:
            continue
        seeded_keys.add(key)
        queue.append(normalized)
        sitemap_seeded_count += 1

    with httpx.Client(
        follow_redirects=False, timeout=timeout, headers={"User-Agent": USER_AGENT}
    ) as client:
        while queue and pages_fetched < max_pages:
            url = queue.popleft()
            key = _dedupe_key(url)
            if key in visited:
                continue
            visited.add(key)

            if not is_crawlable_url(url, hostname):
                continue

            if pages_fetched > 0:
                time.sleep(delay)

            is_homepage = pages_fetched == 0
            page = Page(scan_request_id=scan_request_id, url=url)
            start = time.monotonic()
            try:
                revalidate_redirect_url(url)
                response = client.get(url)

                # A single same-origin-safe redirect hop is allowed (e.g.
                # trailing-slash normalization); anything else is recorded as
                # an error rather than followed further.
                hop_count = 0
                final_response = response
                final_url = url
                while final_response.is_redirect and hop_count < 3:
                    location = final_response.headers.get("location")
                    if not location:
                        break
                    next_url = urljoin(final_url, location)
                    revalidate_redirect_url(next_url)
                    next_hostname = (urlsplit(next_url).hostname or "").lower()
                    if not is_same_origin_hostname(next_hostname, hostname):
                        page.fetch_error = f"Redirected off-origin to {next_url}; not followed."
                        break
                    final_url = next_url
                    final_response = client.get(final_url)
                    hop_count += 1

                duration_ms = int((time.monotonic() - start) * 1000)
                page.final_url = final_url
                page.status_code = final_response.status_code
                page.content_type = final_response.headers.get("content-type")
                page.response_duration_ms = duration_ms

                content_type = final_response.headers.get("content-type", "")
                if final_response.status_code < 400 and "text/html" in content_type and not page.fetch_error:
                    extracted = _extract_page_data(final_response.text, final_url, hostname)
                    page.title = extracted["title"]
                    page.meta_description = extracted["meta_description"]
                    page.robots_directives = extracted["robots_directives"]
                    page.canonical_url = extracted["canonical_url"]
                    page.html_lang = extracted["html_lang"]
                    page.meta_viewport_present = extracted["meta_viewport_present"]
                    page.h1_count = extracted["h1_count"]
                    page.first_h1 = extracted["first_h1"]
                    page.structured_data_types = extracted["structured_data_types"]
                    page.internal_link_count = extracted["internal_link_count"]
                    page.external_link_count = extracted["external_link_count"]

                    for link in extracted["discovered_links"]:
                        if _dedupe_key(link) not in visited and is_crawlable_url(link, hostname):
                            queue.append(link)
                elif final_response.status_code >= 400:
                    error_count += 1

            except UnsafeTargetError as exc:
                page.fetch_error = f"Blocked by SSRF safety check: {exc}"
                error_count += 1
            except httpx.HTTPError as exc:
                page.fetch_error = f"Request failed: {exc}"
                error_count += 1

            db.add(page)
            db.flush()

            if is_homepage:
                homepage_evidence = EvidenceItem(
                    scan_request_id=scan_request_id,
                    category="crawl",
                    source_type="page_snapshot",
                    source_url_or_identifier=page.final_url or page.url,
                    captured_at=datetime.now(timezone.utc),
                    confidence="high" if not page.fetch_error else "low",
                    normalized_payload_json={
                        "url": page.url,
                        "final_url": page.final_url,
                        "status_code": page.status_code,
                        "title": page.title,
                        "meta_description": page.meta_description,
                        "canonical_url": page.canonical_url,
                        "h1_count": page.h1_count,
                        "first_h1": page.first_h1,
                        "html_lang": page.html_lang,
                        "meta_viewport_present": page.meta_viewport_present,
                        "structured_data_types": page.structured_data_types,
                        "fetch_error": page.fetch_error,
                    },
                    human_readable_summary=(
                        f"Homepage snapshot: status {page.status_code}, "
                        f"canonical tag {'present' if page.canonical_url else 'absent'}, "
                        f"meta description {'present' if page.meta_description else 'absent'}."
                    ),
                    raw_response_reference=None,
                )
                db.add(homepage_evidence)
                db.flush()
                homepage_evidence_id = homepage_evidence.id

            pages_fetched += 1

    evidence = EvidenceItem(
        scan_request_id=scan_request_id,
        category="crawl",
        source_type="bounded_crawl",
        source_url_or_identifier=canonical_url,
        captured_at=datetime.now(timezone.utc),
        confidence="high",
        normalized_payload_json={
            "pages_fetched": pages_fetched,
            "max_pages": max_pages,
            "error_count": error_count,
            "sitemap_seeded_count": sitemap_seeded_count,
        },
        human_readable_summary=(
            f"Crawled {pages_fetched} of a maximum {max_pages} same-origin pages "
            f"({sitemap_seeded_count} seeded from the sitemap); "
            f"{error_count} returned an error or fetch failure."
        ),
        raw_response_reference=None,
    )
    db.add(evidence)
    db.flush()

    return {
        "pages_fetched": pages_fetched,
        "error_count": error_count,
        "crawl_evidence_id": evidence.id,
        "homepage_evidence_id": homepage_evidence_id,
    }
