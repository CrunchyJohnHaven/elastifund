#!/usr/bin/env python3
"""Unit tests for bot/btc_5min_maker.py."""

import sys
import time
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from bot.btc_5min_maker import (  # noqa: E402
    BTC5MinMakerBot,
    CLOBExecutor,
    LiveOrderState,
    MakerConfig,
    MarketHttpClient,
    PlacementResult,
    SessionGuardrailOverride,
    active_session_guardrail_override,
    calc_trade_size_usd,
    clob_min_order_size,
    choose_maker_buy_price,
    choose_maker_sell_price,
    choose_token_id_for_direction,
    current_window_start,
    deterministic_fill,
    direction_from_prices,
    effective_max_buy_price,
    effective_quote_ticks,
    _is_transient_request_error_text,
    market_slug_for_window,
    parse_json_list,
    parse_session_guardrail_overrides,
    session_guardrail_reason,
    summarize_recent_direction_regime,
)


ET = ZoneInfo("America/New_York")






def _ts(year: int, month: int, day: int, hour: int, minute: int) -> int:
    return int(datetime(year, month, day, hour, minute, tzinfo=ET).timestamp())






































































class _DummyHTTP:
    top_of_book = staticmethod(MarketHttpClient.top_of_book)

    async def fetch_market_by_slug(self, slug: str) -> dict:
        return {
            "slug": slug,
            "tokens": [
                {"outcome": "Up", "token_id": "tok-up"},
                {"outcome": "Down", "token_id": "tok-down"},
            ],
        }

    async def fetch_book(self, token_id: str) -> dict:
        assert token_id == "tok-up"
        return {
            "bids": [{"price": 0.91, "size": 50}],
            "asks": [{"price": 0.93, "size": 50}],
        }


def _seed_recent_regime(bot: BTC5MinMakerBot, *, window_start_ts: int) -> None:
    start = window_start_ts - (12 * 300)
    for idx in range(12):
        direction = "DOWN" if idx < 6 else "UP"
        pnl = 5.0 if direction == "DOWN" else 1.0
        order_price = 0.49 if direction == "DOWN" else 0.51
        ws = start + (idx * 300)
        bot.db.upsert_window(
            {
                "window_start_ts": ws,
                "window_end_ts": ws + 300,
                "slug": market_slug_for_window(ws),
                "decision_ts": ws + 290,
                "direction": direction,
                "open_price": 100.0,
                "current_price": 100.05,
                "delta": 0.0005,
                "token_id": f"tok-{direction.lower()}",
                "best_bid": order_price - 0.01,
                "best_ask": order_price,
                "order_price": order_price,
                "trade_size_usd": 5.0,
                "shares": round(5.0 / order_price, 2),
                "order_id": f"hist-{idx}",
                "order_status": "live_filled",
                "filled": 1,
                "reason": "seed",
                "resolved_side": direction,
                "won": 1,
                "pnl_usd": pnl,
            }
        )


def _seed_strong_recent_regime(bot: BTC5MinMakerBot, *, window_start_ts: int) -> None:
    start = window_start_ts - (12 * 300)
    for idx in range(12):
        direction = "DOWN" if idx < 6 else "UP"
        pnl = 7.0 if direction == "DOWN" else 1.0
        order_price = 0.48 if direction == "DOWN" else 0.51
        ws = start + (idx * 300)
        bot.db.upsert_window(
            {
                "window_start_ts": ws,
                "window_end_ts": ws + 300,
                "slug": market_slug_for_window(ws),
                "decision_ts": ws + 290,
                "direction": direction,
                "open_price": 100.0,
                "current_price": 100.05,
                "delta": 0.0005,
                "token_id": f"tok-{direction.lower()}",
                "best_bid": order_price - 0.01,
                "best_ask": order_price,
                "order_price": order_price,
                "trade_size_usd": 5.0,
                "shares": round(5.0 / order_price, 2),
                "order_id": f"strong-hist-{idx}",
                "order_status": "live_filled",
                "filled": 1,
                "reason": "seed_strong",
                "resolved_side": direction,
                "won": 1,
                "pnl_usd": pnl,
            }
        )


def _seed_negative_recent_regime(bot: BTC5MinMakerBot, *, window_start_ts: int) -> None:
    start = window_start_ts - (12 * 300)
    for idx in range(12):
        direction = "DOWN" if idx < 6 else "UP"
        pnl = -1.0 if direction == "DOWN" else -4.0
        order_price = 0.49 if direction == "DOWN" else 0.51
        ws = start + (idx * 300)
        bot.db.upsert_window(
            {
                "window_start_ts": ws,
                "window_end_ts": ws + 300,
                "slug": market_slug_for_window(ws),
                "decision_ts": ws + 290,
                "direction": direction,
                "open_price": 100.0,
                "current_price": 100.05,
                "delta": 0.0005,
                "token_id": f"tok-{direction.lower()}",
                "best_bid": order_price - 0.01,
                "best_ask": order_price,
                "order_price": order_price,
                "trade_size_usd": 5.0,
                "shares": round(5.0 / order_price, 2),
                "order_id": f"weak-hist-{idx}",
                "order_status": "live_filled",
                "filled": 1,
                "reason": "seed_weak",
                "resolved_side": "UP",
                "won": 0,
                "pnl_usd": pnl,
            }
        )


def _seed_stage_history(
    bot: BTC5MinMakerBot,
    *,
    window_start_ts: int,
    live_filled_rows: int,
    live_filled_pnl_usd: float,
    order_failed_rows: int = 0,
) -> None:
    start = window_start_ts - ((live_filled_rows + order_failed_rows + 2) * 300)
    for idx in range(live_filled_rows):
        ws = start + (idx * 300)
        bot.db.upsert_window(
            {
                "window_start_ts": ws,
                "window_end_ts": ws + 300,
                "slug": market_slug_for_window(ws),
                "decision_ts": ws + 290,
                "direction": "DOWN" if idx % 2 == 0 else "UP",
                "open_price": 100.0,
                "current_price": 100.05,
                "delta": 0.0005,
                "token_id": "tok",
                "best_bid": 0.49,
                "best_ask": 0.50,
                "order_price": 0.49,
                "trade_size_usd": 5.0,
                "shares": 10.2,
                "order_id": f"stage-fill-{idx}",
                "order_status": "live_filled",
                "filled": 1,
                "reason": "seed_stage",
                "resolved_side": "DOWN",
                "won": 1,
                "pnl_usd": live_filled_pnl_usd,
            }
        )
    for idx in range(order_failed_rows):
        ws = start + ((live_filled_rows + idx) * 300)
        bot.db.upsert_window(
            {
                "window_start_ts": ws,
                "window_end_ts": ws + 300,
                "slug": market_slug_for_window(ws),
                "decision_ts": ws + 290,
                "direction": "UP",
                "open_price": 100.0,
                "current_price": 100.05,
                "delta": 0.0005,
                "token_id": "tok",
                "best_bid": 0.49,
                "best_ask": 0.50,
                "order_price": 0.49,
                "trade_size_usd": 0.0,
                "shares": 0.0,
                "order_id": f"stage-fail-{idx}",
                "order_status": "live_order_failed",
                "filled": 0,
                "reason": "seed_stage_fail",
                "resolved_side": "UP",
                "won": 0,
                "pnl_usd": 0.0,
            }
        )

























































