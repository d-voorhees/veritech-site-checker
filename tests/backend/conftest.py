import os
import sys
import uuid
from pathlib import Path

import pytest

# When run with cwd=apps/api (e.g. `python -m pytest` from that directory),
# `app` is already on sys.path via cwd auto-prepending. When run from the
# repo root (e.g. `make test` /
# `pytest` at the top level), `app` isn't importable yet, so fall back to
# locating apps/api relative to this file.
try:
    import app  # noqa: F401
except ImportError:
    API_ROOT = Path(__file__).resolve().parents[2] / "apps" / "api"
    if str(API_ROOT) not in sys.path:
        sys.path.insert(0, str(API_ROOT))

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault(
    "DATABASE_URL", f"postgresql+psycopg://{os.environ.get('USER', 'postgres')}@localhost:5432/veritech_scan_test"
)
os.environ.setdefault("JWT_SECRET", "test-secret-do-not-use-in-production")
os.environ.setdefault("INITIAL_ADMIN_EMAIL", "admin@example.com")
os.environ.setdefault("INITIAL_ADMIN_PASSWORD", "test-password-123")
os.environ.setdefault("ARTIFACT_STORAGE_LOCAL_PATH", "/tmp/veritech-scan-test-artifacts")

from datetime import datetime, timezone  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models.organization import Organization  # noqa: E402
from app.models.scan import SCAN_STATUS_RUNNING, ScanRequest, ScanTarget  # noqa: E402
from app.models.user import User  # noqa: E402
from app.security.passwords import hash_password  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        for table in reversed(Base.metadata.sorted_tables):
            session.execute(table.delete())
        session.commit()
        session.close()


@pytest.fixture()
def organization(db):
    org = Organization(name="Test Buyer Co.")
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


@pytest.fixture()
def user(db, organization):
    u = User(
        organization_id=organization.id,
        email=f"tester-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("correct-horse-battery-staple"),
        full_name="Test User",
        role="member",
        is_active=True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture()
def scan_request(db, user):
    scan = ScanRequest(
        user_id=user.id,
        organization_id=user.organization_id,
        normalized_domain="example.com",
        original_input="example.com",
        notes="",
        max_pages=10,
        authorization_confirmed_at=datetime.now(timezone.utc),
        status=SCAN_STATUS_RUNNING,
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
    return scan


@pytest.fixture()
def admin_user(db, organization):
    u = User(
        organization_id=organization.id,
        email=f"admin-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("correct-horse-battery-staple"),
        full_name="Test Admin",
        role="admin",
        is_active=True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u
