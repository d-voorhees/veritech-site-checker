import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class Page(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "pages"

    scan_request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scan_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )

    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    final_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)

    canonical_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    title: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    meta_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    robots_directives: Mapped[str | None] = mapped_column(String(255), nullable=True)

    h1_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_h1: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    html_lang: Mapped[str | None] = mapped_column(String(32), nullable=True)
    meta_viewport_present: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    structured_data_types: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    internal_link_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    external_link_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    response_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fetch_error: Mapped[str | None] = mapped_column(Text, nullable=True)
