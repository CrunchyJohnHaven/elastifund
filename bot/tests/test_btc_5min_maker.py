#!/usr/bin/env python3
"""Unit tests for bot/btc_5min_maker.py."""

import sys
import time
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from bot.btc_5min_maker import (  # noqa: E402
    BTC5MinMakerBot,
    CLOBExecutor,
    LiveOrderState,
    MakerConfig,
    MarketHttpClient,
    PlacementResult,
    SessionGuardrailOverride,
    active_session_guardrail_override,
    calc_trade_size_usd,
    clob_min_order_size,
    choose_maker_buy_price,
    choose_token_id_for_direction,
    current_window_start,
    deterministic_fill,
    direction_from_prices,
    effective_max_buy_price,
    effective_quote_ticks,
    market_slug_for_window,
    parse_json_list,
    parse_session_guardrail_overrides,
    session_guardrail_reason,
    summarize_recent_direction_regime,
)


ET = ZoneInfo("America/New_York")


def test_current_window_start_alignment() -> None:
    assert current_window_start(1710000123) == 1710000000
    assert current_window_start(1710000300) == 1710000300


def test_market_slug_for_window() -> None:
    assert market_slug_for_window(1710000000) == "btc-updown-5m-1710000000"


def _ts(year: int, month: int, day: int, hour: int, minute: int) -> int:
    return int(datetime(year, month, day, hour, minute, tzinfo=ET).timestamp())


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
        '[{"name":"hour_et_09","et_hours":[9],"max_abs_delta":0.0001,"up_max_buy_price":0.48,"down_max_buy_price":0.49,"min_delta":0.0004,"maker_improve_ticks":0},{"name":"","et_hours":[12]}]'
    )

    assert len(overrides) == 1
    assert overrides[0].name == "hour_et_09"
    assert overrides[0].et_hours == (9,)
    assert overrides[0].min_delta == pytest.approx(0.0004)
    assert overrides[0].max_abs_delta == pytest.approx(0.0001)
    assert overrides[0].up_max_buy_price == pytest.approx(0.48)
    assert overrides[0].down_max_buy_price == pytest.approx(0.49)
    assert overrides[0].maker_improve_ticks == 0


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


def _seed_recent_regime(bot: BTC5MinMakerBot, *, window_start_ts: int) -> None:
    start = window_start_ts - (12 * 300)
    for idx in range(12):
        direction = "DOWN" if idx < 6 else "UP"
        pnl = 5.0 if direction == "DOWN" else 1.0
        order_price = 0.49 if direction == "DOWN" else 0.51
        ws = start + (idx * 300)
        bot.db.upsert_window(
            {
                "window_start_ts": ws,
                "window_end_ts": ws + 300,
                "slug": market_slug_for_window(ws),
                "decision_ts": ws + 290,
                "direction": direction,
                "open_price": 100.0,
                "current_price": 100.05,
                "delta": 0.0005,
                "token_id": f"tok-{direction.lower()}",
                "best_bid": order_price - 0.01,
                "best_ask": order_price,
                "order_price": order_price,
                "trade_size_usd": 5.0,
                "shares": round(5.0 / order_price, 2),
                "order_id": f"hist-{idx}",
                "order_status": "live_filled",
                "filled": 1,
                "reason": "seed",
                "resolved_side": direction,
                "won": 1,
                "pnl_usd": pnl,
            }
        )


def _seed_strong_recent_regime(bot: BTC5MinMakerBot, *, window_start_ts: int) -> None:
    start = window_start_ts - (12 * 300)
    for idx in range(12):
        direction = "DOWN" if idx < 6 else "UP"
        pnl = 7.0 if direction == "DOWN" else 1.0
        order_price = 0.48 if direction == "DOWN" else 0.51
        ws = start + (idx * 300)
        bot.db.upsert_window(
            {
                "window_start_ts": ws,
                "window_end_ts": ws + 300,
                "slug": market_slug_for_window(ws),
                "decision_ts": ws + 290,
                "direction": direction,
                "open_price": 100.0,
                "current_price": 100.05,
                "delta": 0.0005,
                "token_id": f"tok-{direction.lower()}",
                "best_bid": order_price - 0.01,
                "best_ask": order_price,
                "order_price": order_price,
                "trade_size_usd": 5.0,
                "shares": round(5.0 / order_price, 2),
                "order_id": f"strong-hist-{idx}",
                "order_status": "live_filled",
                "filled": 1,
                "reason": "seed_strong",
                "resolved_side": direction,
                "won": 1,
                "pnl_usd": pnl,
            }
        )


