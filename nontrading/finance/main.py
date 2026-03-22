"""CLI entrypoint for the personal CFO finance worker."""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import replace
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from typing import Any

from nontrading.finance.action_queue import FinanceActionQueue
from nontrading.finance.allocator import build_allocation_plan
from nontrading.finance.config import FinanceSettings
from nontrading.finance.executor import FinanceExecutionError, FinanceExecutor
from nontrading.finance.models import (
    FinanceAccount,
    FinanceAction,
    FinanceExperiment,
    FinancePosition,
    FinanceRecurringCommitment,
    FinanceSubscription,
    FinanceTransaction,
    utc_now,
)
from nontrading.finance.policy import (
    build_finance_lane_contract,
    build_finance_totals,
    detect_baseline_live_trading_pass,
    evaluate_rollout_gates,
    load_json,
    refresh_rollout_gate_policies,
)
from nontrading.finance.recurring import detect_recurring_commitments
from nontrading.finance.store import FinanceStore
from nontrading.finance.subscriptions import audit_subscriptions
from nontrading.finance.vendor_registry import infer_category


def _read_rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            if "rows" in payload:
                rows = payload["rows"]
            else:
                rows = [payload]
        else:
            rows = payload
        return [dict(row) for row in rows]
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    if path.suffix.lower() == ".ofx":
        rows: list[dict[str, Any]] = []
        current: dict[str, str] = {}
        for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if line.startswith("<STMTTRN>"):
                current = {}
                continue
            if line.startswith("</STMTTRN>"):
                rows.append(current)
                current = {}
                continue
            if line.startswith("<") and ">" in line:
                tag, value = line[1:].split(">", 1)
                current[tag.upper()] = value.strip()
        normalized: list[dict[str, Any]] = []
        for index, row in enumerate(rows):
            normalized.append(
                {
                    "transaction_key": f"{path.stem}-{index}",
                    "account_key": path.stem,
                    "posted_at": row.get("DTPOSTED", ""),
                    "merchant": row.get("NAME", ""),
                    "description": row.get("MEMO", ""),
                    "amount_usd": row.get("TRNAMT", 0.0),
                    "category": "",
                    "source": "ofx_import",
                }
            )
        return normalized
    return []


def _normalize_path(path: Path, workspace_root: Path) -> Path:
    return path if path.is_absolute() else workspace_root / path


def _plus_minutes(value: str, minutes: int) -> str:
    return (datetime.fromisoformat(value.replace("Z", "+00:00")) + timedelta(minutes=minutes)).isoformat()


def _execution_policy_checks(
    *,
    action: Any | None,
    settings: FinanceSettings,
    totals: dict[str, Any],
    remaining_monthly_commitment: float,
) -> dict[str, Any]:
    if action is None:
        return {
            "reserve_floor_pass": True,
            "single_action_cap_pass": True,
            "monthly_commitment_cap_pass": True,
            "whitelist_destination_pass": True,
            "wallet_truth_check_pass": False,
            "destination_whitelisted": True,
            "destination": "",
        }
    destination = action.destination.strip().lower()
    whitelist = set(settings.whitelist)
    wallet_truth_check_pass = bool(
        load_json(settings.workspace_root / "reports" / "runtime_truth_latest.json")
    )
    return {
        "reserve_floor_pass": float(action.amount_usd or 0.0) <= float(totals.get("capital_ready_to_deploy_usd", 0.0) or 0.0),
        "single_action_cap_pass": float(action.amount_usd or 0.0) <= settings.single_action_cap_usd,
        "monthly_commitment_cap_pass": float(action.monthly_commitment_usd or 0.0) <= remaining_monthly_commitment,
        "whitelist_destination_pass": (not action.requires_whitelist) or (destination in whitelist),
        "wallet_truth_check_pass": wallet_truth_check_pass,
        "destination_whitelisted": destination in whitelist if destination else True,
        "destination": action.destination,
    }


