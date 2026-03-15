from __future__ import annotations

import json
import time
from pathlib import Path

from nontrading.revenue_audit.config import (
    DEFAULT_PRICING,
    DEFAULT_RECURRING_MONITOR_PRICING,
    RevenueAuditSettings,
)
from nontrading.revenue_audit.contracts import (
    AuditBundle,
    CreateCheckoutRequest,
    IssueEvidence,
    ProspectProfile,
)
from nontrading.revenue_audit.fulfillment import RevenueAuditFulfillmentService
from nontrading.revenue_audit.recurring_monitor import build_recurring_monitor_summary
from nontrading.revenue_audit.service import RevenueAuditCheckoutService
from nontrading.revenue_audit.store import RevenueAuditStore
from nontrading.revenue_audit.stripe import generate_signature_header
from nontrading.store import RevenueStore
from nontrading.telemetry import NonTradingTelemetry


class _FakeStripeCheckoutClient:
    def __init__(self) -> None:
        self.calls = 0

    def create_checkout_session(self, **kwargs: object) -> dict[str, object]:
        self.calls += 1
        assert int(kwargs["amount_cents"]) > 0
        return {
            "id": f"cs_test_{self.calls:03d}",
            "url": f"https://checkout.stripe.test/session/cs_test_{self.calls:03d}",
            "payment_intent": f"pi_test_{self.calls:03d}",
            "status": "open",
            "expires_at": "2026-03-10T12:00:00+00:00",
            "raw": dict(kwargs),
        }


def _build_runtime(tmp_path: Path) -> tuple[RevenueAuditCheckoutService, RevenueAuditFulfillmentService, RevenueAuditStore, RevenueStore]:
    db_path = tmp_path / "revenue_agent.db"
    revenue_store = RevenueStore(db_path)
    audit_store = RevenueAuditStore(db_path)
    telemetry = NonTradingTelemetry(revenue_store)
    settings = RevenueAuditSettings(
        db_path=db_path,
        offer_slug="website-growth-audit",
        currency="USD",
        stripe_secret_key="sk_test",
        stripe_webhook_secret="whsec_test",
        stripe_api_base="https://api.stripe.com",
        stripe_success_url="https://elastifund.io/success?session_id={CHECKOUT_SESSION_ID}",
        stripe_cancel_url="https://elastifund.io/cancel",
        recurring_monitor_success_url="https://elastifund.io/monitor/success?session_id={CHECKOUT_SESSION_ID}",
        recurring_monitor_cancel_url="https://elastifund.io/monitor/cancel",
        stripe_webhook_tolerance_seconds=300,
        pricing=DEFAULT_PRICING,
        recurring_monitor_pricing=DEFAULT_RECURRING_MONITOR_PRICING,
    )
    checkout_service = RevenueAuditCheckoutService(
        settings,
        audit_store=audit_store,
        revenue_store=revenue_store,
        telemetry=telemetry,
        stripe_client=_FakeStripeCheckoutClient(),
    )
    fulfillment_service = RevenueAuditFulfillmentService(
        audit_store=audit_store,
        revenue_store=revenue_store,
        telemetry=telemetry,
        artifact_root=tmp_path / "reports" / "nontrading",
    )
    return checkout_service, fulfillment_service, audit_store, revenue_store


