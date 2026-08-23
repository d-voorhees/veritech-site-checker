import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_user, get_current_user_optional
from app.core.rate_limit import RateLimitExceeded, enforce_scan_creation_rate_limit
from app.core.url_safety import UnsafeTargetError
from app.db import get_db
from app.models.evidence import EvidenceItem
from app.models.finding import Finding, FindingEvidence
from app.models.scan import CLAIMABLE_SCAN_STATUSES, SCAN_STATUS_RUNNING, ScanRequest
from app.models.user import User
from app.schemas.evidence import EvidenceItemOut, FindingOut
from app.schemas.report import ReportOut
from app.schemas.scan import ScanCreateRequest, ScanDetailOut, ScanEventOut, ScanSummaryOut
from app.services.fly_machines import FlyMachinesError
from app.services.html_export import render_report_html
from app.services.report_builder import build_report
from app.services.scan_orchestrator import create_scan, request_scan_runner

router = APIRouter(prefix="/scans", tags=["scans"])


def _get_owned_scan(db: Session, scan_id: uuid.UUID, user: User) -> ScanRequest:
    scan = db.get(ScanRequest, scan_id)
    if not scan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scan not found")
    if scan.user_id != user.id and not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have access to this scan")
    return scan


@router.post("", response_model=ScanDetailOut, status_code=status.HTTP_201_CREATED)
def create_scan_endpoint(
    payload: ScanCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ScanDetailOut:
    try:
        enforce_scan_creation_rate_limit(db, user.id)
    except RateLimitExceeded as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc

    try:
        scan = create_scan(db, user, payload)
    except UnsafeTargetError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    try:
        request_scan_runner(db, scan)
    except FlyMachinesError as exc:
        # request_scan_runner() has already marked the scan `failed` and
        # recorded the failure event — never leave a scan appearing to be
        # queued/running when its runner never actually started.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to start the scan runner; the scan has been marked as failed.",
        ) from exc

    db.refresh(scan)
    return scan


@router.get("", response_model=list[ScanSummaryOut])
def list_scans(
    scope: str = Query("mine", pattern="^(mine|all)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ScanSummaryOut]:
    query = db.query(ScanRequest)
    if scope == "all" and user.is_admin:
        pass
    else:
        query = query.filter(ScanRequest.user_id == user.id)
    return query.order_by(ScanRequest.created_at.desc()).all()


@router.get("/{scan_id}", response_model=ScanDetailOut)
def get_scan(
    scan_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> ScanDetailOut:
    scan = _get_owned_scan(db, scan_id, user)
    db.refresh(scan)
    _ = scan.jobs  # ensure loaded
    return scan


@router.delete("/{scan_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_scan(
    scan_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> Response:
    scan = _get_owned_scan(db, scan_id, user)
    if scan.status in CLAIMABLE_SCAN_STATUSES or scan.status == SCAN_STATUS_RUNNING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Cannot delete a scan that is still in progress."
        )
    db.delete(scan)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{scan_id}/events", response_model=list[ScanEventOut])
def get_scan_events(
    scan_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[ScanEventOut]:
    scan = _get_owned_scan(db, scan_id, user)
    return scan.events


@router.get("/{scan_id}/findings", response_model=list[FindingOut])
def get_scan_findings(
    scan_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[FindingOut]:
    scan = _get_owned_scan(db, scan_id, user)
    findings = (
        db.query(Finding)
        .options(joinedload(Finding.evidence_links).joinedload(FindingEvidence.evidence_item))
        .filter(Finding.scan_request_id == scan.id)
        .all()
    )
    severity_rank = {"high": 0, "medium": 1, "low": 2, "info": 3}
    findings.sort(key=lambda f: (severity_rank.get(f.severity, 9), f.created_at))
    return [
        FindingOut(
            id=f.id,
            category=f.category,
            severity=f.severity,
            confidence=f.confidence,
            title=f.title,
            impact=f.impact,
            recommended_next_step=f.recommended_next_step,
            status=f.status,
            rule_version=f.rule_version,
            created_at=f.created_at,
            evidence=[EvidenceItemOut.model_validate(link.evidence_item) for link in f.evidence_links],
        )
        for f in findings
    ]


@router.get("/{scan_id}/evidence", response_model=list[EvidenceItemOut])
def get_scan_evidence(
    scan_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[EvidenceItemOut]:
    scan = _get_owned_scan(db, scan_id, user)
    items = (
        db.query(EvidenceItem)
        .filter(EvidenceItem.scan_request_id == scan.id)
        .order_by(EvidenceItem.captured_at)
        .all()
    )
    return items


@router.get("/{scan_id}/report", response_model=ReportOut)
def get_scan_report(
    scan_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> ReportOut:
    scan = _get_owned_scan(db, scan_id, user)
    return build_report(db, scan)


@router.get("/{scan_id}/export/html")
def export_scan_html(
    scan_id: uuid.UUID, db: Session = Depends(get_db), user: User | None = Depends(get_current_user_optional)
) -> Response:
    # This link is opened directly in the browser (not fetched from the SPA),
    # so an unauthenticated hit needs a real redirect to the login page
    # instead of a raw {"detail": "Not authenticated"} JSON body.
    if user is None:
        return RedirectResponse(url="/login?session=expired")
    scan = _get_owned_scan(db, scan_id, user)
    report = build_report(db, scan)
    html = render_report_html(report)
    filename = f"veritech-scan-{scan.normalized_domain}-{scan.id}.html"
    return Response(
        content=html,
        media_type="text/html",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
