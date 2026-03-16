from . import _btc_5min_maker_shared as _shared

globals().update({k: v for k, v in vars(_shared).items() if not k.startswith("__")})
pytestmark = pytest.mark.asyncio


async def test_process_window_keeps_up_live_direction_shadow_only_during_recovery(
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
        up_max_buy_price=0.95,
        down_max_buy_price=0.95,
        min_buy_price=0.45,
        tick_size=0.01,
        up_live_mode="shadow_only",
    )
    bot = BTC5MinMakerBot(cfg)

    async def fake_resolve(http, through_window_start: int) -> None:
        return None

    async def fake_prices(*, window_start_ts: int, http) -> tuple[float, float]:
        return 100.0, 100.01

    monkeypatch.setattr(bot, "_resolve_unsettled", fake_resolve)
    monkeypatch.setattr(bot, "_get_open_and_current_price", fake_prices)

    window_start_ts = _ts(2026, 3, 9, 9, 35)
    result = await bot._process_window(window_start_ts=window_start_ts, http=_DummyHTTP())

    assert result["status"] == "skip_shadow_only_direction"
    assert result["direction"] == "UP"
    assert result["edge_tier"] == "suppressed"
    assert result["sizing_target_usd"] == pytest.approx(0.0)
    assert "suppression_reason=recovery_sprint_up_shadow_only" in result["decision_reason_tags"]
    assert "recovery_sprint_up_shadow_only" in result["sizing_reason_tags"]

    with bot.db._connect() as conn:
        row = conn.execute(
            """
            SELECT order_status, edge_tier, decision_reason_tags, sizing_reason_tags
            FROM window_trades
            WHERE window_start_ts = ?
            """,
            (window_start_ts,),
        ).fetchone()
    assert row["order_status"] == "skip_shadow_only_direction"
    assert row["edge_tier"] == "suppressed"
    assert "suppression_reason=recovery_sprint_up_shadow_only" in json.loads(
        row["decision_reason_tags"]
    )
    assert "recovery_sprint_up_shadow_only" in json.loads(row["sizing_reason_tags"])


async def test_process_window_skips_lt049_bucket_baseline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cfg = MakerConfig(
        paper_trading=True,
        db_path=tmp_path / "btc5.db",
        bankroll_usd=250.0,
        risk_fraction=0.01,
        max_trade_usd=2.50,
        min_trade_usd=0.25,
        min_delta=0.0,
        max_buy_price=0.95,
        up_max_buy_price=0.95,
        down_max_buy_price=0.95,
        min_buy_price=0.40,
        tick_size=0.01,
        enforce_lt049_skip_baseline=True,
    )
    bot = BTC5MinMakerBot(cfg)

    async def fake_resolve(http, through_window_start: int) -> None:
        return None

    async def fake_prices(*, window_start_ts: int, http) -> tuple[float, float]:
        return 100.0, 99.95

    class _DownBookHTTP(_DummyHTTP):
        async def fetch_book(self, token_id: str) -> dict:
            assert token_id == "tok-down"
            return {
                "bids": [{"price": 0.46, "size": 50}],
                "asks": [{"price": 0.49, "size": 50}],
            }

    monkeypatch.setattr(bot, "_resolve_unsettled", fake_resolve)
    monkeypatch.setattr(bot, "_get_open_and_current_price", fake_prices)

    window_start_ts = _ts(2026, 3, 9, 9, 35)
    result = await bot._process_window(window_start_ts=window_start_ts, http=_DownBookHTTP())

    assert result["status"] == "skip_price_bucket_floor"
    assert result["direction"] == "DOWN"
    assert result["price"] == pytest.approx(0.47)
    assert "suppression_reason=recovery_sprint_lt_0.49_block" in result["decision_reason_tags"]

    with bot.db._connect() as conn:
        row = conn.execute(
            """
            SELECT order_status, order_price, decision_reason_tags
            FROM window_trades
            WHERE window_start_ts = ?
            """,
            (window_start_ts,),
        ).fetchone()
    assert row["order_status"] == "skip_price_bucket_floor"
    assert row["order_price"] == pytest.approx(0.47)
    assert "suppression_reason=recovery_sprint_lt_0.49_block" in json.loads(
        row["decision_reason_tags"]
    )


