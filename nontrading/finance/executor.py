"""Executor and staged autonomy for finance actions."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from nontrading.finance.config import FinanceSettings
from nontrading.finance.models import ExecutionResult, FinanceAction, utc_now
from nontrading.finance.policy import LIVE_MODES, build_finance_totals, evaluate_rollout_gates
from nontrading.finance.store import FinanceStore

UTC = timezone.utc
LIVE_SPEND_ACTION_TYPES = {"cancel_subscription", "buy_tool_or_data"}
SPEND_ACTION_TYPES = {"transfer", "buy_tool_or_data"}


class FinanceExecutionError(RuntimeError):
    """Raised when finance execution cannot proceed in the requested mode."""


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class FinanceExecutor:
    """Runs staged finance actions under caps, gates, and whitelist policy."""

    def __init__(self, store: FinanceStore, settings: FinanceSettings):
        self.store = store
        self.settings = settings

    def _require_rollout_ready(self, mode: str) -> list[str]:
        if mode not in LIVE_MODES:
            return []
        gate_status = evaluate_rollout_gates(self.store)
        if mode == "live_spend" and not gate_status.ready_for_live_spend:
            return list(gate_status.reasons)
        if mode == "live_treasury" and not gate_status.ready_for_live_treasury:
            return list(gate_status.reasons)
        return []

    def _reject(self, action: FinanceAction, mode: str, reason: str) -> ExecutionResult:
        updated = replace(
            action,
            status="rejected",
            executed_at=utc_now(),
            metadata={**action.metadata, "last_execution_reason": reason, "last_execution_mode": mode},
        )
        self.store.upsert_action(updated)
        return ExecutionResult(
            action_key=action.action_key,
            status="rejected",
            mode=mode,
            reason=reason,
            performed=False,
            idempotency_key=action.idempotency_key,
        )

    def _simulate(self, action: FinanceAction, mode: str) -> ExecutionResult:
        updated = replace(
            action,
            status="shadowed",
            metadata={**action.metadata, "last_shadow_run_at": utc_now(), "last_execution_mode": mode},
        )
        self.store.upsert_action(updated)
        return ExecutionResult(
            action_key=action.action_key,
            status="shadowed",
            mode=mode,
            reason="shadow_only",
            performed=False,
            idempotency_key=action.idempotency_key,
        )

    def simulate_action(
        self,
        action: FinanceAction,
        *,
        requested_mode: str,
        reason: str,
        metadata: dict[str, object] | None = None,
    ) -> ExecutionResult:
        updated = replace(
            action,
            status="shadowed",
            metadata={
                **action.metadata,
                "last_shadow_run_at": utc_now(),
                "last_execution_mode": "shadow",
                "last_requested_mode": requested_mode,
                "last_execution_reason": reason,
                **(metadata or {}),
            },
        )
        self.store.upsert_action(updated)
        return ExecutionResult(
            action_key=action.action_key,
            status="shadowed",
            mode="shadow",
            reason=reason,
            performed=False,
            idempotency_key=action.idempotency_key,
            metadata=metadata or {},
        )

    def _execute_live(self, action: FinanceAction, mode: str) -> ExecutionResult:
        updated = replace(
            action,
            status="executed",
            executed_at=utc_now(),
            metadata={**action.metadata, "last_execution_mode": mode},
        )
        self.store.upsert_action(updated)
        return ExecutionResult(
            action_key=action.action_key,
            status="executed",
            mode=mode,
            reason="executed",
            performed=True,
            idempotency_key=action.idempotency_key,
        )

    def _validate_action(
        self,
        action: FinanceAction,
        mode: str,
        *,
        remaining_cash: float,
        remaining_monthly_commitment: float,
        rollout_blockers: list[str],
    ) -> str | None:
        now = _parse_time(utc_now())
        cooldown_until = _parse_time(action.cooldown_until)
        if rollout_blockers:
            return "rollout_gates_blocked:" + ",".join(sorted(set(rollout_blockers)))
        if action.amount_usd > self.settings.single_action_cap_usd:
            return "single_action_cap_exceeded"
        if action.monthly_commitment_usd > self.settings.monthly_new_commitment_cap_usd:
            return "monthly_new_commitment_cap_exceeded"
        if action.action_type in SPEND_ACTION_TYPES and action.amount_usd > 0.0 and action.amount_usd > remaining_cash:
            return (
                "reserve_floor_exceeded:"
                + f"requested={round(action.amount_usd, 2)}"
                + f",available={round(remaining_cash, 2)}"
            )
        if action.monthly_commitment_usd > remaining_monthly_commitment:
            return "monthly_commitment_budget_exhausted"
        if cooldown_until is not None and now is not None and cooldown_until > now:
            return "cooldown_active"
        if self.store.get_action_by_idempotency_key(action.idempotency_key or action.action_key):
            return "idempotency_key_already_executed"
        if mode == "shadow":
            if action.metadata.get("execution_method") == "browser_automation":
                return "open_ended_browser_automation_forbidden"
            return None
        if mode == "live_spend" and action.action_type not in LIVE_SPEND_ACTION_TYPES:
            return "action_type_not_allowed_in_live_spend"
        if action.action_type == "transfer":
            if mode != "live_treasury":
                return "transfer_requires_live_treasury"
            if action.destination.strip().lower() not in set(self.settings.whitelist):
                return "destination_not_whitelisted"
        if action.requires_whitelist and action.destination.strip().lower() not in set(self.settings.whitelist):
            return "destination_not_whitelisted"
        if action.metadata.get("execution_method") == "browser_automation":
            return "open_ended_browser_automation_forbidden"
        return None

    def preview_action(
        self,
        action: FinanceAction,
        mode: str,
        *,
        remaining_cash: float,
        remaining_monthly_commitment: float,
        rollout_blockers: list[str] | None = None,
    ) -> str | None:
        return self._validate_action(
            action,
            mode,
            remaining_cash=remaining_cash,
            remaining_monthly_commitment=remaining_monthly_commitment,
            rollout_blockers=list(rollout_blockers) if rollout_blockers is not None else self._require_rollout_ready(mode),
        )

    def execute(self, mode: str | None = None, *, action_keys: tuple[str, ...] | None = None) -> dict[str, object]:
        selected_mode = (mode or self.settings.autonomy_mode).strip().lower()
        rollout_blockers = self._require_rollout_ready(selected_mode)
        if rollout_blockers:
            raise FinanceExecutionError("rollout_gates_blocked:" + ",".join(sorted(set(rollout_blockers))))
        pending_actions = self.store.list_actions(statuses=("queued",))
        if action_keys is not None:
            selected = set(action_keys)
            pending_actions = [action for action in pending_actions if action.action_key in selected]
        totals = build_finance_totals(self.store, self.settings)
        remaining_cash = round(float(totals.get("capital_ready_to_deploy_usd", 0.0)), 2)
        remaining_monthly_commitment = round(
            max(
                self.settings.monthly_new_commitment_cap_usd - self.store.current_month_new_commitments_usd(),
                0.0,
            ),
            2,
        )
        results: list[ExecutionResult] = []
        for action in pending_actions:
            reason = self._validate_action(
                action,
                selected_mode,
                remaining_cash=remaining_cash,
                remaining_monthly_commitment=remaining_monthly_commitment,
                rollout_blockers=rollout_blockers,
            )
            if reason is not None:
                results.append(self._reject(action, selected_mode, reason))
                continue
            if selected_mode == "shadow":
                results.append(self._simulate(action, selected_mode))
                continue
            if action.action_type in SPEND_ACTION_TYPES:
                remaining_cash = round(max(remaining_cash - action.amount_usd, 0.0), 2)
            remaining_monthly_commitment = round(
                max(remaining_monthly_commitment - action.monthly_commitment_usd, 0.0),
                2,
            )
            results.append(self._execute_live(action, selected_mode))
        return {
            "schema_version": "finance_execute.v1",
            "generated_at": utc_now(),
            "mode": selected_mode,
            "results": [item.to_dict() for item in results],
            "rollout_gates": evaluate_rollout_gates(self.store).to_dict(),
        }
