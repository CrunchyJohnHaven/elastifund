from . import _btc_5min_maker_shared as _shared

globals().update({k: v for k, v in vars(_shared).items() if not k.startswith("__")})

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
    assert payload["shadow_research_tiers"]["shadow_300"]["max_trade_usd"] == pytest.approx(300.0)


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
            "size_adjustment_tags": ["size_adjustment=standard_risk_fraction", "size_reduced_vs_stage_cap"],
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
            "decision_reason_tags": ["decision=skip", "skip_reason=price_outside_guardrails"],
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
            "decision_reason_tags": ["decision=skip", "skip_reason=no_book"],
            "filled": 0,
        },
    ]
    for row in rows:
        bot.db.upsert_window(row)

    status = bot.db.status_summary()
    intraday = status["intraday_live_summary"]

    assert status["estimated_maker_rebate_usd"] == pytest.approx(0.0312, abs=1e-4)
    assert status["net_pnl_after_estimated_rebate_usd"] == pytest.approx(0.4496, abs=1e-4)
    assert intraday["filled_rows_today"] == 2
    assert intraday["filled_pnl_usd_today"] == pytest.approx(0.4184)
    assert intraday["estimated_maker_rebate_usd_today"] == pytest.approx(0.0312, abs=1e-4)
    assert intraday["net_pnl_after_estimated_rebate_usd_today"] == pytest.approx(0.4496, abs=1e-4)
    assert intraday["win_rate_today"] == pytest.approx(0.5)
    assert intraday["recent_5_pnl_usd"] == pytest.approx(0.4184)
    assert intraday["recent_5_estimated_maker_rebate_usd"] == pytest.approx(0.0312, abs=1e-4)
    assert intraday["recent_5_net_pnl_after_estimated_rebate_usd"] == pytest.approx(0.4496, abs=1e-4)
    assert intraday["recent_12_pnl_usd"] == pytest.approx(0.4184)
    assert intraday["recent_12_estimated_maker_rebate_usd"] == pytest.approx(0.0312, abs=1e-4)
    assert intraday["recent_12_net_pnl_after_estimated_rebate_usd"] == pytest.approx(0.4496, abs=1e-4)
    assert intraday["skip_price_count"] == 1
    assert intraday["order_failed_count"] == 1
    assert intraday["cancelled_unfilled_count"] == 1
    assert intraday["partial_fill_count"] == 0
    assert intraday["cancel_unknown_count"] == 0
    assert intraday["post_only_retry_attempts"] == 0
    assert intraday["decision_reason_counts"]["skip_reason=no_book"] == 1
    assert intraday["decision_reason_counts"]["skip_reason=price_outside_guardrails"] == 1
    assert intraday["order_failure_counts"]["order_placement_failure"] == 1
    assert intraday["order_failure_counts"]["cancel_before_fill"] == 1
    assert intraday["order_failure_counts"]["no_book"] == 1
    assert intraday["size_adjustment_counts"]["size_adjustment=standard_risk_fraction"] == 1
    assert intraday["size_adjustment_counts"]["size_reduced_vs_stage_cap"] == 1
    assert intraday["best_direction_today"]["label"] == "DOWN"
    assert intraday["best_price_bucket_today"]["label"] == "<0.49"


def test_recent_execution_drag_tracks_retry_and_cleanup_metrics(tmp_path: Path) -> None:
    cfg = MakerConfig(db_path=tmp_path / "btc5.db")
    bot = BTC5MinMakerBot(cfg)
    now = current_window_start(time.time())
    rows = [
        {
            "window_start_ts": now - 1200,
            "window_end_ts": now - 900,
            "slug": market_slug_for_window(now - 1200),
            "decision_ts": now - 910,
            "order_status": "live_order_failed",
            "reason": "placement_failure_attribution=post_only_cross_failure | post_only_retry_no_safe_price",
            "filled": 0,
        },
        {
            "window_start_ts": now - 900,
            "window_end_ts": now - 600,
            "slug": market_slug_for_window(now - 900),
            "decision_ts": now - 610,
            "order_status": "live_cancelled_unfilled",
            "reason": "post_only_retry direction=UP from=0.49 to=0.48 | order_outcome_attribution=cancel_before_fill",
            "filled": 0,
        },
        {
            "window_start_ts": now - 600,
            "window_end_ts": now - 300,
            "slug": market_slug_for_window(now - 600),
            "decision_ts": now - 310,
            "order_status": "live_partial_fill_cancelled",
            "reason": "post_only_retry direction=DOWN from=0.49 to=0.48 | order_outcome_attribution=partial_fill_then_cancel",
            "filled": 1,
        },
        {
            "window_start_ts": now - 300,
            "window_end_ts": now,
            "slug": market_slug_for_window(now - 300),
            "decision_ts": now - 10,
            "order_status": "live_cancel_unknown",
            "reason": "post_only_retry direction=UP from=0.49 to=0.48 | status=open",
            "filled": 0,
        },
    ]
    for row in rows:
        bot.db.upsert_window(row)

    drag = bot.db.recent_execution_drag(limit=10)

    assert drag["live_order_failed"] == 1
    assert drag["live_cancelled_unfilled"] == 1
    assert drag["live_partial_fill_cancelled"] == 1
    assert drag["live_cancel_unknown"] == 1
    assert drag["cleanup_cancel_count"] == 2
    assert drag["cleanup_unknown_count"] == 1
    assert drag["partial_fill_count"] == 1
    assert drag["partial_fill_rate"] == pytest.approx(1.0 / 3.0, rel=1e-6)
    assert drag["post_only_cross_failures"] == 1
    assert drag["post_only_retry_attempts"] == 4
    assert drag["post_only_retry_failures"] == 1
    assert drag["post_only_retry_successes"] == 3
    assert drag["order_failed_rate"] == pytest.approx(1.0 / 3.0, rel=1e-6)
