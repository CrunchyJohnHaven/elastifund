import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from hub.app.main import app
from nontrading.revenue_audit.config import RevenueAuditSettings
from nontrading.revenue_audit.contracts import AuditBundle, IssueEvidence, ProspectProfile
from nontrading.revenue_audit.fulfillment import RevenueAuditFulfillmentService
from nontrading.revenue_audit.service import RevenueAuditCheckoutService
from nontrading.revenue_audit.stripe import generate_signature_header


class FakeStripeCheckoutClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def create_checkout_session(self, **kwargs):
        self.calls.append(kwargs)
        suffix = len(self.calls)
        return {
            "id": f"cs_test_revenue_audit_{suffix:03d}",
            "url": f"https://checkout.stripe.test/cs_test_revenue_audit_{suffix:03d}",
            "payment_intent": f"pi_test_revenue_audit_{suffix:03d}",
            "status": "open",
            "expires_at": "2026-03-10T15:00:00+00:00",
            "raw": {"object": "checkout.session", "id": f"cs_test_revenue_audit_{suffix:03d}", **kwargs},
        }


def _configure_env(monkeypatch, db_path: Path) -> None:
    monkeypatch.setenv("JJ_REVENUE_DB_PATH", str(db_path))
    monkeypatch.setenv("JJ_REVENUE_PUBLIC_BASE_URL", "https://elastifund.io")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_checkout")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test_checkout")
    monkeypatch.setenv(
        "JJ_N_WEBSITE_GROWTH_AUDIT_PRICING_JSON",
        json.dumps(
            [
                {
                    "key": "starter",
                    "label": "Starter Audit",
                    "amount_usd": 500,
                    "description": "Baseline website growth audit.",
                },
                {
                    "key": "growth",
                    "label": "Growth Audit",
                    "amount_usd": 1500,
                    "description": "Audit with competitor benchmark appendix.",
                },
            ]
        ),
    )


def test_offer_endpoint_returns_checkout_surface(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path / "revenue_agent.db")

    client = TestClient(app)
    response = client.get("/v1/nontrading/offers/website-growth-audit")

    assert response.status_code == 200
    body = response.json()
    assert body["offer"]["slug"] == "website-growth-audit"
    assert body["pricing"]["currency"] == "USD"
    assert [option["key"] for option in body["pricing"]["options"]] == ["starter", "growth"]
    assert body["checkout"]["provider"] == "stripe"
    assert body["checkout"]["enabled"] is True
    assert body["checkout"]["live_offer_url"] == "https://elastifund.io/nontrading/website-growth-audit"
    assert body["checkout"]["launch_ready"] is True
    assert body["order_lookup"]["by_session_id"].endswith("session_id={CHECKOUT_SESSION_ID}")
    assert body["expansion_offer"]["offer"]["slug"] == "website-growth-audit-recurring-monitor"


def test_recurring_monitor_offer_endpoint_returns_subscription_surface(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path / "revenue_agent.db")

    client = TestClient(app)
    response = client.get("/v1/nontrading/offers/website-growth-audit/recurring-monitor")

    assert response.status_code == 200
    body = response.json()
    assert body["offer"]["slug"] == "website-growth-audit-recurring-monitor"
    assert body["checkout"]["mode"] == "subscription"
    assert body["lifecycle"]["attached_to_offer_slug"] == "website-growth-audit"


def test_offer_page_renders_human_checkout_surface(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path / "revenue_agent.db")

    client = TestClient(app)
    response = client.get("/nontrading/website-growth-audit")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Continue to secure Stripe checkout" in response.text
    assert "Lookup order status" in response.text
    assert "Live-launch checklist" in response.text


