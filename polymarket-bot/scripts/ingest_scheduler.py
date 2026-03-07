#!/usr/bin/env python3
"""Cron-friendly market data ingestion scheduler.

Usage:
    # Single run (good for cron):
    python scripts/ingest_scheduler.py

    # Continuous mode (runs every N minutes):
    python scripts/ingest_scheduler.py --continuous --interval 300

    # First-run probe (fetch + print field summary, no DB write):
    python scripts/ingest_scheduler.py --probe

    # Limit orderbook fetches (top N liquid markets):
    python scripts/ingest_scheduler.py --ob-limit 20

Environment:
    DATABASE_URL must be set (or .env file present).
"""

import argparse
import asyncio
import json
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import structlog

from src.data.ingest.fetcher import MarketDataFetcher, extract_token_ids
from src.data.ingest.models import IngestRun, MarketSnapshot, OrderbookSnapshot, TradeSnapshot
from src.data.ingest.repository import IngestRepository
from src.store.database import DatabaseManager
from src.store.models import Base

logger = structlog.get_logger("ingest_scheduler")


async def run_probe():
    """First-run probe: fetch markets + sample orderbook, print field summary."""
    print("=" * 60)
    print("INGEST PROBE — First Pull Field Summary")
    print("=" * 60)

    async with MarketDataFetcher() as fetcher:
        # 1. Fetch markets
        print("\n[1] Fetching markets from Gamma API...")
        markets = await fetcher.fetch_markets(max_pages=1)
        print(f"    Received {len(markets)} markets")

        if not markets:
            print("    ERROR: No markets returned. Check network/API.")
            return

        # Summarize fields from first market
        sample = markets[0]
        print(f"\n[MARKET FIELDS] Keys in first market response ({len(sample)} fields):")
        for key in sorted(sample.keys()):
            val = sample[key]
            val_type = type(val).__name__
            val_preview = str(val)[:80] if val is not None else "null"
            print(f"    {key:30s}  ({val_type:6s})  {val_preview}")

        # Check expected fields
        expected = [
            "id", "question", "clobTokenIds", "outcomePrices",
            "volume", "liquidity", "endDate", "slug", "active",
            "closed", "condition_id", "category",
        ]
        present = set(sample.keys())
        missing = [f for f in expected if f not in present]
        extra = sorted(present - set(expected))

        print(f"\n[EXPECTED FIELDS CHECK]")
        print(f"    Present:  {len(expected) - len(missing)}/{len(expected)}")
        if missing:
            print(f"    Missing:  {missing}")
        if extra:
            print(f"    Extra:    {extra[:20]}{'...' if len(extra) > 20 else ''}")

        # 2. Fetch a sample orderbook
        token_ids = extract_token_ids(sample)
        if token_ids:
            print(f"\n[2] Fetching orderbook for token {token_ids[0][:20]}...")
            try:
                ob = await fetcher.fetch_orderbook(token_ids[0])
                ob_keys = sorted(ob.keys())
                print(f"    Orderbook keys: {ob_keys}")
                tob = ob.get("_top_of_book", {})
                print(f"    Top-of-book: {json.dumps(tob, indent=6)}")
                bids = ob.get("bids", [])
                asks = ob.get("asks", [])
                if bids:
                    print(f"    Sample bid: {bids[0]}")
                if asks:
                    print(f"    Sample ask: {asks[0]}")
            except Exception as e:
                print(f"    Orderbook error: {e}")

            # 3. Try trades
            print(f"\n[3] Fetching trades for token {token_ids[0][:20]}...")
            trades = await fetcher.fetch_trades(token_ids[0])
            if trades:
                print(f"    Got {len(trades)} trade records")
                print(f"    Sample trade keys: {sorted(trades[0].keys())}")
                print(f"    Sample trade: {json.dumps(trades[0], indent=6)}")
            else:
                print("    No trades data available (endpoint may not be public)")

    print("\n" + "=" * 60)
    print("PROBE COMPLETE — Review fields above before running full ingest")
    print("=" * 60)


