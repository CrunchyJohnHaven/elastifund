#!/usr/bin/env python3
"""
Run the RTDS Latency Surface Measurement Harness.

DISPATCH_110 — measures the lag between Polymarket RTDS crypto prices and
market channel prices to determine whether a latency edge exists for the
crypto maker lane.

Usage
-----
    python3 scripts/run_rtds_harness.py \\
        --tokens TOKEN_ID_1,TOKEN_ID_2 \\
        --symbol BTC \\
        --duration 168

Arguments
---------
--tokens    Comma-separated Polymarket condition token IDs to monitor.
            Example: "0xabc123...,0xdef456..."
            Required for a live run; defaults to a placeholder for dry-runs.
--symbol    Crypto symbol to subscribe to on RTDS.  Default: BTC.
--duration  Run duration in hours.  Default: 168 (7 days).
--db        SQLite output path.  Default: bot/data/rtds_latency.db.
--model     Fair value model: "passthrough" (default).
--analyse   After collection, print the kill-condition verdict and exit.
            Pass --analyse alone (no --tokens) to analyse an existing DB.
--log-level Logging level.  Default: INFO.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Path bootstrap so this script works whether invoked from repo root or
# from inside scripts/.
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from bot.rtds_latency_harness import (
    RTDSLatencyHarness,
    analyse_latency_surface,
    KILL_EVALUATION_HOURS,
)


def _parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RTDS Latency Surface Measurement Harness (DISPATCH_110)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--tokens",
        default="",
        help="Comma-separated Polymarket condition token IDs.",
    )
    parser.add_argument(
        "--symbol",
        default="BTC",
        help="Crypto symbol for RTDS subscription (default: BTC).",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=168.0,
        help="Run duration in hours (default: 168 = 7 days).",
    )
    parser.add_argument(
        "--db",
        default=str(_REPO_ROOT / "bot" / "data" / "rtds_latency.db"),
        help="SQLite output path.",
    )
    parser.add_argument(
        "--model",
        default="passthrough",
        choices=["passthrough"],
        help="Fair value model (default: passthrough).",
    )
    parser.add_argument(
        "--analyse",
        action="store_true",
        help="Analyse the existing DB and print a verdict (no live collection).",
    )
    parser.add_argument(
        "--min-samples",
        type=int,
        default=1000,
        help="Minimum price-error samples required for a valid verdict (default: 1000).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO).",
    )
    return parser.parse_args(argv)


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )


def _run_analysis(db: str, min_samples: int) -> None:
    """Print the kill-condition verdict for an existing DB and exit."""
    logging.info("Analysing latency surface DB: %s", db)
    result = analyse_latency_surface(db, min_samples=min_samples)
    print("\n=== RTDS Latency Surface Verdict ===")
    print(result["summary"])
    print()
    print(json.dumps(result, indent=2))

    # Write verdict file alongside the DB
    db_path = Path(db)
    verdict_dir = _REPO_ROOT / "reports" / "latency_surface"
    verdict_dir.mkdir(parents=True, exist_ok=True)
    verdict_path = verdict_dir / "verdict.json"
    verdict_path.write_text(json.dumps(result, indent=2))
    logging.info("Verdict written to %s", verdict_path)


def main(argv=None) -> int:
    args = _parse_args(argv)
    _setup_logging(args.log_level)

    if args.analyse:
        _run_analysis(args.db, args.min_samples)
        return 0

    # Parse token IDs
    token_ids = [t.strip() for t in args.tokens.split(",") if t.strip()]
    if not token_ids:
        logging.error(
            "No --tokens provided.  Pass at least one Polymarket condition token ID.\n"
            "Example: python3 scripts/run_rtds_harness.py --tokens 0xabc123..."
        )
        return 1

    logging.info(
        "Starting RTDS Latency Harness: symbol=%s tokens=%d duration=%.1fh db=%s",
        args.symbol, len(token_ids), args.duration, args.db,
    )

    harness = RTDSLatencyHarness(
        token_ids=token_ids,
        symbol=args.symbol,
        db_path=args.db,
        fair_value_model=args.model,
    )

    try:
        asyncio.run(harness.run(duration_hours=args.duration))
    except KeyboardInterrupt:
        logging.info("Interrupted by user.")
    finally:
        harness.db.flush()
        harness.db.close()

    # After collection, automatically print the verdict if enough time has elapsed
    logging.info("Collection finished.  Running kill-condition analysis...")
    _run_analysis(args.db, args.min_samples)
    return 0


if __name__ == "__main__":
    sys.exit(main())
