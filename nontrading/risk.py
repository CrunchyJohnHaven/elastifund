"""Risk rails for the non-trading revenue agent."""

from __future__ import annotations

from dataclasses import dataclass, field

from nontrading.config import RevenueAgentSettings
from nontrading.models import Campaign, RiskEvent
from nontrading.store import RevenueStore


@dataclass(frozen=True)
class DeliverabilityMetrics:
    total_sends: int
    complaint_events: int
    bounce_events: int
    complaint_rate: float
    bounce_rate: float
    status: str


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    reason: str = ""
    remaining_quota: int = 0
    metrics: DeliverabilityMetrics | None = None
    metadata: dict[str, float | int | str] = field(default_factory=dict)


class RevenueRiskManager:
    """Applies kill-switch, quota, and deliverability gates before sending."""

    def __init__(self, store: RevenueStore, settings: RevenueAgentSettings):
        self.store = store
        self.settings = settings

    def deliverability_metrics(self) -> DeliverabilityMetrics:
        total_sends = self.store.count_total_sends_today()
        complaint_events = self.store.count_send_events_today("complaint")
        bounce_events = self.store.count_send_events_today("bounce")
        denominator = max(total_sends, 1)
        complaint_rate = complaint_events / denominator
        bounce_rate = bounce_events / denominator

        if complaint_rate >= self.settings.complaint_rate_red or bounce_rate >= self.settings.bounce_rate_red:
            status = "red"
        elif complaint_rate >= self.settings.complaint_rate_yellow or bounce_rate >= self.settings.bounce_rate_yellow:
            status = "yellow"
        else:
            status = "green"

        self.store.update_deliverability_status(status)
        return DeliverabilityMetrics(
            total_sends=total_sends,
            complaint_events=complaint_events,
            bounce_events=bounce_events,
            complaint_rate=complaint_rate,
            bounce_rate=bounce_rate,
            status=status,
        )

    def evaluate_engine(self, engine_name: str) -> RiskDecision:
        state = self.store.get_agent_state()
        if state.global_kill_switch:
            return RiskDecision(allowed=False, reason="global_kill_switch")

        engine_state = self.store.get_engine_state(engine_name)
        if engine_state is not None and engine_state.kill_switch_active:
            return RiskDecision(
                allowed=False,
                reason="engine_kill_switch",
                metadata={"engine_name": engine_name},
            )

        return RiskDecision(allowed=True)

    def evaluate_campaign(self, campaign: Campaign, *, engine_name: str = "outbound_followup") -> RiskDecision:
        engine_decision = self.evaluate_engine(engine_name)
        if not engine_decision.allowed:
            return engine_decision

        if campaign.kill_switch_active:
            return RiskDecision(allowed=False, reason="campaign_kill_switch")

        metrics = self.deliverability_metrics()
        if metrics.status == "red":
            self.store.record_risk_event(
                RiskEvent(
                    scope="agent",
                    severity="critical",
                    event_type="deliverability_gate_red",
                    detail=(
                        f"Complaint rate={metrics.complaint_rate:.4f}, "
                        f"bounce rate={metrics.bounce_rate:.4f}"
                    ),
                )
            )
            return RiskDecision(allowed=False, reason="deliverability_gate_red", metrics=metrics)

        limit = min(campaign.daily_send_quota, self.settings.daily_send_quota)
        used = self.store.count_campaign_sends_today(campaign.id or 0)
        remaining = max(limit - used, 0)
        if remaining <= 0:
            return RiskDecision(
                allowed=False,
                reason="daily_quota_exhausted",
                remaining_quota=0,
                metrics=metrics,
                metadata={"used": used, "limit": limit},
            )

        return RiskDecision(
            allowed=True,
            remaining_quota=remaining,
            metrics=metrics,
            metadata={"used": used, "limit": limit},
        )

    def trigger_global_kill(self, reason: str) -> None:
        self.store.set_global_kill_switch(True, reason)
        self.store.record_risk_event(
            RiskEvent(
                scope="agent",
                severity="critical",
                event_type="global_kill_switch",
                detail=reason,
            )
        )

    def trigger_engine_kill(self, engine_name: str, reason: str) -> None:
        self.store.set_engine_kill_switch(engine_name, True, reason)
        self.store.record_risk_event(
            RiskEvent(
                scope="engine",
                scope_id=engine_name,
                severity="critical",
                event_type="engine_kill_switch",
                detail=reason,
                metadata={"engine_name": engine_name},
            )
        )
