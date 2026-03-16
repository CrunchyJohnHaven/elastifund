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
            # Non-skip row should never be counted.
            (1, 1773072000, "btc-updown-5m-1773072000", "DOWN", -0.00010, 0.87, 0.88, "live_filled", "DOWN", 5.0),
            # skip_delta_too_large: one win and one loss -> WR 0.5, pnl/trade +0.1
            (2, 1773072300, "btc-updown-5m-1773072300", "DOWN", -0.00012, 0.48, 0.50, "skip_delta_too_large", "DOWN", 0.0),
            (3, 1773072600, "btc-updown-5m-1773072600", "UP", 0.00012, 0.48, 0.50, "skip_delta_too_large", "DOWN", 0.0),
            # skip_price_outside_guardrails: strong winner.
            (4, 1773072900, "btc-updown-5m-1773072900", "UP", 0.00020, 0.19, 0.20, "skip_price_outside_guardrails", "UP", 0.0),
            # skip_bad_book row is invalid due to missing ask and should be ignored.
            (5, 1773073200, "btc-updown-5m-1773073200", "DOWN", -0.00008, None, None, "skip_bad_book", "DOWN", 0.0),
            # Invalid resolved side should be ignored even though not null.
            (6, 1773073500, "btc-updown-5m-1773073500", "DOWN", -0.00011, 0.59, 0.60, "skip_shadow_only", "FLAT", 0.0),
            # direction missing should fallback to delta sign -> UP and win.
            (7, 1773073800, "btc-updown-5m-1773073800", None, 0.00009, 0.29, 0.30, "skip_toxic_order_flow", "UP", 0.0),
            # Zero-delta with missing direction is invalid and should be ignored.
            (8, 1773074100, "btc-updown-5m-1773074100", None, 0.0, 0.49, 0.50, "skip_toxic_order_flow", "UP", 0.0),
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


def _table_by_reason(report: dict) -> dict[str, dict]:
    return {row["skip_reason"]: row for row in report["table"]}


def test_counterfactual_report_groups_and_scores_skip_reasons(tmp_path: Path) -> None:
    db_path = tmp_path / "btc_5min_maker.db"
    _write_counterfactual_db(db_path)

    report = build_counterfactual_report(db_paths=[db_path])

    by_reason = _table_by_reason(report)
    assert set(by_reason) == {
        "skip_delta_too_large",
        "skip_price_outside_guardrails",
        "skip_toxic_order_flow",
    }
    assert report["raw_skip_rows_scanned"] == 7
    assert report["invalid_rows_ignored"] == 3
    assert report["invalid_rows_by_reason"]["skip_bad_book"] == 1
    assert report["invalid_rows_by_reason"]["skip_shadow_only"] == 1
    assert report["invalid_rows_by_reason"]["skip_toxic_order_flow"] == 1

    delta_bucket = by_reason["skip_delta_too_large"]
    assert delta_bucket["count"] == 2
    assert delta_bucket["counterfactual_WR"] == 0.5
    assert delta_bucket["counterfactual_PnL_per_trade"] == 0.1
    assert delta_bucket["verdict"] == "RELAX"

    price_bucket = by_reason["skip_price_outside_guardrails"]
    assert price_bucket["count"] == 1
    assert price_bucket["counterfactual_WR"] == 1.0
    assert price_bucket["counterfactual_PnL_per_trade"] == 0.8
    assert price_bucket["verdict"] == "RELAX"

    toxic_bucket = by_reason["skip_toxic_order_flow"]
    assert toxic_bucket["count"] == 1
    assert toxic_bucket["counterfactual_WR"] == 1.0
    assert toxic_bucket["counterfactual_PnL_per_trade"] == 0.7
    assert toxic_bucket["verdict"] == "RELAX"

    assert report["overall"]["count"] == 4
    assert report["overall"]["counterfactual_WR"] == 0.75
    assert report["overall"]["counterfactual_PnL_per_trade"] == 0.425


def test_counterfactual_report_marks_negative_skip_reason_as_tighten(tmp_path: Path) -> None:
    db_path = tmp_path / "eth_5min_maker.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE window_trades (
                id INTEGER PRIMARY KEY,
                order_status TEXT,
                direction TEXT,
                best_ask REAL,
                delta REAL,
                resolved_side TEXT
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO window_trades (id, order_status, direction, best_ask, delta, resolved_side)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (1, "skip_midpoint_kill_zone", "UP", 0.90, None, "DOWN"),
                (2, "skip_midpoint_kill_zone", "UP", 0.70, None, "DOWN"),
                (3, "skip_neutral", "DOWN", 0.60, None, "DOWN"),
                (4, "skip_neutral", "UP", 0.40, None, "DOWN"),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    report = build_counterfactual_report(db_paths=[db_path])
    by_reason = _table_by_reason(report)

    midpoint = by_reason["skip_midpoint_kill_zone"]
    assert midpoint["count"] == 2
    assert midpoint["counterfactual_WR"] == 0.0
    assert midpoint["counterfactual_PnL_per_trade"] == -0.8
    assert midpoint["verdict"] == "TIGHTEN"

    neutral = by_reason["skip_neutral"]
    assert neutral["count"] == 2
    assert neutral["counterfactual_PnL_per_trade"] == 0.0
    assert neutral["verdict"] == "KEEP"
