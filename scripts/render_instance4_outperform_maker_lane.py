#!/usr/bin/env python3
"""Render the canonical maker-lane contracts from measured shadow truth."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_MAKER_SHADOW_PATH = REPO_ROOT / "reports" / "autoresearch" / "maker_shadow" / "latest.json"
DEFAULT_MAKER_SHADOW_CAP099_PATH = REPO_ROOT / "reports" / "autoresearch" / "maker_shadow_cap099" / "latest.json"
DEFAULT_MIRROR_WALLET_ROSTER_PATH = REPO_ROOT / "reports" / "parallel" / "instance03_mirror_wallet_roster.json"
DEFAULT_RUNTIME_TRUTH_PATH = REPO_ROOT / "reports" / "runtime_truth_latest.json"
DEFAULT_DIRECTIONAL_PROBE_PATH = REPO_ROOT / "reports" / "parallel" / "instance02_directional_conversion_probe.json"
DEFAULT_DUAL_SIDED_OUTPUT = REPO_ROOT / "reports" / "parallel" / "instance04_dual_sided_maker_lane.json"
DEFAULT_OUTPERFORM_OUTPUT = REPO_ROOT / "reports" / "parallel" / "instance04_outperform_maker_lane.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


def _repo_rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _find_cap_row(rows: list[dict[str, Any]], cap: float) -> dict[str, Any]:
    target = round(float(cap), 2)
    for row in rows:
        if round(_as_float(row.get("combined_cost_cap")), 2) == target:
            return row
    return {}


def _wallet_label(wallet: dict[str, Any]) -> str:
    return str(wallet.get("label") or wallet.get("address") or "").strip()


def _build_wallet_sections(roster: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    wallets = roster.get("wallets")
    wallet_rows = wallets if isinstance(wallets, list) else []
    ranked_wallets = sorted(
        [row for row in wallet_rows if isinstance(row, dict)],
        key=lambda row: (_as_int(row.get("clone_priority"), 999), _wallet_label(row)),
    )

    blueprint_wallets = []
    overlay_only_wallets = []
    for row in ranked_wallets:
        label = _wallet_label(row)
        mode = str(row.get("recommended_use_mode") or "")
        if mode == "inspired_shadow_blueprint":
            maker_confidence = _as_float(
                ((row.get("maker_vs_directional_confidence") or {}).get("maker_confidence")),
                0.0,
            )
            blueprint_wallets.append(
                {
                    "label": label,
                    "address": row.get("address"),
                    "maker_confidence": round(maker_confidence, 4),
                    "wallet_copy_mode": "blueprint_for_shadow_design",
                }
            )
        elif label:
            overlay_only_wallets.append(label)

    maker_priority = roster.get("roster_views", {}).get("maker_mechanics_priority")
    reference_wallets = maker_priority if isinstance(maker_priority, list) and maker_priority else [
        row["label"] for row in blueprint_wallets[:3]
    ]
    overlay_view = roster.get("roster_views", {}).get("overlay_only_references")
    if isinstance(overlay_view, list) and overlay_view:
        overlay_only_wallets = [str(item) for item in overlay_view]
    return blueprint_wallets, overlay_only_wallets, [str(item) for item in reference_wallets if str(item).strip()]


def _build_validation_ladder(maker_shadow: dict[str, Any], maker_shadow_cap099: dict[str, Any]) -> dict[str, Any]:
    sensitivity_rows = maker_shadow.get("combined_cost_cap_sensitivity")
    rows = sensitivity_rows if isinstance(sensitivity_rows, list) else []
    row_097 = _find_cap_row(rows, 0.97)
    row_098 = _find_cap_row(rows, 0.98)
    row_099 = _find_cap_row(rows, 0.99)
    if not row_099:
        row_099 = {
            "combined_cost_cap": 0.99,
            "ranked_candidate_count": maker_shadow_cap099.get("ranked_candidate_count"),
            "top_combined_cost": (
                (maker_shadow_cap099.get("ranked_candidates") or [{}])[0].get("combined_cost")
                if maker_shadow_cap099.get("ranked_candidates")
                else None
            ),
            "top_score": (
                (maker_shadow_cap099.get("ranked_candidates") or [{}])[0].get("score")
                if maker_shadow_cap099.get("ranked_candidates")
                else 0.0
            ),
            "one_next_cycle_action": maker_shadow_cap099.get("one_next_cycle_action"),
        }

    cap099_top_score = _as_float(row_099.get("top_score"))
    cap099_arr_delta_bps = _as_float(maker_shadow_cap099.get("candidate_delta_arr_bps"))
    cap099_note = (
        "Used for fill-realism and scratch-loss sensitivity only; "
        f"current thin gross edge is {cap099_arr_delta_bps:g} bps with top score {cap099_top_score:.5f}."
    )
    return {
        "0.97": {
            "designation": "conservative_validated_threshold",
            "current_ranked_candidate_count": _as_int(row_097.get("ranked_candidate_count")),
            "decision": "validation_target_not_yet_green",
            "live_policy": "shadow_only",
            "promotion_requirements": [
                "At least 3 consecutive cycles with ranked_candidate_count > 0 under 0.97.",
                "Fill-to-scratch loss ratio <= 0.45 on the matched shadow sample.",
                "Toxicity-adjusted expected value > 0.0 after costs.",
                "Improvement-per-dollar is positive versus the mirror cohort baseline.",
            ],
        },
        "0.98": {
            "designation": "observe_only",
            "current_ranked_candidate_count": _as_int(row_098.get("ranked_candidate_count")),
            "decision": "monitor_for_regime_shift",
            "live_policy": "never_live_without_0_97_green",
            "notes": "Used to detect tightening books before they appear at 0.97.",
        },
        "0.99": {
            "designation": "sensitivity_only",
            "current_ranked_candidate_count": _as_int(row_099.get("ranked_candidate_count")),
            "decision": "execute_shadow_measurement_only",
            "live_policy": "forbidden_this_cycle",
            "notes": cap099_note,
        },
    }


def _build_required_outputs(maker_shadow: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_delta_arr_bps": _as_float(maker_shadow.get("candidate_delta_arr_bps")),
        "expected_improvement_velocity_delta": _as_float(maker_shadow.get("expected_improvement_velocity_delta")),
        "arr_confidence_score": _as_float(maker_shadow.get("arr_confidence_score")),
        "finance_gate_pass": bool(maker_shadow.get("finance_gate_pass")),
    }


def _build_block_reasons(maker_shadow: dict[str, Any], maker_shadow_cap099: dict[str, Any]) -> list[str]:
    reasons = [
        "maker_cap_0_97_has_zero_candidates",
        "maker_cap_0_98_has_zero_candidates",
        "fill_to_scratch_loss_ratio_unmeasured",
        "toxicity_adjusted_ev_unmeasured",
        "improvement_per_dollar_unmeasured",
        "maker_lane_shadow_only_until_validation_green",
    ]
    if _as_int(maker_shadow_cap099.get("ranked_candidate_count")) > 0:
        reasons.append("maker_cap_0_99_only_has_thin_sensitivity_candidates")
    for reason in maker_shadow.get("block_reasons") or []:
        label = str(reason)
        if label not in reasons:
            reasons.append(label)
    return reasons


def _build_common_inputs(root: Path) -> dict[str, Any]:
    maker_shadow = _read_json_dict(DEFAULT_MAKER_SHADOW_PATH if root == REPO_ROOT else root / "reports" / "autoresearch" / "maker_shadow" / "latest.json")
    maker_shadow_cap099 = _read_json_dict(
        DEFAULT_MAKER_SHADOW_CAP099_PATH if root == REPO_ROOT else root / "reports" / "autoresearch" / "maker_shadow_cap099" / "latest.json"
    )
    mirror_wallet_roster = _read_json_dict(
        DEFAULT_MIRROR_WALLET_ROSTER_PATH if root == REPO_ROOT else root / "reports" / "parallel" / "instance03_mirror_wallet_roster.json"
    )
    runtime_truth = _read_json_dict(DEFAULT_RUNTIME_TRUTH_PATH if root == REPO_ROOT else root / "reports" / "runtime_truth_latest.json")
    directional_probe = _read_json_dict(
        DEFAULT_DIRECTIONAL_PROBE_PATH if root == REPO_ROOT else root / "reports" / "parallel" / "instance02_directional_conversion_probe.json"
    )
    return {
        "maker_shadow": maker_shadow,
        "maker_shadow_cap099": maker_shadow_cap099,
        "mirror_wallet_roster": mirror_wallet_roster,
        "runtime_truth": runtime_truth,
        "directional_probe": directional_probe,
    }


def build_instance4_maker_artifacts(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    inputs = _build_common_inputs(root)
    maker_shadow = inputs["maker_shadow"]
    maker_shadow_cap099 = inputs["maker_shadow_cap099"]
    mirror_wallet_roster = inputs["mirror_wallet_roster"]
    runtime_truth = inputs["runtime_truth"]
    directional_probe = inputs["directional_probe"]
    required = _build_required_outputs(maker_shadow)
    validation_ladder = _build_validation_ladder(maker_shadow, maker_shadow_cap099)
    block_reasons = _build_block_reasons(maker_shadow, maker_shadow_cap099)
    blueprint_wallets, overlay_only_wallets, reference_wallets = _build_wallet_sections(mirror_wallet_roster)

    generated_at = _utc_now()
    source_paths = {
        "maker_shadow_latest": _repo_rel(root / "reports" / "autoresearch" / "maker_shadow" / "latest.json", root),
        "maker_shadow_cap099_latest": _repo_rel(root / "reports" / "autoresearch" / "maker_shadow_cap099" / "latest.json", root),
        "mirror_wallet_roster": _repo_rel(root / "reports" / "parallel" / "instance03_mirror_wallet_roster.json", root),
        "runtime_truth_latest": _repo_rel(root / "reports" / "runtime_truth_latest.json", root),
        "directional_conversion_probe": _repo_rel(root / "reports" / "parallel" / "instance02_directional_conversion_probe.json", root),
        "research_prompt": "AutoregressionResearchPrompt.md",
        "backlog": "research/edge_backlog_ranked.md",
        "maker_contracts": "bot/maker_velocity_blitz.py",
        "maker_cli": "scripts/maker_velocity_blitz.py",
        "maker_shadow_runner": "scripts/run_btc5_dual_sided_maker_shadow.py",
    }
    measurement_snapshot = {
        "live_threshold": {
            "combined_cost_cap": _as_float(maker_shadow.get("combined_cost_cap"), 0.97),
            "ranked_candidate_count": _as_int(maker_shadow.get("ranked_candidate_count")),
            "candidate_delta_arr_bps": required["candidate_delta_arr_bps"],
            "expected_improvement_velocity_delta": required["expected_improvement_velocity_delta"],
            "arr_confidence_score": required["arr_confidence_score"],
            "block_reasons": list(maker_shadow.get("block_reasons") or []),
            "one_next_cycle_action": maker_shadow.get("one_next_cycle_action"),
        },
        "cap_0_99_sensitivity": {
            "combined_cost_cap": _as_float(maker_shadow_cap099.get("combined_cost_cap"), 0.99),
            "ranked_candidate_count": _as_int(maker_shadow_cap099.get("ranked_candidate_count")),
            "candidate_delta_arr_bps": _as_float(maker_shadow_cap099.get("candidate_delta_arr_bps")),
            "expected_improvement_velocity_delta": _as_float(maker_shadow_cap099.get("expected_improvement_velocity_delta")),
            "arr_confidence_score": _as_float(maker_shadow_cap099.get("arr_confidence_score")),
            "one_next_cycle_action": maker_shadow_cap099.get("one_next_cycle_action"),
        },
    }

    runtime_snapshot = {
        "launch_posture": runtime_truth.get("launch_posture") or (runtime_truth.get("summary") or {}).get("launch_posture"),
        "execution_mode": runtime_truth.get("execution_mode"),
        "allow_order_submission": runtime_truth.get("allow_order_submission"),
        "finance_gate_pass": runtime_truth.get("finance_gate_pass", required["finance_gate_pass"]),
        "btc5_trade_now_status": (
            runtime_truth.get("btc5_trade_now_status")
            or ((runtime_truth.get("btc5_stage_readiness") or {}).get("trade_now_status"))
        ),
    }

    dual_sided_payload = {
        "artifact": "instance04_dual_sided_maker_lane",
        "instance": 4,
        "instance_label": "Claude Code / Sonnet - maker contract refresh from measured shadow truth",
        "generated_at": generated_at,
        "schema_version": "1.1",
        "dispatch_objective": "Refresh the maker-lane canonical contract from measured BTC5 maker-shadow truth and keep live readiness bound to the conservative threshold.",
        "strategy_family": "dual_sided_maker_spread_capture",
        "rationale": {
            "primary_fast_market_thesis": "maker_first",
            "reference_wallets": reference_wallets,
            "directional_copying_role": "confirmation_overlay_only",
            "why_now": [
                "Measured maker-shadow truth now exists for the BTC5 dual-sided lane.",
                "The conservative 0.97 live threshold currently has zero candidates, so the contract must remain shadow-only.",
                "The cap ladder shows only thin 0.99 sensitivity candidates until fill-to-scratch validation exists.",
            ],
        },
        "lane_contract": {
            "market_universe": "BTC 5-minute Polymarket up/down markets only",
            "execution_mode": "maker_only_post_only_shadow",
            "inventory_style": "dual_sided_yes_no",
            "combined_cost_cap": 0.97,
            "timeout_seconds": 120,
            "wallet_confirmation_mode": "overlay_only",
            "taker_momentum_mode": "disabled",
            "capital_policy": {
                "bankroll_reference_usd": _as_float(maker_shadow.get("bankroll_usd"), 247.0),
                "per_market_total_notional_usd": [5.0, 10.0],
                "max_concurrent_markets": 8,
                "cash_reserve_pct": _as_float(maker_shadow.get("reserve_pct"), 0.2),
                "live_capital_status": "shadow_only_until_validation_surface_exists",
            },
            "risk_controls": [
                "Do not cross the spread.",
                "Scratch or cancel unmatched hedges after timeout.",
                "Keep wallet-flow directional input as a confirmation overlay only.",
                "Do not deploy live capital until fill/toxicity/queue evidence is positive.",
            ],
        },
        "repo_surfaces": {
            "contracts": [
                "bot/maker_velocity_blitz.py",
                "scripts/maker_velocity_blitz.py",
            ],
            "fill_model": [
                "src/maker_fill_model.py",
            ],
            "execution": [
                "bot/polymarket_clob.py",
                "bot/btc_5min_maker_core.py",
            ],
        },
        "required_validation_surface": [
            "maker fill probability by queue/toxicity regime",
            "paired YES/NO combined-cost distribution",
            "cancel_before_fill rate",
            "scratch-loss distribution",
            "maker rebate and fee contribution",
            "shadow pnl per market and per day",
        ],
        "measurement_snapshot": measurement_snapshot,
        "validation_ladder": validation_ladder,
        "candidate_delta_arr_bps": required["candidate_delta_arr_bps"],
        "expected_improvement_velocity_delta": required["expected_improvement_velocity_delta"],
        "arr_confidence_score": required["arr_confidence_score"],
        "block_reasons": block_reasons,
        "finance_gate_pass": required["finance_gate_pass"],
        "one_next_cycle_action": (
            "Run the 0.97/0.98/0.99 maker cap ladder again on the next window, publish fill-to-scratch and "
            "toxicity-adjusted EV measurements, and keep maker deployment shadow-only until 0.97 turns green."
        ),
        "source_evidence": source_paths,
    }

    outperform_payload = {
        "artifact": "instance04_outperform_maker_lane",
        "instance": 4,
        "instance_label": "Claude Code / Sonnet - maker-first mirror outperformance validation lane",
        "generated_at": generated_at,
        "schema_version": "1.1",
        "dispatch_objective": "Refresh the canonical maker-first validation lane so it tracks measured shadow truth instead of optimistic placeholders.",
        "goal_statement": "outperform_mirror_wallet_strategy_family_not_copy_trades",
        "inputs": {
            "maker_shadow_latest": {
                "path": source_paths["maker_shadow_latest"],
                "generated_at": maker_shadow.get("generated_at"),
                "ranked_candidate_count": maker_shadow.get("ranked_candidate_count"),
            },
            "maker_shadow_cap099_latest": {
                "path": source_paths["maker_shadow_cap099_latest"],
                "generated_at": maker_shadow_cap099.get("generated_at"),
                "ranked_candidate_count": maker_shadow_cap099.get("ranked_candidate_count"),
            },
            "mirror_wallet_roster": {
                "path": source_paths["mirror_wallet_roster"],
                "generated_at": mirror_wallet_roster.get("generated_at"),
            },
            "runtime_truth_latest": {
                "path": source_paths["runtime_truth_latest"],
                "generated_at": runtime_truth.get("generated_at"),
                **runtime_snapshot,
            },
            "directional_conversion_probe": {
                "path": source_paths["directional_conversion_probe"],
                "generated_at": directional_probe.get("generated_at"),
                "arr_confidence_score": directional_probe.get("arr_confidence_score"),
            },
            "maker_code_surfaces": [
                "bot/maker_velocity_blitz.py",
                "src/maker_fill_model.py",
                "bot/polymarket_clob.py",
            ],
        },
        "reference_class_target": {
            "strategy_family": "dual_sided_maker_spread_capture",
            "target_mechanics": [
                "dual-sided maker inventory management",
                "queue-aware spread capture",
                "strict timeout and scratch discipline",
                "wallet overlay only as confirmation",
            ],
            "mirror_cohort_definition": {
                "blueprint_wallets": blueprint_wallets,
                "overlay_only_wallets": overlay_only_wallets,
                "wallet_usage_policy": [
                    "Wallet flow never directly triggers live orders.",
                    "Wallet overlays cannot override book-quality or risk guardrails.",
                    "Reference wallets are used to design and evaluate mechanics, not copy fills.",
                ],
            },
        },
        "validation_ladder": validation_ladder,
        "outperformance_metrics": {
            "candidate_availability": {
                "definition": "ranked_candidate_count at threshold per cycle",
                "current": {
                    "cap_0_97": validation_ladder["0.97"]["current_ranked_candidate_count"],
                    "cap_0_98": validation_ladder["0.98"]["current_ranked_candidate_count"],
                    "cap_0_99": validation_ladder["0.99"]["current_ranked_candidate_count"],
                },
                "target_for_live_consideration": {
                    "cap_0_97_min_candidates_per_cycle": 2,
                    "consecutive_cycles_required": 3,
                },
            },
            "fill_to_scratch_loss_ratio": {
                "definition": "scratch_loss_usd / gross_maker_fill_edge_usd",
                "current_value": None,
                "target_max": 0.45,
                "status": "unmeasured_requires_shadow_fill_capture",
            },
            "toxicity_adjusted_expected_value": {
                "definition": "(locked_edge * fill_probability * (1 - toxicity)) - scratch_loss_rate",
                "unit": "usd_per_100_notional",
                "current_value": None,
                "target_min": 0.05,
                "status": "unmeasured_requires_fill_model_and_shadow_pnl",
            },
            "improvement_per_dollar": {
                "definition": "(strategy_ev_usd - mirror_cohort_reference_ev_usd) / shadow_operating_cost_usd",
                "unit": "ev_usd_per_usd_spent",
                "current_value": None,
                "target_min": 0.1,
                "status": "unmeasured_requires_mirror_cohort_baseline",
            },
        },
        "execution_contract": {
            "mode": "shadow_only",
            "inventory_style": "dual_sided_yes_no",
            "post_only_required": True,
            "timeout_seconds": 120,
            "max_inventory_skew_usd": "per_side_notional_usd",
            "wallet_confirmation_mode": "overlay_only",
            "repo_entrypoints": [
                "jq '.registry' reports/market_registry/latest.json > reports/parallel/instance04_market_snapshots.json",
                "python scripts/maker_velocity_blitz.py build-dual-sided-shadow-plan --markets-json reports/parallel/instance04_market_snapshots.json --bankroll-usd 247 --combined-cost-cap 0.97 --output reports/parallel/instance04_shadow_plan_cap097.json",
                "python scripts/maker_velocity_blitz.py build-dual-sided-shadow-plan --markets-json reports/parallel/instance04_market_snapshots.json --bankroll-usd 247 --combined-cost-cap 0.98 --output reports/parallel/instance04_shadow_plan_cap098.json",
                "python scripts/maker_velocity_blitz.py build-dual-sided-shadow-plan --markets-json reports/parallel/instance04_market_snapshots.json --bankroll-usd 247 --combined-cost-cap 0.99 --output reports/parallel/instance04_shadow_plan_cap099.json",
            ],
            "hard_bounds": [
                "No live maker capital this cycle.",
                "No wallet-only trigger path.",
                "No threshold widening into live without 0.97 validation and finance re-approval.",
            ],
        },
        "decision_status": {
            "lane_decision_complete": True,
            "bounded_program": True,
            "copy_trading_disallowed": True,
            "next_live_change_allowed_now": False,
        },
        "measured_shadow_truth": measurement_snapshot,
        "candidate_delta_arr_bps": required["candidate_delta_arr_bps"],
        "expected_improvement_velocity_delta": required["expected_improvement_velocity_delta"],
        "arr_confidence_score": required["arr_confidence_score"],
        "block_reasons": block_reasons,
        "finance_gate_pass": required["finance_gate_pass"],
        "one_next_cycle_action": (
            "Run the 0.97/0.98/0.99 cap ladder for the next measurement window, publish fill-to-scratch, "
            "toxicity-adjusted EV, and improvement-per-dollar versus the mirror cohort baseline, and keep maker "
            "deployment shadow-only until 0.97 shows consecutive non-zero candidates."
        ),
    }

    return dual_sided_payload, outperform_payload


def write_artifacts(root: Path, dual_sided_output: Path, outperform_output: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    dual_sided_payload, outperform_payload = build_instance4_maker_artifacts(root)
    _write_json(dual_sided_output, dual_sided_payload)
    _write_json(outperform_output, outperform_payload)
    return dual_sided_payload, outperform_payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write canonical maker-lane artifacts from measured shadow truth.")
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="Repository root path.")
    parser.add_argument("--dual-sided-output", type=Path, default=DEFAULT_DUAL_SIDED_OUTPUT)
    parser.add_argument("--outperform-output", type=Path, default=DEFAULT_OUTPERFORM_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    dual_sided_output = args.dual_sided_output.resolve()
    outperform_output = args.outperform_output.resolve()
    dual_sided_payload, outperform_payload = write_artifacts(
        root=root,
        dual_sided_output=dual_sided_output,
        outperform_output=outperform_output,
    )
    print(
        json.dumps(
            {
                "dual_sided_output": _repo_rel(dual_sided_output, root),
                "dual_sided_candidate_delta_arr_bps": dual_sided_payload["candidate_delta_arr_bps"],
                "outperform_output": _repo_rel(outperform_output, root),
                "outperform_candidate_delta_arr_bps": outperform_payload["candidate_delta_arr_bps"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
