"""SSRF and authorization-boundary protections.

Every target — the original scan submission and every redirect the crawler or
HTTP checker follows — passes through `validate_target` / `revalidate_redirect_url`
before a single byte is fetched. See docs/threat-model.md for the full
rationale.
"""

import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

import dns.exception
import dns.resolver


class UnsafeTargetError(ValueError):
    """Raised when a target fails SSRF / authorization-boundary validation."""


BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "ip6-localhost",
    "metadata.google.internal",
}

# Defense in depth: explicit cloud metadata literals. 169.254.169.254 is also
# link-local and would be rejected regardless, but we check it by name too so
# the intent is legible in code and tests.
BLOCKED_IP_LITERALS = {
    "169.254.169.254",  # AWS / GCP / Azure / Oracle Cloud metadata
    "100.100.100.200",  # Alibaba Cloud metadata
}

_HOSTNAME_RE = re.compile(
    r"^[a-z0-9]([a-z0-9\-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9\-]{0,61}[a-z0-9])?)+$"
)


@dataclass(frozen=True)
class ValidatedTarget:
    canonical_url: str
    hostname: str
    resolved_ips: list[str]


def _is_ip_literal(hostname: str) -> bool:
    try:
        ipaddress.ip_address(hostname)
        return True
    except ValueError:
        return False


def normalize_input_to_url(raw_input: str) -> str:
    """Normalize "example.com", "example.com/path", or a full URL into a
    canonical http(s) URL. Defaults to https when no scheme is given.
    """
    raw_input = (raw_input or "").strip()
    if not raw_input:
        raise UnsafeTargetError("A domain or URL is required.")

    if "://" not in raw_input:
        raw_input = f"https://{raw_input}"

    parts = urlsplit(raw_input)

    if parts.scheme not in ("http", "https"):
        raise UnsafeTargetError(
            f"Unsupported URL scheme: {parts.scheme!r}. Only http and https are allowed."
        )

    hostname = (parts.hostname or "").lower().rstrip(".")
    if not hostname:
        raise UnsafeTargetError("Could not determine a hostname from the input.")

    if not _is_ip_literal(hostname) and not _HOSTNAME_RE.match(hostname):
        raise UnsafeTargetError(f"{hostname!r} is not a valid public domain name.")

    netloc = hostname
    if parts.port:
        netloc = f"{hostname}:{parts.port}"

    path = parts.path or "/"
    return urlunsplit((parts.scheme, netloc, path, parts.query, ""))


def is_ip_disallowed(ip_str: str) -> bool:
    """True if the IP must not be contacted: loopback, RFC1918 private,
    link-local, multicast, reserved, unspecified, or a known cloud metadata
    address.
    """
    if ip_str in BLOCKED_IP_LITERALS:
        return True
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True

    return (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or getattr(ip, "is_site_local", False)
    )


def resolve_hostname(hostname: str, resolver: dns.resolver.Resolver | None = None) -> list[str]:
    """Resolve A and AAAA records. Raises UnsafeTargetError on total failure
    or zero usable addresses.
    """
    resolver = resolver or dns.resolver.Resolver()
    resolver.lifetime = 5
    resolver.timeout = 5

    ips: list[str] = []
    errors: list[str] = []
    for record_type in ("A", "AAAA"):
        try:
            answer = resolver.resolve(hostname, record_type)
            ips.extend(str(rdata) for rdata in answer)
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN) as exc:
            errors.append(str(exc))
            continue
        except dns.exception.DNSException as exc:
            errors.append(str(exc))
            continue

    if not ips:
        raise UnsafeTargetError(f"{hostname!r} did not resolve to any IP address.")

    return ips


def validate_target(raw_input: str, resolver: dns.resolver.Resolver | None = None) -> ValidatedTarget:
    """Full validation pipeline: normalize, reject disallowed hostnames,
    resolve DNS, and reject if any resolved IP is private/reserved.
    """
    canonical_url = normalize_input_to_url(raw_input)
    hostname = urlsplit(canonical_url).hostname or ""

    if hostname in BLOCKED_HOSTNAMES:
        raise UnsafeTargetError(f"{hostname!r} is not an authorized public target.")

    if _is_ip_literal(hostname):
        if is_ip_disallowed(hostname):
            raise UnsafeTargetError(f"{hostname!r} is a private or reserved IP address.")
        resolved_ips = [hostname]
    else:
        resolved_ips = resolve_hostname(hostname, resolver=resolver)
        for ip in resolved_ips:
            if is_ip_disallowed(ip):
                raise UnsafeTargetError(
                    f"{hostname!r} resolves to a private or reserved IP address ({ip}) "
                    "and cannot be scanned."
                )

    return ValidatedTarget(canonical_url=canonical_url, hostname=hostname, resolved_ips=resolved_ips)


def revalidate_redirect_url(
    url: str, resolver: dns.resolver.Resolver | None = None
) -> ValidatedTarget:
    """Re-run full validation on a redirect Location before following it, so a
    redirect cannot smuggle collection into a private network.
    """
    return validate_target(url, resolver=resolver)