def test_checkout_and_paid_webhook_record_first_dollar(monkeypatch, tmp_path: Path) -> None:
    db_path = tmp_path / "revenue_agent.db"
    _configure_env(monkeypatch, db_path)
    fake_client = FakeStripeCheckoutClient()
    service = RevenueAuditCheckoutService(
        RevenueAuditSettings.from_env(),
        stripe_client=fake_client,
    )
    monkeypatch.setattr("hub.app.nontrading_api.get_checkout_service", lambda: service)

    client = TestClient(app)
    checkout_response = client.post(
        "/v1/nontrading/checkout/session",
        json={
            "price_key": "starter",
            "customer_email": "owner@example.com",
            "customer_name": "Pat Owner",
            "business_name": "Acme Builders",
            "website_url": "https://acme.example",
            "metadata": {"source": "api-test"},
        },
    )
    assert checkout_response.status_code == 200
    checkout_body = checkout_response.json()
    order_id = checkout_body["order"]["order_id"]
    assert checkout_body["checkout_session"]["provider_session_id"] == "cs_test_revenue_audit_001"
    assert fake_client.calls[0]["metadata"]["order_id"] == order_id
    assert (
        fake_client.calls[0]["success_url"]
        == "https://elastifund.io/nontrading/website-growth-audit/success?session_id={CHECKOUT_SESSION_ID}"
    )
    assert fake_client.calls[0]["cancel_url"] == "https://elastifund.io/nontrading/website-growth-audit/cancel"

    webhook_payload = {
        "id": "evt_test_checkout_paid_001",
        "type": "checkout.session.completed",
        "created": 1773151200,
        "data": {
            "object": {
                "id": "cs_test_revenue_audit_001",
                "payment_intent": "pi_test_revenue_audit_001",
                "payment_status": "paid",
                "status": "complete",
                "amount_total": 50000,
                "currency": "usd",
                "metadata": {"order_id": order_id},
            }
        },
    }
    payload_bytes = json.dumps(webhook_payload).encode("utf-8")
    signature = generate_signature_header(payload_bytes, "whsec_test_checkout")
    webhook_response = client.post(
        "/v1/nontrading/webhooks/stripe",
        data=payload_bytes,
        headers={
            "Content-Type": "application/json",
            "Stripe-Signature": signature,
        },
    )

    assert webhook_response.status_code == 200
    assert webhook_response.json()["order_status"] == "paid"

    order_response = client.get("/v1/nontrading/orders/lookup", params={"session_id": "cs_test_revenue_audit_001"})
    assert order_response.status_code == 200
    order_body = order_response.json()
    assert order_body["order"]["order_id"] == order_id
    assert order_body["order"]["status"] == "paid"
    assert order_body["order"]["fulfillment_status"] == "queued"
    assert order_body["checkout_session"]["provider_payment_intent_id"] == "pi_test_revenue_audit_001"
    assert order_body["payment_events"][0]["event_type"] == "checkout.session.completed"
    assert order_body["payment_events"][0]["amount_total_usd"] == 500.0
    assert order_body["fulfillment_jobs"][0]["status"] == "queued"


def test_recurring_monitor_checkout_reuses_existing_order_model(monkeypatch, tmp_path: Path) -> None:
    db_path = tmp_path / "revenue_agent.db"
    _configure_env(monkeypatch, db_path)
    fake_client = FakeStripeCheckoutClient()
    service = RevenueAuditCheckoutService(
        RevenueAuditSettings.from_env(),
        stripe_client=fake_client,
    )
    monkeypatch.setattr("hub.app.nontrading_api.get_checkout_service", lambda: service)

    client = TestClient(app)
    audit_checkout = client.post(
        "/v1/nontrading/checkout/session",
        json={
            "price_key": "starter",
            "customer_email": "owner@example.com",
            "customer_name": "Pat Owner",
            "business_name": "Acme Builders",
            "website_url": "https://acme.example",
        },
    )
    audit_order_id = audit_checkout.json()["order"]["order_id"]
    audit_paid_payload = {
        "id": "evt_test_checkout_paid_upsell_001",
        "type": "checkout.session.completed",
        "created": 1773151200,
        "data": {
            "object": {
                "id": "cs_test_revenue_audit_001",
                "payment_intent": "pi_test_revenue_audit_001",
                "payment_status": "paid",
                "status": "complete",
                "amount_total": 50000,
                "currency": "usd",
                "metadata": {"order_id": audit_order_id},
            }
        },
    }
    audit_bytes = json.dumps(audit_paid_payload).encode("utf-8")
    audit_signature = generate_signature_header(audit_bytes, "whsec_test_checkout")
    client.post(
        "/v1/nontrading/webhooks/stripe",
        data=audit_bytes,
        headers={"Content-Type": "application/json", "Stripe-Signature": audit_signature},
    )

    recurring_checkout = client.post(
        "/v1/nontrading/checkout/session",
        json={
            "offer_slug": "website-growth-audit-recurring-monitor",
            "source_order_id": audit_order_id,
            "price_key": "monitor-monthly",
            "customer_email": "owner@example.com",
            "customer_name": "Pat Owner",
        },
    )

    assert recurring_checkout.status_code == 200
    recurring_body = recurring_checkout.json()
    assert recurring_body["order"]["offer_slug"] == "website-growth-audit-recurring-monitor"
    assert recurring_body["checkout_session"]["metadata"]["mode"] == "subscription"
    assert recurring_body["recurring_monitor"]["enrollment"]["status"] == "checkout_pending"
    audit_order_lookup = client.get("/v1/nontrading/orders/lookup", params={"order_id": audit_order_id})
    audit_order_body = audit_order_lookup.json()
    assert [item["status"] for item in audit_order_body["timeline"]][:2] == ["payment_received", "fulfillment_queued"]
    assert audit_order_body["timeline"][-1]["status"] == "recurring_monitor_staged"


