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
from scripts.generate_nontrading_public_report import build_public_report, write_sidecar_artifacts


class _FakeStripeCheckoutClient:
    def create_checkout_session(self, **_: object) -> dict[str, object]:
        return {
            "id": "cs_public_001",
            "url": "https://checkout.stripe.test/session/cs_public_001",
            "payment_intent": "pi_public_001",
            "status": "open",
            "expires_at": "2026-03-10T12:00:00+00:00",
            "raw": {},
        }


def test_public_report_moves_from_paid_order_seen_to_revenue_evidence(tmp_path: Path) -> None:
    db_path = tmp_path / "revenue_agent.db"
    revenue_store = RevenueStore(db_path)
    audit_store = RevenueAuditStore(db_path)
    telemetry = NonTradingTelemetry(revenue_store)
    settings = RevenueAuditSettings(
        db_path=db_path,
        offer_slug="website-growth-audit",
        currency="USD",
        stripe_secret_key="sk_test",
        stripe_webhook_secret="whsec_public",
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

    prospect = ProspectProfile(
        business_name="Beacon Roofing",
        website_url="https://beacon-roofing.test",
        contact_email="owner@beacon-roofing.test",
        contact_name="Taylor Reed",
        industry="home_services",
    )
    bundle = AuditBundle(
        bundle_id="bundle_public_001",
        prospect=prospect,
        issues=(
            IssueEvidence(
                detector_key="content-depth",
                summary="Service pages are thin and lack proof.",
                severity="high",
                evidence_url="https://beacon-roofing.test/services",
            ),
        ),
        score={
            "purchase_probability": 0.88,
            "expected_margin_usd": 1180.0,
            "confidence_score": 0.83,
        },
        summary="One strong issue justifies the paid audit.",
    )
    checkout_payload = checkout_service.create_checkout_session(
        CreateCheckoutRequest(
            price_key="growth",
            customer_email="owner@beacon-roofing.test",
            customer_name="Taylor Reed",
            business_name="Beacon Roofing",
            website_url="https://beacon-roofing.test",
            prospect_profile=prospect,
            audit_bundle=bundle,
        )
    )
    order_id = checkout_payload["order"]["order_id"]
    webhook_payload = {
        "id": "evt_public_001",
        "type": "checkout.session.completed",
        "created": int(time.time()),
        "data": {
            "object": {
                "id": "cs_public_001",
                "payment_intent": "pi_public_001",
                "status": "complete",
                "payment_status": "paid",
                "amount_total": 150000,
                "currency": "usd",
                "metadata": {"order_id": order_id},
            }
        },
    }
    payload_bytes = json.dumps(webhook_payload).encode("utf-8")
    signature = generate_signature_header(payload_bytes, settings.stripe_webhook_secret, timestamp=webhook_payload["created"])
    checkout_service.handle_stripe_webhook(payload_bytes, signature)
    paid_launch_summary_path = tmp_path / "reports" / "launch_summary_paid.json"
    paid_report = build_public_report(
        revenue_store,
        launch_summary_path=paid_launch_summary_path,
    )

    assert paid_report["headline"]["claim_status"] == "payment_recorded"
    assert paid_report["commercial"]["paid_orders_count"] == 1
    assert paid_report["commercial"]["revenue_won_usd"] == 0.0
    assert paid_report["launch_summary"]["orders_recorded"] == 1
    assert paid_report["launch_summary"]["paid_orders_seen"] == 1
    assert paid_report["launch_summary"]["delivery_artifacts_generated"] == 0
    assert paid_report["first_dollar_readiness"]["status"] == "paid_order_seen"

    fulfillment_execution = fulfillment_service.fulfill_order(order_id)
    monitor_execution = fulfillment_service.run_monitor(
        order_id,
        current_bundle=AuditBundle(
            bundle_id="bundle_public_monitor_002",
            prospect=prospect,
            issues=(
                IssueEvidence(
                    detector_key="content-depth",
                    summary="Service pages are still thin and lack proof.",
                    severity="critical",
                    evidence_url="https://beacon-roofing.test/services",
                ),
                IssueEvidence(
                    detector_key="cta-clarity",
                    summary="Homepage CTA still buries the estimate request.",
                    severity="medium",
                    evidence_url="https://beacon-roofing.test",
                ),
            ),
            score={
                "purchase_probability": 0.84,
                "expected_margin_usd": 1100.0,
                "confidence_score": 0.81,
            },
            summary="Recurring monitor rerun after paid delivery.",
        ),
    )

    report_path = tmp_path / "reports" / "nontrading_public_report.json"
    launch_summary_path = tmp_path / "reports" / "nontrading_launch_summary.json"
    status_path = tmp_path / "reports" / "nontrading_first_dollar_status.json"
    allocator_path = tmp_path / "reports" / "nontrading_allocator_input.json"
    comparison_path = tmp_path / "reports" / "nontrading_benchmark_comparison.json"
    payload = build_public_report(
        revenue_store,
        report_path=report_path,
        launch_summary_path=launch_summary_path,
        status_path=status_path,
        allocator_path=allocator_path,
        comparison_path=comparison_path,
    )
    write_sidecar_artifacts(
        payload,
        launch_summary_path=launch_summary_path,
        status_path=status_path,
        allocator_path=allocator_path,
        comparison_path=comparison_path,
    )

    assert all(Path(path).exists() for path in fulfillment_execution.artifact_paths)
    assert all(Path(path).exists() for path in monitor_execution.artifact_paths)
    assert payload["wedge"]["status"] == "revenue_evidence"
    assert payload["headline"]["claim_status"] == "actual_revenue_recorded"
    assert payload["commercial"]["paid_orders_count"] == 1
    assert payload["commercial"]["revenue_won_usd"] == 1500.0
    assert payload["launch_summary"]["orders_recorded"] == 1
    assert payload["launch_summary"]["paid_orders_seen"] == 1
    assert payload["launch_summary"]["delivery_artifacts_generated"] == 1
    assert payload["launch_summary"]["monitor_runs_completed"] == 1
    assert payload["first_dollar_readiness"]["status"] == "first_dollar_observed"
    assert payload["fulfillment"]["delivered_jobs"] == 1
    assert payload["fulfillment"]["monitor_runs_completed"] == 1
    assert json.loads(status_path.read_text(encoding="utf-8"))["status"] == "first_dollar_observed"
    assert payload["source_artifacts"]["report_artifact"].endswith("nontrading_public_report.json")