def _sync_import_dir(store: FinanceStore, settings: FinanceSettings) -> dict[str, Any]:
    imported_counts = {
        "accounts": 0,
        "transactions": 0,
        "positions": 0,
        "subscriptions": 0,
        "experiments": 0,
    }
    gaps: list[str] = []
    import_dir = _normalize_path(settings.imports_dir, settings.workspace_root)
    import_dir.mkdir(parents=True, exist_ok=True)

    for path in sorted(import_dir.iterdir()):
        if not path.is_file():
            continue
        rows = _read_rows(path)
        stem = path.stem.lower()
        if stem.startswith("account"):
            for row in rows:
                store.upsert_account(
                    FinanceAccount(
                        account_key=str(row.get("account_key") or f"{path.stem}-{imported_counts['accounts']}"),
                        name=str(row.get("name") or row.get("account_key") or path.stem),
                        account_type=str(row.get("account_type") or "cash"),
                        institution=str(row.get("institution") or ""),
                        currency=str(row.get("currency") or "USD"),
                        balance_usd=float(row.get("balance_usd", 0.0) or 0.0),
                        available_cash_usd=float(row.get("available_cash_usd", row.get("balance_usd", 0.0)) or 0.0),
                        source=str(row.get("source") or "import"),
                        metadata={k: v for k, v in row.items() if k not in {"account_key", "name", "account_type", "institution", "currency", "balance_usd", "available_cash_usd", "source"}},
                    )
                )
                imported_counts["accounts"] += 1
            continue
        if stem.startswith("transaction") or path.suffix.lower() == ".ofx":
            for index, row in enumerate(rows):
                store.upsert_transaction(
                    FinanceTransaction(
                        transaction_key=str(row.get("transaction_key") or f"{path.stem}-{index}"),
                        account_key=str(row.get("account_key") or "imports"),
                        posted_at=str(row.get("posted_at") or row.get("date") or row.get("DTPOSTED") or utc_now()),
                        merchant=str(row.get("merchant") or row.get("NAME") or row.get("payee") or ""),
                        description=str(row.get("description") or row.get("MEMO") or ""),
                        amount_usd=float(row.get("amount_usd", row.get("amount", row.get("TRNAMT", 0.0))) or 0.0),
                        category=str(row.get("category") or ""),
                        source=str(row.get("source") or "import"),
                        metadata={k: v for k, v in row.items() if k not in {"transaction_key", "account_key", "posted_at", "date", "merchant", "description", "amount_usd", "amount", "category", "source"}},
                    )
                )
                imported_counts["transactions"] += 1
            continue
        if stem.startswith("position") or stem.startswith("equity"):
            for index, row in enumerate(rows):
                asset_type = str(row.get("asset_type") or ("startup_equity" if "equity" in stem else "security"))
                store.upsert_position(
                    FinancePosition(
                        position_key=str(row.get("position_key") or f"{path.stem}-{index}"),
                        account_key=str(row.get("account_key") or "portfolio"),
                        symbol=str(row.get("symbol") or row.get("ticker") or path.stem),
                        asset_type=asset_type,
                        quantity=float(row.get("quantity", 0.0) or 0.0),
                        market_value_usd=float(row.get("market_value_usd", row.get("value_usd", 0.0)) or 0.0),
                        deployable_cash_usd=float(row.get("deployable_cash_usd", 0.0) or 0.0),
                        source=str(row.get("source") or "import"),
                        metadata={k: v for k, v in row.items() if k not in {"position_key", "account_key", "symbol", "ticker", "asset_type", "quantity", "market_value_usd", "value_usd", "deployable_cash_usd", "source"}},
                    )
                )
                imported_counts["positions"] += 1
            continue
        if stem.startswith("subscription"):
            for index, row in enumerate(rows):
                store.upsert_subscription(
                    FinanceSubscription(
                        subscription_key=str(row.get("subscription_key") or f"{path.stem}-{index}"),
                        vendor=str(row.get("vendor") or row.get("merchant") or ""),
                        product_name=str(row.get("product_name") or row.get("plan") or ""),
                        category=infer_category(
                            str(row.get("vendor") or row.get("merchant") or ""),
                            str(row.get("category") or ""),
                            str(row.get("product_name") or ""),
                        ),
                        monthly_cost_usd=float(row.get("monthly_cost_usd", row.get("amount_usd", 0.0)) or 0.0),
                        billing_cycle=str(row.get("billing_cycle") or "monthly"),
                        usage_frequency=str(row.get("usage_frequency") or "unknown"),
                        status=str(row.get("status") or "active"),
                        duplicate_group=str(row.get("duplicate_group") or ""),
                        source=str(row.get("source") or "import"),
                        metadata={k: v for k, v in row.items() if k not in {"subscription_key", "vendor", "merchant", "product_name", "plan", "category", "monthly_cost_usd", "amount_usd", "billing_cycle", "usage_frequency", "status", "duplicate_group", "source"}},
                    )
                )
                imported_counts["subscriptions"] += 1
            continue
        if stem.startswith("experiment"):
            for index, row in enumerate(rows):
                store.upsert_experiment(
                    FinanceExperiment(
                        experiment_key=str(row.get("experiment_key") or f"{path.stem}-{index}"),
                        name=str(row.get("name") or f"experiment-{index}"),
                        bucket=str(row.get("bucket") or "buy_tool_or_data"),
                        status=str(row.get("status") or "candidate"),
                        budget_usd=float(row.get("budget_usd", 0.0) or 0.0),
                        monthly_budget_usd=float(row.get("monthly_budget_usd", 0.0) or 0.0),
                        expected_net_value_30d=float(row.get("expected_net_value_30d", 0.0) or 0.0),
                        expected_information_gain_30d=float(row.get("expected_information_gain_30d", 0.0) or 0.0),
                        metadata={k: v for k, v in row.items() if k not in {"experiment_key", "name", "bucket", "status", "budget_usd", "monthly_budget_usd", "expected_net_value_30d", "expected_information_gain_30d"}},
                    )
                )
                imported_counts["experiments"] += 1
            continue

    if imported_counts["accounts"] == 0:
        gaps.append("accounts_import_missing")
    if imported_counts["transactions"] == 0:
        gaps.append("transactions_import_missing")
    return {"imported_counts": imported_counts, "gaps": gaps}


