"""Policy helpers and rollout-gate evaluation for finance autonomy."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nontrading.finance.config import FinanceSettings
from nontrading.finance.store import FinanceStore

LIVE_MODES = {"live_spend", "live_treasury"}


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
