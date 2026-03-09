"""Phase 0 approval routing for JJ-N actions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from nontrading.crm_schema import ApprovalClass, Interaction, utc_now

ActionExecutor = Callable[[Interaction], Any]


@dataclass(frozen=True)
class ApprovalDecision:
    interaction_id: str
    approval_class: ApprovalClass
    status: str
    executed: bool
    queued: bool
    blocked: bool
    paper_mode: bool
    event: dict[str, Any]


class ApprovalGate:
    """Route JJ-N actions by approval class while honoring paper mode."""

    def __init__(self, *, paper_mode: bool = True):
        self.paper_mode = paper_mode
        self.review_queue: list[Interaction] = []
        self.escalation_queue: list[Interaction] = []
        self.approved_ids: set[str] = set()
        self.events: list[dict[str, Any]] = []

    def route(self, interaction: Interaction, execute: ActionExecutor | None = None) -> ApprovalDecision:
        executed = False
        queued = False
        blocked = False
        status = "queued_review"

        if interaction.approval_class is ApprovalClass.AUTO:
            status = "paper_logged" if self.paper_mode else "executed"
            executed = not self.paper_mode
            if not self.paper_mode and execute is not None:
                execute(interaction)
        elif interaction.approval_class is ApprovalClass.REVIEW:
            queued = True
            self.review_queue.append(interaction)
        else:
            blocked = True
            status = "blocked_escalation"
            self.escalation_queue.append(interaction)

        event = {
            "event_type": "approval_gate",
            "timestamp": utc_now(),
            "interaction_id": interaction.id,
            "lead_id": interaction.lead_id,
            "engine": interaction.engine,
            "action": interaction.action,
            "approval_class": interaction.approval_class.value,
            "status": status,
            "paper_mode": self.paper_mode,
            "executed": executed,
        }
        self.events.append(event)
        return ApprovalDecision(
            interaction_id=interaction.id,
            approval_class=interaction.approval_class,
            status=status,
            executed=executed,
            queued=queued,
            blocked=blocked,
            paper_mode=self.paper_mode,
            event=event,
        )

    def approve(self, interaction_id: str) -> bool:
        matched = self._remove_from_queue(self.review_queue, interaction_id)
        matched = self._remove_from_queue(self.escalation_queue, interaction_id) or matched
        if not matched:
            return False
        self.approved_ids.add(interaction_id)
        self.events.append(
            {
                "event_type": "approval_gate",
                "timestamp": utc_now(),
                "interaction_id": interaction_id,
                "status": "approved",
                "paper_mode": self.paper_mode,
            }
        )
        return True

    def flush_events(self) -> list[dict[str, Any]]:
        events = list(self.events)
        self.events.clear()
        return events

    @staticmethod
    def _remove_from_queue(queue: list[Interaction], interaction_id: str) -> bool:
        for index, interaction in enumerate(queue):
            if interaction.id == interaction_id:
                del queue[index]
                return True
        return False
