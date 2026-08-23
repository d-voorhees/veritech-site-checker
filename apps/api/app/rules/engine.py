import uuid

from sqlalchemy.orm import Session

from veritech_scan_rules import RuleResult, all_rules

from app.logging_config import get_logger
from app.models.finding import Finding, FindingEvidence, FindingRule
from app.models.scan import ScanRequest
from app.rules.context import build_rule_context

logger = get_logger(__name__)


def _get_or_create_rule(db: Session, result: RuleResult) -> FindingRule:
    existing = (
        db.query(FindingRule)
        .filter(FindingRule.rule_key == result.rule_key, FindingRule.version == result.version)
        .first()
    )
    if existing:
        return existing

    rule_row = FindingRule(
        rule_key=result.rule_key,
        version=result.version,
        title=result.title,
        category=result.category,
        default_severity=result.severity,
        default_confidence=result.confidence,
        description=result.impact,
    )
    db.add(rule_row)
    db.flush()
    return rule_row


def run_rules_engine(db: Session, scan: ScanRequest) -> list[uuid.UUID]:
    """Runs every registered rule against the scan's collected evidence and
    persists Finding + FindingEvidence rows. Deterministic and idempotent-ish:
    re-running clears prior findings for this scan first so results always
    reflect the current evidence set.
    """
    db.query(Finding).filter(Finding.scan_request_id == scan.id).delete(synchronize_session=False)
    db.flush()

    context = build_rule_context(db, scan)
    created_ids: list[uuid.UUID] = []

    for rule_func in all_rules():
        result = rule_func(context)
        if result is None:
            continue

        # A single malformed rule result (e.g. a bad RuleResult from the
        # private rules package) must not take down every other finding
        # for this scan — each rule gets its own savepoint so a failure
        # here rolls back only this rule's row, not the whole batch.
        try:
            with db.begin_nested():
                rule_row = _get_or_create_rule(db, result)

                finding = Finding(
                    scan_request_id=scan.id,
                    rule_id=rule_row.id,
                    rule_version=result.version,
                    category=result.category,
                    severity=result.severity,
                    confidence=result.confidence,
                    title=result.title,
                    impact=result.impact,
                    recommended_next_step=result.recommended_next_step,
                    dollar_impact=result.dollar_impact,
                    remediation_timing=result.remediation_timing,
                )
                db.add(finding)
                db.flush()

                for evidence_id in result.evidence_ids:
                    db.add(FindingEvidence(finding_id=finding.id, evidence_item_id=evidence_id))
        except Exception as exc:  # noqa: BLE001
            logger.error("rule_finding_persist_failed", rule_key=result.rule_key, error=str(exc))
            continue

        created_ids.append(finding.id)

    db.flush()
    return created_ids
