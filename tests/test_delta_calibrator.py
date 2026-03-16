from __future__ import annotations

import sqlite3
from pathlib import Path

from bot.delta_calibrator import calibrate_asset, run_calibration


def _make_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE window_trades (
                delta REAL,
                order_status TEXT,
                pnl_usd REAL,
                won INTEGER,
                created_at TEXT
            )
            """
        )
        conn.commit()


def _insert_rows(path: Path, rows: list[tuple[float, str, float, int]]) -> None:
    with sqlite3.connect(path) as conn:
        conn.executemany(
            """
            INSERT INTO window_trades (delta, order_status, pnl_usd, won, created_at)
            VALUES (?, ?, ?, ?, '2026-03-16T00:00:00Z')
            """,
            rows,
        )
        conn.commit()


def test_calibrate_asset_shrinks_toward_profitable_band(tmp_path: Path) -> None:
    db_path = tmp_path / "data" / "btc_5min_maker.db"
    _make_db(db_path)
    rows: list[tuple[float, str, float, int]] = []
    rows.extend([(0.0020, "live_filled", 2.0, 1)] * 30)
    rows.extend([(0.0024, "live_filled", 1.8, 1)] * 20)
    rows.extend([(0.0078, "live_filled", -2.2, 0)] * 25)
    rows.extend([(0.0084, "live_filled", -1.9, 0)] * 25)
    _insert_rows(db_path, rows)

    result = calibrate_asset(
        asset="btc",
        db_path=db_path,
        current_max_abs_delta=0.0060,
        current_min_delta=0.0003,
        max_fill_rows=300,
        max_window_rows=400,
        min_fill_rows=60,
        min_bin_fills=4,
        min_bin_win_rate=0.55,
        vol_multiplier=1.35,
    )

    assert result.status == "updated"
    assert result.reason == "volatility_and_profitability"
    assert result.profitable_band_lower is not None
    assert result.profitable_band_upper is not None
    assert result.recommended_max_abs_delta is not None
    assert result.recommended_min_delta is not None
    assert result.recommended_max_abs_delta < 0.0060
    assert result.profitable_band_upper < 0.0060
    assert 0.0 < result.recommended_min_delta < result.recommended_max_abs_delta


def test_run_calibration_writes_stage_and_asset_envs(tmp_path: Path) -> None:
    state_env = tmp_path / "state" / "btc5_capital_stage.env"
    state_env.parent.mkdir(parents=True, exist_ok=True)
    state_env.write_text("BTC5_MAX_ABS_DELTA=0.005\nBTC5_MIN_DELTA=0.0003\n", encoding="utf-8")

    btc_env = tmp_path / "config" / "btc5_strategy.env"
    eth_env = tmp_path / "config" / "eth5_strategy.env"
    btc_env.parent.mkdir(parents=True, exist_ok=True)
    btc_env.write_text("BTC5_MIN_BUY_PRICE=0.90\n", encoding="utf-8")
    eth_env.write_text("BTC5_MIN_BUY_PRICE=0.90\nBTC5_MAX_ABS_DELTA=0.009\n", encoding="utf-8")

    btc_db = tmp_path / "data" / "btc_5min_maker.db"
    eth_db = tmp_path / "data" / "eth_5min_maker.db"
    _make_db(btc_db)
    _make_db(eth_db)

    btc_rows = [(0.0042, "live_filled", 2.0, 1)] * 60 + [(0.0090, "live_filled", -1.8, 0)] * 40
    eth_rows = [(0.0014, "live_filled", 1.5, 1)] * 65 + [(0.0048, "live_filled", -1.3, 0)] * 35
    _insert_rows(btc_db, btc_rows)
    _insert_rows(eth_db, eth_rows)

    report = run_calibration(
        state_env_path=state_env,
        asset_db_paths={"btc": btc_db, "eth": eth_db},
        asset_env_paths={"btc": btc_env, "eth": eth_env},
        report_path=tmp_path / "data" / "delta_calibration_report.json",
        dry_run=False,
        min_fill_rows=80,
    )

    stage_text = state_env.read_text(encoding="utf-8")
    eth_text = eth_env.read_text(encoding="utf-8")

    assert "BTC5_MAX_ABS_DELTA=" in stage_text
    assert "BTC5_MIN_DELTA=" in stage_text
    assert "BTC5_PROBE_MAX_ABS_DELTA=" in stage_text
    assert "BTC5_MAX_ABS_DELTA=" in eth_text
    assert "BTC5_MIN_DELTA=" in eth_text
    assert "BTC5_PROBE_MAX_ABS_DELTA=" in eth_text

    assets = {row["asset"]: row for row in report["assets"]}
    assert "btc" in assets
    assert "eth" in assets
    assert assets["btc"]["recommended_max_abs_delta"] != assets["eth"]["recommended_max_abs_delta"]
