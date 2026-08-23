import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.evidence import FindingOut


class FindingSeverityCounts(BaseModel):
    high: int = 0
    medium: int = 0
    low: int = 0
    info: int = 0


class LimitationOut(BaseModel):
    task_name: str
    message: str


class ReportOut(BaseModel):
    scan_id: uuid.UUID
    product_name: str
    parent_brand: str
    report_name: str
    domain: str
    original_input: str
    notes: str
    status: str
    max_pages: int
    authorization_confirmed_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    pages_scanned: int
    is_demo: bool

    severity_counts: FindingSeverityCounts
    findings: list[FindingOut]
    rules_checked: dict
    coverage: dict

    dns_email: dict
    http_security: dict
    crawl_indexability: dict
    technology: dict
    third_party_dependencies: dict
    performance: dict
    tls: dict
    platform_exposure: dict
    domain_registration: dict
    accessibility: dict

    scope_statement: str
    limitations: list[LimitationOut]
    generated_at: datetime
