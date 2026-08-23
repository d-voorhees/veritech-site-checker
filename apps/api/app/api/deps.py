
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.user import User
from app.security.tokens import decode_access_token

SESSION_COOKIE_NAME = "veritech_session"


def _extract_token(request: Request) -> str | None:
    cookie_token = request.cookies.get(SESSION_COOKIE_NAME)
    if cookie_token:
        return cookie_token

    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:]

    return None


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    user_id = decode_access_token(token)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session")

    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session")

    return user


def get_current_user_optional(request: Request, db: Session = Depends(get_db)) -> User | None:
    """Like get_current_user, but returns None instead of raising 401.

    For endpoints a user's browser navigates to directly (e.g. the HTML
    export link), rather than ones only ever called via fetch() from the
    SPA — a raw 401 JSON body has nowhere good to render, so those routes
    check this themselves and redirect to /login instead.
    """
    token = _extract_token(request)
    if not token:
        return None

    user_id = decode_access_token(token)
    if not user_id:
        return None

    user = db.get(User, user_id)
    if not user or not user.is_active:
        return None

    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user
