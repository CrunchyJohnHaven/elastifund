"""CLI entrypoint for digital-product niche discovery."""

from __future__ import annotations

import argparse
import csv
from dataclasses import replace
from pathlib import Path

from nontrading.config import RevenueAgentSettings
from nontrading.store import RevenueStore

from .config import DigitalProductResearchSettings
from .models import DiscoveryResult, GeneratedLead
from .research import NicheDiscoveryAgent, StaticMarketplaceSource
from .store import DigitalProductStore


def format_result(agent: NicheDiscoveryAgent, result: DiscoveryResult, top: int) -> str:
    ranked = list(result.ranked_niches)
    lines = [
        f"digital-product niche discovery run_count={len(ranked)} lead_count={len(result.generated_leads)}",
    ]
    for item in ranked[:top]:
        keywords = ",".join(item.candidate.keywords[:4]) or "-"
        lines.append(
            " | ".join(
                [
                    f"#{item.rank}",
                    item.candidate.title,
                    f"type={item.candidate.product_type}",
                    f"score={item.composite_score:.4f}",
                    f"demand={item.candidate.monthly_demand:.0f}",
                    f"price={item.candidate.average_price:.2f}",
                    f"competition={item.candidate.competition_count}",
                    f"audit={item.audit_opportunity:.2f}",
                    f"icp={item.icp_match_score:.2f}",
                    f"saturation={item.saturation_band}",
                    f"keywords={keywords}",
                ]
            )
        )
    if ranked:
        top_doc = ranked[0].to_knowledge_document(index_name=agent.settings.elastic_index_name)
        lines.append(
            f"elastic_index={agent.settings.elastic_index_name} vector_dims={len(top_doc['vector'])}"
        )
    sync = result.crm_sync_summary
    if sync.leads_processed or sync.accounts_processed or sync.opportunities_processed:
        lines.append(
            "crm_sync "
            f"leads={sync.leads_processed} "
            f"accounts={sync.accounts_processed} "
            f"opportunities={sync.opportunities_processed}"
        )
    return "\n".join(lines)


def write_lead_csv(path: Path, leads: list[GeneratedLead]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(GeneratedLead.csv_headers()))
        writer.writeheader()
        for lead in leads:
            writer.writerow(lead.to_csv_row())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the digital-product niche discovery agent.")
    parser.add_argument("--run-once", action="store_true", help="Discover and rank niches once.")
    parser.add_argument("--source-file", help="JSON file with normalized marketplace niche candidates.")
    parser.add_argument("--db-path", help="Override JJ_DP_DB_PATH for this process.")
    parser.add_argument("--marketplace", help="Override JJ_DP_MARKETPLACE for this run.")
    parser.add_argument("--limit", type=int, help="Maximum candidates to evaluate.")
    parser.add_argument("--top", type=int, default=5, help="How many ranked niches to print.")
    parser.add_argument(
        "--emit-elastic-bulk",
        help="Optional path for Elasticsearch bulk NDJSON output.",
    )
    parser.add_argument(
        "--emit-lead-csv",
        help="Optional path for CSV output consumable by nontrading.importers.csv_import.",
    )
    parser.add_argument(
        "--sync-crm",
        action="store_true",
        help="Sync generated lead and opportunity records into the non-trading revenue store.",
    )
    parser.add_argument(
        "--crm-db-path",
        help="Override JJ_REVENUE_DB_PATH when --sync-crm is enabled.",
    )
    args = parser.parse_args(argv)

    if not args.run_once:
        parser.error("Only --run-once is currently supported.")
    if not args.source_file:
        parser.error("--source-file is required for --run-once.")

    settings = DigitalProductResearchSettings.from_env()
    if args.db_path:
        settings = replace(settings, db_path=Path(args.db_path))
    if args.marketplace:
        settings = replace(settings, default_marketplace=args.marketplace.lower())
    settings.ensure_paths()

    source = StaticMarketplaceSource.from_json_file(
        args.source_file,
        marketplace=settings.default_marketplace,
    )
    revenue_store = None
    if args.sync_crm or args.crm_db_path:
        revenue_settings = RevenueAgentSettings.from_env()
        crm_db_path = Path(args.crm_db_path) if args.crm_db_path else revenue_settings.db_path
        crm_db_path.parent.mkdir(parents=True, exist_ok=True)
        revenue_store = RevenueStore(crm_db_path)

    store = DigitalProductStore(settings.db_path, revenue_store=revenue_store)
    agent = NicheDiscoveryAgent(store, settings)
    result = agent.run_once(source, limit=args.limit)

    if args.emit_elastic_bulk:
        bulk_path = Path(args.emit_elastic_bulk)
        bulk_path.parent.mkdir(parents=True, exist_ok=True)
        bulk_path.write_text(agent.build_elastic_bulk(list(result.ranked_niches)))
    if args.emit_lead_csv:
        write_lead_csv(Path(args.emit_lead_csv), list(result.generated_leads))

    print(format_result(agent, result, top=max(1, args.top)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
