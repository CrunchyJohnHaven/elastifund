from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from nontrading.digital_products.config import DigitalProductResearchSettings
from nontrading.digital_products.models import NicheCandidate
from nontrading.digital_products.research import NicheDiscoveryAgent, StaticMarketplaceSource
from nontrading.digital_products.store import DigitalProductStore


FIXTURE_PATH = Path(__file__).with_name("fixtures") / "sample_product_niches.json"


def make_settings(tmp_path: Path) -> DigitalProductResearchSettings:
    return DigitalProductResearchSettings(
        db_path=tmp_path / "digital_products.db",
        export_dir=tmp_path / "exports",
        default_marketplace="etsy",
        default_limit=25,
        embedding_dimensions=768,
        competition_floor=1,
    )


def test_niche_discovery_ranks_by_composite_score_formula(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    store = DigitalProductStore(settings.db_path)
    agent = NicheDiscoveryAgent(
        store,
        settings,
    )
    source = StaticMarketplaceSource.from_json_file(FIXTURE_PATH, marketplace="etsy")

    result = agent.run_once(source)

    titles = [item.candidate.title for item in result.ranked_niches]
    assert titles[0] == "ADHD Planner System"
    assert titles[1] == "Wedding Planner Template"
    assert result.ranked_niches[0].composite_score > result.ranked_niches[1].composite_score
    assert len(result.ranked_niches[0].embedding) == 768


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


def test_cli_run_once_writes_bulk_export_and_summary(tmp_path: Path) -> None:
    db_path = tmp_path / "dp.db"
    bulk_path = tmp_path / "bulk" / "knowledge.ndjson"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "nontrading.digital_products.main",
            "--run-once",
            "--source-file",
            str(FIXTURE_PATH),
            "--db-path",
            str(db_path),
            "--emit-elastic-bulk",
            str(bulk_path),
            "--top",
            "3",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "digital-product niche discovery run_count=5" in result.stdout
    assert "#1 | ADHD Planner System" in result.stdout
    assert bulk_path.exists()

    lines = [line for line in bulk_path.read_text().splitlines() if line.strip()]
    assert len(lines) == 10
    first_action = json.loads(lines[0])
    first_document = json.loads(lines[1])
    assert first_action["index"]["_index"] == "elastifund-knowledge"
    assert first_document["title"] == "ADHD Planner System"
    assert len(first_document["vector"]) == 768
