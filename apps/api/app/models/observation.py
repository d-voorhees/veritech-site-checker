import uuid

from sqlalchemy import Boolean, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class HTTPObservation(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "http_observations"

    scan_request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scan_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    final_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    redirect_chain: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    headers: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cache_control: Mapped[str | None] = mapped_column(String(255), nullable=True)
    server_header: Mapped[str | None] = mapped_column(String(255), nullable=True)
    strict_transport_security: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_security_policy: Mapped[str | None] = mapped_column(Text, nullable=True)
    x_content_type_options: Mapped[str | None] = mapped_column(String(255), nullable=True)
    x_frame_options: Mapped[str | None] = mapped_column(String(255), nullable=True)
    referrer_policy: Mapped[str | None] = mapped_column(String(255), nullable=True)
    permissions_policy: Mapped[str | None] = mapped_column(Text, nullable=True)

    response_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_https: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class DNSObservation(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "dns_observations"

    scan_request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scan_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    record_type: Mapped[str] = mapped_column(String(16), nullable=False)  # A, AAAA, CNAME, MX, NS, TXT, SPF, DMARC
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    values: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    lookup_successful: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # SPF-specific
    spf_record: Mapped[str | None] = mapped_column(Text, nullable=True)

    # DMARC-specific
    dmarc_record: Mapped[str | None] = mapped_column(Text, nullable=True)
    dmarc_policy: Mapped[str | None] = mapped_column(String(32), nullable=True)
    dmarc_pct: Mapped[str | None] = mapped_column(String(16), nullable=True)
    dmarc_rua: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # DKIM-specific — the selector this record was found under (probed against
    # a curated list of common ESP selectors; see collectors/dns_checks.py)
    dkim_selector: Mapped[str | None] = mapped_column(String(64), nullable=True)


class TechnologyObservation(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "technology_observations"

    scan_request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scan_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    technology_name: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    detection_method: Mapped[str] = mapped_column(String(255), nullable=False)
    confidence: Mapped[str] = mapped_column(String(16), nullable=False)  # low | medium | high
    evidence_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("evidence_items.id", ondelete="SET NULL"), nullable=True
    )


class PerformanceObservation(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "performance_observations"

    scan_request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scan_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)  # local | google_pagespeed
    configured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    response_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    html_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    third_party_domain_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    js_resource_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    desktop_lcp_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    desktop_cls: Mapped[float | None] = mapped_column(Float, nullable=True)
    desktop_inp_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    desktop_fcp_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    desktop_ttfb_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    desktop_performance_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    desktop_accessibility_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    desktop_best_practices_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    desktop_seo_score: Mapped[int | None] = mapped_column(Integer, nullable=True)

    mobile_lcp_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    mobile_cls: Mapped[float | None] = mapped_column(Float, nullable=True)
    mobile_inp_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    mobile_fcp_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    mobile_ttfb_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    mobile_performance_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mobile_accessibility_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mobile_best_practices_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mobile_seo_score: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ThirdPartyDependency(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "third_party_dependencies"

    scan_request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scan_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    hostname: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="uncategorized")
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    classification_method: Mapped[str] = mapped_column(String(255), nullable=False, default="")
