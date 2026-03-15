#!/usr/bin/env python3
"""Run the Kalshi LLM-edge opportunity scanner (Instance 5)."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.kalshi_opportunity_scanner import ScanConfig, run_and_write_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-event-pages",
        type=int,
        default=int(os.environ.get("KALSHI_SCAN_MAX_EVENT_PAGES", "8")),
        help="How many Kalshi /events pages to scan (default: 8).",
    )
    parser.add_argument(
        "--events-page-limit",
        type=int,
        default=int(os.environ.get("KALSHI_SCAN_EVENTS_PAGE_LIMIT", "200")),
        help="Page size for /events calls (default: 200).",
    )
    parser.add_argument(
        "--market-limit-per-event",
        type=int,
        default=int(os.environ.get("KALSHI_SCAN_MARKET_LIMIT_PER_EVENT", "200")),
        help="Max markets to request for each event (default: 200).",
    )
    parser.add_argument(
        "--max-hours",
        type=float,
        default=float(os.environ.get("KALSHI_SCAN_MAX_HOURS", "72")),
        help="Max hours to resolution for eligible opportunities (default: 72).",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=int(os.environ.get("KALSHI_SCAN_TOP_N", "20")),
        help="Max number of opportunities in output (default: 20).",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=float(os.environ.get("KALSHI_SCAN_SLEEP_SECONDS", "0.06")),
        help="Delay between API calls to stay below read rate limits (default: 0.06).",
    )
    parser.add_argument(
        "--output",
        default="data/kalshi_opportunities.json",
        help="Output JSON path (default: data/kalshi_opportunities.json).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Python log level (default: INFO).",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    config = ScanConfig(
        max_event_pages=max(1, int(args.max_event_pages)),
        events_page_limit=max(1, int(args.events_page_limit)),
        market_limit_per_event=max(1, int(args.market_limit_per_event)),
        max_hours_to_resolution=max(1.0, float(args.max_hours)),
        top_n=max(1, int(args.top_n)),
        per_request_sleep_seconds=max(0.0, float(args.sleep_seconds)),
    )
    payload, output_path = run_and_write_report(
        config=config,
        output_path=Path(args.output),
    )
    print(output_path)
    print(
        "scanned_markets="
        f"{payload['total_markets']} passing={payload['passing_filters']} top={payload['passing_filters_top_n']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

