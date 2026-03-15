from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from bot.smart_wallet_feed import SmartWalletFeed, WalletConsensus, load_smart_wallet_addresses


def test_load_smart_wallet_addresses_supports_mixed_rows(tmp_path: Path) -> None:
    config_path = tmp_path / "smart_wallets.json"
    config_path.write_text(
        json.dumps(
            {
                "wallets": [
                    {"label": "alpha", "address": "0xAAA"},
                    "0xbbb",
                    {"wallet": "0xAAA"},
                    {"address": "0xccc"},
                ]
            }
        )
    )
    wallets = load_smart_wallet_addresses(config_path)
    assert wallets == ["0xaaa", "0xbbb", "0xccc"]


def test_wallet_consensus_strong_thresholds() -> None:
    strong = WalletConsensus(
        condition_id="cond-1",
        window_start_ts=1_700_000_000,
        direction="DOWN",
        smart_wallet_count=3,
        combined_notional_usd=250.0,
        avg_price=0.91,
        trade_count=4,
    )
    assert strong.strong()
    assert not strong.strong(min_wallets=4)
    assert not strong.strong(min_notional_usd=300.0)
    assert not strong.strong(min_avg_price=0.95)


@pytest.mark.asyncio
async def test_start_background_watch_caches_consensus(monkeypatch: pytest.MonkeyPatch) -> None:
    now = int(time.time())
    window_start_ts = now - 11
    trades = [
        {
            "proxyWallet": "0x1",
            "side": "BUY",
            "outcome": "Down",
            "size": "120",
            "price": "0.91",
            "timestamp": now - 5,
        },
        {
            "proxyWallet": "0x2",
            "side": "SELL",
            "outcome": "Up",
            "size": "150",
            "price": "0.92",
            "timestamp": now - 4,
        },
        {
            "proxyWallet": "0x3",
            "side": "BUY",
            "outcome": "Down",
            "size": "140",
            "price": "0.90",
            "timestamp": now - 3,
        },
        {
            "proxyWallet": "0xnot-tracked",
            "side": "BUY",
            "outcome": "Down",
            "size": "500",
            "price": "0.99",
            "timestamp": now - 3,
        },
    ]
    feed = SmartWalletFeed(
        ["0x1", "0x2", "0x3"],
        poll_interval_sec=1.0,
        observation_window_sec=10,
    )
    fetch_mock = AsyncMock(return_value=trades)
    monkeypatch.setattr(feed, "_fetch_trades_for_condition", fetch_mock)

    feed.start_background_watch("cond-1", window_start_ts)
    await feed.wait_for_window(window_start_ts)
    consensus = await feed.get_cached_consensus(window_start_ts)

    assert consensus is not None
    assert consensus.direction == "DOWN"
    assert consensus.smart_wallet_count == 3
    assert consensus.combined_notional_usd == pytest.approx(373.2)
    assert consensus.avg_price == pytest.approx(0.9103, abs=1e-4)
    assert consensus.strong()
    fetch_mock.assert_awaited_once_with("cond-1")
    await feed.close()


@pytest.mark.asyncio
async def test_get_cached_consensus_returns_none_without_watch() -> None:
    feed = SmartWalletFeed(["0x1"])
    assert await feed.get_cached_consensus(1_700_000_000) is None
    await feed.close()
