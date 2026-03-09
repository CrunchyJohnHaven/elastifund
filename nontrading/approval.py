"""Unified approval gate for JJ-N paper-mode and CRM interaction routing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from nontrading.crm_schema import ApprovalClass, Interaction as CRMInteraction, utc_now
from nontrading.models import ApprovalRequest, TelemetryEvent
from nontrading.store import RevenueStore

ActionExecutor = Callable[[CRMInteraction], Any]


@dataclass(frozen=True)
class ApprovalDecision:
    allowed: bool
    reason: str
    request_status: str
    request: ApprovalRequest | None = None
    interaction_id: str | None = None
    approval_class: ApprovalClass | None = None
    status: str = ""
    executed: bool = False
    queued: bool = False
    blocked: bool = False
    paper_mode: bool = True
    event: dict[str, Any] = field(default_factory=dict)


class ApprovalGate:
    """Route JJ-N actions through one approval pipeline."""

    def __init__(self, store: RevenueStore | None = None, *, paper_mode: bool = True):
        self.store = store
        self.paper_mode = paper_mode
        self._review_queue: list[CRMInteraction] = []
        self._escalation_queue: list[CRMInteraction] = []
        self._approved_ids: set[str] = set()
        self.events: list[dict[str, Any]] = []

    @property
    def review_queue(self) -> list[CRMInteraction]:
        return self._load_queue(self._review_queue, ApprovalClass.REVIEW)

    @property
    def escalation_queue(self) -> list[CRMInteraction]:
        return self._load_queue(self._escalation_queue, ApprovalClass.ESCALATE)

    @property
    def approved_ids(self) -> set[str]:
        if self.store is None:
            return set(self._approved_ids)
        approved = {
            request.entity_id
            for request in self.store.list_approval_requests(status="approved")
            if request.entity_type == "interaction"
        }
        return approved | self._approved_ids

    def require_approval(
        self,
        *,
        action_type: str,
        entity_type: str,
        entity_id: str,
        summary: str,
        payload: dict[str, Any] | None = None,
        requested_by: str = "jj-n",
    ) -> ApprovalDecision:
        if not self.paper_mode:
            event = self._record_event(
                entity_type=entity_type,
                entity_id=entity_id,
                status="not_required",
                payload={
                    "action_type": action_type,
                    "summary": summary,
                    "reason": "approval_not_required",
                    "paper_mode": self.paper_mode,
                },
            )
            return ApprovalDecision(
                allowed=True,
                reason="approval_not_required",
                request_status="not_required",
                status="not_required",
                paper_mode=self.paper_mode,
                event=event,
            )

        existing = (
            self.store.find_latest_approval_request(action_type, entity_type, entity_id)
            if self.store is not None
            else None
        )
        if existing is not None:
            if existing.status == "approved":
                reason = "approval_granted"
                allowed = True
                status = "approved"
            elif existing.status == "rejected":
                reason = "approval_rejected"
                allowed = False
                status = "rejected"
            else:
                reason = "approval_pending"
                allowed = False
                status = "pending"
            event = self._record_event(
                entity_type=entity_type,
                entity_id=entity_id,
                status=status,
                payload={
                    "action_type": action_type,
                    "summary": summary,
                    "reason": reason,
                    "paper_mode": self.paper_mode,
                    "request_id": existing.id,
                },
            )
            return ApprovalDecision(
                allowed=allowed,
                reason=reason,
                request_status=existing.status,
                request=existing,
                status=status,
                paper_mode=self.paper_mode,
                event=event,
            )

        request = ApprovalRequest(
            action_type=action_type,
            entity_type=entity_type,
            entity_id=entity_id,
            summary=summary,
            requested_by=requested_by,
            payload=payload or {},
        )
        if self.store is not None:
            request = self.store.create_approval_request(request)
        event = self._record_event(
            entity_type=entity_type,
            entity_id=entity_id,
            status="pending",
            payload={
                "action_type": action_type,
                "summary": summary,
                "reason": "approval_required",
                "paper_mode": self.paper_mode,
                "request_id": request.id,
            },
        )
        return ApprovalDecision(
            allowed=False,
            reason="approval_required",
            request_status=request.status,
            request=request,
            status="pending",
            paper_mode=self.paper_mode,
            event=event,
        )

    def route(
        self,
        action: CRMInteraction | ApprovalRequest,
        execute: ActionExecutor | None = None,
        *,
        requested_by: str = "jj-n",
    ) -> ApprovalDecision:
        if isinstance(action, ApprovalRequest):
            decision = self.require_approval(
                action_type=action.action_type,
                entity_type=action.entity_type,
                entity_id=action.entity_id,
                summary=action.summary,
                payload=action.payload,
                requested_by=action.requested_by or requested_by,
            )
            return ApprovalDecision(
                **{
                    **decision.__dict__,
                    "status": decision.status or decision.request_status,
                }
            )

        interaction = action
        if interaction.approval_class is ApprovalClass.AUTO:
            executed = False
            status = "paper_logged" if self.paper_mode else "executed"
            if not self.paper_mode and execute is not None:
                execute(interaction)
                executed = True
            event = self._record_event(
                entity_type="interaction",
                entity_id=interaction.id,
                status=status,
                payload=self._interaction_payload(interaction),
            )
            return ApprovalDecision(
                allowed=True,
                reason="auto_approved",
                request_status="not_required",
                interaction_id=interaction.id,
                approval_class=interaction.approval_class,
                status=status,
                executed=executed,
                paper_mode=self.paper_mode,
                event=event,
            )

        request_payload = self._interaction_payload(interaction)
        if interaction.approval_class is ApprovalClass.ESCALATE:
            request_payload["escalation_required"] = True

        decision = self.require_approval(
            action_type=interaction.action,
            entity_type="interaction",
            entity_id=interaction.id,
            summary=f"{interaction.engine}:{interaction.action}",
            payload=request_payload,
            requested_by=requested_by,
        )

        if interaction.approval_class is ApprovalClass.REVIEW:
            if decision.allowed:
                executed = False
                if not self.paper_mode and execute is not None:
                    execute(interaction)
                    executed = True
                status = "executed" if executed else "approved"
                event = self._record_event(
                    entity_type="interaction",
                    entity_id=interaction.id,
                    status=status,
                    payload=request_payload,
                )
                return ApprovalDecision(
                    **{
                        **decision.__dict__,
                        "interaction_id": interaction.id,
                        "approval_class": interaction.approval_class,
                        "status": status,
                        "executed": executed,
                        "queued": False,
                        "blocked": False,
                        "event": event,
                    }
                )
            self._queue_interaction(interaction, ApprovalClass.REVIEW)
            event = self._record_event(
                entity_type="interaction",
                entity_id=interaction.id,
                status="queued_review",
                payload=request_payload,
            )
            return ApprovalDecision(
                **{
                    **decision.__dict__,
                    "interaction_id": interaction.id,
                    "approval_class": interaction.approval_class,
                    "status": "queued_review",
                    "queued": True,
                    "blocked": False,
                    "event": event,
                }
            )

        if decision.allowed:
            executed = False
            if not self.paper_mode and execute is not None:
                execute(interaction)
                executed = True
            status = "executed" if executed else "approved_escalation"
            event = self._record_event(
                entity_type="interaction",
                entity_id=interaction.id,
                status=status,
                payload=request_payload,
            )
            return ApprovalDecision(
                **{
                    **decision.__dict__,
                    "interaction_id": interaction.id,
                    "approval_class": interaction.approval_class,
                    "status": status,
                    "executed": executed,
                    "queued": False,
                    "blocked": False,
                    "event": event,
                }
            )

        self._queue_interaction(interaction, ApprovalClass.ESCALATE)
        event = self._record_event(
            entity_type="interaction",
            entity_id=interaction.id,
            status="blocked_escalation",
            payload=request_payload,
        )
        return ApprovalDecision(
            **{
                **decision.__dict__,
                "interaction_id": interaction.id,
                "approval_class": interaction.approval_class,
                "status": "blocked_escalation",
                "queued": False,
                "blocked": True,
                "event": event,
            }
        )

    def approve(
        self,
        target: int | str,
        *,
        reviewed_by: str = "system",
        review_notes: str = "",
    ) -> ApprovalRequest | bool:
        request = self._resolve_request(target)
        if request is None:
            return False
        updated = (
            self.store.update_approval_request_status(
                request.id or 0,
                status="approved",
                reviewed_by=reviewed_by,
                review_notes=review_notes,
            )
            if self.store is not None
            else ApprovalRequest(
                id=request.id,
                action_type=request.action_type,
                entity_type=request.entity_type,
                entity_id=request.entity_id,
                summary=request.summary,
                status="approved",
                requested_by=request.requested_by,
                reviewed_by=reviewed_by,
                review_notes=review_notes,
                payload=request.payload,
                created_at=request.created_at,
                updated_at=utc_now(),
                reviewed_at=utc_now(),
            )
        )
        self._approved_ids.add(updated.entity_id)
        self._remove_from_queue(updated.entity_id)
        self._record_event(
            entity_type=updated.entity_type,
            entity_id=updated.entity_id,
            status="approved",
            payload={
                "request_id": updated.id,
                "reviewed_by": reviewed_by,
                "review_notes": review_notes,
                "paper_mode": self.paper_mode,
            },
        )
        if isinstance(target, str):
            return True
        return updated

    def reject(
        self,
        target: int | str,
        *,
        reviewed_by: str = "system",
        review_notes: str = "",
    ) -> ApprovalRequest | bool:
        request = self._resolve_request(target)
        if request is None:
            return False
        updated = (
            self.store.update_approval_request_status(
                request.id or 0,
                status="rejected",
                reviewed_by=reviewed_by,
                review_notes=review_notes,
            )
            if self.store is not None
            else ApprovalRequest(
                id=request.id,
                action_type=request.action_type,
                entity_type=request.entity_type,
                entity_id=request.entity_id,
                summary=request.summary,
                status="rejected",
                requested_by=request.requested_by,
                reviewed_by=reviewed_by,
                review_notes=review_notes,
                payload=request.payload,
                created_at=request.created_at,
                updated_at=utc_now(),
                reviewed_at=utc_now(),
            )
        )
        self._remove_from_queue(updated.entity_id)
        self._record_event(
            entity_type=updated.entity_type,
            entity_id=updated.entity_id,
            status="rejected",
            payload={
                "request_id": updated.id,
                "reviewed_by": reviewed_by,
                "review_notes": review_notes,
                "paper_mode": self.paper_mode,
            },
        )
        if isinstance(target, str):
            return True
        return updated

    def flush_events(self) -> list[dict[str, Any]]:
        events = list(self.events)
        self.events.clear()
        return events

    def _queue_interaction(self, interaction: CRMInteraction, approval_class: ApprovalClass) -> None:
        queue = self._review_queue if approval_class is ApprovalClass.REVIEW else self._escalation_queue
        if interaction.id not in {item.id for item in queue}:
            queue.append(interaction)

    def _remove_from_queue(self, interaction_id: str) -> None:
        self._review_queue = [item for item in self._review_queue if item.id != interaction_id]
        self._escalation_queue = [item for item in self._escalation_queue if item.id != interaction_id]

    def _load_queue(
        self,
        fallback_queue: list[CRMInteraction],
        approval_class: ApprovalClass,
    ) -> list[CRMInteraction]:
        if self.store is None:
            return list(fallback_queue)
        queue: list[CRMInteraction] = []
        for request in self.store.list_approval_requests(status="pending"):
            if request.entity_type != "interaction":
                continue
            interaction = self._interaction_from_request(request)
            if interaction is None or interaction.approval_class is not approval_class:
                continue
            queue.append(interaction)
        return queue

    def _resolve_request(self, target: int | str) -> ApprovalRequest | None:
        if isinstance(target, int):
            return self.store.get_approval_request(target) if self.store is not None else None
        if self.store is not None:
            for request in reversed(self.store.list_approval_requests()):
                if request.entity_id == target:
                    return request
        interaction = next(
            (item for item in self._review_queue + self._escalation_queue if item.id == target),
            None,
        )
        if interaction is None:
            return None
        return ApprovalRequest(
            action_type=interaction.action,
            entity_type="interaction",
            entity_id=interaction.id,
            summary=f"{interaction.engine}:{interaction.action}",
            payload=self._interaction_payload(interaction),
        )

    def _interaction_from_request(self, request: ApprovalRequest) -> CRMInteraction | None:
        payload = request.payload
        approval_value = payload.get("approval_class")
        if not isinstance(approval_value, str):
            return None
        try:
            approval_class = ApprovalClass(approval_value)
        except ValueError:
            return None
        return CRMInteraction(
            id=request.entity_id,
            lead_id=str(payload.get("lead_id", "")),
            engine=str(payload.get("engine", request.entity_type)),
            action=str(payload.get("action", request.action_type)),
            approval_class=approval_class,
            approved=request.status == "approved",
            result=str(payload.get("result", "")),
            timestamp=str(payload.get("timestamp", request.created_at or utc_now())),
            metadata=dict(payload.get("metadata", {})),
        )

    def _record_event(
        self,
        *,
        entity_type: str,
        entity_id: str,
        status: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        event = {
            "event_type": "approval_gate",
            "timestamp": utc_now(),
            "entity_type": entity_type,
            "entity_id": entity_id,
            "status": status,
            "paper_mode": self.paper_mode,
            **payload,
        }
        self.events.append(event)
        if self.store is not None:
            self.store.record_telemetry_event(
                TelemetryEvent(
                    event_type="approval_gate",
                    entity_type=entity_type,
                    entity_id=entity_id,
                    status=status,
                    payload=event,
                )
            )
        return event

    @staticmethod
    def _interaction_payload(interaction: CRMInteraction) -> dict[str, Any]:
        return {
            "lead_id": interaction.lead_id,
            "engine": interaction.engine,
            "action": interaction.action,
            "approval_class": interaction.approval_class.value,
            "approved": interaction.approved,
            "result": interaction.result,
            "timestamp": interaction.timestamp,
            "metadata": dict(interaction.metadata),
        }
