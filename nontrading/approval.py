"""Paper-mode approval gate for JJ-N outreach actions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nontrading.models import ApprovalRequest
from nontrading.store import RevenueStore


@dataclass(frozen=True)
class ApprovalDecision:
    allowed: bool
    reason: str
    request_status: str
    request: ApprovalRequest | None = None


class ApprovalGate:
    """Requires human approval for Phase 0 actions while paper mode is active."""

    def __init__(self, store: RevenueStore, *, paper_mode: bool = True):
        self.store = store
        self.paper_mode = paper_mode

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
            return ApprovalDecision(
                allowed=True,
                reason="approval_not_required",
                request_status="not_required",
            )

        existing = self.store.find_latest_approval_request(action_type, entity_type, entity_id)
        if existing is not None:
            if existing.status == "approved":
                return ApprovalDecision(
                    allowed=True,
                    reason="approval_granted",
                    request_status=existing.status,
                    request=existing,
                )
            if existing.status == "rejected":
                return ApprovalDecision(
                    allowed=False,
                    reason="approval_rejected",
                    request_status=existing.status,
                    request=existing,
                )
            return ApprovalDecision(
                allowed=False,
                reason="approval_pending",
                request_status=existing.status,
                request=existing,
            )

        request = self.store.create_approval_request(
            ApprovalRequest(
                action_type=action_type,
                entity_type=entity_type,
                entity_id=entity_id,
                summary=summary,
                requested_by=requested_by,
                payload=payload or {},
            )
        )
        return ApprovalDecision(
            allowed=False,
            reason="approval_required",
            request_status=request.status,
            request=request,
        )

    def approve(self, request_id: int, *, reviewed_by: str, review_notes: str = "") -> ApprovalRequest:
        return self.store.update_approval_request_status(
            request_id,
            status="approved",
            reviewed_by=reviewed_by,
            review_notes=review_notes,
        )

    def reject(self, request_id: int, *, reviewed_by: str, review_notes: str = "") -> ApprovalRequest:
        return self.store.update_approval_request_status(
            request_id,
            status="rejected",
            reviewed_by=reviewed_by,
            review_notes=review_notes,
        )
