import uuid

from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class RequestLinkRequest(BaseModel):
    email: EmailStr


class RequestLinkResponse(BaseModel):
    message: str = "If that email is valid, a sign-in link is on its way."


class VerifyTokenRequest(BaseModel):
    token: str


class VerifyTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class SetPasswordRequest(BaseModel):
    password: str


class MeResponse(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: str
    organization_id: uuid.UUID
    organization_name: str
    scans_used_today: int
    scan_daily_limit: int
    has_password: bool

    model_config = {"from_attributes": True}
