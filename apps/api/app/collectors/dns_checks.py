"""Collector 4: DNS and email posture (SPF / DMARC / DKIM).

DKIM has no fixed, well-known DNS location the way SPF (domain apex TXT) and
DMARC (_dmarc.<domain>) do — a DKIM public key lives at
`<selector>._domainkey.<domain>`, and the selector is chosen by whichever
sending service configured it. Without an authenticated mail sample there is
no way to learn the real selector, so this collector does a best-effort probe
of a curated list of selectors used by default by common email/marketing
providers (Google Workspace, Microsoft 365, Mailchimp, SendGrid, etc.). A hit
is strong positive evidence; a miss is not proof of absence — the domain may
sign with a selector outside this list.
"""

import uuid
from datetime import datetime, timezone

import dns.exception
import dns.resolver
import httpx

from app.models.evidence import EvidenceItem
from app.models.observation import DNSObservation

RECORD_TYPES = ("A", "AAAA", "CNAME", "MX", "NS", "TXT")
RDAP_TIMEOUT_SECONDS = 8

# Default selectors used out-of-the-box by common email/marketing providers.
# Not exhaustive — a domain using a custom selector won't be found here.
COMMON_DKIM_SELECTORS = (
    "google",       # Google Workspace
    "selector1",    # Microsoft 365
    "selector2",    # Microsoft 365
    "k1",           # Mailchimp / Mandrill
    "mandrill",     # Mandrill
    "s1",           # SendGrid (legacy)
    "s2",           # SendGrid (legacy)
    "smtpapi",      # SendGrid
    "mailgun",      # Mailgun
    "mailjet",      # Mailjet
    "pm",           # Postmark
    "zoho",         # Zoho Mail
    "amazonses",    # Amazon SES
    "dkim",         # generic
    "default",      # generic
    "mail",         # generic
)


def _resolve(resolver: dns.resolver.Resolver, name: str, record_type: str) -> tuple[list[str], bool, str | None]:
    try:
        answer = resolver.resolve(name, record_type)
        return [rdata.to_text() for rdata in answer], True, None
    except dns.resolver.NXDOMAIN:
        return [], True, "Domain does not exist."
    except dns.resolver.NoAnswer:
        return [], True, None
    except dns.exception.DNSException as exc:
        return [], False, str(exc)


def _parse_dmarc(record_text: str) -> dict:
    tags = {}
    for part in record_text.split(";"):
        part = part.strip()
        if "=" not in part:
            continue
        key, _, value = part.partition("=")
        tags[key.strip().lower()] = value.strip()
    return {
        "policy": tags.get("p"),
        "rua": tags.get("rua"),
        "pct": tags.get("pct"),
    }


def _discover_dkim(resolver: dns.resolver.Resolver, hostname: str) -> list[dict]:
    """Probes COMMON_DKIM_SELECTORS and returns one dict per selector that has
    a TXT record looking like a real DKIM public key (contains a `p=` tag)."""
    found = []
    for selector in COMMON_DKIM_SELECTORS:
        name = f"{selector}._domainkey.{hostname}"
        values, lookup_successful, error_message = _resolve(resolver, name, "TXT")
        record = next((v.strip('"') for v in values if "p=" in v.lower()), None)
        if lookup_successful and record:
            found.append({"selector": selector, "name": name, "record": record})
    return found


def _registrable_domain(hostname: str) -> str:
    """Best-effort strip of a leading 'www.' label — RDAP domain objects
    exist only for registered (not sub-) domains. Does not handle deeper
    subdomains or multi-part public suffixes; a mismatch just produces a
    lookup error below, not a wrong answer.
    """
    return hostname[4:] if hostname.lower().startswith("www.") else hostname


def _extract_registrar_name(entities: list | None) -> str | None:
    for entity in entities or []:
        if "registrar" not in (entity.get("roles") or []):
            continue
        vcard = entity.get("vcardArray")
        if not vcard or len(vcard) < 2:
            continue
        for field in vcard[1]:
            if field and field[0] == "fn" and len(field) >= 4:
                return field[3]
    return None