async def test_process_window_runs_down_mid_bucket_suppress_experiment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cfg = MakerConfig(
        paper_trading=True,
        db_path=tmp_path / "btc5.db",
        bankroll_usd=250.0,
        risk_fraction=0.01,
        max_trade_usd=2.50,
        min_trade_usd=0.25,
        min_delta=0.0,
        max_buy_price=0.95,
        up_max_buy_price=0.95,
        down_max_buy_price=0.95,
        min_buy_price=0.45,
        tick_size=0.01,
        enable_midpoint_guardrail=False,
        midpoint_guardrail_min_price=0.0,
        midpoint_guardrail_max_price=0.0,
        down_mid_bucket_experiment_mode="suppress",
    )
    bot = BTC5MinMakerBot(cfg)

    async def fake_resolve(http, through_window_start: int) -> None:
        return None

    async def fake_prices(*, window_start_ts: int, http) -> tuple[float, float]:
        return 100.0, 99.95

    class _DownBookHTTP(_DummyHTTP):
        async def fetch_book(self, token_id: str) -> dict:
            assert token_id == "tok-down"
            return {
                "bids": [{"price": 0.49, "size": 50}],
                "asks": [{"price": 0.52, "size": 50}],
            }

    monkeypatch.setattr(bot, "_resolve_unsettled", fake_resolve)
    monkeypatch.setattr(bot, "_get_open_and_current_price", fake_prices)

    window_start_ts = _ts(2026, 3, 9, 9, 35)
    result = await bot._process_window(window_start_ts=window_start_ts, http=_DownBookHTTP())

    assert result["status"] == "skip_down_mid_bucket_experiment"
    assert result["direction"] == "DOWN"
    assert result["price"] == pytest.approx(0.50)
    assert "execution_experiment=down_mid_bucket_repair" in result["decision_reason_tags"]
    assert "execution_experiment_action=suppress" in result["decision_reason_tags"]
    assert "execution_experiment=down_mid_bucket_repair" in result["sizing_reason_tags"]

    with bot.db._connect() as conn:
        row = conn.execute(
            """
            SELECT order_status, order_price, decision_reason_tags, sizing_reason_tags
            FROM window_trades
            WHERE window_start_ts = ?
            """,
            (window_start_ts,),
        ).fetchone()
    assert row["order_status"] == "skip_down_mid_bucket_experiment"
    assert row["order_price"] == pytest.approx(0.50)
    assert "execution_experiment=down_mid_bucket_repair" in json.loads(row["decision_reason_tags"])
    assert "execution_experiment_action=suppress" in json.loads(row["decision_reason_tags"])
    assert "execution_experiment=down_mid_bucket_repair" in json.loads(row["sizing_reason_tags"])


