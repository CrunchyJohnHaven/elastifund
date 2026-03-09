"""Account intelligence stub for JJ-N Phase 0."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nontrading.crm_schema import ApprovalClass
from nontrading.crm_schema import Interaction as CRMInteraction
from nontrading.crm_schema import Lead as CRMLead
from nontrading.models import Account
from nontrading.store import RevenueStore
from nontrading.telemetry import NonTradingTelemetry


@dataclass(frozen=True)
class AccountResearchResult:
    account: Account
    telemetry_event_id: int | None


class AccountIntelligenceEngine:
    """Phase 0: stage research actions. Phase 1: enrich targets from live sources."""

    def __init__(self, store: RevenueStore | None = None, telemetry: NonTradingTelemetry | None = None):
        self.store = store
        self.telemetry = telemetry

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
