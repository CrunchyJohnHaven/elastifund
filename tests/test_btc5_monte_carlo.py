from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from scripts.btc5_monte_carlo import (
    GuardrailProfile,
    _dedupe_rows,
    build_capacity_stress_summary,
    build_candidate_profiles,
    build_summary,
    load_observed_rows_from_csv,
    load_observed_rows_from_db,
    row_matches_profile,
    run_monte_carlo,
    summarize_continuation_arr,
    summarize_profile_history,
)


ET_TZ = ZoneInfo("America/New_York")


def _et_window_ts(year: int, month: int, day: int, hour: int, minute: int) -> int:
    return int(
        datetime(year, month, day, hour, minute, tzinfo=ET_TZ)
        .astimezone(timezone.utc)
        .timestamp()
    )


def _write_test_db(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE window_trades (
                id INTEGER PRIMARY KEY,
                window_start_ts INTEGER,
                slug TEXT,
                direction TEXT,
                delta REAL,
                order_price REAL,
                trade_size_usd REAL,
                won INTEGER,
                pnl_usd REAL,
                order_status TEXT,
                updated_at TEXT
            )
            """
        )
        rows = [
            (1, 1773072000, "btc-updown-5m-1773072000", "DOWN", -0.00010, 0.48, 5.0, 1, 5.20, "live_filled", "2026-03-09T16:00:00Z"),
            (2, 1773072300, "btc-updown-5m-1773072300", "UP", 0.00008, 0.49, 5.0, 1, 5.10, "live_filled", "2026-03-09T16:05:00Z"),
            (3, 1773072600, "btc-updown-5m-1773072600", "UP", 0.00012, 0.50, 5.0, 0, -5.00, "live_filled", "2026-03-09T16:10:00Z"),
            (4, 1773072900, "btc-updown-5m-1773072900", "DOWN", -0.00009, 0.51, 5.0, 1, 4.80, "live_filled", "2026-03-09T16:15:00Z"),
            (5, 1773073200, "btc-updown-5m-1773073200", "UP", 0.00018, 0.49, 5.0, 0, -5.00, "live_filled", "2026-03-09T16:20:00Z"),
            (6, 1773073500, "btc-updown-5m-1773073500", "DOWN", -0.00007, 0.47, 5.0, 1, 5.60, "live_filled", "2026-03-09T16:25:00Z"),
            (7, 1773073800, "btc-updown-5m-1773073800", "DOWN", -0.00011, 0.48, 5.0, 1, 5.40, "live_filled", "2026-03-09T16:30:00Z"),
            (8, 1773074100, "btc-updown-5m-1773074100", "UP", 0.00009, 0.49, 5.0, 1, 5.00, "live_filled", "2026-03-09T16:35:00Z"),
            (9, 1773074400, "btc-updown-5m-1773074400", "DOWN", -0.00013, 0.50, 5.0, 0, -5.00, "live_filled", "2026-03-09T16:40:00Z"),
            (10, 1773074700, "btc-updown-5m-1773074700", "UP", 0.00006, 0.48, 5.0, 1, 5.20, "live_filled", "2026-03-09T16:45:00Z"),
            (11, 1773075000, "btc-updown-5m-1773075000", "UP", 0.00005, 0.49, 5.0, 1, 5.30, "live_filled", "2026-03-09T16:50:00Z"),
            (12, 1773075300, "btc-updown-5m-1773075300", "DOWN", -0.00004, 0.49, 5.0, 1, 5.10, "live_filled", "2026-03-09T16:55:00Z"),
            (13, 1773075600, "btc-updown-5m-1773075600", "UP", 0.00010, 0.52, 5.0, 0, -5.00, "skip_price_outside_guardrails", "2026-03-09T17:00:00Z"),
        ]
        conn.executemany(
            """
            INSERT INTO window_trades (
                id, window_start_ts, slug, direction, delta, order_price, trade_size_usd, won, pnl_usd, order_status, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def _write_regime_loss_test_db(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE window_trades (
                id INTEGER PRIMARY KEY,
                window_start_ts INTEGER,
                slug TEXT,
                direction TEXT,
                delta REAL,
                order_price REAL,
                trade_size_usd REAL,
                won INTEGER,
                pnl_usd REAL,
                order_status TEXT,
                updated_at TEXT
            )
            """
        )
        rows = [
            (1, _et_window_ts(2026, 3, 9, 9, 0), "btc-open-1", "DOWN", -0.00004, 0.49, 5.0, 0, -5.00, "live_filled", "2026-03-09T14:00:00Z"),
            (2, _et_window_ts(2026, 3, 9, 9, 5), "btc-open-2", "DOWN", -0.00004, 0.50, 0.0, 0, 0.0, "live_order_failed", "2026-03-09T14:05:00Z"),
            (3, _et_window_ts(2026, 3, 9, 9, 10), "btc-open-3", "DOWN", -0.00004, 0.49, 5.0, 0, -4.90, "live_filled", "2026-03-09T14:10:00Z"),
            (4, _et_window_ts(2026, 3, 9, 9, 15), "btc-open-4", "UP", 0.00006, 0.48, 5.0, 1, 5.10, "live_filled", "2026-03-09T14:15:00Z"),
            (5, _et_window_ts(2026, 3, 9, 12, 0), "btc-midday-1", "DOWN", -0.00008, 0.48, 5.0, 1, 5.40, "live_filled", "2026-03-09T17:00:00Z"),
            (6, _et_window_ts(2026, 3, 9, 12, 5), "btc-midday-2", "DOWN", -0.00007, 0.48, 5.0, 1, 5.60, "live_filled", "2026-03-09T17:05:00Z"),
            (7, _et_window_ts(2026, 3, 9, 12, 10), "btc-midday-3", "UP", 0.00007, 0.49, 5.0, 1, 5.00, "live_filled", "2026-03-09T17:10:00Z"),
            (8, _et_window_ts(2026, 3, 9, 12, 15), "btc-midday-4", "DOWN", -0.00005, 0.49, 5.0, 1, 5.20, "live_filled", "2026-03-09T17:15:00Z"),
            (9, _et_window_ts(2026, 3, 9, 15, 0), "btc-late-1", "DOWN", -0.00006, 0.49, 0.0, 0, 0.0, "live_cancelled_unfilled", "2026-03-09T20:00:00Z"),
        ]
        conn.executemany(
            """
            INSERT INTO window_trades (
                id, window_start_ts, slug, direction, delta, order_price, trade_size_usd, won, pnl_usd, order_status, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def test_load_live_filled_rows_ignores_non_fills(tmp_path: Path) -> None:
    db_path = tmp_path / "btc5.db"
    _write_test_db(db_path)

    rows = load_observed_rows_from_db(db_path)

    assert len(rows) == 13
    assert rows[0]["id"] == 1
    assert rows[-1]["id"] == 13
    assert rows[0]["et_hour"] == 12
    assert rows[0]["session_name"] == "midday_et"
    assert sum(1 for row in rows if row["order_status"] == "live_filled") == 12


def test_row_matches_profile_applies_directional_caps() -> None:
    profile = GuardrailProfile(
        name="guarded",
        max_abs_delta=0.00015,
        up_max_buy_price=0.49,
        down_max_buy_price=0.51,
    )
    assert row_matches_profile({"direction": "UP", "abs_delta": 0.00010, "order_price": 0.49}, profile) is True
    assert row_matches_profile({"direction": "UP", "abs_delta": 0.00010, "order_price": 0.50}, profile) is False
    assert row_matches_profile({"direction": "DOWN", "abs_delta": 0.00016, "order_price": 0.49}, profile) is False


def test_summarize_profile_history_counts_only_matching_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "btc5.db"
    _write_test_db(db_path)
    rows = load_observed_rows_from_db(db_path)
    profile = GuardrailProfile(
        name="current",
        max_abs_delta=0.00015,
        up_max_buy_price=0.49,
        down_max_buy_price=0.51,
    )

    history = summarize_profile_history(rows, profile)

    assert history["baseline_window_rows"] == 13
    assert history["baseline_live_filled_rows"] == 12
    assert history["replay_window_rows"] == 10
    assert history["replay_attempt_rows"] == 10
    assert history["replay_live_filled_rows"] == 10
    assert history["replay_live_filled_pnl_usd"] == 41.7


def test_run_monte_carlo_is_deterministic_for_same_seed(tmp_path: Path) -> None:
    db_path = tmp_path / "btc5.db"
    _write_test_db(db_path)
    rows = load_observed_rows_from_db(db_path)
    profile = GuardrailProfile(
        name="current",
        max_abs_delta=0.00015,
        up_max_buy_price=0.49,
        down_max_buy_price=0.51,
    )

    first = run_monte_carlo(
        rows,
        profile,
        paths=250,
        horizon_trades=12,
        block_size=3,
        loss_limit_usd=10.0,
        seed=7,
    )
    second = run_monte_carlo(
        rows,
        profile,
        paths=250,
        horizon_trades=12,
        block_size=3,
        loss_limit_usd=10.0,
        seed=7,
    )

    assert first == second
    assert first["profit_probability"] > 0.8
    assert first["sampling_dimensions"] == [
        "session_name",
        "direction",
        "price_bucket",
        "delta_bucket",
    ]
    assert first["capital_efficiency"] > 0.0
    assert "session_tail_contribution" in first


def test_summarize_continuation_arr_emits_percentage_metrics(tmp_path: Path) -> None:
    db_path = tmp_path / "btc5.db"
    _write_test_db(db_path)
    rows = load_observed_rows_from_db(db_path)
    profile = GuardrailProfile(
        name="current",
        max_abs_delta=0.00015,
        up_max_buy_price=0.49,
        down_max_buy_price=0.51,
    )
    history = summarize_profile_history(rows, profile)
    monte_carlo = run_monte_carlo(
        rows,
        profile,
        paths=250,
        horizon_trades=12,
        block_size=3,
        loss_limit_usd=10.0,
        seed=7,
    )
    continuation = summarize_continuation_arr(historical=history, monte_carlo=monte_carlo)
    assert continuation["metric_name"] == "continuation_arr_pct"
    assert continuation["historical_arr_pct"] > 0.0
    assert continuation["median_arr_pct"] > 0.0


def test_build_candidate_profiles_keeps_current_and_runtime_profiles(tmp_path: Path) -> None:
    db_path = tmp_path / "btc5.db"
    _write_test_db(db_path)
    rows = load_observed_rows_from_db(db_path)
    current = GuardrailProfile("current_live_profile", 0.00015, 0.49, 0.51, "current")
    runtime = GuardrailProfile("runtime_recommended", 0.00015, 0.49, 0.51, "runtime")

    profiles = build_candidate_profiles(
        rows,
        current_live_profile=current,
        runtime_recommended_profile=runtime,
        top_grid_candidates=3,
        min_replay_fills=8,
    )

    names = [profile.name for profile in profiles]
    assert "baseline_all_live_fills" in names
    assert "current_live_profile" in names
    assert len(profiles) >= 3


def test_build_summary_ranks_candidates(tmp_path: Path) -> None:
    db_path = tmp_path / "btc5.db"
    _write_test_db(db_path)
    rows = load_observed_rows_from_db(db_path)
    current = GuardrailProfile("current_live_profile", 0.00015, 0.49, 0.51, "current")
    runtime = GuardrailProfile("runtime_recommended", 0.00015, 0.49, 0.51, "runtime")

    summary = build_summary(
        rows=rows,
        db_path=db_path,
        current_live_profile=current,
        runtime_recommended_profile=runtime,
        paths=250,
        horizon_trades=12,
        block_size=3,
        loss_limit_usd=10.0,
        seed=11,
        top_grid_candidates=3,
        min_replay_fills=8,
    )

    assert summary["best_candidate"] is not None
    assert summary["best_vs_current"] is not None
    assert summary["best_candidate"]["monte_carlo"]["median_total_pnl_usd"] >= 0.0
    assert "continuation" in summary["best_candidate"]
    assert "median_arr_pct_delta" in summary["best_vs_current"]
    assert summary["candidates"][0]["profile"]["name"] == summary["best_candidate"]["profile"]["name"]
    capacity_stress = summary["capacity_stress_summary"]
    assert capacity_stress["metric_name"] == "capacity_stress_summary"
    assert capacity_stress["recommended_reference"] == "best_candidate"
    assert "current_live_profile" in capacity_stress["profiles"]
    assert "best_candidate" in capacity_stress["profiles"]
    assert capacity_stress["profiles"]["current_live_profile"]["trade_sizes_usd"] == [5.0, 10.0, 20.0, 50.0, 100.0, 200.0]
    assert capacity_stress["profiles"]["current_live_profile"]["current_base_sweep"]["trade_size_usd"] == 5.0
    assert capacity_stress["profiles"]["current_live_profile"]["stage_trade_sizes_usd"] == {
        "stage_1": 10.0,
        "stage_2": 20.0,
        "stage_3": 50.0,
    }
    assert capacity_stress["profiles"]["current_live_profile"]["shadow_trade_sizes_usd"] == {
        "shadow_100": 100.0,
        "shadow_200": 200.0,
    }
    assert capacity_stress["profiles"]["current_live_profile"]["baseline_execution_drag"]["matched_live_filled_rows"] == 10


def test_build_capacity_stress_summary_emits_expected_size_sweeps(tmp_path: Path) -> None:
    db_path = tmp_path / "btc5.db"
    _write_test_db(db_path)
    rows = load_observed_rows_from_db(db_path)
    profile = GuardrailProfile(
        name="current",
        max_abs_delta=0.00015,
        up_max_buy_price=0.49,
        down_max_buy_price=0.51,
    )
    historical = summarize_profile_history(rows, profile)
    monte_carlo = run_monte_carlo(
        rows,
        profile,
        paths=250,
        horizon_trades=12,
        block_size=3,
        loss_limit_usd=10.0,
        seed=7,
    )
    continuation = summarize_continuation_arr(historical=historical, monte_carlo=monte_carlo)

    stress = build_capacity_stress_summary(
        rows=rows,
        profile=profile,
        historical=historical,
        monte_carlo=monte_carlo,
        continuation=continuation,
        paths=250,
        horizon_trades=12,
        block_size=3,
        loss_limit_usd=10.0,
        seed=7,
    )

    assert stress["metric_name"] == "capacity_stress_summary"
    assert stress["configured_current_trade_size_usd"] == 5.0
    assert stress["observed_avg_trade_size_usd"] == 5.0
    assert stress["trade_sizes_usd"] == [5.0, 10.0, 20.0, 50.0, 100.0, 200.0]
    assert stress["reference_trade_size_usd"] == 5.0
    assert stress["reference_trade_size_source"] == "configured_current_trade_size_usd"
    assert stress["current_base_trade_size_usd"] == 5.0
    assert stress["stage_trade_sizes_usd"] == {
        "stage_1": 10.0,
        "stage_2": 20.0,
        "stage_3": 50.0,
    }
    assert stress["shadow_trade_sizes_usd"] == {
        "shadow_100": 100.0,
        "shadow_200": 200.0,
    }
    assert stress["current_base_sweep"]["trade_size_usd"] == 5.0
    assert stress["current_base_sweep"]["sizing_track"] == "current_base"
    assert [item["capital_stage"] for item in stress["stage_sweeps"]] == [1, 2, 3]
    assert [item["shadow_label"] for item in stress["shadow_sweeps"]] == ["shadow_100", "shadow_200"]
    assert stress["baseline_execution_drag"]["matched_rows"] == 10
    assert stress["baseline_execution_drag"]["post_only_retry_failure_rate"] == 0.0
    sweeps = stress["size_sweeps"]
    assert sweeps[0]["trade_size_usd"] == 5.0
    assert sweeps[0]["sizing_track"] == "current_base"
    assert sweeps[1]["trade_size_usd"] == 10.0
    assert sweeps[1]["sizing_track"] == "live_stage"
    assert sweeps[1]["capital_stage"] == 1
    assert sweeps[1]["expected_same_level_fill_ratio"] == pytest.approx(0.5, abs=1e-4)
    assert sweeps[1]["expected_fill_probability"] == pytest.approx(0.7121, abs=1e-4)
    assert sweeps[1]["expected_one_tick_worse_fill_ratio"] == pytest.approx(0.2121, abs=1e-4)
    assert sweeps[1]["expected_fill_retention_ratio"] == pytest.approx(0.7121, abs=1e-4)
    assert sweeps[1]["expected_post_only_retry_failure_rate"] == pytest.approx(0.2879, abs=1e-4)
    assert sweeps[2]["expected_fill_retention_ratio"] == pytest.approx(0.4750, abs=1e-4)
    assert sweeps[3]["expected_fill_retention_ratio"] == pytest.approx(0.2708, abs=1e-4)
    assert sweeps[4]["expected_fill_retention_ratio"] == pytest.approx(0.1775, abs=1e-4)
    assert sweeps[5]["expected_fill_retention_ratio"] == pytest.approx(0.1175, abs=1e-4)
    assert sweeps[4]["sizing_track"] == "shadow"
    assert sweeps[4]["shadow_label"] == "shadow_100"
    assert "loss_hit_probability_impact" in sweeps[2]
    assert "expected_daily_loss_hit_probability" in sweeps[2]
    assert "expected_non_positive_path_probability" in sweeps[2]
    assert "expected_capital_efficiency" in sweeps[2]
    assert "expected_p95_max_drawdown_usd" in sweeps[2]
    assert "p95_drawdown_impact_usd" in sweeps[2]
    assert "execution_drag_summary" in sweeps[2]
    assert "regime_size_sensitivity" in sweeps[2]
    assert sweeps[2]["session_size_sensitivity"][0]["session_name"] == "midday_et"
    assert stress["stage_sweeps"][0]["trade_size_usd"] == 10.0
    assert len(stress["edge_tier_weighted_stage_sweeps"]) == 3
    assert stress["edge_tier_weighted_stage_sweeps"][0]["sizing_track"] == "edge_tier_weighted"


def test_build_capacity_stress_summary_keeps_configured_current_cap_as_reference(tmp_path: Path) -> None:
    db_path = tmp_path / "btc5.db"
    _write_test_db(db_path)
    rows = load_observed_rows_from_db(db_path)
    rows[0]["trade_size_usd"] = 2.5
    profile = GuardrailProfile(
        name="current",
        max_abs_delta=0.00015,
        up_max_buy_price=0.49,
        down_max_buy_price=0.51,
    )
    historical = summarize_profile_history(rows, profile)
    monte_carlo = run_monte_carlo(
        rows,
        profile,
        paths=250,
        horizon_trades=12,
        block_size=3,
        loss_limit_usd=10.0,
        seed=7,
    )
    continuation = summarize_continuation_arr(historical=historical, monte_carlo=monte_carlo)

    stress = build_capacity_stress_summary(
        rows=rows,
        profile=profile,
        historical=historical,
        monte_carlo=monte_carlo,
        continuation=continuation,
        current_trade_size_usd=5.0,
        paths=250,
        horizon_trades=12,
        block_size=3,
        loss_limit_usd=10.0,
        seed=7,
    )

    assert stress["configured_current_trade_size_usd"] == 5.0
    assert stress["observed_avg_trade_size_usd"] == pytest.approx(4.75, abs=1e-4)
    assert stress["reference_trade_size_usd"] == 5.0
    assert stress["reference_trade_size_source"] == "configured_current_trade_size_usd"
    assert stress["trade_sizes_usd"][0] == 5.0


def test_dedupe_rows_prefers_higher_priority_and_newer_update() -> None:
    rows = [
        {
            "slug": "btc-updown-5m-1",
            "window_start_ts": 1,
            "id": 1,
            "source": "archive_csv:older",
            "source_priority": 2,
            "updated_at": "2026-03-09T17:00:00Z",
        },
        {
            "slug": "btc-updown-5m-1",
            "window_start_ts": 1,
            "id": 2,
            "source": "sqlite:btc_5min_maker.db",
            "source_priority": 3,
            "updated_at": "2026-03-09T17:05:00Z",
        },
    ]
    deduped = _dedupe_rows(rows)
    assert len(deduped) == 1
    assert deduped[0]["source"] == "sqlite:btc_5min_maker.db"


def test_load_observed_rows_from_csv_normalizes_fields(tmp_path: Path) -> None:
    csv_path = tmp_path / "rows.csv"
    csv_path.write_text(
        "id,window_start_ts,slug,direction,delta,order_price,trade_size_usd,won,pnl_usd,order_status,updated_at\n"
        "1,1773078000,btc-updown-5m-1773078000,DOWN,-0.00012,0.48,5.0,1,5.4184,live_filled,2026-03-09T17:45:00Z\n"
        "2,1773078300,btc-updown-5m-1773078300,UP,0.00011,0.52,0,0,0,skip_price_outside_guardrails,2026-03-09T17:50:00Z\n"
        "3,1773078600,btc-updown-5m-1773078600,DOWN,-0.00009,0.49,2.5,1,2.1042,live_partial_fill_cancelled,2026-03-09T17:55:00Z\n"
    )
    rows = load_observed_rows_from_csv(csv_path, source="archive_csv:test")
    assert len(rows) == 3
    assert rows[0]["realized_pnl_usd"] == 5.4184
    assert rows[1]["realized_pnl_usd"] == 0.0
    assert rows[2]["realized_pnl_usd"] == 2.1042


def test_summarize_profile_history_counts_partial_live_fills(tmp_path: Path) -> None:
    csv_path = tmp_path / "partial_rows.csv"
    csv_path.write_text(
        "id,window_start_ts,slug,direction,delta,order_price,trade_size_usd,won,pnl_usd,order_status,updated_at\n"
        "1,1773078000,btc-updown-5m-1773078000,DOWN,-0.00010,0.48,2.5,1,2.10,live_partial_fill_cancelled,2026-03-09T17:45:00Z\n"
    )
    rows = load_observed_rows_from_csv(csv_path, source="archive_csv:test")
    profile = GuardrailProfile(
        name="current",
        max_abs_delta=0.00015,
        up_max_buy_price=0.49,
        down_max_buy_price=0.51,
    )

    history = summarize_profile_history(rows, profile)

    assert history["baseline_live_filled_rows"] == 1
    assert history["replay_live_filled_rows"] == 1
    assert history["replay_live_filled_pnl_usd"] == 2.1


def test_run_monte_carlo_emits_regime_sampling_summary(tmp_path: Path) -> None:
    db_path = tmp_path / "btc5_regime.db"
    _write_regime_loss_test_db(db_path)
    rows = load_observed_rows_from_db(db_path)
    profile = GuardrailProfile(
        name="current",
        max_abs_delta=0.00015,
        up_max_buy_price=0.51,
        down_max_buy_price=0.51,
    )

    summary = run_monte_carlo(
        rows,
        profile,
        paths=200,
        horizon_trades=9,
        block_size=2,
        loss_limit_usd=10.0,
        seed=17,
    )

    assert summary["sampling_dimensions"] == [
        "session_name",
        "direction",
        "price_bucket",
        "delta_bucket",
    ]
    assert summary["regime_sampling_summary"]
    regime_keys = {item["regime_key"] for item in summary["regime_sampling_summary"]}
    assert "open_et|DOWN|0.49_to_0.51|le_0.00005" in regime_keys
    assert any(item["session_name"] == "midday_et" for item in summary["regime_sampling_summary"])
    assert summary["avg_order_failed_trades"] > 0.0


def test_run_monte_carlo_models_loss_cluster_shocks(tmp_path: Path) -> None:
    db_path = tmp_path / "btc5_regime.db"
    _write_regime_loss_test_db(db_path)
    rows = load_observed_rows_from_db(db_path)
    profile = GuardrailProfile(
        name="current",
        max_abs_delta=0.00015,
        up_max_buy_price=0.51,
        down_max_buy_price=0.51,
    )

    summary = run_monte_carlo(
        rows,
        profile,
        paths=200,
        horizon_trades=9,
        block_size=2,
        loss_limit_usd=10.0,
        seed=17,
    )

    assert summary["loss_cluster_scenarios"]
    assert summary["loss_cluster_scenarios"][0]["session_name"] == "open_et"
    assert summary["loss_cluster_scenarios"][0]["regime_key"] == "open_et|DOWN|0.49_to_0.51|le_0.00005"
    assert summary["loss_cluster_shock_hit_probability"] > 0.0
    assert summary["daily_loss_hit_probability"] >= summary["loss_limit_hit_probability"]
    assert summary["session_tail_contribution"]
    assert summary["session_tail_contribution"][0]["session_name"] == "open_et"
