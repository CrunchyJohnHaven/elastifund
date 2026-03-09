from __future__ import annotations

from nontrading.approval_gate import ApprovalGate
from nontrading.crm_schema import ApprovalClass, Interaction


def make_interaction(interaction_id: str, approval_class: ApprovalClass) -> Interaction:
    return Interaction(
        id=interaction_id,
        lead_id="lead-1",
        engine="outreach",
        action="draft_outreach",
        approval_class=approval_class,
    )


def test_auto_route_logs_without_execution_in_paper_mode() -> None:
    gate = ApprovalGate(paper_mode=True)
    called: list[str] = []

    decision = gate.route(make_interaction("auto-paper", ApprovalClass.AUTO), execute=lambda _: called.append("run"))

    assert decision.status == "paper_logged"
    assert not decision.executed
    assert called == []


def test_auto_route_executes_callback_when_not_in_paper_mode() -> None:
    gate = ApprovalGate(paper_mode=False)
    called: list[str] = []

    decision = gate.route(make_interaction("auto-live", ApprovalClass.AUTO), execute=lambda _: called.append("run"))

    assert decision.status == "executed"
    assert decision.executed
    assert called == ["run"]


def test_review_route_queues_for_human_review() -> None:
    gate = ApprovalGate()

    decision = gate.route(make_interaction("review-1", ApprovalClass.REVIEW))

    assert decision.queued
    assert not decision.blocked
    assert [interaction.id for interaction in gate.review_queue] == ["review-1"]


def test_escalate_route_blocks_until_explicit_approval() -> None:
    gate = ApprovalGate()

    decision = gate.route(make_interaction("escalate-1", ApprovalClass.ESCALATE))

    assert decision.blocked
    assert decision.status == "blocked_escalation"
    assert [interaction.id for interaction in gate.escalation_queue] == ["escalate-1"]


def test_approve_removes_review_queue_item() -> None:
    gate = ApprovalGate()
    gate.route(make_interaction("review-2", ApprovalClass.REVIEW))

    approved = gate.approve("review-2")

    assert approved
    assert gate.review_queue == []
    assert "review-2" in gate.approved_ids


def test_approve_unknown_item_returns_false() -> None:
    gate = ApprovalGate()

    assert not gate.approve("missing")
