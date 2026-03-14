#!/usr/bin/env python3
"""Instance 5 runner: cross-asset cascade scoring + Monte Carlo artifacts."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import time

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.cross_asset_cascade import run_instance5_cycle


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=REPO_ROOT,
        help="Workspace root path (default: repo root).",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run continuously and emit artifacts every --interval-seconds.",
    )
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=15,
        help="Daemon loop interval in seconds (default: 15).",
    )
    parser.add_argument(
        "--duration-seconds",
        type=int,
        default=120,
        help="Total daemon duration in seconds; <=0 means run forever.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    root = args.root.resolve()

    if not args.daemon:
        payload = run_instance5_cycle(root)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    interval_seconds = max(1, int(args.interval_seconds))
    duration_seconds = int(args.duration_seconds)
    started_at = datetime.now(timezone.utc)
    stop_at = None if duration_seconds <= 0 else started_at + timedelta(seconds=duration_seconds)

    last_payload: dict[str, object] = {}
    while True:
        loop_started = time.monotonic()
        last_payload = run_instance5_cycle(root)

        if stop_at is not None and datetime.now(timezone.utc) >= stop_at:
            break

        elapsed = time.monotonic() - loop_started
        sleep_for = max(0.0, float(interval_seconds) - elapsed)
        time.sleep(sleep_for)

    print(json.dumps(last_payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
