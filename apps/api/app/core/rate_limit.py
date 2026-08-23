import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.magic_link_token import MagicLinkToken
from app.models.scan import ScanRequest


class RateLimitExceeded(Exception):
    pass


def get_daily_scan_usage(db: Session, user_id: uuid.UUID) -> tuple[int, int]:
    """(scans created in the last rolling 24h, daily limit) for this user —
    the same window enforce_scan_creation_rate_limit checks, so the frontend
    can display live usage against the limit that actually applies.
    """
    settings = get_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    count = (
        db.query(ScanRequest)
        .filter(ScanRequest.user_id == user_id, ScanRequest.created_at >= cutoff)
        .count()
    )
    return count, settings.scan_create_rate_limit_per_day


def enforce_scan_creation_rate_limit(db: Session, user_id: uuid.UUID) -> None:
    """Rolling-window counts of scans this user has created, backed by
    Postgres (no Redis in this architecture). The hourly limit is a burst
    guard; the daily limit is the real cost cap now that scans are free and
    self-serve — a rolling hour alone permits far more than a few scans a
    day if spread out.
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)

    hourly_limit = settings.scan_create_rate_limit_per_hour
    hourly_count = (
        db.query(ScanRequest)
        .filter(ScanRequest.user_id == user_id, ScanRequest.created_at >= now - timedelta(hours=1))
        .count()
    )
    if hourly_count >= hourly_limit:
        raise RateLimitExceeded(
            f"Scan creation limit reached ({hourly_limit} per hour). Please try again later."
        )

    daily_count, daily_limit = get_daily_scan_usage(db, user_id)
    if daily_count >= daily_limit:
        raise RateLimitExceeded(
            f"This tool is currently limited to {daily_limit} scans a day. "
            "Please try again tomorrow, or contact danielle@veritechdiligence.com "
            "to discuss more usage."
        )


def enforce_magic_link_request_rate_limit(db: Session, requested_ip: str | None) -> None:
    """Rolling-hour count of magic-link requests from one IP, so the
    request-link endpoint can't be used to spam arbitrary email addresses.
    An unknown IP (requested_ip is None) is never rate-limited here — that
    would rate-limit every unknown-IP caller as one shared bucket.
    """
    if not requested_ip:
        return

    settings = get_settings()
    limit = settings.magic_link_request_rate_limit_per_hour
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)

    count = (
        db.query(MagicLinkToken)
        .filter(MagicLinkToken.requested_ip == requested_ip, MagicLinkToken.created_at >= cutoff)
        .count()
    )

    if count >= limit:
        raise RateLimitExceeded(
            f"Too many sign-in link requests ({limit} per hour). Please try again later."
        )
