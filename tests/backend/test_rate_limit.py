from datetime import datetime, timedelta, timezone

from app.config import get_settings
from app.core.rate_limit import RateLimitExceeded, enforce_scan_creation_rate_limit
from app.models.scan import SCAN_STATUS_QUEUED, ScanRequest, ScanTarget


def _make_scan(db, user, created_at):
    scan = ScanRequest(
        user_id=user.id,
        organization_id=user.organization_id,
        normalized_domain="example.com",
        original_input="example.com",
        notes="",
        max_pages=10,
        authorization_confirmed_at=datetime.now(timezone.utc),
        status=SCAN_STATUS_QUEUED,
    )
    db.add(scan)
    db.flush()
    db.add(
        ScanTarget(
            scan_request_id=scan.id,
            hostname="example.com",
            canonical_url="https://example.com/",
            resolved_ips=["93.184.216.34"],
        )
    )
    db.commit()
    db.refresh(scan)
    # created_at has a server_default, so overwrite it directly for the test.
    db.query(ScanRequest).filter_by(id=scan.id).update({"created_at": created_at})
    db.commit()
    return scan


def test_allows_scans_under_both_limits(db, user):
    settings = get_settings()
    limit = min(settings.scan_create_rate_limit_per_hour, settings.scan_create_rate_limit_per_day)
    now = datetime.now(timezone.utc)
    for _ in range(limit - 1):
        _make_scan(db, user, now)

    enforce_scan_creation_rate_limit(db, user.id)  # should not raise


def test_blocks_scans_at_the_hourly_limit(db, user):
    limit = get_settings().scan_create_rate_limit_per_hour
    now = datetime.now(timezone.utc)
    for _ in range(limit):
        _make_scan(db, user, now)

    try:
        enforce_scan_creation_rate_limit(db, user.id)
        assert False, "expected RateLimitExceeded"
    except RateLimitExceeded as exc:
        assert "per hour" in str(exc)


def test_blocks_scans_at_the_daily_limit_even_outside_the_hourly_window(db, user):
    settings = get_settings()
    assert settings.scan_create_rate_limit_per_day < settings.scan_create_rate_limit_per_hour
    limit = settings.scan_create_rate_limit_per_day
    stale_hour_but_fresh_day = datetime.now(timezone.utc) - timedelta(hours=2)
    for _ in range(limit):
        _make_scan(db, user, stale_hour_but_fresh_day)

    try:
        enforce_scan_creation_rate_limit(db, user.id)
        assert False, "expected RateLimitExceeded"
    except RateLimitExceeded as exc:
        assert "scans a day" in str(exc)
        assert "danielle@veritechdiligence.com" in str(exc)


def test_scans_older_than_one_day_do_not_count(db, user):
    limit = get_settings().scan_create_rate_limit_per_day
    stale = datetime.now(timezone.utc) - timedelta(hours=25)
    for _ in range(limit + 5):
        _make_scan(db, user, stale)

    enforce_scan_creation_rate_limit(db, user.id)  # should not raise — all scans are stale


def test_rate_limit_is_per_user(db, user, admin_user):
    limit = get_settings().scan_create_rate_limit_per_day
    now = datetime.now(timezone.utc)
    for _ in range(limit):
        _make_scan(db, user, now)

    enforce_scan_creation_rate_limit(db, admin_user.id)  # a different user is unaffected
