"""The scan-runner: a one-shot process that runs exactly one scan and exits.

Started either as a Fly Machine (production — see
app/services/fly_machines.py and app/services/scan_orchestrator.py) or as a
plain local subprocess (development — no persistent worker in either case).
There is no queue, no broker, and no long-lived process — one runner
processes one scan ID and exits.

Each collection area gets its own ScanJob row and its own bounded retry
(`_run_job`): independent failure isolation and bounded retries per area,
without the operational complexity of a multi-actor DAG for a sequential
pipeline that must respect one overall scan time budget.
"""

import time
import uuid
from datetime import datetime, timezone

from sqlalchemy import update

from app.collectors import browser_render, crawler, dns_checks, http_checks, performance, robots_sitemap, technology
from app.config import get_settings
from app.db import SessionLocal
from app.logging_config import get_logger
from app.models.report import Report
from app.models.scan import (
    CLAIMABLE_SCAN_STATUSES,
    JOB_STATUS_FAILED,
    JOB_STATUS_RUNNING,
    JOB_STATUS_SUCCEEDED,
    SCAN_STATUS_COMPLETED,
    SCAN_STATUS_COMPLETED_WITH_WARNINGS,
    SCAN_STATUS_FAILED,
    SCAN_STATUS_RUNNING,
    ScanJob,
    ScanRequest,
    ScanTarget,
)
from app.models.user import User
from app.rules.engine import run_rules_engine
from app.services.artifact_storage import get_artifact_storage
from app.services.brevo_client import BrevoClient, BrevoError
from app.services.html_export import render_report_html, render_report_text
from app.services.report_builder import build_report
from app.services.report_summary import build_brevo_summary
from app.services.scan_orchestrator import record_event
from app.services.slack_client import SlackError, send_slack_notification

logger = get_logger(__name__)

MAX_ATTEMPTS = 2

EXIT_OK = 0
EXIT_UNRECOVERABLE = 1


def determine_scan_status(jobs) -> tuple[str, str | None]:
    """Pure status-rollup logic, factored out for unit testing: a scan is
    `failed` only if every collection task failed, `completed_with_warnings`
    if some (but not all) failed, else `completed`.
    """
    failed_jobs = [j for j in jobs if j.status == JOB_STATUS_FAILED]
    succeeded_jobs = [j for j in jobs if j.status == JOB_STATUS_SUCCEEDED]

    if not succeeded_jobs:
        return SCAN_STATUS_FAILED, "All collection tasks failed; no evidence was collected."
    if failed_jobs:
        summary = (
            f"{len(failed_jobs)} of {len(jobs)} collection task(s) failed: "
            + ", ".join(j.task_name for j in failed_jobs)
        )
        return SCAN_STATUS_COMPLETED_WITH_WARNINGS, summary
    return SCAN_STATUS_COMPLETED, None


def _touch_heartbeat(db, scan) -> None:
    scan.heartbeat_at = datetime.now(timezone.utc)
    db.commit()


def _run_job(db, scan, task_name, fn):
    """Runs one collection area with a bounded number of attempts. Never
    raises — a permanent failure is recorded on the ScanJob row and the
    runner moves on to the next collection area.
    """
    job = db.query(ScanJob).filter_by(scan_request_id=scan.id, task_name=task_name).first()
    job.status = JOB_STATUS_RUNNING
    job.started_at = datetime.now(timezone.utc)
    record_event(db, scan.id, f"{task_name}_started", f"{task_name.replace('_', ' ').title()} started.")
    db.commit()

    for attempt in range(1, MAX_ATTEMPTS + 1):
        job.attempts = attempt
        db.commit()
        try:
            result = fn()
            job.status = JOB_STATUS_SUCCEEDED
            job.finished_at = datetime.now(timezone.utc)
            record_event(db, scan.id, f"{task_name}_succeeded", f"{task_name.replace('_', ' ').title()} completed.")
            db.commit()
            return result
        except Exception as exc:  # noqa: BLE001 -- collector failures must never crash the scan
            db.rollback()
            logger.warning("collection_task_failed", task=task_name, attempt=attempt, error=str(exc))
            job = db.query(ScanJob).filter_by(scan_request_id=scan.id, task_name=task_name).first()
            job.attempts = attempt
            job.error_message = str(exc)[:2000]
            if attempt >= MAX_ATTEMPTS:
                job.status = JOB_STATUS_FAILED
                job.finished_at = datetime.now(timezone.utc)
                db.commit()
                record_event(
                    db,
                    scan.id,
                    f"{task_name}_failed",
                    f"{task_name.replace('_', ' ').title()} failed after {attempt} attempt(s): {str(exc)[:300]}",
                )
                db.commit()
                return None
            db.commit()

    return None


