"""Sequential JJ-N pipeline that wires the five engines into one cycle."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from nontrading.approval import ApprovalGate
from nontrading.campaigns.website_growth_audit_funnel import (
    WEBSITE_GROWTH_AUDIT_STEPS,
    fulfillment_placeholder,
)
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
DEFAULT_CYCLE_REPORT_PATH = Path("reports/nontrading/website_growth_audit_cycle_reports.jsonl")


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
    outreach_approved: int = 0
    outreach_blocked: int = 0
    outreach_sent: int = 0
    approval_pending: int = 0
    replies_recorded: int = 0
    meetings_booked: int = 0
    proposals_sent: int = 0
    fulfillment_planned: int = 0
    outcomes_recorded: int = 0
    outcomes_won: int = 0
    offer_slug: str = "website-growth-audit"
    funnel_steps: tuple[str, ...] = WEBSITE_GROWTH_AUDIT_STEPS
    funnel_stage_counts: dict[str, int] | None = None
    persisted_report_path: str = ""

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
        configured_report_path = os.environ.get("JJ_NONTRADING_CYCLE_REPORT_PATH", "").strip()
        self.cycle_report_path = Path(configured_report_path) if configured_report_path else DEFAULT_CYCLE_REPORT_PATH

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
            fulfillment_records = self._run_fulfillment_stage(proposals)
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
        outreach_approved = sum(
            1
            for result in outreach
            if result.approval.allowed and result.compliance.allowed
        )
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
            outreach_approved=outreach_approved,
            outreach_blocked=max(0, len(qualified) - outreach_approved),
            outreach_sent=sum(1 for result in outreach if result.delivery_status in SUCCESSFUL_DELIVERY_STATUSES),
            approval_pending=sum(
                1
                for result in outreach
                if result.reason in {"approval_required", "approval_pending"}
            ),
            replies_recorded=sum(1 for item in interactions if item.reply_message_id is not None),
            meetings_booked=sum(1 for item in interactions if item.meeting_id is not None),
            proposals_sent=len(proposals),
            fulfillment_planned=len(fulfillment_records),
            outcomes_recorded=len(outcomes),
            outcomes_won=sum(1 for item in outcomes if str(item.status or "").endswith("won")),
            funnel_stage_counts=self._build_funnel_stage_counts(),
        )
        persisted_path = self._persist_cycle_report(report)
        report = CycleReport(**{**report.to_dict(), "persisted_report_path": str(persisted_path)})
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
        for result in dispatched:
            self._sync_opportunity_stage_from_outreach(result)
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
        for interaction in interactions:
            self._sync_opportunity_stage_from_interaction(interaction)
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
        for proposal in proposals:
            self._sync_opportunity_stage(
                proposal.opportunity_id,
                stage="proposal",
                next_action="prepare_fulfillment",
                metadata={"proposal_sent_at": timestamp},
            )
        return proposals

    def _run_fulfillment_stage(self, proposals):
        self._ensure_stage_allowed("fulfillment")
        self.store.touch_engine_heartbeat(
            "fulfillment",
            status="running",
            run_mode=self.run_mode,
            metadata={"new_proposals": len(proposals)},
        )
        records: list[dict[str, Any]] = []
        timestamp = utc_now()
        for proposal in proposals:
            if proposal.id is None:
                continue
            placeholder = fulfillment_placeholder(
                opportunity_id=proposal.opportunity_id,
                proposal_id=proposal.id,
                simulated=self.simulate_responses,
            )
            records.append(placeholder)
            self._sync_opportunity_stage(
                proposal.opportunity_id,
                stage="fulfillment",
                next_action="collect_audit_inputs",
                metadata={"fulfillment": placeholder, "fulfillment_planned_at": timestamp},
            )
        self.store.upsert_engine_state(
            "fulfillment",
            status="idle",
            run_mode=self.run_mode,
            metadata={"new_proposals": len(proposals), "fulfillment_planned": len(records)},
            last_heartbeat_at=timestamp,
            last_event_at=timestamp if records else None,
        )
        return records

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
        for outcome in outcomes:
            won = str(outcome.status or "").endswith("won")
            self._sync_opportunity_stage(
                outcome.opportunity_id,
                stage="outcome",
                status="won" if won else "open",
                next_action="archive_case_study" if won else "follow_up_pipeline",
                metadata={"latest_outcome_status": outcome.status, "latest_outcome_at": timestamp},
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

    def _sync_opportunity_stage(
        self,
        opportunity_id: int | None,
        *,
        stage: str,
        status: str | None = None,
        next_action: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not opportunity_id:
            return
        current = self.store.get_opportunity(int(opportunity_id))
        if current is None:
            return
        merged_metadata = dict(current.metadata)
        if metadata:
            merged_metadata.update(metadata)
        self.store.upsert_opportunity(
            current.__class__(
                id=current.id,
                account_id=current.account_id,
                name=current.name,
                offer_name=current.offer_name,
                stage=str(stage).strip().lower(),
                status=status or current.status,
                score=current.score,
                score_breakdown=current.score_breakdown,
                estimated_value=current.estimated_value,
                currency=current.currency,
                next_action=next_action or current.next_action,
                metadata=merged_metadata,
                created_at=current.created_at,
                updated_at=current.updated_at,
            )
        )

    def _sync_opportunity_stage_from_outreach(self, result) -> None:
        opportunity_id = result.message.opportunity_id
        if opportunity_id is None:
            return
        if result.reason in {"approval_required", "approval_pending"}:
            self._sync_opportunity_stage(
                opportunity_id,
                stage="approval",
                next_action="review_outreach_approval",
                metadata={"approval_status": "pending"},
            )
            return
        if result.delivery_status in SUCCESSFUL_DELIVERY_STATUSES:
            self._sync_opportunity_stage(
                opportunity_id,
                stage="outreach",
                next_action="monitor_replies",
                metadata={"outreach_status": "sent"},
            )
            return
        self._sync_opportunity_stage(
            opportunity_id,
            stage="approval",
            status="blocked",
            next_action="resolve_send_blocker",
            metadata={"outreach_status": result.delivery_status or result.reason},
        )

    def _sync_opportunity_stage_from_interaction(self, interaction) -> None:
        if interaction.opportunity_id is None:
            return
        if interaction.meeting_id is not None:
            self._sync_opportunity_stage(
                interaction.opportunity_id,
                stage="meeting",
                next_action="prepare_proposal",
                metadata={"interaction_classification": interaction.classification},
            )
            return
        if interaction.reply_message_id is not None:
            self._sync_opportunity_stage(
                interaction.opportunity_id,
                stage="meeting",
                next_action="book_discovery_call",
                metadata={"interaction_classification": interaction.classification},
            )

    def _build_funnel_stage_counts(self) -> dict[str, int]:
        counts = {step: 0 for step in WEBSITE_GROWTH_AUDIT_STEPS}
        for opportunity in self.store.list_opportunities():
            stage = str(opportunity.stage or "").strip().lower()
            if stage in counts:
                counts[stage] += 1
        return counts

    def _persist_cycle_report(self, report: CycleReport) -> Path:
        report_path = Path(self.cycle_report_path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with report_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(report.to_dict(), sort_keys=True) + "\n")
        return report_path

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
        persisted_path = self._persist_cycle_report(report)
        report = CycleReport(**{**report.to_dict(), "persisted_report_path": str(persisted_path)})
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
