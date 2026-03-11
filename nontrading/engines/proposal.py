"""Proposal stub for JJ-N Phase 0."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nontrading.approval import ApprovalDecision, ApprovalGate
from nontrading.crm_schema import ApprovalClass
from nontrading.crm_schema import Interaction as CRMInteraction
from nontrading.crm_schema import Opportunity as CRMOpportunity
from nontrading.engines.interaction import ProcessedInteraction
from nontrading.models import Proposal
from nontrading.store import RevenueStore
from nontrading.telemetry import NonTradingTelemetry


@dataclass(frozen=True)
class ProposalResult:
    proposal_id: int | None
    telemetry_event_id: int | None


class ProposalEngine:
    """Phase 0: draft proposal records. Phase 1: generate scoped commercial offers."""

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

    def route(self, opportunity: CRMOpportunity) -> ApprovalDecision:
        if self.approval_gate is None:
            raise RuntimeError("route requires an approval gate")
        return self.approval_gate.route(self.process(opportunity))

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

    def stage_proposal(self, proposal: Proposal) -> Proposal:
        if self.store is None:
            raise RuntimeError("stage_proposal requires store")
        return self.store.create_proposal(
            Proposal(
                account_id=proposal.account_id,
                opportunity_id=proposal.opportunity_id,
                contact_id=proposal.contact_id,
                title=proposal.title,
                status=proposal.status or "draft",
                amount=proposal.amount,
                currency=proposal.currency,
                summary=proposal.summary,
                metadata=proposal.metadata,
            )
        )

    def ensure_staged_proposal(
        self,
        proposal: Proposal,
        *,
        metadata_match: dict[str, Any] | None = None,
    ) -> Proposal:
        if self.store is None:
            raise RuntimeError("ensure_staged_proposal requires store")
        existing = self.store.list_proposals(opportunity_id=proposal.opportunity_id)
        for candidate in existing:
            if metadata_match and all(candidate.metadata.get(key) == value for key, value in metadata_match.items()):
                return candidate
        if existing:
            return existing[0]
        return self.stage_proposal(proposal)

    def create_proposal_for_interaction(self, interaction: ProcessedInteraction) -> Proposal | None:
        if self.store is None or self.telemetry is None:
            raise RuntimeError("create_proposal_for_interaction requires store and telemetry")
        if not interaction.ready_for_proposal or interaction.opportunity_id is None:
            return None

        existing = self.store.list_proposals(opportunity_id=interaction.opportunity_id)
        if existing:
            return existing[0]

        opportunity = self.store.get_opportunity(interaction.opportunity_id)
        account = self.store.get_account(interaction.account_id)
        if opportunity is None or account is None:
            return None

        amount = round((500.0 + min(max(opportunity.score, 0.0), 100.0) * 20.0) / 50.0) * 50.0
        result = self.send_proposal(
            Proposal(
                account_id=interaction.account_id,
                opportunity_id=interaction.opportunity_id,
                contact_id=interaction.contact_id,
                title=f"{opportunity.offer_name or 'Website Growth Audit'} Proposal",
                amount=max(500.0, min(amount, 2500.0)),
                summary=(
                    f"Five-day audit for {account.name} covering acquisition friction, conversion blockers, "
                    "and analytics instrumentation."
                ),
                metadata={
                    "classification": interaction.classification,
                    "simulated": True,
                    "source_message_id": interaction.source_message_id,
                    "fit_score": opportunity.score,
                },
            )
        )
        return self.store.get_proposal(result.proposal_id or 0)