def _sync_runtime_truth(store: FinanceStore, settings: FinanceSettings) -> list[str]:
    gaps: list[str] = []
    runtime_truth = load_json(settings.workspace_root / "reports" / "runtime_truth_latest.json")
    if runtime_truth is None:
        return ["runtime_truth_missing"]
    capital = runtime_truth.get("capital", {})
    wallet = runtime_truth.get("polymarket_wallet", {})
    store.upsert_account(
        FinanceAccount(
            account_key="runtime::polymarket",
            name="Polymarket Runtime",
            account_type="trading",
            institution="Polymarket",
            balance_usd=float(wallet.get("total_wallet_value_usd", 0.0) or 0.0),
            available_cash_usd=float(wallet.get("free_collateral_usd", capital.get("polymarket_actual_deployable_usd", 0.0)) or 0.0),
            source="runtime_truth",
            metadata={"artifact": "reports/runtime_truth_latest.json"},
        )
    )
    store.upsert_position(
        FinancePosition(
            position_key="runtime::polymarket-open",
            account_key="runtime::polymarket",
            symbol="POLY-OPEN",
            asset_type="trading_position",
            quantity=float(wallet.get("open_positions_count", 0.0) or 0.0),
            market_value_usd=float(wallet.get("positions_current_value_usd", 0.0) or 0.0),
            deployable_cash_usd=0.0,
            source="runtime_truth",
            metadata={"artifact": "reports/runtime_truth_latest.json"},
        )
    )
    return gaps


