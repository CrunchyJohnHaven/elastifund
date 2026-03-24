#!/usr/bin/env python3
"""Run one local structural-profit cycle and publish the resulting state."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.report_envelope import write_report  # noqa: E402

PYTHON = sys.executable
REPORT_PATH = REPO_ROOT / "reports" / "structural_alpha" / "local_cycle.json"


def _run(relpath: str, extra_args: list[str] | None = None) -> dict[str, Any]:
    cmd = [PYTHON, str(REPO_ROOT / relpath)] + (extra_args or [])
    result = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "script": relpath,
        "args": list(extra_args or []),
        "returncode": result.returncode,
        "stdout_tail": "\n".join(result.stdout.splitlines()[-8:]),
        "stderr_tail": "\n".join(result.stderr.splitlines()[-8:]),
    }


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _artifact_state(path: Path) -> dict[str, Any]:
    payload = _load_json(path)
    return {
        "path": str(path),
        "exists": path.exists(),
        "status": payload.get("status") if isinstance(payload, dict) else None,
        "generated_at": payload.get("generated_at") if isinstance(payload, dict) else None,
    }


def build_cycle() -> dict[str, Any]:
    steps = [
        _run("scripts/canonical_truth_writer.py"),
        _run("scripts/continuous_structural_scanner.py", ["--once"]),
        _run("scripts/simulation_lab.py", ["all"]),
        _run("scripts/run_promotion_bundle.py"),
        _run("scripts/run_strike_factory.py"),
    ]

    structural_queue = _load_json(REPO_ROOT / "reports" / "structural_alpha" / "live_queue.json") or {}
    lane_snapshot = _load_json(REPO_ROOT / "reports" / "structural_alpha" / "structural_lane_snapshot.json") or {}

    blockers: list[str] = []
    artifact_states = {
        "canonical_truth": REPO_ROOT / "reports" / "canonical_operator_truth.json",
        "simulation_ranking": REPO_ROOT / "reports" / "simulation" / "ranked_candidates.json",
        "promotion_bundle": REPO_ROOT / "reports" / "promotion_bundle.json",
        "structural_lane_snapshot": REPO_ROOT / "reports" / "structural_alpha" / "structural_lane_snapshot.json",
    }
    for key, path in artifact_states.items():
        if not path.exists():
            blockers.append(f"{key}_missing")
    for step in steps:
        if step["returncode"] != 0:
            blockers.append(f"{Path(step['script']).stem}_failed")

    artifacts = {
        "canonical_truth": _artifact_state(REPO_ROOT / "reports" / "canonical_operator_truth.json"),
        "simulation_ranking": _artifact_state(REPO_ROOT / "reports" / "simulation" / "ranked_candidates.json"),
        "promotion_bundle": _artifact_state(REPO_ROOT / "reports" / "promotion_bundle.json"),
        "strike_factory": _artifact_state(REPO_ROOT / "reports" / "strike_factory" / "latest.json"),
        "structural_lane_snapshot": _artifact_state(REPO_ROOT / "reports" / "structural_alpha" / "structural_lane_snapshot.json"),
        "structural_live_queue": _artifact_state(REPO_ROOT / "reports" / "structural_alpha" / "live_queue.json"),
    }
    for name, artifact in artifacts.items():
        status = str(artifact.get("status") or "").strip().lower()
        if status in {"blocked", "stale", "error"}:
            blockers.append(f"{name}_{status}")

    return {
        "artifact": "structural_profit_cycle.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "steps": steps,
        "artifacts": artifacts,
        "recommended_live_lane": structural_queue.get("recommended_live_lane"),
        "recommended_size_usd": structural_queue.get("recommended_size_usd"),
        "proof_status": structural_queue.get("proof_status"),
        "lane_count": len(lane_snapshot.get("lanes") or []),
        "blockers": list(dict.fromkeys(blockers)),
        "status": "blocked" if blockers else "fresh",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)

    report = build_cycle()
    write_report(
        REPORT_PATH,
        artifact="structural_profit_cycle",
        payload=report,
        status=report["status"],
        source_of_truth=(
            "reports/canonical_operator_truth.json; reports/simulation/ranked_candidates.json; "
            "reports/promotion_bundle.json; reports/structural_alpha/live_queue.json"
        ),
        freshness_sla_seconds=1800,
        blockers=list(report.get("blockers") or []),
        summary=(
            f"recommended_live_lane={report.get('recommended_live_lane') or 'none'} "
            f"proof_status={report.get('proof_status') or 'none'}"
        ),
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "fresh" else 1


if __name__ == "__main__":
    raise SystemExit(main())
