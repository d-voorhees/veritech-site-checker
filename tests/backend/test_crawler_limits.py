"""Verifies the crawler respects the user-selected max-page budget even when
the site graph is much larger, and that it never leaves same-origin.
"""

import respx
from httpx import Response

import app.collectors.crawler as crawler_module
from app.collectors.crawler import run_crawl
from app.models.page import Page

PAGE_TEMPLATE = """
<html><head><title>Page {n}</title></head>
<body>
  <h1>Page {n}</h1>
  <a href="/page-{next_n}">Next</a>
  <a href="https://external.example/page-{n}">External</a>
</body></html>
"""


@respx.mock
def test_crawl_stops_at_max_pages(db, scan_request, monkeypatch):
    # A 20-page linear site; max_pages caps the crawl at 5.
    for n in range(20):
        respx.get(f"https://example.com/page-{n}").mock(
            return_value=Response(200, headers={"content-type": "text/html"}, html=PAGE_TEMPLATE.format(n=n, next_n=n + 1))
        )
    respx.get("https://example.com/").mock(
        return_value=Response(
            200, headers={"content-type": "text/html"}, html=PAGE_TEMPLATE.format(n=0, next_n=1)
        )
    )

    monkeypatch.setattr(crawler_module.time, "sleep", lambda seconds: None)

    result = run_crawl(db, scan_request.id, "https://example.com/", "example.com", max_pages=5)

    assert result["pages_fetched"] == 5
    pages = db.query(Page).filter_by(scan_request_id=scan_request.id).all()
    assert len(pages) == 5
    for page in pages:
        assert "example.com" in (page.final_url or page.url)


@respx.mock
def test_crawl_follows_apex_to_www_redirect(db, scan_request, monkeypatch):
    # The user entered the apex domain, but the site canonically redirects to
    # www. This must still be treated as same-origin and crawled normally,
    # not abandoned after the homepage.
    respx.get("https://example.com/").mock(
        return_value=Response(301, headers={"location": "https://www.example.com/"})
    )
    for n in range(5):
        respx.get(f"https://www.example.com/page-{n}").mock(
            return_value=Response(200, headers={"content-type": "text/html"}, html=PAGE_TEMPLATE.format(n=n, next_n=n + 1))
        )
    respx.get("https://www.example.com/").mock(
        return_value=Response(
            200, headers={"content-type": "text/html"}, html=PAGE_TEMPLATE.format(n=0, next_n=1)
        )
    )

    monkeypatch.setattr(crawler_module.time, "sleep", lambda seconds: None)

    result = run_crawl(db, scan_request.id, "https://example.com/", "example.com", max_pages=5)

    assert result["pages_fetched"] == 5
    pages = db.query(Page).filter_by(scan_request_id=scan_request.id).all()
    assert all(page.fetch_error is None for page in pages)
