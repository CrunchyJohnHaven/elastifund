"""Follow-up planning for the Website Growth Audit outreach sequence."""

from __future__ import annotations

from dataclasses import dataclass

from nontrading.campaigns.template_selector import ANGLE_3, TemplateSelection, TemplateSelector
from nontrading.config import RevenueAgentSettings
from nontrading.email.sender import BaseSender, DeliveryResult
from nontrading.models import Campaign, Lead, OutboxMessage
from nontrading.offers.website_growth_audit import ServiceOffer
from nontrading.store import RevenueStore


@dataclass(frozen=True)
class SequenceStep:
    step_number: int
    day_offset: int
    label: str
    strategy: str


@dataclass(frozen=True)
class PlannedSequenceStep:
    step_number: int
    day_offset: int
    label: str
    angle: str


@dataclass(frozen=True)
class SequenceState:
    sent_angles: tuple[str, ...] = ()
    replied: bool = False
    unsubscribed: bool = False

    def advance(self, angle: str) -> "SequenceState":
        return SequenceState(
            sent_angles=self.sent_angles + (angle,),
            replied=self.replied,
            unsubscribed=self.unsubscribed,
        )


@dataclass(frozen=True)
class OutreachSequence:
    name: str
    offer_slug: str
    steps: tuple[SequenceStep, ...]
    post_day7_action: str = "nurture"

    def next_step(
        self,
        lead: Lead,
        offer: ServiceOffer,
        selector: TemplateSelector,
        *,
        days_since_start: int,
        state: SequenceState,
    ) -> PlannedSequenceStep | None:
        if state.replied or state.unsubscribed:
            return None

        sent_count = len(state.sent_angles)
        if sent_count >= len(self.steps):
            return None

        step = self.steps[sent_count]
        if days_since_start < step.day_offset:
            return None
        return PlannedSequenceStep(
            step_number=step.step_number,
            day_offset=step.day_offset,
            label=step.label,
            angle=self._resolve_angle(step, lead, offer, selector, state.sent_angles),
        )

    def terminal_action(self, *, days_since_start: int, state: SequenceState) -> str | None:
        if state.unsubscribed:
            return "suppress"
        if state.replied:
            return None
        if days_since_start > 7 and len(state.sent_angles) >= len(self.steps):
            return self.post_day7_action
        return None

    def _resolve_angle(
        self,
        step: SequenceStep,
        lead: Lead,
        offer: ServiceOffer,
        selector: TemplateSelector,
        sent_angles: tuple[str, ...],
    ) -> str:
        if step.strategy == "selected":
            return selector.select_angle(lead, offer)
        options = selector.angle_options(lead, offer, used_angles=sent_angles)
        if step.strategy == "rotate":
            return options[0]
        if step.strategy == "final_value_add":
            return ANGLE_3 if ANGLE_3 not in sent_angles else options[0]
        raise ValueError(f"Unknown sequence strategy: {step.strategy}")


WEBSITE_GROWTH_AUDIT_SEQUENCE = OutreachSequence(
    name="website-growth-audit-sequence",
    offer_slug="website-growth-audit",
    steps=(
        SequenceStep(step_number=1, day_offset=0, label="initial_outreach", strategy="selected"),
        SequenceStep(step_number=2, day_offset=3, label="follow_up", strategy="rotate"),
        SequenceStep(step_number=3, day_offset=7, label="final_value_add", strategy="final_value_add"),
    ),
    post_day7_action="nurture",
)


@dataclass(frozen=True)
class SequenceDelivery:
    planned_step: PlannedSequenceStep
    selection: TemplateSelection
    message: OutboxMessage
    delivery: DeliveryResult
    next_state: SequenceState


class SequenceRunner:
    def __init__(
        self,
        store: RevenueStore,
        sender: BaseSender,
        settings: RevenueAgentSettings,
        selector: TemplateSelector | None = None,
        sequence: OutreachSequence = WEBSITE_GROWTH_AUDIT_SEQUENCE,
    ):
        self.store = store
        self.sender = sender
        self.settings = settings
        self.selector = selector or TemplateSelector(settings)
        self.sequence = sequence

    def send_due_step(
        self,
        lead: Lead,
        offer: ServiceOffer,
        campaign: Campaign,
        *,
        days_since_start: int,
        state: SequenceState,
    ) -> SequenceDelivery | None:
        planned_step = self.sequence.next_step(
            lead,
            offer,
            self.selector,
            days_since_start=days_since_start,
            state=state,
        )
        if planned_step is None:
            return None

        selection = self.selector.select(
            lead,
            offer,
            preferred_angle=planned_step.angle,
            campaign_name=campaign.name,
        )
        message = self.store.queue_outbox_message(
            campaign=campaign,
            lead=lead,
            subject=selection.rendered_email.subject,
            body=selection.rendered_email.body,
            headers=selection.rendered_email.headers,
            from_email=self.settings.from_email,
            provider=self.sender.provider_name,
        )
        delivery = self.sender.send(message)
        next_state = state.advance(planned_step.angle)
        return SequenceDelivery(
            planned_step=planned_step,
            selection=selection,
            message=message,
            delivery=delivery,
            next_state=next_state,
        )
