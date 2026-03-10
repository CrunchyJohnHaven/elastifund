from __future__ import annotations

import json
import time
from pathlib import Path

from nontrading.revenue_audit.config import DEFAULT_PRICING, RevenueAuditSettings
from nontrading.revenue_audit.contracts import (
    AuditBundle,
    CreateCheckoutRequest,
    IssueEvidence,
    ProspectProfile,
)
from nontrading.revenue_audit.fulfillment import RevenueAuditFulfillmentService
from nontrading.revenue_audit.service import RevenueAuditCheckoutService
from nontrading.revenue_audit.store import RevenueAuditStore
from nontrading.revenue_audit.stripe import generate_signature_header
from nontrading.store import RevenueStore
from nontrading.telemetry import NonTradingTelemetry


class _FakeStripeCheckoutClient:
    def create_checkout_session(
        self,
        *,
        amount_cents: int,
        currency: str,
        success_url: str,
        cancel_url: str,
        customer_email: str = "",
        client_reference_id: str = "",
        metadata: dict[str, str] | None = None,
        line_item_name: str,
        line_item_description: str = "",
    ) -> dict[str, object]:
        assert amount_cents > 0
        return {
            "id": "cs_test_123",
            "url": "https://checkout.stripe.test/session/cs_test_123",
            "payment_intent": "pi_test_123",
            "status": "open",
            "expires_at": "2026-03-10T12:00:00+00:00",
            "raw": {
                "amount_cents": amount_cents,
                "currency": currency,
                "success_url": success_url,
                "cancel_url": cancel_url,
                "customer_email": customer_email,
                "client_reference_id": client_reference_id,
                "metadata": metadata or {},
                "line_item_name": line_item_name,
                "line_item_description": line_item_description,
            },
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
        stripe_webhook_tolerance_seconds=300,
        pricing=DEFAULT_PRICING,
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


def test_paid_order_generates_delivery_artifact_and_monitor_delta(tmp_path: Path) -> None:
    order_id, fulfillment_service, audit_store, revenue_store = _seed_paid_order(tmp_path)

    execution = fulfillment_service.fulfill_order(order_id)

    order = audit_store.get_order(order_id)
    assert order is not None
    assert order.fulfillment_status == "delivered"
    assert execution.job.status == "completed"
    assert len(execution.artifact_paths) == 2
    assert all(Path(path).exists() for path in execution.artifact_paths)

    delivery_payload = json.loads(Path(execution.artifact_paths[0]).read_text(encoding="utf-8"))
    assert delivery_payload["artifact"] == "revenue_audit_delivery"
    assert delivery_payload["payment"]["payments_collected_usd"] == 1500.0
    assert len(delivery_payload["audit_bundle"]["issues"]) == 2

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

    assert "artifact_generated" in statuses
    assert "delivered" in statuses
    assert "monitor_rerun_completed" in statuses
    assert snapshot["phase"]["claim_status"] == "actual_revenue_recorded"
    assert snapshot["commercial"]["revenue_won_usd"] == 1500.0
    assert snapshot["fulfillment"]["delivered_jobs"] == 1
    assert snapshot["fulfillment"]["monitor_runs_completed"] == 1