async def test_process_window_reprices_down_mid_bucket_experiment_to_049(
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
        up_max_buy_price=0.95,
        down_max_buy_price=0.95,
        min_buy_price=0.45,
        tick_size=0.01,
        enable_midpoint_guardrail=False,
        midpoint_guardrail_min_price=0.0,
        midpoint_guardrail_max_price=0.0,
        cancel_seconds_before_close=2,
        down_mid_bucket_experiment_mode="reprice_to_0.49",
    )
    bot = BTC5MinMakerBot(cfg)

    async def fake_resolve(http, through_window_start: int) -> None:
        return None

    async def fake_prices(*, window_start_ts: int, http) -> tuple[float, float]:
        return 100.0, 99.95

    class _DownBookHTTP(_DummyHTTP):
        async def fetch_book(self, token_id: str) -> dict:
            assert token_id == "tok-down"
            return {
                "bids": [{"price": 0.49, "size": 50}],
                "asks": [{"price": 0.52, "size": 50}],
            }

    class _LiveCLOB:
        def __init__(self) -> None:
            self.states = [
                LiveOrderState(
                    order_id="ord-mid-bucket",
                    status="cancelled",
                    original_size=5.10,
                    size_matched=0.0,
                    price=0.49,
                )
            ]

        def place_post_only_buy(self, token_id: str, price: float, shares: float) -> PlacementResult:
            assert token_id == "tok-down"
            assert price == pytest.approx(0.49)
            return PlacementResult(order_id="ord-mid-bucket", success=True, status="live")

        def get_order_state(self, order_id: str) -> LiveOrderState:
            assert order_id == "ord-mid-bucket"
            return self.states[0]

        def cancel_order(self, order_id: str) -> bool:
            assert order_id == "ord-mid-bucket"
            return True

    monkeypatch.setattr(bot, "_resolve_unsettled", fake_resolve)
    monkeypatch.setattr(bot, "_get_open_and_current_price", fake_prices)
    bot.clob = _LiveCLOB()

    window_start_ts = _ts(2026, 3, 9, 9, 35)
    result = await bot._process_window(window_start_ts=window_start_ts, http=_DownBookHTTP())

    assert result["status"] == "live_cancelled_unfilled"
    assert result["price"] == pytest.approx(0.49)
    assert "execution_experiment=down_mid_bucket_repair" in result["decision_reason_tags"]
    assert "execution_experiment_action=reprice_to_0.49" in result["decision_reason_tags"]
    assert "execution_experiment=down_mid_bucket_repair" in result["sizing_reason_tags"]

    with bot.db._connect() as conn:
        row = conn.execute(
            """
            SELECT order_status, order_price, decision_reason_tags, sizing_reason_tags
            FROM window_trades
            WHERE window_start_ts = ?
            """,
            (window_start_ts,),
        ).fetchone()
    assert row["order_status"] == "live_cancelled_unfilled"
    assert row["order_price"] == pytest.approx(0.49)
    assert "execution_experiment=down_mid_bucket_repair" in json.loads(row["decision_reason_tags"])
    assert "execution_experiment_action=reprice_to_0.49" in json.loads(
        row["decision_reason_tags"]
    )
    assert "execution_experiment=down_mid_bucket_repair" in json.loads(row["sizing_reason_tags"])

async def test_process_window_suppresses_direction_when_session_policy_zero_caps_it(
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
        min_delta=0.0,
        max_abs_delta=0.00015,
        max_buy_price=0.95,
        min_buy_price=0.45,
        tick_size=0.01,
        paper_fill_probability=1.0,
        session_policy_json='[{"name":"hour_et_08","et_hours":[8],"max_abs_delta":0.00002,"up_max_buy_price":0.0,"down_max_buy_price":0.48}]',
    )
    bot = BTC5MinMakerBot(cfg)

    async def fake_resolve(http, through_window_start: int) -> None:
        return None

    async def fake_prices(*, window_start_ts: int, http) -> tuple[float, float]:
        return 100.0, 100.001

    monkeypatch.setattr(bot, "_resolve_unsettled", fake_resolve)
    monkeypatch.setattr(bot, "_get_open_and_current_price", fake_prices)

    window_start_ts = _ts(2026, 3, 9, 8, 35)
    result = await bot._process_window(window_start_ts=window_start_ts, http=_DummyHTTP())

    assert result["status"] == "skip_direction_suppressed"
    assert result["edge_tier"] == "suppressed"
    assert result["loss_cluster_suppressed"] is False
    assert result["sizing_target_usd"] == pytest.approx(0.0)
    assert "skip_reason=direction_suppressed" in result["decision_reason_tags"]
    assert "suppression_reason=session_policy_direction_blocked" in result["decision_reason_tags"]
    assert "session_policy_direction_blocked" in result["sizing_reason_tags"]
    assert "session_bias=down_only" in result["sizing_reason_tags"]

    with bot.db._connect() as conn:
        row = conn.execute(
            """
            SELECT edge_tier, sizing_reason_tags, decision_reason_tags, loss_cluster_suppressed, order_status
            FROM window_trades
            WHERE window_start_ts = ?
            """,
            (window_start_ts,),
        ).fetchone()
    assert row["edge_tier"] == "suppressed"
    assert row["loss_cluster_suppressed"] == 0
    assert row["order_status"] == "skip_direction_suppressed"
    assert "session_policy_direction_blocked" in json.loads(row["sizing_reason_tags"])
    assert "suppression_reason=session_policy_direction_blocked" in json.loads(row["decision_reason_tags"])


