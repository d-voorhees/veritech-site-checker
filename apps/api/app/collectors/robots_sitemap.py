"""Collector 2: robots.txt and sitemap discovery.

Purely observational — this collector never crawls more than the user's
selected max page count, and it does not implement (or claim to implement)
full robots.txt enforcement. See docs/threat-model.md.
"""

import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit

import httpx

from app.collectors.user_agent import USER_AGENT
from app.config import get_settings
from app.core.url_safety import UnsafeTargetError, revalidate_redirect_url
from app.models.evidence import EvidenceItem

SAMPLE_URL_LIMIT = 10

# Known-path exposure probes. Each is a single GET, revalidated against the
# SSRF boundary immediately before it is requested (same pattern the crawler
# uses per-request) — not a vulnerability confirmation, just a presence
# observation the rules engine interprets.
EXPOSURE_PROBE_PATHS = {
    "xmlrpc": "xmlrpc.php",
    "wp_json": "wp-json/",
}


def _strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _fetch(client: httpx.Client, url: str) -> tuple[int | None, str | None, str | None]:
    """Returns (status_code, text, error_message)."""
    try:
        resp = client.get(url)
        return resp.status_code, resp.text, None
    except httpx.HTTPError as exc:
        return None, None, str(exc)


def _parse_robots_disallow(robots_text: str) -> list[str]:
    """Returns Disallow path prefixes that apply to `User-agent: *` groups.

    Consecutive `User-agent:` lines are grouped per the robots.txt spec (a
    block of directives applies to every agent named immediately above it);
    a group is considered closed once a non-user-agent directive is seen.
    Wildcard (`*`) and end-anchor (`$`) extensions used by some robots.txt
    files are not evaluated — only plain prefix matching.
    """
    disallow: list[str] = []
    current_agents: set[str] = set()
    group_open = False
    for raw_line in robots_text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if key == "user-agent":
            if group_open:
                current_agents = set()
                group_open = False
            current_agents.add(value.lower())
        elif key in ("disallow", "allow", "crawl-delay", "sitemap"):
            group_open = True
            if key == "disallow" and value and "*" in current_agents:
                disallow.append(value)
    return disallow


def _parse_sitemap_xml(xml_text: str) -> tuple[str, list[str], list[str], list[str]]:
    """Returns (kind, urls, lastmods, parse_errors) where kind is 'urlset',
    'sitemapindex', or 'unknown'. `lastmods` is a parallel list of raw
    <lastmod> text values (only for entries that had one — sitemap freshness
    is a coarse aggregate over whatever subset of entries declare it, not
    every URL)."""
    urls: list[str] = []
    lastmods: list[str] = []
    errors: list[str] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        return "unknown", [], [], [f"XML parse error: {exc}"]

    kind = _strip_ns(root.tag)
    for child in root:
        if _strip_ns(child.tag) not in ("url", "sitemap"):
            continue
        loc_el = next((c for c in child if _strip_ns(c.tag) == "loc"), None)
        if loc_el is not None and loc_el.text:
            urls.append(loc_el.text.strip())
        else:
            errors.append(f"Entry missing <loc> under <{_strip_ns(child.tag)}>")
            continue
        lastmod_el = next((c for c in child if _strip_ns(c.tag) == "lastmod"), None)
        if lastmod_el is not None and lastmod_el.text:
            lastmods.append(lastmod_el.text.strip())

    return kind, urls, lastmods, errors


def _parse_lastmod_date(value: str):
    """Sitemap <lastmod> is W3C datetime (ISO 8601), but real-world sitemaps
    vary in precision (date-only vs. full datetime, with/without offset).
    Best-effort parse; unparseable values are dropped rather than raising."""
    from datetime import date, datetime

    text = value.strip()
    try:
        if len(text) == 10:  # YYYY-MM-DD
            return date.fromisoformat(text)
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _summarize_lastmods(lastmods: list[str]) -> dict:
    from datetime import date, datetime

    parsed = [(raw, _parse_lastmod_date(raw)) for raw in lastmods]
    parsed = [(raw, d) for raw, d in parsed if d is not None]
    if not parsed:
        return {"lastmod_count": 0, "newest_lastmod": None, "oldest_lastmod": None}

    def _sort_key(item):
        raw, d = item
        # Normalize date-only values to a datetime for comparison against
        # full datetimes (midnight, naive vs. aware compared as strings
        # would sort incorrectly across formats).
        if isinstance(d, datetime):
            return d.replace(tzinfo=None)
        if isinstance(d, date):
            return datetime(d.year, d.month, d.day)
        return d

    newest = max(parsed, key=_sort_key)
    oldest = min(parsed, key=_sort_key)
    return {
        "lastmod_count": len(parsed),
        "newest_lastmod": newest[0],
        "oldest_lastmod": oldest[0],
    }