def build_runtime(settings: FinanceSettings) -> tuple[FinanceStore, FinanceActionQueue, FinanceExecutor]:
    settings.validate()
    settings.ensure_paths()
    store = FinanceStore(settings.db_path)
    store.set_budget_policy("autonomy_mode", settings.autonomy_mode)
    store.set_budget_policy("single_action_cap_usd", settings.single_action_cap_usd)
    store.set_budget_policy("monthly_new_commitment_cap_usd", settings.monthly_new_commitment_cap_usd)
    store.set_budget_policy("min_cash_reserve_months", settings.min_cash_reserve_months)
    store.set_budget_policy("equity_treatment", settings.equity_treatment)
    queue = FinanceActionQueue(store)
    executor = FinanceExecutor(store, settings)
    return store, queue, executor


def _merge_lane_contract(
    payload: dict[str, Any],
    *,
    settings: FinanceSettings,
    totals: dict[str, Any],
    block_reasons: list[str] | None = None,
    current_live_capital_usd: float | None = None,
) -> dict[str, Any]:
    lane_contract = build_finance_lane_contract(
        workspace_root=settings.workspace_root,
        capital_ready_to_deploy_usd=float(totals.get("capital_ready_to_deploy_usd", 0.0) or 0.0),
        single_action_cap_usd=settings.single_action_cap_usd,
        baseline_live_trading_pass=detect_baseline_live_trading_pass(settings.workspace_root),
        block_reasons=block_reasons,
        current_live_capital_usd=current_live_capital_usd,
    )
    payload.update(lane_contract)
    return payload


def run_sync(store: FinanceStore, settings: FinanceSettings) -> dict[str, Any]:
    import_summary = _sync_import_dir(store, settings)
    recurring_commitments = detect_recurring_commitments(store)
    runtime_gaps = _sync_runtime_truth(store, settings)
    rollout_gates = refresh_rollout_gate_policies(store, settings)
    totals = build_finance_totals(store, settings)
    report = {
        "schema_version": "finance_latest.v1",
        "generated_at": utc_now(),
        "status_snapshot": store.status_snapshot(),
        "totals": totals,
        "rollout_gates": rollout_gates.to_dict(),
        "imported_counts": import_summary["imported_counts"],
        "recurring_commitments_detected": len(recurring_commitments),
        "gaps": list(import_summary["gaps"]) + runtime_gaps,
    }
    report = _merge_lane_contract(report, settings=settings, totals=totals, block_reasons=report["gaps"])
    settings.latest_report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    store.record_snapshot("sync", report["schema_version"], report)
    return report


