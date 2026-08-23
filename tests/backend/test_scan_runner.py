"""Tests for the scan-runner (app/runner/run.py): duplicate-runner
prevention, invalid scan ID handling, successful completion, partial
completion, unrecoverable failure, and the database-backed event history
each of those leaves behind. All collectors are stubbed — no real network,
DNS, or Playwright calls.
"""

import uuid

import app.core.url_safety as url_safety
from app.collectors import browser_render, crawler, dns_checks, http_checks, performance, robots_sitemap, technology
from app.models.scan import (
    JOB_STATUS_FAILED,
    JOB_STATUS_SUCCEEDED,
    SCAN_STATUS_COMPLETED,
    SCAN_STATUS_COMPLETED_WITH_WARNINGS,
    SCAN_STATUS_FAILED,
    ScanEvent,
    ScanJob,
    ScanRequest,
)
from app.runner.run import EXIT_OK, EXIT_UNRECOVERABLE, run_scan
from app.schemas.scan import ScanCreateRequest
from app.services.scan_orchestrator import create_scan

COLLECTOR_PATCH_TARGETS = {
    "http_checks": (http_checks, "run_http_checks"),
    "robots_sitemap": (robots_sitemap, "run_robots_and_sitemap_checks"),
    "crawl": (crawler, "run_crawl"),
    "dns_email_posture": (dns_checks, "run_dns_and_email_checks"),
    "browser_render": (browser_render, "run_browser_render"),
    "technology_detection": (technology, "run_technology_detection"),
    "performance": (performance, "run_performance_checks"),
}


def _queued_scan(db, user, monkeypatch, ip="93.184.216.34"):
    monkeypatch.setattr(url_safety, "resolve_hostname", lambda hostname, resolver=None: [ip])
    payload = ScanCreateRequest(
        target_input="example.com", notes="", max_pages=10, authorization_acknowledgment=True
    )
    return create_scan(db, user, payload)


def _stub_collectors(monkeypatch, *, fail_task: str | None = None):
    """Every collector stage becomes a fast no-op; `fail_task`, if given,
    always raises instead (exercising _run_job's retry-then-fail path).
    """
    for task_name, (module, fn_name) in COLLECTOR_PATCH_TARGETS.items():
        if task_name == fail_task:
            def failing(*args, **kwargs):
                raise RuntimeError(f"simulated failure in {task_name}")

            monkeypatch.setattr(module, fn_name, failing)
        else:
            monkeypatch.setattr(module, fn_name, lambda *args, **kwargs: {})


def _event_types(db, scan_id):
    return [e.event_type for e in db.query(ScanEvent).filter_by(scan_request_id=scan_id).order_by(ScanEvent.created_at).all()]


def test_runner_startup_with_missing_scan_id_returns_unrecoverable(db):
    assert run_scan(str(uuid.uuid4())) == EXIT_UNRECOVERABLE


def test_runner_startup_with_malformed_scan_id_returns_unrecoverable(db):
    assert run_scan("not-a-uuid") == EXIT_UNRECOVERABLE


def test_successful_completion_sets_status_and_full_event_history(db, user, monkeypatch):
    scan = _queued_scan(db, user, monkeypatch)
    _stub_collectors(monkeypatch)

    exit_code = run_scan(str(scan.id), runner_machine_id="test-machine-1")

    assert exit_code == EXIT_OK
    db.refresh(scan)
    assert scan.status == SCAN_STATUS_COMPLETED
    assert scan.runner_machine_id == "test-machine-1"
    assert scan.started_at is not None
    assert scan.completed_at is not None
    assert scan.heartbeat_at is not None

    jobs = db.query(ScanJob).filter_by(scan_request_id=scan.id).all()
    assert all(j.status == JOB_STATUS_SUCCEEDED for j in jobs)

    events = _event_types(db, scan.id)
    assert "scan_queued" in events
    assert "runner_started" in events
    assert "http_checks_started" in events
    assert "http_checks_succeeded" in events
    assert "findings_generated" in events
    assert "scan_completed" in events
    assert "report_finalized" in events
    assert "runner_exited" in events


def test_partial_completion_preserves_other_evidence(db, user, monkeypatch):
    scan = _queued_scan(db, user, monkeypatch)
    _stub_collectors(monkeypatch, fail_task="crawl")

    exit_code = run_scan(str(scan.id))

    assert exit_code == EXIT_OK
    db.refresh(scan)
    assert scan.status == SCAN_STATUS_COMPLETED_WITH_WARNINGS
    assert "crawl" in scan.failure_summary

    jobs = {j.task_name: j for j in db.query(ScanJob).filter_by(scan_request_id=scan.id).all()}
    assert jobs["crawl"].status == JOB_STATUS_FAILED
    assert jobs["crawl"].attempts == 2  # MAX_ATTEMPTS
    # Other stages still ran and succeeded — one failure doesn't abort the scan.
    assert jobs["http_checks"].status == JOB_STATUS_SUCCEEDED
    assert jobs["dns_email_posture"].status == JOB_STATUS_SUCCEEDED

    events = _event_types(db, scan.id)
    assert "crawl_failed" in events
    assert "http_checks_succeeded" in events


def test_duplicate_runner_is_a_safe_no_op(db, user, monkeypatch):
    scan = _queued_scan(db, user, monkeypatch)
    _stub_collectors(monkeypatch)

    first = run_scan(str(scan.id))
    assert first == EXIT_OK
    db.refresh(scan)
    assert scan.status == SCAN_STATUS_COMPLETED
    events_after_first = _event_types(db, scan.id)

    # A second runner invocation for the same (now-finished) scan must not
    # reprocess it or emit a second "runner_started"/collection-stage event.
    second = run_scan(str(scan.id))
    assert second == EXIT_OK
    db.refresh(scan)
    assert scan.status == SCAN_STATUS_COMPLETED

    events_after_second = _event_types(db, scan.id)
    assert events_after_second == events_after_first + ["runner_duplicate_skipped"]
    assert events_after_second.count("runner_started") == 1


def test_unrecoverable_runner_failure_marks_scan_failed(db, user, monkeypatch):
    scan = _queued_scan(db, user, monkeypatch)
    _stub_collectors(monkeypatch)

    # Simulate a data-integrity bug: a ScanJob row missing for a stage the
    # runner is about to execute. _run_job dereferences it unconditionally,
    # so this is a genuine unrecoverable runner-level error, not a
    # collector-level failure that _run_job's own retry logic would catch.
    db.query(ScanJob).filter_by(scan_request_id=scan.id, task_name="http_checks").delete()
    db.commit()

    exit_code = run_scan(str(scan.id))

    assert exit_code == EXIT_UNRECOVERABLE
    db.refresh(scan)
    assert scan.status == SCAN_STATUS_FAILED
    assert scan.failure_summary

    events = _event_types(db, scan.id)
    assert "runner_failed" in events
