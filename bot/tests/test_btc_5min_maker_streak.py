from . import _btc_5min_maker_shared as _shared

globals().update({k: v for k, v in vars(_shared).items() if not k.startswith("__")})
pytestmark = pytest.mark.asyncio


async def test_process_window_uses_shadow_only_for_first_streak_events(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cfg = MakerConfig(
        paper_trading=False,
        db_path=tmp_path / "btc5.db",
        streak_log_path=tmp_path / "streak_log.json",
        bankroll_usd=500.0,
        risk_fraction=0.02,
        max_trade_usd=10.0,
        min_trade_usd=0.25,
        min_delta=0.0,
        max_abs_delta=0.01,
        max_buy_price=0.95,
        up_max_buy_price=0.95,
        down_max_buy_price=0.95,
        min_buy_price=0.45,
        tick_size=0.01,
        up_live_mode="live_enabled",
    )
    bot = BTC5MinMakerBot(cfg)

    seed_start = _ts(2026, 3, 9, 9, 15)
    for idx in range(3):
        ws = seed_start + (idx * 300)
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
                "order_status": "live_cancelled_unfilled",
                "filled": 0,
                "resolved_side": "UP",
            }
        )

    async def fake_resolve(http, through_window_start: int) -> None:
        return None

    async def fake_prices(*, window_start_ts: int, http) -> tuple[float, float]:
        return 100.0, 100.05

    class _FailIfLiveCLOB:
        def place_post_only_buy(self, token_id: str, price: float, shares: float) -> PlacementResult:
            raise AssertionError("streak warmup should be shadow-only")

        def get_order_state(self, order_id: str) -> LiveOrderState:
            raise AssertionError("streak warmup should be shadow-only")

        def cancel_order(self, order_id: str) -> bool:
            raise AssertionError("streak warmup should be shadow-only")

    monkeypatch.setattr(bot, "_resolve_unsettled", fake_resolve)
    monkeypatch.setattr(bot, "_get_open_and_current_price", fake_prices)
    bot.clob = _FailIfLiveCLOB()

    window_start_ts = _ts(2026, 3, 9, 9, 35)
    result = await bot._process_window(window_start_ts=window_start_ts, http=_DummyHTTP())

    assert result["status"] == "shadow_streak_only"
    assert result["streak_signal"] is True
    assert result["streak_event_index"] == 1
    assert result["streak_shadow_only"] is True
    assert "streak_N=3" in result["sizing_reason_tags"]
    assert "streak_shadow_only_warmup" in result["sizing_reason_tags"]

    with bot.db._connect() as conn:
        row = conn.execute(
            """
            SELECT order_status, sizing_reason_tags
            FROM window_trades
            WHERE window_start_ts = ?
            """,
            (window_start_ts,),
        ).fetchone()
    assert row["order_status"] == "shadow_streak_only"
    assert "streak_N=3" in json.loads(row["sizing_reason_tags"])

    streak_log = json.loads((tmp_path / "streak_log.json").read_text())
    assert streak_log["events"][-1]["streak_signal"] is True
    assert streak_log["events"][-1]["streak_event_index"] == 1
