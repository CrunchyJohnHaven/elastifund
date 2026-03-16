import json
from pathlib import Path

import pytest

import bot.btc_5min_maker as maker_mod
from bot.btc_5min_maker import BTC5MinMakerBot, MakerConfig


class _BookHTTP:
    async def fetch_market_by_slug(self, slug: str) -> dict:
        return {
            "slug": slug,
            "tokens": [
                {"outcome": "UP", "token_id": "tok-up"},
                {"outcome": "DOWN", "token_id": "tok-down"},
            ],
        }

    async def fetch_book(self, token_id: str) -> dict:
        assert token_id in {"tok-up", "tok-down"}
        return {"bids": [{"price": 0.47, "size": 100}], "asks": [{"price": 0.48, "size": 100}]}

    def top_of_book(self, book: dict) -> tuple[float | None, float | None]:
        bid = book.get("bids", [{}])[0].get("price")
        ask = book.get("asks", [{}])[0].get("price")
        return bid, ask


@pytest.mark.asyncio
async def test_process_window_uses_early_decision_when_two_sided_book(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    window_start_ts = 1_700_000_000
    now_ts = window_start_ts + 180  # inside [T-180, T-50) window

    cfg = MakerConfig(
        paper_trading=True,
        db_path=tmp_path / "btc5.db",
        bankroll_usd=250.0,
        risk_fraction=0.01,
        max_trade_usd=2.5,
        min_trade_usd=0.25,
        min_delta=0.0002,
        entry_seconds_before_close=50,
        early_decision_sec=180,
        max_buy_price=0.95,
        min_buy_price=0.45,
        tick_size=0.01,
        paper_fill_probability=1.0,
    )
    bot = BTC5MinMakerBot(cfg)

    async def fake_resolve(http, through_window_start: int) -> None:
        return None

    async def fake_prices(*, window_start_ts: int, http) -> tuple[float, float]:
        return 100.0, 99.95  # abs(delta)=0.0005 > early 2x threshold (0.0004)

    monkeypatch.setattr(bot, "_resolve_unsettled", fake_resolve)
    monkeypatch.setattr(bot, "_get_open_and_current_price", fake_prices)
    monkeypatch.setattr(maker_mod.time, "time", lambda: float(now_ts))

    result = await bot._process_window(window_start_ts=window_start_ts, http=_BookHTTP())

    assert result["status"] == "paper_filled"
    assert result["decision_timing"] == "early"
    assert result["early_fallback_reason"] is None

    with bot.db._connect() as conn:
        row = conn.execute(
            "SELECT decision_ts, reason, sizing_reason_tags FROM window_trades WHERE window_start_ts = ?",
            (window_start_ts,),
        ).fetchone()
    assert row is not None
    assert int(row["decision_ts"]) == now_ts
    assert "decision_timing=early" in str(row["reason"] or "")
    assert "decision_timing=early" in json.loads(row["sizing_reason_tags"])


@pytest.mark.asyncio
async def test_process_window_falls_back_to_late_decision_when_early_signal_too_small(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    window_start_ts = 1_700_000_000
    now_ts = window_start_ts + 180  # inside [T-180, T-50) window

    cfg = MakerConfig(
        paper_trading=True,
        db_path=tmp_path / "btc5.db",
        bankroll_usd=250.0,
        risk_fraction=0.01,
        max_trade_usd=2.5,
        min_trade_usd=0.25,
        min_delta=0.0002,
        entry_seconds_before_close=50,
        early_decision_sec=180,
        max_buy_price=0.95,
        min_buy_price=0.45,
        tick_size=0.01,
        paper_fill_probability=1.0,
    )
    bot = BTC5MinMakerBot(cfg)

    async def fake_resolve(http, through_window_start: int) -> None:
        return None

    price_calls: list[tuple[float, float]] = [(100.0, 100.01), (100.0, 99.90)]

    async def fake_prices(*, window_start_ts: int, http) -> tuple[float, float]:
        return price_calls.pop(0)

    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr(bot, "_resolve_unsettled", fake_resolve)
    monkeypatch.setattr(bot, "_get_open_and_current_price", fake_prices)
    monkeypatch.setattr(maker_mod.time, "time", lambda: float(now_ts))
    monkeypatch.setattr(maker_mod.asyncio, "sleep", fake_sleep)

    result = await bot._process_window(window_start_ts=window_start_ts, http=_BookHTTP())

    assert result["status"] == "paper_filled"
    assert result["decision_timing"] == "late"
    assert result["early_fallback_reason"] == "delta_too_small"
    assert len(sleep_calls) == 1
    assert sleep_calls[0] == pytest.approx(70.0)

    with bot.db._connect() as conn:
        row = conn.execute(
            "SELECT reason, sizing_reason_tags FROM window_trades WHERE window_start_ts = ?",
            (window_start_ts,),
        ).fetchone()
    assert row is not None
    assert "decision_timing=late" in str(row["reason"] or "")
    assert "early_fallback_reason=delta_too_small" in str(row["reason"] or "")
    assert "decision_timing=late" in json.loads(row["sizing_reason_tags"])
