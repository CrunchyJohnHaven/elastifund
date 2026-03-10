from __future__ import annotations

import json
from pathlib import Path

from nontrading.config import RevenueAgentSettings
from nontrading.models import Account, Contact, Lead, Opportunity
from nontrading.revenue_audit import StaticPageFetcher
from nontrading.revenue_audit.acquisition_bridge import RevenueAuditAcquisitionBridge
from nontrading.store import RevenueStore
from scripts.generate_revenue_audit_launch_bridge import main as generate_launch_bridge_main


def make_settings(
    tmp_path: Path,
    *,
    provider: str = "sendgrid",
    sender_domain_verified: bool = True,
) -> RevenueAgentSettings:
    return RevenueAgentSettings(
        db_path=tmp_path / "revenue_agent.db",
        outbox_dir=tmp_path / "outbox",
        provider=provider,
        public_base_url="https://elastifund.io",
        from_name="JJ-N",
        from_email="ops@elastifund.io",
        sendgrid_api_key="test-key",
        sender_domain_verified=sender_domain_verified,
    )


def seed_curated_prospect(
    store: RevenueStore,
    *,
    company: str,
    email: str,
    score: float,
    country_code: str = "US",
    curated: bool = True,
    include_evidence: bool = True,
) -> Opportunity:
    lead_metadata = {
        "first_name": "Pat",
        "industry": "construction",
        "role": "owner",
        "company_size": "11-50",
        "website_url": f"https://{email.split('@', 1)[1]}",
    }
    if curated:
        lead_metadata["curated_launch_batch"] = True
    if include_evidence:
        lead_metadata["website_findings"] = "the main estimate CTA is buried below the fold on mobile"
        lead_metadata["quick_win"] = "move the estimate CTA into the first screen on service pages"
    lead, _ = store.upsert_lead(
        Lead(
            email=email,
            company_name=company,
            country_code=country_code,
            source="manual_csv",
            explicit_opt_in=True,
            metadata=lead_metadata,
        )
    )
    account = store.create_account(
        Account(
            name=company,
            domain=email.split("@", 1)[1],
            website_url=f"https://{email.split('@', 1)[1]}",
            metadata={
                "lead_email": lead.email,
                "country_code": country_code,
            },
        )
    )
    contact = store.create_contact(
        Contact(
            account_id=account.id or 0,
            full_name="Pat Jones",
            email=email,
            role="owner",
            metadata={"country_code": country_code},
        )
    )
    return store.create_opportunity(
        Opportunity(
            account_id=account.id or 0,
            name=f"Website Growth Audit for {company}",
            offer_name="Website Growth Audit",
            stage="qualified",
            status="open",
            score=score,
            estimated_value=900.0 + score * 10.0,
            next_action="launch_bridge",
            metadata={
                "contact_id": contact.id or 0,
                "curated_launch_batch": curated,
                "website_findings": lead_metadata.get("website_findings", ""),
                "quick_win": lead_metadata.get("quick_win", ""),
            },
        )
    )


def _write_curated_source(tmp_path: Path, *, company: str, website_url: str) -> Path:
    source_path = tmp_path / "curated_launch_batch.json"
    source_path.write_text(
        json.dumps(
            [
                {
                    "company_name": company,
                    "website_url": website_url,
                    "country_code": "US",
                    "segment": "local_services",
                    "city": "Austin",
                    "state": "TX",
                }
            ]
        ),
        encoding="utf-8",
    )
    return source_path


def _curated_fetcher_with_email() -> StaticPageFetcher:
    home = """
    <html>
      <head><title>Home</title></head>
      <body>
        <h1>Welcome</h1>
        <a href="/services">Services</a>
        <a href="/contact">Contact</a>
        <a href="mailto:hello@growth-gap.test">Email</a>
        <a href="tel:5125550100">Call</a>
        <button>Learn More</button>
      </body>
    </html>
    """
    services = """
    <html>
      <head><title>Services</title></head>
      <body>
        <h1>Services</h1>
        <button>Learn More</button>
      </body>
    </html>
    """
    contact = """
    <html>
      <head><title>Contact</title></head>
      <body>
        <form action="/submit"></form>
        <a href="mailto:hello@growth-gap.test">Email</a>
      </body>
    </html>
    """
    return StaticPageFetcher(
        {
            "https://growth-gap.test/": home,
            "https://growth-gap.test/services": services,
            "https://growth-gap.test/contact": contact,
        }
    )


