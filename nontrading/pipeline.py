"""Sequential JJ-N pipeline that wires the five engines into one cycle."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any

from nontrading.approval import ApprovalGate
from nontrading.compliance import ComplianceGuard
from nontrading.config import RevenueAgentSettings
from nontrading.email.sender import BaseSender
from nontrading.engines import (
    AccountIntelligenceEngine,
    InteractionEngine,
    LearningEngine,
    OutreachEngine,
    ProposalEngine,
)
from nontrading.models import Campaign, Lead, utc_now
from nontrading.risk import RevenueRiskManager
from nontrading.store import RevenueStore
from nontrading.telemetry import NonTradingTelemetry

logger = logging.getLogger("nontrading.pipeline")

PIPELINE_ENGINE = "revenue_pipeline"
QUALIFICATION_THRESHOLD = 70.0
SUCCESSFUL_DELIVERY_STATUSES = {"dry_run", "provider_accepted", "sent"}


@dataclass(frozen=True)
class CycleReport:
    cycle_id: str
    started_at: str
    completed_at: str
    status: str = "completed"
    reason: str = ""
    blocked_stage: str = ""
    scanned_leads: int = 0
    suppressed_leads: int = 0
    skipped_existing: int = 0
    accounts_researched: int = 0
    qualified_accounts: int = 0
    outreach_attempted: int = 0
    outreach_sent: int = 0
    approval_pending: int = 0
    replies_recorded: int = 0
    meetings_booked: int = 0
    proposals_sent: int = 0
    outcomes_recorded: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RevenuePipeline:
    """Run the Account Intelligence -> Outreach -> Interaction -> Proposal -> Learning loop."""

    def __init__(
        self,
        store: RevenueStore,
        settings: RevenueAgentSettings,
        risk_manager: RevenueRiskManager,
        approval_gate: ApprovalGate,
        compliance_guard: ComplianceGuard,
        telemetry: NonTradingTelemetry,
        sender: BaseSender,
        *,
        campaign: Campaign,
        simulate_responses: bool = False,
    ):
        self.store = store
        self.settings = settings
        self.risk_manager = risk_manager
        self.approval_gate = approval_gate
        self.compliance_guard = compliance_guard
        self.telemetry = telemetry
        self.sender = sender
        self.campaign = campaign
        self.simulate_responses = simulate_responses
        self.account_engine = AccountIntelligenceEngine(store, telemetry)
        self.outreach_engine = OutreachEngine(store, approval_gate, compliance_guard, telemetry)
        self.interaction_engine = InteractionEngine(store, telemetry)
        self.proposal_engine = ProposalEngine(store, telemetry)
        self.learning_engine = LearningEngine(store, telemetry)

    @property
    def run_mode(self) -> str:
        return "sim" if self.sender.provider_name == "dry_run" else "live"

    def run_cycle(self, leads: list[Lead] | None = None) -> CycleReport:
        cycle_id = f"cycle-{utc_now()}"
        started_at = utc_now()
        self.store.touch_heartbeat()
        self.store.touch_engine_heartbeat(
            PIPELINE_ENGINE,
            status="running",
            run_mode=self.run_mode,
            metadata={"cycle_id": cycle_id},
        )

        pipeline_decision = self.risk_manager.evaluate_engine(PIPELINE_ENGINE)
        if not pipeline_decision.allowed:
            return self._blocked_report(
                cycle_id=cycle_id,
                started_at=started_at,
                reason=pipeline_decision.reason,
                blocked_stage=PIPELINE_ENGINE,
            )

        cycle_leads, scanned, suppressed, skipped_existing = self._load_cycle_leads(leads)
        try:
            researched = self._run_account_stage(cycle_leads)
            qualified = [result for result in researched if result.qualified]
            outreach = self._run_outreach_stage(qualified)
            interactions = self._run_interaction_stage(outreach)
            proposals = self._run_proposal_stage(interactions)
            outcomes = self._run_learning_stage(proposals)
        except RuntimeError as exc:
            stage_name, _, reason = str(exc).partition(":")
            logger.warning("pipeline_blocked stage=%s reason=%s", stage_name, reason or str(exc))
            return self._blocked_report(
                cycle_id=cycle_id,
                started_at=started_at,
                reason=reason or str(exc),
                blocked_stage=stage_name or PIPELINE_ENGINE,
            )

        completed_at = utc_now()
        report = CycleReport(
            cycle_id=cycle_id,
            started_at=started_at,
            completed_at=completed_at,
            scanned_leads=scanned,
            suppressed_leads=suppressed,
            skipped_existing=skipped_existing,
            accounts_researched=len(researched),
            qualified_accounts=len(qualified),
            outreach_attempted=len(qualified),
            outreach_sent=sum(1 for result in outreach if result.delivery_status in SUCCESSFUL_DELIVERY_STATUSES),
            approval_pending=sum(
                1
                for result in outreach
                if result.reason in {"approval_required", "approval_pending"}
            ),
            replies_recorded=sum(1 for item in interactions if item.reply_message_id is not None),
            meetings_booked=sum(1 for item in interactions if item.meeting_id is not None),
            proposals_sent=len(proposals),
            outcomes_recorded=len(outcomes),
        )
        self.telemetry.cycle_completed(report.to_dict())
        self.store.upsert_engine_state(
            PIPELINE_ENGINE,
            status="idle",
            run_mode=self.run_mode,
            metadata=report.to_dict(),
            last_heartbeat_at=completed_at,
            last_event_at=completed_at,
        )
        return report

    def _run_account_stage(self, leads: list[Lead]):
        self._ensure_stage_allowed("account_intelligence")
        self.store.touch_engine_heartbeat(
            "account_intelligence",
            status="running",
            run_mode=self.run_mode,
            metadata={"candidate_leads": len(leads)},
        )
        results = [
            self.account_engine.research_lead(
                lead,
                campaign=self.campaign,
                settings=self.settings,
                qualification_threshold=QUALIFICATION_THRESHOLD,
            )
            for lead in leads
        ]
        timestamp = utc_now()
        self.store.upsert_engine_state(
            "account_intelligence",
            status="idle",
            run_mode=self.run_mode,
            metadata={
                "candidate_leads": len(leads),
                "researched_accounts": len(results),
                "qualified_accounts": sum(1 for result in results if result.qualified),
            },
            last_heartbeat_at=timestamp,
            last_event_at=timestamp if results else None,
        )
        return results

    def _run_outreach_stage(self, qualified_results):
        self._ensure_stage_allowed("outreach")
        self.store.touch_engine_heartbeat(
            "outreach",
            status="running",
            run_mode=self.run_mode,
            metadata={"qualified_accounts": len(qualified_results)},
        )
        dispatched = [
            self.outreach_engine.deliver_message(
                lead=result.lead,
                account=result.account,
                contact=result.contact,
                opportunity=result.opportunity,
                campaign=self.campaign,
                settings=self.settings,
                sender=self.sender,
                sender_name=self.settings.from_name,
                sender_email=self.settings.from_email,
                requested_by=PIPELINE_ENGINE,
            )
            for result in qualified_results
        ]
        timestamp = utc_now()
        self.store.upsert_engine_state(
            "outreach",
            status="idle",
            run_mode=self.run_mode,
            metadata={
                "qualified_accounts": len(qualified_results),
                "attempted": len(dispatched),
                "sent": sum(1 for result in dispatched if result.delivery_status in SUCCESSFUL_DELIVERY_STATUSES),
                "approval_pending": sum(
                    1 for result in dispatched if result.reason in {"approval_required", "approval_pending"}
                ),
            },
            last_heartbeat_at=timestamp,
            last_event_at=timestamp if dispatched else None,
        )
        return dispatched

    def _run_interaction_stage(self, outreach_results):
        self._ensure_stage_allowed("interaction")
        sent_messages = [
            result.message
            for result in outreach_results
            if result.delivery_status in SUCCESSFUL_DELIVERY_STATUSES and result.message is not None
        ]
        self.store.touch_engine_heartbeat(
            "interaction",
            status="running",
            run_mode=self.run_mode,
            metadata={"outbound_messages": len(sent_messages)},
        )
        interactions = self.interaction_engine.process_inbox(
            sent_messages,
            simulate=self.simulate_responses,
        )
        timestamp = utc_now()
        self.store.upsert_engine_state(
            "interaction",
            status="idle",
            run_mode=self.run_mode,
            metadata={
                "outbound_messages": len(sent_messages),
                "replies_recorded": sum(1 for item in interactions if item.reply_message_id is not None),
                "meetings_booked": sum(1 for item in interactions if item.meeting_id is not None),
            },
            last_heartbeat_at=timestamp,
            last_event_at=timestamp if interactions else None,
        )
        return interactions

    def _run_proposal_stage(self, interactions):
        self._ensure_stage_allowed("proposal")
        ready = [item for item in interactions if item.ready_for_proposal]
        self.store.touch_engine_heartbeat(
            "proposal",
            status="running",
            run_mode=self.run_mode,
            metadata={"qualified_interactions": len(ready)},
        )
        proposals = [
            proposal
            for item in ready
            if (proposal := self.proposal_engine.create_proposal_for_interaction(item)) is not None
        ]
        timestamp = utc_now()
        self.store.upsert_engine_state(
            "proposal",
            status="idle",
            run_mode=self.run_mode,
            metadata={
                "qualified_interactions": len(ready),
                "proposals_sent": len(proposals),
            },
            last_heartbeat_at=timestamp,
            last_event_at=timestamp if proposals else None,
        )
        return proposals

    def _run_learning_stage(self, proposals):
        self._ensure_stage_allowed("learning")
        self.store.touch_engine_heartbeat(
            "learning",
            status="running",
            run_mode=self.run_mode,
            metadata={"new_proposals": len(proposals)},
        )
        outcomes = self.learning_engine.evaluate_cycle(
            proposals,
            simulate=self.simulate_responses,
        )
        timestamp = utc_now()
        self.store.upsert_engine_state(
            "learning",
            status="idle",
            run_mode=self.run_mode,
            metadata={
                "new_proposals": len(proposals),
                "outcomes_recorded": len(outcomes),
            },
            last_heartbeat_at=timestamp,
            last_event_at=timestamp if outcomes else None,
        )
        return outcomes

    def _ensure_stage_allowed(self, engine_name: str) -> None:
        decision = self.risk_manager.evaluate_engine(engine_name)
        if decision.allowed:
            return
        raise RuntimeError(f"{engine_name}:{decision.reason}")

    def _load_cycle_leads(self, leads: list[Lead] | None) -> tuple[list[Lead], int, int, int]:
        if leads is not None:
            return leads, len(leads), 0, 0

        t = self.store.tables
        with self.store._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT l.*,
                       EXISTS(
                           SELECT 1
                           FROM {t['suppression_list']} AS s
                           WHERE s.email_normalized = l.email_normalized
                       ) AS is_suppressed,
                       EXISTS(
                           SELECT 1
                           FROM {t['outbox_messages']} AS o
                           WHERE o.campaign_id = ?
                             AND o.lead_id = l.id
                             AND o.status IN ('queued', 'dry_run', 'provider_accepted', 'sent')
                       ) AS already_contacted
                FROM {t['leads']} AS l
                ORDER BY l.explicit_opt_in DESC, l.created_at ASC
                """,
                (self.campaign.id or 0,),
            ).fetchall()

        visible: list[Lead] = []
        suppressed = 0
        skipped_existing = 0
        for row in rows:
            lead = self.store._lead_from_row(row)
            if bool(row["already_contacted"]):
                skipped_existing += 1
                continue
            if bool(row["is_suppressed"]):
                suppressed += 1
                continue
            visible.append(lead)
        return visible, len(rows), suppressed, skipped_existing

    def _blocked_report(
        self,
        *,
        cycle_id: str,
        started_at: str,
        reason: str,
        blocked_stage: str,
    ) -> CycleReport:
        completed_at = utc_now()
        report = CycleReport(
            cycle_id=cycle_id,
            started_at=started_at,
            completed_at=completed_at,
            status="blocked",
            reason=reason,
            blocked_stage=blocked_stage,
        )
        self.telemetry.cycle_completed(report.to_dict(), status="blocked")
        self.store.upsert_engine_state(
            blocked_stage,
            status="blocked",
            run_mode=self.run_mode,
            metadata={"cycle_id": cycle_id, "reason": reason},
            last_heartbeat_at=completed_at,
            last_event_at=completed_at,
        )
        self.store.upsert_engine_state(
            PIPELINE_ENGINE,
            status="blocked",
            run_mode=self.run_mode,
            metadata=report.to_dict(),
            last_heartbeat_at=completed_at,
            last_event_at=completed_at,
        )
        return report
