#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENABLE_JJ_LIVE_SUITE = "ELASTIFUND_ENABLE_JJ_LIVE_SUITE"
JJ_LIVE_TESTS = [
    "bot/tests/test_ensemble_disagreement.py",
    "bot/tests/test_jj_live_instance6.py",
    "bot/tests/test_jj_live_microstructure.py",
    "tests/test_jj_live_combinatorial.py",
    "tests/test_jj_live_sum_violation.py",
]


def _join_pythonpath(paths: list[Path], existing: str | None = None) -> str:
    ordered: list[str] = []
    for path in paths:
        value = str(path)
        if value not in ordered:
            ordered.append(value)
    if existing:
        for value in existing.split(os.pathsep):
            if value and value not in ordered:
                ordered.append(value)
    return os.pathsep.join(ordered)


def _run(label: str, args: list[str], env: dict[str, str]) -> None:
    print(f"[tests] {label}", flush=True)
    result = subprocess.run([sys.executable, "-m", "pytest", *args], cwd=ROOT, env=env)
    if result.returncode:
        raise SystemExit(result.returncode)


def main() -> None:
    base_env = os.environ.copy()

    core_env = base_env.copy()
    core_env.pop(ENABLE_JJ_LIVE_SUITE, None)
    core_env["PYTHONPATH"] = _join_pythonpath(
        [ROOT, ROOT / "edge-backlog"],
        base_env.get("PYTHONPATH"),
    )
    _run("core monorepo suites", ["-q"], core_env)

    if importlib.util.find_spec("yaml") is None:
        print(
            "[tests] skipped simulator/tests/test_simulator.py because "
            "PyYAML is unavailable in the active environment",
            flush=True,
        )

    jj_live_env = base_env.copy()
    jj_live_env["PYTHONPATH"] = _join_pythonpath([ROOT], base_env.get("PYTHONPATH"))
    jj_live_env[ENABLE_JJ_LIVE_SUITE] = "1"
    _run("jj_live import-boundary suites", ["-q", *JJ_LIVE_TESTS], jj_live_env)


if __name__ == "__main__":
    main()
