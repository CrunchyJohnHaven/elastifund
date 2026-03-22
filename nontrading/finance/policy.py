"""Policy helpers and rollout-gate evaluation for finance autonomy."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nontrading.finance.config import FinanceSettings
from nontrading.finance.store import FinanceStore

LIVE_MODES = {"live_spend", "live_treasury"}
DEFAULT_BOOTSTRAP_STAGE_CAP = 1
DEFAULT_BOOTSTRAP_TRADE_SIZE_USD = 5.0
BOOTSTRAP_LANE_ID = "maker_bootstrap_live"
WALLET_INTEL_SHADOW_LANE_ID = "wallet_intel_directional_shadow"
WEATHER_SHADOW_LANE_ID = "weather"
EVERYTHING_ELSE_LANE_ID = "everything_else"


@dataclass(frozen=True)
class RolloutGateStatus:
    classification_precision: float
    snapshot_reconciliation: float
    ready_for_live_spend: bool
    ready_for_live_treasury: bool
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "classification_precision": round(self.classification_precision, 4),
            "snapshot_reconciliation": round(self.snapshot_reconciliation, 4),
            "ready_for_live_spend": self.ready_for_live_spend,
            "ready_for_live_treasury": self.ready_for_live_treasury,
            "reasons": list(self.reasons),
        }


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def detect_baseline_live_trading_pass(workspace_root: Path) -> bool:
    runtime_truth = load_json(workspace_root / "reports" / "runtime_truth_latest.json")
    if isinstance(runtime_truth, dict):
        direct = runtime_truth.get("btc5_baseline_live_allowed")
        if direct is not None:
            return bool(direct)
        stage = runtime_truth.get("btc5_stage_readiness")
        if isinstance(stage, dict):
            for key in ("baseline_live_allowed", "can_trade_now", "ready_for_stage_1"):
                if key in stage:
                    return bool(stage.get(key))
            status = str(stage.get("trade_now_status") or "").strip().lower()
            if status == "unblocked":
                return True
            allowed_stage = _as_int(stage.get("allowed_stage"), 0)
            if allowed_stage >= DEFAULT_BOOTSTRAP_STAGE_CAP:
                return True
        if runtime_truth.get("allow_order_submission") is not None:
            return bool(runtime_truth.get("allow_order_submission")) and not bool(runtime_truth.get("paper_trading", True))

    launch_packet = load_json(workspace_root / "reports" / "launch_packet_latest.json")
    if isinstance(launch_packet, dict):
        contract = launch_packet.get("contract")
        if isinstance(contract, dict) and contract.get("allow_order_submission") is not None:
            launch_posture = str(contract.get("launch_posture") or "").strip().lower()
            return bool(contract.get("allow_order_submission")) and launch_posture == "clear"
    return False


def _load_bootstrap_trade_size_cap(workspace_root: Path) -> dict[str, Any]:
    payload = load_json(workspace_root / "reports" / "btc5_autoresearch" / "latest.json")
    if not isinstance(payload, dict):
        return {
            "max_live_stage_cap": DEFAULT_BOOTSTRAP_STAGE_CAP,
            "trade_size_cap_usd": DEFAULT_BOOTSTRAP_TRADE_SIZE_USD,
            "source": "default_stage1_cap",
        }

    size_summary = payload.get("selected_size_aware_deployment")
    if not isinstance(size_summary, dict):
        size_summary = payload.get("size_aware_deployment")
    if not isinstance(size_summary, dict):
        size_summary = {}

    stage_cap = max(DEFAULT_BOOTSTRAP_STAGE_CAP, _as_int(size_summary.get("recommended_live_stage_cap"), DEFAULT_BOOTSTRAP_STAGE_CAP))
    trade_size_cap = max(
        0.0,
        _as_float(
            size_summary.get("recommended_live_trade_size_cap_usd"),
            _as_float(size_summary.get("safe_live_trade_size_usd"), DEFAULT_BOOTSTRAP_TRADE_SIZE_USD),
        ),
    )
    if trade_size_cap <= 0:
        trade_size_cap = DEFAULT_BOOTSTRAP_TRADE_SIZE_USD

    return {
        "max_live_stage_cap": min(stage_cap, DEFAULT_BOOTSTRAP_STAGE_CAP),
        "trade_size_cap_usd": round(min(trade_size_cap, DEFAULT_BOOTSTRAP_TRADE_SIZE_USD), 2),
        "source": "reports/btc5_autoresearch/latest.json",
    }


def build_finance_lane_contract(
    *,
    workspace_root: Path,
    capital_ready_to_deploy_usd: float,
    single_action_cap_usd: float,
    baseline_live_trading_pass: bool,
    block_reasons: list[str] | None = None,
    current_live_capital_usd: float | None = None,
) -> dict[str, Any]:
    release_reasons = [str(item) for item in (block_reasons or []) if str(item).strip()]
    size_cap = _load_bootstrap_trade_size_cap(workspace_root)
    approved_live_budget_usd = round(
        max(
            0.0,
            min(
                _as_float(current_live_capital_usd, capital_ready_to_deploy_usd),
                _as_float(single_action_cap_usd),
                _as_float(capital_ready_to_deploy_usd),
            ),
        ),
        2,
    )
    if not baseline_live_trading_pass:
        approved_live_budget_usd = 0.0

    lane_verdicts = {
        BOOTSTRAP_LANE_ID: "baseline_allowed" if baseline_live_trading_pass else "blocked",
        WALLET_INTEL_SHADOW_LANE_ID: "shadow_only",
        WEATHER_SHADOW_LANE_ID: "shadow_only",
        EVERYTHING_ELSE_LANE_ID: "blocked",
    }
    bootstrap_block_reasons = [] if baseline_live_trading_pass else (release_reasons or ["baseline_live_trading_blocked"])
    lane_budgets = {
        BOOTSTRAP_LANE_ID: {
            "lane_id": BOOTSTRAP_LANE_ID,
            "strategy_family": "btc5",
            "finance_verdict": lane_verdicts[BOOTSTRAP_LANE_ID],
            "approved_live_budget_usd": approved_live_budget_usd,
            "live_capital_usd": approved_live_budget_usd,
            "max_live_stage_cap": DEFAULT_BOOTSTRAP_STAGE_CAP,
            "trade_size_cap_usd": round(size_cap["trade_size_cap_usd"], 2),
            "allow_notional_creep": False,
            "flat_stage_only": True,
            "stage_upgrade_allowed": False,
            "capital_expansion_allowed": False,
            "allowed_live_action": "allocate::maintain_stage1_flat_size",
            "block_reasons": bootstrap_block_reasons,
            "trade_size_cap_source": size_cap["source"],
        },
        WALLET_INTEL_SHADOW_LANE_ID: {
            "lane_id": WALLET_INTEL_SHADOW_LANE_ID,
            "strategy_family": "wallet_intel_directional",
            "finance_verdict": lane_verdicts[WALLET_INTEL_SHADOW_LANE_ID],
            "approved_live_budget_usd": 0.0,
            "live_capital_usd": 0.0,
            "allow_notional_creep": False,
            "shadow_scanning_allowed": True,
            "stage_upgrade_allowed": False,
            "capital_expansion_allowed": False,
            "block_reasons": ["shadow_only_lane_no_live_treasury_allocation"],
        },
        WEATHER_SHADOW_LANE_ID: {
            "lane_id": WEATHER_SHADOW_LANE_ID,
            "strategy_family": "weather",
            "finance_verdict": lane_verdicts[WEATHER_SHADOW_LANE_ID],
            "approved_live_budget_usd": 0.0,
            "live_capital_usd": 0.0,
            "allow_notional_creep": False,
            "shadow_scanning_allowed": True,
            "stage_upgrade_allowed": False,
            "capital_expansion_allowed": False,
            "block_reasons": ["weather_live_capital_locked_zero_this_cycle", "capital_expansion_only_hold"],
        },
        EVERYTHING_ELSE_LANE_ID: {
            "lane_id": EVERYTHING_ELSE_LANE_ID,
            "strategy_family": "all_other_lanes",
            "finance_verdict": lane_verdicts[EVERYTHING_ELSE_LANE_ID],
            "approved_live_budget_usd": 0.0,
            "live_capital_usd": 0.0,
            "allow_notional_creep": False,
            "shadow_scanning_allowed": False,
            "stage_upgrade_allowed": False,
            "capital_expansion_allowed": False,
            "block_reasons": ["non_btc5_lanes_blocked_for_this_cycle"],
        },
    }
    allocation_contract = {
        "allow_notional_creep": False,
        "baseline_allocation_state": lane_verdicts[BOOTSTRAP_LANE_ID],
        "wallet_intel_lane_state": lane_verdicts[WALLET_INTEL_SHADOW_LANE_ID],
        "weather_lane_state": lane_verdicts[WEATHER_SHADOW_LANE_ID],
        "other_lanes_state": lane_verdicts[EVERYTHING_ELSE_LANE_ID],
        "btc5_only_live_funded_lane": True,
        "live_funded_lane_ids": [BOOTSTRAP_LANE_ID] if baseline_live_trading_pass else [],
        "shadow_only_lane_ids": [WALLET_INTEL_SHADOW_LANE_ID, WEATHER_SHADOW_LANE_ID],
        "blocked_lane_ids": [EVERYTHING_ELSE_LANE_ID] + ([] if baseline_live_trading_pass else [BOOTSTRAP_LANE_ID]),
        "capital_expansion_only_hold": True,
        "capital_expansion_state": "expansion_blocked",
        "max_live_stage_cap": DEFAULT_BOOTSTRAP_STAGE_CAP,
        "stage_upgrade_allowed": False,
    }
    return {
        "baseline_live_trading_pass": bool(baseline_live_trading_pass),
        "capital_expansion_only_hold": True,
        "max_live_stage_cap": DEFAULT_BOOTSTRAP_STAGE_CAP,
        "finance_lane_verdicts": lane_verdicts,
        "finance_lane_budgets": lane_budgets,
        "allocation_contract": allocation_contract,
        "policy": {
            "baseline_live_allowed": bool(baseline_live_trading_pass),
            "allow_notional_creep": False,
            "btc5_only_live_funded_lane": True,
            "capital_expansion_allowed": False,
            "capital_expansion_only_hold": True,
            "max_live_stage_cap": DEFAULT_BOOTSTRAP_STAGE_CAP,
            "release_rule_required_for_expansion": True,
            "scale_up_allowed": False,
            "stage_upgrade_allowed": False,
            "weather_shadow_only": True,
        },
        "verdict": dict(lane_verdicts),
        "bankroll": {
            "currency": "USD",
            "sleeves": dict(lane_budgets),
        },
    }


def evaluate_rollout_gates(store: FinanceStore) -> RolloutGateStatus:
    classification_precision = float(store.get_budget_policy("classification_precision", 0.0) or 0.0)
    snapshot_reconciliation = float(store.get_budget_policy("snapshot_reconciliation", 0.0) or 0.0)
    reasons: list[str] = []
    if classification_precision < 0.95:
        reasons.append("classification_precision_below_0_95")
    if snapshot_reconciliation < 0.99:
        reasons.append("snapshot_reconciliation_below_0_99")
    live_ready = not reasons
    return RolloutGateStatus(
        classification_precision=classification_precision,
        snapshot_reconciliation=snapshot_reconciliation,
        ready_for_live_spend=live_ready,
        ready_for_live_treasury=live_ready,
        reasons=tuple(reasons),
    )


def refresh_rollout_gate_policies(store: FinanceStore, settings: FinanceSettings) -> RolloutGateStatus:
    transactions = store.list_transactions()
    if transactions:
        categorized = sum(1 for item in transactions if str(item.category or "").strip().lower() not in {"", "uncategorized"})
        classification_precision = categorized / len(transactions)
    else:
        classification_precision = float(store.get_budget_policy("classification_precision", 0.0) or 0.0)

    snapshot_reconciliation = float(store.get_budget_policy("snapshot_reconciliation", 0.0) or 0.0)
    runtime_truth = load_json(settings.workspace_root / "reports" / "runtime_truth_latest.json")
    if isinstance(runtime_truth, dict):
        reconciliation = runtime_truth.get("accounting_reconciliation")
        if isinstance(reconciliation, dict):
            status_ok = str(reconciliation.get("status") or "").lower() == "reconciled"
            delta_ok = abs(float(reconciliation.get("capital_accounting_delta_usd", 0.0) or 0.0)) < 0.005
            open_ok = int((reconciliation.get("unmatched_open_positions") or {}).get("absolute_delta", 1) or 0) == 0
            closed_ok = int((reconciliation.get("unmatched_closed_positions") or {}).get("absolute_delta", 1) or 0) == 0
            checks = [status_ok, delta_ok, open_ok, closed_ok]
            snapshot_reconciliation = sum(1.0 for passed in checks if passed) / len(checks)

    store.set_budget_policy("classification_precision", round(classification_precision, 4))
    store.set_budget_policy("snapshot_reconciliation", round(snapshot_reconciliation, 4))
    return evaluate_rollout_gates(store)


def build_finance_totals(store: FinanceStore, settings: FinanceSettings) -> dict[str, float]:
    accounts = store.list_accounts()
    positions = store.list_positions()
    subscriptions = [item for item in store.list_subscriptions() if item.status.lower() == "active"]
    commitments = store.list_recurring_commitments()
    experiments = [item for item in store.list_experiments() if item.status.lower() in {"candidate", "active"}]

    liquid_cash_usd = round(
        sum(account.available_cash_usd or account.balance_usd for account in accounts),
        2,
    )
    startup_equity_usd = round(
        sum(position.market_value_usd for position in positions if position.asset_type == "startup_equity"),
        2,
    )
    deployable_positions_usd = round(
        sum(
            position.deployable_cash_usd or position.market_value_usd
            for position in positions
            if position.asset_type not in {"startup_equity"}
        ),
        2,
    )
    subscription_burn_monthly = round(sum(item.monthly_cost_usd for item in subscriptions), 2)
    recurring_commitments_monthly = round(sum(item.monthly_cost_usd for item in commitments), 2)
    monthly_burn_usd = round(subscription_burn_monthly + recurring_commitments_monthly, 2)
    cash_reserve_floor_usd = round(monthly_burn_usd * settings.min_cash_reserve_months, 2)
    if settings.equity_treatment == "illiquid_only":
        deployable_cash_base = liquid_cash_usd
    else:
        deployable_cash_base = liquid_cash_usd + startup_equity_usd
    capital_ready_to_deploy_usd = round(max(deployable_cash_base - cash_reserve_floor_usd, 0.0), 2)
    active_experiment_budget_usd = round(sum(item.budget_usd for item in experiments), 2)
    return {
        "liquid_cash_usd": liquid_cash_usd,
        "deployable_positions_usd": deployable_positions_usd,
        "startup_equity_usd": startup_equity_usd,
        "subscription_burn_monthly": subscription_burn_monthly,
        "recurring_commitments_monthly": recurring_commitments_monthly,
        "monthly_burn_usd": monthly_burn_usd,
        "cash_reserve_floor_usd": cash_reserve_floor_usd,
        "free_cash_after_floor": capital_ready_to_deploy_usd,
        "capital_ready_to_deploy_usd": capital_ready_to_deploy_usd,
        "active_experiment_budget_usd": active_experiment_budget_usd,
    }
