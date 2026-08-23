import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.evidence import EvidenceItem

SEVERITIES = ("ok", "info", "low", "medium", "high")
CONFIDENCES = ("low", "medium", "high")

# "ok" is a positive/neutral observation (e.g. DKIM signing found) — it never
# appears in the risk register, only in the rules-coverage table. Every other
# severity is a register-eligible risk level, from "info" (worth knowing) up
# to "high". See docs/rules-engine.md.
REGISTER_SEVERITIES = ("info", "low", "medium", "high")

# Rough, rule-assigned bands — never exact dollars, and never set by whoever
# is reading the report. "n/a" is for "ok"-severity (no risk, nothing to
# price) and for findings where remediation isn't really a "fix" (e.g. a
# purely informational signal). See docs/rules-engine.md for how a rule
# picks its band.
DOLLAR_IMPACT_LEVELS = ("n/a", "$", "$$", "$$$")
REMEDIATION_TIMINGS = ("n/a", "30-day", "60-day", "90-day", "longer-term")

FINDING_STATUS_OPEN = "open"
FINDING_STATUS_ACKNOWLEDGED = "acknowledged"


class FindingRule(Base, UUIDMixin, TimestampMixin):
    """Catalog of deterministic rule definitions. See docs/rules-engine.md."""

    __tablename__ = "finding_rules"
    __table_args__ = (UniqueConstraint("rule_key", "version", name="uq_finding_rules_key_version"),)

    rule_key: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    default_severity: Mapped[str] = mapped_column(String(16), nullable=False)
    default_confidence: Mapped[str] = mapped_column(String(16), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")


class Finding(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "findings"

    scan_request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scan_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rule_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("finding_rules.id"), nullable=False)
    rule_version: Mapped[int] = mapped_column(Integer, nullable=False)

    category: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[str] = mapped_column(String(16), nullable=False)

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    impact: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_next_step: Mapped[str] = mapped_column(Text, nullable=False)
    dollar_impact: Mapped[str] = mapped_column(String(8), nullable=False)
    remediation_timing: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=FINDING_STATUS_OPEN)

    rule: Mapped["FindingRule"] = relationship()
    evidence_links: Mapped[list["FindingEvidence"]] = relationship(
        back_populates="finding", cascade="all, delete-orphan"
    )


class FindingEvidence(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "finding_evidence"
    __table_args__ = (UniqueConstraint("finding_id", "evidence_item_id", name="uq_finding_evidence"),)

    finding_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("findings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    evidence_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evidence_items.id", ondelete="CASCADE"), nullable=False, index=True
    )

    finding: Mapped["Finding"] = relationship(back_populates="evidence_links")
    evidence_item: Mapped["EvidenceItem"] = relationship(back_populates="finding_links")
