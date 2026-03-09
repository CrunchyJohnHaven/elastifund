"""Interaction stub for JJ-N Phase 0."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nontrading.crm_schema import ApprovalClass
from nontrading.crm_schema import Interaction as CRMInteraction
from nontrading.crm_schema import Lead as CRMLead
from nontrading.models import Meeting, Message
from nontrading.store import RevenueStore
from nontrading.telemetry import NonTradingTelemetry


@dataclass(frozen=True)
class InteractionResult:
    record_id: int | None
    telemetry_event_id: int | None


class InteractionEngine:
    """Phase 0: capture replies and meetings. Phase 1: classify and route them."""

    def __init__(self, store: RevenueStore | None = None, telemetry: NonTradingTelemetry | None = None):
        self.store = store
        self.telemetry = telemetry

    def process(self, lead: CRMLead) -> CRMInteraction:
        return CRMInteraction(
            id=f"{lead.id}:interaction",
            lead_id=lead.id,
            engine="interaction",
            action="classify_reply",
            approval_class=ApprovalClass.REVIEW,
            result=f"Prepared interaction workflow for {lead.company}",
        )

    @staticmethod
    def to_event(interaction: CRMInteraction) -> dict[str, Any]:
        return interaction.to_event()

    def record_reply(self, message: Message) -> InteractionResult:
        if self.store is None or self.telemetry is None:
            raise RuntimeError("record_reply requires store and telemetry")
        inbound = self.store.create_message(
            Message(
                account_id=message.account_id,
                opportunity_id=message.opportunity_id,
                contact_id=message.contact_id,
                recipient_email=message.recipient_email,
                subject=message.subject,
                body=message.body,
                channel=message.channel,
                direction="inbound",
                status="received",
                requires_approval=False,
                approval_status="not_required",
                sender_name=message.sender_name,
                sender_email=message.sender_email,
                metadata=message.metadata,
            )
        )
        event = self.telemetry.reply_received(inbound)
        return InteractionResult(record_id=inbound.id, telemetry_event_id=event.id)

    def book_meeting(self, meeting: Meeting) -> InteractionResult:
        if self.store is None or self.telemetry is None:
            raise RuntimeError("book_meeting requires store and telemetry")
        booked = self.store.create_meeting(meeting)
        event = self.telemetry.meeting_booked(booked)
        return InteractionResult(record_id=booked.id, telemetry_event_id=event.id)