def test_order_lookup_exposes_delivery_pack_and_monitor_timeline(monkeypatch, tmp_path: Path) -> None:
    db_path = tmp_path / "revenue_agent.db"
    _configure_env(monkeypatch, db_path)
    fake_client = FakeStripeCheckoutClient()
    service = RevenueAuditCheckoutService(
        RevenueAuditSettings.from_env(),
        stripe_client=fake_client,
    )
    monkeypatch.setattr("hub.app.nontrading_api.get_checkout_service", lambda: service)

    client = TestClient(app)
    checkout_response = client.post(
        "/v1/nontrading/checkout/session",
        json={
            "price_key": "starter",
            "customer_email": "owner@example.com",
            "customer_name": "Pat Owner",
            "business_name": "Acme Builders",
            "website_url": "https://acme.example",
            "audit_bundle": {
                "bundle_id": "bundle_api_001",
                "prospect": {
                    "business_name": "Acme Builders",
                    "website_url": "https://acme.example",
                    "contact_email": "owner@example.com",
                    "contact_name": "Pat Owner",
                },
                "issues": [
                    {
                        "detector_key": "cta",
                        "summary": "Primary estimate CTA is buried below the fold.",
                        "severity": "high",
                        "evidence_url": "https://acme.example",
                    }
                ],
                "summary": "API-seeded bundle for the paid-order drill.",
            },
        },
    )
    order_id = checkout_response.json()["order"]["order_id"]
    webhook_payload = {
        "id": "evt_test_checkout_paid_002",
        "type": "checkout.session.completed",
        "created": 1773151200,
        "data": {
            "object": {
                "id": "cs_test_revenue_audit_001",
                "payment_intent": "pi_test_revenue_audit_001",
                "payment_status": "paid",
                "status": "complete",
                "amount_total": 50000,
                "currency": "usd",
                "metadata": {"order_id": order_id},
            }
        },
    }
    payload_bytes = json.dumps(webhook_payload).encode("utf-8")
    signature = generate_signature_header(payload_bytes, "whsec_test_checkout")
    webhook_response = client.post(
        "/v1/nontrading/webhooks/stripe",
        data=payload_bytes,
        headers={
            "Content-Type": "application/json",
            "Stripe-Signature": signature,
        },
    )

    assert webhook_response.status_code == 200

    fulfillment_service = RevenueAuditFulfillmentService(
        audit_store=service.audit_store,
        revenue_store=service.revenue_store,
        telemetry=service.telemetry,
        artifact_root=tmp_path / "reports" / "nontrading",
    )
    fulfillment_service.fulfill_order(order_id)
    order = service.audit_store.get_order(order_id)
    assert order is not None
    fulfillment_service.run_monitor(
        order_id,
        current_bundle=AuditBundle(
            bundle_id="bundle_monitor_api_001",
            prospect=order.prospect_profile or ProspectProfile(business_name="Acme Builders", website_url="https://acme.example"),
            issues=(
                IssueEvidence(
                    detector_key="cta",
                    summary="Primary estimate CTA is still buried below the fold.",
                    severity="high",
                    evidence_url="https://acme.example",
                ),
            ),
            summary="Monitor rerun from API test.",
        ),
    )

    order_response = client.get("/v1/nontrading/orders/lookup", params={"order_id": order_id})
    assert order_response.status_code == 200
    body = order_response.json()
    assert body["artifacts"]["delivery_pack"].endswith("delivery_pack.json")
    assert body["artifacts"]["delivery_checklist"].endswith("delivery_checklist.json")
    assert body["artifacts"]["monitor_json"].endswith("monitor_delta.json")
    assert [item["status"] for item in body["timeline"]][-3:] == [
        "artifact_generated",
        "delivered",
        "monitor_rerun_completed",
    ]


def test_checkout_rejects_disallowed_redirect_host(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path / "revenue_agent.db")
    service = RevenueAuditCheckoutService(
        RevenueAuditSettings.from_env(),
        stripe_client=FakeStripeCheckoutClient(),
    )
    monkeypatch.setattr("hub.app.nontrading_api.get_checkout_service", lambda: service)

    client = TestClient(app)
    response = client.post(
        "/v1/nontrading/checkout/session",
        json={
            "price_key": "starter",
            "customer_email": "owner@example.com",
            "business_name": "Acme Builders",
            "website_url": "https://acme.example",
            "success_url": "https://evil.example/checkout/success?session_id={CHECKOUT_SESSION_ID}",
        },
    )

    assert response.status_code == 400
    assert "not allowed" in response.json()["detail"]


def test_launch_checklist_flags_placeholder_public_offer_host(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path / "revenue_agent.db")
    monkeypatch.setenv("JJ_REVENUE_PUBLIC_BASE_URL", "https://example.invalid")

    client = TestClient(app)
    response = client.get("/v1/nontrading/offers/website-growth-audit/launch-checklist")

    assert response.status_code == 200
    body = response.json()
    assert body["launch_ready"] is False
    assert "public_base_url" in body["blocking_requirements"]
    assert body["summary"]["offer_surface_ready"] is False


def test_stripe_webhook_rejects_invalid_signature(monkeypatch, tmp_path: Path) -> None:
    db_path = tmp_path / "revenue_agent.db"
    _configure_env(monkeypatch, db_path)
    service = RevenueAuditCheckoutService(
        RevenueAuditSettings.from_env(),
        stripe_client=FakeStripeCheckoutClient(),
    )
    monkeypatch.setattr("hub.app.nontrading_api.get_checkout_service", lambda: service)

    client = TestClient(app)
    response = client.post(
        "/v1/nontrading/webhooks/stripe",
        data=b"{}",
        headers={
            "Content-Type": "application/json",
            "Stripe-Signature": "t=1,v1=not-valid",
        },
    )

    assert response.status_code == 400
    assert "Stripe webhook" in response.json()["detail"]
