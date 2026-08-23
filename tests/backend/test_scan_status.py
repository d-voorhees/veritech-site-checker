from types import SimpleNamespace

from app.models.scan import (
    JOB_STATUS_FAILED,
    JOB_STATUS_SUCCEEDED,
    SCAN_STATUS_COMPLETED,
    SCAN_STATUS_COMPLETED_WITH_WARNINGS,
    SCAN_STATUS_FAILED,
)
from app.runner.run import determine_scan_status


def job(task_name, status):
    return SimpleNamespace(task_name=task_name, status=status)


def test_all_succeeded_is_completed():
    jobs = [job("http_checks", JOB_STATUS_SUCCEEDED), job("dns_email_posture", JOB_STATUS_SUCCEEDED)]
    status, summary = determine_scan_status(jobs)
    assert status == SCAN_STATUS_COMPLETED
    assert summary is None


def test_partial_failure_is_completed_with_warnings():
    jobs = [
        job("http_checks", JOB_STATUS_SUCCEEDED),
        job("browser_render", JOB_STATUS_FAILED),
        job("rules_engine", JOB_STATUS_SUCCEEDED),
    ]
    status, summary = determine_scan_status(jobs)
    assert status == SCAN_STATUS_COMPLETED_WITH_WARNINGS
    assert "browser_render" in summary
    assert "1 of 3" in summary


def test_all_failed_is_failed():
    jobs = [job("http_checks", JOB_STATUS_FAILED), job("dns_email_posture", JOB_STATUS_FAILED)]
    status, summary = determine_scan_status(jobs)
    assert status == SCAN_STATUS_FAILED
    assert "no evidence" in summary.lower()
