"""Phase 0 opportunity scoring and registry helpers for JJ-N."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from nontrading.crm_schema import Lead as CRMLead
from nontrading.crm_schema import LeadStatus
from nontrading.crm_schema import Opportunity as CRMOpportunity
from nontrading.crm_schema import utc_now
from nontrading.models import Account, Contact, Opportunity as StoredOpportunity, normalize_domain
from nontrading.store import RevenueStore

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
LEAD_METADATA_KEY = "registry_lead"
OPPORTUNITY_METADATA_KEY = "registry_opportunity"


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
    """Scores opportunities and tracks Phase 0 registry state in memory or SQLite."""

    def __init__(
        self,
        threshold: float = DEFAULT_PHASE0_THRESHOLD,
        *,
        store: RevenueStore | None = None,
    ):
        self.threshold = threshold
        self.store = store
        self.leads: dict[str, CRMLead] = {}
        self.opportunities: dict[str, CRMOpportunity] = {}
        self.events: list[dict[str, Any]] = []
        if self.store is not None:
            self._hydrate_from_store()

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
        candidates: Iterable[tuple[str, OpportunityScoreInput]] | None = None,
    ) -> list[tuple[str, OpportunityAssessment]]:
        if candidates is None:
            candidates = [
                (
                    opportunity.id,
                    OpportunityScoreInput(**self._registry_input_for_opportunity(opportunity)),
                )
                for opportunity in self.rank_opportunities()
            ]
        scored = [(name, self.score(score_input)) for name, score_input in candidates]
        return sorted(scored, key=lambda item: item[1].total_score, reverse=True)

    def apply(self, opportunity: StoredOpportunity, score_input: OpportunityScoreInput) -> StoredOpportunity:
        assessment = self.score(score_input)
        scored = StoredOpportunity(
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
        if self.store is None:
            return scored
        stored, _ = self.store.upsert_opportunity(scored)
        return stored

    def add_lead(self, lead: CRMLead) -> CRMLead:
        stored_lead = lead
        if self.store is not None:
            account, _ = self.store.upsert_account(self._account_from_lead(lead))
            self.store.upsert_contact(self._contact_from_lead(account.id or 0, lead))
            contact = self._primary_contact_for_account(account.id or 0)
            stored_lead = self._lead_from_store(account, contact) or lead
        self.leads[stored_lead.id] = stored_lead
        self.events.append(stored_lead.to_event())
        return stored_lead

    def add_opportunity(self, opportunity: CRMOpportunity) -> CRMOpportunity:
        opportunity.compute_score()
        stored_opportunity = opportunity
        if self.store is not None:
            account = self._account_for_lead_id(opportunity.lead_id)
            if account is None:
                account, _ = self.store.upsert_account(
                    Account(
                        name=f"Lead {opportunity.lead_id}",
                        status="research",
                        metadata={
                            LEAD_METADATA_KEY: {
                                "id": opportunity.lead_id,
                                "source": "synthetic",
                                "status": LeadStatus.RESEARCH.value,
                                "fit_score": 0.0,
                                "opportunity_score": 0.0,
                                "created_at": utc_now(),
                                "updated_at": utc_now(),
                                "notes": "",
                                "tags": [],
                                "contact_name": "",
                                "contact_email": "",
                                "metadata": {},
                            }
                        },
                    )
                )
            persisted, _ = self.store.upsert_opportunity(self._stored_opportunity_from_crm(account.id or 0, opportunity))
            stored_opportunity = self._crm_opportunity_from_store(persisted)
        self.opportunities[stored_opportunity.id] = stored_opportunity
        self.events.append(stored_opportunity.to_event())
        return stored_opportunity

    def rank_opportunities(self) -> list[CRMOpportunity]:
        if self.store is not None:
            self.opportunities = {
                opportunity.id: opportunity
                for opportunity in (
                    self._crm_opportunity_from_store(item) for item in self.store.list_opportunities()
                )
            }
        return sorted(
            self.opportunities.values(),
            key=lambda opportunity: opportunity.composite_score,
            reverse=True,
        )

    def get_lead(self, lead_id: str) -> CRMLead | None:
        if self.store is not None and lead_id not in self.leads:
            self._hydrate_from_store()
        return self.leads.get(lead_id)

    def update_lead_status(self, lead_id: str, status: LeadStatus) -> CRMLead | None:
        lead = self.get_lead(lead_id)
        if lead is None:
            return None
        lead.status = status
        lead.updated_at = utc_now()
        if self.store is not None:
            account, _ = self.store.upsert_account(self._account_from_lead(lead))
            self.store.upsert_contact(self._contact_from_lead(account.id or 0, lead))
            contact = self._primary_contact_for_account(account.id or 0)
            lead = self._lead_from_store(account, contact) or lead
        self.events.append(lead.to_event())
        self.leads[lead.id] = lead
        return lead

    def flush_events(self) -> list[dict[str, Any]]:
        events = list(self.events)
        self.events.clear()
        return events

    def _hydrate_from_store(self) -> None:
        if self.store is None:
            return
        leads: dict[str, CRMLead] = {}
        for account in self.store.list_accounts():
            lead = self._lead_from_store(account, self._primary_contact_for_account(account.id or 0))
            if lead is not None:
                leads[lead.id] = lead
        self.leads = leads
        self.opportunities = {
            opportunity.id: opportunity
            for opportunity in (
                self._crm_opportunity_from_store(item) for item in self.store.list_opportunities()
            )
        }

    def _lead_from_store(self, account: Account, contact: Contact | None) -> CRMLead | None:
        payload = account.metadata.get(LEAD_METADATA_KEY)
        if not isinstance(payload, dict) or not payload.get("id"):
            return None
        contact_name = contact.full_name if contact is not None else str(payload.get("contact_name", ""))
        contact_email = contact.email if contact is not None else str(payload.get("contact_email", ""))
        return CRMLead(
            id=str(payload["id"]),
            company=account.name,
            contact_name=contact_name,
            contact_email=contact_email,
            source=str(payload.get("source", "manual")),
            status=LeadStatus(str(payload.get("status", account.status or LeadStatus.RESEARCH.value))),
            fit_score=float(payload.get("fit_score", 0.0)),
            opportunity_score=float(payload.get("opportunity_score", 0.0)),
            created_at=str(payload.get("created_at", account.created_at or utc_now())),
            updated_at=str(payload.get("updated_at", account.updated_at or utc_now())),
            notes=str(payload.get("notes", account.notes)),
            tags=list(payload.get("tags", [])),
            metadata=dict(payload.get("metadata", {})),
        )

    def _crm_opportunity_from_store(self, opportunity: StoredOpportunity) -> CRMOpportunity:
        payload = opportunity.metadata.get(OPPORTUNITY_METADATA_KEY, {})
        if not isinstance(payload, dict):
            payload = {}
        return CRMOpportunity(
            id=str(payload.get("id", opportunity.id or "")),
            lead_id=str(payload.get("lead_id", "")),
            service_type=str(payload.get("service_type", opportunity.name)),
            estimated_value_usd=float(payload.get("estimated_value_usd", opportunity.estimated_value)),
            time_to_first_dollar_days=int(payload.get("time_to_first_dollar_days", 30)),
            gross_margin_pct=float(payload.get("gross_margin_pct", 0.0)),
            automation_fraction=float(payload.get("automation_fraction", 0.0)),
            data_exhaust_score=float(payload.get("data_exhaust_score", 0.0)),
            compliance_simplicity=float(payload.get("compliance_simplicity", 0.0)),
            capital_required_usd=float(payload.get("capital_required_usd", 0.0)),
            sales_cycle_days=int(payload.get("sales_cycle_days", 30)),
            composite_score=float(opportunity.score),
            status=str(payload.get("status", opportunity.status)),
            created_at=str(payload.get("created_at", opportunity.created_at or utc_now())),
            metadata=dict(payload.get("metadata", {})),
        )

    def _account_from_lead(self, lead: CRMLead) -> Account:
        domain = ""
        if isinstance(lead.metadata, dict):
            domain = str(lead.metadata.get("domain", "")).strip()
        if not domain and "@" in lead.contact_email:
            domain = lead.contact_email.split("@", 1)[1]
        return Account(
            name=lead.company,
            domain=normalize_domain(domain),
            status=lead.status.value,
            notes=lead.notes,
            metadata={
                LEAD_METADATA_KEY: {
                    "id": lead.id,
                    "source": lead.source,
                    "status": lead.status.value,
                    "fit_score": lead.fit_score,
                    "opportunity_score": lead.opportunity_score,
                    "created_at": lead.created_at,
                    "updated_at": lead.updated_at,
                    "notes": lead.notes,
                    "tags": list(lead.tags),
                    "contact_name": lead.contact_name,
                    "contact_email": lead.contact_email,
                    "metadata": dict(lead.metadata),
                }
            },
        )

    def _contact_from_lead(self, account_id: int, lead: CRMLead) -> Contact:
        return Contact(
            account_id=account_id,
            full_name=lead.contact_name,
            email=lead.contact_email,
            role="primary_contact",
            metadata={"registry_lead_id": lead.id},
        )

    def _stored_opportunity_from_crm(self, account_id: int, opportunity: CRMOpportunity) -> StoredOpportunity:
        stored_name = f"{opportunity.service_type}:{opportunity.id}" if opportunity.id else opportunity.service_type
        return StoredOpportunity(
            account_id=account_id,
            name=stored_name,
            offer_name=opportunity.service_type,
            stage=opportunity.status,
            status=opportunity.status,
            score=opportunity.composite_score,
            estimated_value=opportunity.estimated_value_usd,
            metadata={
                OPPORTUNITY_METADATA_KEY: {
                    "id": opportunity.id,
                    "lead_id": opportunity.lead_id,
                    "service_type": opportunity.service_type,
                    "estimated_value_usd": opportunity.estimated_value_usd,
                    "time_to_first_dollar_days": opportunity.time_to_first_dollar_days,
                    "gross_margin_pct": opportunity.gross_margin_pct,
                    "automation_fraction": opportunity.automation_fraction,
                    "data_exhaust_score": opportunity.data_exhaust_score,
                    "compliance_simplicity": opportunity.compliance_simplicity,
                    "capital_required_usd": opportunity.capital_required_usd,
                    "sales_cycle_days": opportunity.sales_cycle_days,
                    "status": opportunity.status,
                    "created_at": opportunity.created_at,
                    "metadata": dict(opportunity.metadata),
                }
            },
        )

    def _account_for_lead_id(self, lead_id: str) -> Account | None:
        if self.store is None:
            return None
        for account in self.store.list_accounts():
            payload = account.metadata.get(LEAD_METADATA_KEY)
            if isinstance(payload, dict) and str(payload.get("id", "")) == lead_id:
                return account
        return None

    def _primary_contact_for_account(self, account_id: int) -> Contact | None:
        if self.store is None:
            return None
        contacts = self.store.list_contacts(account_id=account_id)
        return contacts[0] if contacts else None

    @staticmethod
    def _registry_input_for_opportunity(opportunity: CRMOpportunity) -> dict[str, float]:
        return {
            "time_to_first_dollar": max(0.0, min(1.0, 1.0 / max(opportunity.time_to_first_dollar_days, 1))),
            "gross_margin": max(0.0, min(1.0, opportunity.gross_margin_pct)),
            "automation_fraction": max(0.0, min(1.0, opportunity.automation_fraction)),
            "data_exhaust": max(0.0, min(1.0, opportunity.data_exhaust_score)),
            "compliance_simplicity": max(0.0, min(1.0, opportunity.compliance_simplicity)),
            "capital_required": max(0.0, min(1.0, 1.0 / max(opportunity.capital_required_usd, 1.0))),
            "sales_cycle_length": max(0.0, min(1.0, 1.0 / max(opportunity.sales_cycle_days, 1))),
        }