async def test_process_window_applies_session_guardrail_override(
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
        up_max_buy_price=0.95,
        down_max_buy_price=0.95,
        min_buy_price=0.45,
        tick_size=0.01,
        cancel_seconds_before_close=2,
        enforce_lt049_skip_baseline=False,
        up_live_mode="live_enabled",
        session_policy_json='[{"name":"hour_et_09","et_hours":[9],"max_abs_delta":0.0002,"up_max_buy_price":0.48,"down_max_buy_price":0.49}]',
    )
    bot = BTC5MinMakerBot(cfg)

    async def fake_resolve(http, through_window_start: int) -> None:
        return None

    async def fake_prices(*, window_start_ts: int, http) -> tuple[float, float]:
        return 100.0, 100.011

    class SessionBookHTTP(_DummyHTTP):
        async def fetch_book(self, token_id: str) -> dict:
            assert token_id == "tok-up"
            return {
                "bids": [{"price": 0.47, "size": 50}],
                "asks": [{"price": 0.48, "size": 50}],
            }

    class FakeCLOB:
        def __init__(self) -> None:
                self.states = [
                    LiveOrderState(
                        order_id="ord-session",
                        status="cancelled",
                        original_size=10.42,
                        size_matched=0.0,
                        price=0.47,
                    )
                ]

        def place_post_only_buy(self, token_id: str, price: float, shares: float) -> PlacementResult:
            assert token_id == "tok-up"
            assert price == pytest.approx(0.47)
            return PlacementResult(order_id="ord-session", success=True, status="live")

        def get_order_state(self, order_id: str) -> LiveOrderState:
            assert order_id == "ord-session"
            return self.states[0]

        def cancel_order(self, order_id: str) -> bool:
            assert order_id == "ord-session"
            return True

    monkeypatch.setattr(bot, "_resolve_unsettled", fake_resolve)
    monkeypatch.setattr(bot, "_get_open_and_current_price", fake_prices)
    bot.clob = FakeCLOB()

    window_start_ts = _ts(2026, 3, 9, 9, 35)
    result = await bot._process_window(window_start_ts=window_start_ts, http=SessionBookHTTP())

    assert result["status"] == "live_cancelled_unfilled"
    assert result["price"] == pytest.approx(0.47)
    assert result["session_override_triggered"] is True
    assert result["session_policy_name"] == "hour_et_09"

    with bot.db._connect() as conn:
        row = conn.execute(
            "SELECT order_price, reason, order_status FROM window_trades WHERE window_start_ts = ?",
            (window_start_ts,),
        ).fetchone()
    assert row["order_price"] == pytest.approx(0.47)
    assert "session_policy" in (row["reason"] or "")
    assert row["order_status"] == "live_cancelled_unfilled"


