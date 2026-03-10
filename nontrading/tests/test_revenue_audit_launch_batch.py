from __future__ import annotations

import json
from pathlib import Path

from nontrading.config import RevenueAgentSettings
from nontrading.revenue_audit import StaticPageFetcher
from nontrading.revenue_audit.acquisition_bridge import RevenueAuditAcquisitionBridge
from nontrading.revenue_audit.launch_batch import refresh_curated_launch_batch
from nontrading.store import RevenueStore
from scripts.refresh_revenue_audit_launch_batch import main as refresh_launch_batch_main


FIXTURE_DIR = Path(__file__).with_name("fixtures") / "revenue_audit"


def _fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def _write_seed_file(tmp_path: Path, rows: list[dict[str, str]]) -> Path:
    source_path = tmp_path / "launch_batch_seed.json"
    source_path.write_text(json.dumps(rows), encoding="utf-8")
    return source_path


def _curated_fetcher() -> StaticPageFetcher:
    good_home = """
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
    good_services = """
    <html>
      <head><title>Services</title></head>
      <body>
        <h1>Services</h1>
        <button>Learn More</button>
      </body>
    </html>
    """
    good_contact = """
    <html>
      <head><title>Contact</title></head>
      <body>
        <form action="/submit"></form>
        <a href="mailto:hello@growth-gap.test">Email</a>
      </body>
    </html>
    """
    phone_home = """
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
    phone_services = """
    <html>
      <head><title>Services</title></head>
      <body>
        <h1>Services</h1>
        <button>Learn More</button>
      </body>
    </html>
    """
    phone_contact = """
    <html>
      <head><title>Contact</title></head>
      <body>
        <form action="/submit"></form>
        <a href="tel:5125550111">Call</a>
      </body>
    </html>
    """
    contactless_home = """
    <html>
      <head><title>Contactless Builders</title></head>
      <body>
        <h1>Welcome</h1>
        <a href="/services">Services</a>
        <a href="/about">About</a>
        <button>Learn More</button>
      </body>
    </html>
    """
    contactless_services = """
    <html>
      <head><title>Services</title></head>
      <body>
        <h1>Services</h1>
        <button>Learn More</button>
      </body>
    </html>
    """
    contactless_about = """
    <html>
      <head><title>About</title></head>
      <body>
        <h1>About</h1>
      </body>
    </html>
    """
    return StaticPageFetcher(
        {
            "https://growth-gap.test/": good_home,
            "https://growth-gap.test/services": good_services,
            "https://growth-gap.test/contact": good_contact,
            "https://phone-only-gap.test/": phone_home,
            "https://phone-only-gap.test/services": phone_services,
            "https://phone-only-gap.test/contact": phone_contact,
            "https://contactless-gap.test/": contactless_home,
            "https://contactless-gap.test/services": contactless_services,
            "https://contactless-gap.test/about": contactless_about,
            "https://lonestarfence.test/": _fixture("strong_home.html"),
            "https://lonestarfence.test/services/fence-repair": _fixture("strong_services.html"),
            "https://lonestarfence.test/contact": _fixture("strong_contact.html"),
        }
    )


def _make_settings(tmp_path: Path, *, sender_domain_verified: bool = False) -> RevenueAgentSettings:
    return RevenueAgentSettings(
        db_path=tmp_path / "revenue_agent.db",
        outbox_dir=tmp_path / "outbox",
        provider="sendgrid",
        public_base_url="https://elastifund.io",
        from_name="JJ-N",
        from_email="ops@elastifund.io",
        sendgrid_api_key="test-key",
        sender_domain_verified=sender_domain_verified,
    )


