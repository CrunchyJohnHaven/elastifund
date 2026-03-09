"""Learning stub for JJ-N Phase 0."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nontrading.approval import ApprovalDecision, ApprovalGate
from nontrading.crm_schema import ApprovalClass
from nontrading.crm_schema import Interaction as CRMInteraction
from nontrading.crm_schema import Opportunity as CRMOpportunity
from nontrading.models import Outcome, Proposal
from nontrading.store import RevenueStore
from nontrading.telemetry import NonTradingTelemetry


@dataclass(frozen=True)
class LearningResult:
    outcome_id: int | None
    telemetry_event_id: int | None


class LearningEngine:
    """Phase 0: log learning events. Phase 1: revise playbooks from outcomes."""

    def __init__(
        self,
        store: RevenueStore | None = None,
        telemetry: NonTradingTelemetry | None = None,
        approval_gate: ApprovalGate | None = None,
    ):
        self.store = store
        self.telemetry = telemetry
        self.approval_gate = approval_gate

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

    def route(self, opportunity: CRMOpportunity) -> ApprovalDecision:
        if self.approval_gate is None:
            raise RuntimeError("route requires an approval gate")
        return self.approval_gate.route(self.process(opportunity))

    def record_outcome(self, outcome: Outcome) -> LearningResult:
        if self.store is None or self.telemetry is None:
            raise RuntimeError("record_outcome requires store and telemetry")
        stored = self.store.create_outcome(outcome)
        event = self.telemetry.outcome_recorded(stored)
        return LearningResult(outcome_id=stored.id, telemetry_event_id=event.id)

    def evaluate_cycle(
        self,
        proposals: list[Proposal],
        *,
        simulate: bool = False,
    ) -> list[Outcome]:
        if self.store is None or self.telemetry is None:
            raise RuntimeError("evaluate_cycle requires store and telemetry")
        if not simulate:
            return []

        outcomes: list[Outcome] = []
        for proposal in proposals:
            if proposal.id is None:
                continue
            if any(existing.proposal_id == proposal.id for existing in self.store.list_outcomes(opportunity_id=proposal.opportunity_id)):
                continue
            fit_score = float(proposal.metadata.get("fit_score", 0.0))
            won = bool(proposal.metadata.get("simulated")) and fit_score >= 95.0
            result = self.record_outcome(
                Outcome(
                    account_id=proposal.account_id,
                    opportunity_id=proposal.opportunity_id,
                    proposal_id=proposal.id,
                    status="simulated_won" if won else "simulated_open",
                    revenue=proposal.amount if won else 0.0,
                    gross_margin=round(proposal.amount * 0.7, 2) if won else 0.0,
                    summary="Synthetic pipeline outcome recorded during dry-run execution.",
                    metadata={
                        "simulated": True,
                        "fit_score": fit_score,
                    },
                )
            )
            stored = self.store.get_outcome(result.outcome_id or 0)
            if stored is not None:
                outcomes.append(stored)
        return outcomes