def fetch_domain_registration(hostname: str) -> dict:
    """RDAP lookup via rdap.org's registry-bounce service: a fixed, trusted
    third-party endpoint (same precedent as the Google PageSpeed call in
    collectors/performance.py) — not the user-controlled scan target, so
    this sits outside the per-target SSRF revalidation boundary by design.
    """
    domain = _registrable_domain(hostname)
    try:
        with httpx.Client(timeout=RDAP_TIMEOUT_SECONDS, follow_redirects=True) as client:
            resp = client.get(f"https://rdap.org/domain/{domain}")
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        return {"domain": domain, "error": str(exc)}

    events = {e.get("eventAction"): e.get("eventDate") for e in data.get("events", []) if e.get("eventAction")}
    expiration_date = events.get("expiration")
    days_until_expiration = None
    if expiration_date:
        try:
            exp = datetime.fromisoformat(expiration_date.replace("Z", "+00:00"))
            days_until_expiration = (exp - datetime.now(timezone.utc)).days
        except ValueError:
            pass

    return {
        "domain": domain,
        "registrar": _extract_registrar_name(data.get("entities")),
        "registration_date": events.get("registration"),
        "expiration_date": expiration_date,
        "days_until_expiration": days_until_expiration,
    }


def run_dns_and_email_checks(
    db,
    scan_request_id: uuid.UUID,
    hostname: str,
    resolver: dns.resolver.Resolver | None = None,
    rdap_lookup_fn=None,
) -> dict:
    if resolver is None:
        resolver = dns.resolver.Resolver()
        resolver.lifetime = 5
        resolver.timeout = 5

    summary: dict = {"records": {}, "spf_present": False, "dmarc_present": False}

    for record_type in RECORD_TYPES:
        values, lookup_successful, error_message = _resolve(resolver, hostname, record_type)
        db.add(
            DNSObservation(
                scan_request_id=scan_request_id,
                record_type=record_type,
                name=hostname,
                values=values,
                lookup_successful=lookup_successful,
                error_message=error_message,
            )
        )
        summary["records"][record_type] = values

    # --- SPF: derived from TXT records already fetched above. -----------------
    txt_values = summary["records"].get("TXT", [])
    spf_records = [v.strip('"') for v in txt_values if v.strip('"').lower().startswith("v=spf1")]
    spf_record = spf_records[0] if spf_records else None

    db.add(
        DNSObservation(
            scan_request_id=scan_request_id,
            record_type="SPF",
            name=hostname,
            values=spf_records,
            lookup_successful=True,
            spf_record=spf_record,
        )
    )
    summary["spf_present"] = spf_record is not None
    summary["spf_record"] = spf_record

    # --- DMARC: separate query against _dmarc.<domain> --------------------------
    dmarc_name = f"_dmarc.{hostname}"
    dmarc_values, dmarc_lookup_successful, dmarc_error = _resolve(resolver, dmarc_name, "TXT")
    dmarc_records = [v.strip('"') for v in dmarc_values if v.strip('"').lower().startswith("v=dmarc1")]
    dmarc_record = dmarc_records[0] if dmarc_records else None
    dmarc_tags = _parse_dmarc(dmarc_record) if dmarc_record else {}

    db.add(
        DNSObservation(
            scan_request_id=scan_request_id,
            record_type="DMARC",
            name=dmarc_name,
            values=dmarc_records,
            lookup_successful=dmarc_lookup_successful,
            error_message=dmarc_error,
            dmarc_record=dmarc_record,
            dmarc_policy=dmarc_tags.get("policy"),
            dmarc_pct=dmarc_tags.get("pct"),
            dmarc_rua=dmarc_tags.get("rua"),
        )
    )
    summary["dmarc_present"] = dmarc_record is not None
    summary["dmarc_lookup_successful"] = dmarc_lookup_successful
    summary["dmarc_record"] = dmarc_record
    summary["dmarc_policy"] = dmarc_tags.get("policy")

    # --- DKIM: best-effort probe of common ESP-default selectors. --------------
    dkim_hits = _discover_dkim(resolver, hostname)
    for hit in dkim_hits:
        db.add(
            DNSObservation(
                scan_request_id=scan_request_id,
                record_type="DKIM",
                name=hit["name"],
                values=[hit["record"]],
                lookup_successful=True,
                dkim_selector=hit["selector"],
            )
        )
    if not dkim_hits:
        db.add(
            DNSObservation(
                scan_request_id=scan_request_id,
                record_type="DKIM",
                name=hostname,
                values=[],
                lookup_successful=True,
                error_message=(
                    f"No DKIM record found under any of {len(COMMON_DKIM_SELECTORS)} common selectors "
                    "probed. Not proof of absence — a custom selector would not be found."
                ),
            )
        )
    summary["dkim_selectors_found"] = [hit["selector"] for hit in dkim_hits]

    db.flush()

    dns_evidence = EvidenceItem(
        scan_request_id=scan_request_id,
        category="dns",
        source_type="dns_lookup",
        source_url_or_identifier=hostname,
        captured_at=datetime.now(timezone.utc),
        confidence="high",
        normalized_payload_json={"records": summary["records"]},
        human_readable_summary=(
            f"Resolved DNS records for {hostname}: "
            + ", ".join(f"{k}={len(v)}" for k, v in summary["records"].items())
        ),
        raw_response_reference=None,
    )
    db.add(dns_evidence)

    email_evidence = EvidenceItem(
        scan_request_id=scan_request_id,
        category="email_posture",
        source_type="spf_dmarc_lookup",
        source_url_or_identifier=f"{hostname} / {dmarc_name}",
        captured_at=datetime.now(timezone.utc),
        confidence="high",
        normalized_payload_json={
            "spf_present": summary["spf_present"],
            "spf_record": spf_record,
            "dmarc_present": summary["dmarc_present"],
            "dmarc_lookup_successful": dmarc_lookup_successful,
            "dmarc_record": dmarc_record,
            "dmarc_policy": dmarc_tags.get("policy"),
            "dmarc_pct": dmarc_tags.get("pct"),
            "dmarc_rua": dmarc_tags.get("rua"),
            "dkim_selectors_found": summary["dkim_selectors_found"],
            "dkim_selectors_probed": list(COMMON_DKIM_SELECTORS),
        },
        human_readable_summary=(
            f"SPF record {'present' if summary['spf_present'] else 'not present'}. "
            f"DMARC record {'present' if summary['dmarc_present'] else 'not present'}"
            + (f" with policy p={dmarc_tags.get('policy')}." if dmarc_tags.get("policy") else ".")
            + (
                f" DKIM found under selector(s): {', '.join(summary['dkim_selectors_found'])}."
                if summary["dkim_selectors_found"]
                else f" No DKIM record found under {len(COMMON_DKIM_SELECTORS)} commonly probed selectors "
                "(not proof of absence)."
            )
        ),
        raw_response_reference=None,
    )
    db.add(email_evidence)
    db.flush()

    summary["evidence_id"] = email_evidence.id
    summary["dns_evidence_id"] = dns_evidence.id

    # --- Domain registration (RDAP): age and registrar expiration. -------------
    lookup_fn = rdap_lookup_fn or fetch_domain_registration
    try:
        registration = lookup_fn(hostname)
    except Exception as exc:  # noqa: BLE001 -- a third-party RDAP hiccup must not fail DNS collection
        registration = {"domain": _registrable_domain(hostname), "error": str(exc)}

    registration_evidence = EvidenceItem(
        scan_request_id=scan_request_id,
        category="domain_registration",
        source_type="rdap_lookup",
        source_url_or_identifier=registration.get("domain", hostname),
        captured_at=datetime.now(timezone.utc),
        confidence="high" if not registration.get("error") else "low",
        normalized_payload_json=registration,
        human_readable_summary=(
            f"Registrar: {registration.get('registrar') or 'unknown'}. "
            f"Registered {registration.get('registration_date') or 'unknown'}, "
            f"expires {registration.get('expiration_date') or 'unknown'}."
            if not registration.get("error")
            else f"RDAP domain registration lookup failed: {registration['error']}"
        ),
        raw_response_reference=None,
    )
    db.add(registration_evidence)
    db.flush()
    summary["domain_registration"] = registration
    summary["domain_registration_evidence_id"] = registration_evidence.id

    return summary
