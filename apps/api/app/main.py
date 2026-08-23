import json

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


@app.get("/health")
def health() -> Response:
    """Readiness check: verifies Postgres connectivity. Used by Fly's
    http_service health check (proxied through Next.js — see
    next.config.mjs's rewrite for /health) to decide whether the web/API
    Machine is ready to receive traffic after an autostart.
    """
    checks = {"postgres": False}

    try:
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            checks["postgres"] = True
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("health_check_postgres_failed", error=str(exc))

    healthy = all(checks.values())
    payload = {"status": "ok" if healthy else "degraded", "checks": checks}
    return Response(
        content=json.dumps(payload),
        media_type="application/json",
        status_code=status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
    )
