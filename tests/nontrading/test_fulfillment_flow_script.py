from __future__ import annotations

import json
import sys
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
from nontrading.revenue_audit.service import RevenueAuditCheckoutService
from nontrading.revenue_audit.store import RevenueAuditStore
from nontrading.revenue_audit.stripe import generate_signature_header
from nontrading.store import RevenueStore
from nontrading.telemetry import NonTradingTelemetry
from scripts import run_revenue_audit_fulfillment_flow


class _FakeStripeCheckoutClient:
    def create_checkout_session(self, **_: object) -> dict[str, object]:
        return {
            "id": "cs_script_001",
            "url": "https://checkout.stripe.test/session/cs_script_001",
            "payment_intent": "pi_script_001",
            "status": "open",
            "expires_at": "2026-03-10T12:00:00+00:00",
            "raw": {},
        }


def _seed_paid_order(tmp_path: Path) -> tuple[Path, str]:
    db_path = tmp_path / "revenue_agent.db"
    revenue_store = RevenueStore(db_path)
    audit_store = RevenueAuditStore(db_path)
    telemetry = NonTradingTelemetry(revenue_store)
    settings = RevenueAuditSettings(
        db_path=db_path,
        offer_slug="website-growth-audit",
        currency="USD",
        stripe_secret_key="sk_test",
        stripe_webhook_secret="whsec_script",
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
    prospect = ProspectProfile(
        business_name="Script Builders",
        website_url="https://script-builders.test",
        contact_email="owner@script-builders.test",
        contact_name="Pat Script",
        industry="construction",
    )
    bundle = AuditBundle(
        bundle_id="bundle_script_001",
        prospect=prospect,
        issues=(
            IssueEvidence(
                detector_key="pagespeed",
                summary="Homepage is slow on mobile.",
                severity="high",
                evidence_url="https://script-builders.test",
            ),
        ),
        summary="Script-seeded paid audit bundle.",
    )
    checkout_payload = checkout_service.create_checkout_session(
        CreateCheckoutRequest(
            price_key="growth",
            customer_email="owner@script-builders.test",
            customer_name="Pat Script",
            business_name="Script Builders",
            website_url="https://script-builders.test",
            prospect_profile=prospect,
            audit_bundle=bundle,
        )
    )
    order_id = checkout_payload["order"]["order_id"]
    webhook_payload = {
        "id": "evt_script_001",
        "type": "checkout.session.completed",
        "created": int(time.time()),
        "data": {
            "object": {
                "id": "cs_script_001",
                "payment_intent": "pi_script_001",
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
    result = checkout_service.handle_stripe_webhook(payload_bytes, signature)
    assert result["status"] == "processed"
    return db_path, order_id


def test_fulfillment_flow_script_runs_paid_order_drill_without_manual_db_edits(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path, order_id = _seed_paid_order(tmp_path)
    artifact_root = tmp_path / "reports" / "nontrading"
    output_root = tmp_path / "reports" / "nontrading" / "operations"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_revenue_audit_fulfillment_flow.py",
            "--order-id",
            order_id,
            "--db-path",
            str(db_path),
            "--artifact-root",
            str(artifact_root),
            "--output-root",
            str(output_root),
        ],
    )

    assert run_revenue_audit_fulfillment_flow.main() == 0

    summary_path = output_root / order_id / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    assert summary["report_status"] == "first_dollar_observed"
    assert summary["claim_status"] == "actual_revenue_recorded"
    assert summary["delivery_checklist_path"].endswith("delivery_checklist.json")
    assert summary["delivery_pack_path"].endswith("delivery_pack.json")
    assert summary["monitor_status"] == "completed"
    assert [item["status"] for item in summary["order_timeline"]][-3:] == [
        "artifact_generated",
        "delivered",
        "monitor_rerun_completed",
    ]
    assert [item["step"] for item in summary["operator_steps"]] == [
        "regenerate_report",
        "verify_status",
        "ship_delivery_pack",
    ]
    assert summary["operator_steps"][1]["status"] == "completed"
