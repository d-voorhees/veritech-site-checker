import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class Report(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "reports"

    scan_request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scan_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    format: Mapped[str] = mapped_column(String(16), nullable=False, default="html")
    storage_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Lean summary pushed to Brevo as contact attributes (see
    # app/services/report_summary.py) — persisted here so it never needs to
    # be recomputed from the full findings/evidence tables later.
    brevo_summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
