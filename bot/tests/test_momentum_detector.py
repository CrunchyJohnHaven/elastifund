import json
import time
from pathlib import Path

import pytest

from bot.btc_5min_maker import BTC5MinMakerBot, MakerConfig, TradeDB, current_window_start, market_slug_for_window
from bot.momentum_detector import MomentumDetector


def _seed_resolved_window(db: TradeDB, *, window_start_ts: int, resolved_side: str) -> None:
    db.upsert_window(
        {
            "window_start_ts": window_start_ts,
            "window_end_ts": window_start_ts + 300,
            "slug": market_slug_for_window(window_start_ts),
            "order_status": "skip_delta_too_small",
            "resolved_side": resolved_side,
        }
    )


def test_momentum_detector_identifies_streak_and_persists_state(tmp_path: Path) -> None:
    db_path = tmp_path / "btc5.db"
    db = TradeDB(db_path)
    base = 1_710_000_000
    for idx, side in enumerate(("UP", "DOWN", "DOWN", "DOWN")):
        _seed_resolved_window(db, window_start_ts=base + (idx * 300), resolved_side=side)

    state_path = tmp_path / "momentum_state.json"
    detector = MomentumDetector(
        db_path=db_path,
        state_path=state_path,
        asset_symbol="BTCUSDT",
        lookback_windows=16,
        streak_min_windows=3,
        reversal_boost_windows=2,
        favored_min_delta_multiplier=0.6,
        opposed_min_delta_multiplier=1.4,
    )
    snapshot = detector.update(as_of_window_start_ts=base + (5 * 300))

    assert snapshot.mode == "momentum"
    assert snapshot.favored_direction == "DOWN"
    assert snapshot.streak_direction == "DOWN"
    assert snapshot.streak_length == 3
    assert snapshot.min_delta_multiplier_for_direction("DOWN") == pytest.approx(0.6)
    assert snapshot.min_delta_multiplier_for_direction("UP") == pytest.approx(1.4)
    assert state_path.exists()
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload["mode"] == "momentum"
    assert payload["favored_direction"] == "DOWN"


def test_momentum_detector_identifies_reversal_after_long_streak(tmp_path: Path) -> None:
    db_path = tmp_path / "btc5.db"
    db = TradeDB(db_path)
    base = 1_710_100_000
    # Long DOWN streak breaks to UP on the latest resolved window.
    for idx, side in enumerate(("DOWN", "DOWN", "DOWN", "UP")):
        _seed_resolved_window(db, window_start_ts=base + (idx * 300), resolved_side=side)

    detector = MomentumDetector(
        db_path=db_path,
        state_path=tmp_path / "momentum_state.json",
        lookback_windows=16,
        streak_min_windows=3,
        reversal_boost_windows=2,
        favored_min_delta_multiplier=0.7,
        opposed_min_delta_multiplier=1.3,
    )
    snapshot = detector.snapshot(as_of_window_start_ts=base + (5 * 300))

    assert snapshot.mode == "reversal"
    assert snapshot.favored_direction == "UP"
    assert snapshot.break_from_direction == "DOWN"
    assert snapshot.break_to_direction == "UP"
    assert snapshot.break_streak_length == 3
    assert snapshot.windows_since_break == 0
    assert snapshot.min_delta_multiplier_for_direction("UP") == pytest.approx(0.7)
    assert snapshot.min_delta_multiplier_for_direction("DOWN") == pytest.approx(1.3)


class _DownMomentumHTTP:
    async def fetch_market_by_slug(self, slug: str) -> dict:
        return {
            "slug": slug,
            "tokens": [
                {"outcome": "Up", "token_id": "tok-up"},
                {"outcome": "Down", "token_id": "tok-down"},
            ],
        }

    async def fetch_book(self, token_id: str) -> dict:
        assert token_id == "tok-down"
        return {
            "bids": [{"price": 0.91, "size": 50}],
            "asks": [{"price": 0.93, "size": 50}],
        }

    @staticmethod
    def top_of_book(book: dict) -> tuple[float | None, float | None]:
        bids = book.get("bids") or []
        asks = book.get("asks") or []
        best_bid = float(bids[0]["price"]) if bids else None
        best_ask = float(asks[0]["price"]) if asks else None
        return best_bid, best_ask


@pytest.mark.asyncio
async def test_process_window_applies_momentum_delta_multiplier(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cfg = MakerConfig(
        paper_trading=True,
        db_path=tmp_path / "btc5.db",
        bankroll_usd=250.0,
        risk_fraction=0.02,
        max_trade_usd=5.0,
        min_trade_usd=0.25,
        min_delta=0.0010,
        max_buy_price=0.95,
        min_buy_price=0.90,
        tick_size=0.01,
        paper_fill_probability=1.0,
        enable_momentum_persistence=True,
        momentum_state_path=tmp_path / "momentum_state.json",
        momentum_lookback_windows=16,
        momentum_streak_min_windows=3,
        momentum_reversal_boost_windows=2,
        momentum_favored_min_delta_multiplier=0.5,
        momentum_opposed_min_delta_multiplier=1.5,
    )
    bot = BTC5MinMakerBot(cfg)

    async def fake_resolve(http, through_window_start: int) -> None:
        return None

    async def fake_prices(*, window_start_ts: int, http) -> tuple[float, float]:
        # Raw delta = -0.0006, below base threshold 0.0010.
        return 100.0, 99.94

    monkeypatch.setattr(bot, "_resolve_unsettled", fake_resolve)
    monkeypatch.setattr(bot, "_get_open_and_current_price", fake_prices)

    ws = current_window_start(time.time()) - (2 * 300)
    for back in (3, 2, 1):
        prior = ws - (back * 300)
        _seed_resolved_window(bot.db, window_start_ts=prior, resolved_side="DOWN")

    result = await bot._process_window(window_start_ts=ws, http=_DownMomentumHTTP())

    assert result["status"] == "paper_filled"
    assert result["direction"] == "DOWN"
    assert result["momentum_mode"] == "momentum"
    assert result["momentum_favored_direction"] == "DOWN"
    assert result["momentum_streak_length"] == 3
    assert result["momentum_min_delta_multiplier"] == pytest.approx(0.5)
    assert (tmp_path / "momentum_state.json").exists()
