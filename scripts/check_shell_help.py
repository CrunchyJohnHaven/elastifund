#!/usr/bin/env python3
"""Verify every shell wrapper in scripts/ supports --help safely."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout-seconds", type=float, default=5.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    failures: list[str] = []

    for script in sorted(SCRIPTS_DIR.glob("*.sh")):
        try:
            completed = subprocess.run(
                ["bash", str(script), "--help"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=args.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            failures.append(f"{script}: timed out after {args.timeout_seconds}s")
            continue

        if completed.returncode != 0:
            stderr_tail = completed.stderr.strip().splitlines()[-1] if completed.stderr.strip() else ""
            failures.append(
                f"{script}: exited {completed.returncode}" + (f" ({stderr_tail})" if stderr_tail else "")
            )

    if failures:
        print("shell-help check failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("shell-help check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
