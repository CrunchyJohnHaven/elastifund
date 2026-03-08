#!/usr/bin/env python3
"""Human-friendly environment diagnostics for local Elastifund setup."""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIN_PYTHON = (3, 10)


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    detail: str


def check_python() -> CheckResult:
    version = sys.version_info
    ok = version >= MIN_PYTHON
    detail = f"{version.major}.{version.minor}.{version.micro}"
    if not ok:
        detail += f" (need >= {MIN_PYTHON[0]}.{MIN_PYTHON[1]})"
    return CheckResult("python", "pass" if ok else "fail", detail)


def check_command(name: str, args: list[str], success_detail: str) -> CheckResult:
    binary = shutil.which(args[0])
    if not binary:
        return CheckResult(name, "fail", f"{args[0]} not installed")
    result = subprocess.run(
        args,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return CheckResult(name, "pass", success_detail)
    stderr = result.stderr.strip() or result.stdout.strip() or "command failed"
    return CheckResult(name, "fail", stderr)


def check_optional_command(name: str, args: list[str], success_detail: str, missing_detail: str) -> CheckResult:
    binary = shutil.which(args[0])
    if not binary:
        return CheckResult(name, "warn", missing_detail)
    result = subprocess.run(
        args,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return CheckResult(name, "pass", success_detail)
    stderr = result.stderr.strip() or result.stdout.strip() or "command failed"
    return CheckResult(name, "warn", stderr)


def check_env_file() -> CheckResult:
    env_path = ROOT / ".env"
    if env_path.exists():
        return CheckResult("env_file", "pass", ".env present")
    return CheckResult("env_file", "warn", "missing .env (run python3 scripts/quickstart.py --prepare-only)")


def check_preflight() -> CheckResult:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return CheckResult("preflight", "warn", "skipped because .env is missing")
    result = subprocess.run(
        [sys.executable, "scripts/elastifund_setup.py", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return CheckResult("preflight", "pass", "preflight checks passed")
    detail = (
        result.stdout.strip().splitlines()[0]
        if result.stdout.strip()
        else result.stderr.strip() or "preflight failed"
    )
    return CheckResult("preflight", "fail", detail)


def run_checks() -> list[CheckResult]:
    return [
        check_python(),
        check_command("git", ["git", "--version"], "git installed"),
        check_optional_command(
            "docker",
            ["docker", "--version"],
            "docker installed",
            "docker not installed (optional unless you want the full local stack)",
        ),
        check_optional_command(
            "docker_compose",
            ["docker", "compose", "version"],
            "docker compose available",
            "docker compose unavailable (install Docker to run the full local stack)",
        ),
        check_env_file(),
        check_preflight(),
    ]


def format_results(results: list[CheckResult]) -> str:
    width = max(len(result.name) for result in results)
    return "\n".join(
        f"{result.name.ljust(width)}  {result.status.upper():<5}  {result.detail}"
        for result in results
    )


def main() -> int:
    results = run_checks()
    print(format_results(results))
    if any(result.status == "fail" for result in results):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
