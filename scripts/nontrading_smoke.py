#!/usr/bin/env python3
"""Deterministic smoke run for both non-trading lanes."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nontrading.campaigns.engine import CampaignEngine
from nontrading.config import RevenueAgentSettings
from nontrading.digital_products.config import DigitalProductResearchSettings
from nontrading.digital_products.research import NicheDiscoveryAgent, StaticMarketplaceSource
from nontrading.digital_products.store import DigitalProductStore
from nontrading.email.sender import DryRunSender
from nontrading.importers.csv_import import import_csv
from nontrading.risk import RevenueRiskManager
from nontrading.store import RevenueStore

LEADS_FIXTURE = ROOT / "nontrading" / "tests" / "fixtures" / "sample_leads.csv"
NICHES_FIXTURE = ROOT / "nontrading" / "tests" / "fixtures" / "sample_product_niches.json"


def run_smoke() -> dict[str, Any]:
    """Run both non-trading lanes against deterministic fixtures."""

    with tempfile.TemporaryDirectory(prefix="elastifund-nontrading-smoke-") as tmpdir:
        tmp = Path(tmpdir)

        revenue_result = _run_revenue_smoke(tmp)
        digital_result = _run_digital_product_smoke(tmp)

    return {
        "revenue_agent": revenue_result,
        "digital_products": digital_result,
    }


def format_smoke_summary(result: dict[str, Any]) -> str:
    """Render smoke output as concise CLI text."""

    revenue = result["revenue_agent"]
    digital = result["digital_products"]

    return "\n".join(
        [
            "nontrading smoke ok",
            (
                "revenue_agent "
                f"campaigns={revenue['campaigns']} "
                f"leads={revenue['leads']} "
                f"sent={revenue['sent']} "
                f"filtered={revenue['filtered']} "
                f"deliverability={revenue['deliverability_status']} "
                f"recipients={','.join(revenue['recipients'])}"
            ),
            (
                "digital_products "
                f"ranked={digital['ranked']} "
                f"top_title={digital['top_title']} "
                f"top_score={digital['top_score']:.4f} "
                f"elastic_index={digital['elastic_index']} "
                f"vector_dims={digital['vector_dims']}"
            ),
        ]
    )


def _run_revenue_smoke(tmp: Path) -> dict[str, Any]:
    settings = RevenueAgentSettings(
        db_path=tmp / "revenue_agent.db",
        outbox_dir=tmp / "outbox",
        public_base_url="https://example.invalid",
        postal_address="100 Main Street, Austin, TX 78701",
        daily_send_quota=10,
    )
    settings.ensure_paths()

    store = RevenueStore(settings.db_path)
    import_csv(LEADS_FIXTURE, store)
    store.ensure_default_campaign(settings)

    engine = CampaignEngine(
        store,
        RevenueRiskManager(store, settings),
        DryRunSender(settings, store),
        settings,
    )
    summary = engine.run_once()
    snapshot = store.status_snapshot()
    recipients = sorted(
        message.recipient_email
        for message in store.list_outbox_messages()
        if message.status == "dry_run"
    )

    return {
        "campaigns": int(snapshot["campaigns"]),
        "leads": int(snapshot["leads"]),
        "deliverability_status": str(snapshot["deliverability_status"]),
        "sent": int(summary.sent),
        "filtered": int(summary.filtered),
        "suppressed": int(summary.suppressed),
        "recipients": recipients,
    }


def _run_digital_product_smoke(tmp: Path) -> dict[str, Any]:
    settings = DigitalProductResearchSettings(
        db_path=tmp / "digital_products.db",
        export_dir=tmp / "exports",
        default_marketplace="etsy",
        default_limit=25,
        embedding_dimensions=768,
        competition_floor=1,
    )
    settings.ensure_paths()

    store = DigitalProductStore(settings.db_path)
    agent = NicheDiscoveryAgent(store, settings)
    source = StaticMarketplaceSource.from_json_file(NICHES_FIXTURE, marketplace="etsy")
    result = agent.run_once(source)
    ranked = list(result.ranked_niches)
    top = ranked[0]

    return {
        "ranked": len(ranked),
        "top_title": top.candidate.title,
        "top_score": float(top.composite_score),
        "elastic_index": settings.elastic_index_name,
        "vector_dims": len(top.embedding),
    }


def main() -> int:
    result = run_smoke()
    print(format_smoke_summary(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
