#!/usr/bin/env python3
"""Data quality report CLI for market data ingestion.

Shows:
- Last successful pull time
- Markets pulled count
- Missing fields / schema drift flags
- Recent run history

Usage:
    python scripts/ingest_quality_report.py
    python scripts/ingest_quality_report.py --runs 20
    python scripts/ingest_quality_report.py --check-drift
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import desc, func, select

from src.data.ingest.models import (
    IngestRun,
    MarketSnapshot,
    OrderbookSnapshot,
    TradeSnapshot,
)
from src.store.database import DatabaseManager
from src.store.models import Base


# Expected normalized fields per model
EXPECTED_MARKET_FIELDS = {
    "market_id", "condition_id", "question", "slug", "status",
    "outcome_yes_price", "outcome_no_price", "volume", "liquidity",
    "clob_token_id_yes", "clob_token_id_no", "end_date", "category",
}

EXPECTED_OB_FIELDS = {
    "best_bid", "best_ask", "spread", "midpoint", "bid_depth", "ask_depth",
}


async def generate_report(num_runs: int = 10, check_drift: bool = False):
    DatabaseManager.initialize()
    async with DatabaseManager._engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    print("=" * 60)
    print("DATA QUALITY REPORT")
    print(f"Generated: {datetime.utcnow().isoformat()}Z")
    print("=" * 60)

    async with DatabaseManager.get_session() as session:
        # ── Last Successful Pull ───────────────────────────────
        stmt = (
            select(IngestRun)
            .where(IngestRun.status.in_(["success", "partial"]))
            .order_by(desc(IngestRun.finished_at))
            .limit(1)
        )
        result = await session.execute(stmt)
        last_good = result.scalar_one_or_none()

        print("\n--- Last Successful Pull ---")
        if last_good:
            age = datetime.utcnow() - last_good.finished_at if last_good.finished_at else None
            age_str = f" ({age.total_seconds()/60:.0f} min ago)" if age else ""
            print(f"  Time:        {last_good.finished_at}{age_str}")
            print(f"  Status:      {last_good.status}")
            print(f"  Markets:     {last_good.markets_fetched}")
            print(f"  Orderbooks:  {last_good.orderbooks_fetched}")
            print(f"  Trades:      {last_good.trades_fetched}")
            print(f"  Errors:      {last_good.errors}")
            if last_good.error_detail:
                print(f"  Error detail: {last_good.error_detail[:200]}")
        else:
            print("  No successful runs found.")

        # ── Totals ─────────────────────────────────────────────
        print("\n--- Database Totals ---")

        total_runs = await session.execute(
            select(func.count(IngestRun.id))
        )
        print(f"  Total runs:             {total_runs.scalar() or 0}")

        total_markets = await session.execute(
            select(func.count(MarketSnapshot.id))
        )
        print(f"  Total market snapshots:  {total_markets.scalar() or 0}")

        unique_markets = await session.execute(
            select(func.count(func.distinct(MarketSnapshot.market_id)))
        )
        print(f"  Unique markets:          {unique_markets.scalar() or 0}")

        total_obs = await session.execute(
            select(func.count(OrderbookSnapshot.id))
        )
        print(f"  Total OB snapshots:      {total_obs.scalar() or 0}")

        total_trades = await session.execute(
            select(func.count(TradeSnapshot.id))
        )
        print(f"  Total trade snapshots:   {total_trades.scalar() or 0}")

        # ── Recent Runs ────────────────────────────────────────
        print(f"\n--- Recent Runs (last {num_runs}) ---")
        runs_stmt = (
            select(IngestRun)
            .order_by(desc(IngestRun.id))
            .limit(num_runs)
        )
        runs_result = await session.execute(runs_stmt)
        runs = runs_result.scalars().all()

        if runs:
            print(f"  {'ID':>4}  {'Status':>8}  {'Markets':>7}  {'OBs':>4}  {'Trades':>6}  {'Errs':>4}  Finished")
            print(f"  {'─'*4}  {'─'*8}  {'─'*7}  {'─'*4}  {'─'*6}  {'─'*4}  {'─'*20}")
            for r in runs:
                fin = r.finished_at.strftime("%Y-%m-%d %H:%M") if r.finished_at else "running..."
                print(
                    f"  {r.id:>4}  {r.status:>8}  {r.markets_fetched:>7}  "
                    f"{r.orderbooks_fetched:>4}  {r.trades_fetched:>6}  "
                    f"{r.errors:>4}  {fin}"
                )
        else:
            print("  No runs recorded yet.")

        # ── Missing Fields / Schema Drift ──────────────────────
        if check_drift:
            print("\n--- Schema Drift Check ---")
            await _check_drift(session)

    print("\n" + "=" * 60)


async def _check_drift(session):
    """Check for NULL rates in normalized fields — indicates schema drift."""
    # Sample latest 100 market snapshots
    stmt = (
        select(MarketSnapshot)
        .order_by(desc(MarketSnapshot.fetched_at))
        .limit(100)
    )
    result = await session.execute(stmt)
    snapshots = result.scalars().all()

    if not snapshots:
        print("  No market snapshots to check.")
        return

    null_counts: dict[str, int] = {f: 0 for f in EXPECTED_MARKET_FIELDS}
    total = len(snapshots)

    for s in snapshots:
        for field in EXPECTED_MARKET_FIELDS:
            if getattr(s, field, None) is None:
                null_counts[field] += 1

    print(f"  Checked {total} recent market snapshots:")
    drift_found = False
    for field, nulls in sorted(null_counts.items()):
        pct = nulls / total * 100
        flag = " *** DRIFT" if pct > 50 else ""
        if nulls > 0:
            drift_found = True
            print(f"    {field:25s}  {nulls:>3}/{total} null ({pct:.0f}%){flag}")

    if not drift_found:
        print("    All normalized fields populated. No drift detected.")

    # Check for new keys in raw payloads not captured in normalized cols
    if snapshots:
        raw = snapshots[0].raw_payload or {}
        raw_keys = set(raw.keys())
        # Known Gamma API keys we intentionally skip
        known_skip = {
            "image", "icon", "description", "outcomes", "tags",
            "orderPriceMinTickSize", "orderMinSize", "notificationsEnabled",
            "negRisk", "negRiskMarketID", "negRiskRequestID",
        }
        novel = raw_keys - known_skip - {
            "id", "question", "clobTokenIds", "outcomePrices",
            "volume", "liquidity", "endDate", "slug", "active",
            "closed", "condition_id", "category", "end_date_iso",
        }
        if novel:
            print(f"\n  New/unmapped raw payload keys found ({len(novel)}):")
            for k in sorted(novel):
                print(f"    - {k}")
        else:
            print("\n  No unmapped payload keys detected.")

    # Check orderbook snapshots
    ob_stmt = (
        select(OrderbookSnapshot)
        .order_by(desc(OrderbookSnapshot.fetched_at))
        .limit(50)
    )
    ob_result = await session.execute(ob_stmt)
    ob_snaps = ob_result.scalars().all()

    if ob_snaps:
        ob_null_counts = {f: 0 for f in EXPECTED_OB_FIELDS}
        for s in ob_snaps:
            for field in EXPECTED_OB_FIELDS:
                if getattr(s, field, None) is None:
                    ob_null_counts[field] += 1

        ob_drift = {k: v for k, v in ob_null_counts.items() if v > 0}
        if ob_drift:
            print(f"\n  Orderbook drift ({len(ob_snaps)} snapshots):")
            for field, nulls in sorted(ob_drift.items()):
                pct = nulls / len(ob_snaps) * 100
                print(f"    {field:20s}  {nulls:>3}/{len(ob_snaps)} null ({pct:.0f}%)")
        else:
            print(f"\n  Orderbook fields: all populated ({len(ob_snaps)} snapshots).")


async def main():
    parser = argparse.ArgumentParser(description="Data quality report for ingestion")
    parser.add_argument(
        "--runs", type=int, default=10,
        help="Number of recent runs to show (default: 10)"
    )
    parser.add_argument(
        "--check-drift", action="store_true",
        help="Check for schema drift / missing fields"
    )
    args = parser.parse_args()

    await generate_report(num_runs=args.runs, check_drift=args.check_drift)


if __name__ == "__main__":
    asyncio.run(main())