def _curated_fetcher_phone_only() -> StaticPageFetcher:
    home = """
    <html>
      <head><title>Home</title></head>
      <body>
        <h1>Welcome</h1>
        <a href="/services">Services</a>
        <a href="/contact">Contact</a>
        <a href="tel:5125550111">Call</a>
        <button>Learn More</button>
      </body>
    </html>
    """
    services = """
    <html>
      <head><title>Services</title></head>
      <body>
        <h1>Services</h1>
        <button>Learn More</button>
      </body>
    </html>
    """
    contact = """
    <html>
      <head><title>Contact</title></head>
      <body>
        <form action="/submit"></form>
        <a href="tel:5125550111">Call</a>
      </body>
    </html>
    """
    return StaticPageFetcher(
        {
            "https://phone-only-gap.test/": home,
            "https://phone-only-gap.test/services": services,
            "https://phone-only-gap.test/contact": contact,
        }
    )


def test_bridge_stages_approval_queue_for_verified_sender(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, sender_domain_verified=True)
    store = RevenueStore(settings.db_path)
    seed_curated_prospect(store, company="Acme Roofing", email="owner@acme-roofing.com", score=92.0)
    seed_curated_prospect(store, company="North Ridge HVAC", email="sales@northridge-hvac.com", score=81.0)

    artifact = RevenueAuditAcquisitionBridge(store, settings).build_artifact()

    assert artifact.launch_mode == "approval_queue_only"
    assert artifact.sender_verification["live_send_eligible"] is True
    assert artifact.selected_prospects == 2
    assert artifact.overflow_count == 0
    assert artifact.landing_page_cta_optimizations == ()
    assert len(store.list_messages()) == 2
    assert {message.status for message in store.list_messages()} == {"pending_approval"}
    assert len(store.list_approval_requests()) == 2
    assert all(packet["approval_request_id"] for packet in artifact.prospects)
    assert all(packet["next_step"] == "human_review_send" for packet in artifact.prospects)
    assert all(packet["recommended_price_tier"]["price_usd"] >= 500 for packet in artifact.prospects)


def test_bridge_falls_back_to_manual_close_when_sender_unverified(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, sender_domain_verified=False)
    store = RevenueStore(settings.db_path)
    seed_curated_prospect(store, company="Blue River Plumbing", email="owner@blueriverplumbing.com", score=88.0)

    artifact = RevenueAuditAcquisitionBridge(store, settings).build_artifact()

    assert artifact.launch_mode == "manual_close_only"
    assert artifact.sender_verification["reason"] == "sender_domain_unverified"
    assert artifact.selected_prospects == 1
    assert len(store.list_approval_requests()) == 0
    messages = store.list_messages()
    assert len(messages) == 1
    assert messages[0].status == "manual_close_ready"
    assert messages[0].approval_status == "not_required"
    assert len(artifact.landing_page_cta_optimizations) == 3
    assert artifact.prospects[0]["manual_close_talk_track"]
    assert artifact.prospects[0]["manual_close_packet"]["recommended_price_tier"]["price_usd"] >= 500
    assert artifact.prospects[0]["next_step"] == "manual_close_packet"


def test_bridge_caps_batch_at_ten_and_filters_non_us_or_missing_evidence(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, sender_domain_verified=False)
    store = RevenueStore(settings.db_path)

    for index in range(12):
        seed_curated_prospect(
            store,
            company=f"Prospect {index}",
            email=f"owner{index}@prospect{index}.com",
            score=100.0 - index,
        )
    seed_curated_prospect(
        store,
        company="Non US Prospect",
        email="owner@montreal-builder.ca",
        score=85.0,
        country_code="CA",
    )
    seed_curated_prospect(
        store,
        company="No Evidence Prospect",
        email="owner@noevidence.com",
        score=84.0,
        include_evidence=False,
    )

    artifact = RevenueAuditAcquisitionBridge(store, settings).build_artifact()

    assert artifact.selected_prospects == 10
    assert artifact.overflow_count == 2
    assert artifact.skipped_non_us == 1
    assert artifact.skipped_missing_evidence == 1
    assert artifact.prospects[0]["company_name"] == "Prospect 0"


