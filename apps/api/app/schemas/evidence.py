import uuid
from datetime import datetime

from pydantic import BaseModel


class EvidenceItemOut(BaseModel):
    id: uuid.UUID
    category: str
    source_type: str
    source_url_or_identifier: str
    captured_at: datetime
    confidence: str
    normalized_payload_json: dict
    human_readable_summary: str
    raw_response_reference: str | None

    model_config = {"from_attributes": True}


class FindingOut(BaseModel):
    id: uuid.UUID
    category: str
    severity: str
    confidence: str
    title: str
    impact: str
    recommended_next_step: str
    dollar_impact: str
    remediation_timing: str
    status: str
    rule_version: int
    created_at: datetime
    evidence: list[EvidenceItemOut] = []

    model_config = {"from_attributes": True}
