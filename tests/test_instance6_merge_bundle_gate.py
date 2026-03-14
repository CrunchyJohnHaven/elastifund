from __future__ import annotations

import json
from pathlib import Path

from scripts.run_instance6_merge_bundle_gate import GitState, build_instance6_merge_bundle_gate


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def _write_runtime_stack(
    root: Path,
    *,
    rollout_profile: str,
    runtime_profile: str,
    autoresearch_profile: str,
    maker_delta: float,
    maker_confidence: float,
    dual_delta: float,
    dual_confidence: float,
    instance05_outperform_status: str,
    instance05_queue_status: str,
    queue_status: str,
    instance06_canonical_present: bool,
    instance06_fallback_used: bool,
) -> None:
    _write_json(
        root / "reports" / "btc5_rollout_latest.json",
        {
            "remote_cycle_status_summary": {
                "btc5_selected_package": {
                    "selected_best_profile_name": rollout_profile,
                    "selected_policy_id": rollout_profile,
                }
            }
        },
    )
    _write_json(
        root / "reports" / "runtime_truth_latest.json",
        {
            "btc5_selected_package": {
                "selected_best_profile_name": runtime_profile,
                "selected_policy_id": runtime_profile,
            },
            "launch_packet": {
                "mandatory_outputs": {
                    "finance_gate_pass": True,
                }
            },
        },
    )
    _write_json(
        root / "reports" / "btc5_autoresearch" / "latest.json",
        {
            "active_runtime_package": {
                "profile": {
                    "name": autoresearch_profile,
                }
            }
        },
    )
    _write_json(
        root / "reports" / "autoresearch" / "maker_shadow" / "latest.json",
        {
            "candidate_delta_arr_bps": maker_delta,
            "expected_improvement_velocity_delta": 0.0,
            "arr_confidence_score": maker_confidence,
        },
    )
    _write_json(
        root / "reports" / "parallel" / "instance04_dual_sided_maker_lane.json",
        {
            "candidate_delta_arr_bps": dual_delta,
            "arr_confidence_score": dual_confidence,
        },
    )
    _write_json(
        root / "reports" / "parallel" / "instance04_outperform_maker_lane.json",
        {
            "candidate_delta_arr_bps": maker_delta,
            "arr_confidence_score": maker_confidence,
        },
    )
    _write_json(
        root / "reports" / "parallel" / "instance05_finance_mirror_lane_policy.json",
        {
            "finance_gate_pass": True,
            "baseline_policy": {
                "selected_live_profile": rollout_profile,
                "queue_state": {
                    "status": instance05_queue_status,
                },
            },
            "inputs": {
                "instance04_outperform_maker_lane": {
                    "status": instance05_outperform_status,
                }
            },
        },
    )
    _write_json(
        root / "reports" / "parallel" / "instance06_mirror_outperform_queue.json",
        {
            "dependency_status": {
                "instance04_outperform_maker_lane_present": instance06_canonical_present,
                "instance04_fallback_used": instance06_fallback_used,
            }
        },
    )
    _write_json(
        root / "reports" / "finance" / "action_queue.json",
        {
            "actions": [
                {
                    "action_key": "allocate::maintain_stage1_flat_size",
                    "status": queue_status,
                }
            ]
        },
    )


