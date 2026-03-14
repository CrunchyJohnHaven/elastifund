#!/usr/bin/env python3
"""Run one bounded autoprompt cycle and publish canonical artifacts."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.run_instance4_autoprompt_guardrails import (  # noqa: E402
    build_instance4_artifact,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LATEST_JSON = REPO_ROOT / "reports" / "autoprompting" / "latest.json"
DEFAULT_CYCLE_DIR = REPO_ROOT / "reports" / "autoprompting" / "cycles"
DEFAULT_MERGE_DIR = REPO_ROOT / "reports" / "autoprompting" / "merges"
DEFAULT_INSTANCE4_JSON = REPO_ROOT / "reports" / "autoprompting" / "instance4" / "latest.json"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%SZ")


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _repo_rel(path: Path, root: Path) -> str:
    try:
        rel = path.resolve().relative_to(root.resolve())
        return rel.as_posix()
    except ValueError:
        return path.as_posix()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _merge_decision_rows(instance4_payload: dict[str, Any]) -> list[dict[str, Any]]:
    examples = instance4_payload.get("examples") if isinstance(instance4_payload.get("examples"), dict) else {}
    rows: list[dict[str, Any]] = []
    for key in ("tier2_judge_verdict", "tier3_judge_verdict"):
        verdict = examples.get(key) if isinstance(examples.get(key), dict) else {}
        merge = verdict.get("merge_decision") if isinstance(verdict.get("merge_decision"), dict) else {}
        row = {
            "run_id": verdict.get("run_id"),
            "lane_name": verdict.get("lane_name"),
            "adapter": verdict.get("adapter"),
            "tier": verdict.get("tier"),
            "judge_decision": verdict.get("decision"),
            "judge_approved": verdict.get("judge_approved"),
            "merge_decision": merge.get("decision"),
            "merge_class": merge.get("merge_class"),
            "missing_requirements": list(merge.get("missing_requirements") or []),
            "autonomous_deploy_allowed": merge.get("autonomous_deploy_allowed"),
        }
        rows.append(row)
    return rows


def _merge_summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    summary = {
        "auto_merge": 0,
        "queued_merge": 0,
        "gated_merge": 0,
        "no_merge": 0,
    }
    for row in rows:
        key = str(row.get("merge_class") or "").strip()
        if key in summary:
            summary[key] += 1
    return summary


def build_autoprompt_cycle(
    *,
    root: Path,
    latest_json_path: Path,
    cycle_dir: Path,
    merge_dir: Path,
    instance4_json_path: Path,
) -> dict[str, Any]:
    now = _utc_now()
    cycle_id = _stamp(now)

    instance4_payload = build_instance4_artifact(root)

    merge_rows = _merge_decision_rows(instance4_payload)
    merges_payload = {
        "schema_version": "autoprompt_merges.v1",
        "generated_at": _iso(now),
        "cycle_id": cycle_id,
        "decisions": merge_rows,
        "summary": _merge_summary(merge_rows),
    }

    cycle_json_path = cycle_dir / f"{cycle_id}.json"
    merge_json_path = merge_dir / f"{cycle_id}.json"

    cycle_payload = {
        "schema_version": "cycle_truth.v1",
        "generated_at": _iso(now),
        "cycle_id": cycle_id,
        "objective": "bounded_autonomy_provider_boundary_phase1",
        "status": "hold_repair" if (instance4_payload.get("stale_hold_repair") or {}).get("active") else "active",
        "contracts": dict(instance4_payload.get("contracts") or {}),
        "instance4_guardrails": instance4_payload,
        "merge_artifact": _repo_rel(merge_json_path, root),
    }

    latest_payload = {
        "schema_version": "autoprompting.v1",
        "generated_at": _iso(now),
        "cycle_id": cycle_id,
        "objective": cycle_payload["objective"],
        "status": cycle_payload["status"],
        "contracts": cycle_payload["contracts"],
        "required_outputs": dict(instance4_payload.get("required_outputs") or {}),
        "stale_hold_repair": dict(instance4_payload.get("stale_hold_repair") or {}),
        "artifacts": {
            "latest_json": _repo_rel(latest_json_path, root),
            "cycle_json": _repo_rel(cycle_json_path, root),
            "merge_json": _repo_rel(merge_json_path, root),
            "instance4_json": _repo_rel(instance4_json_path, root),
        },
        "one_next_cycle_action": instance4_payload.get("one_next_cycle_action"),
    }

    _write_json(instance4_json_path, instance4_payload)
    _write_json(merge_json_path, merges_payload)
    _write_json(cycle_json_path, cycle_payload)
    _write_json(latest_json_path, latest_payload)

    return {
        "cycle_id": cycle_id,
        "latest_json": latest_json_path,
        "cycle_json": cycle_json_path,
        "merge_json": merge_json_path,
        "instance4_json": instance4_json_path,
        "status": latest_payload["status"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one autoprompt cycle and publish artifacts.")
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="Repository root path.")
    parser.add_argument("--latest-json", type=Path, default=DEFAULT_LATEST_JSON)
    parser.add_argument("--cycle-dir", type=Path, default=DEFAULT_CYCLE_DIR)
    parser.add_argument("--merge-dir", type=Path, default=DEFAULT_MERGE_DIR)
    parser.add_argument("--instance4-json", type=Path, default=DEFAULT_INSTANCE4_JSON)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    outcome = build_autoprompt_cycle(
        root=root,
        latest_json_path=args.latest_json,
        cycle_dir=args.cycle_dir,
        merge_dir=args.merge_dir,
        instance4_json_path=args.instance4_json,
    )
    print(
        json.dumps(
            {
                "cycle_id": outcome["cycle_id"],
                "status": outcome["status"],
                "latest_json": _repo_rel(Path(outcome["latest_json"]), root),
                "cycle_json": _repo_rel(Path(outcome["cycle_json"]), root),
                "merge_json": _repo_rel(Path(outcome["merge_json"]), root),
                "instance4_json": _repo_rel(Path(outcome["instance4_json"]), root),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
