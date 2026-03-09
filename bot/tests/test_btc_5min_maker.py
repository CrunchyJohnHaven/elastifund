#!/usr/bin/env python3
"""Unit tests for bot/btc_5min_maker.py."""

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from bot.btc_5min_maker import (  # noqa: E402
    BTC5MinMakerBot,
    CLOBExecutor,
    LiveOrderState,
    MakerConfig,
    MarketHttpClient,
    PlacementResult,
    calc_trade_size_usd,
    clob_min_order_size,
    choose_maker_buy_price,
    choose_token_id_for_direction,
    current_window_start,
    deterministic_fill,
    direction_from_prices,
    effective_max_buy_price,
    market_slug_for_window,
    parse_json_list,
)


def test_current_window_start_alignment() -> None:
    assert current_window_start(1710000123) == 1710000000
    assert current_window_start(1710000300) == 1710000300


def test_market_slug_for_window() -> None:
    assert market_slug_for_window(1710000000) == "btc-updown-5m-1710000000"


def test_direction_from_prices_above_threshold() -> None:
    direction, delta = direction_from_prices(open_price=100.0, current_price=100.05, min_delta=0.0003)
    assert direction == "UP"
    assert delta == pytest.approx(0.0005)


def test_direction_from_prices_below_threshold() -> None:
    direction, delta = direction_from_prices(open_price=100.0, current_price=100.01, min_delta=0.0003)
    assert direction is None
    assert delta == pytest.approx(0.0001)


def test_choose_maker_buy_price_standard_case() -> None:
    price = choose_maker_buy_price(
        best_bid=0.91,
        best_ask=0.93,
        max_price=0.95,
        min_price=0.90,
        tick_size=0.01,
    )
    assert price == pytest.approx(0.92)


def test_choose_maker_buy_price_guardrails() -> None:
    # Ask already above max buy threshold => skip.
    assert (
        choose_maker_buy_price(
            best_bid=0.95,
            best_ask=0.96,
            max_price=0.95,
            min_price=0.90,
            tick_size=0.01,
        )
        is None
    )


def test_effective_max_buy_price_prefers_directional_caps() -> None:
    cfg = MakerConfig(
        up_max_buy_price=0.51,
        down_max_buy_price=0.50,
        max_buy_price=0.95,
    )
    assert effective_max_buy_price(cfg, "UP") == pytest.approx(0.51)
    assert effective_max_buy_price(cfg, "DOWN") == pytest.approx(0.50)
    assert effective_max_buy_price(cfg, "OTHER") == pytest.approx(0.95)


def test_choose_maker_buy_price_rounds_to_tick() -> None:
    price = choose_maker_buy_price(
        best_bid=0.913,
        best_ask=0.931,
        max_price=0.95,
        min_price=0.90,
        tick_size=0.01,
    )
    assert price == pytest.approx(0.92)


def test_calc_trade_size_usd() -> None:
    assert calc_trade_size_usd(250.0, 0.01, 2.50) == pytest.approx(2.50)
    assert calc_trade_size_usd(100.0, 0.01, 2.50) == pytest.approx(1.00)


def test_clob_min_order_size_enforces_five_dollar_notional() -> None:
    assert clob_min_order_size(0.92) == pytest.approx(5.44)
    assert clob_min_order_size(0.30) == pytest.approx(16.67)


def test_parse_json_list() -> None:
    assert parse_json_list('["Up","Down"]') == ["Up", "Down"]
    assert parse_json_list(["Up", "Down"]) == ["Up", "Down"]
    assert parse_json_list("") == []
    assert parse_json_list("{bad}") == []


def test_choose_token_id_for_direction_tokens_field() -> None:
    market = {
        "tokens": [
            {"outcome": "Up", "token_id": "tok-up"},
            {"outcome": "Down", "token_id": "tok-down"},
        ]
    }
    assert choose_token_id_for_direction(market, "UP") == "tok-up"
    assert choose_token_id_for_direction(market, "DOWN") == "tok-down"


def test_choose_token_id_for_direction_fallback_binary_order() -> None:
    market = {
        "outcomes": '["Something odd","Something else"]',
        "clobTokenIds": '["tid0","tid1"]',
    }
    assert choose_token_id_for_direction(market, "UP") == "tid0"
    assert choose_token_id_for_direction(market, "DOWN") == "tid1"


