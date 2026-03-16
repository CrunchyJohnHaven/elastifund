#!/usr/bin/env python3
"""Depth-signal unit tests for bot/btc_5min_maker.py."""

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from bot.btc_5min_maker import BTC5MinMakerBot, BinancePriceCache, MakerConfig  # noqa: E402


@pytest.mark.asyncio
async def test_binance_price_cache_computes_book_imbalance_from_depth_levels() -> None:
    cache = BinancePriceCache()
    await cache.add_depth_snapshot(
        ts_sec=1_710_000_000,
        bids=[["100000", "30"], ["99990", "10"]],
        asks=[["100010", "12"], ["100020", "8"]],
    )

    imbalance = await cache.latest_book_imbalance(max_age_sec=10_000_000)
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