async def test_process_window_session_policy_tightens_min_delta(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cfg = MakerConfig(
        paper_trading=True,
        db_path=tmp_path / "btc5.db",
        min_delta=0.0001,
        session_policy_json='[{"name":"hour_et_09","et_hours":[9],"min_delta":0.0002}]',
        min_buy_price=0.45,
        tick_size=0.01,
    )
    bot = BTC5MinMakerBot(cfg)

    async def fake_resolve(http, through_window_start: int) -> None:
        return None

    async def fake_prices(*, window_start_ts: int, http) -> tuple[float, float]:
        return 100.0, 100.015  # delta=0.00015, passes base but fails tightened session min_delta.

    monkeypatch.setattr(bot, "_resolve_unsettled", fake_resolve)
    monkeypatch.setattr(bot, "_get_open_and_current_price", fake_prices)

    window_start_ts = _ts(2026, 3, 9, 9, 35)
    result = await bot._process_window(window_start_ts=window_start_ts, http=_DummyHTTP())

    assert result["status"] == "skip_delta_too_small"
    assert result["session_policy_name"] == "hour_et_09"
    assert "skip_reason=delta_below_min" in result["decision_reason_tags"]

    with bot.db._connect() as conn:
        row = conn.execute(
            "SELECT reason, order_status, decision_reason_tags FROM window_trades WHERE window_start_ts = ?",
            (window_start_ts,),
        ).fetchone()
    assert row["order_status"] == "skip_delta_too_small"
    assert "name=hour_et_09" in (row["reason"] or "")
    assert "skip_reason=delta_below_min" in json.loads(row["decision_reason_tags"])


async def test_process_window_session_policy_caps_quote_ticks_even_with_regime(
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
        up_max_buy_price=0.95,
        down_max_buy_price=0.95,
        min_buy_price=0.45,
        tick_size=0.01,
        enable_midpoint_guardrail=False,
        midpoint_guardrail_min_price=0.0,
        midpoint_guardrail_max_price=0.0,
        cancel_seconds_before_close=2,
        maker_improve_ticks=1,
        enable_recent_regime_skew=True,
        recent_regime_fills=12,
        regime_min_fills_per_direction=5,
        regime_min_pnl_gap_usd=20.0,
        regime_weaker_direction_quote_ticks=0,
        down_mid_bucket_experiment_mode="off",
        session_policy_json='[{"name":"hour_et_09","et_hours":[9],"maker_improve_ticks":0}]',
    )
    bot = BTC5MinMakerBot(cfg)

    async def fake_resolve(http, through_window_start: int) -> None:
        return None

    async def fake_prices(*, window_start_ts: int, http) -> tuple[float, float]:
        return 100.0, 99.95  # DOWN direction (favored in seeded regime)

    class TightBookHTTP(_DummyHTTP):
        async def fetch_book(self, token_id: str) -> dict:
            assert token_id == "tok-down"
            return {
                "bids": [{"price": 0.49, "size": 50}],
                "asks": [{"price": 0.51, "size": 50}],
            }

    class FakeCLOB:
        def __init__(self) -> None:
            self.states = [
                LiveOrderState(
                    order_id="ord-regime-policy",
                    status="cancelled",
                    original_size=10.21,
                    size_matched=0.0,
                    price=0.49,
                )
            ]

        def place_post_only_buy(self, token_id: str, price: float, shares: float) -> PlacementResult:
            assert token_id == "tok-down"
            assert price == pytest.approx(0.49)
            return PlacementResult(order_id="ord-regime-policy", success=True, status="live")

        def get_order_state(self, order_id: str) -> LiveOrderState:
            assert order_id == "ord-regime-policy"
            return self.states[0]

        def cancel_order(self, order_id: str) -> bool:
            assert order_id == "ord-regime-policy"
            return True

    monkeypatch.setattr(bot, "_resolve_unsettled", fake_resolve)
    monkeypatch.setattr(bot, "_get_open_and_current_price", fake_prices)
    bot.clob = FakeCLOB()

    window_start_ts = _ts(2026, 3, 9, 9, 35)
    _seed_recent_regime(bot, window_start_ts=window_start_ts)
    result = await bot._process_window(window_start_ts=window_start_ts, http=TightBookHTTP())

    assert result["status"] == "live_cancelled_unfilled"
    assert result["quote_ticks"] == 0
    assert result["regime_triggered"] is True
    assert result["session_policy_name"] == "hour_et_09"


async def test_process_window_enters_probe_mode_after_recent_live_loss(
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
        up_max_buy_price=0.95,
        down_max_buy_price=0.95,
        min_buy_price=0.45,
        tick_size=0.01,
        enable_midpoint_guardrail=False,
        midpoint_guardrail_min_price=0.0,
        midpoint_guardrail_max_price=0.0,
        cancel_seconds_before_close=2,
        enable_probe_after_recent_loss=True,
        probe_recent_fills=4,
        probe_recent_min_pnl_usd=0.0,
        probe_quote_ticks=0,
        probe_up_max_buy_price=0.49,
        probe_down_max_buy_price=0.51,
        enforce_lt049_skip_baseline=False,
        up_live_mode="live_enabled",
    )
    bot = BTC5MinMakerBot(cfg)

    async def fake_resolve(http, through_window_start: int) -> None:
        return None

    async def fake_prices(*, window_start_ts: int, http) -> tuple[float, float]:
        return 100.0, 100.05

    class ProbeBookHTTP(_DummyHTTP):
        async def fetch_book(self, token_id: str) -> dict:
            assert token_id == "tok-up"
            return {
                "bids": [{"price": 0.48, "size": 50}],
                "asks": [{"price": 0.49, "size": 50}],
            }

    class FakeCLOB:
        def __init__(self) -> None:
            self.states = [
                LiveOrderState(
                    order_id="ord-probe",
                    status="cancelled",
                    original_size=10.21,
                    size_matched=0.0,
                    price=0.49,
                )
            ]

        def place_post_only_buy(self, token_id: str, price: float, shares: float) -> PlacementResult:
            assert token_id == "tok-up"
            assert price == pytest.approx(0.48)
            return PlacementResult(order_id="ord-probe", success=True, status="live")

        def get_order_state(self, order_id: str) -> LiveOrderState:
            assert order_id == "ord-probe"
            return self.states[0]

        def cancel_order(self, order_id: str) -> bool:
            assert order_id == "ord-probe"
            return True

    monkeypatch.setattr(bot, "_resolve_unsettled", fake_resolve)
    monkeypatch.setattr(bot, "_get_open_and_current_price", fake_prices)
    bot.clob = FakeCLOB()

    start = current_window_start(time.time()) - (8 * 300)
    for idx in range(6):
        ws = start + (idx * 300)
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
                "token_id": "tok-up",
                    "best_bid": 0.48,
                    "best_ask": 0.49,
                "order_price": 0.50,
                "trade_size_usd": 5.0,
                "shares": 10.0,
                "order_id": f"probe-seed-{idx}",
                "order_status": "live_filled",
                "filled": 1,
                "reason": "seed_loss",
                "resolved_side": "DOWN",
                "won": 0,
                "pnl_usd": -5.0,
            }
        )

    window_start_ts = current_window_start(time.time()) - (2 * 300)
    result = await bot._process_window(window_start_ts=window_start_ts, http=ProbeBookHTTP())

    assert result["status"] == "live_cancelled_unfilled"
    assert result["risk_mode"] == "probe_confirmation_v2"
    assert result["price"] == pytest.approx(0.48)

    with bot.db._connect() as conn:
        row = conn.execute(
            "SELECT order_price, reason, order_status, risk_mode FROM window_trades WHERE window_start_ts = ?",
            (window_start_ts,),
        ).fetchone()
    assert row["order_price"] == pytest.approx(0.48)
    assert "probe_recent_live_pnl" in (row["reason"] or "")
    assert row["order_status"] == "live_cancelled_unfilled"
    assert row["risk_mode"] == "probe_confirmation_v2"


