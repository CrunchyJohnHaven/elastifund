"""Campaign scan -> score -> enqueue -> send loop."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from nontrading.campaigns.policies import evaluate_lead_policy
from nontrading.config import RevenueAgentSettings
from nontrading.email.render import render_campaign_email
from nontrading.email.sender import BaseSender, DeliveryResult
from nontrading.models import Campaign, Lead, SendEvent, utc_now
from nontrading.risk import RevenueRiskManager
from nontrading.store import RevenueStore

logger = logging.getLogger("nontrading.campaigns")
OUTBOUND_FOLLOWUP_ENGINE = "outbound_followup"


@dataclass
class CampaignRunSummary:
    campaign_name: str
    campaign_id: int
    scanned: int = 0
    eligible: int = 0
    queued: int = 0
    sent: int = 0
    suppressed: int = 0
    filtered: int = 0
    deferred: int = 0
    failed: int = 0
    blocked: bool = False
    block_reason: str = ""


@dataclass
class EngineRunSummary:
    campaigns_scanned: int = 0
    blocked_campaigns: int = 0
    scanned: int = 0
    eligible: int = 0
    queued: int = 0
    sent: int = 0
    suppressed: int = 0
    filtered: int = 0
    deferred: int = 0
    failed: int = 0
    campaign_summaries: list[CampaignRunSummary] = field(default_factory=list)

    def add_campaign(self, summary: CampaignRunSummary) -> None:
        self.campaign_summaries.append(summary)
        self.campaigns_scanned += 1
        self.blocked_campaigns += 1 if summary.blocked else 0
        self.scanned += summary.scanned
        self.eligible += summary.eligible
        self.queued += summary.queued
        self.sent += summary.sent
        self.suppressed += summary.suppressed
        self.filtered += summary.filtered
        self.deferred += summary.deferred
        self.failed += summary.failed


class CampaignEngine:
    """Single-pass campaign engine with compliance gating and rate limits."""

    def __init__(
        self,
        store: RevenueStore,
        risk_manager: RevenueRiskManager,
        sender: BaseSender,
        settings: RevenueAgentSettings,
    ):
        self.store = store
        self.risk_manager = risk_manager
        self.sender = sender
        self.settings = settings

    def run_once(self) -> EngineRunSummary:
        self.store.touch_heartbeat()
        self.store.touch_engine_heartbeat(
            OUTBOUND_FOLLOWUP_ENGINE,
            status="running",
            run_mode=self._run_mode(),
        )
        summary = EngineRunSummary()
        for campaign in self.store.list_active_campaigns():
            summary.add_campaign(self._run_campaign(campaign))
        self.store.upsert_engine_state(
            OUTBOUND_FOLLOWUP_ENGINE,
            status="blocked" if summary.blocked_campaigns else "idle",
            run_mode=self._run_mode(),
            metadata={
                "campaigns_scanned": summary.campaigns_scanned,
                "blocked_campaigns": summary.blocked_campaigns,
                "queued": summary.queued,
                "sent": summary.sent,
                "failed": summary.failed,
            },
            last_heartbeat_at=utc_now(),
            last_event_at=utc_now() if summary.queued or summary.sent or summary.failed else None,
        )
        return summary

    def _run_campaign(self, campaign: Campaign) -> CampaignRunSummary:
        campaign_id = campaign.id or 0
        summary = CampaignRunSummary(campaign_name=campaign.name, campaign_id=campaign_id)
        decision = self.risk_manager.evaluate_campaign(campaign, engine_name=OUTBOUND_FOLLOWUP_ENGINE)
        if not decision.allowed:
            logger.warning("campaign_blocked name=%s reason=%s", campaign.name, decision.reason)
            summary.blocked = True
            summary.block_reason = decision.reason
            return summary

        candidates = self.store.list_unsent_leads_for_campaign(campaign_id)
        summary.scanned = len(candidates)

        ranked: list[tuple[float, Lead]] = []
        for lead in candidates:
            if self.store.is_suppressed(lead.email):
                summary.suppressed += 1
                continue
            policy = evaluate_lead_policy(lead, campaign, self.settings)
            if not policy.allowed:
                summary.filtered += 1
                logger.info(
                    "lead_rejected campaign=%s email=%s reasons=%s",
                    campaign.name,
                    lead.email,
                    ",".join(policy.reasons),
                )
                continue
            ranked.append((policy.score, lead))

        ranked.sort(key=lambda item: item[0], reverse=True)
        summary.eligible = len(ranked)
        summary.deferred = max(len(ranked) - decision.remaining_quota, 0)

        for _, lead in ranked[: decision.remaining_quota]:
            try:
                rendered = render_campaign_email(campaign, lead, self.settings)
            except ValueError as exc:
                logger.error("render_failed campaign=%s email=%s error=%s", campaign.name, lead.email, exc)
                summary.failed += 1
                self.store.record_send_event(
                    SendEvent(
                        campaign_id=campaign_id,
                        lead_id=lead.id,
                        email=lead.email,
                        event_type="render_failed",
                        status="failed",
                        provider=self.sender.provider_name,
                        detail=str(exc),
                    )
                )
                continue

            queued = self.store.queue_outbox_message(
                campaign=campaign,
                lead=lead,
                subject=rendered.subject,
                body=rendered.body,
                headers=rendered.headers,
                from_email=self.settings.from_email,
                provider=self.sender.provider_name,
            )
            summary.queued += 1
            self.store.record_send_event(
                SendEvent(
                    campaign_id=campaign_id,
                    lead_id=lead.id,
                    email=lead.email,
                    event_type="enqueued",
                    status="queued",
                    provider=self.sender.provider_name,
                    detail="queued for delivery",
                )
            )

            delivery = self.sender.send(queued)
            self._record_delivery_event(lead, campaign_id, delivery)

            if delivery.status in {"dry_run", "provider_accepted", "sent"}:
                summary.sent += 1
            elif delivery.status == "suppressed":
                summary.suppressed += 1
            else:
                summary.failed += 1

        return summary

    def _record_delivery_event(self, lead: Lead, campaign_id: int, delivery: DeliveryResult) -> None:
        event_type = {
            "dry_run": "dry_run",
            "provider_accepted": "sent",
            "sent": "sent",
            "suppressed": "suppressed",
            "rejected": "rejected",
        }.get(delivery.status, "failed")
        self.store.record_send_event(
            SendEvent(
                campaign_id=campaign_id,
                lead_id=lead.id,
                email=lead.email,
                event_type=event_type,
                status=delivery.status,
                provider=delivery.provider,
                detail=delivery.detail,
                metadata={
                    "transport_message_id": delivery.transport_message_id or "",
                    "filesystem_path": delivery.filesystem_path or "",
                },
            )
        )

    def _run_mode(self) -> str:
        return "sim" if self.sender.provider_name == "dry_run" else "live"
