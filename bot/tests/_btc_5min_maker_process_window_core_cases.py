from . import _btc_5min_maker_shared as _shared

globals().update({k: v for k, v in vars(_shared).items() if not k.startswith("__")})
pytestmark = pytest.mark.asyncio

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
    assert "size_adjustment=clob_min_share_bump" in result["size_adjustment_tags"]
    assert "size_bumped_to_exchange_minimum" in result["size_adjustment_tags"]

    with bot.db._connect() as conn:
        row = conn.execute(
            "SELECT shares, trade_size_usd, filled, order_status, size_adjustment_tags FROM window_trades"
        ).fetchone()
    assert row["shares"] == pytest.approx(1.2)
    assert row["trade_size_usd"] == pytest.approx(1.104, rel=1e-3)
    assert row["filled"] == 1
    assert row["order_status"] == "live_partial_fill_cancelled"
    assert "size_adjustment=clob_min_share_bump" in json.loads(row["size_adjustment_tags"])


async def test_process_window_sell_early_closes_open_live_position(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cfg = MakerConfig(
        paper_trading=False,
        db_path=tmp_path / "btc5.db",
        bankroll_usd=250.0,
        risk_fraction=0.01,
        max_trade_usd=5.0,
        min_trade_usd=0.25,
        min_delta=0.01,
        max_buy_price=0.95,
        min_buy_price=0.90,
        tick_size=0.01,
        cancel_seconds_before_close=2,
        enable_sell_early=True,
        sell_early_min_profit_price=0.0,
        sell_early_max_candidates=3,
    )
    bot = BTC5MinMakerBot(cfg)

    async def fake_resolve(http, through_window_start: int) -> None:
        return None

    async def fake_prices(*, window_start_ts: int, http) -> tuple[float, float]:
        return 100.0, 100.0001

    class SellOnlyCLOB:
        def place_post_only_sell(self, token_id: str, price: float, shares: float) -> PlacementResult:
            assert token_id == "tok-down"
            assert price == pytest.approx(1.0)
            assert shares == pytest.approx(10.0)
            return PlacementResult(order_id="sell-1", success=True, status="live")

        def get_order_state(self, order_id: str) -> LiveOrderState:
            assert order_id == "sell-1"
            return LiveOrderState(
                order_id="sell-1",
                status="matched",
                original_size=10.0,
                size_matched=10.0,
                price=1.0,
            )

        def cancel_order(self, order_id: str) -> bool:
            raise AssertionError("cancel should not run when sell is fully filled")

    class EarlySellHTTP:
        top_of_book = staticmethod(MarketHttpClient.top_of_book)

        async def fetch_book(self, token_id: str) -> dict:
            assert token_id == "tok-down"
            return {
                "bids": [{"price": 0.99, "size": 100}],
                "asks": [],
            }

    monkeypatch.setattr(bot, "_resolve_unsettled", fake_resolve)
    monkeypatch.setattr(bot, "_get_open_and_current_price", fake_prices)
    bot.clob = SellOnlyCLOB()

    window_start_ts = current_window_start(time.time()) - (2 * 300)
    prior_window_start_ts = window_start_ts - 300
    bot.db.upsert_window(
        {
            "window_start_ts": prior_window_start_ts,
            "window_end_ts": prior_window_start_ts + 300,
            "slug": market_slug_for_window(prior_window_start_ts),
            "decision_ts": prior_window_start_ts + 290,
            "direction": "DOWN",
            "open_price": 100.0,
            "current_price": 99.95,
            "delta": -0.0005,
            "token_id": "tok-down",
            "best_bid": 0.94,
            "best_ask": 0.95,
            "order_price": 0.95,
            "trade_size_usd": 9.5,
            "shares": 10.0,
            "order_id": "buy-1",
            "order_status": "live_filled",
            "filled": 1,
            "reason": "seed_open",
            "resolved_side": None,
            "won": None,
            "pnl_usd": None,
            "realized_pnl_usd": 0.0,
        }
    )

    result = await bot._process_window(window_start_ts=window_start_ts, http=EarlySellHTTP())

    assert result["status"] == "skip_delta_too_small"
    assert result["sell_early"]["attempted"] == 1
    assert result["sell_early"]["closed"] == 1
    assert result["sell_early"]["realized_pnl_usd"] == pytest.approx(0.5)

    with bot.db._connect() as conn:
        row = conn.execute(
            """
            SELECT shares, order_status, resolved_side, won, pnl_usd, realized_pnl_usd, reason
            FROM window_trades
            WHERE window_start_ts = ?
            """,
            (prior_window_start_ts,),
        ).fetchone()
    assert row["shares"] == pytest.approx(0.0)
    assert row["order_status"] == "live_exited_early"
    assert row["resolved_side"] == "EARLY_EXIT"
    assert row["won"] == 1
    assert row["pnl_usd"] == pytest.approx(0.5)
    assert row["realized_pnl_usd"] == pytest.approx(0.5)
    assert "sell_early_price=1.00" in str(row["reason"] or "")


async def test_process_window_emits_capital_stage_fields(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cfg = MakerConfig(
        paper_trading=True,
        db_path=tmp_path / "btc5.db",
        bankroll_usd=10_000.0,
        risk_fraction=0.02,
        max_trade_usd=10.0,
        capital_stage=3,
        stage1_max_trade_usd=10.0,
        stage2_max_trade_usd=20.0,
        stage3_max_trade_usd=50.0,
        daily_loss_limit_usd=250.0,
        min_trade_usd=0.25,
        min_delta=0.0003,
        max_buy_price=0.95,
        min_buy_price=0.90,
        tick_size=0.01,
        paper_fill_probability=1.0,
    )
    bot = BTC5MinMakerBot(cfg)

    async def fake_resolve(http, through_window_start: int) -> None:
        return None

    async def fake_prices(*, window_start_ts: int, http) -> tuple[float, float]:
        return 100.0, 100.05

    monkeypatch.setattr(bot, "_resolve_unsettled", fake_resolve)
    monkeypatch.setattr(bot, "_get_open_and_current_price", fake_prices)

    window_start_ts = current_window_start(time.time()) - (2 * 300)
    _seed_stage_history(
        bot,
        window_start_ts=window_start_ts,
        live_filled_rows=120,
        live_filled_pnl_usd=1.0,
        order_failed_rows=9,
    )
    result = await bot._process_window(window_start_ts=window_start_ts, http=_DummyHTTP())

    assert "capital_stage" in result
    assert "recommended_live_stage" in result
    assert "effective_max_trade_usd" in result
    assert "effective_daily_loss_limit_usd" in result
    assert "advantage_tier" in result
    assert "stage_gate_reason" in result
    assert "stage_blockers" in result
    assert "probe_freshness_hours" in result
    assert "probe_fresh_for_stage_upgrade" in result
    assert "execution_drag_counts" in result
    assert "shadow_research_tiers" in result
    assert "capital_utilization_ratio" in result
    assert result["capital_stage"] == 3
    assert result["recommended_live_stage"] == 3
    assert result["effective_max_trade_usd"] == pytest.approx(50.0)
    assert result["effective_daily_loss_limit_usd"] == pytest.approx(250.0)
    assert result["advantage_tier"] == "stage_3_live_ready"
    assert result["probe_fresh_for_stage_upgrade"] is True
    assert result["shadow_research_tiers"]["shadow_100"]["size_usd"] == pytest.approx(100.0)
    assert result["shadow_research_tiers"]["shadow_200"]["size_usd"] == pytest.approx(200.0)
    assert result["shadow_research_tiers"]["shadow_200"]["max_trade_usd"] == pytest.approx(200.0)
    assert result["capital_utilization_ratio"] > 0.0


async def test_process_window_strong_validated_session_uses_full_stage_cap(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cfg = MakerConfig(
        paper_trading=True,
        db_path=tmp_path / "btc5.db",
        bankroll_usd=250.0,
        risk_fraction=0.02,
        max_trade_usd=5.0,
        stage1_max_trade_usd=10.0,
        min_trade_usd=0.25,
        min_delta=0.0,
        max_abs_delta=0.00015,
        max_buy_price=0.95,
        min_buy_price=0.45,
        tick_size=0.01,
        enable_midpoint_guardrail=False,
        midpoint_guardrail_min_price=0.0,
        midpoint_guardrail_max_price=0.0,
        adverse_session_size_multiplier=1.0,
        paper_fill_probability=1.0,
        session_policy_json='[{"name":"hour_et_09","et_hours":[9],"max_abs_delta":0.00005,"up_max_buy_price":0.49,"down_max_buy_price":0.48}]',
    )
    bot = BTC5MinMakerBot(cfg)

    async def fake_resolve(http, through_window_start: int) -> None:
        return None

    async def fake_prices(*, window_start_ts: int, http) -> tuple[float, float]:
        return 100.0, 99.996

    class StrongDownHTTP(_DummyHTTP):
        async def fetch_book(self, token_id: str) -> dict:
            assert token_id == "tok-down"
            return {
                "bids": [{"price": 0.47, "size": 50}],
                "asks": [{"price": 0.48, "size": 50}],
            }

    monkeypatch.setattr(bot, "_resolve_unsettled", fake_resolve)
    monkeypatch.setattr(bot, "_get_open_and_current_price", fake_prices)

    window_start_ts = _ts(2026, 3, 9, 9, 35)
    result = await bot._process_window(window_start_ts=window_start_ts, http=StrongDownHTTP())

    assert result["status"] == "paper_filled"
    assert result["edge_tier"] == "strong_validated"
    assert result["session_policy_name"] == "hour_et_09"
    assert result["effective_stage"] == 1
    assert result["effective_max_trade_usd"] == pytest.approx(10.0)
    assert result["size_usd"] == pytest.approx(9.4, rel=1e-4)
    assert result["sizing_target_usd"] == pytest.approx(result["size_usd"], rel=1e-4)
    assert result["sizing_cap_usd"] == pytest.approx(result["size_usd"], rel=1e-4)
    assert "sizing_mode=full_stage_cap" in result["sizing_reason_tags"]
    assert "validated_tight_session_delta" in result["sizing_reason_tags"]

    with bot.db._connect() as conn:
        row = conn.execute(
            """
            SELECT edge_tier, sizing_reason_tags, session_policy_name, effective_stage, trade_size_usd,
                   sizing_target_usd, sizing_cap_usd
            FROM window_trades
            WHERE window_start_ts = ?
            """,
            (window_start_ts,),
        ).fetchone()
    assert row["edge_tier"] == "strong_validated"
    assert row["session_policy_name"] == "hour_et_09"
    assert row["effective_stage"] == 1
    assert row["trade_size_usd"] == pytest.approx(9.4, rel=1e-4)
    assert row["sizing_target_usd"] == pytest.approx(row["trade_size_usd"], rel=1e-4)
    assert row["sizing_cap_usd"] == pytest.approx(row["trade_size_usd"], rel=1e-4)
    assert "validated_session_window" in json.loads(row["sizing_reason_tags"])


async def test_process_window_down_biased_cap_without_tight_delta_stays_probe_size(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cfg = MakerConfig(
        paper_trading=True,
        db_path=tmp_path / "btc5.db",
        bankroll_usd=500.0,
        risk_fraction=0.02,
        max_trade_usd=5.0,
        stage1_max_trade_usd=20.0,
        min_trade_usd=0.25,
        min_delta=0.0,
        max_abs_delta=0.00015,
        max_buy_price=0.95,
        min_buy_price=0.45,
        tick_size=0.01,
        enable_midpoint_guardrail=False,
        midpoint_guardrail_min_price=0.0,
        midpoint_guardrail_max_price=0.0,
        adverse_session_size_multiplier=1.0,
        paper_fill_probability=1.0,
        session_policy_json='[{"name":"hour_et_11","et_hours":[11],"up_max_buy_price":0.51,"down_max_buy_price":0.49}]',
    )
    bot = BTC5MinMakerBot(cfg)

    async def fake_resolve(http, through_window_start: int) -> None:
        return None

    async def fake_prices(*, window_start_ts: int, http) -> tuple[float, float]:
        return 100.0, 99.99

    class ExploratoryDownHTTP(_DummyHTTP):
        async def fetch_book(self, token_id: str) -> dict:
            assert token_id == "tok-down"
            return {
                "bids": [{"price": 0.48, "size": 50}],
                "asks": [{"price": 0.49, "size": 50}],
            }

    monkeypatch.setattr(bot, "_resolve_unsettled", fake_resolve)
    monkeypatch.setattr(bot, "_get_open_and_current_price", fake_prices)

    window_start_ts = _ts(2026, 3, 9, 11, 35)
    result = await bot._process_window(window_start_ts=window_start_ts, http=ExploratoryDownHTTP())

    assert result["status"] == "paper_filled"
    assert result["edge_tier"] == "exploratory"
    assert result["effective_max_trade_usd"] == pytest.approx(20.0)
    assert result["size_usd"] == pytest.approx(5.0016, rel=1e-4)
    assert result["sizing_target_usd"] == pytest.approx(5.0)
    assert result["sizing_cap_usd"] == pytest.approx(10.0)
    assert result["size_usd"] < result["effective_max_trade_usd"]
    assert "size_adjustment=exploratory_half_cap" in result["size_adjustment_tags"]
    assert "size_reduced_vs_stage_cap" in result["size_adjustment_tags"]
    assert "down_bias_probe_only_guardrail" in result["sizing_reason_tags"]
    assert "sizing_mode=exploratory_half_cap" in result["sizing_reason_tags"]


async def test_process_window_balanced_hour_11_candidate_stays_standard_without_tight_delta(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cfg = MakerConfig(
        paper_trading=True,
        db_path=tmp_path / "btc5.db",
        bankroll_usd=500.0,
        risk_fraction=0.02,
        max_trade_usd=5.0,
        stage1_max_trade_usd=20.0,
        min_trade_usd=0.25,
        min_delta=0.0,
        max_abs_delta=0.00015,
        max_buy_price=0.95,
        min_buy_price=0.45,
        tick_size=0.01,
        enable_midpoint_guardrail=False,
        midpoint_guardrail_min_price=0.0,
        midpoint_guardrail_max_price=0.0,
        adverse_session_size_multiplier=1.0,
        paper_fill_probability=1.0,
        session_policy_json='[{"name":"hour_et_11","et_hours":[11],"up_max_buy_price":0.51,"down_max_buy_price":0.51}]',
    )
    bot = BTC5MinMakerBot(cfg)

    async def fake_resolve(http, through_window_start: int) -> None:
        return None

    async def fake_prices(*, window_start_ts: int, http) -> tuple[float, float]:
        return 100.0, 99.99

    class BalancedHour11HTTP(_DummyHTTP):
        async def fetch_book(self, token_id: str) -> dict:
            assert token_id == "tok-down"
            return {
                "bids": [{"price": 0.47, "size": 50}],
                "asks": [{"price": 0.48, "size": 50}],
            }

    monkeypatch.setattr(bot, "_resolve_unsettled", fake_resolve)
    monkeypatch.setattr(bot, "_get_open_and_current_price", fake_prices)

    window_start_ts = _ts(2026, 3, 9, 11, 35)
    result = await bot._process_window(window_start_ts=window_start_ts, http=BalancedHour11HTTP())

    assert result["status"] == "paper_filled"
    assert result["edge_tier"] == "standard"
    assert result["size_usd"] == pytest.approx(9.4, rel=1e-4)
    assert result["sizing_target_usd"] == pytest.approx(result["size_usd"], rel=1e-4)
    assert result["sizing_cap_usd"] == pytest.approx(result["size_usd"], rel=1e-4)
    assert "size_adjustment=standard_risk_fraction" in result["size_adjustment_tags"]
    assert "size_reduced_vs_stage_cap" in result["size_adjustment_tags"]
    assert "sizing_mode=standard_risk_fraction" in result["sizing_reason_tags"]
    assert "validated_session_window=true" not in result["sizing_reason_tags"]


async def test_process_window_down_only_hour_11_candidate_stays_probe_only_tier(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cfg = MakerConfig(
        paper_trading=True,
        db_path=tmp_path / "btc5.db",
        bankroll_usd=1_000.0,
        risk_fraction=0.02,
        max_trade_usd=5.0,
        stage1_max_trade_usd=20.0,
        min_trade_usd=0.25,
        min_delta=0.0,
        max_abs_delta=0.00015,
        max_buy_price=0.95,
        min_buy_price=0.45,
        tick_size=0.01,
        enable_midpoint_guardrail=False,
        midpoint_guardrail_min_price=0.0,
        midpoint_guardrail_max_price=0.0,
        adverse_session_size_multiplier=1.0,
        paper_fill_probability=1.0,
        session_policy_json='[{"name":"hour_et_11","et_hours":[11],"max_abs_delta":0.00015,"up_max_buy_price":0.0,"down_max_buy_price":0.48}]',
    )
    bot = BTC5MinMakerBot(cfg)

    async def fake_resolve(http, through_window_start: int) -> None:
        return None

    async def fake_prices(*, window_start_ts: int, http) -> tuple[float, float]:
        return 100.0, 99.99

    class AsymmetricHour11HTTP(_DummyHTTP):
        async def fetch_book(self, token_id: str) -> dict:
            assert token_id == "tok-down"
            return {
                "bids": [{"price": 0.47, "size": 50}],
                "asks": [{"price": 0.48, "size": 50}],
            }

    monkeypatch.setattr(bot, "_resolve_unsettled", fake_resolve)
    monkeypatch.setattr(bot, "_get_open_and_current_price", fake_prices)

    window_start_ts = _ts(2026, 3, 9, 11, 35)
    result = await bot._process_window(window_start_ts=window_start_ts, http=AsymmetricHour11HTTP())

    assert result["status"] == "paper_filled"
    assert result["edge_tier"] == "exploratory"
    assert result["size_usd"] == pytest.approx(9.4, rel=1e-4)
    assert result["size_usd"] < result["effective_max_trade_usd"]
    assert result["sizing_target_usd"] == pytest.approx(result["size_usd"], rel=1e-4)
    assert result["sizing_cap_usd"] == pytest.approx(result["size_usd"], rel=1e-4)
    assert "down_bias_probe_only_guardrail" in result["sizing_reason_tags"]
    assert "session_bias=down_only" in result["sizing_reason_tags"]
    assert "sizing_mode=exploratory_half_cap" in result["sizing_reason_tags"]


async def test_process_window_weak_recent_regime_downgrades_nonvalidated_trade_to_exploratory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cfg = MakerConfig(
        paper_trading=True,
        db_path=tmp_path / "btc5.db",
        bankroll_usd=500.0,
        risk_fraction=0.02,
        max_trade_usd=5.0,
        stage1_max_trade_usd=20.0,
        min_trade_usd=0.25,
        min_delta=0.0,
        max_buy_price=0.95,
        up_max_buy_price=0.95,
        down_max_buy_price=0.95,
        min_buy_price=0.45,
        tick_size=0.01,
        paper_fill_probability=1.0,
        enable_recent_regime_skew=True,
        enable_probe_after_daily_loss=False,
        enable_probe_after_recent_loss=False,
        recent_regime_fills=12,
        regime_min_fills_per_direction=5,
        regime_min_pnl_gap_usd=20.0,
        regime_weaker_direction_quote_ticks=0,
    )
    bot = BTC5MinMakerBot(cfg)

    async def fake_resolve(http, through_window_start: int) -> None:
        return None

    async def fake_prices(*, window_start_ts: int, http) -> tuple[float, float]:
        return 100.0, 99.99

    class WeakWindowHTTP(_DummyHTTP):
        async def fetch_book(self, token_id: str) -> dict:
            assert token_id == "tok-down"
            return {
                "bids": [{"price": 0.49, "size": 50}],
                "asks": [{"price": 0.50, "size": 50}],
            }

    monkeypatch.setattr(bot, "_resolve_unsettled", fake_resolve)
    monkeypatch.setattr(bot, "_get_open_and_current_price", fake_prices)

    window_start_ts = current_window_start(time.time()) - (2 * 300)
    _seed_negative_recent_regime(bot, window_start_ts=window_start_ts)
    result = await bot._process_window(window_start_ts=window_start_ts, http=WeakWindowHTTP())

    assert result["status"] == "paper_filled"
    assert result["edge_tier"] == "exploratory"
    assert result["risk_mode"] == "normal"
    assert result["sizing_target_usd"] == pytest.approx(5.0)
    assert result["sizing_cap_usd"] == pytest.approx(10.0)
    assert "weak_recent_regime_guardrail" in result["sizing_reason_tags"]
    assert "recent_regime_weak_window=true" in result["sizing_reason_tags"]
    assert "decision=trade" in result["decision_reason_tags"]
    assert "trade_edge_tier=exploratory" in result["decision_reason_tags"]

    with bot.db._connect() as conn:
        row = conn.execute(
            """
            SELECT edge_tier, sizing_reason_tags, decision_reason_tags
            FROM window_trades
            WHERE window_start_ts = ?
            """,
            (window_start_ts,),
        ).fetchone()
    assert row["edge_tier"] == "exploratory"
    assert "weak_recent_regime_guardrail" in json.loads(row["sizing_reason_tags"])
    assert "decision=trade" in json.loads(row["decision_reason_tags"])


async def test_process_window_suppresses_observed_open_et_loss_cluster(
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
        min_delta=0.00001,
        max_buy_price=0.95,
        min_buy_price=0.45,
        tick_size=0.01,
        enable_midpoint_guardrail=False,
        midpoint_guardrail_min_price=0.0,
        midpoint_guardrail_max_price=0.0,
        adverse_session_size_multiplier=1.0,
        paper_fill_probability=1.0,
    )
    bot = BTC5MinMakerBot(cfg)

    async def fake_resolve(http, through_window_start: int) -> None:
        return None

    async def fake_prices(*, window_start_ts: int, http) -> tuple[float, float]:
        return 100.0, 99.996

    class ClusterDownHTTP(_DummyHTTP):
        async def fetch_book(self, token_id: str) -> dict:
            assert token_id == "tok-down"
            return {
                "bids": [{"price": 0.49, "size": 50}],
                "asks": [{"price": 0.51, "size": 50}],
            }

    monkeypatch.setattr(bot, "_resolve_unsettled", fake_resolve)
    monkeypatch.setattr(bot, "_get_open_and_current_price", fake_prices)

    window_start_ts = _ts(2026, 3, 9, 10, 35)
    result = await bot._process_window(window_start_ts=window_start_ts, http=ClusterDownHTTP())

    assert result["status"] == "skip_loss_cluster_suppressed"
    assert result["edge_tier"] == "suppressed"
    assert result["loss_cluster_suppressed"] is True
    assert result["size_usd"] == 0.0
    assert "skip_reason=loss_cluster_suppressed" in result["decision_reason_tags"]
    assert "suppression_reason=observed_loss_cluster_guardrail" in result["decision_reason_tags"]

    with bot.db._connect() as conn:
        row = conn.execute(
            """
            SELECT edge_tier, loss_cluster_suppressed, sizing_reason_tags, decision_reason_tags, order_status
            FROM window_trades
            WHERE window_start_ts = ?
            """,
            (window_start_ts,),
        ).fetchone()
    assert row["edge_tier"] == "suppressed"
    assert row["loss_cluster_suppressed"] == 1
    assert row["order_status"] == "skip_loss_cluster_suppressed"
    assert "observed_loss_cluster_guardrail" in json.loads(row["sizing_reason_tags"])
    assert "skip_reason=loss_cluster_suppressed" in json.loads(row["decision_reason_tags"])


async def test_process_window_stale_stage_readiness_keeps_full_size_at_effective_stage_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cfg = MakerConfig(
        paper_trading=True,
        db_path=tmp_path / "btc5.db",
        bankroll_usd=5_000.0,
        risk_fraction=0.02,
        max_trade_usd=5.0,
        capital_stage=3,
        stage1_max_trade_usd=10.0,
        stage2_max_trade_usd=20.0,
        stage3_max_trade_usd=50.0,
        stage_probe_freshness_max_hours=6.0,
        min_trade_usd=0.25,
        min_delta=0.0,
        max_abs_delta=0.00015,
        max_buy_price=0.95,
        min_buy_price=0.45,
        tick_size=0.01,
        enable_midpoint_guardrail=False,
        midpoint_guardrail_min_price=0.0,
        midpoint_guardrail_max_price=0.0,
        adverse_session_size_multiplier=1.0,
        paper_fill_probability=1.0,
        session_policy_json='[{"name":"hour_et_09","et_hours":[9],"max_abs_delta":0.00005,"up_max_buy_price":0.49,"down_max_buy_price":0.48}]',
    )
    bot = BTC5MinMakerBot(cfg)

    async def fake_resolve(http, through_window_start: int) -> None:
        return None

    async def fake_prices(*, window_start_ts: int, http) -> tuple[float, float]:
        return 100.0, 99.996

    class StrongDownHTTP(_DummyHTTP):
        async def fetch_book(self, token_id: str) -> dict:
            assert token_id == "tok-down"
            return {
                "bids": [{"price": 0.47, "size": 50}],
                "asks": [{"price": 0.48, "size": 50}],
            }

    monkeypatch.setattr(bot, "_resolve_unsettled", fake_resolve)
    monkeypatch.setattr(bot, "_get_open_and_current_price", fake_prices)

    stale_ws = _ts(2026, 3, 9, 0, 0)
    _seed_stage_history(bot, window_start_ts=stale_ws, live_filled_rows=120, live_filled_pnl_usd=1.0, order_failed_rows=0)

    window_start_ts = _ts(2026, 3, 9, 9, 35)
    result = await bot._process_window(window_start_ts=window_start_ts, http=StrongDownHTTP())

    assert result["status"] == "paper_filled"
    assert result["edge_tier"] == "strong_validated"
    assert result["effective_stage"] == 1
    assert result["recommended_live_stage"] == 1
    assert result["effective_max_trade_usd"] == pytest.approx(10.0)
    assert result["size_usd"] == pytest.approx(9.4, rel=1e-4)
    assert result["size_usd"] < cfg.stage3_max_trade_usd


async def test_process_window_uses_less_aggressive_quote_on_weaker_recent_direction(
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
    )
    bot = BTC5MinMakerBot(cfg)

    async def fake_resolve(http, through_window_start: int) -> None:
        return None

    async def fake_prices(*, window_start_ts: int, http) -> tuple[float, float]:
        return 100.0, 100.05

    class TightBookHTTP:
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
                "bids": [{"price": 0.49, "size": 50}],
                "asks": [{"price": 0.51, "size": 50}],
            }

    class FakeCLOB:
        def __init__(self) -> None:
            self.states = [
                LiveOrderState(
                    order_id="ord-regime",
                    status="cancelled",
                    original_size=10.21,
                    size_matched=0.0,
                    price=0.49,
                )
            ]

        def place_post_only_buy(self, token_id: str, price: float, shares: float) -> PlacementResult:
            assert token_id == "tok-up"
            assert price == pytest.approx(0.49)
            return PlacementResult(order_id="ord-regime", success=True, status="live")

        def get_order_state(self, order_id: str) -> LiveOrderState:
            assert order_id == "ord-regime"
            return self.states[0]

        def cancel_order(self, order_id: str) -> bool:
            assert order_id == "ord-regime"
            return True

    monkeypatch.setattr(bot, "_resolve_unsettled", fake_resolve)
    monkeypatch.setattr(bot, "_get_open_and_current_price", fake_prices)
    bot.clob = FakeCLOB()

    window_start_ts = current_window_start(time.time()) - (2 * 300)
    _seed_recent_regime(bot, window_start_ts=window_start_ts)

    result = await bot._process_window(window_start_ts=window_start_ts, http=TightBookHTTP())

    assert result["status"] == "live_cancelled_unfilled"
    assert result["quote_ticks"] == 0
    assert result["regime_triggered"] is True

    with bot.db._connect() as conn:
        row = conn.execute(
            "SELECT order_price, reason, order_status FROM window_trades WHERE window_start_ts = ?",
            (window_start_ts,),
        ).fetchone()
    assert row["order_price"] == pytest.approx(0.49)
    assert "recent_regime" in (row["reason"] or "")
    assert row["order_status"] == "live_cancelled_unfilled"


async def test_process_window_suppresses_weaker_direction_when_one_sided_regime_triggers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cfg = MakerConfig(
        paper_trading=True,
        db_path=tmp_path / "btc5.db",
        min_delta=0.0003,
        max_buy_price=0.95,
        up_max_buy_price=0.95,
        down_max_buy_price=0.95,
        min_buy_price=0.45,
        tick_size=0.01,
        enable_recent_regime_skew=True,
        recent_regime_fills=12,
        regime_min_fills_per_direction=5,
        regime_min_pnl_gap_usd=20.0,
        regime_weaker_direction_quote_ticks=0,
        enable_recent_regime_one_sided_guardrail=True,
        regime_one_sided_min_pnl_gap_usd=30.0,
        direction_suppression_min_price_exempt=1.0,
    )
    bot = BTC5MinMakerBot(cfg)

    async def fake_resolve(http, through_window_start: int) -> None:
        return None

    async def fake_prices(*, window_start_ts: int, http) -> tuple[float, float]:
        return 100.0, 100.05

    monkeypatch.setattr(bot, "_resolve_unsettled", fake_resolve)
    monkeypatch.setattr(bot, "_get_open_and_current_price", fake_prices)

    window_start_ts = current_window_start(time.time()) - (2 * 300)
    _seed_strong_recent_regime(bot, window_start_ts=window_start_ts)
    result = await bot._process_window(window_start_ts=window_start_ts, http=_DummyHTTP())

    assert result["status"] == "skip_direction_suppressed"
    assert result["directional_mode"] == "one_sided"
    assert result["suppressed_direction"] == "UP"
    assert result["regime_triggered"] is True

    with bot.db._connect() as conn:
        row = conn.execute(
            "SELECT reason, order_status FROM window_trades WHERE window_start_ts = ?",
            (window_start_ts,),
        ).fetchone()
    assert row["order_status"] == "skip_direction_suppressed"
    assert "suppressed_direction=UP" in (row["reason"] or "")


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
    assert result["order_outcome_attribution"] == "cancel_before_fill"

    with bot.db._connect() as conn:
        row = conn.execute(
            "SELECT reason, order_status FROM window_trades WHERE window_start_ts = ?",
            (window_start_ts,),
        ).fetchone()
    assert row["order_status"] == "live_cancelled_unfilled"
    assert "order_outcome_attribution=cancel_before_fill" in (row["reason"] or "")


async def test_process_window_retries_post_only_cross_with_safer_quote(
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
        min_buy_price=0.45,
        tick_size=0.01,
        enable_midpoint_guardrail=False,
        midpoint_guardrail_min_price=0.0,
        midpoint_guardrail_max_price=0.0,
        cancel_seconds_before_close=2,
        retry_post_only_cross=True,
        retry_post_only_safety_ticks=1,
    )
    bot = BTC5MinMakerBot(cfg)

    async def fake_resolve(http, through_window_start: int) -> None:
        return None

    async def fake_prices(*, window_start_ts: int, http) -> tuple[float, float]:
        return 100.0, 100.05

    class RetryBookHTTP:
        top_of_book = staticmethod(MarketHttpClient.top_of_book)

        def __init__(self) -> None:
            self.calls = 0

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
            self.calls += 1
            return {
                "bids": [{"price": 0.49, "size": 50}],
                "asks": [{"price": 0.50, "size": 50}],
            }

    class FakeCLOB:
        def __init__(self) -> None:
            self.calls: list[tuple[str, float, float]] = []
            self.states = [
                LiveOrderState(
                    order_id="ord-retry",
                    status="cancelled",
                    original_size=10.42,
                    size_matched=0.0,
                    price=0.48,
                )
            ]

        def place_post_only_buy(self, token_id: str, price: float, shares: float) -> PlacementResult:
            self.calls.append((token_id, price, shares))
            assert token_id == "tok-up"
            if len(self.calls) == 1:
                raise RuntimeError(
                    "PolyApiException[status_code=400, error_message={'error': 'invalid post-only order: order crosses book'}]"
                )
            assert price == pytest.approx(0.48)
            assert shares == pytest.approx(10.42)
            return PlacementResult(order_id="ord-retry", success=True, status="live")

        def get_order_state(self, order_id: str) -> LiveOrderState:
            assert order_id == "ord-retry"
            return self.states[0]

        def cancel_order(self, order_id: str) -> bool:
            assert order_id == "ord-retry"
            return True

    monkeypatch.setattr(bot, "_resolve_unsettled", fake_resolve)
    monkeypatch.setattr(bot, "_get_open_and_current_price", fake_prices)
    bot.clob = FakeCLOB()

    http = RetryBookHTTP()
    window_start_ts = current_window_start(time.time()) - (2 * 300)
    result = await bot._process_window(window_start_ts=window_start_ts, http=http)

    assert result["status"] == "live_cancelled_unfilled"
    assert result["price"] == pytest.approx(0.48)
    assert len(bot.clob.calls) == 2
    assert http.calls == 2
    assert result["placement_failure_attribution"] == "post_only_cross_failure"
    assert result["order_outcome_attribution"] == "cancel_before_fill"
    assert "post_only_cross_detected" in result["decision_reason_tags"]
    assert "post_only_retry_attempted" in result["decision_reason_tags"]
    assert "post_only_retry_status=repriced" in result["decision_reason_tags"]
    assert "decision=trade" in result["decision_reason_tags"]

    with bot.db._connect() as conn:
        row = conn.execute(
            """
            SELECT best_bid, best_ask, order_price, reason, order_status, decision_reason_tags
            FROM window_trades
            WHERE window_start_ts = ?
            """,
            (window_start_ts,),
        ).fetchone()
    assert row["best_bid"] == pytest.approx(0.49)
    assert row["best_ask"] == pytest.approx(0.50)
    assert row["order_price"] == pytest.approx(0.48)
    assert "post_only_retry" in (row["reason"] or "")
    assert "placement_failure_attribution=post_only_cross_failure" in (row["reason"] or "")
    assert row["order_status"] == "live_cancelled_unfilled"
    assert "post_only_retry_status=repriced" in json.loads(row["decision_reason_tags"])


async def test_process_window_flags_bad_book_attribution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cfg = MakerConfig(
        paper_trading=True,
        db_path=tmp_path / "btc5.db",
        min_delta=0.0,
        max_buy_price=0.95,
        min_buy_price=0.45,
        tick_size=0.01,
    )
    bot = BTC5MinMakerBot(cfg)

    async def fake_resolve(http, through_window_start: int) -> None:
        return None

    async def fake_prices(*, window_start_ts: int, http) -> tuple[float, float]:
        return 100.0, 100.05

    class BadBookHTTP(_DummyHTTP):
        async def fetch_book(self, token_id: str) -> dict:
            assert token_id == "tok-up"
            return {
                "bids": [{"price": 0.51, "size": 50}],
                "asks": [{"price": 0.50, "size": 50}],
            }

    monkeypatch.setattr(bot, "_resolve_unsettled", fake_resolve)
    monkeypatch.setattr(bot, "_get_open_and_current_price", fake_prices)

    window_start_ts = current_window_start(time.time()) - (2 * 300)
    result = await bot._process_window(window_start_ts=window_start_ts, http=BadBookHTTP())

    assert result["status"] == "skip_bad_book"
    assert result["book_failure_attribution"] == "bad_book"

    with bot.db._connect() as conn:
        row = conn.execute(
            "SELECT reason, order_status FROM window_trades WHERE window_start_ts = ?",
            (window_start_ts,),
        ).fetchone()
    assert row["order_status"] == "skip_bad_book"
    assert "book_failure_attribution=bad_book" in (row["reason"] or "")


async def test_process_window_records_order_placement_failure_attribution(
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

    class FailingCLOB:
        def place_post_only_buy(self, token_id: str, price: float, shares: float) -> PlacementResult:
            raise RuntimeError("placement unavailable")

        def get_order_state(self, order_id: str) -> LiveOrderState:
            raise AssertionError("get_order_state should not be called")

        def cancel_order(self, order_id: str) -> bool:
            raise AssertionError("cancel_order should not be called")

    monkeypatch.setattr(bot, "_resolve_unsettled", fake_resolve)
    monkeypatch.setattr(bot, "_get_open_and_current_price", fake_prices)
    bot.clob = FailingCLOB()

    window_start_ts = current_window_start(time.time()) - (2 * 300)
    result = await bot._process_window(window_start_ts=window_start_ts, http=_DummyHTTP())

    assert result["status"] == "live_order_failed"
    assert result["placement_failure_attribution"] == "order_placement_failure"

    with bot.db._connect() as conn:
        row = conn.execute(
            "SELECT reason, order_status FROM window_trades WHERE window_start_ts = ?",
            (window_start_ts,),
        ).fetchone()
    assert row["order_status"] == "live_order_failed"
    assert "placement_failure_attribution=order_placement_failure" in (row["reason"] or "")


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
    assert "skip_reason=delta_above_max" in result["decision_reason_tags"]

    with bot.db._connect() as conn:
        row = conn.execute(
            "SELECT decision_reason_tags, order_status FROM window_trades WHERE window_start_ts = ?",
            (window_start_ts,),
        ).fetchone()
    assert row["order_status"] == "skip_delta_too_large"
    assert "skip_reason=delta_above_max" in json.loads(row["decision_reason_tags"])


async def test_process_window_wallet_copy_dark_mode_without_feed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cfg = MakerConfig(
        paper_trading=True,
        db_path=tmp_path / "btc5.db",
        min_delta=0.001,
        max_buy_price=0.95,
        min_buy_price=0.45,
        tick_size=0.01,
        enable_wallet_copy=True,
        paper_fill_probability=1.0,
    )
    bot = BTC5MinMakerBot(cfg)
    bot.smart_wallet_feed = None

    async def fake_resolve(http, through_window_start: int) -> None:
        return None

    async def fake_prices(*, window_start_ts: int, http) -> tuple[float, float]:
        # abs(delta)=0.0001, below min_delta and should stay skipped without a feed.
        return 100.0, 100.01

    monkeypatch.setattr(bot, "_resolve_unsettled", fake_resolve)
    monkeypatch.setattr(bot, "_get_open_and_current_price", fake_prices)

    window_start_ts = current_window_start(time.time()) - (2 * 300)
    result = await bot._process_window(window_start_ts=window_start_ts, http=_DummyHTTP())

    assert result["status"] == "skip_delta_too_small"
    assert result["wallet_copy"] is False
    assert result["wallet_count"] == 0
    assert result["wallet_notional"] == pytest.approx(0.0)

    with bot.db._connect() as conn:
        row = conn.execute(
            """
            SELECT order_status, wallet_copy, wallet_count, wallet_notional
            FROM window_trades
            WHERE window_start_ts = ?
            """,
            (window_start_ts,),
        ).fetchone()
    assert row["order_status"] == "skip_delta_too_small"
    assert row["wallet_copy"] == 0
    assert row["wallet_count"] == 0
    assert row["wallet_notional"] == pytest.approx(0.0)


async def test_process_window_wallet_copy_overrides_direction_and_persists_fields(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cfg = MakerConfig(
        paper_trading=True,
        db_path=tmp_path / "btc5.db",
        min_delta=0.001,
        max_buy_price=0.95,
        up_max_buy_price=0.95,
        down_max_buy_price=0.95,
        min_buy_price=0.45,
        tick_size=0.01,
        enable_wallet_copy=True,
        wallet_copy_override_delta=0.0005,
        wallet_copy_min_wallets=3,
        wallet_copy_min_notional=200.0,
        paper_fill_probability=1.0,
    )
    bot = BTC5MinMakerBot(cfg)

    class _Consensus:
        direction = "UP"
        smart_wallet_count = 4
        combined_notional_usd = 250.0

        def strong(self) -> bool:
            return True

    class _MockWalletFeed:
        def __init__(self) -> None:
            self.started: list[tuple[str, int]] = []

        async def start_background_watch(self, condition_id: str, window_start_ts: int) -> None:
            self.started.append((condition_id, window_start_ts))

        async def get_cached_consensus(self, window_start_ts: int) -> _Consensus:
            return _Consensus()

    class _WalletHTTP(_DummyHTTP):
        async def fetch_market_by_slug(self, slug: str) -> dict:
            payload = await super().fetch_market_by_slug(slug)
            payload["conditionId"] = "cond-123"
            return payload

    async def fake_resolve(http, through_window_start: int) -> None:
        return None

    async def fake_prices(*, window_start_ts: int, http) -> tuple[float, float]:
        # abs(delta)=0.0001, so base direction is None and wallet copy should override.
        return 100.0, 100.01

    monkeypatch.setattr(bot, "_resolve_unsettled", fake_resolve)
    monkeypatch.setattr(bot, "_get_open_and_current_price", fake_prices)
    bot.smart_wallet_feed = _MockWalletFeed()

    window_start_ts = current_window_start(time.time()) - (2 * 300)
    result = await bot._process_window(window_start_ts=window_start_ts, http=_WalletHTTP())

    assert result["status"] == "paper_filled"
    assert result["direction"] == "UP"
    assert result["wallet_copy"] is True
    assert result["wallet_count"] == 4
    assert result["wallet_notional"] == pytest.approx(250.0)
    assert bot.smart_wallet_feed.started

    with bot.db._connect() as conn:
        row = conn.execute(
            """
            SELECT direction, order_status, wallet_copy, wallet_count, wallet_notional
            FROM window_trades
            WHERE window_start_ts = ?
            """,
            (window_start_ts,),
        ).fetchone()
    assert row["direction"] == "UP"
    assert row["order_status"] == "paper_filled"
    assert row["wallet_copy"] == 1
    assert row["wallet_count"] == 4
    assert row["wallet_notional"] == pytest.approx(250.0)


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
        enable_midpoint_guardrail=False,
        midpoint_guardrail_min_price=0.0,
        midpoint_guardrail_max_price=0.0,
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

    assert result["status"] in {"live_cancelled_unfilled", "live_filled", "live_order_failed"}
    with bot.db._connect() as conn:
        row = conn.execute(
            "SELECT order_price, order_status FROM window_trades WHERE window_start_ts = ?",
            (window_start_ts,),
        ).fetchone()
    assert row is not None
    assert row["order_status"] in {"live_cancelled_unfilled", "live_filled", "live_order_failed"}
    assert row["order_price"] == pytest.approx(0.50)