async def test_process_window_uses_probe_mode_after_daily_loss(
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
        up_max_buy_price=0.95,
        down_max_buy_price=0.95,
        min_buy_price=0.45,
        tick_size=0.01,
        enable_midpoint_guardrail=False,
        midpoint_guardrail_min_price=0.0,
        midpoint_guardrail_max_price=0.0,
        cancel_seconds_before_close=2,
        daily_loss_limit_usd=5.0,
        enable_probe_after_daily_loss=True,
        enable_probe_after_recent_loss=False,
        probe_quote_ticks=0,
        probe_up_max_buy_price=0.49,
        probe_down_max_buy_price=0.51,
        enforce_lt049_skip_baseline=False,
        up_live_mode="live_enabled",
    )
    bot = BTC5MinMakerBot(cfg)

    async def fake_resolve(http, through_window_start: int) -> None:
        return None

    async def fake_prices(*, window_start_ts: int, http) -> tuple[float, float]:
        return 100.0, 100.05

    class ProbeBookHTTP(_DummyHTTP):
        async def fetch_book(self, token_id: str) -> dict:
            assert token_id == "tok-up"
            return {
                "bids": [{"price": 0.48, "size": 50}],
                "asks": [{"price": 0.49, "size": 50}],
            }

    class FakeCLOB:
        def __init__(self) -> None:
            self.states = [
                LiveOrderState(
                    order_id="ord-daily-probe",
                    status="cancelled",
                    original_size=10.21,
                    size_matched=0.0,
                    price=0.49,
                )
            ]

        def place_post_only_buy(self, token_id: str, price: float, shares: float) -> PlacementResult:
            assert token_id == "tok-up"
            assert price == pytest.approx(0.48)
            return PlacementResult(order_id="ord-daily-probe", success=True, status="live")

        def get_order_state(self, order_id: str) -> LiveOrderState:
            assert order_id == "ord-daily-probe"
            return self.states[0]

        def cancel_order(self, order_id: str) -> bool:
            assert order_id == "ord-daily-probe"
            return True

    monkeypatch.setattr(bot, "_resolve_unsettled", fake_resolve)
    monkeypatch.setattr(bot, "_get_open_and_current_price", fake_prices)
    bot.clob = FakeCLOB()

    ws = current_window_start(time.time()) - (6 * 300)
    bot.db.upsert_window(
        {
            "window_start_ts": ws,
            "window_end_ts": ws + 300,
            "slug": market_slug_for_window(ws),
            "decision_ts": int(time.time()) - 60,
            "direction": "UP",
            "open_price": 100.0,
            "current_price": 100.05,
            "delta": 0.0005,
            "token_id": "tok-up",
            "best_bid": 0.48,
            "best_ask": 0.49,
            "order_price": 0.50,
            "trade_size_usd": 5.0,
            "shares": 10.0,
            "order_id": "seed-daily-loss",
            "order_status": "live_filled",
            "filled": 1,
            "reason": "seed_daily_loss",
            "resolved_side": "DOWN",
            "won": 0,
            "pnl_usd": -6.0,
        }
    )

    window_start_ts = current_window_start(time.time()) - (2 * 300)
    prev_ws = window_start_ts - 300
    bot.db.upsert_window(
        {
            "window_start_ts": prev_ws,
            "window_end_ts": prev_ws + 300,
            "slug": market_slug_for_window(prev_ws),
            "decision_ts": prev_ws + 290,
            "direction": "UP",
            "open_price": 100.0,
            "current_price": 100.05,
            "delta": 0.0005,
            "order_status": "skip_probe_seed",
            "reason": "seed_probe_confirmation",
        }
    )
    result = await bot._process_window(window_start_ts=window_start_ts, http=ProbeBookHTTP())

    assert result["status"] == "live_cancelled_unfilled"
    assert result["risk_mode"] == "probe_confirmation_v2"

    with bot.db._connect() as conn:
        row = conn.execute(
            "SELECT order_price, reason, order_status, risk_mode FROM window_trades WHERE window_start_ts = ?",
            (window_start_ts,),
        ).fetchone()
    assert row["order_price"] == pytest.approx(0.48)
    assert "probe_daily_loss" in (row["reason"] or "")
    assert row["order_status"] == "live_cancelled_unfilled"
    assert row["risk_mode"] == "probe_confirmation_v2"


