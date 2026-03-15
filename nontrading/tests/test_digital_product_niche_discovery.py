from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

from nontrading.digital_products.config import DigitalProductResearchSettings
from nontrading.digital_products.models import NicheCandidate
from nontrading.digital_products.research import NicheDiscoveryAgent, StaticMarketplaceSource
from nontrading.digital_products.store import DigitalProductStore
from nontrading.store import RevenueStore


FIXTURE_PATH = Path(__file__).with_name("fixtures") / "sample_product_niches.json"


def make_settings(tmp_path: Path) -> DigitalProductResearchSettings:
    return DigitalProductResearchSettings(
        db_path=tmp_path / "digital_products.db",
        export_dir=tmp_path / "exports",
        default_marketplace="etsy",
        default_limit=25,
        embedding_dimensions=768,
        competition_floor=1,
        minimum_audit_opportunity=0.55,
        minimum_icp_match_score=0.55,
        lead_list_per_niche=2,
        synthetic_leads_enabled=True,
    )


def build_service_candidate(
    *,
    slug: str = "roofing-contractors",
    title: str = "Roofing Contractors",
    website_signals: dict[str, bool] | None = None,
    lead_targets: list[dict[str, object]] | None = None,
    revenue: float = 1_800_000.0,
) -> NicheCandidate:
    return NicheCandidate(
        niche_slug=slug,
        title=title,
        product_type="service_business",
        marketplace="web",
        keywords=("roofing", "contractor", "local", "service"),
        monthly_demand=1400,
        competition_count=650,
        average_price=850.0,
        profit_margin=0.62,
        source="service_fixture",
        metadata={
            "business_model": "service",
            "annual_revenue_estimate": revenue,
            "company_size": "small",
            "website_signals": website_signals
            or {
                "missing_meta_tags": True,
                "slow_load": True,
                "not_mobile_optimized": True,
                "missing_schema_markup": True,
                "weak_cta": True,
            },
            "lead_targets": lead_targets
            or [
                {
                    "company_name": "North Peak Roofing",
                    "domain": "northpeakroofing.example",
                    "website_url": "https://northpeakroofing.example",
                    "email": "info@northpeakroofing.example",
                    "country_code": "US",
                    "industry": "roofing",
                }
            ],
        },
    )


