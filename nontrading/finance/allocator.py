"""Allocator that ranks where the next dollar should go."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from datetime import timedelta
from typing import Any

from nontrading.finance.config import FinanceSettings
from nontrading.finance.models import AllocationBucket, FinanceAction, utc_now
from nontrading.finance.policy import build_finance_totals, load_json, load_trading_finance_policy_context
from nontrading.finance.store import FinanceStore


class FinanceBucket(str, Enum):
    KEEP_IN_CASH = "keep_in_cash"
    FUND_TRADING = "fund_trading"
    FUND_NONTRADING = "fund_nontrading"
    BUY_TOOL_OR_DATA = "buy_tool_or_data"
    CUT_OR_CANCEL = "cut_or_cancel"


class ResourceAskKind(str, Enum):
    CAPITAL = "capital"
    TOOL = "tool"
    DATA = "data"
    EXPERIMENT = "experiment"


@dataclass(frozen=True)
class FinancePolicy:
    single_action_cap_usd: float = 250.0
    monthly_new_commitment_cap_usd: float = 1000.0
    min_cash_reserve_months: float = 1.0


@dataclass(frozen=True)
class FinanceSnapshot:
    liquid_cash_usd: float = 0.0
    monthly_burn_usd: float = 0.0
    recurring_commitments_monthly_usd: float = 0.0
    monthly_new_commitments_usd: float = 0.0
    illiquid_equity_usd: float = 0.0
    active_experiment_budget_usd: float = 0.0


@dataclass(frozen=True)
class AllocationCandidate:
    candidate_id: str
    label: str
    bucket: FinanceBucket
    requested_amount_usd: float
    expected_net_value_30d: float
    expected_information_gain_30d: float
    recurring_commitment_monthly_usd: float = 0.0
    confidence: float = 0.0
    ask_kind: ResourceAskKind = ResourceAskKind.CAPITAL
    expected_arr_lift_30d: float = 0.0
    expected_arr_confidence_lift: float = 0.0
    blocker_removal_value: float = 0.0
    model_tier: str = "routine_ingestion"
    model_minutes: float = 0.0
    model_provider: str = ""
    allocation_cap_usd: float | None = None
    hard_blockers: tuple[str, ...] = ()
    decision_reason: str = ""


def _bucket_to_lane(bucket: FinanceBucket) -> str:
    if bucket == FinanceBucket.FUND_TRADING:
        return "trading"
    if bucket == FinanceBucket.FUND_NONTRADING:
        return "nontrading"
    if bucket == FinanceBucket.BUY_TOOL_OR_DATA:
        return "tools"
    return bucket.value


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _plus_minutes(value: str, minutes: int) -> str:
    base = utc_now() if not value else value
    from datetime import datetime

    return (datetime.fromisoformat(base.replace("Z", "+00:00")) + timedelta(minutes=minutes)).isoformat()


def _load_allocation_rankings(workspace_root: Path) -> dict[str, dict[str, Any]]:
    payload = load_json(workspace_root / "reports" / "finance" / "latest.json")
    if not isinstance(payload, dict):
        return {}
    batch = payload.get("allocator_rankings_batch")
    if not isinstance(batch, dict):
        return {}
    rows = batch.get("candidate_rankings")
    if not isinstance(rows, list):
        return {}

    best: dict[str, dict[str, Any]] = {}
    for item in rows:
        if not isinstance(item, dict):
            continue
        lane = str(item.get("lane") or item.get("bucket") or "").lower()
        if lane not in {"trading", "nontrading", "tools"}:
            continue
        if str(item.get("decision") or "").lower() != "approve":
            continue
        confidence = _safe_float(item.get("confidence_score"), 0.0)
        score = _safe_float(item.get("confidence_adjusted_score"), _safe_float(item.get("score"), 0.0))
        if confidence < 0.6 or score <= 0.0:
            continue
        prior = best.get(lane)
        prior_score = _safe_float(prior.get("confidence_adjusted_score"), 0.0) if prior else 0.0
        if prior is None or score > prior_score:
            best[lane] = item
    return best


def _model_value_case(candidate: AllocationCandidate) -> dict[str, float]:
    return {
        "expected_arr_lift_30d": round(candidate.expected_arr_lift_30d, 2),
        "expected_arr_confidence_lift": round(candidate.expected_arr_confidence_lift, 4),
        "blocker_removal_value": round(candidate.blocker_removal_value, 2),
    }


def _has_model_value_case(candidate: AllocationCandidate) -> bool:
    value_case = _model_value_case(candidate)
    return any(float(value or 0.0) > 0.0 for value in value_case.values())


def _is_escalated_model_tier(candidate: AllocationCandidate) -> bool:
    return str(candidate.model_tier or "").strip().lower() == "conflict_arbitration"


def _btc5_stage_green(workspace_root: Path) -> bool:
    runtime_truth = load_json(workspace_root / "reports" / "runtime_truth_latest.json")
    if not isinstance(runtime_truth, dict):
        return False
    stage = runtime_truth.get("btc5_stage_readiness")
    if not isinstance(stage, dict):
        return False
    if bool(stage.get("can_trade_now")):
        return True
    if str(stage.get("trade_now_status") or "").lower() == "unblocked":
        return True
    try:
        return int(stage.get("allowed_stage", 0) or 0) >= 1
    except (TypeError, ValueError):
        return False


def _load_release_context(workspace_root: Path) -> dict[str, Any]:
    launch_packet = load_json(workspace_root / "reports" / "launch_packet_latest.json") or {}
    state_improvement = load_json(workspace_root / "reports" / "state_improvement_latest.json") or {}
    nontrading_report = load_json(workspace_root / "reports" / "nontrading_public_report.json") or {}
    nontrading_cycle = load_json(workspace_root / "reports" / "nontrading_cycle_packet.json") or {}
    action_queue = load_json(workspace_root / "reports" / "finance" / "action_queue.json") or {}

    trading_blockers: list[str] = []
    contract = launch_packet.get("contract") if isinstance(launch_packet.get("contract"), dict) else {}
    launch_state = launch_packet.get("launch_state") if isinstance(launch_packet.get("launch_state"), dict) else {}
    storage = launch_state.get("storage") if isinstance(launch_state.get("storage"), dict) else {}
    package_load = launch_state.get("package_load") if isinstance(launch_state.get("package_load"), dict) else {}
    if contract and str(contract.get("service_state") or "").lower() != "running":
        trading_blockers.append("service_not_running")
    if bool(storage.get("blocked")):
        trading_blockers.append("remote_runtime_storage_blocked")
    if package_load.get("runtime_package_loaded") is False:
        trading_blockers.append("runtime_package_load_pending")

    if state_improvement:
        metrics = state_improvement.get("metrics") if isinstance(state_improvement.get("metrics"), dict) else {}
        executed_notional = _safe_float(
            (state_improvement.get("per_venue_executed_notional_usd") or {}).get("combined_hourly"),
            _safe_float(metrics.get("executed_notional_usd"), 0.0),
        )
        conversion = _safe_float(metrics.get("candidate_to_trade_conversion"), 0.0)
        if executed_notional <= 0:
            trading_blockers.append("executed_notional_zero_across_current_cycle")
        if conversion <= 0:
            trading_blockers.append("candidate_to_trade_conversion_zero_across_current_cycle")

    executed_trading_allocation_usd = 0.0
    actions = action_queue.get("actions") if isinstance(action_queue.get("actions"), list) else []
    for action in actions:
        if not isinstance(action, dict):
            continue
        if action.get("action_key") == "allocate::fund_trading" and str(action.get("status") or "").lower() == "executed":
            executed_trading_allocation_usd = max(
                executed_trading_allocation_usd,
                _safe_float(action.get("amount_usd"), 0.0),
            )

    allocator_input = nontrading_report.get("allocator_input") if isinstance(nontrading_report.get("allocator_input"), dict) else {}
    nontrading_budget_cap = _safe_float(
        allocator_input.get("required_budget"),
        _safe_float((allocator_input.get("capacity_limits") or {}).get("budget_usd"), 0.0),
    )
    cycle_verdict = str(nontrading_cycle.get("cycle_verdict") or "").lower()
    manual_close_ready = cycle_verdict == "manual_close_ready_now"
    nontrading_blockers: list[str] = []
    if not manual_close_ready:
        for reason in (
            allocator_input.get("metadata", {}).get("blocking_reasons")
            if isinstance(allocator_input.get("metadata"), dict)
            else []
        ):
            if reason:
                nontrading_blockers.append(str(reason))

    return {
        "trading_blockers": list(dict.fromkeys(trading_blockers)),
        "executed_trading_allocation_usd": round(executed_trading_allocation_usd, 2),
        "nontrading_budget_cap_usd": round(nontrading_budget_cap, 2),
        "nontrading_blockers": list(dict.fromkeys(nontrading_blockers)),
        "manual_close_ready_now": manual_close_ready,
    }


class FinanceAllocator:
    """Constraint-aware allocator used by the finance report contract tests."""

    def __init__(self, policy: FinancePolicy):
        self.policy = policy

    def allocate(self, *, snapshot: FinanceSnapshot, candidates: list[AllocationCandidate]) -> dict[str, Any]:
        reserve_floor_usd = round(snapshot.monthly_burn_usd * self.policy.min_cash_reserve_months, 2)
        free_cash_after_floor_usd = round(max(snapshot.liquid_cash_usd - reserve_floor_usd, 0.0), 2)
        remaining_cash = free_cash_after_floor_usd
        remaining_commitment = round(
            max(self.policy.monthly_new_commitment_cap_usd - snapshot.monthly_new_commitments_usd, 0.0),
            2,
        )

        ranked_actions: list[dict[str, Any]] = []
        resource_asks: list[dict[str, Any]] = []
        bucket_totals = {bucket.value: 0.0 for bucket in FinanceBucket}
        cycle_budget_ledger = {
            "dollars": {
                "requested_usd": 0.0,
                "approved_usd": 0.0,
                "shortfall_usd": 0.0,
                "free_cash_after_floor_usd": free_cash_after_floor_usd,
                "single_action_cap_usd": round(self.policy.single_action_cap_usd, 2),
            },
            "model_minutes": {
                "requested_total": 0.0,
                "approved_total": 0.0,
                "requested_cheap": 0.0,
                "requested_escalated": 0.0,
                "approved_cheap": 0.0,
                "approved_escalated": 0.0,
                "escalated_without_value_case": 0.0,
            },
        }
        ordered_candidates = sorted(
            candidates,
            key=lambda item: item.expected_net_value_30d + item.expected_information_gain_30d,
            reverse=True,
        )

        for candidate in ordered_candidates:
            constraint_hits: list[str] = []
            requested_amount = candidate.requested_amount_usd
            if candidate.allocation_cap_usd is not None:
                requested_amount = min(requested_amount, max(candidate.allocation_cap_usd, 0.0))
            recommended_amount = min(requested_amount, remaining_cash, self.policy.single_action_cap_usd)
            model_minutes = round(max(candidate.model_minutes, 0.0), 2)
            model_value_case = _model_value_case(candidate)
            model_value_case_pass = True
            if candidate.requested_amount_usd > self.policy.single_action_cap_usd:
                constraint_hits.append("single_action_cap")
            if remaining_cash <= 0:
                constraint_hits.append("cash_after_floor")
                recommended_amount = 0.0
            if candidate.recurring_commitment_monthly_usd > remaining_commitment:
                constraint_hits.append("monthly_new_commitment_cap")
                recommended_amount = 0.0
            if _is_escalated_model_tier(candidate) and model_minutes > 0 and not _has_model_value_case(candidate):
                constraint_hits.append("missing_model_value_case")
                recommended_amount = 0.0
                model_value_case_pass = False
            if candidate.hard_blockers:
                constraint_hits.extend([item for item in candidate.hard_blockers if item not in constraint_hits])
                recommended_amount = 0.0

            remaining_cash = round(max(remaining_cash - recommended_amount, 0.0), 2)
            if recommended_amount > 0 and candidate.recurring_commitment_monthly_usd > 0:
                remaining_commitment = round(
                    max(remaining_commitment - candidate.recurring_commitment_monthly_usd, 0.0),
                    2,
                )

            bucket_totals[candidate.bucket.value] += round(recommended_amount, 2)
            shortfall_usd = round(max(requested_amount - recommended_amount, 0.0), 2)
            cycle_budget_ledger["dollars"]["requested_usd"] += round(requested_amount, 2)
            cycle_budget_ledger["dollars"]["approved_usd"] += round(recommended_amount, 2)
            cycle_budget_ledger["dollars"]["shortfall_usd"] += shortfall_usd
            cycle_budget_ledger["model_minutes"]["requested_total"] += model_minutes
            if _is_escalated_model_tier(candidate):
                cycle_budget_ledger["model_minutes"]["requested_escalated"] += model_minutes
                if not _has_model_value_case(candidate):
                    cycle_budget_ledger["model_minutes"]["escalated_without_value_case"] += model_minutes
            else:
                cycle_budget_ledger["model_minutes"]["requested_cheap"] += model_minutes
            if shortfall_usd > 0 or candidate.ask_kind != ResourceAskKind.CAPITAL:
                resource_asks.append(
                    {
                        "candidate_id": candidate.candidate_id,
                        "ask_type": candidate.ask_kind.value,
                        "shortfall_usd": shortfall_usd,
                        "model_tier": candidate.model_tier,
                        "model_minutes": model_minutes,
                        "value_case": model_value_case,
                    }
                )
            approved_model_minutes = model_minutes if recommended_amount > 0 and model_value_case_pass else 0.0
            cycle_budget_ledger["model_minutes"]["approved_total"] += approved_model_minutes
            if _is_escalated_model_tier(candidate):
                cycle_budget_ledger["model_minutes"]["approved_escalated"] += approved_model_minutes
            else:
                cycle_budget_ledger["model_minutes"]["approved_cheap"] += approved_model_minutes

            decision = "approve"
            if recommended_amount <= 0 and shortfall_usd > 0:
                decision = "ask"
            if "missing_model_value_case" in constraint_hits:
                decision = "deny"
            if candidate.hard_blockers and shortfall_usd > 0:
                decision = "ask"

            ranked_actions.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "lane": _bucket_to_lane(candidate.bucket),
                    "label": candidate.label,
                    "bucket": candidate.bucket.value,
                    "score": round(candidate.expected_net_value_30d + candidate.expected_information_gain_30d, 2),
                    "confidence_adjusted_score": round(
                        max(candidate.expected_arr_lift_30d, 0.0) * candidate.confidence
                        + max(candidate.expected_information_gain_30d, 0.0),
                        2,
                    ),
                    "recommended_amount_usd": round(recommended_amount, 2),
                    "requested_amount_usd": round(requested_amount, 2),
                    "constraint_hits": constraint_hits,
                    "ask_type": candidate.ask_kind.value,
                    "decision": decision,
                    "decision_reason": candidate.decision_reason,
                    "confidence_score": round(candidate.confidence, 4),
                    "expected_arr_lift_30d": model_value_case["expected_arr_lift_30d"],
                    "expected_arr_confidence_lift": model_value_case["expected_arr_confidence_lift"],
                    "blocker_removal_value": model_value_case["blocker_removal_value"],
                    "model_tier": candidate.model_tier,
                    "model_minutes": model_minutes,
                    "model_provider": candidate.model_provider,
                    "model_value_case": model_value_case,
                    "model_value_case_pass": model_value_case_pass,
                }
            )

        bucket_totals[FinanceBucket.KEEP_IN_CASH.value] = round(snapshot.liquid_cash_usd - sum(bucket_totals.values()), 2)
        cycle_budget_ledger["dollars"] = {
            key: round(value, 2) for key, value in cycle_budget_ledger["dollars"].items()
        }
        cycle_budget_ledger["model_minutes"] = {
            key: round(value, 2) for key, value in cycle_budget_ledger["model_minutes"].items()
        }
        return {
            "schema_version": "finance_allocation_plan.v1",
            "finance_snapshot": {
                "reserve_floor_usd": reserve_floor_usd,
                "free_cash_after_floor_usd": free_cash_after_floor_usd,
                "capital_ready_to_deploy_usd": free_cash_after_floor_usd,
                "ignored_illiquid_equity_usd": round(snapshot.illiquid_equity_usd, 2),
            },
            "ranked_actions": ranked_actions,
            "bucket_totals": bucket_totals,
            "resource_asks": resource_asks,
            "cycle_budget_ledger": cycle_budget_ledger,
        }


def _load_trading_signal(workspace_root: Path) -> tuple[float, float, list[str]]:
    runtime_truth = load_json(workspace_root / "reports" / "runtime_truth_latest.json")
    gaps: list[str] = []
    if runtime_truth is None:
        return 0.0, 0.0, ["runtime_truth_missing"]
    maker = runtime_truth.get("btc_5min_maker", {})
    guardrail = maker.get("guardrail_recommendation")
    if not isinstance(guardrail, dict):
        guardrail = {}
    baseline_pnl = float(guardrail.get("baseline_live_filled_pnl_usd", 0.0) or 0.0)
    live_rows = float(guardrail.get("baseline_live_filled_rows", 0.0) or 0.0)
    return round(baseline_pnl, 2), min(round(live_rows / 100.0, 2), 1.0), gaps


def _load_nontrading_signal(workspace_root: Path) -> tuple[float, float, list[str]]:
    report = load_json(workspace_root / "reports" / "nontrading_public_report.json")
    if report is None:
        return 0.0, 0.0, ["nontrading_public_report_missing"]
    readiness = report.get("first_dollar_readiness", {})
    expected_cash = float(readiness.get("expected_net_cash_30d", 0.0) or 0.0)
    launchable = bool(readiness.get("launchable"))
    confidence = float(readiness.get("confidence", 0.0) or 0.0)
    information_gain = round((1.0 - confidence) * (25.0 if not launchable else 5.0), 2)
    return round(expected_cash, 2), information_gain, []


def build_allocation_plan(store: FinanceStore, settings: FinanceSettings, audit_report: dict[str, Any] | None = None) -> dict[str, Any]:
    totals = build_finance_totals(store, settings)
    ranked_candidates = _load_allocation_rankings(settings.workspace_root)
    btc5_stage_green = _btc5_stage_green(settings.workspace_root)
    trading_finance_policy = load_trading_finance_policy_context(settings.workspace_root)
    release_context = _load_release_context(settings.workspace_root)

    trading_candidate = ranked_candidates.get("trading") if btc5_stage_green else None
    nontrading_candidate = ranked_candidates.get("nontrading")

    if trading_candidate:
        trading_value = round(_safe_float(trading_candidate.get("confidence_adjusted_score"), 0.0), 2)
        trading_info_gain = round(_safe_float(trading_candidate.get("expected_information_gain_30d"), 0.0), 2)
        trading_gaps: list[str] = []
        trading_rationale = (
            "Confidence-adjusted BTC5 candidate takes priority when stage gates are green."
        )
        trading_metadata = {
            "source": "reports/finance/latest.json",
            "candidate_id": trading_candidate.get("candidate_id"),
            "decision": trading_candidate.get("decision"),
            "confidence_adjusted_score": trading_value,
        }
    else:
        trading_value, trading_info_gain, trading_gaps = _load_trading_signal(settings.workspace_root)
        trading_rationale = "BTC5 runtime truth remains the highest-confidence capital deployment lane."
        trading_metadata = {"source": "reports/runtime_truth_latest.json"}

    if nontrading_candidate:
        nontrading_value = round(_safe_float(nontrading_candidate.get("confidence_adjusted_score"), 0.0), 2)
        nontrading_info_gain = round(_safe_float(nontrading_candidate.get("expected_information_gain_30d"), 0.0), 2)
        nontrading_gaps: list[str] = []
        nontrading_requested_amount = round(_safe_float(nontrading_candidate.get("requested_amount_usd"), 0.0), 2)
        nontrading_rationale = (
            "Confidence-adjusted non-trading routing runs when BTC5 stage gates are not the top opportunity."
        )
        nontrading_metadata = {
            "source": "reports/finance/latest.json",
            "candidate_id": nontrading_candidate.get("candidate_id"),
            "decision": nontrading_candidate.get("decision"),
            "confidence_adjusted_score": nontrading_value,
        }
    else:
        nontrading_value, nontrading_info_gain, nontrading_gaps = _load_nontrading_signal(settings.workspace_root)
        nontrading_requested_amount = 0.0
        nontrading_rationale = "JJ-N still offers information gain even while first-dollar gates are open."
        nontrading_metadata = {"source": "reports/nontrading_public_report.json"}
    experiments = [item for item in store.list_experiments() if item.status.lower() in {"candidate", "active"}]
    best_experiment = max(
        experiments,
        key=lambda item: (item.expected_net_value_30d + item.expected_information_gain_30d, item.budget_usd),
        default=None,
    )
    audit_findings = list((audit_report or {}).get("findings", []))
    cut_value = round(sum(float(item.get("estimated_savings_usd", 0.0) or 0.0) for item in audit_findings), 2)

    remaining_monthly_commitment = max(
        settings.monthly_new_commitment_cap_usd - store.current_month_new_commitments_usd(),
        0.0,
    )
    liquid_capacity = totals["capital_ready_to_deploy_usd"]
    capped_spend = min(liquid_capacity, settings.single_action_cap_usd)
    nontrading_budget_cap = nontrading_requested_amount or release_context["nontrading_budget_cap_usd"] or capped_spend

    buckets = [
        AllocationBucket(
            bucket="keep_in_cash",
            expected_net_value_30d=0.0,
            expected_information_gain_30d=0.0,
            score=0.0,
            recommended_amount_usd=0.0,
            monthly_commitment_usd=0.0,
            rationale="Preserve the cash floor when deployable capital is thin or signal quality is weak.",
        ),
        AllocationBucket(
            bucket="fund_trading",
            expected_net_value_30d=trading_value,
            expected_information_gain_30d=trading_info_gain,
            score=trading_value + trading_info_gain,
            recommended_amount_usd=(
                0.0
                if (
                    trading_finance_policy["hold_live_treasury"]
                    or release_context["trading_blockers"]
                    or release_context["executed_trading_allocation_usd"] > 0
                )
                else capped_spend if trading_value > 0 and liquid_capacity > 0 else 0.0
            ),
            monthly_commitment_usd=0.0,
            rationale=(
                "Keep BTC5 size flat at stage 1; do not fund the next live tranche until higher-notional validation and the explicit next-$100 hold clear."
                if trading_finance_policy["hold_live_treasury"]
                else "Treat the executed $250 trading allocation as sufficient for the current proof window; hold incremental capital until service health, package load, executed notional, and conversion all recover."
                if release_context["executed_trading_allocation_usd"] > 0
                else "Hold trading capital until service health, package load, executed notional, and candidate conversion all turn positive."
                if release_context["trading_blockers"]
                else trading_rationale
            ),
            action_type="transfer",
            destination="polymarket_runtime",
            metadata={
                **trading_metadata,
                "finance_state": trading_finance_policy["finance_state"],
                "capital_expansion_blockers": trading_finance_policy["block_reasons"],
                "capital_expansion_source": trading_finance_policy["source_artifact"],
                "release_blockers": release_context["trading_blockers"],
                "executed_trading_allocation_usd": release_context["executed_trading_allocation_usd"],
            },
        ),
        AllocationBucket(
            bucket="fund_nontrading",
            expected_net_value_30d=nontrading_value,
            expected_information_gain_30d=nontrading_info_gain,
            score=nontrading_value + nontrading_info_gain,
            recommended_amount_usd=(
                min(nontrading_budget_cap, capped_spend)
                if nontrading_info_gain > 0 and liquid_capacity > 0 and not release_context["nontrading_blockers"]
                else 0.0
            ),
            monthly_commitment_usd=0.0,
            rationale=(
                "Keep JJ-N budget at the minimum control-plane amount needed for manual-close-first execution; do not widen spend before automated checkout is healthy."
                if release_context["manual_close_ready_now"]
                else nontrading_rationale
            ),
            action_type="transfer",
            destination="jjn_control_plane",
            metadata={
                **nontrading_metadata,
                "release_blockers": release_context["nontrading_blockers"],
                "allocation_cap_usd": nontrading_budget_cap,
                "manual_close_ready_now": release_context["manual_close_ready_now"],
            },
        ),
        AllocationBucket(
            bucket="buy_tool_or_data",
            expected_net_value_30d=best_experiment.expected_net_value_30d if best_experiment else 0.0,
            expected_information_gain_30d=best_experiment.expected_information_gain_30d if best_experiment else 0.0,
            score=(
                (best_experiment.expected_net_value_30d + best_experiment.expected_information_gain_30d)
                if best_experiment
                else 0.0
            ),
            recommended_amount_usd=(
                min(best_experiment.budget_usd, settings.single_action_cap_usd, liquid_capacity)
                if best_experiment and liquid_capacity > 0
                else 0.0
            ),
            monthly_commitment_usd=(
                min(best_experiment.monthly_budget_usd, remaining_monthly_commitment)
                if best_experiment
                else 0.0
            ),
            rationale="Tools and data are funded when their expected value plus information gain is positive.",
            action_type="buy_tool_or_data",
            destination=best_experiment.name if best_experiment else "",
            metadata={"experiment_key": best_experiment.experiment_key if best_experiment else ""},
        ),
        AllocationBucket(
            bucket="cut_or_cancel",
            expected_net_value_30d=cut_value,
            expected_information_gain_30d=0.0,
            score=cut_value,
            recommended_amount_usd=0.0,
            monthly_commitment_usd=0.0,
            rationale="Recurring savings create deployable cash without weakening the reserve floor.",
            action_type="cancel_subscription",
            destination="",
            metadata={"finding_count": len(audit_findings)},
        ),
    ]
    ranked = sorted(buckets, key=lambda item: item.score, reverse=True)
    if liquid_capacity <= 0:
        ranked = sorted(ranked, key=lambda item: 1 if item.bucket == "keep_in_cash" else 0, reverse=True)

    actions: list[FinanceAction] = []
    for bucket in ranked:
        if bucket.action_type and bucket.recommended_amount_usd > 0:
            action_key = f"allocate::{bucket.bucket}"
            actions.append(
                FinanceAction(
                    action_key=action_key,
                    action_type=bucket.action_type,
                    bucket=bucket.bucket,
                    title=f"Allocate to {bucket.bucket}",
                    amount_usd=bucket.recommended_amount_usd,
                    monthly_commitment_usd=bucket.monthly_commitment_usd,
                    priority_score=bucket.score,
                    destination=bucket.destination,
                    mode_requested="live_treasury" if bucket.action_type == "transfer" else "live_spend",
                    reason=bucket.rationale,
                    rollback="Revert budget assignment if realized signal quality degrades.",
                    idempotency_key=action_key,
                    requires_whitelist=bucket.action_type == "transfer",
                    metadata=bucket.metadata,
                )
            )
            continue

        if bucket.bucket != "fund_trading":
            continue

        if not trading_finance_policy["hold_live_treasury"] and not trading_finance_policy["baseline_live_allowed"]:
            continue

        retry_in_minutes = 30
        action_status = "queued" if trading_finance_policy["baseline_live_allowed"] else "rejected"
        action_reason = (
            "Maintain BTC5 at flat stage 1 while treasury expansion remains blocked."
            if trading_finance_policy["baseline_live_allowed"]
            else "Hold BTC5 baseline live action until baseline-live policy blockers clear."
        )
        actions.append(
            FinanceAction(
                action_key="allocate::maintain_stage1_flat_size",
                action_type="maintain_stage1_flat_size",
                bucket="fund_trading",
                title="Maintain BTC5 stage 1 flat size",
                status=action_status,
                amount_usd=0.0,
                monthly_commitment_usd=0.0,
                priority_score=bucket.score,
                destination="polymarket_runtime",
                mode_requested="live_treasury",
                reason=action_reason,
                rollback="Stop the BTC5 stage-1 baseline if launch or finance truth turns blocked.",
                idempotency_key="allocate::maintain_stage1_flat_size",
                requires_whitelist=False,
                metadata={
                    **bucket.metadata,
                    "baseline_live_trading_pass": trading_finance_policy["baseline_live_allowed"],
                    "treasury_gate_pass": not trading_finance_policy["hold_live_treasury"],
                    "capital_expansion_only_hold": trading_finance_policy["hold_live_treasury"],
                    "policy_hold": not trading_finance_policy["baseline_live_allowed"],
                    "hold_reason": (
                        trading_finance_policy["reason"]
                        if trading_finance_policy["hold_live_treasury"]
                        else ",".join(trading_finance_policy["baseline_live_block_reasons"])
                    ),
                    "retry_in_minutes": retry_in_minutes,
                    "retry_at": _plus_minutes(utc_now(), retry_in_minutes),
                },
            )
        )

    gaps = trading_gaps + nontrading_gaps + list((audit_report or {}).get("gaps", []))
    return {
        "schema_version": "finance_allocation_plan.v1",
        "generated_at": utc_now(),
        "totals": totals,
        "ranked_buckets": [bucket.to_dict() for bucket in ranked],
        "recommended_actions": [action.__dict__ for action in actions],
        "gaps": gaps,
    }
