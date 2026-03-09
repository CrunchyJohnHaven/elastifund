"""Outreach stub for JJ-N Phase 0."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nontrading.approval import ApprovalDecision, ApprovalGate
from nontrading.compliance import ComplianceDecision, ComplianceGuard
from nontrading.crm_schema import ApprovalClass
from nontrading.crm_schema import Interaction as CRMInteraction
from nontrading.crm_schema import Lead as CRMLead
from nontrading.models import Message
from nontrading.store import RevenueStore
from nontrading.telemetry import NonTradingTelemetry


@dataclass(frozen=True)
class OutreachResult:
    allowed: bool
    reason: str
    message: Message
    approval: ApprovalDecision
    compliance: ComplianceDecision


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
            return OutreachResult(
                allowed=False,
                reason=compliance.reason,
                message=blocked,
                approval=ApprovalDecision(False, "compliance_blocked", "blocked"),
                compliance=compliance,
            )

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
            return OutreachResult(
                allowed=False,
                reason=approval.reason,
                message=pending,
                approval=approval,
                compliance=compliance,
            )

        sent = self.store.update_message_status(
            message.id or 0,
            status="sent",
            approval_status="approved",
            sender_name=sender_name,
            sender_email=sender_email,
        )
        self.telemetry.message_sent(sent)
        return OutreachResult(
            allowed=True,
            reason="sent",
            message=sent,
            approval=approval,
            compliance=compliance,
        )