def test_deterministic_fill_stable() -> None:
    a = deterministic_fill(1710000000, 0.2)
    b = deterministic_fill(1710000000, 0.2)
    assert a == b


def test_get_order_state_parses_scaled_sizes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cfg = MakerConfig(db_path=tmp_path / "btc5.db")
    executor = CLOBExecutor(cfg)

    class FakeClient:
        def get_order(self, order_id: str) -> dict:
            assert order_id == "ord-1"
            return {
                "order": {
                    "status": "CANCELED",
                    "original_size": "3000000",
                    "size_matched": "2500000",
                    "price": "0.92",
                }
            }

    monkeypatch.setattr(executor, "ensure_client", lambda: FakeClient())
    state = executor.get_order_state("ord-1")

    assert state is not None
    assert state.is_cancelled is True
    assert state.original_size == pytest.approx(3.0)
    assert state.size_matched == pytest.approx(2.5)
    assert state.partially_filled is True


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


@pytest.mark.asyncio
async def test_process_window_records_partial_live_fill(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cfg = MakerConfig(
        paper_trading=False,
        db_path=tmp_path / "btc5.db",
        bankroll_usd=250.0,
        risk_fraction=0.01,
        max_trade_usd=2.50,
        min_trade_usd=0.25,
        min_delta=0.0003,
        max_buy_price=0.95,
        min_buy_price=0.90,
        tick_size=0.01,
        cancel_seconds_before_close=2,
    )
    bot = BTC5MinMakerBot(cfg)

    async def fake_resolve(http, through_window_start: int) -> None:
        return None

    async def fake_prices(*, window_start_ts: int, http) -> tuple[float, float]:
        return 100.0, 100.05

    class FakeCLOB:
        def __init__(self) -> None:
            self.states = [
                LiveOrderState(
                    order_id="ord-1",
                    status="live",
                    original_size=2.6881,
                    size_matched=1.2,
                    price=0.93,
                ),
                LiveOrderState(
                    order_id="ord-1",
                    status="cancelled",
                    original_size=2.6881,
                    size_matched=1.2,
                    price=0.93,
                ),
            ]

        def place_post_only_buy(self, token_id: str, price: float, shares: float) -> PlacementResult:
            assert token_id == "tok-up"
            assert price == pytest.approx(0.92)
            assert shares == pytest.approx(5.44)  # bumped to exchange-valid live minimum
            return PlacementResult(order_id="ord-1", success=True, status="live")

        def get_order_state(self, order_id: str) -> LiveOrderState:
            assert order_id == "ord-1"
            return self.states.pop(0)

        def cancel_order(self, order_id: str) -> bool:
            assert order_id == "ord-1"
            return True

    monkeypatch.setattr(bot, "_resolve_unsettled", fake_resolve)
    monkeypatch.setattr(bot, "_get_open_and_current_price", fake_prices)
    bot.clob = FakeCLOB()

    window_start_ts = current_window_start(time.time()) - (2 * 300)
    result = await bot._process_window(window_start_ts=window_start_ts, http=_DummyHTTP())

    assert result["status"] == "live_partial_fill_cancelled"
    assert result["filled"] == 1
    assert result["size_usd"] == pytest.approx(1.104, rel=1e-3)

    with bot.db._connect() as conn:
        row = conn.execute("SELECT shares, trade_size_usd, filled, order_status FROM window_trades").fetchone()
    assert row["shares"] == pytest.approx(1.2)
    assert row["trade_size_usd"] == pytest.approx(1.104, rel=1e-3)
    assert row["filled"] == 1
    assert row["order_status"] == "live_partial_fill_cancelled"


@pytest.mark.asyncio
async def test_process_window_records_cancelled_unfilled_live_order(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cfg = MakerConfig(
        paper_trading=False,
        db_path=tmp_path / "btc5.db",
        bankroll_usd=250.0,
        risk_fraction=0.01,
        max_trade_usd=2.50,
        min_trade_usd=0.25,
        min_delta=0.0003,
        max_buy_price=0.95,
        min_buy_price=0.90,
        tick_size=0.01,
        cancel_seconds_before_close=2,
    )
    bot = BTC5MinMakerBot(cfg)

    async def fake_resolve(http, through_window_start: int) -> None:
        return None

    async def fake_prices(*, window_start_ts: int, http) -> tuple[float, float]:
        return 100.0, 100.05

    class FakeCLOB:
        def __init__(self) -> None:
            self.states = [
                LiveOrderState(
                    order_id="ord-2",
                    status="live",
                    original_size=2.6881,
                    size_matched=0.0,
                    price=0.93,
                ),
                LiveOrderState(
                    order_id="ord-2",
                    status="cancelled",
                    original_size=2.6881,
                    size_matched=0.0,
                    price=0.93,
                ),
            ]

        def place_post_only_buy(self, token_id: str, price: float, shares: float) -> PlacementResult:
            return PlacementResult(order_id="ord-2", success=True, status="live")

        def get_order_state(self, order_id: str) -> LiveOrderState:
            return self.states.pop(0)

        def cancel_order(self, order_id: str) -> bool:
            return True

    monkeypatch.setattr(bot, "_resolve_unsettled", fake_resolve)
    monkeypatch.setattr(bot, "_get_open_and_current_price", fake_prices)
    bot.clob = FakeCLOB()

    window_start_ts = current_window_start(time.time()) - (2 * 300)
    result = await bot._process_window(window_start_ts=window_start_ts, http=_DummyHTTP())

    assert result["status"] == "live_cancelled_unfilled"
    assert result["filled"] == 0
    assert result["size_usd"] == 0.0


@pytest.mark.asyncio
async def test_process_window_skips_delta_too_large(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cfg = MakerConfig(
        paper_trading=False,
        db_path=tmp_path / "btc5.db",
        bankroll_usd=250.0,
        risk_fraction=0.01,
        max_trade_usd=2.50,
        min_trade_usd=0.25,
        min_delta=0.0,
        max_abs_delta=0.0001,
        max_buy_price=0.95,
        min_buy_price=0.01,
        tick_size=0.01,
        cancel_seconds_before_close=2,
    )
    bot = BTC5MinMakerBot(cfg)

    async def fake_resolve(http, through_window_start: int) -> None:
        return None

    async def fake_prices(*, window_start_ts: int, http) -> tuple[float, float]:
        return 100.0, 100.03

    monkeypatch.setattr(bot, "_resolve_unsettled", fake_resolve)
    monkeypatch.setattr(bot, "_get_open_and_current_price", fake_prices)

    window_start_ts = current_window_start(time.time()) - (2 * 300)
    result = await bot._process_window(window_start_ts=window_start_ts, http=_DummyHTTP())

    assert result["status"] == "skip_delta_too_large"


@pytest.mark.asyncio
async def test_process_window_respects_directional_price_cap(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cfg = MakerConfig(
        paper_trading=False,
        db_path=tmp_path / "btc5.db",
        bankroll_usd=250.0,
        risk_fraction=0.01,
        max_trade_usd=2.50,
        min_trade_usd=0.25,
        min_delta=0.0,
        max_buy_price=0.95,
        down_max_buy_price=0.50,
        min_buy_price=0.01,
        tick_size=0.01,
        cancel_seconds_before_close=2,
    )
    bot = BTC5MinMakerBot(cfg)

    async def fake_resolve(http, through_window_start: int) -> None:
        return None

    async def fake_prices(*, window_start_ts: int, http) -> tuple[float, float]:
        return 100.0, 99.99

    class _DownBookHTTP(_DummyHTTP):
        async def fetch_book(self, token_id: str) -> dict:
            assert token_id == "tok-down"
            return {
                "bids": [{"price": 0.50, "size": 50}],
                "asks": [{"price": 0.53, "size": 50}],
            }

    monkeypatch.setattr(bot, "_resolve_unsettled", fake_resolve)
    monkeypatch.setattr(bot, "_get_open_and_current_price", fake_prices)

    window_start_ts = current_window_start(time.time()) - (2 * 300)
    result = await bot._process_window(window_start_ts=window_start_ts, http=_DownBookHTTP())

    assert result["status"] == "skip_price_outside_guardrails"