def _seed_stage_history(
    bot: BTC5MinMakerBot,
    *,
    window_start_ts: int,
    live_filled_rows: int,
    live_filled_pnl_usd: float,
    order_failed_rows: int = 0,
) -> None:
    start = window_start_ts - ((live_filled_rows + order_failed_rows + 2) * 300)
    for idx in range(live_filled_rows):
        ws = start + (idx * 300)
        bot.db.upsert_window(
            {
                "window_start_ts": ws,
                "window_end_ts": ws + 300,
                "slug": market_slug_for_window(ws),
                "decision_ts": ws + 290,
                "direction": "DOWN" if idx % 2 == 0 else "UP",
                "open_price": 100.0,
                "current_price": 100.05,
                "delta": 0.0005,
                "token_id": "tok",
                "best_bid": 0.49,
                "best_ask": 0.50,
                "order_price": 0.49,
                "trade_size_usd": 5.0,
                "shares": 10.2,
                "order_id": f"stage-fill-{idx}",
                "order_status": "live_filled",
                "filled": 1,
                "reason": "seed_stage",
                "resolved_side": "DOWN",
                "won": 1,
                "pnl_usd": live_filled_pnl_usd,
            }
        )
    for idx in range(order_failed_rows):
        ws = start + ((live_filled_rows + idx) * 300)
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
                "token_id": "tok",
                "best_bid": 0.49,
                "best_ask": 0.50,
                "order_price": 0.49,
                "trade_size_usd": 0.0,
                "shares": 0.0,
                "order_id": f"stage-fail-{idx}",
                "order_status": "live_order_failed",
                "filled": 0,
                "reason": "seed_stage_fail",
                "resolved_side": "UP",
                "won": 0,
                "pnl_usd": 0.0,
            }
        )


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
    assert controls["shadow_research_tiers"]["shadow_200"]["size_usd"] == pytest.approx(200.0)


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
    assert result["capital_utilization_ratio"] > 0.0


@pytest.mark.asyncio
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
        max_buy_price=0.95,
        min_buy_price=0.45,
        tick_size=0.01,
        paper_fill_probability=1.0,
        session_policy_json='[{"name":"hour_et_09","et_hours":[9],"up_max_buy_price":0.49,"down_max_buy_price":0.48}]',
    )
    bot = BTC5MinMakerBot(cfg)

    async def fake_resolve(http, through_window_start: int) -> None:
        return None

    async def fake_prices(*, window_start_ts: int, http) -> tuple[float, float]:
        return 100.0, 99.95

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
    assert result["size_usd"] == pytest.approx(9.9969, rel=1e-4)
    assert "sizing_mode=full_stage_cap" in result["sizing_reason_tags"]

    with bot.db._connect() as conn:
        row = conn.execute(
            """
            SELECT edge_tier, sizing_reason_tags, session_policy_name, effective_stage, trade_size_usd
            FROM window_trades
            WHERE window_start_ts = ?
            """,
            (window_start_ts,),
        ).fetchone()
    assert row["edge_tier"] == "strong_validated"
    assert row["session_policy_name"] == "hour_et_09"
    assert row["effective_stage"] == 1
    assert row["trade_size_usd"] == pytest.approx(9.9969, rel=1e-4)
    assert "validated_session_hour_et_09" in json.loads(row["sizing_reason_tags"])


@pytest.mark.asyncio
async def test_process_window_exploratory_hour_11_candidate_is_not_full_size(
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
        max_buy_price=0.95,
        min_buy_price=0.45,
        tick_size=0.01,
        paper_fill_probability=1.0,
        session_policy_json='[{"name":"hour_et_11","et_hours":[11],"up_max_buy_price":0.51,"down_max_buy_price":0.51}]',
    )
    bot = BTC5MinMakerBot(cfg)

    async def fake_resolve(http, through_window_start: int) -> None:
        return None

    async def fake_prices(*, window_start_ts: int, http) -> tuple[float, float]:
        return 100.0, 99.95

    class ExploratoryDownHTTP(_DummyHTTP):
        async def fetch_book(self, token_id: str) -> dict:
            assert token_id == "tok-down"
            return {
                "bids": [{"price": 0.49, "size": 50}],
                "asks": [{"price": 0.51, "size": 50}],
            }

    monkeypatch.setattr(bot, "_resolve_unsettled", fake_resolve)
    monkeypatch.setattr(bot, "_get_open_and_current_price", fake_prices)

    window_start_ts = _ts(2026, 3, 9, 11, 35)
    result = await bot._process_window(window_start_ts=window_start_ts, http=ExploratoryDownHTTP())

    assert result["status"] == "paper_filled"
    assert result["edge_tier"] == "exploratory"
    assert result["effective_max_trade_usd"] == pytest.approx(20.0)
    assert result["size_usd"] == pytest.approx(10.0)
    assert result["size_usd"] < result["effective_max_trade_usd"]
    assert "sizing_mode=exploratory_half_cap" in result["sizing_reason_tags"]


