"""CLI entrypoint for digital-product niche discovery."""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

from .config import DigitalProductResearchSettings
from .research import NicheDiscoveryAgent, StaticMarketplaceSource
from .store import DigitalProductStore


def format_result(agent: NicheDiscoveryAgent, ranked: list, top: int) -> str:
    lines = [
        f"digital-product niche discovery run_count={len(ranked)}",
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
    return "\n".join(lines)


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
    store = DigitalProductStore(settings.db_path)
    agent = NicheDiscoveryAgent(store, settings)
    result = agent.run_once(source, limit=args.limit)

    if args.emit_elastic_bulk:
        bulk_path = Path(args.emit_elastic_bulk)
        bulk_path.parent.mkdir(parents=True, exist_ok=True)
        bulk_path.write_text(agent.build_elastic_bulk(list(result.ranked_niches)))

    print(format_result(agent, list(result.ranked_niches), top=max(1, args.top)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
