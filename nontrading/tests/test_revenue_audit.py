from __future__ import annotations

from pathlib import Path

from nontrading.revenue_audit import StaticPageFetcher, build_audit_bundle, discover_prospect, run_detectors


FIXTURE_DIR = Path(__file__).with_name("fixtures") / "revenue_audit"


def _fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def _gap_fetcher() -> StaticPageFetcher:
    return StaticPageFetcher(
        {
            "https://acme-builders.test/": _fixture("gap_home.html"),
            "https://acme-builders.test/services": _fixture("gap_services.html"),
            "https://acme-builders.test/about": _fixture("gap_about.html"),
        }
    )


def _strong_fetcher() -> StaticPageFetcher:
    return StaticPageFetcher(
        {
            "https://lonestarfence.test/": _fixture("strong_home.html"),
            "https://lonestarfence.test/services/fence-repair": _fixture("strong_services.html"),
            "https://lonestarfence.test/contact": _fixture("strong_contact.html"),
        }
    )


def test_discovery_normalizes_public_web_pages_into_prospect_profile() -> None:
    profile = discover_prospect("https://acme-builders.test/", fetcher=_gap_fetcher())

    assert profile.domain == "acme-builders.test"
    assert profile.company_name == "Acme"
    assert len(profile.pages) == 3
    assert profile.pages[0].title == "Acme"
    assert profile.pages[0].internal_links == (
        "https://acme-builders.test/services",
        "https://acme-builders.test/about",
    )
    assert profile.contact_channels == ()


def test_gap_fixture_produces_stable_issue_bundle() -> None:
    profile = discover_prospect("https://acme-builders.test/", fetcher=_gap_fetcher())

    issue_ids = [issue.issue_id for issue in run_detectors(profile)]

    assert issue_ids == [
        "missing_contact_affordance",
        "missing_meta_description",
        "unclear_primary_offer",
        "weak_cta_structure",
        "heavy_homepage_payload",
        "missing_business_schema",
        "weak_title_signal",
    ]


def test_scoring_prefers_issue_dense_site_over_polished_fixture() -> None:
    gap_bundle = build_audit_bundle(discover_prospect("https://acme-builders.test/", fetcher=_gap_fetcher()))
    strong_bundle = build_audit_bundle(discover_prospect("https://lonestarfence.test/", fetcher=_strong_fetcher()))

    assert len(gap_bundle.issues) == 7
    assert len(strong_bundle.issues) == 0
    assert gap_bundle.score.purchase_probability > strong_bundle.score.purchase_probability
    assert gap_bundle.score.expected_margin_usd > strong_bundle.score.expected_margin_usd
    assert gap_bundle.score.compliance_risk_score > strong_bundle.score.compliance_risk_score
    assert gap_bundle.score.explanation["inputs"]["issue_count"] == 7


def test_strong_fixture_discovers_public_contact_channels() -> None:
    profile = discover_prospect("https://lonestarfence.test/", fetcher=_strong_fetcher())

    kinds = {channel.kind for channel in profile.contact_channels}
    assert {"email", "phone", "contact_form", "contact_page"}.issubset(kinds)
    assert "https://lonestarfence.test/contact" in profile.public_contact_urls
