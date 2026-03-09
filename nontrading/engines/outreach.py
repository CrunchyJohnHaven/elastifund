"""Outreach stub for JJ-N Phase 0."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nontrading.approval import ApprovalDecision, ApprovalGate
from nontrading.compliance import ComplianceDecision, ComplianceGuard
from nontrading.config import RevenueAgentSettings
from nontrading.crm_schema import ApprovalClass
from nontrading.crm_schema import Interaction as CRMInteraction
from nontrading.crm_schema import Lead as CRMLead
from nontrading.email.render import render_campaign_email
from nontrading.email.sender import BaseSender
from nontrading.models import Account, Campaign, Contact, Lead, Message, Opportunity, OutboxMessage
from nontrading.store import RevenueStore
from nontrading.telemetry import NonTradingTelemetry

SUCCESSFUL_DELIVERY_STATUSES = {"dry_run", "provider_accepted", "sent"}


@dataclass(frozen=True)
class OutreachResult:
    allowed: bool
    reason: str
    message: Message
    approval: ApprovalDecision
    compliance: ComplianceDecision
    outbox_message: OutboxMessage | None = None
    delivery_status: str = ""
    delivery_detail: str = ""


class OutreachEngine:
    """Phase 0: draft and queue outreach. Phase 1: dispatch approved sends."""

    def __init__(
        self,
        store: RevenueStore | None = None,
        approval_gate: ApprovalGate | None = None,
        compliance_guard: ComplianceGuard | None = None,
        telemetry: NonTradingTelemetry | None = None,
    ):
        self.store = store
        self.approval_gate = approval_gate
        self.compliance_guard = compliance_guard
        self.telemetry = telemetry

    def process(self, lead: CRMLead) -> CRMInteraction:
        return CRMInteraction(
            id=f"{lead.id}:outreach",
            lead_id=lead.id,
            engine="outreach",
            action="draft_outreach",
            approval_class=ApprovalClass.REVIEW,
            result=f"Queued outreach for {lead.contact_email}",
        )

    @staticmethod
    def to_event(interaction: CRMInteraction) -> dict[str, Any]:
        return interaction.to_event()

    def route(self, lead: CRMLead) -> ApprovalDecision:
        if self.approval_gate is None:
            raise RuntimeError("route requires an approval gate")
        return self.approval_gate.route(self.process(lead))

    def stage_message(self, message: Message) -> Message:
        if self.store is None:
            raise RuntimeError("stage_message requires a configured store")
        return self.store.create_message(message)

    def request_send(
        self,
        message_id: int,
        *,
        sender_name: str,
        sender_email: str,
        requested_by: str = "jj-n",
    ) -> OutreachResult:
        staged, approval, compliance = self._authorize_send(
            message_id,
            sender_name=sender_name,
            sender_email=sender_email,
            requested_by=requested_by,
        )
        if not compliance.allowed or not approval.allowed:
            return OutreachResult(
                allowed=False,
                reason=compliance.reason if not compliance.allowed else approval.reason,
                message=staged,
                approval=approval,
                compliance=compliance,
                delivery_status=staged.status,
            )

        sent = self.store.update_message_status(
            staged.id or 0,
            status="sent",
            approval_status="approved",
            sender_name=sender_name,
            sender_email=sender_email,
            metadata={"delivery_status": "internal_only"},
        )
        self.telemetry.message_sent(sent)
        return OutreachResult(
            allowed=True,
            reason="sent",
            message=sent,
            approval=approval,
            compliance=compliance,
            delivery_status="sent",
        )

    def deliver_message(
        self,
        *,
        lead: Lead,
        account: Account,
        contact: Contact,
        opportunity: Opportunity,
        campaign: Campaign,
        settings: RevenueAgentSettings,
        sender: BaseSender,
        sender_name: str,
        sender_email: str,
        requested_by: str = "jj-n",
    ) -> OutreachResult:
        if self.store is None or self.telemetry is None:
            raise RuntimeError("deliver_message requires store and telemetry")

        rendered = render_campaign_email(campaign, lead, settings)
        staged = self.stage_message(
            Message(
                account_id=account.id or 0,
                opportunity_id=opportunity.id,
                contact_id=contact.id,
                recipient_email=lead.email,
                subject=rendered.subject,
                body=rendered.body,
                metadata={
                    "campaign_id": campaign.id,
                    "lead_id": lead.id,
                    "fit_score": opportunity.score,
                    "explicit_opt_in": lead.explicit_opt_in,
                    "unsubscribe_url": rendered.unsubscribe_url,
                },
            )
        )
        approved_message, approval, compliance = self._authorize_send(
            staged.id or 0,
            sender_name=sender_name,
            sender_email=sender_email,
            requested_by=requested_by,
        )
        if not compliance.allowed or not approval.allowed:
            return OutreachResult(
                allowed=False,
                reason=compliance.reason if not compliance.allowed else approval.reason,
                message=approved_message,
                approval=approval,
                compliance=compliance,
                delivery_status=approved_message.status,
            )

        outbox_message = self.store.queue_outbox_message(
            campaign=campaign,
            lead=lead,
            subject=rendered.subject,
            body=rendered.body,
            headers=rendered.headers,
            from_email=sender_email,
            provider=sender.provider_name,
        )
        delivery = sender.send(outbox_message)
        final_status = "sent" if delivery.status in SUCCESSFUL_DELIVERY_STATUSES else "failed"
        if delivery.status == "suppressed":
            final_status = "blocked"
        delivered_message = self.store.update_message_status(
            approved_message.id or 0,
            status=final_status,
            approval_status="approved",
            sender_name=sender_name,
            sender_email=sender_email,
            metadata={
                "outbox_message_id": outbox_message.id,
                "delivery_status": delivery.status,
                "delivery_detail": delivery.detail,
                "transport_message_id": delivery.transport_message_id or "",
                "filesystem_path": delivery.filesystem_path or "",
            },
        )
        if delivery.status in SUCCESSFUL_DELIVERY_STATUSES:
            self.telemetry.message_sent(delivered_message)
        return OutreachResult(
            allowed=delivery.status in SUCCESSFUL_DELIVERY_STATUSES,
            reason="sent" if delivery.status in SUCCESSFUL_DELIVERY_STATUSES else delivery.status,
            message=delivered_message,
            approval=approval,
            compliance=compliance,
            outbox_message=self.store.get_outbox_message(outbox_message.id or 0),
            delivery_status=delivery.status,
            delivery_detail=delivery.detail,
        )

    def _authorize_send(
        self,
        message_id: int,
        *,
        sender_name: str,
        sender_email: str,
        requested_by: str,
    ) -> tuple[Message, ApprovalDecision, ComplianceDecision]:
        if (
            self.store is None
            or self.approval_gate is None
            or self.compliance_guard is None
            or self.telemetry is None
        ):
            raise RuntimeError("request_send requires store, approval gate, compliance guard, and telemetry")
        message = self.store.get_message(message_id)
        if message is None:
            raise RuntimeError(f"CRM message {message_id} is missing")

        compliance = self.compliance_guard.evaluate_outreach(
            sender_name=sender_name,
            sender_email=sender_email,
            recipient_email=message.recipient_email,
        )
        if not compliance.allowed:
            blocked = self.store.update_message_status(
                message.id or 0,
                status="blocked",
                approval_status="blocked",
                sender_name=sender_name,
                sender_email=sender_email,
            )
            return blocked, ApprovalDecision(False, "compliance_blocked", "blocked"), compliance

        approval = self.approval_gate.require_approval(
            action_type="outreach_message",
            entity_type="message",
            entity_id=str(message.id or 0),
            summary=f"Approve outreach to {message.recipient_email}",
            payload={
                "account_id": message.account_id,
                "opportunity_id": message.opportunity_id or 0,
                "contact_id": message.contact_id or 0,
                "subject": message.subject,
            },
            requested_by=requested_by,
        )
        if not approval.allowed:
            pending = self.store.update_message_status(
                message.id or 0,
                status="pending_approval",
                approval_status=approval.request_status,
                sender_name=sender_name,
                sender_email=sender_email,
            )
            return pending, approval, compliance

        approved = self.store.update_message_status(
            message.id or 0,
            sender_name=sender_name,
            sender_email=sender_email,
        )
        return approved, approval, compliance
