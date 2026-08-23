"""Builds the lean, Brevo-bound summary of a finished scan (Part 5 of the
free-launch signup build). Deliberately small — full findings/evidence
already live in their own tables; this is only what gets pushed as contact
attributes to trigger the post-report email sequence.

There's no existing "overall risk" field anywhere in the report pipeline
(ReportOut only carries severity_counts), so the risk read here is derived
from severity counts rather than sourced from an existing field — flagged
here since it's new interpretive logic, not a pre-existing concept in the
data model.
"""

from __future__ import annotations

from app.schemas.report import ReportOut

_SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2, "info": 3, "ok": 4}


def derive_risk_level(report: ReportOut) -> str:
    counts = report.severity_counts
    if counts.high > 0:
        return "High risk"
    if counts.medium > 0:
        return "Medium risk"
    if counts.low > 0:
        return "Low risk"
    return "Minimal risk"


def build_brevo_summary(report: ReportOut, report_url: str) -> dict:
    ranked_findings = sorted(report.findings, key=lambda f: (_SEVERITY_RANK.get(f.severity, 9), f.created_at))
    top_findings = [f.title for f in ranked_findings if f.severity in ("high", "medium")][:2]

    return {
        "last_scan_url": report_url,
        "last_scan_date": report.completed_at.isoformat() if report.completed_at else None,
        "last_scan_risk_level": derive_risk_level(report),
        "last_scan_top_finding": top_findings[0] if top_findings else "No high or medium severity findings.",
        "last_scan_finding_count_red": report.severity_counts.high,
        "last_scan_finding_count_yellow": report.severity_counts.medium,
    }