def test_instance6_merge_bundle_gate_blocks_on_truth_and_dependency_drift(tmp_path: Path) -> None:
    _write_runtime_stack(
        tmp_path,
        rollout_profile="active_profile_probe_d0_00075",
        runtime_profile="current_live_profile",
        autoresearch_profile="current_live_profile",
        maker_delta=0.0,
        maker_confidence=0.1,
        dual_delta=4300.0,
        dual_confidence=0.62,
        instance05_outperform_status="missing",
        instance05_queue_status="queued",
        queue_status="executed",
        instance06_canonical_present=False,
        instance06_fallback_used=True,
    )
    git_state = GitState(
        current_branch="codex/elastic-employee-narrative-sprint",
        base_ref="main",
        branch_diff_files=tuple(f"docs/noise_{idx}.md" for idx in range(41)),
        working_tree_files=("scripts/write_remote_cycle_status.py",),
        untracked_files=(
            "AutoregressionResearchPrompt.md",
            "scripts/remote_cycle_status_core.py",
            "scripts/render_instance2_directional_conversion_probe.py",
            "scripts/render_instance4_outperform_maker_lane.py",
            "scripts/run_btc5_dual_sided_maker_shadow.py",
            "scripts/run_instance6_rollout_finance_dispatch.py",
            "tests/test_remote_cycle_status_build_and_gates.py",
            "tests/test_render_instance2_directional_conversion_probe.py",
            "tests/test_render_instance4_outperform_maker_lane.py",
            "tests/test_run_btc5_dual_sided_maker_shadow.py",
            "tests/test_instance6_rollout_finance_dispatch.py",
        ),
    )

    payload = build_instance6_merge_bundle_gate(tmp_path, git_state=git_state)

    assert payload["merge_gate"]["ready_for_push"] is False
    assert payload["merge_gate"]["ready_for_deploy"] is False
    assert "branch_scope_too_broad_for_safe_push:41_tracked_files" in payload["block_reasons"]
    assert "policy_runtime_package_mismatch:active_profile_probe_d0_00075!=current_live_profile" in payload["block_reasons"]
    assert "autoresearch_active_package_drift:current_live_profile!=active_profile_probe_d0_00075" in payload["block_reasons"]
    assert "maker_dual_sided_contract_stale_vs_measured_shadow_truth" in payload["block_reasons"]
    assert "instance05_still_claims_instance04_missing" in payload["block_reasons"]
    assert "instance05_queue_state_stale:queued!=executed" in payload["block_reasons"]
    assert "instance06_dependency_status_still_missing_canonical_instance04" in payload["block_reasons"]
    assert "instance06_still_using_instance04_fallback" in payload["block_reasons"]
    assert "scripts/remote_cycle_status_core.py" in payload["bundle_scope"]["bundle_paths"]
    assert "docs/noise_0.md" not in payload["bundle_scope"]["bundle_paths"]
    assert payload["candidate_delta_arr_bps"] == 0.0


def test_instance6_merge_bundle_gate_turns_green_for_consistent_narrow_bundle(tmp_path: Path) -> None:
    _write_runtime_stack(
        tmp_path,
        rollout_profile="active_profile_probe_d0_00075",
        runtime_profile="active_profile_probe_d0_00075",
        autoresearch_profile="active_profile_probe_d0_00075",
        maker_delta=0.0,
        maker_confidence=0.1,
        dual_delta=0.0,
        dual_confidence=0.1,
        instance05_outperform_status="present",
        instance05_queue_status="executed",
        queue_status="executed",
        instance06_canonical_present=True,
        instance06_fallback_used=False,
    )
    git_state = GitState(
        current_branch="codex/instance6-narrow-bundle",
        base_ref="main",
        branch_diff_files=(
            "scripts/write_remote_cycle_status.py",
            "scripts/remote_cycle_status_core.py",
            "scripts/render_instance2_directional_conversion_probe.py",
            "scripts/render_instance4_outperform_maker_lane.py",
            "scripts/run_btc5_dual_sided_maker_shadow.py",
            "scripts/run_instance6_merge_bundle_gate.py",
            "tests/test_remote_cycle_status_build_and_gates.py",
            "tests/test_instance6_merge_bundle_gate.py",
        ),
        working_tree_files=(),
        untracked_files=(),
    )

    payload = build_instance6_merge_bundle_gate(tmp_path, git_state=git_state)

    assert payload["block_reasons"] == []
    assert payload["merge_gate"]["ready_for_push"] is True
    assert payload["merge_gate"]["ready_for_deploy"] is True
    assert payload["bundle_scope"]["bundle_file_count"] == 8
    assert payload["finance_gate_pass"] is True
