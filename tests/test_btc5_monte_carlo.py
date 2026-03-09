from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts.btc5_monte_carlo import (
    GuardrailProfile,
    _dedupe_rows,
    build_candidate_profiles,
    build_summary,
    load_observed_rows_from_csv,
    load_observed_rows_from_db,
    row_matches_profile,
    run_monte_carlo,
    summarize_profile_history,
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


def test_load_live_filled_rows_ignores_non_fills(tmp_path: Path) -> None:
    db_path = tmp_path / "btc5.db"
    _write_test_db(db_path)

    rows = load_observed_rows_from_db(db_path)

    assert len(rows) == 13
    assert rows[0]["id"] == 1
    assert rows[-1]["id"] == 13
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
    assert summary["candidates"][0]["profile"]["name"] == summary["best_candidate"]["profile"]["name"]


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
    )
    rows = load_observed_rows_from_csv(csv_path, source="archive_csv:test")
    assert len(rows) == 2
    assert rows[0]["realized_pnl_usd"] == 5.4184
    assert rows[1]["realized_pnl_usd"] == 0.0
