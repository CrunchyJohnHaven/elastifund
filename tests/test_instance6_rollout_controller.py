"""Tests for scripts/instance6_rollout_controller.py."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.instance6_rollout_controller import (
    STAGE_SHADOW_REPLAY,
    STAGE_SHADOW_LIVE_INTENTS,
    STAGE_SINGLE_FOLLOWER_MICRO,
    STAGE_TWO_ASSET_BASKET,
    STAGE_FOUR_ASSET_BASKET,
    SINGLE_ACTION_CAP_USD,
    MONTHLY_NEW_COMMITMENT_CAP_USD,
    ARTIFACT_PATHS,
    FALLBACK_PATHS,
    FOLLOWER_ASSETS,
    ArtifactStatus,
    FinanceGateResult,
    RolloutState,
    apply_transition,
    check_btc5_baseline,
    build_repair_branches,
    evaluate_stage_transition,
    run_finance_gate,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_artifact(
    name: str,
    *,
    exists: bool = True,
    stale: bool = False,
    data: dict | None = None,
    age_seconds: float = 10.0,
) -> ArtifactStatus:
    blocker: str | None = None
    if not exists:
        blocker = f"{name} artifact missing"
    elif stale:
        blocker = f"{name} is stale"
    return ArtifactStatus(
        name=name,
        path=f"reports/{name}/latest.json",
        exists=exists,
        age_seconds=age_seconds if exists else None,
        stale=stale,
        blocker=blocker,
        data=data or {},
    )


def _fresh_artifacts(**overrides) -> dict[str, ArtifactStatus]:
    """Build a full set of fresh, non-blocking artifacts."""
    base = {
        "data_plane_health": _make_artifact("data_plane_health", data={"healthy": True}),
        "market_registry": _make_artifact("market_registry", data={"markets": []}),
        "cross_asset_cascade": _make_artifact(
            "cross_asset_cascade",
            data={
                "trigger_score": 0.72,
                "shadow_intended_notional_usd": 5.0,
                "correlation_collapse": False,
                "followers": {
                    "ETH": {"win_rate": 0.62, "candle_sets": 60, "post_cost_ev": 0.003, "auto_killed": False},
                    "SOL": {"win_rate": 0.58, "candle_sets": 55, "post_cost_ev": 0.002, "auto_killed": False},
                    "XRP": {"win_rate": 0.56, "candle_sets": 51, "post_cost_ev": 0.001, "auto_killed": False},
                    "DOGE": {"win_rate": 0.57, "candle_sets": 52, "post_cost_ev": 0.0015, "auto_killed": False},
                },
            },
        ),
        "cross_asset_mc": _make_artifact(
            "cross_asset_mc", data={"tail_breach": False, "drawdown_stress_breach": False}
        ),
        "remote_cycle_status": _make_artifact(
            "remote_cycle_status",
            data={"btc5_service_running": True},
        ),
        "wallet_reconciliation": _make_artifact(
            "wallet_reconciliation",
            data={
                "snapshot_precision": 0.995,
                "classification_precision": 0.98,
                "phantom_local_open_trade_ids": [],
            },
        ),
        "btc5_rollout_latest": _make_artifact(
            "btc5_rollout_latest", data={"deploy_mode": "shadow_probe", "service_running": True}
        ),
        "vendor_stack": _make_artifact("vendor_stack", data={"recommended_vendor": {"monthly_usd": 0}}),
        "finance_latest": _make_artifact(
            "finance_latest",
            data={
                "autonomy_mode": "live_spend",
                "monthly_new_committed_usd": 0.0,
                "monthly_new_commitment_cap_usd": MONTHLY_NEW_COMMITMENT_CAP_USD,
                "single_action_cap_usd": SINGLE_ACTION_CAP_USD,
                "reserve_floor_ok": True,
                "cash_reserve_months": 3.0,
                "min_cash_reserve_months": 1.0,
            },
        ),
        "finance_action_queue": _make_artifact("finance_action_queue", data={"actions": []}),
        "instance1_artifact": _make_artifact(
            "instance1_artifact", data={"arr_confidence_score": 0.75, "expected_improvement_velocity_delta": 0.1}
        ),
        "instance2_artifact": _make_artifact(
            "instance2_artifact",
            data={"finance_gate_pass": True, "arr_confidence_score": 0.70, "expected_improvement_velocity_delta": 0.05},
        ),
        "instance3_artifact": _make_artifact(
            "instance3_artifact", data={"arr_confidence_score": 0.65, "expected_improvement_velocity_delta": 0.02}
        ),
        "instance4_artifact": _make_artifact(
            "instance4_artifact", data={"arr_confidence_score": 0.72, "expected_improvement_velocity_delta": 0.08}
        ),
        "instance5_artifact": _make_artifact(
            "instance5_artifact", data={"arr_confidence_score": 0.68, "expected_improvement_velocity_delta": 0.06}
        ),
    }
    base.update(overrides)
    return base


def _passing_finance() -> FinanceGateResult:
    return FinanceGateResult(
        passed=True,
        block_reasons=[],
        monthly_committed_usd=0.0,
        single_action_remaining_usd=SINGLE_ACTION_CAP_USD,
        reserve_floor_ok=True,
        autonomy_mode="live_spend",
    )


def _blocking_finance(reason: str = "finance_test_block") -> FinanceGateResult:
    return FinanceGateResult(
        passed=False,
        block_reasons=[reason],
        monthly_committed_usd=0.0,
        single_action_remaining_usd=SINGLE_ACTION_CAP_USD,
        reserve_floor_ok=True,
        autonomy_mode="shadow",
    )


def test_check_btc5_baseline_prefers_instance2_baseline_contract() -> None:
    artifacts = _fresh_artifacts(
        instance2_artifact=_make_artifact(
            "instance2_artifact",
            data={
                "baseline_contract": {
                    "baseline_status": "baseline_live_ok",
                    "finance_gate_pass": True,
                }
            },
        ),
        remote_cycle_status=_make_artifact("remote_cycle_status", data={"btc5_service_running": False}),
        btc5_rollout_latest=_make_artifact(
            "btc5_rollout_latest",
            data={"deploy_mode": "shadow_probe", "service_running": False},
        ),
    )

    status, healthy = check_btc5_baseline(artifacts)

    assert status == "btc5_running"
    assert healthy is True


# ── Finance gate tests ─────────────────────────────────────────────────────────

class TestRunFinanceGate:
    def test_passes_when_all_caps_ok(self) -> None:
        arts = _fresh_artifacts()
        result = run_finance_gate(arts, proposed_action_usd=10.0, vendor_monthly_usd=0.0)
        assert result.passed

    def test_blocks_on_shadow_mode_with_spend(self) -> None:
        arts = _fresh_artifacts(
            finance_latest=_make_artifact(
                "finance_latest",
                data={
                    "autonomy_mode": "shadow",
                    "monthly_new_committed_usd": 0.0,
                    "monthly_new_commitment_cap_usd": MONTHLY_NEW_COMMITMENT_CAP_USD,
                    "single_action_cap_usd": SINGLE_ACTION_CAP_USD,
                    "reserve_floor_ok": True,
                    "cash_reserve_months": 3.0,
                    "min_cash_reserve_months": 1.0,
                },
            )
        )
        result = run_finance_gate(arts, proposed_action_usd=5.0)
        assert not result.passed
        assert any("shadow" in b for b in result.block_reasons)

    def test_blocks_when_single_action_exceeds_cap(self) -> None:
        arts = _fresh_artifacts()
        result = run_finance_gate(arts, proposed_action_usd=SINGLE_ACTION_CAP_USD + 1.0)
        assert not result.passed
        assert any("single_action_cap" in b for b in result.block_reasons)

    def test_blocks_when_monthly_cap_exceeded(self) -> None:
        arts = _fresh_artifacts(
            finance_latest=_make_artifact(
                "finance_latest",
                data={
                    "autonomy_mode": "live_spend",
                    "monthly_new_committed_usd": 990.0,
                    "monthly_new_commitment_cap_usd": MONTHLY_NEW_COMMITMENT_CAP_USD,
                    "single_action_cap_usd": SINGLE_ACTION_CAP_USD,
                    "reserve_floor_ok": True,
                    "cash_reserve_months": 3.0,
                    "min_cash_reserve_months": 1.0,
                },
            )
        )
        result = run_finance_gate(arts, proposed_action_usd=0.0, vendor_monthly_usd=50.0)
        assert not result.passed
        assert any("monthly_cap" in b for b in result.block_reasons)

    def test_blocks_when_reserve_floor_violated(self) -> None:
        arts = _fresh_artifacts(
            finance_latest=_make_artifact(
                "finance_latest",
                data={
                    "autonomy_mode": "live_spend",
                    "monthly_new_committed_usd": 0.0,
                    "monthly_new_commitment_cap_usd": MONTHLY_NEW_COMMITMENT_CAP_USD,
                    "single_action_cap_usd": SINGLE_ACTION_CAP_USD,
                    "reserve_floor_ok": False,
                    "cash_reserve_months": 0.5,
                    "min_cash_reserve_months": 1.0,
                },
            )
        )
        result = run_finance_gate(arts, proposed_action_usd=0.0)
        assert not result.passed
        assert any("reserve" in b for b in result.block_reasons)

    def test_zero_spend_no_new_vendor_always_passes_on_live_spend(self) -> None:
        arts = _fresh_artifacts()
        result = run_finance_gate(arts, proposed_action_usd=0.0, vendor_monthly_usd=0.0)
        assert result.passed


# ── Stage transition tests ─────────────────────────────────────────────────────

class TestEvaluateStageTransition:
    def test_promotes_stage0_to_stage1_when_cascade_and_mc_ready(self) -> None:
        state = RolloutState(current_stage=STAGE_SHADOW_REPLAY)
        arts = _fresh_artifacts()
        finance = _passing_finance()
        action, target, blocks = evaluate_stage_transition(state, arts, finance)
        assert action == "promote"
        assert target == STAGE_SHADOW_LIVE_INTENTS
        assert blocks == []

    def test_holds_stage0_when_cascade_missing(self) -> None:
        state = RolloutState(current_stage=STAGE_SHADOW_REPLAY)
        arts = _fresh_artifacts(
            cross_asset_cascade=_make_artifact("cross_asset_cascade", exists=False)
        )
        finance = _passing_finance()
        action, target, blocks = evaluate_stage_transition(state, arts, finance)
        assert action == "hold"
        assert target is None
        assert any("cascade" in b for b in blocks)

    def test_holds_stage1_when_insufficient_positive_intent_cycles(self) -> None:
        # positive_intent_cycles=0 → +1 from current shadow notional = 1, below MIN of 2
        state = RolloutState(current_stage=STAGE_SHADOW_LIVE_INTENTS, positive_intent_cycles=0)
        arts = _fresh_artifacts()
        finance = _passing_finance()
        action, target, blocks = evaluate_stage_transition(state, arts, finance)
        assert action == "hold"
        assert any("positive_intent_cycles" in b for b in blocks)

    def test_promotes_stage1_to_stage2_when_sufficient_intent_cycles(self) -> None:
        state = RolloutState(
            current_stage=STAGE_SHADOW_LIVE_INTENTS,
            positive_intent_cycles=2,  # already at 2, gets +1 from current shadow_notional > 0
        )
        arts = _fresh_artifacts()
        finance = _passing_finance()
        action, target, blocks = evaluate_stage_transition(state, arts, finance)
        assert action == "promote"
        assert target == STAGE_SINGLE_FOLLOWER_MICRO

    def test_holds_stage1_when_wallet_reconciliation_precision_is_not_ready(self) -> None:
        state = RolloutState(current_stage=STAGE_SHADOW_LIVE_INTENTS, positive_intent_cycles=2)
        arts = _fresh_artifacts(
            wallet_reconciliation=_make_artifact(
                "wallet_reconciliation",
                data={
                    "snapshot_precision": 0.92,
                    "classification_precision": 0.80,
                    "phantom_local_open_trade_ids": ["phantom-1"],
                },
            )
        )
        finance = _passing_finance()
        action, target, blocks = evaluate_stage_transition(state, arts, finance)
        assert action == "hold"
        assert target is None
        assert any("wallet_reconciliation_not_ready" in b for b in blocks)

    def test_holds_stage1_when_finance_gate_fails(self) -> None:
        state = RolloutState(current_stage=STAGE_SHADOW_LIVE_INTENTS, positive_intent_cycles=2)
        arts = _fresh_artifacts()
        finance = _blocking_finance("test_finance_block")
        action, target, blocks = evaluate_stage_transition(state, arts, finance)
        assert action == "hold"
        assert any("finance" in b or "test_finance_block" in b for b in blocks)

    def test_demotes_on_mc_tail_breach_in_live_stage(self) -> None:
        state = RolloutState(current_stage=STAGE_SINGLE_FOLLOWER_MICRO, active_followers=["ETH"])
        arts = _fresh_artifacts(
            cross_asset_mc=_make_artifact("cross_asset_mc", data={"tail_breach": True})
        )
        finance = _passing_finance()
        action, target, blocks = evaluate_stage_transition(state, arts, finance)
        assert action == "rollback"
        assert target == STAGE_SHADOW_REPLAY
        assert any("mc_tail_breach" in b for b in blocks)

    def test_repair_branch_when_critical_artifact_missing(self) -> None:
        state = RolloutState(current_stage=STAGE_SHADOW_REPLAY)
        arts = _fresh_artifacts(
            data_plane_health=_make_artifact("data_plane_health", exists=False),
        )
        finance = _passing_finance()
        action, target, blocks = evaluate_stage_transition(state, arts, finance)
        assert action == "repair"
        assert any("data_plane_health" in b for b in blocks)
        # New classification: prefix is missing_artifact:
        assert any(b.startswith("missing_artifact:data_plane_health") for b in blocks)

    def test_demotes_live_stage_on_stale_artifacts(self) -> None:
        state = RolloutState(current_stage=STAGE_SINGLE_FOLLOWER_MICRO, active_followers=["ETH"])
        arts = _fresh_artifacts(
            market_registry=_make_artifact("market_registry", stale=True, age_seconds=120.0)
        )
        finance = _passing_finance()
        action, target, blocks = evaluate_stage_transition(state, arts, finance)
        assert action == "demote"
        assert target == STAGE_SHADOW_LIVE_INTENTS

    def test_demotes_stage2_when_active_follower_auto_killed(self) -> None:
        state = RolloutState(current_stage=STAGE_SINGLE_FOLLOWER_MICRO, active_followers=["ETH"])
        arts = _fresh_artifacts(
            cross_asset_cascade=_make_artifact(
                "cross_asset_cascade",
                data={
                    "trigger_score": 0.8,
                    "shadow_intended_notional_usd": 5.0,
                    "correlation_collapse": False,
                    "followers": {
                        "ETH": {"win_rate": 0.0, "candle_sets": 55, "post_cost_ev": -0.01, "auto_killed": True},
                        "SOL": {"win_rate": 0.59, "candle_sets": 55, "post_cost_ev": 0.002, "auto_killed": False},
                        "XRP": {"win_rate": 0.57, "candle_sets": 55, "post_cost_ev": 0.001, "auto_killed": False},
                        "DOGE": {"win_rate": 0.56, "candle_sets": 55, "post_cost_ev": 0.001, "auto_killed": False},
                    },
                },
            )
        )
        finance = _passing_finance()
        action, target, blocks = evaluate_stage_transition(state, arts, finance)
        assert action == "demote"
        assert any("auto_killed" in b for b in blocks)

    def test_holds_stage2_when_insufficient_candle_sets(self) -> None:
        state = RolloutState(
            current_stage=STAGE_SINGLE_FOLLOWER_MICRO,
            active_followers=["ETH"],
            cumulative_candle_sets={"ETH": 0},
        )
        arts = _fresh_artifacts(
            cross_asset_cascade=_make_artifact(
                "cross_asset_cascade",
                data={
                    "trigger_score": 0.8,
                    "shadow_intended_notional_usd": 5.0,
                    "correlation_collapse": False,
                    "followers": {
                        "ETH": {"win_rate": 0.62, "candle_sets": 10, "post_cost_ev": 0.003, "auto_killed": False},
                        "SOL": {"win_rate": 0.60, "candle_sets": 55, "post_cost_ev": 0.002, "auto_killed": False},
                        "XRP": {"win_rate": 0.57, "candle_sets": 55, "post_cost_ev": 0.001, "auto_killed": False},
                        "DOGE": {"win_rate": 0.56, "candle_sets": 55, "post_cost_ev": 0.001, "auto_killed": False},
                    },
                },
            )
        )
        finance = _passing_finance()
        action, target, blocks = evaluate_stage_transition(state, arts, finance)
        assert action == "hold"
        assert any("candle_sets" in b for b in blocks)

    def test_demotes_stage3_on_correlation_collapse(self) -> None:
        state = RolloutState(
            current_stage=STAGE_TWO_ASSET_BASKET,
            active_followers=["ETH", "SOL"],
        )
        arts = _fresh_artifacts(
            cross_asset_cascade=_make_artifact(
                "cross_asset_cascade",
                data={
                    "trigger_score": 0.8,
                    "shadow_intended_notional_usd": 10.0,
                    "correlation_collapse": True,
                    "followers": {
                        "ETH": {"win_rate": 0.62, "candle_sets": 60, "post_cost_ev": 0.003, "auto_killed": False},
                        "SOL": {"win_rate": 0.59, "candle_sets": 55, "post_cost_ev": 0.002, "auto_killed": False},
                        "XRP": {"win_rate": 0.57, "candle_sets": 55, "post_cost_ev": 0.001, "auto_killed": False},
                        "DOGE": {"win_rate": 0.56, "candle_sets": 55, "post_cost_ev": 0.001, "auto_killed": False},
                    },
                },
            )
        )
        finance = _passing_finance()
        action, target, blocks = evaluate_stage_transition(state, arts, finance)
        assert action == "demote"
        assert target == STAGE_SHADOW_LIVE_INTENTS
        assert any("correlation_collapse" in b for b in blocks)

    def test_promotes_stage3_to_stage4_when_all_four_followers_pass(self) -> None:
        state = RolloutState(
            current_stage=STAGE_TWO_ASSET_BASKET,
            active_followers=["ETH", "SOL"],
        )
        arts = _fresh_artifacts()
        finance = _passing_finance()
        action, target, blocks = evaluate_stage_transition(state, arts, finance)
        assert action == "promote"
        assert target == STAGE_FOUR_ASSET_BASKET

    def test_holds_stage4_as_max_stage(self) -> None:
        state = RolloutState(current_stage=STAGE_FOUR_ASSET_BASKET, active_followers=list("ESXD"))
        arts = _fresh_artifacts()
        finance = _passing_finance()
        action, target, blocks = evaluate_stage_transition(state, arts, finance)
        assert action == "hold"
        assert target is None


# ── Apply transition tests ────────────────────────────────────────────────────

class TestApplyTransition:
    def test_promote_increments_stage_and_resets_cycles(self) -> None:
        state = RolloutState(current_stage=STAGE_SHADOW_REPLAY, cycles_at_stage=5)
        arts = _fresh_artifacts()
        new_state = apply_transition(state, "promote", STAGE_SHADOW_LIVE_INTENTS, arts)
        assert new_state.current_stage == STAGE_SHADOW_LIVE_INTENTS
        assert new_state.cycles_at_stage == 0
        assert new_state.last_promotion_ts is not None

    def test_demote_resets_followers_and_positive_intent_cycles(self) -> None:
        state = RolloutState(
            current_stage=STAGE_SINGLE_FOLLOWER_MICRO,
            active_followers=["ETH"],
            positive_intent_cycles=4,
            cycles_at_stage=10,
        )
        arts = _fresh_artifacts()
        new_state = apply_transition(state, "demote", STAGE_SHADOW_LIVE_INTENTS, arts)
        assert new_state.current_stage == STAGE_SHADOW_LIVE_INTENTS
        assert new_state.active_followers == []
        assert new_state.positive_intent_cycles == 0
        assert new_state.cycles_at_stage == 0
        assert new_state.last_demotion_ts is not None

    def test_hold_increments_cycle_count_and_updates_candle_sets(self) -> None:
        state = RolloutState(
            current_stage=STAGE_SINGLE_FOLLOWER_MICRO,
            active_followers=["ETH"],
            cycles_at_stage=3,
            cumulative_candle_sets={"ETH": 20},
        )
        arts = _fresh_artifacts()
        new_state = apply_transition(state, "hold", None, arts)
        assert new_state.cycles_at_stage == 4
        assert new_state.cumulative_candle_sets.get("ETH", 0) > 20

    def test_hold_increments_positive_intent_cycles_when_notional_positive(self) -> None:
        state = RolloutState(
            current_stage=STAGE_SHADOW_LIVE_INTENTS,
            positive_intent_cycles=1,
        )
        arts = _fresh_artifacts()  # shadow_intended_notional_usd = 5.0
        new_state = apply_transition(state, "hold", None, arts)
        assert new_state.positive_intent_cycles == 2

    def test_hold_resets_positive_intent_cycles_when_no_notional(self) -> None:
        state = RolloutState(
            current_stage=STAGE_SHADOW_LIVE_INTENTS,
            positive_intent_cycles=3,
        )
        arts = _fresh_artifacts(
            cross_asset_cascade=_make_artifact(
                "cross_asset_cascade",
                data={"trigger_score": 0.5, "shadow_intended_notional_usd": 0.0, "followers": {}},
            )
        )
        new_state = apply_transition(state, "hold", None, arts)
        assert new_state.positive_intent_cycles == 0


# ── Repair branch tests ────────────────────────────────────────────────────────

class TestBuildRepairBranches:
    def test_generates_repair_for_stale_artifact(self) -> None:
        arts = _fresh_artifacts(
            market_registry=_make_artifact("market_registry", stale=True)
        )
        branches = build_repair_branches(arts, "repair")
        names = [b.artifact for b in branches]
        assert "market_registry" in names
        assert any("market_registry" in b.artifact for b in branches)

    def test_generates_repair_for_missing_artifact(self) -> None:
        arts = _fresh_artifacts(
            data_plane_health=_make_artifact("data_plane_health", exists=False)
        )
        branches = build_repair_branches(arts, "repair")
        names = [b.artifact for b in branches]
        assert "data_plane_health" in names

    def test_no_repair_branches_for_promote_action(self) -> None:
        arts = _fresh_artifacts()
        branches = build_repair_branches(arts, "promote")
        assert branches == []

    def test_retry_eta_is_set(self) -> None:
        arts = _fresh_artifacts(
            cross_asset_cascade=_make_artifact("cross_asset_cascade", stale=True)
        )
        branches = build_repair_branches(arts, "hold")
        assert all(b.retry_eta_minutes > 0 for b in branches)


# ── Full run (dry_run) test ────────────────────────────────────────────────────

class TestRunDryRun:
    def test_run_dry_run_returns_packet_without_writing_files(self, tmp_path) -> None:
        from scripts.instance6_rollout_controller import run

        output = tmp_path / "latest.json"
        with (
            patch(
                "scripts.instance6_rollout_controller.ROLLOUT_STATE_PATH",
                tmp_path / "state.json",
            ),
            patch(
                "scripts.instance6_rollout_controller.ARTIFACT_PATHS",
                {
                    name: (tmp_path / f"{name}.json", threshold)
                    for name, (_, threshold) in __import__(
                        "scripts.instance6_rollout_controller",
                        fromlist=["ARTIFACT_PATHS"],
                    ).ARTIFACT_PATHS.items()
                },
            ),
        ):
            packet = run(dry_run=True, output_path=output)

        # No output file written in dry_run mode
        assert not output.exists()
        assert packet.generated_at
        assert packet.action in {"promote", "hold", "demote", "rollback", "repair"}

    def test_run_writes_output_when_not_dry_run(self, tmp_path) -> None:
        from scripts.instance6_rollout_controller import run, ARTIFACT_PATHS

        output = tmp_path / "out" / "latest.json"
        state_path = tmp_path / "state.json"

        # Seed finance artifact so finance gate has data
        fin_dir = tmp_path / "finance"
        fin_dir.mkdir(parents=True)
        (fin_dir / "latest.json").write_text(
            json.dumps({
                "autonomy_mode": "live_spend",
                "monthly_new_committed_usd": 0.0,
                "monthly_new_commitment_cap_usd": MONTHLY_NEW_COMMITMENT_CAP_USD,
                "single_action_cap_usd": SINGLE_ACTION_CAP_USD,
                "reserve_floor_ok": True,
                "cash_reserve_months": 3.0,
                "min_cash_reserve_months": 1.0,
            }),
            encoding="utf-8",
        )

        with (
            patch(
                "scripts.instance6_rollout_controller.ROLLOUT_STATE_PATH",
                state_path,
            ),
        ):
            packet = run(dry_run=False, output_path=output)

        assert output.exists()
        saved = json.loads(output.read_text())
        assert "action" in saved
        assert "generated_at" in saved
        assert "one_next_cycle_action" in saved


# ── Finance cap constants test ─────────────────────────────────────────────────

class TestFinanceCapsMatchPolicy:
    def test_single_action_cap_is_250(self) -> None:
        assert SINGLE_ACTION_CAP_USD == 250.0

    def test_monthly_cap_is_1000(self) -> None:
        assert MONTHLY_NEW_COMMITMENT_CAP_USD == 1000.0


# ── Canonical path hygiene tests ───────────────────────────────────────────────

class TestCanonicalPathHygiene:
    """Fail if any required canonical cross-asset artifact path is missing from ARTIFACT_PATHS."""

    REQUIRED_CANONICAL_KEYS = (
        "data_plane_health",
        "market_registry",
        "cross_asset_cascade",
        "cross_asset_mc",
        "instance1_artifact",
        "instance2_artifact",
        "instance3_artifact",
        "instance4_artifact",
        "instance5_artifact",
        "wallet_reconciliation",
        "finance_latest",
        "finance_action_queue",
        "remote_cycle_status",
        "btc5_rollout_latest",
    )

    def test_all_required_keys_present_in_artifact_paths(self) -> None:
        for key in self.REQUIRED_CANONICAL_KEYS:
            assert key in ARTIFACT_PATHS, f"ARTIFACT_PATHS missing required key: {key}"

    def test_no_duplicate_canonical_paths(self) -> None:
        paths = [str(p) for p, _ in ARTIFACT_PATHS.values()]
        assert len(paths) == len(set(paths)), "Duplicate canonical paths in ARTIFACT_PATHS"

    def test_fallback_keys_are_subset_of_artifact_paths(self) -> None:
        for key in FALLBACK_PATHS:
            assert key in ARTIFACT_PATHS, (
                f"FALLBACK_PATHS key '{key}' has no corresponding canonical ARTIFACT_PATHS entry"
            )

    def test_follower_assets_matches_expected_universe(self) -> None:
        assert set(FOLLOWER_ASSETS) == {"ETH", "SOL", "XRP", "DOGE"}

    def test_run_writes_mirror_path_when_not_dry_run(self, tmp_path) -> None:
        from scripts.instance6_rollout_controller import run, ARTIFACT_PATHS, MIRROR_PATH

        output = tmp_path / "out" / "latest.json"
        mirror = tmp_path / "rollout_control" / "latest.json"
        state_path = tmp_path / "state.json"

        fin_dir = tmp_path / "finance"
        fin_dir.mkdir(parents=True)
        (fin_dir / "latest.json").write_text(
            json.dumps({
                "autonomy_mode": "live_spend",
                "monthly_new_committed_usd": 0.0,
                "monthly_new_commitment_cap_usd": MONTHLY_NEW_COMMITMENT_CAP_USD,
                "single_action_cap_usd": SINGLE_ACTION_CAP_USD,
                "reserve_floor_ok": True,
                "cash_reserve_months": 3.0,
                "min_cash_reserve_months": 1.0,
            }),
            encoding="utf-8",
        )

        from unittest.mock import patch
        with (
            patch("scripts.instance6_rollout_controller.ROLLOUT_STATE_PATH", state_path),
            patch("scripts.instance6_rollout_controller.MIRROR_PATH", mirror),
        ):
            run(dry_run=False, output_path=output)

        assert output.exists(), "Canonical output not written"
        assert mirror.exists(), "Mirror path not written"
        canonical = json.loads(output.read_text())
        mirrored = json.loads(mirror.read_text())
        assert canonical == mirrored, "Canonical and mirror outputs diverged"

    def test_stale_finance_inputs_trigger_repair(self) -> None:
        state = RolloutState(current_stage=STAGE_SHADOW_REPLAY)
        arts = _fresh_artifacts(
            finance_latest=_make_artifact("finance_latest", stale=True, age_seconds=7200.0),
        )
        finance = _passing_finance()
        action, target, blocks = evaluate_stage_transition(state, arts, finance)
        assert action == "repair"
        assert any("stale_finance_inputs" in b for b in blocks)

    def test_no_follower_universe_blocker_when_cascade_has_no_candle_sets(self) -> None:
        state = RolloutState(current_stage=STAGE_SHADOW_LIVE_INTENTS, positive_intent_cycles=3)
        arts = _fresh_artifacts(
            cross_asset_cascade=_make_artifact(
                "cross_asset_cascade",
                data={
                    "trigger_score": 0.5,
                    "shadow_intended_notional_usd": 5.0,
                    "correlation_collapse": False,
                    "followers": {
                        "ETH": {"win_rate": 0.0, "candle_sets": 0, "post_cost_ev": 0.0, "auto_killed": False},
                        "SOL": {"win_rate": 0.0, "candle_sets": 0, "post_cost_ev": 0.0, "auto_killed": False},
                        "XRP": {"win_rate": 0.0, "candle_sets": 0, "post_cost_ev": 0.0, "auto_killed": False},
                        "DOGE": {"win_rate": 0.0, "candle_sets": 0, "post_cost_ev": 0.0, "auto_killed": False},
                    },
                },
            )
        )
        finance = _passing_finance()
        action, target, blocks = evaluate_stage_transition(state, arts, finance)
        assert action == "hold"
        assert any("no_follower_universe" in b for b in blocks)

    def test_negative_signal_quality_blocker_emitted(self) -> None:
        state = RolloutState(current_stage=STAGE_SHADOW_LIVE_INTENTS, positive_intent_cycles=3)
        arts = _fresh_artifacts(
            cross_asset_cascade=_make_artifact(
                "cross_asset_cascade",
                data={
                    "trigger_score": 0.5,
                    "shadow_intended_notional_usd": 5.0,
                    "correlation_collapse": False,
                    "followers": {
                        "ETH": {"win_rate": 0.40, "candle_sets": 60, "post_cost_ev": -0.001, "auto_killed": False},
                        "SOL": {"win_rate": 0.40, "candle_sets": 55, "post_cost_ev": -0.001, "auto_killed": False},
                        "XRP": {"win_rate": 0.40, "candle_sets": 51, "post_cost_ev": -0.001, "auto_killed": False},
                        "DOGE": {"win_rate": 0.40, "candle_sets": 52, "post_cost_ev": -0.001, "auto_killed": False},
                    },
                },
            )
        )
        finance = _passing_finance()
        action, target, blocks = evaluate_stage_transition(state, arts, finance)
        assert action == "hold"
        assert any("negative_signal_quality" in b for b in blocks)

    def test_follower_stats_accepts_bps_only_post_cost_ev_from_instance5(self) -> None:
        state = RolloutState(current_stage=STAGE_SHADOW_LIVE_INTENTS, positive_intent_cycles=3)
        arts = _fresh_artifacts(
            cross_asset_cascade=_make_artifact(
                "cross_asset_cascade",
                data={
                    "trigger_score": 0.5,
                    "shadow_intended_notional_usd": 5.0,
                    "correlation_collapse": False,
                    "followers": {
                        "ETH": {"win_rate": 0.61, "candle_sets": 60, "post_cost_ev_bps": 12.0, "auto_killed": False},
                        "SOL": {"win_rate": 0.40, "candle_sets": 55, "post_cost_ev_bps": -5.0, "auto_killed": False},
                        "XRP": {"win_rate": 0.40, "candle_sets": 51, "post_cost_ev_bps": -5.0, "auto_killed": False},
                        "DOGE": {"win_rate": 0.40, "candle_sets": 52, "post_cost_ev_bps": -5.0, "auto_killed": False},
                    },
                },
            )
        )
        finance = _passing_finance()
        action, target, blocks = evaluate_stage_transition(state, arts, finance)
        assert action == "promote"
        assert target == STAGE_SINGLE_FOLLOWER_MICRO