def _claim_scan(db, scan_id: uuid.UUID, runner_machine_id: str | None) -> bool:
    """Atomically transitions the scan to `running`, guarding against two
    runners processing the same scan (duplicate-runner prevention). Uses a
    single UPDATE...WHERE...RETURNING against the claimable statuses instead
    of a SELECT-then-UPDATE, which would race across two separate runner
    processes/connections. Returns True iff this call won the claim.
    """
    result = db.execute(
        update(ScanRequest)
        .where(ScanRequest.id == scan_id, ScanRequest.status.in_(CLAIMABLE_SCAN_STATUSES))
        .values(
            status=SCAN_STATUS_RUNNING,
            started_at=datetime.now(timezone.utc),
            heartbeat_at=datetime.now(timezone.utc),
            runner_machine_id=runner_machine_id,
        )
        .returning(ScanRequest.id)
    )
    claimed = result.first() is not None
    db.commit()
    return claimed


def run_scan(scan_id: str, runner_machine_id: str | None = None) -> int:
    """Runs one scan end to end and returns a process exit code. Safe to
    retry: a scan that's already been claimed (or finished) by another
    runner is a no-op, not an error.
    """
    settings = get_settings()
    db = SessionLocal()
    try:
        try:
            scan_uuid = uuid.UUID(scan_id)
        except (ValueError, TypeError):
            logger.error("scan_runner_invalid_scan_id", scan_id=scan_id)
            return EXIT_UNRECOVERABLE

        scan = db.get(ScanRequest, scan_uuid)
        if not scan:
            logger.error("scan_not_found", scan_id=scan_id)
            return EXIT_UNRECOVERABLE

        if not _claim_scan(db, scan_uuid, runner_machine_id):
            # Either another runner already claimed this scan, or it's
            # already in a terminal state. Idempotent no-op, not a failure.
            record_event(
                db, scan_uuid, "runner_duplicate_skipped", "Runner exited: scan was already claimed or finished."
            )
            db.commit()
            return EXIT_OK

        db.refresh(scan)
        record_event(db, scan.id, "runner_started", f"Runner started for scan {scan.id}.")
        db.commit()

        try:
            target = db.query(ScanTarget).filter_by(scan_request_id=scan.id).first()
            if target is None:
                # create_scan() always writes a ScanTarget alongside the
                # ScanRequest — this would indicate a data integrity bug,
                # not a user-facing condition.
                logger.error("scan_target_missing", scan_id=scan_id)
                record_event(db, scan.id, "runner_failed", "Internal error: scan target record is missing.")
                scan.status = SCAN_STATUS_FAILED
                scan.failure_summary = "Internal error: scan target record is missing."
                db.commit()
                return EXIT_UNRECOVERABLE

            deadline = time.monotonic() + settings.scan_max_total_minutes * 60

            def time_remaining() -> bool:
                return time.monotonic() < deadline

            http_result = None
            browser_result = None

            if time_remaining():
                http_result = _run_job(
                    db,
                    scan,
                    "http_checks",
                    lambda: http_checks.run_http_checks(
                        db, scan.id, target.canonical_url, hostname=target.hostname, resolved_ips=target.resolved_ips
                    ),
                )
            _touch_heartbeat(db, scan)

            robots_result = None
            if time_remaining():
                robots_result = _run_job(
                    db,
                    scan,
                    "robots_sitemap",
                    lambda: robots_sitemap.run_robots_and_sitemap_checks(
                        db, scan.id, target.canonical_url, scan.max_pages
                    ),
                )
            _touch_heartbeat(db, scan)

            if time_remaining():
                _run_job(
                    db,
                    scan,
                    "crawl",
                    lambda: crawler.run_crawl(
                        db,
                        scan.id,
                        target.canonical_url,
                        target.hostname,
                        scan.max_pages,
                        sitemap_urls=(robots_result or {}).get("discovered_urls"),
                    ),
                )
            _touch_heartbeat(db, scan)

            if time_remaining():
                _run_job(
                    db,
                    scan,
                    "dns_email_posture",
                    lambda: dns_checks.run_dns_and_email_checks(db, scan.id, target.hostname),
                )
            _touch_heartbeat(db, scan)

            if time_remaining():
                browser_result = _run_job(
                    db,
                    scan,
                    "browser_render",
                    lambda: browser_render.run_browser_render(db, scan.id, target.canonical_url, target.hostname),
                )
            _touch_heartbeat(db, scan)

            if time_remaining():
                _run_job(
                    db,
                    scan,
                    "technology_detection",
                    lambda: technology.run_technology_detection(
                        db,
                        scan.id,
                        (http_result or {}).get("html_text"),
                        (http_result or {}).get("headers", {}),
                        (browser_result or {}).get("rendered_html"),
                        (robots_result or {}).get("robots_body_excerpt"),
                    ),
                )
            _touch_heartbeat(db, scan)

            if time_remaining():
                perf_context = {
                    "response_duration_ms": (http_result or {}).get("response_duration_ms"),
                    "html_bytes": (http_result or {}).get("html_bytes"),
                    "third_party_domain_count": (browser_result or {}).get("third_party_domain_count"),
                    "js_resource_count": (browser_result or {}).get("js_resource_count"),
                }
                _run_job(
                    db,
                    scan,
                    "performance",
                    lambda: performance.run_performance_checks(
                        db, scan.id, (http_result or {}).get("final_url", target.canonical_url), perf_context
                    ),
                )
            _touch_heartbeat(db, scan)

            # Always run the rules engine against whatever evidence was
            # collected, even if the deadline passed partway through
            # collection.
            findings = _run_job(db, scan, "rules_engine", lambda: run_rules_engine(db, scan))
            findings_count = len(findings) if findings is not None else 0
            record_event(db, scan.id, "findings_generated", f"{findings_count} finding(s) generated.")
            db.commit()

            db.refresh(scan)
            jobs = db.query(ScanJob).filter_by(scan_request_id=scan.id).all()
            scan.status, scan.failure_summary = determine_scan_status(jobs)
            scan.completed_at = datetime.now(timezone.utc)
            record_event(db, scan.id, "scan_completed", f"Scan finished with status: {scan.status}.")
            db.commit()

            try:
                report = build_report(db, scan)
                html = render_report_html(report)
                email_html = render_report_html(report, for_email=True)
                storage = get_artifact_storage()
                path = storage.save(f"{scan.id}/report.html", html.encode("utf-8"))

                report_row = Report(
                    scan_request_id=scan.id,
                    format="html",
                    storage_path=path,
                    generated_at=datetime.now(timezone.utc),
                )

                if scan.status in (SCAN_STATUS_COMPLETED, SCAN_STATUS_COMPLETED_WITH_WARNINGS):
                    # A Brevo push failure must never affect a scan the user
                    # can already see the report for, so it's wrapped
                    # separately from the report-row write above it.
                    try:
                        report_url = f"{settings.app_url}/scans/{scan.id}"
                        summary = build_brevo_summary(report, report_url)
                        report_row.brevo_summary_json = summary
                        user = db.get(User, scan.user_id)
                        if user and settings.brevo_api_key:
                            with BrevoClient(settings.brevo_api_key) as brevo:
                                brevo.upsert_contact(
                                    email=user.email,
                                    attributes={
                                        "LAST_SCAN_URL": summary["last_scan_url"],
                                        "LAST_SCAN_DATE": summary["last_scan_date"],
                                        "LAST_SCAN_RISK_LEVEL": summary["last_scan_risk_level"],
                                        "LAST_SCAN_TOP_FINDING": summary["last_scan_top_finding"],
                                        "LAST_SCAN_FINDING_COUNT_RED": summary["last_scan_finding_count_red"],
                                        "LAST_SCAN_FINDING_COUNT_YELLOW": summary["last_scan_finding_count_yellow"],
                                    },
                                )
                    except BrevoError as exc:
                        logger.warning("brevo_scan_summary_sync_failed", scan_id=scan_id, error=str(exc))
                        record_event(db, scan.id, "brevo_scan_summary_sync_failed", str(exc)[:500])

                    # Each of the two notifications below is independently
                    # wrapped — a Slack outage must never prevent the
                    # results-copy email, and vice versa. Both outcomes are
                    # also recorded as scan events (not just server logs,
                    # which are ephemeral) so "did the alert actually fire"
                    # stays answerable after the fact.
                    try:
                        send_slack_notification(
                            settings.slack_webhook_url,
                            (
                                "*:white_check_mark: VERITECH SITE CHECKER — Scan Completed*\n"
                                f"*Domain:* {scan.normalized_domain}\n"
                                f"*Status:* {scan.status}\n"
                                f"*Report:* {report_url}"
                            ),
                        )
                        record_event(db, scan.id, "slack_completion_notification_sent", "Slack completion alert sent.")
                    except SlackError as exc:
                        logger.warning("slack_scan_completed_notification_failed", scan_id=scan_id, error=str(exc))
                        record_event(db, scan.id, "slack_completion_notification_failed", str(exc)[:500])

                    if settings.results_notification_email and settings.brevo_api_key:
                        try:
                            with BrevoClient(settings.brevo_api_key) as brevo:
                                brevo.send_html_email(
                                    to_email=settings.results_notification_email,
                                    sender_email=settings.brevo_sender_email,
                                    sender_name=settings.brevo_sender_name,
                                    subject=f"Scan completed: {scan.normalized_domain}",
                                    html_content=email_html,
                                    text_content=render_report_text(email_html),
                                )
                            record_event(
                                db,
                                scan.id,
                                "results_email_sent",
                                f"Results copy emailed to {settings.results_notification_email}.",
                            )
                        except BrevoError as exc:
                            logger.warning("results_copy_email_failed", scan_id=scan_id, error=str(exc))
                            record_event(db, scan.id, "results_email_failed", str(exc)[:500])
                    else:
                        record_event(
                            db,
                            scan.id,
                            "results_email_skipped",
                            "Results copy email skipped: RESULTS_NOTIFICATION_EMAIL or BREVO_API_KEY not configured.",
                        )

                db.add(report_row)
                record_event(db, scan.id, "report_finalized", "Report generated and stored.")
                db.commit()
            except Exception as exc:  # noqa: BLE001
                logger.warning("report_generation_failed", scan_id=scan_id, error=str(exc))
                db.rollback()

            record_event(db, scan.id, "runner_exited", f"Runner exited normally with status {scan.status}.")
            db.commit()
            return EXIT_OK

        except Exception as exc:  # noqa: BLE001 -- unrecoverable runner-level failure
            db.rollback()
            logger.error("scan_runner_unrecoverable_failure", scan_id=scan_id, error=str(exc))
            scan = db.get(ScanRequest, scan_uuid)
            if scan and scan.status == SCAN_STATUS_RUNNING:
                scan.status = SCAN_STATUS_FAILED
                scan.failure_summary = f"Runner failed unexpectedly: {str(exc)[:500]}"
                scan.completed_at = datetime.now(timezone.utc)
                record_event(db, scan.id, "runner_failed", scan.failure_summary)
                db.commit()
            return EXIT_UNRECOVERABLE
    finally:
        db.close()