def _seed_paid_order(tmp_path: Path) -> tuple[str, RevenueAuditFulfillmentService, RevenueAuditStore, RevenueStore]:
    checkout_service, fulfillment_service, audit_store, revenue_store = _build_runtime(tmp_path)
    prospect = ProspectProfile(
        business_name="Acme Builders",
        website_url="https://acme-builders.test",
        contact_email="owner@acme-builders.test",
        contact_name="Pat Jones",
        industry="construction",
    )
    baseline_bundle = AuditBundle(
        bundle_id="bundle_baseline_001",
        prospect=prospect,
        issues=(
            IssueEvidence(
                detector_key="pagespeed",
                summary="Homepage is slow on mobile.",
                severity="high",
                evidence_url="https://acme-builders.test",
                evidence_snippet="Largest Contentful Paint above 4s.",
            ),
            IssueEvidence(
                detector_key="cta-check",
                summary="Hero CTA is too vague.",
                severity="medium",
                evidence_url="https://acme-builders.test",
                evidence_snippet="No primary conversion action appears above the fold.",
            ),
        ),
        score={
            "purchase_probability": 0.82,
            "expected_margin_usd": 980.0,
            "confidence_score": 0.79,
        },
        summary="Two deterministic issues warrant a paid audit.",
    )
    request = CreateCheckoutRequest(
        price_key="growth",
        customer_email="owner@acme-builders.test",
        customer_name="Pat Jones",
        business_name="Acme Builders",
        website_url="https://acme-builders.test",
        success_url="https://elastifund.io/success?session_id={CHECKOUT_SESSION_ID}",
        cancel_url="https://elastifund.io/cancel",
        prospect_profile=prospect,
        audit_bundle=baseline_bundle,
    )
    checkout_payload = checkout_service.create_checkout_session(request)
    order_id = checkout_payload["order"]["order_id"]
    webhook_payload = {
        "id": "evt_test_123",
        "type": "checkout.session.completed",
        "created": int(time.time()),
        "data": {
            "object": {
                "id": checkout_payload["checkout_session"]["provider_session_id"],
                "payment_intent": checkout_payload["checkout_session"]["provider_payment_intent_id"],
                "status": "complete",
                "payment_status": "paid",
                "amount_total": 150000,
                "currency": "usd",
                "metadata": {"order_id": order_id},
            }
        },
    }
    payload_bytes = json.dumps(webhook_payload).encode("utf-8")
    signature = generate_signature_header(
        payload_bytes,
        checkout_service.settings.stripe_webhook_secret,
        timestamp=webhook_payload["created"],
    )
    result = checkout_service.handle_stripe_webhook(payload_bytes, signature)
    assert result["status"] == "processed"
    assert audit_store.get_order(order_id).status == "paid"
    return order_id, fulfillment_service, audit_store, revenue_store


def _seed_paid_order_runtime(
    tmp_path: Path,
) -> tuple[str, RevenueAuditCheckoutService, RevenueAuditFulfillmentService, RevenueAuditStore, RevenueStore]:
    checkout_service, fulfillment_service, audit_store, revenue_store = _build_runtime(tmp_path)
    prospect = ProspectProfile(
        business_name="Acme Builders",
        website_url="https://acme-builders.test",
        contact_email="owner@acme-builders.test",
        contact_name="Pat Jones",
        industry="construction",
    )
    baseline_bundle = AuditBundle(
        bundle_id="bundle_runtime_001",
        prospect=prospect,
        issues=(
            IssueEvidence(
                detector_key="pagespeed",
                summary="Homepage is slow on mobile.",
                severity="high",
                evidence_url="https://acme-builders.test",
            ),
        ),
        score={
            "purchase_probability": 0.82,
            "expected_margin_usd": 980.0,
            "confidence_score": 0.79,
        },
        summary="Audit findings justify a paid order.",
    )
    checkout_payload = checkout_service.create_checkout_session(
        CreateCheckoutRequest(
            price_key="growth",
            customer_email="owner@acme-builders.test",
            customer_name="Pat Jones",
            business_name="Acme Builders",
            website_url="https://acme-builders.test",
            success_url="https://elastifund.io/success?session_id={CHECKOUT_SESSION_ID}",
            cancel_url="https://elastifund.io/cancel",
            prospect_profile=prospect,
            audit_bundle=baseline_bundle,
        )
    )
    order_id = checkout_payload["order"]["order_id"]
    webhook_payload = {
        "id": "evt_runtime_001",
        "type": "checkout.session.completed",
        "created": int(time.time()),
        "data": {
            "object": {
                "id": checkout_payload["checkout_session"]["provider_session_id"],
                "payment_intent": checkout_payload["checkout_session"]["provider_payment_intent_id"],
                "status": "complete",
                "payment_status": "paid",
                "amount_total": 150000,
                "currency": "usd",
                "metadata": {"order_id": order_id},
            }
        },
    }
    payload_bytes = json.dumps(webhook_payload).encode("utf-8")
    signature = generate_signature_header(
        payload_bytes,
        checkout_service.settings.stripe_webhook_secret,
        timestamp=webhook_payload["created"],
    )
    checkout_service.handle_stripe_webhook(payload_bytes, signature)
    return order_id, checkout_service, fulfillment_service, audit_store, revenue_store


