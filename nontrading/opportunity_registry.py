"""Phase 0 opportunity scoring and registry helpers for JJ-N."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from nontrading.crm_schema import Lead as CRMLead
from nontrading.crm_schema import LeadStatus
from nontrading.crm_schema import Opportunity as CRMOpportunity
from nontrading.crm_schema import utc_now
from nontrading.models import Opportunity

CRITERION_WEIGHTS = {
    "time_to_first_dollar": 0.25,
    "gross_margin": 0.20,
    "automation_fraction": 0.20,
    "data_exhaust": 0.15,
    "compliance_simplicity": 0.10,
    "capital_required": 0.05,
    "sales_cycle_length": 0.05,
}

DEFAULT_PHASE0_THRESHOLD = 70.0


@dataclass(frozen=True)
class OpportunityScoreInput:
    time_to_first_dollar: float
    gross_margin: float
    automation_fraction: float
    data_exhaust: float
    compliance_simplicity: float
    capital_required: float
    sales_cycle_length: float

    def as_dict(self) -> dict[str, float]:
        return {
            "time_to_first_dollar": self.time_to_first_dollar,
            "gross_margin": self.gross_margin,
            "automation_fraction": self.automation_fraction,
            "data_exhaust": self.data_exhaust,
            "compliance_simplicity": self.compliance_simplicity,
            "capital_required": self.capital_required,
            "sales_cycle_length": self.sales_cycle_length,
        }


@dataclass(frozen=True)
class OpportunityAssessment:
    total_score: float
    threshold: float
    decision: str
    weighted_breakdown: dict[str, float]
    normalized_inputs: dict[str, float]


class OpportunityRegistry:
    """Scores opportunities and tracks the in-memory Phase 0 registry."""

    def __init__(self, threshold: float = DEFAULT_PHASE0_THRESHOLD):
        self.threshold = threshold
        self.leads: dict[str, CRMLead] = {}
        self.opportunities: dict[str, CRMOpportunity] = {}
        self.events: list[dict[str, Any]] = []

    def score(self, score_input: OpportunityScoreInput) -> OpportunityAssessment:
        values = score_input.as_dict()
        for criterion, value in values.items():
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{criterion} must be between 0.0 and 1.0")

        weighted_breakdown = {
            criterion: round(value * CRITERION_WEIGHTS[criterion] * 100.0, 2)
            for criterion, value in values.items()
        }
        total_score = round(sum(weighted_breakdown.values()), 2)
        decision = "advance" if total_score >= self.threshold else "research_only"
        return OpportunityAssessment(
            total_score=total_score,
            threshold=self.threshold,
            decision=decision,
            weighted_breakdown=weighted_breakdown,
            normalized_inputs=values,
        )

    def rank(
        self,
        candidates: Iterable[tuple[str, OpportunityScoreInput]],
    ) -> list[tuple[str, OpportunityAssessment]]:
        scored = [(name, self.score(score_input)) for name, score_input in candidates]
        return sorted(scored, key=lambda item: item[1].total_score, reverse=True)

    def apply(self, opportunity: Opportunity, score_input: OpportunityScoreInput) -> Opportunity:
        assessment = self.score(score_input)
        return Opportunity(
            id=opportunity.id,
            account_id=opportunity.account_id,
            name=opportunity.name,
            offer_name=opportunity.offer_name,
            stage=opportunity.stage,
            status=opportunity.status,
            score=assessment.total_score,
            score_breakdown=assessment.weighted_breakdown,
            estimated_value=opportunity.estimated_value,
            currency=opportunity.currency,
            next_action=opportunity.next_action,
            metadata={
                **opportunity.metadata,
                "registry_decision": assessment.decision,
                "registry_inputs": assessment.normalized_inputs,
            },
            created_at=opportunity.created_at,
            updated_at=opportunity.updated_at,
        )

    def add_lead(self, lead: CRMLead) -> CRMLead:
        self.leads[lead.id] = lead
        self.events.append(lead.to_event())
        return lead

    def add_opportunity(self, opportunity: CRMOpportunity) -> CRMOpportunity:
        opportunity.compute_score()
        self.opportunities[opportunity.id] = opportunity
        self.events.append(opportunity.to_event())
        return opportunity

    def rank_opportunities(self) -> list[CRMOpportunity]:
        return sorted(
            self.opportunities.values(),
            key=lambda opportunity: opportunity.composite_score,
            reverse=True,
        )

    def get_lead(self, lead_id: str) -> CRMLead | None:
        return self.leads.get(lead_id)

    def update_lead_status(self, lead_id: str, status: LeadStatus) -> CRMLead | None:
        lead = self.leads.get(lead_id)
        if lead is None:
            return None
        lead.status = status
        lead.updated_at = utc_now()
        self.events.append(lead.to_event())
        return lead

    def flush_events(self) -> list[dict[str, Any]]:
        events = list(self.events)
        self.events.clear()
        return events
