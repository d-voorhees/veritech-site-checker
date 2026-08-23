import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

# Scan lifecycle statuses.
SCAN_STATUS_QUEUED = "queued"
SCAN_STATUS_STARTING = "starting"
SCAN_STATUS_RUNNING = "running"
SCAN_STATUS_COMPLETED = "completed"
SCAN_STATUS_COMPLETED_WITH_WARNINGS = "completed_with_warnings"
SCAN_STATUS_FAILED = "failed"
SCAN_STATUS_CANCELLED = "cancelled"

SCAN_STATUSES = (
    SCAN_STATUS_QUEUED,
    SCAN_STATUS_STARTING,
    SCAN_STATUS_RUNNING,
    SCAN_STATUS_COMPLETED,
    SCAN_STATUS_COMPLETED_WITH_WARNINGS,
    SCAN_STATUS_FAILED,
    SCAN_STATUS_CANCELLED,
)

# Statuses a scan-runner is still allowed to claim (i.e. no runner has
# successfully started processing it yet).
CLAIMABLE_SCAN_STATUSES = (SCAN_STATUS_QUEUED, SCAN_STATUS_STARTING)

JOB_STATUS_PENDING = "pending"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_SUCCEEDED = "succeeded"
JOB_STATUS_FAILED = "failed"


class ScanRequest(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "scan_requests"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )

    normalized_domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    original_input: Mapped[str] = mapped_column(String(2048), nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    max_pages: Mapped[int] = mapped_column(Integer, nullable=False, default=10)

    authorization_confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default=SCAN_STATUS_QUEUED, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # On-demand Fly Machine tracking (see app/services/fly_machines.py and
    # app/runner/). runner_machine_id is the Fly Machine ID created to run
    # this one scan; heartbeat_at is updated by the runner between stages so
    # a crashed/killed runner is detectable without an explicit event;
    # retry_count counts how many times a runner Machine has been requested
    # for this scan.
    runner_machine_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    is_demo: Mapped[bool] = mapped_column(default=False, nullable=False)

    target: Mapped["ScanTarget"] = relationship(back_populates="scan_request", uselist=False, cascade="all, delete-orphan")
    jobs: Mapped[list["ScanJob"]] = relationship(back_populates="scan_request", cascade="all, delete-orphan")
    events: Mapped[list["ScanEvent"]] = relationship(
        back_populates="scan_request", cascade="all, delete-orphan", order_by="ScanEvent.created_at"
    )


class ScanTarget(Base, UUIDMixin, TimestampMixin):
    """The validated, SSRF-checked resolution of a scan request's target."""

    __tablename__ = "scan_targets"

    scan_request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scan_requests.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    hostname: Mapped[str] = mapped_column(String(255), nullable=False)
    canonical_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    resolved_ips: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    scan_request: Mapped["ScanRequest"] = relationship(back_populates="target")


class ScanJob(Base, UUIDMixin, TimestampMixin):
    """One retryable collection task within a scan (http, dns, crawl, browser, ...)."""

    __tablename__ = "scan_jobs"

    scan_request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scan_requests.id", ondelete="CASCADE"), nullable=False
    )
    task_name: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=JOB_STATUS_PENDING)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    scan_request: Mapped["ScanRequest"] = relationship(back_populates="jobs")


class ScanEvent(Base, UUIDMixin, TimestampMixin):
    """Append-only timeline used to render scan progress."""

    __tablename__ = "scan_events"

    scan_request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scan_requests.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    scan_request: Mapped["ScanRequest"] = relationship(back_populates="events")
