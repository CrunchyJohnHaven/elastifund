"""
Historical Data Pipeline Runner -- Daily incremental ingestion.

Usage:
    python -m data_layer.pipeline_runner          # Full incremental run
    python -m data_layer.pipeline_runner --venue polymarket  # Single venue
    python -m data_layer.pipeline_runner --quality-check     # Quality checks only
    python -m data_layer.pipeline_runner --calibration       # Build calibration snapshots
"""
import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from data_layer.historical_db import HistoricalDB, classify_bin
from data_layer.ingestors import polymarket_ingestor, kalshi_ingestor

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def ingest_polymarket(db: HistoricalDB):
    """Run Polymarket incremental ingestion."""
    watermark = db.get_watermark("polymarket")
    wm_ts = watermark.get("last_settle_scan_ts", 0)

    logger.info(f"Polymarket: scanning closed markets since ts={wm_ts}")
    count = 0
    max_ts = wm_ts

    for raw_market in polymarket_ingestor.scan_closed_markets(wm_ts):
        parsed = polymarket_ingestor.parse_market(raw_market)

        db.upsert_market(**{k: v for k, v in parsed.items()
                           if k not in ("yes_token_id", "outcome_yes")})

        # Ingest resolution if we have outcome
        if parsed["outcome_yes"] is not None and parsed["settle_ts"]:
            close_ts = parsed["close_ts"] or parsed["settle_ts"]
            ttr = parsed["settle_ts"] - close_ts if close_ts else 0

            # Get final price
            final_price = None
            if parsed.get("yes_token_id") and close_ts:
                prices = polymarket_ingestor.fetch_yes_price_history(
                    parsed["yes_token_id"],
                    close_ts - 3600,  # 1 hour before close
                    close_ts,
                    interval="1m",
                )
                if prices:
                    final_price = prices[-1]["price"]

            db.upsert_resolution(
                venue="polymarket",
                market_id=parsed["market_id"],
                outcome_yes=parsed["outcome_yes"],
                settlement_value=1.0 if parsed["outcome_yes"] == 1 else 0.0,
                settled_ts=parsed["settle_ts"],
                time_to_resolution_s=ttr,
                final_yes_price=final_price,
                final_yes_price_ts=close_ts,
            )

        # Ingest price history
        if parsed.get("yes_token_id") and parsed.get("open_ts") and parsed.get("close_ts"):
            prices = polymarket_ingestor.fetch_yes_price_history(
                parsed["yes_token_id"],
                parsed["open_ts"],
                parsed["close_ts"],
                interval="1h",
            )
            if prices:
                rows = [
                    ("polymarket", parsed["market_id"], p["ts"], p["price"],
                     None, None, None, "polymarket_clob_prices_history")
                    for p in prices
                ]
                db.insert_yes_prices(rows)

        if parsed.get("settle_ts") and parsed["settle_ts"] > max_ts:
            max_ts = parsed["settle_ts"]
        count += 1

        if count % 50 == 0:
            logger.info(f"Polymarket: processed {count} markets")

    db.set_watermark("polymarket",
                     last_market_scan_ts=int(datetime.now(timezone.utc).timestamp()),
                     last_settle_scan_ts=max_ts)
    logger.info(f"Polymarket: ingested {count} markets, watermark -> {max_ts}")


def ingest_kalshi(db: HistoricalDB):
    """Run Kalshi incremental ingestion."""
    watermark = db.get_watermark("kalshi")
    wm_ts = watermark.get("last_settle_scan_ts", 0)

    # Get cutoff to know which partition to query
    cutoff = kalshi_ingestor.get_cutoff()
    logger.info(f"Kalshi cutoff: {cutoff}")

    logger.info(f"Kalshi: scanning settled markets since ts={wm_ts}")
    count = 0
    max_ts = wm_ts

    # Scan both live and historical partitions
    for scanner in [kalshi_ingestor.scan_settled_markets, kalshi_ingestor.scan_historical_markets]:
        for raw_market in scanner(wm_ts):
            parsed = kalshi_ingestor.parse_market(raw_market)

            db.upsert_market(**{k: v for k, v in parsed.items()
                               if k not in ("outcome_yes", "settlement_value", "time_to_resolution_s")})

            if parsed["outcome_yes"] is not None and parsed["settle_ts"]:
                # Get final price from last candlestick
                final_price = None
                if parsed["close_ts"]:
                    candles = kalshi_ingestor.fetch_candlesticks(
                        parsed["market_id"],
                        parsed["close_ts"] - 3600,
                        parsed["close_ts"],
                        period_minutes=1,
                    )
                    if candles:
                        last_candle = candles[-1]
                        final_price = last_candle.get("close", last_candle.get("yes_price"))
                        if final_price and final_price > 1:
                            final_price = final_price / 100  # Convert cents to dollars

                db.upsert_resolution(
                    venue="kalshi",
                    market_id=parsed["market_id"],
                    outcome_yes=parsed["outcome_yes"],
                    settlement_value=parsed["settlement_value"],
                    settled_ts=parsed["settle_ts"],
                    time_to_resolution_s=parsed["time_to_resolution_s"],
                    final_yes_price=final_price,
                    final_yes_price_ts=parsed.get("close_ts"),
                )

            if parsed.get("settle_ts") and parsed["settle_ts"] > max_ts:
                max_ts = parsed["settle_ts"]
            count += 1

            if count % 50 == 0:
                logger.info(f"Kalshi: processed {count} markets")

    db.set_watermark("kalshi",
                     last_market_scan_ts=int(datetime.now(timezone.utc).timestamp()),
                     last_settle_scan_ts=max_ts)
    logger.info(f"Kalshi: ingested {count} markets, watermark -> {max_ts}")


def main():
    parser = argparse.ArgumentParser(description="Historical Data Pipeline Runner")
    parser.add_argument("--venue", choices=["polymarket", "kalshi", "alpaca", "all"], default="all")
    parser.add_argument("--quality-check", action="store_true", help="Run quality checks only")
    parser.add_argument("--calibration", action="store_true", help="Build calibration snapshots")
    parser.add_argument("--stats", action="store_true", help="Print venue statistics")
    args = parser.parse_args()

    db = HistoricalDB()

    if args.quality_check:
        issues = db.run_quality_checks()
        for issue in issues:
            print(issue)
        sys.exit(0 if "ALL CHECKS PASSED" in issues else 1)

    if args.calibration:
        db.build_calibration_snapshots()
        stats = db.get_calibration_stats()
        for bin_label, data in stats.items():
            status = "OK" if data["sufficient"] else f"NEED {data['min_required'] - data['n']} more"
            print(f"{bin_label}: n={data['n']}, empirical={data['empirical_rate']:.3f}, "
                  f"predicted={data['avg_predicted']:.3f}, miscal={data['miscalibration']:.3f}, {status}")
        sys.exit(0)

    if args.stats:
        stats = db.get_venue_stats()
        for venue, data in stats.items():
            print(f"{venue}: {data['markets']} markets, {data['resolved']} resolved, "
                  f"{data['price_observations']} prices, {data['trades']} trades")
        sys.exit(0)

    # Run ingestion
    if args.venue in ("polymarket", "all"):
        ingest_polymarket(db)
    if args.venue in ("kalshi", "all"):
        ingest_kalshi(db)

    # Quality checks
    issues = db.run_quality_checks()
    for issue in issues:
        logger.info(f"QA: {issue}")

    # Stats
    stats = db.get_venue_stats()
    logger.info(f"Pipeline complete. Stats: {json.dumps(stats, indent=2)}")


if __name__ == "__main__":
    main()
