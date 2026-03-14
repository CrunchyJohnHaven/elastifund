from __future__ import annotations

import json
from pathlib import Path

from scripts.render_instance4_outperform_maker_lane import build_instance4_maker_artifacts, write_artifacts


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def _write_inputs(root: Path) -> None:
    _write_json(
        root / "reports" / "autoresearch" / "maker_shadow" / "latest.json",
        {
            "generated_at": "2026-03-12T14:46:24.746208+00:00",
            "bankroll_usd": 247.0,
            "combined_cost_cap": 0.97,
            "reserve_pct": 0.2,
            "candidate_delta_arr_bps": 0.0,
            "expected_improvement_velocity_delta": 0.0,
            "arr_confidence_score": 0.1,
            "finance_gate_pass": True,
            "ranked_candidate_count": 0,
            "block_reasons": [
                "no_shadow_candidates_with_combined_cost_edge",
                "combined_bid_cost_above_cap",
            ],
            "one_next_cycle_action": "wait_for_tighter_books_or_more_liquidity",
            "combined_cost_cap_sensitivity": [
                {
                    "combined_cost_cap": 0.97,
                    "ranked_candidate_count": 0,
                    "top_combined_cost": None,
                    "top_score": 0.0,
                    "one_next_cycle_action": "wait_for_tighter_books_or_more_liquidity",
                },
                {
                    "combined_cost_cap": 0.98,
                    "ranked_candidate_count": 0,
                    "top_combined_cost": None,
                    "top_score": 0.0,
                    "one_next_cycle_action": "wait_for_tighter_books_or_more_liquidity",
                },
                {
                    "combined_cost_cap": 0.99,
                    "ranked_candidate_count": 6,
                    "top_combined_cost": 0.99,
                    "top_score": 0.01728,
                    "one_next_cycle_action": "run_dual_sided_maker_shadow_loop",
                },
            ],
        },
    )
    _write_json(
        root / "reports" / "autoresearch" / "maker_shadow_cap099" / "latest.json",
        {
            "generated_at": "2026-03-12T14:43:52.814894+00:00",
            "combined_cost_cap": 0.99,
            "candidate_delta_arr_bps": 100.0,
            "expected_improvement_velocity_delta": 0.01728,
            "arr_confidence_score": 0.35,
            "ranked_candidate_count": 6,
            "one_next_cycle_action": "run_dual_sided_maker_shadow_loop",
        },
    )
    _write_json(
        root / "reports" / "parallel" / "instance03_mirror_wallet_roster.json",
        {
            "generated_at": "2026-03-12T15:42:04Z",
            "roster_views": {
                "maker_mechanics_priority": ["k9Q2mX4L8A7ZP3R", "vidarx", "gabagool22"],
                "overlay_only_references": ["distinct-baguette", "0x1979", "0x8dxd", "BoneReader"],
            },
            "wallets": [
                {
                    "label": "vidarx",
                    "address": "0x1",
                    "clone_priority": 1,
                    "recommended_use_mode": "inspired_shadow_blueprint",
                    "maker_vs_directional_confidence": {"maker_confidence": 0.8},
                },
                {
                    "label": "gabagool22",
                    "address": "0x2",
                    "clone_priority": 2,
                    "recommended_use_mode": "inspired_shadow_blueprint",
                    "maker_vs_directional_confidence": {"maker_confidence": 0.65},
                },
                {
                    "label": "k9Q2mX4L8A7ZP3R",
                    "address": "0x3",
                    "clone_priority": 3,
                    "recommended_use_mode": "inspired_shadow_blueprint",
                    "maker_vs_directional_confidence": {"maker_confidence": 0.82},
                },
                {
                    "label": "distinct-baguette",
                    "address": "0x4",
                    "clone_priority": 4,
                    "recommended_use_mode": "overlay_reference_only",
                    "maker_vs_directional_confidence": {"maker_confidence": 0.52},
                },
            ],
        },
    )
    _write_json(
        root / "reports" / "runtime_truth_latest.json",
        {
            "generated_at": "2026-03-12T15:33:54.293935+00:00",
            "execution_mode": "live",
            "allow_order_submission": True,
            "launch_posture": "clear",
            "finance_gate_pass": True,
            "btc5_stage_readiness": {"trade_now_status": "unblocked"},
        },
    )
    _write_json(
        root / "reports" / "parallel" / "instance02_directional_conversion_probe.json",
        {
            "generated_at": "2026-03-12T15:47:07.273098Z",
            "arr_confidence_score": 0.11,
        },
    )


def test_build_instance4_maker_artifacts_uses_measured_shadow_truth(tmp_path: Path) -> None:
    _write_inputs(tmp_path)

    dual_sided, outperform = build_instance4_maker_artifacts(tmp_path)

    assert dual_sided["candidate_delta_arr_bps"] == 0.0
    assert dual_sided["expected_improvement_velocity_delta"] == 0.0
    assert dual_sided["arr_confidence_score"] == 0.1
    assert dual_sided["measurement_snapshot"]["live_threshold"]["ranked_candidate_count"] == 0
    assert dual_sided["validation_ladder"]["0.99"]["current_ranked_candidate_count"] == 6
    assert "maker_cap_0_99_only_has_thin_sensitivity_candidates" in dual_sided["block_reasons"]

    assert outperform["candidate_delta_arr_bps"] == 0.0
    assert outperform["expected_improvement_velocity_delta"] == 0.0
    assert outperform["arr_confidence_score"] == 0.1
    assert outperform["reference_class_target"]["mirror_cohort_definition"]["blueprint_wallets"][0]["label"] == "vidarx"
    assert outperform["validation_ladder"]["0.97"]["current_ranked_candidate_count"] == 0
    assert outperform["outperformance_metrics"]["candidate_availability"]["current"]["cap_0_99"] == 6
    assert "fill_to_scratch_loss_ratio_unmeasured" in outperform["block_reasons"]


def test_write_artifacts_persists_both_canonical_outputs(tmp_path: Path) -> None:
    _write_inputs(tmp_path)

    dual_sided_output = tmp_path / "reports" / "parallel" / "instance04_dual_sided_maker_lane.json"
    outperform_output = tmp_path / "reports" / "parallel" / "instance04_outperform_maker_lane.json"
    write_artifacts(
        root=tmp_path,
        dual_sided_output=dual_sided_output,
        outperform_output=outperform_output,
    )

    dual_sided_payload = json.loads(dual_sided_output.read_text(encoding="utf-8"))
    outperform_payload = json.loads(outperform_output.read_text(encoding="utf-8"))

    assert dual_sided_payload["candidate_delta_arr_bps"] == 0.0
    assert outperform_payload["candidate_delta_arr_bps"] == 0.0
