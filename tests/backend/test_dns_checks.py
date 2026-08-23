import dns.exception
import dns.resolver

from app.collectors.dns_checks import (
    _extract_registrar_name,
    _parse_dmarc,
    _registrable_domain,
    run_dns_and_email_checks,
)
from app.models.evidence import EvidenceItem
from app.models.observation import DNSObservation

# Stubs out the RDAP domain-registration lookup so these tests never make a
# real network call to rdap.org — same offline-by-default intent as
# FakeResolver for DNS itself.
_no_op_rdap_lookup = lambda hostname: {"domain": hostname, "registrar": None, "expiration_date": None}  # noqa: E731


class FakeRData:
    def __init__(self, text):
        self._text = text

    def to_text(self):
        return self._text


class FakeResolver:
    """records: {(name, record_type): [raw_text, ...]}. Missing keys raise
    NoAnswer (a normal "record absent" outcome, not a lookup failure).
    """

    def __init__(self, records=None, nxdomain_for=None, servfail_for=None):
        self.records = records or {}
        self.nxdomain_for = nxdomain_for or set()
        self.servfail_for = servfail_for or set()
        self.lifetime = 5
        self.timeout = 5

    def resolve(self, name, record_type):
        if name in self.servfail_for:
            raise dns.exception.DNSException("SERVFAIL")
        if name in self.nxdomain_for:
            raise dns.resolver.NXDOMAIN()
        key = (name, record_type)
        if key not in self.records:
            raise dns.resolver.NoAnswer()
        return [FakeRData(v) for v in self.records[key]]


def test_parse_dmarc_extracts_policy_rua_pct():
    tags = _parse_dmarc("v=DMARC1; p=quarantine; rua=mailto:dmarc@example.com; pct=50")
    assert tags["policy"] == "quarantine"
    assert tags["rua"] == "mailto:dmarc@example.com"
    assert tags["pct"] == "50"


def test_parse_dmarc_handles_missing_optional_tags():
    tags = _parse_dmarc("v=DMARC1; p=none")
    assert tags["policy"] == "none"
    assert tags["rua"] is None
    assert tags["pct"] is None


def test_spf_and_dmarc_present(db, scan_request):
    resolver = FakeResolver(
        records={
            ("example.com", "TXT"): ['"v=spf1 include:_spf.google.com ~all"'],
            ("_dmarc.example.com", "TXT"): ['"v=DMARC1; p=quarantine; rua=mailto:dmarc@example.com"'],
        }
    )
    summary = run_dns_and_email_checks(
        db, scan_request.id, "example.com", resolver=resolver, rdap_lookup_fn=_no_op_rdap_lookup
    )

    assert summary["spf_present"] is True
    assert "v=spf1" in summary["spf_record"]
    assert summary["dmarc_present"] is True
    assert summary["dmarc_policy"] == "quarantine"


def test_missing_spf_and_dmarc_are_recorded_as_absent_not_failed(db, scan_request):
    resolver = FakeResolver(nxdomain_for={"_dmarc.example.com"})
    summary = run_dns_and_email_checks(
        db, scan_request.id, "example.com", resolver=resolver, rdap_lookup_fn=_no_op_rdap_lookup
    )

    assert summary["spf_present"] is False
    assert summary["dmarc_present"] is False
    # NXDOMAIN on the _dmarc subdomain is a normal "no record published"
    # outcome, not a DNS lookup failure.
    assert summary["dmarc_lookup_successful"] is True


def test_dns_servfail_is_recorded_as_lookup_failure(db, scan_request):
    resolver = FakeResolver(servfail_for={"example.com"})
    scan_id = scan_request.id
    run_dns_and_email_checks(db, scan_id, "example.com", resolver=resolver, rdap_lookup_fn=_no_op_rdap_lookup)

    a_obs = (
        db.query(DNSObservation)
        .filter(DNSObservation.scan_request_id == scan_id, DNSObservation.record_type == "A")
        .first()
    )
    assert a_obs.lookup_successful is False
    assert a_obs.error_message


def test_registrable_domain_strips_leading_www():
    assert _registrable_domain("www.example.com") == "example.com"
    assert _registrable_domain("example.com") == "example.com"


def test_extract_registrar_name_parses_vcard_array():
    entities = [
        {
            "roles": ["registrar"],
            "vcardArray": ["vcard", [["version", {}, "text", "4.0"], ["fn", {}, "text", "Example Registrar Inc."]]],
        }
    ]
    assert _extract_registrar_name(entities) == "Example Registrar Inc."


def test_extract_registrar_name_returns_none_without_registrar_role():
    assert _extract_registrar_name([{"roles": ["registrant"], "vcardArray": []}]) is None
    assert _extract_registrar_name(None) is None


def test_run_dns_and_email_checks_records_domain_registration_evidence(db, scan_request):
    resolver = FakeResolver()
    fake_registration = {
        "domain": "example.com", "registrar": "Example Registrar", "registration_date": "2010-01-01T00:00:00Z",
        "expiration_date": "2030-01-01T00:00:00Z", "days_until_expiration": 1000,
    }
    run_dns_and_email_checks(
        db, scan_request.id, "example.com", resolver=resolver, rdap_lookup_fn=lambda hostname: fake_registration
    )

    evidence = (
        db.query(EvidenceItem)
        .filter(EvidenceItem.scan_request_id == scan_request.id, EvidenceItem.category == "domain_registration")
        .first()
    )
    assert evidence is not None
    assert evidence.normalized_payload_json["registrar"] == "Example Registrar"
    assert evidence.confidence == "high"


def test_run_dns_and_email_checks_records_low_confidence_on_rdap_failure(db, scan_request):
    resolver = FakeResolver()

    def failing_lookup(hostname):
        raise RuntimeError("rdap.org unreachable")

    run_dns_and_email_checks(db, scan_request.id, "example.com", resolver=resolver, rdap_lookup_fn=failing_lookup)

    evidence = (
        db.query(EvidenceItem)
        .filter(EvidenceItem.scan_request_id == scan_request.id, EvidenceItem.category == "domain_registration")
        .first()
    )
    assert evidence is not None
    assert evidence.confidence == "low"
    assert evidence.normalized_payload_json["error"]
