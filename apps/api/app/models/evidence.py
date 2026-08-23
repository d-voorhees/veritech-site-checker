import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.finding import FindingEvidence

# Evidence categories map to collection areas.
EVIDENCE_CATEGORIES = (
    "http",
    "robots_sitemap",
    "crawl",
    "dns",
    "email_posture",
    "browser_render",
    "technology",
    "performance",
    "tls",
    "exposure",
    "domain_registration",
    "accessibility",
)


class EvidenceItem(Base, UUIDMixin, TimestampMixin):
    """The normalized evidence layer. This — not raw responses — is the
    product's core data model. Every finding cites one or more of these.
    """

    __tablename__ = "evidence_items"

    scan_request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scan_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)  # e.g. "http_response", "dns_txt", "playwright_render"
    source_url_or_identifier: Mapped[str] = mapped_column(String(2048), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confidence: Mapped[str] = mapped_column(String(16), nullable=False, default="high")  # low | medium | high

    normalized_payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    human_readable_summary: Mapped[str] = mapped_column(Text, nullable=False)
    raw_response_reference: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    finding_links: Mapped[list["FindingEvidence"]] = relationship(
        back_populates="evidence_item", cascade="all, delete-orphan"
    )
