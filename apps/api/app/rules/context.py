import uuid

from sqlalchemy.orm import Session
from veritech_scan_rules import RuleContext

from app.models.evidence import EvidenceItem
from app.models.observation import DNSObservation, HTTPObservation, PerformanceObservation, ThirdPartyDependency
from app.models.page import Page
from app.models.scan import JOB_STATUS_FAILED, ScanJob, ScanRequest
from app.models.observation import TechnologyObservation

__all__ = ["RuleContext", "build_rule_context"]


def build_rule_context(db: Session, scan: ScanRequest) -> RuleContext:
    dns_observations = (
        db.query(DNSObservation).filter(DNSObservation.scan_request_id == scan.id).all()
    )
    http_observation = (
        db.query(HTTPObservation)
        .filter(HTTPObservation.scan_request_id == scan.id)
        .order_by(HTTPObservation.created_at)
        .first()
    )
    pages = db.query(Page).filter(Page.scan_request_id == scan.id).order_by(Page.created_at).all()
    homepage = pages[0] if pages else None
    third_party_deps = (
        db.query(ThirdPartyDependency).filter(ThirdPartyDependency.scan_request_id == scan.id).all()
    )
    performance = (
        db.query(PerformanceObservation)
        .filter(PerformanceObservation.scan_request_id == scan.id)
        .order_by(PerformanceObservation.created_at)
        .first()
    )

    def first_evidence_item(category: str, source_type: str | None = None) -> EvidenceItem | None:
        q = db.query(EvidenceItem).filter(
            EvidenceItem.scan_request_id == scan.id, EvidenceItem.category == category
        )
        if source_type:
            q = q.filter(EvidenceItem.source_type == source_type)
        return q.order_by(EvidenceItem.captured_at).first()

    def item_id(item: EvidenceItem | None) -> uuid.UUID | None:
        return item.id if item else None

    http_evidence_item = first_evidence_item("http", "http_response")
    sitemap_evidence = first_evidence_item("robots_sitemap", "sitemap_xml")

    evidence_ids = {
        "email_posture": item_id(first_evidence_item("email_posture", "spf_dmarc_lookup")),
        "http": item_id(http_evidence_item),
        "sitemap": item_id(sitemap_evidence),
        "crawl": item_id(first_evidence_item("crawl", "bounded_crawl")),
        "homepage_snapshot": item_id(first_evidence_item("crawl", "page_snapshot")),
        "performance": item_id(first_evidence_item("performance", "performance_measurement")),
    }

    technology_observations = (
        db.query(TechnologyObservation).filter(TechnologyObservation.scan_request_id == scan.id).all()
    )
    failed_scan_jobs = (
        db.query(ScanJob)
        .filter(ScanJob.scan_request_id == scan.id, ScanJob.status == JOB_STATUS_FAILED)
        .all()
    )

    return RuleContext(
        scan=scan,
        dns_observations=dns_observations,
        http_observation=http_observation,
        pages=pages,
        homepage=homepage,
        third_party_deps=third_party_deps,
        performance=performance,
        technology_observations=technology_observations,
        failed_scan_jobs=failed_scan_jobs,
        http_evidence_item=http_evidence_item,
        sitemap_evidence=sitemap_evidence,
        first_browser_render_evidence=first_evidence_item("browser_render"),
        playwright_render_evidence=first_evidence_item("browser_render", "playwright_render"),
        exposure_evidence=first_evidence_item("exposure", "endpoint_probe"),
        tls_evidence=first_evidence_item("tls", "tls_certificate"),
        domain_registration_evidence=first_evidence_item("domain_registration", "rdap_lookup"),
        accessibility_evidence=first_evidence_item("accessibility", "static_accessibility_scan"),
        evidence_ids=evidence_ids,
    )
