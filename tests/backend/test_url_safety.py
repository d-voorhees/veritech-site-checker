import pytest

from app.core.url_safety import (
    UnsafeTargetError,
    is_ip_disallowed,
    normalize_input_to_url,
    revalidate_redirect_url,
    validate_target,
)


class FakeAnswer:
    def __init__(self, ips):
        self._ips = ips

    def __iter__(self):
        return iter(self._ips)


class FakeResolver:
    """Deterministic stand-in for dns.resolver.Resolver so tests never touch
    real DNS.
    """

    def __init__(self, a_records=None, aaaa_records=None, raise_nxdomain=False):
        self.a_records = a_records or []
        self.aaaa_records = aaaa_records or []
        self.raise_nxdomain = raise_nxdomain
        self.lifetime = 5
        self.timeout = 5

    def resolve(self, hostname, record_type):
        import dns.resolver

        if self.raise_nxdomain:
            raise dns.resolver.NXDOMAIN()
        if record_type == "A" and self.a_records:
            return FakeAnswer(self.a_records)
        if record_type == "AAAA" and self.aaaa_records:
            return FakeAnswer(self.aaaa_records)
        raise dns.resolver.NoAnswer()


# --- normalization -----------------------------------------------------------------


def test_normalize_bare_domain_defaults_to_https():
    assert normalize_input_to_url("example.com") == "https://example.com/"


def test_normalize_preserves_explicit_scheme():
    assert normalize_input_to_url("http://example.com/path") == "http://example.com/path"


def test_normalize_lowercases_hostname():
    assert normalize_input_to_url("HTTPS://Example.COM") == "https://example.com/"


def test_normalize_rejects_unsupported_scheme():
    with pytest.raises(UnsafeTargetError):
        normalize_input_to_url("ftp://example.com")


def test_normalize_rejects_empty_input():
    with pytest.raises(UnsafeTargetError):
        normalize_input_to_url("   ")


def test_normalize_rejects_invalid_hostname():
    with pytest.raises(UnsafeTargetError):
        normalize_input_to_url("not a domain")


# --- IP-level rejection -----------------------------------------------------------


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "127.0.0.53",
        "10.0.0.5",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",
        "224.0.0.1",
        "0.0.0.0",
        "100.100.100.200",
        "::1",
        "fe80::1",
        "fc00::1",
    ],
)
def test_disallowed_ips_are_rejected(ip):
    assert is_ip_disallowed(ip) is True


@pytest.mark.parametrize("ip", ["93.184.216.34", "1.1.1.1", "8.8.8.8"])
def test_public_ips_are_allowed(ip):
    assert is_ip_disallowed(ip) is False


def test_validate_target_rejects_localhost_hostname():
    with pytest.raises(UnsafeTargetError):
        validate_target("http://localhost/")


def test_validate_target_rejects_direct_private_ip_literal():
    with pytest.raises(UnsafeTargetError):
        validate_target("http://192.168.1.1/")


def test_validate_target_rejects_metadata_ip_literal():
    with pytest.raises(UnsafeTargetError):
        validate_target("http://169.254.169.254/")


def test_validate_target_rejects_domain_resolving_to_private_ip():
    resolver = FakeResolver(a_records=["10.0.0.5"])
    with pytest.raises(UnsafeTargetError):
        validate_target("internal.example.com", resolver=resolver)


def test_validate_target_accepts_domain_resolving_to_public_ip():
    resolver = FakeResolver(a_records=["93.184.216.34"])
    result = validate_target("example.com", resolver=resolver)
    assert result.hostname == "example.com"
    assert result.resolved_ips == ["93.184.216.34"]
    assert result.canonical_url == "https://example.com/"


def test_validate_target_rejects_nxdomain():
    resolver = FakeResolver(raise_nxdomain=True)
    with pytest.raises(UnsafeTargetError):
        validate_target("this-domain-does-not-exist-xyz.example", resolver=resolver)


# --- redirect revalidation ---------------------------------------------------------


def test_revalidate_redirect_allows_public_target():
    resolver = FakeResolver(a_records=["93.184.216.34"])
    result = revalidate_redirect_url("https://example.com/next", resolver=resolver)
    assert result.hostname == "example.com"


def test_revalidate_redirect_blocks_redirect_to_private_ip():
    resolver = FakeResolver(a_records=["127.0.0.1"])
    with pytest.raises(UnsafeTargetError):
        revalidate_redirect_url("https://attacker-controlled.example/", resolver=resolver)


def test_revalidate_redirect_blocks_direct_loopback_literal():
    with pytest.raises(UnsafeTargetError):
        revalidate_redirect_url("http://127.0.0.1:8080/admin")
