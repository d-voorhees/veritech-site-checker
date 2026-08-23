import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import SESSION_COOKIE_NAME, get_current_user
from app.config import get_settings
from app.core.rate_limit import RateLimitExceeded, enforce_magic_link_request_rate_limit, get_daily_scan_usage
from app.db import SessionLocal, get_db
from app.logging_config import get_logger
from app.models.magic_link_token import MagicLinkToken
from app.models.organization import Organization
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    MeResponse,
    RequestLinkRequest,
    RequestLinkResponse,
    SetPasswordRequest,
    VerifyTokenRequest,
    VerifyTokenResponse,
)
from app.security.magic_link import generate_magic_link_token, hash_magic_link_token
from app.security.passwords import hash_password, password_strength_error, verify_password
from app.security.tokens import create_access_token
from app.services.brevo_client import BrevoClient, BrevoError
from app.services.mailerlite_client import MailerLiteClient, MailerLiteError

router = APIRouter(prefix="/auth", tags=["auth"])
logger = get_logger(__name__)


def _set_session_cookie(response: Response, user_id: uuid.UUID) -> str:
    settings = get_settings()
    token = create_access_token(user_id)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        max_age=settings.jwt_expires_minutes * 60,
        path="/",
    )
    return token


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)) -> LoginResponse:
    user = db.query(User).filter(User.email == payload.email.lower()).first()

    if (
        not user
        or not user.is_active
        or not user.hashed_password
        or not verify_password(payload.password, user.hashed_password)
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    token = _set_session_cookie(response, user.id)
    return LoginResponse(access_token=token)


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me", response_model=MeResponse)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> MeResponse:
    scans_used_today, scan_daily_limit = get_daily_scan_usage(db, user.id)
    return MeResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        organization_id=user.organization_id,
        organization_name=user.organization.name,
        scans_used_today=scans_used_today,
        scan_daily_limit=scan_daily_limit,
        has_password=user.hashed_password is not None,
    )


@router.post("/set-password")
def set_password(
    payload: SetPasswordRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    if user.hashed_password is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password already set.")

    error = password_strength_error(payload.password)
    if error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error)

    user.hashed_password = hash_password(payload.password)
    db.commit()
    return {"ok": True}


@router.post("/request-link", response_model=RequestLinkResponse)
def request_link(payload: RequestLinkRequest, request: Request, db: Session = Depends(get_db)) -> RequestLinkResponse:
    settings = get_settings()
    generic_response = RequestLinkResponse()

    try:
        enforce_magic_link_request_rate_limit(db, request.client.host if request.client else None)
    except RateLimitExceeded as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc

    email = payload.email.lower()
    user = db.query(User).filter(User.email == email).first()
    if not user:
        org = Organization(name=email)
        db.add(org)
        db.flush()
        user = User(
            organization_id=org.id,
            email=email,
            hashed_password=None,
            full_name="",
            role="member",
            is_active=True,
        )
        db.add(user)
        db.flush()

    raw_token = generate_magic_link_token()
    db.add(
        MagicLinkToken(
            user_id=user.id,
            token_hash=hash_magic_link_token(raw_token),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=settings.magic_link_token_expires_minutes),
            requested_ip=request.client.host if request.client else None,
        )
    )
    db.commit()

    magic_link_url = f"{settings.app_url}/auth/verify?token={raw_token}"
    try:
        with BrevoClient(settings.brevo_api_key) as brevo:
            brevo.send_transactional_email(
                to_email=email,
                sender_email=settings.brevo_sender_email,
                sender_name=settings.brevo_sender_name,
                template_id=settings.brevo_magic_link_template_id,
                magic_link_url=magic_link_url,
            )
    except BrevoError as exc:
        # Never log magic_link_url or raw_token — logging the failure detail
        # only, deliberately excluding the link itself.
        logger.error("magic_link_email_send_failed", email=email, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Could not send the sign-in email. Please try again."
        ) from exc

    return generic_response


def _sync_mailerlite(user_id: uuid.UUID) -> None:
    """Runs after the verify response has already been sent (FastAPI
    BackgroundTasks) — needs its own DB session since the request-scoped one
    is already closed by the time this runs. A MailerLite failure here is
    logged and never surfaces to the user; it's retried out of band, not
    inline with auth.
    """
    settings = get_settings()
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if not user:
            return
        try:
            with MailerLiteClient(settings.mailerlite_api_key) as mailerlite:
                mailerlite.upsert_subscriber(email=user.email, group_id=settings.mailerlite_group_id)
            user.mailerlite_synced_at = datetime.now(timezone.utc)
            db.commit()
        except MailerLiteError as exc:
            logger.error("mailerlite_sync_failed", user_id=str(user_id), error=str(exc))
    finally:
        db.close()


@router.post("/verify", response_model=VerifyTokenResponse)
def verify(
    payload: VerifyTokenRequest,
    response: Response,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> VerifyTokenResponse:
    token_hash = hash_magic_link_token(payload.token)
    record = db.query(MagicLinkToken).filter(MagicLinkToken.token_hash == token_hash).first()

    if not record or record.used_at is not None or record.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This sign-in link is invalid or has expired.")

    record.used_at = datetime.now(timezone.utc)
    db.commit()

    user = db.get(User, record.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This sign-in link is invalid or has expired.")

    is_first_verification = user.email_verified_at is None
    if is_first_verification:
        user.email_verified_at = datetime.now(timezone.utc)
        db.commit()
        background_tasks.add_task(_sync_mailerlite, user.id)

    token = _set_session_cookie(response, user.id)
    return VerifyTokenResponse(access_token=token)
