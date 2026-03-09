"""Learning stub for JJ-N Phase 0."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nontrading.crm_schema import ApprovalClass
from nontrading.crm_schema import Interaction as CRMInteraction
from nontrading.crm_schema import Opportunity as CRMOpportunity
from nontrading.models import Outcome
from nontrading.store import RevenueStore
from nontrading.telemetry import NonTradingTelemetry


@dataclass(frozen=True)
class LearningResult:
    outcome_id: int | None
    telemetry_event_id: int | None


class LearningEngine:
    """Phase 0: log learning events. Phase 1: revise playbooks from outcomes."""

    def __init__(self, store: RevenueStore | None = None, telemetry: NonTradingTelemetry | None = None):
        self.store = store
        self.telemetry = telemetry

    def process(self, opportunity: CRMOpportunity) -> CRMInteraction:
        return CRMInteraction(
            id=f"{opportunity.id}:learning",
            lead_id=opportunity.lead_id,
            engine="learning",
            action="record_outcome",
            approval_class=ApprovalClass.AUTO,
            result=f"Learning event staged for {opportunity.service_type}",
        )

    @staticmethod
    def to_event(interaction: CRMInteraction) -> dict[str, Any]:
        return interaction.to_event()

    def record_outcome(self, outcome: Outcome) -> LearningResult:
        if self.store is None or self.telemetry is None:
            raise RuntimeError("record_outcome requires store and telemetry")
        stored = self.store.create_outcome(outcome)
        event = self.telemetry.outcome_recorded(stored)
        return LearningResult(outcome_id=stored.id, telemetry_event_id=event.id)