def test_launch_bridge_script_writes_artifact(tmp_path: Path, monkeypatch) -> None:
    settings = make_settings(tmp_path, sender_domain_verified=False)
    store = RevenueStore(settings.db_path)
    seed_curated_prospect(store, company="Script Prospect", email="owner@scriptprospect.com", score=91.0)
    output_path = tmp_path / "reports" / "launch_bridge.json"

    monkeypatch.setenv("JJ_REVENUE_PROVIDER", settings.provider)
    monkeypatch.setenv("JJ_REVENUE_PUBLIC_BASE_URL", settings.public_base_url)
    monkeypatch.setenv("JJ_REVENUE_FROM_NAME", settings.from_name)
    monkeypatch.setenv("JJ_REVENUE_FROM_EMAIL", settings.from_email)
    monkeypatch.setenv("SENDGRID_API_KEY", settings.sendgrid_api_key or "")
    monkeypatch.setenv("JJ_REVENUE_SENDER_DOMAIN_VERIFIED", "0")

    exit_code = generate_launch_bridge_main(
        [
            "--db-path",
            str(settings.db_path),
            "--output",
            str(output_path),
        ]
    )

    payload = output_path.read_text(encoding="utf-8")
    assert exit_code == 0
    assert '"launch_mode": "manual_close_only"' in payload
    assert '"company_name": "Script Prospect"' in payload


def test_launch_bridge_script_ingests_curated_public_source(tmp_path: Path, monkeypatch) -> None:
    settings = make_settings(tmp_path, sender_domain_verified=False)
    output_path = tmp_path / "reports" / "launch_bridge.json"
    source_path = _write_curated_source(tmp_path, company="Growth Gap HVAC", website_url="https://growth-gap.test/")

    monkeypatch.setenv("JJ_REVENUE_PROVIDER", settings.provider)
    monkeypatch.setenv("JJ_REVENUE_PUBLIC_BASE_URL", settings.public_base_url)
    monkeypatch.setenv("JJ_REVENUE_FROM_NAME", settings.from_name)
    monkeypatch.setenv("JJ_REVENUE_FROM_EMAIL", settings.from_email)
    monkeypatch.setenv("SENDGRID_API_KEY", settings.sendgrid_api_key or "")
    monkeypatch.setenv("JJ_REVENUE_SENDER_DOMAIN_VERIFIED", "0")

    exit_code = generate_launch_bridge_main(
        [
            "--db-path",
            str(settings.db_path),
            "--output",
            str(output_path),
            "--curated-source",
            str(source_path),
        ],
        fetcher=_curated_fetcher_with_email(),
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["source_artifact"] == str(source_path)
    assert payload["selected_prospects"] == 1
    assert payload["prospects"][0]["company_name"] == "Growth Gap HVAC"
    assert payload["prospects"][0]["recipient_email"] == "hello@growth-gap.test"
    assert payload["prospects"][0]["evidence"][0]["source_url"].startswith("https://growth-gap.test")


def test_manual_close_keeps_phone_only_curated_prospect_operator_ready(tmp_path: Path, monkeypatch) -> None:
    settings = make_settings(tmp_path, sender_domain_verified=False)
    output_path = tmp_path / "reports" / "launch_bridge.json"
    source_path = _write_curated_source(
        tmp_path,
        company="Phone Only Roofing",
        website_url="https://phone-only-gap.test/",
    )

    monkeypatch.setenv("JJ_REVENUE_PROVIDER", settings.provider)
    monkeypatch.setenv("JJ_REVENUE_PUBLIC_BASE_URL", settings.public_base_url)
    monkeypatch.setenv("JJ_REVENUE_FROM_NAME", settings.from_name)
    monkeypatch.setenv("JJ_REVENUE_FROM_EMAIL", settings.from_email)
    monkeypatch.setenv("SENDGRID_API_KEY", settings.sendgrid_api_key or "")
    monkeypatch.setenv("JJ_REVENUE_SENDER_DOMAIN_VERIFIED", "0")

    exit_code = generate_launch_bridge_main(
        [
            "--db-path",
            str(settings.db_path),
            "--output",
            str(output_path),
            "--curated-source",
            str(source_path),
        ],
        fetcher=_curated_fetcher_phone_only(),
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["launch_mode"] == "manual_close_only"
    assert payload["selected_prospects"] == 1
    assert payload["prospects"][0]["recipient_email"] == ""
    assert payload["prospects"][0]["message_id"] is None
    assert payload["prospects"][0]["contact_channels"][0]["kind"] in {"phone", "contact_form", "contact_page"}
    assert payload["prospects"][0]["manual_close_packet"]["primary_contact_path"].startswith("phone:")