def test_niche_discovery_ranks_by_composite_score_formula(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    store = DigitalProductStore(settings.db_path)
    agent = NicheDiscoveryAgent(store, settings)
    source = StaticMarketplaceSource.from_json_file(FIXTURE_PATH, marketplace="etsy")

    result = agent.run_once(source)

    titles = [item.candidate.title for item in result.ranked_niches]
    assert titles[0] == "ADHD Planner System"
    assert titles[1] == "Wedding Planner Template"
    assert result.ranked_niches[0].composite_score > result.ranked_niches[1].composite_score
    assert len(result.ranked_niches[0].embedding) == 768
    assert 0.0 <= result.ranked_niches[0].audit_opportunity <= 1.0
    assert 0.0 <= result.ranked_niches[0].icp_match_score <= 1.0


def test_audit_opportunity_dimension_rewards_obvious_site_gaps(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    store = DigitalProductStore(settings.db_path)
    agent = NicheDiscoveryAgent(store, settings)
    source = StaticMarketplaceSource(
        [
            build_service_candidate(),
            build_service_candidate(
                slug="roofing-contractors-clean",
                title="Roofing Contractors With Strong Sites",
                website_signals={
                    "missing_meta_tags": False,
                    "slow_load": False,
                    "not_mobile_optimized": False,
                    "missing_schema_markup": False,
                    "weak_cta": False,
                },
                lead_targets=[
                    {
                        "company_name": "Summit Roofing",
                        "domain": "summitroofing.example",
                        "website_url": "https://summitroofing.example",
                        "email": "info@summitroofing.example",
                        "country_code": "US",
                        "industry": "roofing",
                    }
                ],
            ),
        ]
    )

    result = agent.run_once(source, marketplace="web")

    assert result.ranked_niches[0].audit_opportunity > result.ranked_niches[1].audit_opportunity
    assert result.ranked_niches[0].icp_match_score >= settings.minimum_icp_match_score


def test_lead_list_generation_filters_by_icp_and_matches_csv_import_shape(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    store = DigitalProductStore(settings.db_path)
    agent = NicheDiscoveryAgent(store, settings)
    source = StaticMarketplaceSource(
        [
            build_service_candidate(),
            NicheCandidate(
                niche_slug="adhd-planner",
                title="ADHD Planner System",
                product_type="printable_planner",
                marketplace="web",
                keywords=("adhd", "planner", "digital"),
                monthly_demand=960,
                competition_count=320,
                average_price=14.0,
                profit_margin=0.9,
                source="fixture",
            ),
        ]
    )

    result = agent.run_once(source, marketplace="web")

    assert len(result.generated_leads) == 1
    row = result.generated_leads[0].to_csv_row()
    assert row["email"] == "info@northpeakroofing.example"
    assert row["company_name"] == "North Peak Roofing"
    assert row["country_code"] == "US"
    assert row["explicit_opt_in"] == "false"
    assert row["synthetic"] == "false"
    assert "metadata_json" in row


def test_store_persists_rankings_and_similarity_search(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    store = DigitalProductStore(settings.db_path)
    agent = NicheDiscoveryAgent(store, settings)
    source = StaticMarketplaceSource(
        [
            NicheCandidate(
                niche_slug="teacher-worksheets",
                title="Teacher Worksheets Bundle",
                product_type="educational_worksheets",
                keywords=("teacher", "homeschool", "printable"),
                monthly_demand=1800,
                competition_count=2400,
                average_price=11.5,
                profit_margin=0.88,
                marketplace="etsy",
            ),
            NicheCandidate(
                niche_slug="teacher-lesson-plans",
                title="Teacher Lesson Plan Kit",
                product_type="educational_worksheets",
                keywords=("teacher", "classroom", "lesson plans"),
                monthly_demand=900,
                competition_count=900,
                average_price=12.0,
                profit_margin=0.87,
                marketplace="etsy",
            ),
        ]
    )

    result = agent.run_once(source)
    stored = store.list_ranked_niches()
    matches = store.similar_niches("homeschool teacher printable bundle", limit=1)

    assert result.run.persisted_count == 2
    assert len(stored) == 2
    assert matches[0].niche.candidate.niche_slug == "teacher-worksheets"
    assert 0.0 <= matches[0].similarity_score <= 1.0
    assert "audit_opportunity" in stored[0].to_knowledge_document(index_name="idx")


def test_elastic_bulk_export_includes_audit_and_icp_fields(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    store = DigitalProductStore(settings.db_path)
    agent = NicheDiscoveryAgent(store, settings)
    source = StaticMarketplaceSource([build_service_candidate()])

    result = agent.run_once(source, marketplace="web")
    bulk = agent.build_elastic_bulk(list(result.ranked_niches))
    lines = [line for line in bulk.splitlines() if line.strip()]
    document = json.loads(lines[1])

    assert document["title"] == "Roofing Contractors"
    assert document["audit_opportunity"] > 0.0
    assert document["icp_match_score"] > 0.0
    assert document["audit_fit_score"] >= document["icp_match_score"] / 2.0


def test_run_once_can_sync_qualified_targets_into_revenue_store(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    revenue_store = RevenueStore(tmp_path / "revenue_agent.db")
    store = DigitalProductStore(settings.db_path, revenue_store=revenue_store)
    agent = NicheDiscoveryAgent(store, settings)
    source = StaticMarketplaceSource([build_service_candidate()])

    result = agent.run_once(source, marketplace="web")

    lead = revenue_store.get_lead_by_email("info@northpeakroofing.example")
    accounts = revenue_store.list_accounts()
    opportunities = revenue_store.list_opportunities()

    assert lead is not None
    assert len(accounts) == 1
    assert len(opportunities) == 1
    assert result.crm_sync_summary.leads_processed == 1
    assert result.crm_sync_summary.accounts_processed == 1
    assert result.crm_sync_summary.opportunities_processed == 1


def test_cli_run_once_writes_bulk_export_summary_and_lead_csv(tmp_path: Path) -> None:
    fixture_path = tmp_path / "service_niches.json"
    fixture_path.write_text(
        json.dumps(
            [
                {
                    "niche_slug": "roofing-contractors",
                    "title": "Roofing Contractors",
                    "product_type": "service_business",
                    "marketplace": "web",
                    "keywords": ["roofing", "contractor", "local", "service"],
                    "monthly_demand": 1400,
                    "competition_count": 650,
                    "average_price": 850.0,
                    "profit_margin": 0.62,
                    "source": "service_fixture",
                    "metadata": {
                        "business_model": "service",
                        "annual_revenue_estimate": 1800000,
                        "company_size": "small",
                        "website_signals": {
                            "missing_meta_tags": True,
                            "slow_load": True,
                            "not_mobile_optimized": True,
                            "missing_schema_markup": True,
                            "weak_cta": True,
                        },
                        "lead_targets": [
                            {
                                "company_name": "North Peak Roofing",
                                "domain": "northpeakroofing.example",
                                "website_url": "https://northpeakroofing.example",
                                "email": "info@northpeakroofing.example",
                                "country_code": "US",
                                "industry": "roofing",
                            }
                        ],
                    },
                }
            ]
        )
    )
    db_path = tmp_path / "dp.db"
    bulk_path = tmp_path / "bulk" / "knowledge.ndjson"
    lead_csv = tmp_path / "bulk" / "leads.csv"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "nontrading.digital_products.main",
            "--run-once",
            "--source-file",
            str(fixture_path),
            "--db-path",
            str(db_path),
            "--marketplace",
            "web",
            "--emit-elastic-bulk",
            str(bulk_path),
            "--emit-lead-csv",
            str(lead_csv),
            "--top",
            "1",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "digital-product niche discovery run_count=1" in result.stdout
    assert "lead_count=1" in result.stdout
    assert "#1 | Roofing Contractors" in result.stdout
    assert bulk_path.exists()
    assert lead_csv.exists()

    lines = [line for line in bulk_path.read_text().splitlines() if line.strip()]
    first_action = json.loads(lines[0])
    first_document = json.loads(lines[1])
    assert first_action["index"]["_index"] == "elastifund-knowledge"
    assert first_document["title"] == "Roofing Contractors"
    assert first_document["audit_opportunity"] > 0.0
    assert first_document["icp_match_score"] > 0.0

    with lead_csv.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["email"] == "info@northpeakroofing.example"