def test_refresh_launch_batch_emits_ranked_artifact_and_skip_reasons(tmp_path: Path) -> None:
    store = RevenueStore(tmp_path / "revenue_agent.db")
    source_path = _write_seed_file(
        tmp_path,
        [
            {
                "company_name": "Growth Gap HVAC",
                "website_url": "https://growth-gap.test/",
                "country_code": "US",
                "segment": "hvac",
                "city": "Austin",
                "state": "TX",
            },
            {
                "company_name": "Lone Star Fence",
                "website_url": "https://lonestarfence.test/",
                "country_code": "US",
                "segment": "fencing",
                "city": "Dallas",
                "state": "TX",
            },
            {
                "company_name": "Contactless Builders",
                "website_url": "https://contactless-gap.test/",
                "country_code": "US",
                "segment": "construction",
                "city": "Austin",
                "state": "TX",
            },
            {
                "company_name": "Broken Fetch Plumbing",
                "website_url": "https://missing-site.test/",
                "country_code": "US",
                "segment": "plumbing",
                "city": "Austin",
                "state": "TX",
            },
            {
                "company_name": "Maple Roofing",
                "website_url": "https://maple-roofing.test/",
                "country_code": "CA",
                "segment": "roofing",
                "city": "Toronto",
                "state": "ON",
            },
        ],
    )

    artifact = refresh_curated_launch_batch(
        store,
        source_path=source_path,
        fetcher=_curated_fetcher(),
        max_prospects=1,
    )

    assert artifact.seeds_loaded == 5
    assert artifact.qualified_candidates == 1
    assert artifact.selected_prospects == 1
    assert artifact.overflow_count == 0
    assert artifact.skipped_non_us == 1
    assert artifact.skipped_missing_evidence == 1
    assert artifact.skipped_missing_contact == 1
    assert artifact.skipped_fetch_error == 1
    selected = next(item for item in artifact.prospects if item.status == "selected")
    assert selected.company_name == "Growth Gap HVAC"
    assert selected.selection_rank == 1
    assert selected.price_tier["price_usd"] >= 500
    assert len(selected.issue_evidence) >= 2
    assert selected.quick_win

    opportunity = store.get_opportunity(selected.opportunity_id or 0)
    assert opportunity is not None
    assert opportunity.metadata["segment"] == "hvac"
    assert opportunity.metadata["city"] == "Austin"
    assert opportunity.metadata["state"] == "TX"
    assert opportunity.metadata["price_tier"] == selected.price_tier["label"]
    assert opportunity.metadata["issue_evidence"]
    assert opportunity.metadata["quick_win"] == selected.quick_win
    bundles = store.list_audit_bundles(opportunity_id=selected.opportunity_id)
    assert len(bundles) == 1
    evidence = store.list_issue_evidence(bundle_id=bundles[0].id or 0)
    assert len(evidence) >= 2


def test_refresh_launch_batch_preserves_launch_bridge_metadata_and_reuses_phone_contact(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path, sender_domain_verified=False)
    store = RevenueStore(settings.db_path)
    source_path = _write_seed_file(
        tmp_path,
        [
            {
                "company_name": "Phone Only Roofing",
                "website_url": "https://phone-only-gap.test/",
                "country_code": "US",
                "segment": "roofing",
                "city": "Austin",
                "state": "TX",
            }
        ],
    )

    first_artifact = refresh_curated_launch_batch(
        store,
        source_path=source_path,
        fetcher=_curated_fetcher(),
    )
    first_record = next(item for item in first_artifact.prospects if item.status == "selected")
    bridge = RevenueAuditAcquisitionBridge(store, settings)
    bridge.build_artifact()

    second_artifact = refresh_curated_launch_batch(
        store,
        source_path=source_path,
        fetcher=_curated_fetcher(),
    )
    second_record = next(item for item in second_artifact.prospects if item.status == "selected")

    contacts = store.list_contacts(account_id=first_record.account_id)
    assert len(contacts) == 1
    assert second_record.contact_id == first_record.contact_id
    opportunity = store.get_opportunity(first_record.opportunity_id or 0)
    assert opportunity is not None
    assert "launch_bridge" in opportunity.metadata
    assert opportunity.metadata["launch_batch_status"] == "selected"


def test_refresh_launch_batch_script_writes_batch_and_bridge_artifacts(tmp_path: Path, monkeypatch) -> None:
    settings = _make_settings(tmp_path, sender_domain_verified=False)
    batch_output = tmp_path / "reports" / "launch_batch.json"
    bridge_output = tmp_path / "reports" / "launch_bridge.json"
    source_path = _write_seed_file(
        tmp_path,
        [
            {
                "company_name": "Growth Gap HVAC",
                "website_url": "https://growth-gap.test/",
                "country_code": "US",
                "segment": "hvac",
                "city": "Austin",
                "state": "TX",
            }
        ],
    )

    monkeypatch.setenv("JJ_REVENUE_PROVIDER", settings.provider)
    monkeypatch.setenv("JJ_REVENUE_PUBLIC_BASE_URL", settings.public_base_url)
    monkeypatch.setenv("JJ_REVENUE_FROM_NAME", settings.from_name)
    monkeypatch.setenv("JJ_REVENUE_FROM_EMAIL", settings.from_email)
    monkeypatch.setenv("SENDGRID_API_KEY", settings.sendgrid_api_key or "")
    monkeypatch.setenv("JJ_REVENUE_SENDER_DOMAIN_VERIFIED", "0")

    exit_code = refresh_launch_batch_main(
        [
            "--db-path",
            str(settings.db_path),
            "--curated-source",
            str(source_path),
            "--batch-output",
            str(batch_output),
            "--bridge-output",
            str(bridge_output),
        ],
        fetcher=_curated_fetcher(),
    )

    batch_payload = json.loads(batch_output.read_text(encoding="utf-8"))
    bridge_payload = json.loads(bridge_output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert batch_payload["selected_prospects"] == 1
    assert batch_payload["qualified_candidates"] == 1
    assert bridge_payload["selected_prospects"] == 1
    assert bridge_payload["source_artifact"] == str(source_path)
    assert bridge_payload["launch_mode"] == "manual_close_only"
