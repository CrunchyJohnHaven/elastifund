from __future__ import annotations

from pathlib import Path

from nontrading.config import RevenueAgentSettings
from nontrading.email.render import render_campaign_email
from nontrading.email.sender import DryRunSender
from nontrading.email.validate import validate_outbox_message
from nontrading.models import Lead
from nontrading.store import RevenueStore


def make_settings(tmp_path: Path) -> RevenueAgentSettings:
    return RevenueAgentSettings(
        db_path=tmp_path / "revenue_agent.db",
        outbox_dir=tmp_path / "outbox",
        public_base_url="https://example.invalid",
        postal_address="100 Main Street, Austin, TX 78701",
    )


def test_rendered_email_has_required_footer_and_unsubscribe_headers(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    store = RevenueStore(settings.db_path)
    campaign = store.ensure_default_campaign(settings)
    lead, _ = store.upsert_lead(
        Lead(email="info@usbiz.com", company_name="US Biz", country_code="US", source="manual_csv")
    )

    rendered = render_campaign_email(campaign, lead, settings)
    queued = store.queue_outbox_message(
        campaign=campaign,
        lead=lead,
        subject=rendered.subject,
        body=rendered.body,
        headers=rendered.headers,
        from_email=settings.from_email,
        provider="dry_run",
    )

    assert settings.postal_address in rendered.body
    assert "List-Unsubscribe" in rendered.headers
    assert rendered.unsubscribe_url in rendered.body
    validate_outbox_message(queued, settings.postal_address)


def test_dry_run_sender_honors_suppression_before_write(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    store = RevenueStore(settings.db_path)
    campaign = store.ensure_default_campaign(settings)
    lead, _ = store.upsert_lead(
        Lead(email="sales@vendor.example.com", company_name="Vendor", country_code="US", source="manual_csv")
    )
    rendered = render_campaign_email(campaign, lead, settings)
    queued = store.queue_outbox_message(
        campaign=campaign,
        lead=lead,
        subject=rendered.subject,
        body=rendered.body,
        headers=rendered.headers,
        from_email=settings.from_email,
        provider="dry_run",
    )
    store.append_suppression(lead.email, "recipient_unsubscribed", "test")

    sender = DryRunSender(settings, store)
    result = sender.send(queued)

    assert result.status == "suppressed"
    outbox_message = store.get_outbox_message(queued.id or 0)
    assert outbox_message is not None
    assert outbox_message.status == "suppressed"

