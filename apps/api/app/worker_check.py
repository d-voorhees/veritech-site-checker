"""Scan-runner environment verification: confirms Chromium/Playwright can
actually launch and render on this host.

`--startup-only` (the only mode now — there's no broker/queue to check
anymore, since scan-runners are one-off Fly Machines, not a persistent
worker) is run at Docker image build time and by `make fly-scan-runner-test`
so a host that cannot launch Chromium fails loudly before it ever gets a
real scan.
"""

import argparse
import sys


def check_chromium_launch() -> bool:
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            page = browser.new_page()
            page.set_content("<html><body><h1>Veritech Scan worker check</h1></body></html>")
            _ = page.title()
            browser.close()
        print("[worker-check] Chromium launched and rendered a fixture page successfully.")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[worker-check] Chromium launch FAILED: {exc}", file=sys.stderr)
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Veritech Scan scan-runner environment verification")
    parser.add_argument(
        "--startup-only", action="store_true", help="Only check Chromium launch (used during image build)"
    )
    args = parser.parse_args()
    _ = args
    sys.exit(0 if check_chromium_launch() else 1)


if __name__ == "__main__":
    main()