@pytest.mark.asyncio
async def test_process_window_balanced_hour_11_candidate_can_use_strong_validated_tier(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cfg = MakerConfig(
        paper_trading=True,
        db_path=tmp_path / "btc5.db",
        bankroll_usd=5_000.0,
        risk_fraction=0.02,
        max_trade_usd=5.0,
        stage1_max_trade_usd=20.0,
        min_trade_usd=0.25,
        min_delta=0.0,
        max_buy_price=0.95,
        min_buy_price=0.45,
        tick_size=0.01,
        paper_fill_probability=1.0,
        session_policy_json='[{"name":"hour_et_11","et_hours":[11],"up_max_buy_price":0.51,"down_max_buy_price":0.51}]',
    )
    bot = BTC5MinMakerBot(cfg)

    async def fake_resolve(http, through_window_start: int) -> None:
        return None

    async def fake_prices(*, window_start_ts: int, http) -> tuple[float, float]:
        return 100.0, 99.95

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
    assert result["edge_tier"] == "strong_validated"
    assert result["size_usd"] > 19.95
    assert result["size_usd"] <= result["effective_max_trade_usd"]
    assert "validated_session_hour_et_11" in result["sizing_reason_tags"]
    assert "validated_balanced_session_caps" in result["sizing_reason_tags"]
    assert "sizing_mode=full_stage_cap" in result["sizing_reason_tags"]


@pytest.mark.asyncio
async def test_process_window_asymmetric_hour_11_candidate_stays_probe_only_tier(
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
        max_buy_price=0.95,
        min_buy_price=0.45,
        tick_size=0.01,
        paper_fill_probability=1.0,
        session_policy_json='[{"name":"hour_et_11","et_hours":[11],"up_max_buy_price":0.49,"down_max_buy_price":0.51}]',
    )
    bot = BTC5MinMakerBot(cfg)

    async def fake_resolve(http, through_window_start: int) -> None:
        return None

    async def fake_prices(*, window_start_ts: int, http) -> tuple[float, float]:
        return 100.0, 99.95

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
    assert result["size_usd"] > 9.95
    assert result["size_usd"] < result["effective_max_trade_usd"]
    assert "hour_11_down_bias_probe_only_guardrail" in result["sizing_reason_tags"]
    assert "session_caps_balanced=false" in result["sizing_reason_tags"]
    assert "sizing_mode=exploratory_half_cap" in result["sizing_reason_tags"]


@pytest.mark.asyncio
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

    with bot.db._connect() as conn:
        row = conn.execute(
            """
            SELECT edge_tier, loss_cluster_suppressed, sizing_reason_tags, order_status
            FROM window_trades
            WHERE window_start_ts = ?
            """,
            (window_start_ts,),
        ).fetchone()
    assert row["edge_tier"] == "suppressed"
    assert row["loss_cluster_suppressed"] == 1
    assert row["order_status"] == "skip_loss_cluster_suppressed"
    assert "observed_loss_cluster_guardrail" in json.loads(row["sizing_reason_tags"])


@pytest.mark.asyncio
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
        max_buy_price=0.95,
        min_buy_price=0.45,
        tick_size=0.01,
        paper_fill_probability=1.0,
        session_policy_json='[{"name":"hour_et_09","et_hours":[9],"up_max_buy_price":0.49,"down_max_buy_price":0.48}]',
    )
    bot = BTC5MinMakerBot(cfg)

    async def fake_resolve(http, through_window_start: int) -> None:
        return None

    async def fake_prices(*, window_start_ts: int, http) -> tuple[float, float]:
        return 100.0, 99.95

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
    assert result["size_usd"] == pytest.approx(9.9969, rel=1e-4)
    assert result["size_usd"] < cfg.stage3_max_trade_usd


