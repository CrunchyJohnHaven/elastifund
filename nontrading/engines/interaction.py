"""Interaction stub for JJ-N Phase 0."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from nontrading.approval import ApprovalDecision, ApprovalGate
from nontrading.crm_schema import ApprovalClass
from nontrading.crm_schema import Interaction as CRMInteraction
from nontrading.crm_schema import Lead as CRMLead
from nontrading.models import Meeting, Message
from nontrading.store import RevenueStore
from nontrading.telemetry import NonTradingTelemetry

UTC = timezone.utc


@dataclass(frozen=True)
class InteractionResult:
    record_id: int | None
    telemetry_event_id: int | None


@dataclass(frozen=True)
class ProcessedInteraction:
    source_message_id: int
    account_id: int
    opportunity_id: int | None
    contact_id: int | None
    classification: str
    reply_message_id: int | None = None
    meeting_id: int | None = None
    ready_for_proposal: bool = False


class InteractionEngine:
    """Phase 0: capture replies and meetings. Phase 1: classify and route them."""

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

    def route(self, lead: CRMLead) -> ApprovalDecision:
        if self.approval_gate is None:
            raise RuntimeError("route requires an approval gate")
        return self.approval_gate.route(self.process(lead))

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

    def process_inbox(
        self,
        sent_messages: list[Message],
        *,
        simulate: bool = False,
    ) -> list[ProcessedInteraction]:
        if self.store is None or self.telemetry is None:
            raise RuntimeError("process_inbox requires store and telemetry")

        processed: list[ProcessedInteraction] = []
        for message in sent_messages:
            if message.direction != "outbound":
                continue
            if message.metadata.get("interaction_processed_at"):
                continue

            classification = self._classify_message(message, simulate=simulate)
            metadata = {
                "interaction_processed_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
                "interaction_classification": classification,
            }
            self.store.update_message_status(message.id or 0, metadata=metadata)
            if classification == "no_reply":
                continue

            reply = self.record_reply(
                Message(
                    account_id=message.account_id,
                    opportunity_id=message.opportunity_id,
                    contact_id=message.contact_id,
                    recipient_email=message.recipient_email,
                    subject=f"Re: {message.subject}",
                    body=self._reply_body(classification),
                    sender_name=self._sender_name_for_reply(message.recipient_email),
                    sender_email=message.recipient_email,
                    metadata={
                        "classification": classification,
                        "simulated": simulate,
                        "source_message_id": message.id,
                    },
                )
            )
            meeting_id: int | None = None
            ready_for_proposal = classification in {"meeting_request", "interested"}
            if classification == "meeting_request":
                meeting = self.book_meeting(
                    Meeting(
                        account_id=message.account_id,
                        opportunity_id=message.opportunity_id,
                        contact_id=message.contact_id,
                        scheduled_for=(
                            datetime.now(UTC).replace(microsecond=0) + timedelta(days=1)
                        ).isoformat(),
                        owner="jj-n",
                        notes="Synthetic dry-run discovery call scheduled by pipeline.",
                        metadata={
                            "simulated": simulate,
                            "source_message_id": message.id,
                        },
                    )
                )
                meeting_id = meeting.record_id
            processed.append(
                ProcessedInteraction(
                    source_message_id=message.id or 0,
                    account_id=message.account_id,
                    opportunity_id=message.opportunity_id,
                    contact_id=message.contact_id,
                    classification=classification,
                    reply_message_id=reply.record_id,
                    meeting_id=meeting_id,
                    ready_for_proposal=ready_for_proposal,
                )
            )
        return processed

    def _classify_message(self, message: Message, *, simulate: bool) -> str:
        if not simulate:
            return "no_reply"
        if bool(message.metadata.get("force_meeting_request")):
            return "meeting_request"
        if bool(message.metadata.get("force_interested")):
            return "interested"
        if bool(message.metadata.get("explicit_opt_in")):
            return "meeting_request"
        fit_score = float(message.metadata.get("fit_score", 0.0))
        if fit_score >= 95.0:
            return "interested"
        return "no_reply"

    @staticmethod
    def _reply_body(classification: str) -> str:
        if classification == "meeting_request":
            return "This looks relevant. Can we schedule a short call this week?"
        if classification == "interested":
            return "Interested. Please send over the scope and pricing."
        return "Thanks."

    @staticmethod
    def _sender_name_for_reply(recipient_email: str) -> str:
        localpart = recipient_email.partition("@")[0].replace(".", " ").replace("_", " ").strip()
        return " ".join(part.capitalize() for part in localpart.split()) or "Prospect"
