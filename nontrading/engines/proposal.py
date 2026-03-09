"""Proposal stub for JJ-N Phase 0."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nontrading.crm_schema import ApprovalClass
from nontrading.crm_schema import Interaction as CRMInteraction
from nontrading.crm_schema import Opportunity as CRMOpportunity
from nontrading.models import Proposal
from nontrading.store import RevenueStore
from nontrading.telemetry import NonTradingTelemetry


@dataclass(frozen=True)
class ProposalResult:
    proposal_id: int | None
    telemetry_event_id: int | None


class ProposalEngine:
    """Phase 0: draft proposal records. Phase 1: generate scoped commercial offers."""

    def __init__(self, store: RevenueStore | None = None, telemetry: NonTradingTelemetry | None = None):
        self.store = store
        self.telemetry = telemetry

    def process(self, opportunity: CRMOpportunity) -> CRMInteraction:
        return CRMInteraction(
            id=f"{opportunity.id}:proposal",
            lead_id=opportunity.lead_id,
            engine="proposal",
            action="draft_proposal",
            approval_class=ApprovalClass.ESCALATE,
            result=f"Prepared proposal stub for {opportunity.service_type}",
        )

    @staticmethod
    def to_event(interaction: CRMInteraction) -> dict[str, Any]:
        return interaction.to_event()

    def send_proposal(self, proposal: Proposal) -> ProposalResult:
        if self.store is None or self.telemetry is None:
            raise RuntimeError("send_proposal requires store and telemetry")
        sent = self.store.create_proposal(
            Proposal(
                account_id=proposal.account_id,
                opportunity_id=proposal.opportunity_id,
                contact_id=proposal.contact_id,
                title=proposal.title,
                status="sent",
                amount=proposal.amount,
                currency=proposal.currency,
                summary=proposal.summary,
                metadata=proposal.metadata,
            )
        )
        event = self.telemetry.proposal_sent(sent)
        return ProposalResult(proposal_id=sent.id, telemetry_event_id=event.id)
