import pytest

from app.core.crawl_policy import (
    has_excluded_extension,
    has_excluded_path,
    is_crawlable_url,
    is_same_origin_hostname,
)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/",
        "https://example.com/about",
        "https://example.com/blog/post-1",
    ],
)
def test_same_origin_html_pages_are_crawlable(url):
    assert is_crawlable_url(url, "example.com") is True


def test_external_origin_is_not_crawlable():
    assert is_crawlable_url("https://other-domain.example/", "example.com") is False


@pytest.mark.parametrize(
    "scheme_url",
    ["mailto:hello@example.com", "tel:+15555550100", "javascript:void(0)", "data:text/plain;base64,aGk="],
)
def test_excluded_schemes_are_not_crawlable(scheme_url):
    assert is_crawlable_url(scheme_url, "example.com") is False


@pytest.mark.parametrize(
    "path",
    ["/logo.png", "/styles.css", "/app.js", "/doc.pdf", "/archive.zip", "/data.json"],
)
def test_static_assets_are_excluded(path):
    assert has_excluded_extension(path) is True


@pytest.mark.parametrize(
    "path",
    ["/wp-admin/edit.php", "/login", "/account/settings", "/cart", "/checkout", "/api/v1/users", "/admin/"],
)
def test_sensitive_paths_are_excluded(path):
    assert has_excluded_path(path) is True


def test_normal_content_path_is_not_excluded():
    assert has_excluded_path("/blog/annual-report") is False


def test_crawlable_url_combines_all_checks():
    assert is_crawlable_url("https://example.com/wp-admin/", "example.com") is False
    assert is_crawlable_url("https://example.com/logo.png", "example.com") is False
    assert is_crawlable_url("https://example.com/pricing", "example.com") is True


@pytest.mark.parametrize(
    ("hostname", "allowed_hostname"),
    [
        ("www.example.com", "example.com"),
        ("example.com", "www.example.com"),
        ("www.example.com", "www.example.com"),
        ("EXAMPLE.com", "www.Example.com"),
    ],
)
def test_www_and_apex_are_same_origin(hostname, allowed_hostname):
    assert is_same_origin_hostname(hostname, allowed_hostname) is True


def test_different_domains_are_not_same_origin():
    assert is_same_origin_hostname("other-domain.example", "example.com") is False
    assert is_same_origin_hostname("evilexample.com", "example.com") is False


def test_crawlable_url_allows_www_apex_variants():
    assert is_crawlable_url("https://www.example.com/pricing", "example.com") is True
    assert is_crawlable_url("https://example.com/pricing", "www.example.com") is True
