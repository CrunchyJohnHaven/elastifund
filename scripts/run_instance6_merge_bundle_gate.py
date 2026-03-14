#!/usr/bin/env python3
"""Build the Instance 6 narrow merge-bundle gate artifact."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from fnmatch import fnmatch
import json
from pathlib import Path
import subprocess
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_PATH = REPO_ROOT / "reports" / "parallel" / "instance06_merge_bundle_gate.json"
SCOPE_BLOCKER_FILE_THRESHOLD = 40
TARGET_PATTERNS = (
    "AutoregressionResearchPrompt.md",
    "scripts/remote_cycle_*.py",
    "scripts/render_instance2_directional_conversion_probe.py",
    "scripts/render_instance4_outperform_maker_lane.py",
    "scripts/run_btc5_dual_sided_maker_shadow.py",
    "scripts/run_instance6_merge_bundle_gate.py",
    "scripts/run_instance6_rollout_finance_dispatch.py",
    "scripts/write_remote_cycle_status.py",
    "tests/_remote_cycle_status_*.py",
    "tests/test_instance6_merge_bundle_gate.py",
    "tests/test_instance6_rollout_finance_dispatch.py",
    "tests/test_remote_cycle_*.py",
    "tests/test_render_instance2_directional_conversion_probe.py",
    "tests/test_render_instance4_outperform_maker_lane.py",
    "tests/test_run_btc5_dual_sided_maker_shadow.py",
)
IGNORED_RUNTIME_ARTIFACTS = (
    "reports/btc5_autoresearch/latest.json",
    "reports/runtime_truth_latest.json",
    "reports/public_runtime_snapshot.json",
    "reports/parallel/instance02_directional_conversion_probe.json",
    "reports/parallel/instance03_mirror_wallet_roster.json",
    "reports/parallel/instance04_dual_sided_maker_lane.json",
    "reports/parallel/instance04_outperform_maker_lane.json",
    "reports/parallel/instance05_finance_mirror_lane_policy.json",
    "reports/parallel/instance06_mirror_outperform_queue.json",
    "reports/finance/action_queue.json",
)
TARGET_TESTS = (
    "tests/test_instance6_merge_bundle_gate.py",
    "tests/test_remote_cycle_status_build_and_gates.py",
    "tests/test_remote_cycle_status_finance.py",
    "tests/test_remote_cycle_status_io.py",
    "tests/test_remote_cycle_status_render_bridge.py",
    "tests/test_remote_cycle_status_write_metrics_and_snapshot.py",
    "tests/test_remote_cycle_status_write_runtime_contracts.py",
    "tests/test_render_instance2_directional_conversion_probe.py",
    "tests/test_run_btc5_dual_sided_maker_shadow.py",
    "tests/test_render_instance4_outperform_maker_lane.py",
    "tests/test_instance6_rollout_finance_dispatch.py",
)


@dataclass(frozen=True)
class GitState:
    current_branch: str
    base_ref: str
    branch_diff_files: tuple[str, ...]
    working_tree_files: tuple[str, ...]
    untracked_files: tuple[str, ...]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _read_json_dict(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _git_lines(root: Path, *args: str) -> list[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _git_scalar(root: Path, *args: str, default: str = "") -> str:
    rows = _git_lines(root, *args)
    return rows[0] if rows else default


def _detect_base_ref(root: Path) -> str:
    for candidate in ("main", "origin/main", "master", "origin/master"):
        result = subprocess.run(
            ["git", "rev-parse", "--verify", candidate],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return candidate
    return "HEAD"


def _gather_git_state(root: Path) -> GitState:
    base_ref = _detect_base_ref(root)
    current_branch = _git_scalar(root, "branch", "--show-current", default="detached")
    branch_diff_files = tuple(_git_lines(root, "diff", "--name-only", f"{base_ref}...HEAD"))
    working_tree_files = tuple(_git_lines(root, "diff", "--name-only"))
    untracked_files = tuple(_git_lines(root, "ls-files", "--others", "--exclude-standard"))
    return GitState(
        current_branch=current_branch,
        base_ref=base_ref,
        branch_diff_files=branch_diff_files,
        working_tree_files=working_tree_files,
        untracked_files=untracked_files,
    )


def _matches_target(path: str) -> bool:
    return any(fnmatch(path, pattern) for pattern in TARGET_PATTERNS)


def _ordered_unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        token = str(item).strip()
        if not token or token in seen:
            continue
        seen.add(token)
        ordered.append(token)
    return ordered


def _extract_nested(payload: dict[str, Any], *path: str) -> Any:
    node: Any = payload
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def _extract_selected_profile_name(payload: dict[str, Any]) -> str:
    candidates = (
        _extract_nested(payload, "remote_cycle_status_summary", "btc5_selected_package", "selected_best_profile_name"),
        _extract_nested(payload, "remote_cycle_status_summary", "btc5_selected_package", "selected_policy_id"),
        _extract_nested(payload, "btc5_selected_package", "selected_best_profile_name"),
        _extract_nested(payload, "btc5_selected_package", "selected_policy_id"),
        _extract_nested(payload, "baseline_policy", "selected_live_profile"),
    )
    for candidate in candidates:
        value = str(candidate or "").strip()
        if value:
            return value
    return ""


def _extract_active_runtime_profile(payload: dict[str, Any]) -> str:
    candidates = (
        _extract_nested(payload, "active_runtime_package", "profile", "name"),
        _extract_nested(payload, "active_profile", "name"),
        _extract_nested(payload, "current_champions", "policy", "policy_id"),
        _extract_nested(payload, "current_champions", "policy", "id"),
    )
    for candidate in candidates:
        value = str(candidate or "").strip()
        if value:
            return value
    return ""


def _queue_status(payload: dict[str, Any], action_key: str) -> str:
    actions = payload.get("actions")
    if not isinstance(actions, list):
        return ""
    for row in actions:
        if not isinstance(row, dict):
            continue
        if str(row.get("action_key") or "").strip() == action_key:
            return str(row.get("status") or "").strip()
    return ""


def _canonical_outperform_present(root: Path, payload: dict[str, Any]) -> bool:
    if payload:
        return True
    return (root / "reports" / "parallel" / "instance04_outperform_maker_lane.json").exists()


def _float_value(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _build_recommended_tests(bundle_paths: list[str], root: Path) -> list[str]:
    selected: list[str] = []
    for candidate in TARGET_TESTS:
        if (root / candidate).exists():
            selected.append(candidate)
    if any(path.startswith("tests/") for path in bundle_paths):
        for path in bundle_paths:
            if (
                path.startswith("tests/")
                and not Path(path).name.startswith("_")
                and (root / path).exists()
            ):
                selected.append(path)
    return _ordered_unique(selected)


def build_instance6_merge_bundle_gate(root: Path, *, git_state: GitState | None = None) -> dict[str, Any]:
    root = root.resolve()
    git_state = git_state or _gather_git_state(root)

    tracked_branch_files = list(git_state.branch_diff_files)
    working_tree_files = list(git_state.working_tree_files)
    untracked_files = list(git_state.untracked_files)
    all_changed_paths = _ordered_unique(tracked_branch_files + working_tree_files + untracked_files)
    bundle_paths = [path for path in all_changed_paths if _matches_target(path)]
    excluded_paths = [path for path in tracked_branch_files if not _matches_target(path)]

    btc5_autoresearch = _read_json_dict(root / "reports" / "btc5_autoresearch" / "latest.json")
    btc5_rollout = _read_json_dict(root / "reports" / "btc5_rollout_latest.json")
    runtime_truth = _read_json_dict(root / "reports" / "runtime_truth_latest.json")
    maker_shadow = _read_json_dict(root / "reports" / "autoresearch" / "maker_shadow" / "latest.json")
    maker_lane_dual = _read_json_dict(root / "reports" / "parallel" / "instance04_dual_sided_maker_lane.json")
    maker_lane_outperform = _read_json_dict(root / "reports" / "parallel" / "instance04_outperform_maker_lane.json")
    instance05 = _read_json_dict(root / "reports" / "parallel" / "instance05_finance_mirror_lane_policy.json")
    instance06 = _read_json_dict(root / "reports" / "parallel" / "instance06_mirror_outperform_queue.json")
    finance_queue = _read_json_dict(root / "reports" / "finance" / "action_queue.json")

    promoted_profile = _extract_selected_profile_name(btc5_rollout)
    runtime_profile = _extract_selected_profile_name(runtime_truth)
    active_profile = _extract_active_runtime_profile(btc5_autoresearch)
    instance05_profile = _extract_selected_profile_name(instance05)

    block_reasons: list[str] = []
    if len(tracked_branch_files) > SCOPE_BLOCKER_FILE_THRESHOLD:
        block_reasons.append(
            f"branch_scope_too_broad_for_safe_push:{len(tracked_branch_files)}_tracked_files"
        )
    if not bundle_paths:
        block_reasons.append("instance6_bundle_paths_missing")

    if promoted_profile and runtime_profile and promoted_profile != runtime_profile:
        block_reasons.append(
            f"policy_runtime_package_mismatch:{promoted_profile}!={runtime_profile}"
        )
    if promoted_profile and active_profile and promoted_profile != active_profile:
        block_reasons.append(
            f"autoresearch_active_package_drift:{active_profile}!={promoted_profile}"
        )
    if instance05_profile and runtime_profile and instance05_profile != runtime_profile:
        block_reasons.append(
            f"instance05_vs_runtime_selected_profile_mismatch:{instance05_profile}!={runtime_profile}"
        )

    measured_delta = _float_value(maker_shadow.get("candidate_delta_arr_bps"))
    measured_confidence = _float_value(maker_shadow.get("arr_confidence_score"))
    contract_delta = _float_value(maker_lane_dual.get("candidate_delta_arr_bps"))
    contract_confidence = _float_value(maker_lane_dual.get("arr_confidence_score"))
    if abs(contract_delta - measured_delta) > 1e-9 or abs(contract_confidence - measured_confidence) > 1e-9:
        block_reasons.append(
            "maker_dual_sided_contract_stale_vs_measured_shadow_truth"
        )

    canonical_outperform_present = _canonical_outperform_present(root, maker_lane_outperform)
    instance05_outperform_status = str(
        _extract_nested(instance05, "inputs", "instance04_outperform_maker_lane", "status") or ""
    ).strip()
    if canonical_outperform_present and instance05_outperform_status == "missing":
        block_reasons.append("instance05_still_claims_instance04_missing")

    queue_contract_status = str(
        _extract_nested(instance05, "baseline_policy", "queue_state", "status") or ""
    ).strip()
    actual_queue_status = _queue_status(finance_queue, "allocate::maintain_stage1_flat_size")
    if queue_contract_status and actual_queue_status and queue_contract_status != actual_queue_status:
        block_reasons.append(
            f"instance05_queue_state_stale:{queue_contract_status}!={actual_queue_status}"
        )

    dependency_canonical_present = bool(
        _extract_nested(instance06, "dependency_status", "instance04_outperform_maker_lane_present")
    )
    dependency_fallback_used = bool(
        _extract_nested(instance06, "dependency_status", "instance04_fallback_used")
    )
    if canonical_outperform_present and not dependency_canonical_present:
        block_reasons.append("instance06_dependency_status_still_missing_canonical_instance04")
    if canonical_outperform_present and dependency_fallback_used:
        block_reasons.append("instance06_still_using_instance04_fallback")

    finance_gate_pass = bool(
        instance05.get("finance_gate_pass")
        if instance05.get("finance_gate_pass") is not None
        else _extract_nested(runtime_truth, "launch_packet", "mandatory_outputs", "finance_gate_pass")
    )
    arr_confidence_score = min(
        measured_confidence if measured_confidence > 0.0 else 0.1,
        _float_value(maker_lane_outperform.get("arr_confidence_score"), 0.1) or 0.1,
    )
    candidate_delta_arr_bps = 0.0 if block_reasons else measured_delta
    expected_improvement_velocity_delta = (
        0.0 if block_reasons else _float_value(maker_shadow.get("expected_improvement_velocity_delta"))
    )
    one_next_cycle_action = (
        "Keep this branch unpushed and undeployed, regenerate runtime truth plus instance05/instance06 from canonical instance04 outputs, then transplant only the bundle paths onto a clean branch and rerun the targeted tests."
        if block_reasons
        else "Stage only the narrow bundle paths on a clean branch, rerun the targeted tests, and only then push and deploy."
    )

    payload = {
        "artifact": "instance06_merge_bundle_gate",
        "instance": 6,
        "instance_label": "GPT-5.3-Codex / Medium - narrow merge bundle and deploy gate",
        "generated_at": _utc_now().isoformat(),
        "merge_gate": {
            "current_branch": git_state.current_branch,
            "base_ref": git_state.base_ref,
            "tracked_branch_changed_file_count": len(tracked_branch_files),
            "working_tree_changed_file_count": len(working_tree_files),
            "untracked_file_count": len(untracked_files),
            "ready_for_push": not block_reasons,
            "ready_for_deploy": not block_reasons,
        },
        "bundle_scope": {
            "target_patterns": list(TARGET_PATTERNS),
            "bundle_paths": bundle_paths,
            "bundle_file_count": len(bundle_paths),
            "excluded_tracked_branch_paths_sample": excluded_paths[:25],
            "ignored_runtime_artifacts": list(IGNORED_RUNTIME_ARTIFACTS),
            "recommended_test_targets": _build_recommended_tests(bundle_paths, root),
        },
        "truth_snapshot": {
            "policy_promoted_profile": promoted_profile,
            "runtime_selected_profile": runtime_profile,
            "autoresearch_active_profile": active_profile,
            "instance05_selected_profile": instance05_profile,
            "maker_shadow_candidate_delta_arr_bps": measured_delta,
            "maker_shadow_arr_confidence_score": measured_confidence,
            "maker_dual_contract_candidate_delta_arr_bps": contract_delta,
            "maker_dual_contract_arr_confidence_score": contract_confidence,
            "instance05_outperform_status": instance05_outperform_status or None,
            "instance05_queue_contract_status": queue_contract_status or None,
            "finance_queue_actual_status": actual_queue_status or None,
            "instance06_canonical_dependency_present": dependency_canonical_present,
            "instance06_fallback_used": dependency_fallback_used,
        },
        "candidate_delta_arr_bps": candidate_delta_arr_bps,
        "expected_improvement_velocity_delta": expected_improvement_velocity_delta,
        "arr_confidence_score": round(arr_confidence_score, 4),
        "block_reasons": _ordered_unique(block_reasons),
        "finance_gate_pass": finance_gate_pass,
        "one_next_cycle_action": one_next_cycle_action,
        "required_outputs": {
            "candidate_delta_arr_bps": candidate_delta_arr_bps,
            "expected_improvement_velocity_delta": expected_improvement_velocity_delta,
            "arr_confidence_score": round(arr_confidence_score, 4),
            "block_reasons": _ordered_unique(block_reasons),
            "finance_gate_pass": finance_gate_pass,
            "one_next_cycle_action": one_next_cycle_action,
        },
    }
    return payload


def write_instance6_merge_bundle_gate(root: Path, output_path: Path | None = None) -> tuple[Path, Path]:
    root = root.resolve()
    payload = build_instance6_merge_bundle_gate(root)
    timestamp = _utc_now().strftime("%Y%m%dT%H%M%SZ")
    latest_path = output_path.resolve() if output_path is not None else DEFAULT_OUTPUT_PATH.resolve()
    timestamped_path = latest_path.with_name(f"instance06_merge_bundle_gate_{timestamp}.json")
    _write_json(timestamped_path, payload)
    _write_json(latest_path, payload)
    return timestamped_path, latest_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the Instance 6 narrow merge bundle gate artifact.")
    parser.add_argument("--root", default=".", help="Repository root (default: current directory).")
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_PATH),
        help="Latest artifact output path.",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    output = Path(args.output).resolve()
    timestamped_path, latest_path = write_instance6_merge_bundle_gate(root, output)
    print(
        json.dumps(
            {
                "instance06_merge_bundle_gate": str(latest_path),
                "instance06_merge_bundle_gate_timestamped": str(timestamped_path),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
