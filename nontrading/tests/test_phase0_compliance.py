from __future__ import annotations

from pathlib import Path

from nontrading.compliance import ComplianceGuard
from nontrading.models import TelemetryEvent
from nontrading.store import RevenueStore


def make_store(tmp_path: Path) -> RevenueStore:
    return RevenueStore(tmp_path / "revenue_agent.db")


def make_guard(tmp_path: Path, *, daily_limit: int = 2) -> tuple[RevenueStore, ComplianceGuard]:
    store = make_store(tmp_path)
    guard = ComplianceGuard(
        store,
        verified_domains={"elastifund.io"},
        daily_message_limit=daily_limit,
    )
    return store, guard


def test_verified_domain_is_required(tmp_path: Path) -> None:
    _, guard = make_guard(tmp_path)

    decision = guard.evaluate_outreach(
        sender_name="JJ-N",
        sender_email="ops@unverified.example",
        recipient_email="buyer@example.com",
    )

    assert not decision.allowed
    assert decision.reason == "sender_domain_unverified"


def test_sender_identity_must_be_present(tmp_path: Path) -> None:
    _, guard = make_guard(tmp_path)

    decision = guard.evaluate_outreach(
        sender_name="",
        sender_email="ops@elastifund.io",
        recipient_email="buyer@example.com",
    )

    assert not decision.allowed
    assert decision.reason == "sender_identity_unverified"


def test_suppression_blocks_outreach(tmp_path: Path) -> None:
    store, guard = make_guard(tmp_path)
    store.append_suppression("buyer@example.com", "unsubscribe", "test")

    decision = guard.evaluate_outreach(
        sender_name="JJ-N",
        sender_email="ops@elastifund.io",
        recipient_email="buyer@example.com",
    )

    assert not decision.allowed
    assert decision.reason == "recipient_suppressed"


def test_register_unsubscribe_appends_suppression(tmp_path: Path) -> None:
    store, guard = make_guard(tmp_path)

    guard.register_unsubscribe("buyer@example.com")

    assert store.is_suppressed("buyer@example.com")


def test_rate_limit_blocks_after_message_sent_events(tmp_path: Path) -> None:
    store, guard = make_guard(tmp_path, daily_limit=1)
    store.record_telemetry_event(
        TelemetryEvent(
            event_type="message_sent",
            entity_type="message",
            entity_id="1",
            payload={"environment": "paper"},
        )
    )

    decision = guard.evaluate_outreach(
        sender_name="JJ-N",
        sender_email="ops@elastifund.io",
        recipient_email="buyer@example.com",
    )

    assert not decision.allowed
    assert decision.reason == "daily_rate_limit_exceeded"


def test_compliant_outreach_passes(tmp_path: Path) -> None:
    _, guard = make_guard(tmp_path)

    decision = guard.evaluate_outreach(
        sender_name="JJ-N",
        sender_email="ops@elastifund.io",
        recipient_email="buyer@example.com",
    )

    assert decision.allowed
    assert decision.metadata["daily_message_limit"] == 2
