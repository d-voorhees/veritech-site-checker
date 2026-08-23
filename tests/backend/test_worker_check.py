from app.worker_check import check_chromium_launch


def test_chromium_launches_and_renders_fixture():
    """Real Playwright/Chromium launch — no mocking. This is the same check
    that runs at Docker image build time (see Dockerfile) and via
    `make fly-scan-runner-test`, so a host that can't launch Chromium fails
    loudly before it ever gets a real scan.
    """
    assert check_chromium_launch() is True
