#!/usr/bin/env python3
"""Safety-net resolver for unsettled BTC5 windows.

This script keeps the legacy cron workflow intact while the bot-level
resolution poller handles fast post-fill updates.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

import aiohttp

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bot.btc_5min_maker import (  # noqa: E402
    BTC5MinMakerBot,
    MakerConfig,
    MarketHttpClient,
    WINDOW_SECONDS,
    current_window_start,
)


LOG = logging.getLogger("btc5_backfill_resolutions")


async def _run_once(*, db_path: Path | None, include_current_window: bool) -> dict[str, Any]:
    cfg = MakerConfig()
    if db_path is not None:
        cfg.db_path = Path(db_path)
    bot = BTC5MinMakerBot(cfg)
    through_window_start = current_window_start() - WINDOW_SECONDS
    if include_current_window:
        through_window_start = current_window_start()
    before = len(bot.db.unsettled_rows(max_window_start_ts=through_window_start))

    timeout = aiohttp.ClientTimeout(total=cfg.request_timeout_sec)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        http = MarketHttpClient(cfg, session)
        await bot._resolve_unsettled(http, through_window_start=through_window_start)

    after = len(bot.db.unsettled_rows(max_window_start_ts=through_window_start))
    return {
        "checked_at": int(time.time()),
        "db_path": str(cfg.db_path),
        "through_window_start": int(through_window_start),
        "unsettled_before": int(before),
        "unsettled_after": int(after),
        "resolved_now": int(max(0, before - after)),
    }


async def _run(args: argparse.Namespace) -> None:
    if not args.continuous:
        summary = await _run_once(db_path=args.db, include_current_window=args.include_current_window)
        if args.json:
            print(json.dumps(summary, sort_keys=True))
        else:
            LOG.info("resolution_backfill summary=%s", json.dumps(summary, sort_keys=True))
        return

    interval = max(5.0, float(args.interval_sec))
    while True:
        summary = await _run_once(db_path=args.db, include_current_window=args.include_current_window)
        if args.json:
            print(json.dumps(summary, sort_keys=True))
        else:
            LOG.info("resolution_backfill summary=%s", json.dumps(summary, sort_keys=True))
        await asyncio.sleep(interval)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Resolve unsettled BTC5 windows from Binance candles")
    parser.add_argument("--db", type=Path, default=None, help="Override BTC5 DB path")
    parser.add_argument(
        "--include-current-window",
        action="store_true",
        help="Also attempt current window start (normally excluded)",
    )
    parser.add_argument("--continuous", action="store_true", help="Run in a loop")
    parser.add_argument("--interval-sec", type=float, default=300.0, help="Loop interval when --continuous is set")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON summary")
    return parser


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    args = build_parser().parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
