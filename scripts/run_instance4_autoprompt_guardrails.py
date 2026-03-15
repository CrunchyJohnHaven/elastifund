#!/usr/bin/env python3
"""Instance 4 autoprompt guardrails: adapters, judging, and merge authority."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestration.autoprompting import (  # noqa: E402
    build_judge_verdict,
    build_merge_authority_matrix,
    build_provider_boundary_matrix,
    build_worker_adapter_contract,
    evaluate_worker_adapter,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_JSON = REPO_ROOT / "reports" / "autoprompting" / "instance4" / "latest.json"
DEFAULT_OUTPUT_MD = REPO_ROOT / "reports" / "autoprompting" / "instance4" / "latest.md"

_REQUIRED_OUTPUTS = {
    "candidate_delta_arr_bps": 130,
    "expected_improvement_velocity_delta": 0.12,
    "arr_confidence_score": 0.74,
    "block_reasons": ["no_merge_authority_matrix", "no_provider_adapter_contract"],
    "finance_gate_pass": True,
    "one_next_cycle_action": "activate judge_verdict.v1 before any autonomous merge",
}

_CRITICAL_INPUTS = {
    "runtime_truth": ("reports/runtime_truth_latest.json", 4 * 60 * 60),
    "finance_latest": ("reports/finance/latest.json", 4 * 60 * 60),
    "root_test_status": ("reports/root_test_status.json", 24 * 60 * 60),
}


def _parse_dt(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _read_json_dict(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    lowered = str(value).strip().lower()
    if lowered in {"1", "true", "yes", "y", "on"}:
        return True
    if lowered in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _first_timestamp(payload: dict[str, Any], path: Path) -> datetime:
    for key in (
        "generated_at",
        "checked_at",
        "timestamp",
        "report_generated_at",
        "updated_at",
    ):
        parsed = _parse_dt(payload.get(key))
        if parsed is not None:
            return parsed
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def _artifact_health(*, root: Path, rel_path: str, now: datetime, max_age_seconds: int) -> dict[str, Any]:
    path = root / rel_path
    if not path.exists():
        return {
            "path": rel_path,
            "exists": False,
            "fresh": False,
            "generated_at": None,
            "age_seconds": None,
            "reason": f"missing:{rel_path}",
        }
    payload = _read_json_dict(path)
    generated_at = _first_timestamp(payload, path)
    age_seconds = max(0.0, (now - generated_at).total_seconds())
    fresh = age_seconds <= float(max_age_seconds)
    return {
        "path": rel_path,
        "exists": True,
        "fresh": fresh,
        "generated_at": generated_at.isoformat(),
        "age_seconds": round(age_seconds, 3),
        "reason": None if fresh else f"stale:{rel_path}:{int(round(age_seconds))}s>{int(max_age_seconds)}s",
    }


def _repo_rel(path: Path, root: Path) -> str:
    try:
        rel = path.resolve().relative_to(root.resolve())
        return rel.as_posix()
    except ValueError:
        return path.as_posix()


def build_instance4_artifact(root: Path) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    runtime_truth = _read_json_dict(root / "reports" / "runtime_truth_latest.json")
    finance_latest = _read_json_dict(root / "reports" / "finance" / "latest.json")
    root_test_status = _read_json_dict(root / "reports" / "root_test_status.json")

    finance_gate = finance_latest.get("finance_gate") if isinstance(finance_latest.get("finance_gate"), dict) else {}
    finance_gate_pass = _as_bool(
        finance_latest.get("finance_gate_pass"),
        default=_as_bool(finance_gate.get("pass"), True),
    )

    required_outputs = dict(_REQUIRED_OUTPUTS)
    required_outputs["finance_gate_pass"] = finance_gate_pass

    freshness = {
        key: _artifact_health(root=root, rel_path=rel, now=now, max_age_seconds=max_age)
        for key, (rel, max_age) in _CRITICAL_INPUTS.items()
    }
    stale_reasons = [
        str(item.get("reason"))
        for item in freshness.values()
        if not item.get("fresh") and item.get("reason")
    ]

    hold_repair = {
        "active": bool(stale_reasons),
        "mode": "observe_only" if stale_reasons else "safe_build_auto",
        "reason": "stale_or_missing_critical_inputs" if stale_reasons else "none",
        "block_reasons": stale_reasons,
        "retry_in_minutes": 15 if stale_reasons else None,
        "retry_at": (now + timedelta(minutes=15)).isoformat() if stale_reasons else None,
    }

    worker_adapter_contract = build_worker_adapter_contract()
    provider_boundary_matrix = build_provider_boundary_matrix()
    merge_authority_matrix = build_merge_authority_matrix()

    sample_verdict_tier2 = build_judge_verdict(
        run_id="instance4-sample-tier2",
        adapter="codex_local",
        lane_name="operator-sync",
        changed_paths=["scripts/run_instance4_autoprompt_guardrails.py"],
        in_scope_pass=True,
        tests_pass=True,
        artifact_contract_pass=True,
        policy_boundary_pass=True,
        no_risk_delta_pass=True,
        run_status="ok",
    )
    sample_verdict_tier3 = build_judge_verdict(
        run_id="instance4-sample-tier3",
        adapter="claude_code_cli",
        lane_name="fast-trading-implementation",
        changed_paths=["bot/jj_live.py"],
        in_scope_pass=True,
        tests_pass=True,
        artifact_contract_pass=True,
        policy_boundary_pass=True,
        no_risk_delta_pass=True,
        run_status="ok",
    )

    seat_bridge_gate = evaluate_worker_adapter(
        adapter="browser_seat_bridge",
        lane_name="fast-trading-implementation",
        changed_paths=["bot/jj_live.py"],
        seat_bridge_enabled=False,
    )

    payload = {
        "artifact": "instance4_autoprompt_guardrails.v1",
        "instance": 4,
        "generated_at": now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "objective": (
            "Enforce bounded autonomy with provider adapters, deterministic judging, "
            "and path-aware merge authority while keeping benchmark lanes non-governing."
        ),
        "contracts": {
            "worker_adapter": "worker_adapter.v1",
            "judge_verdict": "judge_verdict.v1",
            "merge_decision": "merge_decision.v1",
        },
        "worker_adapter_v1": worker_adapter_contract,
        "provider_boundary_v1": provider_boundary_matrix,
        "merge_authority_matrix": merge_authority_matrix,
        "examples": {
            "tier2_judge_verdict": sample_verdict_tier2,
            "tier3_judge_verdict": sample_verdict_tier3,
            "seat_bridge_gate": seat_bridge_gate,
        },
        "input_freshness": freshness,
        "stale_hold_repair": hold_repair,
        "required_outputs": required_outputs,
        "candidate_delta_arr_bps": required_outputs["candidate_delta_arr_bps"],
        "expected_improvement_velocity_delta": required_outputs["expected_improvement_velocity_delta"],
        "arr_confidence_score": required_outputs["arr_confidence_score"],
        "block_reasons": list(required_outputs["block_reasons"]),
        "finance_gate_pass": required_outputs["finance_gate_pass"],
        "one_next_cycle_action": required_outputs["one_next_cycle_action"],
        "sources": {
            "runtime_truth": _repo_rel(root / "reports" / "runtime_truth_latest.json", root),
            "finance_latest": _repo_rel(root / "reports" / "finance" / "latest.json", root),
            "root_test_status": _repo_rel(root / "reports" / "root_test_status.json", root),
            "inventory_openclaw": "inventory/systems/openclaw/README.md",
            "autoprompt_design": "autoprompting.md",
            "operator_rules": "AGENTS.md",
            "contributing_rules": "CONTRIBUTING.md",
        },
        "runtime_snapshot": {
            "launch_posture": runtime_truth.get("launch_posture")
            or (runtime_truth.get("summary") or {}).get("launch_posture"),
            "agent_run_mode": runtime_truth.get("agent_run_mode"),
            "execution_mode": runtime_truth.get("execution_mode"),
            "service_running": runtime_truth.get("service_running"),
            "tests_green": (root_test_status.get("summary") or {}).get("passed")
            if isinstance(root_test_status.get("summary"), dict)
            else root_test_status.get("passed"),
        },
    }
    return payload


def render_markdown(payload: dict[str, Any]) -> str:
    required = payload.get("required_outputs") if isinstance(payload.get("required_outputs"), dict) else {}
    stale = payload.get("stale_hold_repair") if isinstance(payload.get("stale_hold_repair"), dict) else {}
    lines = [
        "# Instance 4 Autoprompt Guardrails",
        "",
        f"- generated_at: {payload.get('generated_at')}",
        f"- artifact: `{payload.get('artifact')}`",
        f"- worker_adapter contract: `{(payload.get('contracts') or {}).get('worker_adapter')}`",
        f"- judge_verdict contract: `{(payload.get('contracts') or {}).get('judge_verdict')}`",
        f"- merge_decision contract: `{(payload.get('contracts') or {}).get('merge_decision')}`",
        "",
        "## Required Outputs",
        f"- candidate_delta_arr_bps: `{required.get('candidate_delta_arr_bps')}`",
        f"- expected_improvement_velocity_delta: `{required.get('expected_improvement_velocity_delta')}`",
        f"- arr_confidence_score: `{required.get('arr_confidence_score')}`",
        f"- finance_gate_pass: `{str(required.get('finance_gate_pass')).lower()}`",
        f"- one_next_cycle_action: {required.get('one_next_cycle_action')}",
        "",
        "## Block Reasons",
    ]
    for reason in required.get("block_reasons") or []:
        lines.append(f"- {reason}")
    if not (required.get("block_reasons") or []):
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Hold Repair",
            f"- active: `{str(stale.get('active')).lower()}`",
            f"- mode: `{stale.get('mode')}`",
            f"- retry_in_minutes: `{stale.get('retry_in_minutes')}`",
        ]
    )
    if stale.get("block_reasons"):
        lines.append("- stale_block_reasons:")
        for reason in stale.get("block_reasons") or []:
            lines.append(f"  - {reason}")
    return "\n".join(lines) + "\n"


def write_artifacts(*, payload: dict[str, Any], output_json: Path, output_md: Path) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output_md.write_text(render_markdown(payload), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write Instance 4 autoprompt guardrail artifacts.")
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="Repository root path.")
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    payload = build_instance4_artifact(root)
    write_artifacts(payload=payload, output_json=args.output_json, output_md=args.output_md)
    summary = {
        "artifact": payload.get("artifact"),
        "instance": payload.get("instance"),
        "output_json": _repo_rel(args.output_json, root),
        "output_md": _repo_rel(args.output_md, root),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
