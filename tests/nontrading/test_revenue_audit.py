from __future__ import annotations

import json
from pathlib import Path

from nontrading.revenue_audit import (
    CheckoutSession,
    FirstDollarReadiness,
    FulfillmentJob,
    MonitorRun,
    PaymentEvent,
    StaticPageFetcher,
    build_audit_bundle,
    discover_prospect,
)


FIXTURE_DIR = Path(__file__).resolve().parents[2] / "nontrading" / "tests" / "fixtures" / "revenue_audit"


def _fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def test_shared_revenue_audit_contracts_are_json_ready() -> None:
    fetcher = StaticPageFetcher(
        {
            "https://lonestarfence.test/": _fixture("strong_home.html"),
            "https://lonestarfence.test/services/fence-repair": _fixture("strong_services.html"),
            "https://lonestarfence.test/contact": _fixture("strong_contact.html"),
        }
    )
    bundle = build_audit_bundle(discover_prospect("https://lonestarfence.test/", fetcher=fetcher))
    checkout = CheckoutSession(
        checkout_id="cs_test_123",
        order_id="order_123",
        offer_slug="website-growth-audit",
        amount_usd=1495.0,
        customer_email="owner@lonestarfence.test",
        checkout_url="https://checkout.stripe.test/session/cs_test_123",
    )
    payment = PaymentEvent(
        event_id="evt_123",
        order_id="order_123",
        provider="stripe",
        event_type="checkout.session.completed",
        status="paid",
        amount_usd=1495.0,
    )
    job = FulfillmentJob(
        job_id="job_123",
        order_id="order_123",
        offer_slug="website-growth-audit",
        status="queued",
        artifact_paths=("reports/nontrading/audits/order_123.md",),
    )
    monitor = MonitorRun(
        run_id="monitor_123",
        order_id="order_123",
        prospect_domain="lonestarfence.test",
        status="queued",
        artifact_paths=("reports/nontrading/monitor/order_123_delta.md",),
    )
    readiness = FirstDollarReadiness(
        status="launchable",
        readiness_score=72.5,
        blockers=("webhook_not_verified",),
        metrics={"bundles_scored": 1},
    )

    payload = json.dumps(
        {
            "bundle": bundle.to_dict(),
            "checkout": checkout.to_dict(),
            "payment": payment.to_dict(),
            "job": job.to_dict(),
            "monitor": monitor.to_dict(),
            "readiness": readiness.to_dict(),
        },
        sort_keys=True,
    )

    assert '"status": "launchable"' in payload
    assert '"offer_slug": "website-growth-audit"' in payload
    assert bundle.score.purchase_probability > 0.0