def test_paid_order_generates_delivery_artifact_and_monitor_delta(tmp_path: Path) -> None:
    order_id, fulfillment_service, audit_store, revenue_store = _seed_paid_order(tmp_path)

    execution = fulfillment_service.fulfill_order(order_id)

    order = audit_store.get_order(order_id)
    assert order is not None
    assert order.fulfillment_status == "delivered"
    assert execution.job.status == "completed"
    assert len(execution.artifact_paths) == 2
    assert all(Path(path).exists() for path in execution.artifact_paths)
    assert Path(execution.delivery_checklist_path).exists()
    assert Path(execution.delivery_pack_path).exists()

    delivery_payload = json.loads(Path(execution.artifact_paths[0]).read_text(encoding="utf-8"))
    assert delivery_payload["artifact"] == "revenue_audit_delivery"
    assert delivery_payload["payment"]["payments_collected_usd"] == 1500.0
    assert len(delivery_payload["audit_bundle"]["issues"]) == 2
    assert delivery_payload["recurring_monitor"]["status"] == "staged"
    assert delivery_payload["recurring_monitor"]["offer"]["slug"] == "website-growth-audit-recurring-monitor"
    checklist_payload = json.loads(Path(execution.delivery_checklist_path).read_text(encoding="utf-8"))
    assert checklist_payload["artifact"] == "revenue_audit_delivery_checklist"
    pack_payload = json.loads(Path(execution.delivery_pack_path).read_text(encoding="utf-8"))
    assert pack_payload["artifact"] == "revenue_audit_delivery_pack"
    assert pack_payload["customer_delivery"]["primary_artifact_path"].endswith("paid_audit.md")
    assert pack_payload["monitor_contract"]["reuse_surface"] == "recurring_monitor"
    assert pack_payload["recurring_monitor"]["offer"]["slug"] == "website-growth-audit-recurring-monitor"

    current_bundle = AuditBundle(
        bundle_id="bundle_monitor_002",
        prospect=order.prospect_profile,
        issues=(
            IssueEvidence(
                detector_key="pagespeed",
                summary="Homepage is still slow on mobile.",
                severity="critical",
                evidence_url="https://acme-builders.test",
            ),
            IssueEvidence(
                detector_key="social-proof",
                summary="Service pages still lack testimonials.",
                severity="medium",
                evidence_url="https://acme-builders.test/services",
            ),
        ),
        score={
            "purchase_probability": 0.74,
            "expected_margin_usd": 920.0,
            "confidence_score": 0.76,
        },
        summary="Monitor rerun after purchase.",
    )
    monitor_execution = fulfillment_service.run_monitor(order_id, current_bundle=current_bundle)
    order = audit_store.get_order(order_id)
    assert order is not None

    assert monitor_execution.monitor_run.status == "completed"
    assert all(Path(path).exists() for path in monitor_execution.artifact_paths)
    delta_payload = json.loads(Path(monitor_execution.artifact_paths[0]).read_text(encoding="utf-8"))
    assert delta_payload["artifact"] == "revenue_audit_monitor_delta"
    assert delta_payload["summary"]["new_issue_count"] == 1
    assert delta_payload["summary"]["resolved_issue_count"] == 1
    assert delta_payload["summary"]["persistent_issue_count"] == 1
    assert delta_payload["severity_changes"][0]["direction"] == "worsened"

    snapshot = revenue_store.public_report_snapshot()
    events = [
        event
        for event in revenue_store.list_telemetry_events()
        if event.event_type == "fulfillment_status_changed"
    ]
    statuses = [event.status for event in events]
    timeline_statuses = [entry["status"] for entry in order.metadata["status_timeline"]]
    artifacts = order.metadata["artifacts"]

    assert "artifact_generated" in statuses
    assert "delivered" in statuses
    assert "monitor_rerun_completed" in statuses
    assert timeline_statuses[:2] == ["payment_received", "fulfillment_queued"]
    assert timeline_statuses[-3:] == ["artifact_generated", "delivered", "monitor_rerun_completed"]
    assert artifacts["delivery_pack"].endswith("delivery_pack.json")
    assert artifacts["monitor_json"].endswith("monitor_delta.json")
    assert snapshot["phase"]["claim_status"] == "actual_revenue_recorded"
    assert snapshot["commercial"]["revenue_won_usd"] == 1500.0
    assert snapshot["fulfillment"]["delivered_jobs"] == 1
    assert snapshot["fulfillment"]["monitor_runs_completed"] == 1


