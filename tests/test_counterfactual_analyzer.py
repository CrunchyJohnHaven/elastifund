from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts.counterfactual_analyzer import build_counterfactual_report


def _write_counterfactual_db(db_path: Path) -> None:
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
                best_bid REAL,
                best_ask REAL,
                order_status TEXT,
                resolved_side TEXT,
                trade_size_usd REAL
            )
            """
        )
        rows = [
            # Seed row used for last-known-ask fallback on later skip_bad_book rows.
            (1, 1773072000, "btc-updown-5m-1773072000", "DOWN", -0.00010, 0.87, 0.88, "live_filled", "DOWN", 5.0),
            # Counterfactual win and loss in the same skip reason bucket.
            (2, 1773072300, "btc-updown-5m-1773072300", "DOWN", -0.00012, 0.48, 0.50, "skip_delta_too_large", "DOWN", 0.0),
            (3, 1773072600, "btc-updown-5m-1773072600", "UP", 0.00012, 0.48, 0.50, "skip_delta_too_large", "DOWN", 0.0),
            # Strong win in another skip bucket.
            (4, 1773072900, "btc-updown-5m-1773072900", "UP", 0.00020, 0.19, 0.20, "skip_price_outside_guardrails", "UP", 0.0),
            # Bad book row has no ask and must fallback to the prior directional ask.
            (5, 1773073200, "btc-updown-5m-1773073200", "DOWN", -0.00008, None, None, "skip_bad_book", "DOWN", 0.0),
        ]
        conn.executemany(
            """
            INSERT INTO window_trades (
                id, window_start_ts, slug, direction, delta, best_bid, best_ask, order_status, resolved_side, trade_size_usd
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def test_counterfactual_report_groups_skip_reasons(tmp_path: Path) -> None:
    db_path = tmp_path / "btc_5min_maker.db"
    _write_counterfactual_db(db_path)

    report = build_counterfactual_report(
        db_paths=[db_path],
        trade_size_usd=5.0,
        use_last_known_ask_for_bad_book=False,
        enable_binance_backfill=False,
        binance_timeout_seconds=1.0,
    )

    assert report["skip_windows_analyzed"] == 4
    by_reason = report["by_skip_reason"]
    assert set(by_reason.keys()) == {
        "skip_bad_book",
        "skip_delta_too_large",
        "skip_price_outside_guardrails",
    }

    delta_bucket = by_reason["skip_delta_too_large"]
    assert delta_bucket["simulated_trades"] == 2
    assert delta_bucket["wins"] == 1
    assert delta_bucket["losses"] == 1
    assert delta_bucket["win_rate"] == 0.5
    assert delta_bucket["pnl_usd_total"] == 0.0

    price_bucket = by_reason["skip_price_outside_guardrails"]
    assert price_bucket["simulated_trades"] == 1
    assert price_bucket["wins"] == 1
    assert price_bucket["pnl_usd_total"] == 20.0

    bad_book_bucket = by_reason["skip_bad_book"]
    assert bad_book_bucket["simulated_trades"] == 0


def test_counterfactual_report_uses_last_known_ask_for_bad_book(tmp_path: Path) -> None:
    db_path = tmp_path / "btc_5min_maker.db"
    _write_counterfactual_db(db_path)

    report = build_counterfactual_report(
        db_paths=[db_path],
        trade_size_usd=5.0,
        use_last_known_ask_for_bad_book=True,
        enable_binance_backfill=False,
        binance_timeout_seconds=1.0,
    )

    bad_book_bucket = report["by_skip_reason"]["skip_bad_book"]
    assert bad_book_bucket["simulated_trades"] == 1
    assert bad_book_bucket["wins"] == 1
    assert bad_book_bucket["win_rate"] == 1.0
    # Fallback uses the latest directional ask seen before this window (0.50 here).
    assert bad_book_bucket["pnl_usd_total"] == 5.0
    assert bad_book_bucket["ask_source_counts"]["last_known_directional_ask"] == 1
