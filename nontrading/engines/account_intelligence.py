"""Account intelligence stub for JJ-N Phase 0."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nontrading.approval import ApprovalDecision, ApprovalGate
from nontrading.campaigns.policies import evaluate_lead_policy, is_personal_email_domain
from nontrading.config import RevenueAgentSettings
from nontrading.crm_schema import ApprovalClass
from nontrading.crm_schema import Interaction as CRMInteraction
from nontrading.crm_schema import Lead as CRMLead
from nontrading.models import Account, Campaign, Contact, Lead, Opportunity
from nontrading.store import RevenueStore
from nontrading.telemetry import NonTradingTelemetry


@dataclass(frozen=True)
class AccountResearchResult:
    account: Account
    telemetry_event_id: int | None


@dataclass(frozen=True)
class LeadResearchResult:
    lead: Lead
    account: Account
    contact: Contact
    opportunity: Opportunity
    fit_score: float
    qualified: bool
    reasons: tuple[str, ...]
    score_breakdown: dict[str, float]
    telemetry_event_id: int | None


class AccountIntelligenceEngine:
    """Phase 0: stage research actions. Phase 1: enrich targets from live sources."""

    def __init__(
        self,
        store: RevenueStore | None = None,
        telemetry: NonTradingTelemetry | None = None,
        approval_gate: ApprovalGate | None = None,
    ):
        self.store = store
        self.telemetry = telemetry
        self.approval_gate = approval_gate

    def process(self, lead: CRMLead) -> CRMInteraction:
        return CRMInteraction(
            id=f"{lead.id}:account-intelligence",
            lead_id=lead.id,
            engine="account_intelligence",
            action="research_account",
            approval_class=ApprovalClass.AUTO,
            result=f"Researched {lead.company}",
        )

    @staticmethod
    def to_event(interaction: CRMInteraction) -> dict[str, Any]:
        return interaction.to_event()

    def route(self, lead: CRMLead) -> ApprovalDecision:
        if self.approval_gate is None:
            raise RuntimeError("route requires an approval gate")
        return self.approval_gate.route(self.process(lead))

    def research_account(self, account: Account, *, source: str = "manual", notes: str = "") -> AccountResearchResult:
        if self.store is None or self.telemetry is None:
            raise RuntimeError("store-backed account research requires store and telemetry")
        enriched_account = Account(
            id=account.id,
            name=account.name,
            domain=account.domain,
            industry=account.industry,
            website_url=account.website_url,
            status="researched",
            notes=notes or account.notes,
            metadata={**account.metadata, "research_source": source},
            created_at=account.created_at,
            updated_at=account.updated_at,
        )
        stored, _ = self.store.upsert_account(enriched_account)
        event = self.telemetry.account_researched(stored, source=source, notes=notes)
        return AccountResearchResult(account=stored, telemetry_event_id=event.id)

    def research_lead(
        self,
        lead: Lead,
        *,
        campaign: Campaign,
        settings: RevenueAgentSettings,
        qualification_threshold: float,
        offer_name: str = "Website Growth Audit",
    ) -> LeadResearchResult:
        if self.store is None or self.telemetry is None:
            raise RuntimeError("lead research requires store and telemetry")

        domain = lead.email.partition("@")[2].strip().lower()
        company_name = lead.company_name.strip() or domain or lead.email
        policy = evaluate_lead_policy(lead, campaign, settings)
        personal_domain = is_personal_email_domain(lead.email, settings.personal_email_domains)
        score_breakdown = {
            "policy_score": min(policy.score, 60.0),
            "company_name_present": 10.0 if lead.company_name.strip() else 0.0,
            "business_domain": 10.0 if domain and not personal_domain else 0.0,
            "explicit_opt_in": 10.0 if lead.explicit_opt_in else 0.0,
            "manual_source": 5.0 if lead.source.startswith("manual") else 0.0,
            "allowed_country": 5.0 if settings.country_allowed(lead.country_code) else 0.0,
        }
        fit_score = round(min(sum(score_breakdown.values()), 100.0), 2)
        qualified = policy.allowed and fit_score >= qualification_threshold

        account_result = self.research_account(
            Account(
                name=company_name,
                domain="" if personal_domain else domain,
                industry=str(lead.metadata.get("industry", "")).strip(),
                website_url=str(lead.metadata.get("website_url", "")).strip(),
                status="researched" if qualified else "researching",
                notes="Qualified for outreach." if qualified else "Research lane only.",
                metadata={
                    "lead_id": lead.id,
                    "lead_email": lead.email_normalized,
                    "fit_score": fit_score,
                    "score_breakdown": score_breakdown,
                    "policy_reasons": list(policy.reasons),
                    "source": lead.source,
                },
            ),
            source=lead.source,
            notes="qualified" if qualified else "research_only",
        )
        account = account_result.account
        contact, _ = self.store.upsert_contact(
            Contact(
                account_id=account.id or 0,
                full_name=self._contact_name(lead),
                email=lead.email,
                title=str(lead.metadata.get("title", "")).strip(),
                role=str(lead.metadata.get("role", "")).strip(),
                metadata={"lead_id": lead.id},
            )
        )
        opportunity = self._get_or_create_opportunity(
            account_id=account.id or 0,
            offer_name=offer_name,
            fit_score=fit_score,
            qualified=qualified,
            lead=lead,
            policy_reasons=policy.reasons,
        )
        return LeadResearchResult(
            lead=lead,
            account=account,
            contact=contact,
            opportunity=opportunity,
            fit_score=fit_score,
            qualified=qualified,
            reasons=policy.reasons,
            score_breakdown=score_breakdown,
            telemetry_event_id=account_result.telemetry_event_id,
        )

    def _get_or_create_opportunity(
        self,
        *,
        account_id: int,
        offer_name: str,
        fit_score: float,
        qualified: bool,
        lead: Lead,
        policy_reasons: tuple[str, ...],
    ) -> Opportunity:
        opportunity_name = f"{offer_name} for {lead.company_name.strip() or lead.email.partition('@')[2]}"
        for existing in self.store.list_opportunities(account_id=account_id):
            if existing.name == opportunity_name and existing.offer_name == offer_name:
                return existing
        return self.store.create_opportunity(
            Opportunity(
                account_id=account_id,
                name=opportunity_name,
                offer_name=offer_name,
                stage="qualified" if qualified else "research",
                status="open" if qualified else "research_only",
                score=fit_score,
                score_breakdown={"fit_score": fit_score},
                estimated_value=500.0 + (fit_score / 100.0) * 2000.0,
                next_action="stage_outreach" if qualified else "collect_more_signal",
                metadata={
                    "lead_id": lead.id,
                    "lead_email": lead.email_normalized,
                    "policy_reasons": list(policy_reasons),
                    "explicit_opt_in": lead.explicit_opt_in,
                },
            )
        )

    @staticmethod
    def _contact_name(lead: Lead) -> str:
        explicit = str(lead.metadata.get("contact_name", "")).strip()
        if explicit:
            return explicit
        localpart = lead.email.partition("@")[0].replace(".", " ").replace("_", " ").strip()
        if not localpart:
            return lead.company_name.strip() or "Unknown Contact"
        return " ".join(part.capitalize() for part in localpart.split())
