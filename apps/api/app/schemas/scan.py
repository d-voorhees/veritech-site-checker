import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

REQUIRED_AUTHORIZATION_TEXT = (
    "I confirm that I own this domain or am authorized to analyze its "
    "publicly available content."
)

ALLOWED_MAX_PAGES = (10, 25, 50)


class ScanCreateRequest(BaseModel):
    target_input: str = Field(..., min_length=1, max_length=2048, description="Domain or URL")
    notes: str = Field(default="", max_length=4000)
    max_pages: Literal[10, 25, 50] = 10
    authorization_acknowledgment: bool = False

    @field_validator("authorization_acknowledgment")
    @classmethod
    def must_confirm_authorization(cls, value: bool) -> bool:
        if not value:
            raise ValueError(
                "You must confirm authorization to analyze this domain's public content."
            )
        return value


class ScanJobOut(BaseModel):
    id: uuid.UUID
    task_name: str
    status: str
    attempts: int
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None

    model_config = {"from_attributes": True}


class ScanEventOut(BaseModel):
    id: uuid.UUID
    event_type: str
    message: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ScanSummaryOut(BaseModel):
    id: uuid.UUID
    normalized_domain: str
    status: str
    max_pages: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    is_demo: bool

    model_config = {"from_attributes": True}


class ScanDetailOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    normalized_domain: str
    original_input: str
    notes: str
    max_pages: int
    authorization_confirmed_at: datetime
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    failure_summary: str | None
    created_at: datetime
    is_demo: bool
    jobs: list[ScanJobOut] = []

    model_config = {"from_attributes": True}
