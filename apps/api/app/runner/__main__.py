"""CLI entrypoint for the scan-runner role: `python -m app.runner`.

Reads the scan ID from the SCAN_ID environment variable (how the Fly
Machines API launches it — see app/services/scan_orchestrator.py) or, for
manual/local invocation, from the first command-line argument. Exits 0 on
success or a safe no-op (duplicate/already-claimed scan), non-zero only for
an unrecoverable runner-level failure.
"""

import os
import sys

from app.runner.run import run_scan


def main() -> None:
    scan_id = os.environ.get("SCAN_ID") or (sys.argv[1] if len(sys.argv) > 1 else None)
    if not scan_id:
        print("[scan-runner] No scan ID provided (set SCAN_ID or pass it as an argument).", file=sys.stderr)
        sys.exit(1)

    runner_machine_id = os.environ.get("FLY_MACHINE_ID")
    sys.exit(run_scan(scan_id, runner_machine_id=runner_machine_id))


if __name__ == "__main__":
    main()