async def test_process_window_skips_excluded_price_bucket(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Windows whose order_price rounds to an excluded bucket are skipped."""
    import os

    monkeypatch.setenv("BTC5_EXCLUDE_PRICE_BUCKETS", "0.49")
    cfg = MakerConfig(
        paper_trading=False,
        db_path=tmp_path / "btc5.db",
        bankroll_usd=250.0,
        risk_fraction=0.04,
        max_trade_usd=10.0,
        min_trade_usd=0.25,
        min_delta=0.0,
        max_buy_price=0.95,
        min_buy_price=0.02,
        tick_size=0.01,
        enable_midpoint_guardrail=False,
        midpoint_guardrail_min_price=0.0,
        midpoint_guardrail_max_price=0.0,
        cancel_seconds_before_close=2,
        up_live_mode="live_enabled",
    )
    assert 0.49 in cfg.exclude_price_buckets

    bot = BTC5MinMakerBot(cfg)

    async def fake_resolve(http, through_window_start: int) -> None:
        return None

    async def fake_prices(*, window_start_ts: int, http) -> tuple[float, float]:
        return 100.0, 100.05  # small UP delta

    class _BookHTTP(_DummyHTTP):
        async def fetch_book(self, token_id: str) -> dict:
            assert token_id == "tok-up"
            # ask=0.50 -> maker quote = 0.49 (bid+1 tick) -> excluded bucket
            return {
                "bids": [{"price": 0.48, "size": 50}],
                "asks": [{"price": 0.50, "size": 50}],
            }

    monkeypatch.setattr(bot, "_resolve_unsettled", fake_resolve)
    monkeypatch.setattr(bot, "_get_open_and_current_price", fake_prices)

    window_start_ts = current_window_start(time.time()) - (2 * 300)
    result = await bot._process_window(window_start_ts=window_start_ts, http=_BookHTTP())

    assert result["status"] == "skip_excluded_price_bucket"
    assert result.get("excluded_bucket") == pytest.approx(0.49)

    with bot.db._connect() as conn:
        row = conn.execute(
            "SELECT decision_reason_tags, order_status FROM window_trades WHERE window_start_ts = ?",
            (window_start_ts,),
        ).fetchone()
    assert row["order_status"] == "skip_excluded_price_bucket"
    assert "skip_reason=excluded_price_bucket" in json.loads(row["decision_reason_tags"])


async def test_process_window_skips_session_excluded_bucket_but_keeps_050_available(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cfg = MakerConfig(
        paper_trading=False,
        db_path=tmp_path / "btc5.db",
        bankroll_usd=250.0,
        risk_fraction=0.04,
        max_trade_usd=10.0,
        min_trade_usd=0.25,
        min_delta=0.0,
        max_buy_price=0.95,
        up_max_buy_price=0.48,
        down_max_buy_price=0.51,
        min_buy_price=0.02,
        tick_size=0.01,
        enable_midpoint_guardrail=False,
        midpoint_guardrail_min_price=0.0,
        midpoint_guardrail_max_price=0.0,
        cancel_seconds_before_close=2,
        down_mid_bucket_experiment_mode="off",
        session_policy_json=(
            '[{"name":"hour_et_09_loss_cluster","et_hours":[9],'
            '"up_max_buy_price":0.48,"down_max_buy_price":0.51,'
            '"exclude_price_buckets":[0.45,0.46,0.47,0.48,0.49]}]'
        ),
    )
    bot = BTC5MinMakerBot(cfg)

    async def fake_resolve(http, through_window_start: int) -> None:
        return None

    async def fake_prices(*, window_start_ts: int, http) -> tuple[float, float]:
        return 100.0, 99.95

    class _SessionBookHTTP(_DummyHTTP):
        def __init__(self) -> None:
            self._books = [
                {
                    "bids": [{"price": 0.48, "size": 50}],
                    "asks": [{"price": 0.50, "size": 50}],
                },
                {
                    "bids": [{"price": 0.49, "size": 50}],
                    "asks": [{"price": 0.51, "size": 50}],
                },
            ]

        async def fetch_book(self, token_id: str) -> dict:
            assert token_id == "tok-down"
            return self._books.pop(0)

    class _LiveCLOB:
        def place_post_only_buy(self, token_id: str, price: float, shares: float) -> PlacementResult:
            assert token_id == "tok-down"
            assert price == pytest.approx(0.50)
            return PlacementResult(order_id="ord-050", success=True, status="live")

        def get_order_state(self, order_id: str) -> LiveOrderState:
            assert order_id == "ord-050"
            return LiveOrderState(
                order_id=order_id,
                status="cancelled",
                original_size=10.0,
                size_matched=0.0,
                price=0.50,
            )

        def cancel_order(self, order_id: str) -> bool:
            assert order_id == "ord-050"
            return True

    monkeypatch.setattr(bot, "_resolve_unsettled", fake_resolve)
    monkeypatch.setattr(bot, "_get_open_and_current_price", fake_prices)
    bot.clob = _LiveCLOB()

    http = _SessionBookHTTP()
    blocked_window_ts = _ts(2026, 3, 9, 9, 35)
    blocked_result = await bot._process_window(window_start_ts=blocked_window_ts, http=http)

    assert blocked_result["status"] == "skip_excluded_price_bucket"
    assert blocked_result["excluded_bucket"] == pytest.approx(0.49)
    assert blocked_result["excluded_by_session_policy"] is True
    assert "suppression_reason=session_policy_price_bucket_blocked" in blocked_result["decision_reason_tags"]

    tradable_window_ts = _ts(2026, 3, 9, 9, 40)
    tradable_result = await bot._process_window(window_start_ts=tradable_window_ts, http=http)

    assert tradable_result["status"] == "live_cancelled_unfilled"
    assert tradable_result["price"] == pytest.approx(0.50)
    assert tradable_result["session_policy_name"] == "hour_et_09_loss_cluster"

    with bot.db._connect() as conn:
        blocked_row = conn.execute(
            "SELECT order_status, decision_reason_tags FROM window_trades WHERE window_start_ts = ?",
            (blocked_window_ts,),
        ).fetchone()
        tradable_row = conn.execute(
            "SELECT order_status, order_price FROM window_trades WHERE window_start_ts = ?",
            (tradable_window_ts,),
        ).fetchone()
    assert blocked_row["order_status"] == "skip_excluded_price_bucket"
    assert "suppression_reason=session_policy_price_bucket_blocked" in json.loads(
        blocked_row["decision_reason_tags"]
    )
    assert tradable_row["order_status"] == "live_cancelled_unfilled"
    assert tradable_row["order_price"] == pytest.approx(0.50)