def test_print_status_emits_stage_and_shadow_metadata(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg = MakerConfig(
        db_path=tmp_path / "btc5.db",
        capital_stage=3,
        bankroll_usd=20_000.0,
        risk_fraction=0.02,
        stage1_max_trade_usd=10.0,
        stage2_max_trade_usd=20.0,
        stage3_max_trade_usd=50.0,
    )
    bot = BTC5MinMakerBot(cfg)
    ws = current_window_start(time.time()) - (2 * 300)
    _seed_stage_history(bot, window_start_ts=ws, live_filled_rows=120, live_filled_pnl_usd=1.0, order_failed_rows=9)

    bot.print_status()
    payload = json.loads(capsys.readouterr().out)

    assert payload["capital_stage"] == 3
    assert payload["recommended_live_stage"] == 3
    assert payload["advantage_tier"] == "stage_3_live_ready"
    assert payload["probe_fresh_for_stage_upgrade"] is True
    assert payload["shadow_research_tiers"]["shadow_100"]["shadow_only"] is True
    assert payload["shadow_research_tiers"]["shadow_200"]["max_trade_usd"] == pytest.approx(200.0)


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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
    assert result["order_outcome_attribution"] == "cancel_before_fill"

    with bot.db._connect() as conn:
        row = conn.execute(
            "SELECT reason, order_status FROM window_trades WHERE window_start_ts = ?",
            (window_start_ts,),
        ).fetchone()
    assert row["order_status"] == "live_cancelled_unfilled"
    assert "order_outcome_attribution=cancel_before_fill" in (row["reason"] or "")


@pytest.mark.asyncio
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

    with bot.db._connect() as conn:
        row = conn.execute(
            "SELECT best_bid, best_ask, order_price, reason, order_status FROM window_trades WHERE window_start_ts = ?",
            (window_start_ts,),
        ).fetchone()
    assert row["best_bid"] == pytest.approx(0.49)
    assert row["best_ask"] == pytest.approx(0.50)
    assert row["order_price"] == pytest.approx(0.48)
    assert "post_only_retry" in (row["reason"] or "")
    assert "placement_failure_attribution=post_only_cross_failure" in (row["reason"] or "")
    assert row["order_status"] == "live_cancelled_unfilled"


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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

    with bot.db._connect() as conn:
        row = conn.execute(
            "SELECT reason, order_status FROM window_trades WHERE window_start_ts = ?",
            (window_start_ts,),
        ).fetchone()
    assert row["order_status"] == "skip_delta_too_small"
    assert "name=hour_et_09" in (row["reason"] or "")


@pytest.mark.asyncio
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
        cancel_seconds_before_close=2,
        maker_improve_ticks=1,
        enable_recent_regime_skew=True,
        recent_regime_fills=12,
        regime_min_fills_per_direction=5,
        regime_min_pnl_gap_usd=20.0,
        regime_weaker_direction_quote_ticks=0,
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

@pytest.mark.asyncio
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
        cancel_seconds_before_close=2,
        enable_probe_after_recent_loss=True,
        probe_recent_fills=4,
        probe_recent_min_pnl_usd=0.0,
        probe_quote_ticks=0,
        probe_up_max_buy_price=0.49,
        probe_down_max_buy_price=0.51,
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
    for idx in range(4):
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
    assert result["risk_mode"] == "probe"
    assert result["price"] == pytest.approx(0.48)

    with bot.db._connect() as conn:
        row = conn.execute(
            "SELECT order_price, reason, order_status FROM window_trades WHERE window_start_ts = ?",
            (window_start_ts,),
        ).fetchone()
    assert row["order_price"] == pytest.approx(0.48)
    assert "probe_recent_live_pnl" in (row["reason"] or "")
    assert row["order_status"] == "live_cancelled_unfilled"


@pytest.mark.asyncio
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
        cancel_seconds_before_close=2,
        daily_loss_limit_usd=5.0,
        enable_probe_after_daily_loss=True,
        enable_probe_after_recent_loss=False,
        probe_quote_ticks=0,
        probe_up_max_buy_price=0.49,
        probe_down_max_buy_price=0.51,
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
    result = await bot._process_window(window_start_ts=window_start_ts, http=ProbeBookHTTP())

    assert result["status"] == "live_cancelled_unfilled"
    assert result["risk_mode"] == "probe"

    with bot.db._connect() as conn:
        row = conn.execute(
            "SELECT order_price, reason, order_status FROM window_trades WHERE window_start_ts = ?",
            (window_start_ts,),
        ).fetchone()
    assert row["order_price"] == pytest.approx(0.48)
    assert "probe_daily_loss" in (row["reason"] or "")
    assert row["order_status"] == "live_cancelled_unfilled"


def test_status_summary_includes_intraday_live_summary(tmp_path: Path) -> None:
    cfg = MakerConfig(db_path=tmp_path / "btc5.db")
    bot = BTC5MinMakerBot(cfg)
    now = current_window_start(time.time())
    rows = [
        {
            "window_start_ts": now - 1800,
            "window_end_ts": now - 1500,
            "slug": market_slug_for_window(now - 1800),
            "decision_ts": now - 1510,
            "direction": "DOWN",
            "open_price": 100.0,
            "current_price": 99.95,
            "delta": -0.0005,
            "token_id": "tok-down",
            "best_bid": 0.47,
            "best_ask": 0.48,
            "order_price": 0.48,
            "trade_size_usd": 5.0,
            "shares": 10.42,
            "order_id": "fill-down",
            "order_status": "live_filled",
            "filled": 1,
            "reason": "seed_down",
            "resolved_side": "DOWN",
            "won": 1,
            "pnl_usd": 5.4184,
        },
        {
            "window_start_ts": now - 1500,
            "window_end_ts": now - 1200,
            "slug": market_slug_for_window(now - 1500),
            "decision_ts": now - 1210,
            "direction": "UP",
            "open_price": 100.0,
            "current_price": 100.05,
            "delta": 0.0005,
            "token_id": "tok-up",
            "best_bid": 0.49,
            "best_ask": 0.50,
            "order_price": 0.50,
            "trade_size_usd": 5.0,
            "shares": 10.0,
            "order_id": "fill-up",
            "order_status": "live_filled",
            "filled": 1,
            "reason": "seed_up",
            "resolved_side": "DOWN",
            "won": 0,
            "pnl_usd": -5.0,
        },
        {
            "window_start_ts": now - 1200,
            "window_end_ts": now - 900,
            "slug": market_slug_for_window(now - 1200),
            "decision_ts": now - 910,
            "direction": "UP",
            "open_price": 100.0,
            "current_price": 100.05,
            "delta": 0.0005,
            "token_id": "tok-up",
            "order_status": "skip_price_outside_guardrails",
            "reason": "seed_skip",
            "filled": 0,
        },
        {
            "window_start_ts": now - 900,
            "window_end_ts": now - 600,
            "slug": market_slug_for_window(now - 900),
            "decision_ts": now - 610,
            "direction": "UP",
            "open_price": 100.0,
            "current_price": 100.05,
            "delta": 0.0005,
            "token_id": "tok-up",
            "order_status": "live_order_failed",
            "reason": "placement_failure_attribution=order_placement_failure | seed_fail",
            "filled": 0,
        },
        {
            "window_start_ts": now - 600,
            "window_end_ts": now - 300,
            "slug": market_slug_for_window(now - 600),
            "decision_ts": now - 310,
            "direction": "UP",
            "open_price": 100.0,
            "current_price": 100.05,
            "delta": 0.0005,
            "token_id": "tok-up",
            "order_status": "live_cancelled_unfilled",
            "reason": "order_outcome_attribution=cancel_before_fill | seed_cancel",
            "filled": 0,
            "pnl_usd": 0.0,
            "won": 0,
        },
        {
            "window_start_ts": now - 300,
            "window_end_ts": now,
            "slug": market_slug_for_window(now - 300),
            "decision_ts": now - 10,
            "direction": "DOWN",
            "open_price": 100.0,
            "current_price": 99.95,
            "delta": -0.0005,
            "token_id": "tok-down",
            "order_status": "skip_no_book",
            "reason": "book_failure_attribution=no_book | seed_no_book",
            "filled": 0,
        },
    ]
    for row in rows:
        bot.db.upsert_window(row)

    status = bot.db.status_summary()
    intraday = status["intraday_live_summary"]

    assert intraday["filled_rows_today"] == 2
    assert intraday["filled_pnl_usd_today"] == pytest.approx(0.4184)
    assert intraday["win_rate_today"] == pytest.approx(0.5)
    assert intraday["recent_5_pnl_usd"] == pytest.approx(0.4184)
    assert intraday["recent_12_pnl_usd"] == pytest.approx(0.4184)
    assert intraday["skip_price_count"] == 1
    assert intraday["order_failed_count"] == 1
    assert intraday["cancelled_unfilled_count"] == 1
    assert intraday["order_failure_counts"]["order_placement_failure"] == 1
    assert intraday["order_failure_counts"]["cancel_before_fill"] == 1
    assert intraday["order_failure_counts"]["no_book"] == 1
    assert intraday["best_direction_today"]["label"] == "DOWN"
    assert intraday["best_price_bucket_today"]["label"] == "<0.49"
