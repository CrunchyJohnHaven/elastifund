#!/usr/bin/env python3
"""Depth-signal unit tests for bot/btc_5min_maker.py."""

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from bot.btc_5min_maker import (  # noqa: E402
    BTC5MinMakerBot,
    BinancePriceCache,
    MakerConfig,
    MarketHttpClient,
    current_window_start,
)


@pytest.mark.asyncio
async def test_binance_price_cache_computes_book_imbalance_from_depth_levels() -> None:
    cache = BinancePriceCache()
    await cache.add_depth_snapshot(
        ts_sec=int(time.time()),
        bids=[["100000", "30"], ["99990", "10"]],
        asks=[["100010", "12"], ["100020", "8"]],
    )

    imbalance = await cache.latest_book_imbalance(max_age_sec=10)
    assert imbalance == pytest.approx((40.0 - 20.0) / 60.0, rel=1e-6)


@pytest.mark.asyncio
async def test_binance_price_cache_rejects_stale_depth_snapshot() -> None:
    cache = BinancePriceCache()
    old_ts = int(time.time()) - 30
    await cache.add_depth_snapshot(
        ts_sec=old_ts,
        bids=[["100000", "20"]],
        asks=[["100010", "10"]],
    )

    assert await cache.latest_book_imbalance(max_age_sec=5) is None
    assert await cache.latest_book_imbalance(max_age_sec=60) == pytest.approx((20.0 - 10.0) / 30.0, rel=1e-6)


def test_apply_depth_confirmation_adjusts_edge_tier(tmp_path: Path) -> None:
    cfg = MakerConfig(
        db_path=tmp_path / "btc5.db",
        depth_confirmation_threshold=0.30,
    )
    bot = BTC5MinMakerBot(cfg)

    upgraded_tier, upgraded_tags = bot._apply_depth_confirmation(
        edge_tier="standard",
        direction="DOWN",
        book_imbalance=-0.55,
        sizing_reason_tags=["edge_tier=standard"],
    )
    assert upgraded_tier == "strong_validated"
    assert "depth_confirmation=agree" in upgraded_tags
    assert "depth_edge_tier_upgrade=standard_to_strong_validated" in upgraded_tags

    downgraded_tier, downgraded_tags = bot._apply_depth_confirmation(
        edge_tier="standard",
        direction="DOWN",
        book_imbalance=0.55,
        sizing_reason_tags=["edge_tier=standard"],
    )
    assert downgraded_tier == "exploratory"
    assert "depth_confirmation=disagree" in downgraded_tags
    assert "depth_edge_tier_downgrade=standard_to_exploratory" in downgraded_tags


@pytest.mark.asyncio
async def test_process_window_persists_book_imbalance(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cfg = MakerConfig(
        paper_trading=True,
        db_path=tmp_path / "btc5.db",
        min_delta=0.0,
        min_trade_usd=0.25,
        max_trade_usd=5.0,
        min_buy_price=0.90,
        max_buy_price=0.95,
        paper_fill_probability=1.0,
        depth_confirmation_threshold=0.30,
    )
    bot = BTC5MinMakerBot(cfg)

    async def fake_resolve(http, through_window_start: int) -> None:
        return None

    async def fake_prices(*, window_start_ts: int, http) -> tuple[float, float]:
        return 100.0, 100.05

    class _UpHTTP:
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

    monkeypatch.setattr(bot, "_resolve_unsettled", fake_resolve)
    monkeypatch.setattr(bot, "_get_open_and_current_price", fake_prices)

    await bot.cache.add_depth_snapshot(
        ts_sec=int(time.time()),
        bids=[["100000", "30"]],
        asks=[["100010", "10"]],
    )

    window_start_ts = current_window_start(time.time()) - (2 * 300)
    result = await bot._process_window(window_start_ts=window_start_ts, http=_UpHTTP())

    assert result["status"] == "paper_filled"
    assert "depth_confirmation=agree" in result["sizing_reason_tags"]

    with bot.db._connect() as conn:
        row = conn.execute(
            "SELECT book_imbalance FROM window_trades WHERE window_start_ts = ?",
            (window_start_ts,),
        ).fetchone()
    assert row is not None
    assert row["book_imbalance"] == pytest.approx((30.0 - 10.0) / 40.0, rel=1e-6)