def run_robots_and_sitemap_checks(db, scan_request_id: uuid.UUID, canonical_url: str, max_pages: int) -> dict:
    settings = get_settings()
    parts = urlsplit(canonical_url)
    origin = f"{parts.scheme}://{parts.netloc}"
    robots_url = urljoin(origin + "/", "robots.txt")

    summary: dict = {
        "robots_status_code": None,
        "robots_retrieval_error": None,
        "sitemap_urls_declared": [],
        "sitemap_count": 0,
        "discovered_url_count": 0,
        "sample_urls": [],
        "parsing_errors": [],
        "retrieval_errors": [],
    }

    with httpx.Client(
        timeout=settings.scan_page_timeout_seconds,
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
    ) as client:
        status_code, robots_text, error = _fetch(client, robots_url)
        summary["robots_status_code"] = status_code
        summary["robots_retrieval_error"] = error
        # Same bounded excerpt stored on the evidence item below, surfaced
        # here too so technology_detection can pattern-match paths robots.txt
        # reveals (e.g. "Disallow: /wp-admin/") without a second fetch.
        summary["robots_body_excerpt"] = (robots_text or "")[:4000]

        declared_sitemaps: list[str] = []
        if robots_text:
            for line in robots_text.splitlines():
                line = line.strip()
                if line.lower().startswith("sitemap:"):
                    declared_sitemaps.append(line.split(":", 1)[1].strip())
        summary["sitemap_urls_declared"] = declared_sitemaps

        disallow_rules = _parse_robots_disallow(robots_text) if robots_text else []
        summary["disallow_rules"] = disallow_rules

        robots_evidence = EvidenceItem(
            scan_request_id=scan_request_id,
            category="robots_sitemap",
            source_type="robots_txt",
            source_url_or_identifier=robots_url,
            captured_at=datetime.now(timezone.utc),
            confidence="high",
            normalized_payload_json={
                "status_code": status_code,
                "declared_sitemaps": declared_sitemaps,
                "disallow_rules": disallow_rules,
                "retrieval_error": error,
                "body_excerpt": (robots_text or "")[:4000],
            },
            human_readable_summary=(
                f"robots.txt retrieval returned {status_code}."
                if status_code
                else f"robots.txt retrieval failed: {error}"
            )
            + f" Declared {len(declared_sitemaps)} sitemap URL(s) and {len(disallow_rules)} "
            "Disallow rule(s) for User-agent: *. "
            "Recorded as evidence only — this scan does not implement full robots.txt enforcement.",
            raw_response_reference=None,
        )
        db.add(robots_evidence)

        sitemap_candidates = list(declared_sitemaps)
        if not sitemap_candidates:
            sitemap_candidates.append(urljoin(origin + "/", "sitemap.xml"))

        discovered_urls: list[str] = []
        all_lastmods: list[str] = []
        parsing_errors: list[str] = []
        retrieval_errors: list[str] = []
        sitemap_count = 0

        for sitemap_url in sitemap_candidates[:5]:
            status_code, xml_text, error = _fetch(client, sitemap_url)
            if error or not xml_text or (status_code and status_code >= 400):
                retrieval_errors.append(f"{sitemap_url}: {error or f'HTTP {status_code}'}")
                continue

            sitemap_count += 1
            kind, urls, lastmods, errors = _parse_sitemap_xml(xml_text)
            parsing_errors.extend(f"{sitemap_url}: {e}" for e in errors)
            all_lastmods.extend(lastmods)

            if kind == "sitemapindex":
                # Follow up to 3 child sitemaps to keep this bounded.
                for child_sitemap_url in urls[:3]:
                    c_status, c_xml, c_error = _fetch(client, child_sitemap_url)
                    if c_error or not c_xml:
                        retrieval_errors.append(f"{child_sitemap_url}: {c_error or f'HTTP {c_status}'}")
                        continue
                    sitemap_count += 1
                    _, child_urls, child_lastmods, child_errors = _parse_sitemap_xml(c_xml)
                    parsing_errors.extend(f"{child_sitemap_url}: {e}" for e in child_errors)
                    discovered_urls.extend(child_urls)
                    all_lastmods.extend(child_lastmods)
            else:
                discovered_urls.extend(urls)

            if len(discovered_urls) >= max_pages * 5:
                break

        lastmod_summary = _summarize_lastmods(all_lastmods)

        summary["sitemap_count"] = sitemap_count
        summary["discovered_url_count"] = len(discovered_urls)
        summary["sample_urls"] = discovered_urls[:SAMPLE_URL_LIMIT]
        # Full (already-bounded) list, consumed by the crawler to seed its
        # queue with sitemap URLs ahead of organically-discovered links.
        summary["discovered_urls"] = discovered_urls
        summary["parsing_errors"] = parsing_errors
        summary["retrieval_errors"] = retrieval_errors
        summary.update(lastmod_summary)

        sitemap_evidence = EvidenceItem(
            scan_request_id=scan_request_id,
            category="robots_sitemap",
            source_type="sitemap_xml",
            source_url_or_identifier=", ".join(sitemap_candidates[:5]) or "none",
            captured_at=datetime.now(timezone.utc),
            confidence="high" if sitemap_count else "medium",
            normalized_payload_json={
                "sitemap_count": sitemap_count,
                "discovered_url_count": len(discovered_urls),
                "sample_urls": discovered_urls[:SAMPLE_URL_LIMIT],
                # Full list (already bounded to max_pages * 5 above), kept so the
                # report can cross-reference it against the actual crawled page set.
                "discovered_urls": discovered_urls,
                "parsing_errors": parsing_errors,
                "retrieval_errors": retrieval_errors,
                # Freshness signal: newest/oldest <lastmod> across every
                # sitemap entry that declared one (not every URL does).
                **lastmod_summary,
            },
            human_readable_summary=(
                f"Found {sitemap_count} sitemap file(s) declaring {len(discovered_urls)} URL(s)."
                if sitemap_count
                else "No sitemap could be retrieved from robots.txt or the /sitemap.xml fallback."
            ),
            raw_response_reference=None,
        )
        db.add(sitemap_evidence)
        db.flush()

        exposure_results: dict = {}
        for key, path in EXPOSURE_PROBE_PATHS.items():
            probe_url = urljoin(origin + "/", path)
            try:
                revalidate_redirect_url(probe_url)
                resp = client.get(probe_url)
                exposure_results[key] = {
                    "url": probe_url,
                    "status_code": resp.status_code,
                    "body_excerpt": resp.text[:500] if resp.text else "",
                }
            except (UnsafeTargetError, httpx.HTTPError) as exc:
                exposure_results[key] = {"url": probe_url, "status_code": None, "error": str(exc)}
        summary["exposure_checks"] = exposure_results

        exposure_evidence = EvidenceItem(
            scan_request_id=scan_request_id,
            category="exposure",
            source_type="endpoint_probe",
            source_url_or_identifier=", ".join(r["url"] for r in exposure_results.values()),
            captured_at=datetime.now(timezone.utc),
            confidence="high",
            normalized_payload_json=exposure_results,
            human_readable_summary=(
                "Probed known platform-specific endpoints: "
                + "; ".join(
                    f"{key} -> {r.get('status_code', 'error')}" for key, r in exposure_results.items()
                )
                + ". Presence/absence only — not a vulnerability confirmation."
            ),
            raw_response_reference=None,
        )
        db.add(exposure_evidence)
        db.flush()
        summary["exposure_evidence_id"] = exposure_evidence.id

    return summary
