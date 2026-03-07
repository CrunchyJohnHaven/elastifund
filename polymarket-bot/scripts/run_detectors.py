#!/usr/bin/env python3
"""CLI: run all detector plugins, write ranked opportunities to DB.

Usage:
    python -m scripts.run_detectors [--dry-run] [--min-edge 0.5] [--max-pages 5]

Flags:
    --dry-run      Print opportunities to stdout; skip DB write.
    --min-edge     Minimum edge_pct to surface (default 0.5).
    --max-pages    Gamma API pages to fetch (default 5, 100 markets/page).
"""

import argparse
import asyncio
import os
import sys
from datetime import datetime
from uuid import uuid4

# Ensure project root on path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import structlog

from src.data.ingest.fetcher import MarketDataFetcher
from src.detectors.base import Opportunity
from src.detectors.structural import StructuralDetector

logger = structlog.get_logger(__name__)


def build_detectors(min_edge: float) -> list:
    """Instantiate all registered detectors."""
    return [
        StructuralDetector(min_edge_pct=min_edge),
    ]


async def run(args: argparse.Namespace) -> None:
    detectors = build_detectors(args.min_edge)
    logger.info("detectors_loaded", count=len(detectors), names=[d.name for d in detectors])

    # Fetch markets
    async with MarketDataFetcher() as fetcher:
        markets = await fetcher.fetch_markets(max_pages=args.max_pages, active_only=True)
    logger.info("markets_fetched", count=len(markets))

    # Run each detector
    all_opps: list[Opportunity] = []
    for det in detectors:
        opps = await det.scan(markets)
        logger.info("detector_done", detector=det.name, opportunities=len(opps))
        all_opps.extend(opps)

    all_opps.sort(key=lambda o: o.edge_pct, reverse=True)

    if not all_opps:
        logger.info("no_opportunities_found")
        print("No structural mispricings detected.")
        return

    # Print summary
    print(f"\n{'='*80}")
    print(f"  DETECTOR RESULTS — {len(all_opps)} opportunities found")
    print(f"{'='*80}\n")
    for i, opp in enumerate(all_opps, 1):
        print(f"  #{i}  [{opp.detector}/{opp.kind}]  edge={opp.edge_pct:.2f}%")
        print(f"      {opp.group_label}")
        print(f"      {opp.detail}")
        print(f"      markets: {', '.join(opp.market_ids[:3])}{'...' if len(opp.market_ids) > 3 else ''}")
        print()

    if args.dry_run:
        print("  (dry-run mode — skipping DB write)\n")
        return

    # Write to DB
    from src.store.database import DatabaseManager
    from src.store.models import DetectorOpportunity

    DatabaseManager.initialize()
    await DatabaseManager.init_db()

    run_id = str(uuid4())
    async with DatabaseManager.get_session() as session:
        for opp in all_opps:
            row = DetectorOpportunity(
                id=str(uuid4()),
                run_id=run_id,
                detector=opp.detector,
                kind=opp.kind,
                group_label=opp.group_label,
                market_ids=list(opp.market_ids),
                edge_pct=opp.edge_pct,
                detail=opp.detail,
                prices=opp.prices,
                meta_data=opp.meta,
                detected_at=opp.detected_at,
            )
            session.add(row)
        await session.commit()
        logger.info("opportunities_persisted", run_id=run_id, count=len(all_opps))
        print(f"  Persisted {len(all_opps)} opportunities (run_id={run_id})")

    await DatabaseManager.close()


def main():
    parser = argparse.ArgumentParser(description="Run detector plugins")
    parser.add_argument("--dry-run", action="store_true", help="Print only, skip DB")
    parser.add_argument("--min-edge", type=float, default=0.5, help="Min edge %% (default 0.5)")
    parser.add_argument("--max-pages", type=int, default=5, help="Gamma API pages (default 5)")
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
