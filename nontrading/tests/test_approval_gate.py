from __future__ import annotations

from pathlib import Path

from nontrading.approval import ApprovalGate
from nontrading.store import RevenueStore


def make_store(tmp_path: Path) -> RevenueStore:
    return RevenueStore(tmp_path / "revenue_agent.db")


def test_paper_mode_creates_pending_request(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    gate = ApprovalGate(store, paper_mode=True)

    decision = gate.require_approval(
        action_type="outreach_message",
        entity_type="message",
        entity_id="123",
        summary="Approve outbound message",
    )

    assert not decision.allowed
    assert decision.reason == "approval_required"
    assert decision.request is not None
    assert decision.request.status == "pending"


def test_reuses_existing_pending_request(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    gate = ApprovalGate(store, paper_mode=True)
    first = gate.require_approval(
        action_type="outreach_message",
        entity_type="message",
        entity_id="123",
        summary="Approve outbound message",
    )

    second = gate.require_approval(
        action_type="outreach_message",
        entity_type="message",
        entity_id="123",
        summary="Approve outbound message",
    )

    assert first.request is not None
    assert second.request is not None
    assert first.request.id == second.request.id
    assert second.reason == "approval_pending"


def test_approve_allows_action_on_retry(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    gate = ApprovalGate(store, paper_mode=True)
    first = gate.require_approval(
        action_type="outreach_message",
        entity_type="message",
        entity_id="123",
        summary="Approve outbound message",
    )
    assert first.request is not None

    gate.approve(first.request.id or 0, reviewed_by="john", review_notes="looks good")
    second = gate.require_approval(
        action_type="outreach_message",
        entity_type="message",
        entity_id="123",
        summary="Approve outbound message",
    )

    assert second.allowed
    assert second.reason == "approval_granted"
    assert second.request is not None
    assert second.request.reviewed_by == "john"


def test_reject_blocks_action_on_retry(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    gate = ApprovalGate(store, paper_mode=True)
    first = gate.require_approval(
        action_type="outreach_message",
        entity_type="message",
        entity_id="123",
        summary="Approve outbound message",
    )
    assert first.request is not None

    gate.reject(first.request.id or 0, reviewed_by="john", review_notes="hold")
    second = gate.require_approval(
        action_type="outreach_message",
        entity_type="message",
        entity_id="123",
        summary="Approve outbound message",
    )

    assert not second.allowed
    assert second.reason == "approval_rejected"
    assert second.request is not None
    assert second.request.status == "rejected"


def test_non_paper_mode_skips_request_creation(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    gate = ApprovalGate(store, paper_mode=False)

    decision = gate.require_approval(
        action_type="outreach_message",
        entity_type="message",
        entity_id="123",
        summary="Approve outbound message",
    )

    assert decision.allowed
    assert decision.request is None
    assert store.list_approval_requests() == []


def test_list_approval_requests_can_filter_by_status(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    gate = ApprovalGate(store, paper_mode=True)
    first = gate.require_approval(
        action_type="outreach_message",
        entity_type="message",
        entity_id="123",
        summary="Approve outbound message",
    )
    second = gate.require_approval(
        action_type="outreach_message",
        entity_type="message",
        entity_id="124",
        summary="Approve second outbound message",
    )
    assert first.request is not None
    assert second.request is not None

    gate.approve(first.request.id or 0, reviewed_by="john")

    approved = store.list_approval_requests(status="approved")
    pending = store.list_approval_requests(status="pending")

    assert len(approved) == 1
    assert approved[0].entity_id == "123"
    assert len(pending) == 1
    assert pending[0].entity_id == "124"
