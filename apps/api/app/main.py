import json
import time

from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.v1.auth import router as auth_router
from app.api.v1.scans import router as scans_router
from app.config import get_settings
from app.db import SessionLocal
from app.logging_config import configure_logging, get_logger

settings = get_settings()
configure_logging()
logger = get_logger(__name__)

app = FastAPI(
    title=f"{settings.product_name} API",
    description=(
        f"{settings.product_name} by {settings.parent_brand} — a bounded, rate-limited, "
        "evidence-first technical pre-screening API for public web properties."
    ),
    version="0.1.0",
)

if not settings.is_production:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(auth_router, prefix="/api/v1")
app.include_router(scans_router, prefix="/api/v1")



# The web/API Machine runs always-on (min_machines_running = 1 in fly.toml),
# so Fly polls /health continuously for the Machine's whole lifetime, not
# just after an autostart. Hitting Postgres on every poll kept Neon's
# compute endpoint perpetually active and never let it autosuspend, driving
# compute usage even with zero real traffic. Caching the actual DB check
# for a few minutes keeps /health meaningful without pinging Neon 24/7.
_HEALTH_CHECK_CACHE_SECONDS = 300
_last_postgres_check_at = 0.0
_last_postgres_ok = False


@app.get("/health")
def health() -> Response:
    """Readiness check: verifies Postgres connectivity (cached — see
    _HEALTH_CHECK_CACHE_SECONDS above). Used by Fly's http_service health
    check (proxied through Next.js — see next.config.mjs's rewrite for
    /health) to decide whether the web/API Machine is ready to receive
    traffic.
    """
    global _last_postgres_check_at, _last_postgres_ok

    now = time.monotonic()
    if now - _last_postgres_check_at >= _HEALTH_CHECK_CACHE_SECONDS:
        try:
            db = SessionLocal()
            try:
                db.execute(text("SELECT 1"))
                _last_postgres_ok = True
            finally:
                db.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("health_check_postgres_failed", error=str(exc))
            _last_postgres_ok = False
        _last_postgres_check_at = now

    checks = {"postgres": _last_postgres_ok}
    healthy = all(checks.values())
    payload = {"status": "ok" if healthy else "degraded", "checks": checks}
    return Response(
        content=json.dumps(payload),
        media_type="application/json",
        status_code=status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
    )