async def run_ingest(ob_limit: int = 50):
    """Run a single ingestion cycle."""
    t0 = time.monotonic()

    # Initialize DB and create tables
    DatabaseManager.initialize()
    async with DatabaseManager._engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with DatabaseManager.get_session() as session:
        run = await IngestRepository.create_run(session)
        await session.commit()
        run_id = run.id

    errors = 0
    error_msgs: list[str] = []
    market_count = 0
    ob_count = 0
    trade_count = 0

    try:
        async with MarketDataFetcher() as fetcher:
            # 1. Fetch markets
            logger.info("ingest_step", step="fetch_markets")
            markets = await fetcher.fetch_markets(max_pages=10)

            async with DatabaseManager.get_session() as session:
                market_count = await IngestRepository.store_markets(
                    session, run_id, markets
                )
                await session.commit()

            logger.info("ingest_markets_stored", count=market_count)

            # 2. Fetch orderbooks for top liquid markets
            # Sort by liquidity descending, take top N
            liquid = sorted(
                markets,
                key=lambda m: float(m.get("liquidity", 0) or 0),
                reverse=True,
            )[:ob_limit]

            from src.data.ingest.repository import _parse_token_ids

            for m in liquid:
                market_id = m.get("id") or m.get("condition_id") or ""
                yes_token, no_token = _parse_token_ids(m)
                token_ids = [t for t in [yes_token, no_token] if t]
                if not token_ids:
                    continue

                labels = ["YES", "NO"]
                for i, tid in enumerate(token_ids[:2]):
                    label = labels[i] if i < len(labels) else f"TOKEN_{i}"
                    try:
                        ob = await fetcher.fetch_orderbook(tid)
                        async with DatabaseManager.get_session() as session:
                            await IngestRepository.store_orderbook(
                                session, run_id, market_id, tid, label, ob
                            )
                            await session.commit()
                        ob_count += 1
                    except Exception as e:
                        errors += 1
                        error_msgs.append(f"OB {tid[:16]}: {e}")
                        logger.error(
                            "orderbook_ingest_error",
                            token_id=tid,
                            error=str(e),
                        )

                    # 3. Fetch trades for same token
                    try:
                        trades = await fetcher.fetch_trades(tid)
                        async with DatabaseManager.get_session() as session:
                            stored = await IngestRepository.store_trades(
                                session, run_id, market_id, tid, label, trades
                            )
                            await session.commit()
                        trade_count += stored
                    except Exception as e:
                        errors += 1
                        error_msgs.append(f"Trades {tid[:16]}: {e}")
                        logger.error(
                            "trades_ingest_error",
                            token_id=tid,
                            error=str(e),
                        )

    except Exception as e:
        errors += 1
        error_msgs.append(f"Fatal: {e}")
        logger.error("ingest_fatal_error", error=str(e))
        traceback.print_exc()

    # Finalize run
    elapsed = round(time.monotonic() - t0, 1)
    status = "success" if errors == 0 else ("partial" if market_count > 0 else "failed")

    async with DatabaseManager.get_session() as session:
        stmt = await session.get(IngestRun, run_id)
        if stmt:
            await IngestRepository.finish_run(
                session,
                stmt,
                status=status,
                markets=market_count,
                orderbooks=ob_count,
                trades=trade_count,
                errors=errors,
                error_detail="\n".join(error_msgs[:20]) if error_msgs else None,
            )
            await session.commit()

    logger.info(
        "ingest_complete",
        status=status,
        markets=market_count,
        orderbooks=ob_count,
        trades=trade_count,
        errors=errors,
        elapsed_sec=elapsed,
    )
    print(
        f"[{datetime.utcnow().isoformat()}] Ingest {status}: "
        f"{market_count} markets, {ob_count} orderbooks, "
        f"{trade_count} trades, {errors} errors ({elapsed}s)"
    )


async def main():
    parser = argparse.ArgumentParser(description="Polymarket data ingestion scheduler")
    parser.add_argument(
        "--continuous", action="store_true",
        help="Run continuously instead of single shot"
    )
    parser.add_argument(
        "--interval", type=int, default=300,
        help="Seconds between runs in continuous mode (default: 300)"
    )
    parser.add_argument(
        "--probe", action="store_true",
        help="First-run probe: fetch and print field summary, no DB write"
    )
    parser.add_argument(
        "--ob-limit", type=int, default=50,
        help="Max markets to fetch orderbooks for (default: 50)"
    )
    args = parser.parse_args()

    if args.probe:
        await run_probe()
        return

    if args.continuous:
        print(f"Starting continuous ingestion (interval={args.interval}s)")
        while True:
            try:
                await run_ingest(ob_limit=args.ob_limit)
            except Exception as e:
                logger.error("scheduler_loop_error", error=str(e))
                traceback.print_exc()
            await asyncio.sleep(args.interval)
    else:
        await run_ingest(ob_limit=args.ob_limit)


if __name__ == "__main__":
    asyncio.run(main())
