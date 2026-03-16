from . import _btc_5min_maker_shared as _shared
import types

globals().update({k: v for k, v in vars(_shared).items() if not k.startswith("__")})

def test_current_window_start_alignment() -> None:
    assert current_window_start(1710000123) == 1710000000
    assert current_window_start(1710000300) == 1710000300


def test_market_slug_for_window() -> None:
    assert market_slug_for_window(1710000000) == "btc-updown-5m-1710000000"


def test_market_slug_for_window_supports_1m_override() -> None:
    assert market_slug_for_window(1710000000, window_seconds=60) == "btc-updown-1m-1710000000"


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
    # If the ask is above our cap, we skip — no passive bid above cap.
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


def test_choose_maker_buy_price_prefers_ask_side_on_wide_spread() -> None:
    price = choose_maker_buy_price(
        best_bid=0.51,
        best_ask=0.93,
        max_price=0.95,
        min_price=0.90,
        tick_size=0.01,
    )
    assert price == pytest.approx(0.92)


def test_choose_maker_buy_price_skips_when_post_only_band_falls_below_min_price() -> None:
    assert (
        choose_maker_buy_price(
            best_bid=0.49,
            best_ask=0.50,
            max_price=0.45,
            min_price=0.46,
            tick_size=0.01,
        )
        is None
    )


def test_transient_request_error_detection_identifies_network_flake_text() -> None:
    assert _is_transient_request_error_text("PolyApiException[status_code=None, error_message=Request exception!]")
    assert _is_transient_request_error_text("HTTP timeout while submitting order")


def test_transient_request_error_detection_ignores_non_transient_error_text() -> None:
    assert not _is_transient_request_error_text("post-only order crosses book")
    assert not _is_transient_request_error_text("invalid token_id")


def test_effective_max_buy_price_prefers_directional_caps() -> None:
    cfg = MakerConfig(
        up_max_buy_price=0.51,
        down_max_buy_price=0.50,
        max_buy_price=0.95,
    )
    assert effective_max_buy_price(cfg, "UP") == pytest.approx(0.51)
    assert effective_max_buy_price(cfg, "DOWN") == pytest.approx(0.50)
    assert effective_max_buy_price(cfg, "OTHER") == pytest.approx(0.95)