def test_recurring_monitor_checkout_activates_enrollment_and_summary(tmp_path: Path) -> None:
    order_id, checkout_service, fulfillment_service, audit_store, _ = _seed_paid_order_runtime(tmp_path)
    fulfillment_service.fulfill_order(order_id)

    recurring_checkout = checkout_service.create_checkout_session(
        CreateCheckoutRequest(
            offer_slug="website-growth-audit-recurring-monitor",
            source_order_id=order_id,
            price_key="monitor-monthly",
            customer_email="owner@acme-builders.test",
            customer_name="Pat Jones",
        )
    )
    assert recurring_checkout["order"]["offer_slug"] == "website-growth-audit-recurring-monitor"
    assert recurring_checkout["checkout_session"]["metadata"]["mode"] == "subscription"
    assert recurring_checkout["checkout_session"]["metadata"]["billing_interval"] == "month"
    enrollment = audit_store.find_recurring_monitor_enrollment_by_audit_order(order_id)
    assert enrollment is not None
    assert enrollment.status == "checkout_pending"

    monitor_order_id = recurring_checkout["order"]["order_id"]
    webhook_payload = {
        "id": "evt_monitor_paid_001",
        "type": "checkout.session.completed",
        "created": int(time.time()),
        "data": {
            "object": {
                "id": recurring_checkout["checkout_session"]["provider_session_id"],
                "payment_intent": "",
                "subscription": "sub_monitor_001",
                "status": "complete",
                "payment_status": "paid",
                "amount_total": 29900,
                "currency": "usd",
                "metadata": {"order_id": monitor_order_id, "source_order_id": order_id},
            }
        },
    }
    payload_bytes = json.dumps(webhook_payload).encode("utf-8")
    signature = generate_signature_header(
        payload_bytes,
        checkout_service.settings.stripe_webhook_secret,
        timestamp=webhook_payload["created"],
    )
    result = checkout_service.handle_stripe_webhook(payload_bytes, signature)
    assert result["status"] == "processed"

    active_enrollment = audit_store.find_recurring_monitor_enrollment_by_audit_order(order_id)
    assert active_enrollment is not None
    assert active_enrollment.status == "active"
    assert active_enrollment.monitor_order_id == monitor_order_id
    assert active_enrollment.provider_subscription_id == "sub_monitor_001"
    assert active_enrollment.next_run_at is not None

    order = audit_store.get_order(order_id)
    assert order is not None
    current_bundle = AuditBundle(
        bundle_id="bundle_active_monitor_002",
        prospect=order.prospect_profile,
        issues=(
            IssueEvidence(
                detector_key="pagespeed",
                summary="Homepage is still slow on mobile.",
                severity="critical",
                evidence_url="https://acme-builders.test",
            ),
        ),
        score={
            "purchase_probability": 0.74,
            "expected_margin_usd": 920.0,
            "confidence_score": 0.76,
        },
        summary="Active monitor rerun.",
    )
    fulfillment_service.run_monitor(order_id, current_bundle=current_bundle)
    active_enrollment = audit_store.find_recurring_monitor_enrollment_by_audit_order(order_id)
    assert active_enrollment is not None
    assert active_enrollment.monitor_runs_completed == 1
    assert active_enrollment.latest_monitor_run_id

    summary = build_recurring_monitor_summary(
        audit_store,
        output_path=tmp_path / "reports" / "nontrading_recurring_monitor" / "latest.json",
    )
    assert summary["status"] == "live_contract"
    assert summary["active_enrollments"] == 1
    assert summary["current_mrr_usd"] == 299.0
    assert summary["current_arr_usd"] == 3588.0
    assert summary["summary"]["delta_reports_completed"] == 1