def run_audit(store: FinanceStore, settings: FinanceSettings, queue: FinanceActionQueue | None = None) -> dict[str, Any]:
    report = audit_subscriptions(store)
    report = {
        "schema_version": "finance_subscription_audit.v1",
        "generated_at": utc_now(),
        **report,
    }
    settings.subscription_audit_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    store.record_snapshot("audit", report["schema_version"], report)
    if queue is not None:
        queued_actions = [
            FinanceSubscriptionActionBuilder.build(finding)
            for finding in report["findings"]
            if finding["recommended_action"] in {"cancel_duplicate", "cancel_or_pause", "consolidate_stack"}
        ]
        queue.sync_actions(queued_actions)
        settings.action_queue_path.write_text(json.dumps(queue.build_report(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


class FinanceSubscriptionActionBuilder:
    """Build queue actions from subscription findings."""

    @staticmethod
    def build(finding: dict[str, Any]):
        vendor = str(finding.get("vendor") or "subscription")
        finding_id = str(finding.get("finding_id") or vendor)
        return replace(
            FinanceActionTemplate.cancel_subscription(vendor=vendor, amount_usd=float(finding.get("monthly_cost_usd", 0.0) or 0.0)),
            action_key=f"audit::{finding_id}",
            priority_score=float(finding.get("estimated_savings_usd", 0.0) or 0.0),
            reason=str(finding.get("recommended_action") or "cancel"),
            rollback=str(finding.get("rollback") or ""),
            metadata=finding,
        )


class FinanceActionTemplate:
    """Deterministic action templates for queue hydration."""

    @staticmethod
    def cancel_subscription(*, vendor: str, amount_usd: float):
        from nontrading.finance.models import FinanceAction

        return FinanceAction(
            action_key=f"cancel::{vendor.lower()}",
            action_type="cancel_subscription",
            bucket="cut_or_cancel",
            title=f"Cancel or pause {vendor}",
            amount_usd=amount_usd,
            priority_score=amount_usd,
            vendor=vendor,
            mode_requested="live_spend",
            reason="Reduce recurring burn.",
            rollback=f"Restore {vendor} if it is still needed.",
            idempotency_key=f"cancel::{vendor.lower()}",
        )


def run_allocate(store: FinanceStore, settings: FinanceSettings, queue: FinanceActionQueue) -> dict[str, Any]:
    audit_report = store.latest_snapshot("audit") or {"findings": [], "gaps": ["audit_not_run"]}
    plan = build_allocation_plan(store, settings, audit_report=audit_report)
    settings.allocation_plan_path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    store.record_snapshot("allocate", plan["schema_version"], plan)
    queued_actions = [
        FinanceAction(
            **{
                key: value
                for key, value in action.items()
                if key in FinanceAction.__dataclass_fields__
            }
        )
        for action in plan["recommended_actions"]
    ]
    queue.sync_actions(queued_actions)
    settings.action_queue_path.write_text(json.dumps(queue.build_report(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    latest = store.latest_snapshot("sync") or {
        "schema_version": "finance_latest.v1",
        "generated_at": utc_now(),
        "gaps": ["sync_not_run"],
        "totals": build_finance_totals(store, settings),
    }
    latest["allocation_plan"] = plan
    latest["allocation_contract"] = plan.get("allocation_contract", latest.get("allocation_contract"))
    latest["finance_lane_verdicts"] = plan.get("finance_lane_verdicts", latest.get("finance_lane_verdicts"))
    latest["finance_lane_budgets"] = plan.get("finance_lane_budgets", latest.get("finance_lane_budgets"))
    latest["policy"] = plan.get("policy", latest.get("policy"))
    latest["verdict"] = plan.get("verdict", latest.get("verdict"))
    latest["bankroll"] = plan.get("bankroll", latest.get("bankroll"))
    latest["capital_expansion_only_hold"] = plan.get(
        "capital_expansion_only_hold",
        latest.get("capital_expansion_only_hold", True),
    )
    latest["max_live_stage_cap"] = plan.get("max_live_stage_cap", latest.get("max_live_stage_cap", 1))
    latest["baseline_live_trading_pass"] = plan.get(
        "baseline_live_trading_pass",
        latest.get("baseline_live_trading_pass"),
    )
    settings.latest_report_path.write_text(json.dumps(latest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return plan


def run_execute(store: FinanceStore, settings: FinanceSettings, queue: FinanceActionQueue, executor: FinanceExecutor, mode: str | None = None) -> dict[str, Any]:
    selected_mode = (mode or settings.autonomy_mode).strip().lower()
    rollout_gates = refresh_rollout_gate_policies(store, settings)
    pending_actions = store.list_actions(statuses=("queued",))
    top_trading = next((action for action in pending_actions if action.bucket == "fund_trading"), None)
    fallback_action = top_trading or (pending_actions[0] if pending_actions else None)
    totals = build_finance_totals(store, settings)
    remaining_monthly_commitment = round(
        max(
            settings.monthly_new_commitment_cap_usd - store.current_month_new_commitments_usd(),
            0.0,
        ),
        2,
    )
    policy_checks = _execution_policy_checks(
        action=fallback_action,
        settings=settings,
        totals=totals,
        remaining_monthly_commitment=remaining_monthly_commitment,
    )
    if fallback_action is not None and selected_mode in {"live_spend", "live_treasury"}:
        preflight_reason = executor.preview_action(
            fallback_action,
            selected_mode,
            remaining_cash=round(float(totals.get("capital_ready_to_deploy_usd", 0.0)), 2),
            remaining_monthly_commitment=remaining_monthly_commitment,
            rollout_blockers=list(rollout_gates.reasons),
        )
        if preflight_reason and (
            preflight_reason.startswith("rollout_gates_blocked")
            or preflight_reason == "destination_not_whitelisted"
        ):
            retry_at = _plus_minutes(utc_now(), 30)
            destination = fallback_action.destination.strip().lower()
            whitelist = set(settings.whitelist)
            shadow_result = executor.simulate_action(
                fallback_action,
                requested_mode=selected_mode,
                reason="shadow_fallback_due_to_policy_hold",
                metadata={
                    "hold_reason": preflight_reason,
                    "destination_whitelisted": destination in whitelist if destination else True,
                    "policy_checks": policy_checks,
                },
            )
            result = {
                "schema_version": "finance_execute.v1",
                "generated_at": utc_now(),
                "mode": "shadow",
                "requested_mode": selected_mode,
                "finance_gate_pass": False,
                "results": [shadow_result.to_dict()],
                "rollout_gates": rollout_gates.to_dict(),
                "live_hold": {
                    "status": "hold_repair",
                    "requested_mode": selected_mode,
                    "reason": preflight_reason,
                    "policy_checks": policy_checks,
                    "remediation": (
                        f"Add {fallback_action.destination} to JJ_FINANCE_WHITELIST_JSON for live_treasury "
                        "or keep fund_trading in shadow until treasury policy is updated."
                    ),
                    "retry_in_minutes": 30,
                    "retry_at": retry_at,
                    "action_key": fallback_action.action_key,
                    "destination": fallback_action.destination,
                    "destination_whitelisted": destination in whitelist if destination else True,
                },
            }
            settings.action_queue_path.write_text(json.dumps(queue.build_report(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
            latest = store.latest_snapshot("sync") or {
                "schema_version": "finance_latest.v1",
                "generated_at": utc_now(),
                "gaps": ["sync_not_run"],
                "totals": build_finance_totals(store, settings),
            }
            latest["last_execute"] = result
            latest["rollout_gates"] = rollout_gates.to_dict()
            latest = _merge_lane_contract(
                latest,
                settings=settings,
                totals=latest.get("totals") if isinstance(latest.get("totals"), dict) else totals,
                block_reasons=list(dict.fromkeys([*rollout_gates.reasons, preflight_reason])),
                current_live_capital_usd=(
                    fallback_action.amount_usd
                    if fallback_action.bucket == "fund_trading"
                    else None
                ),
            )
            if selected_mode == "live_treasury":
                latest["treasury_gate_pass"] = False
            settings.latest_report_path.write_text(json.dumps(latest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            store.record_snapshot("execute", "finance_execute.v1", result)
            return result
    try:
        execute_keys = (fallback_action.action_key,) if selected_mode == "live_treasury" and fallback_action is not None else None
        result = executor.execute(selected_mode, action_keys=execute_keys)
    except FinanceExecutionError as exc:
        live_hold = {
            "status": "hold_repair",
            "requested_mode": selected_mode,
            "reason": str(exc),
            "policy_checks": policy_checks,
            "retry_in_minutes": 30,
            "retry_at": _plus_minutes(utc_now(), 30),
        }
        if fallback_action is not None:
            destination = fallback_action.destination.strip().lower()
            whitelist = set(settings.whitelist)
            shadow_result = executor.simulate_action(
                fallback_action,
                requested_mode=selected_mode,
                reason="shadow_fallback_due_to_policy_hold",
                metadata={
                    "hold_reason": str(exc),
                    "destination_whitelisted": destination in whitelist if destination else True,
                    "policy_checks": policy_checks,
                },
            )
            live_hold["action_key"] = fallback_action.action_key
            live_hold["destination"] = fallback_action.destination
            live_hold["destination_whitelisted"] = destination in whitelist if destination else True
            live_hold["remediation"] = (
                f"Add {fallback_action.destination} to JJ_FINANCE_WHITELIST_JSON for live_treasury "
                "or keep fund_trading in shadow until treasury policy is updated."
                if str(exc) == "destination_not_whitelisted"
                else "Repair rollout gates or treasury policy, then retry execution in 30 minutes."
            )
            result = {
                "schema_version": "finance_execute.v1",
                "generated_at": utc_now(),
                "mode": "shadow",
                "requested_mode": selected_mode,
                "finance_gate_pass": False,
                "results": [shadow_result.to_dict()],
                "rollout_gates": rollout_gates.to_dict(),
                "live_hold": live_hold,
            }
        else:
            result = {
                "schema_version": "finance_execute.v1",
                "generated_at": utc_now(),
                "mode": selected_mode,
                "requested_mode": selected_mode,
                "finance_gate_pass": False,
                "results": [],
                "rollout_gates": rollout_gates.to_dict(),
                "live_hold": {**live_hold, "reason": f"{exc},no_pending_actions"},
            }
    else:
        result["finance_gate_pass"] = True
        if fallback_action is not None:
            result["policy_checks"] = policy_checks
    settings.action_queue_path.write_text(json.dumps(queue.build_report(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    latest = store.latest_snapshot("sync") or {
        "schema_version": "finance_latest.v1",
        "generated_at": utc_now(),
        "gaps": ["sync_not_run"],
        "totals": build_finance_totals(store, settings),
    }
    latest["last_execute"] = result
    latest["rollout_gates"] = rollout_gates.to_dict()
    latest = _merge_lane_contract(
        latest,
        settings=settings,
        totals=latest.get("totals") if isinstance(latest.get("totals"), dict) else build_finance_totals(store, settings),
        block_reasons=list(rollout_gates.reasons),
        current_live_capital_usd=(
            fallback_action.amount_usd
            if fallback_action is not None and fallback_action.bucket == "fund_trading"
            else None
        ),
    )
    settings.latest_report_path.write_text(json.dumps(latest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    store.record_snapshot("execute", "finance_execute.v1", result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the finance control plane.")
    parser.add_argument("--db-path", help="Override JJ_FINANCE_DB_PATH for this process.")
    parser.add_argument("--imports-dir", help="Override JJ_FINANCE_IMPORTS_DIR for this process.")
    parser.add_argument("--reports-dir", help="Override report output directory for this process.")
    parser.add_argument("--workspace-root", help="Override workspace root for report discovery.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("sync", help="Ingest account, transaction, position, and subscription truth.")
    subparsers.add_parser("audit", help="Produce recurring-spend, cost-cutting, and duplication findings.")
    subparsers.add_parser("allocate", help="Rank where the next dollar should go.")
    execute_parser = subparsers.add_parser("execute", help="Run queued finance actions.")
    execute_parser.add_argument("--mode", choices=["shadow", "live_spend", "live_treasury"])

    args = parser.parse_args(argv)
    settings = FinanceSettings.from_env()
    if args.db_path:
        settings = replace(settings, db_path=Path(args.db_path))
    if args.imports_dir:
        settings = replace(settings, imports_dir=Path(args.imports_dir))
    if args.reports_dir:
        settings = replace(settings, reports_dir=Path(args.reports_dir))
    if args.workspace_root:
        settings = replace(settings, workspace_root=Path(args.workspace_root))

    store, queue, executor = build_runtime(settings)
    if args.command == "sync":
        print(json.dumps(run_sync(store, settings), sort_keys=True))
        return 0
    if args.command == "audit":
        print(json.dumps(run_audit(store, settings, queue), sort_keys=True))
        return 0
    if args.command == "allocate":
        print(json.dumps(run_allocate(store, settings, queue), sort_keys=True))
        return 0
    if args.command == "execute":
        try:
            print(json.dumps(run_execute(store, settings, queue, executor, args.mode), sort_keys=True))
        except FinanceExecutionError as exc:
            print(json.dumps({"status": "blocked", "reason": str(exc)}, sort_keys=True))
            return 2
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