def test_capital_stage_defaults_keep_base_max_trade(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BTC5_CAPITAL_STAGE", raising=False)
    monkeypatch.delenv("BTC5_STAGE2_MAX_TRADE_USD", raising=False)
    monkeypatch.delenv("BTC5_STAGE3_MAX_TRADE_USD", raising=False)
    cfg = MakerConfig(max_trade_usd=7.5, daily_loss_limit_usd=123.0, capital_stage=None)
    assert cfg.capital_stage is None
    assert cfg.effective_max_trade_usd == pytest.approx(7.5)
    assert cfg.effective_daily_loss_limit_usd == pytest.approx(123.0)


def test_capital_stage_overrides_max_trade() -> None:
    cfg_stage1 = MakerConfig(
        max_trade_usd=5.0,
        capital_stage=1,
        stage1_max_trade_usd=10.0,
        stage2_max_trade_usd=20.0,
        stage3_max_trade_usd=50.0,
    )
    assert cfg_stage1.capital_stage == 1
    assert cfg_stage1.effective_max_trade_usd == pytest.approx(10.0)

    cfg_stage2 = MakerConfig(
        max_trade_usd=10.0,
        capital_stage=2,
        stage1_max_trade_usd=10.0,
        stage2_max_trade_usd=20.0,
        stage3_max_trade_usd=50.0,
    )
    assert cfg_stage2.capital_stage == 2
    assert cfg_stage2.effective_max_trade_usd == pytest.approx(20.0)

    cfg_stage3 = MakerConfig(
        max_trade_usd=10.0,
        capital_stage=3,
        stage1_max_trade_usd=10.0,
        stage2_max_trade_usd=20.0,
        stage3_max_trade_usd=50.0,
    )
    assert cfg_stage3.capital_stage == 3
    assert cfg_stage3.effective_max_trade_usd == pytest.approx(50.0)


def test_parse_session_guardrail_overrides_normalizes_valid_rows() -> None:
    overrides = parse_session_guardrail_overrides(
        '[{"name":"hour_et_09","et_hours":[9],"max_abs_delta":0.0001,"up_max_buy_price":0.48,"down_max_buy_price":0.49,"min_delta":0.0004,"maker_improve_ticks":0,"exclude_price_buckets":[0.49,0.48,0.49]},{"name":"","et_hours":[12]}]'
    )

    assert len(overrides) == 1
    assert overrides[0].name == "hour_et_09"
    assert overrides[0].et_hours == (9,)
    assert overrides[0].min_delta == pytest.approx(0.0004)
    assert overrides[0].max_abs_delta == pytest.approx(0.0001)
    assert overrides[0].up_max_buy_price == pytest.approx(0.48)
    assert overrides[0].down_max_buy_price == pytest.approx(0.49)
    assert overrides[0].maker_improve_ticks == 0


def test_parse_session_guardrail_overrides_preserves_zero_direction_caps() -> None:
    overrides = parse_session_guardrail_overrides(
        '[{"name":"hour_et_08","et_hours":[8],"max_abs_delta":0.00002,"up_max_buy_price":0.0,"down_max_buy_price":0.48}]'
    )

    assert len(overrides) == 1
    assert overrides[0].up_max_buy_price is None  # 0.0 normalizes to None (non-positive)
    assert overrides[0].down_max_buy_price == pytest.approx(0.48)


def test_active_session_guardrail_override_matches_et_hour() -> None:
    cfg = MakerConfig(
        session_policy_json='[{"name":"hour_et_09","et_hours":[9],"up_max_buy_price":0.48,"down_max_buy_price":0.49}]'
    )

    active = active_session_guardrail_override(cfg, window_start_ts=_ts(2026, 3, 9, 9, 35))
    inactive = active_session_guardrail_override(cfg, window_start_ts=_ts(2026, 3, 9, 12, 5))

    assert active is not None
    assert active.session_name == "hour_et_09"
    assert inactive is None


def test_active_session_guardrail_override_prefers_more_specific_hours() -> None:
    cfg = MakerConfig(
        session_policy_json=(
            '[{"name":"open_et","et_hours":[9,10,11],"up_max_buy_price":0.47,"down_max_buy_price":0.48},'
            '{"name":"hour_et_09","et_hours":[9],"up_max_buy_price":0.48,"down_max_buy_price":0.49}]'
        )
    )

    active = active_session_guardrail_override(cfg, window_start_ts=_ts(2026, 3, 9, 9, 35))

    assert active is not None
    assert tuple(override.name for override in cfg.session_guardrail_overrides) == ("hour_et_09", "open_et")
    assert active.session_name == "hour_et_09"


def test_effective_max_buy_price_prefers_session_override_cap() -> None:
    cfg = MakerConfig(
        up_max_buy_price=0.51,
        down_max_buy_price=0.50,
        max_buy_price=0.95,
    )
    session_override = SessionGuardrailOverride(
        name="hour_et_09",
        et_hours=(9,),
        up_max_buy_price=0.48,
        down_max_buy_price=0.49,
    )

    assert effective_max_buy_price(cfg, "UP", session_override=session_override) == pytest.approx(0.48)
    assert effective_max_buy_price(cfg, "DOWN", session_override=session_override) == pytest.approx(0.49)


def test_effective_max_buy_price_allows_zero_session_cap_to_disable_direction() -> None:
    cfg = MakerConfig(
        up_max_buy_price=0.51,
        down_max_buy_price=0.50,
        max_buy_price=0.95,
    )
    session_override = SessionGuardrailOverride(
        name="hour_et_08",
        et_hours=(8,),
        up_max_buy_price=0.0,
        down_max_buy_price=0.48,
    )

    assert effective_max_buy_price(cfg, "UP", session_override=session_override) == pytest.approx(0.0)
    assert effective_max_buy_price(cfg, "DOWN", session_override=session_override) == pytest.approx(0.48)


def test_session_guardrail_reason_mentions_session_and_hour() -> None:
    reason = session_guardrail_reason(
        SessionGuardrailOverride(
            name="hour_et_09",
            et_hours=(9,),
            min_delta=0.0004,
            max_abs_delta=0.0001,
            up_max_buy_price=0.48,
            down_max_buy_price=0.49,
            maker_improve_ticks=0,
        ),
        window_start_ts=_ts(2026, 3, 9, 9, 5),
    )

    assert reason is not None
    assert "name=hour_et_09" in reason
    assert "hour_et=9" in reason


def test_session_policy_no_policy_default_behavior() -> None:
    cfg = MakerConfig(
        session_policy_json="",
        session_policy_path="",
        session_overrides_json="",
    )
    assert cfg.session_guardrail_overrides == ()


def test_session_policy_path_loading(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"
    path.write_text(
        json.dumps(
            [
                {
                    "name": "hour_et_12",
                    "et_hours": [12],
                    "max_abs_delta": 0.0002,
                    "maker_improve_ticks": 0,
                }
            ]
        ),
        encoding="utf-8",
    )
    cfg = MakerConfig(
        session_policy_json="",
        session_policy_path=str(path),
        session_overrides_json='[{"name":"legacy","et_hours":[12],"max_abs_delta":0.0005}]',
    )
    assert len(cfg.session_guardrail_overrides) == 1
    assert cfg.session_guardrail_overrides[0].name == "hour_et_12"
    assert cfg.session_guardrail_overrides[0].max_abs_delta == pytest.approx(0.0002)


def test_session_policy_malformed_inline_is_noop() -> None:
    cfg = MakerConfig(
        session_policy_json="{bad json",
        session_policy_path="",
        session_overrides_json="",
    )
    assert cfg.session_guardrail_overrides == ()


def test_choose_maker_buy_price_rounds_to_tick() -> None:
    price = choose_maker_buy_price(
        best_bid=0.913,
        best_ask=0.931,
        max_price=0.95,
        min_price=0.90,
        tick_size=0.01,
    )
    assert price == pytest.approx(0.92)


def test_choose_maker_buy_price_respects_custom_aggression_ticks() -> None:
    price = choose_maker_buy_price(
        best_bid=0.49,
        best_ask=0.51,
        max_price=0.95,
        min_price=0.45,
        tick_size=0.01,
        aggression_ticks=0,
    )
    assert price == pytest.approx(0.49)


def test_choose_maker_buy_price_supports_post_only_safety_ticks() -> None:
    price = choose_maker_buy_price(
        best_bid=0.49,
        best_ask=0.50,
        max_price=0.95,
        min_price=0.45,
        tick_size=0.01,
        aggression_ticks=0,
        post_only_safety_ticks=1,
    )
    assert price == pytest.approx(0.48)


def test_summarize_recent_direction_regime_tightens_weaker_direction() -> None:
    rows = [
        {"id": idx, "direction": "DOWN", "order_price": 0.49, "pnl_usd": 5.0}
        for idx in range(1, 7)
    ] + [
        {"id": idx + 6, "direction": "UP", "order_price": 0.51, "pnl_usd": 1.0}
        for idx in range(1, 7)
    ]
    regime = summarize_recent_direction_regime(
        rows,
        default_quote_ticks=1,
        weaker_direction_quote_ticks=0,
        min_fills_per_direction=5,
        min_pnl_gap_usd=20.0,
        enable_one_sided_guardrail=True,
        one_sided_min_pnl_gap_usd=30.0,
    )

    assert regime is not None
    assert regime["triggered"] is True
    assert regime["favored_direction"] == "DOWN"
    assert regime["weaker_direction"] == "UP"
    assert regime["direction_quote_ticks"] == {"DOWN": 1, "UP": 0}
    assert regime["one_sided_triggered"] is False
    assert regime["directional_mode"] == "two_sided"


def test_summarize_recent_direction_regime_can_suppress_weaker_direction() -> None:
    rows = [
        {"id": idx, "direction": "DOWN", "order_price": 0.48, "pnl_usd": 7.0}
        for idx in range(1, 7)
    ] + [
        {"id": idx + 6, "direction": "UP", "order_price": 0.51, "pnl_usd": 1.0}
        for idx in range(1, 7)
    ]
    regime = summarize_recent_direction_regime(
        rows,
        default_quote_ticks=1,
        weaker_direction_quote_ticks=0,
        min_fills_per_direction=5,
        min_pnl_gap_usd=20.0,
        enable_one_sided_guardrail=True,
        one_sided_min_pnl_gap_usd=30.0,
    )

    assert regime is not None
    assert regime["triggered"] is True
    assert regime["one_sided_triggered"] is True
    assert regime["directional_mode"] == "one_sided"
    assert regime["suppressed_direction"] == "UP"
    assert regime["allowed_directions"] == ["DOWN"]


def test_summarize_recent_direction_regime_marks_net_negative_window_as_weak() -> None:
    rows = [
        {"id": idx, "direction": "DOWN", "order_price": 0.49, "pnl_usd": -1.0}
        for idx in range(1, 7)
    ] + [
        {"id": idx + 6, "direction": "UP", "order_price": 0.51, "pnl_usd": -4.0}
        for idx in range(1, 7)
    ]
    regime = summarize_recent_direction_regime(
        rows,
        default_quote_ticks=1,
        weaker_direction_quote_ticks=0,
        min_fills_per_direction=5,
        min_pnl_gap_usd=20.0,
        enable_one_sided_guardrail=True,
        one_sided_min_pnl_gap_usd=30.0,
    )

    assert regime is not None
    assert regime["triggered"] is False
    assert regime["trigger_reason"] == "pnl_gap_below_threshold"


def test_effective_quote_ticks_prefers_recent_regime_override() -> None:
    cfg = MakerConfig(maker_improve_ticks=1)
    regime = {
        "triggered": True,
        "direction_quote_ticks": {"UP": 0, "DOWN": 1},
    }
    assert effective_quote_ticks(cfg, "UP", recent_regime=regime) == 0
    assert effective_quote_ticks(cfg, "DOWN", recent_regime=regime) == 1
    assert effective_quote_ticks(cfg, "UP", recent_regime=None) == 1


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


def _install_fake_clob_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    py_clob_root = types.ModuleType("py_clob_client")
    clob_types = types.ModuleType("py_clob_client.clob_types")
    order_builder = types.ModuleType("py_clob_client.order_builder")
    constants = types.ModuleType("py_clob_client.order_builder.constants")

    class FakeOrderArgs:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeOrderType:
        GTC = "GTC"

    clob_types.OrderArgs = FakeOrderArgs
    clob_types.OrderType = FakeOrderType
    constants.BUY = "BUY"

    monkeypatch.setitem(sys.modules, "py_clob_client", py_clob_root)
    monkeypatch.setitem(sys.modules, "py_clob_client.clob_types", clob_types)
    monkeypatch.setitem(sys.modules, "py_clob_client.order_builder", order_builder)
    monkeypatch.setitem(sys.modules, "py_clob_client.order_builder.constants", constants)


def test_place_post_only_buy_fails_closed_when_post_only_unsupported(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfg = MakerConfig(db_path=tmp_path / "btc5.db")
    executor = CLOBExecutor(cfg)
    _install_fake_clob_modules(monkeypatch)

    class FakeClient:
        def create_order(self, order_args):
            return {"signed": order_args.kwargs}

        def post_order(self, _signed, _order_type, **kwargs):
            if "post_only" in kwargs:
                raise TypeError("post_only unsupported")
            raise AssertionError("non-post-only fallback should never execute")

    monkeypatch.setattr(executor, "ensure_client", lambda: FakeClient())

    with pytest.raises(RuntimeError, match="post_only=True"):
        executor.place_post_only_buy("tok-1", 0.49, 10.0)


def test_capital_stage_controls_gate_forward_and_shadow_research(tmp_path: Path) -> None:
    cfg = MakerConfig(
        db_path=tmp_path / "btc5.db",
        capital_stage=3,
        max_trade_usd=10.0,
        bankroll_usd=20_000.0,
        risk_fraction=0.02,
        stage1_max_trade_usd=10.0,
        stage2_max_trade_usd=20.0,
        stage3_max_trade_usd=50.0,
        daily_loss_limit_usd=250.0,
    )
    bot = BTC5MinMakerBot(cfg)
    ws = current_window_start(time.time()) - (2 * 300)
    _seed_stage_history(bot, window_start_ts=ws, live_filled_rows=120, live_filled_pnl_usd=1.0, order_failed_rows=9)

    controls = bot._capital_stage_controls(today_pnl=20.0)
    assert controls["effective_stage"] == 3
    assert controls["recommended_live_stage"] == 3
    assert controls["advantage_tier"] == "stage_3_live_ready"
    assert controls["effective_max_trade_usd"] == pytest.approx(50.0)
    assert controls["execution_drag_counts"]["order_failed_rate"] < 0.25
    assert controls["probe_fresh_for_stage_upgrade"] is True
    assert controls["shadow_research_tiers"]["shadow_100"]["shadow_only"] is True
    assert controls["shadow_research_tiers"]["shadow_100"]["size_usd"] == pytest.approx(100.0)
    assert controls["shadow_research_tiers"]["shadow_300"]["size_usd"] == pytest.approx(300.0)


def test_capital_stage_controls_block_stage_upgrade_when_probe_is_stale(tmp_path: Path) -> None:
    cfg = MakerConfig(
        db_path=tmp_path / "btc5.db",
        capital_stage=3,
        stage1_max_trade_usd=10.0,
        stage2_max_trade_usd=20.0,
        stage3_max_trade_usd=50.0,
        stage_probe_freshness_max_hours=6.0,
    )
    bot = BTC5MinMakerBot(cfg)
    stale_ws = current_window_start(time.time() - (8 * 3600))
    _seed_stage_history(bot, window_start_ts=stale_ws, live_filled_rows=120, live_filled_pnl_usd=1.0, order_failed_rows=0)

    controls = bot._capital_stage_controls(today_pnl=20.0)

    assert controls["effective_stage"] == 1
    assert controls["recommended_live_stage"] == 1
    assert controls["advantage_tier"] == "stage_1_live_only"
    assert controls["probe_fresh_for_stage_upgrade"] is False
    assert "stage_upgrade_probe_stale" in controls["stage_blockers"]
    assert "capped_to_stage_1" in controls["stage_gate_reason"]
