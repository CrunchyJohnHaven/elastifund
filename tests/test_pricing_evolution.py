from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bot.pricing_evolution import MAX_BUY_CAP, MAX_RISK_FRACTION, MIN_BUY_FLOOR, run_pricing_evolution


def _create_window_trades_table(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE window_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            direction TEXT,
            order_price REAL,
            pnl_usd REAL,
            won INTEGER,
            delta REAL,
            created_at TEXT,
            order_status TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def test_pricing_evolution_promotes_bounded_genome(tmp_path: Path) -> None:
    db_path = tmp_path / "btc5.db"
    overrides_path = tmp_path / "autoresearch_overrides.json"
    _create_window_trades_table(db_path)

    now = datetime.now(timezone.utc)
    rows = [
        ("DOWN", 0.91, 0.60, 1, 0.0030, (now - timedelta(minutes=50)).isoformat(), "live_filled"),
        ("UP", 0.90, 0.50, 1, 0.0020, (now - timedelta(minutes=45)).isoformat(), "live_filled"),
        ("DOWN", 0.88, 0.80, 1, 0.0010, (now - timedelta(minutes=40)).isoformat(), "live_filled"),
        ("UP", 0.96, -0.40, 0, 0.0065, (now - timedelta(minutes=35)).isoformat(), "live_filled"),
        ("DOWN", 0.95, -0.20, 0, 0.0040, (now - timedelta(minutes=30)).isoformat(), "live_filled"),
    ]
    conn = sqlite3.connect(db_path)
    conn.executemany(
        """
        INSERT INTO window_trades(direction, order_price, pnl_usd, won, delta, created_at, order_status)
        VALUES (?,?,?,?,?,?,?)
        """,
        rows,
    )
    conn.commit()
    conn.close()

    result = run_pricing_evolution(
        db_path=db_path,
        overrides_path=overrides_path,
        lookback_hours=24,
        mutation_count=6,
        rng_seed=42,
    )

    assert result["status"] == "promoted"
    assert result["mutation_count"] == 6
    assert result["replay_rows"] == 5

    promoted = json.loads(overrides_path.read_text())
    assert promoted["promotion_stage"] == "validated"
    assert isinstance(promoted.get("lineage"), list)
    assert len(promoted["lineage"]) >= 1

    params = promoted["params"]
    assert params["BTC5_MIN_BUY_PRICE"] >= MIN_BUY_FLOOR
    assert params["BTC5_DOWN_MAX_BUY_PRICE"] <= MAX_BUY_CAP
    assert params["BTC5_UP_MAX_BUY_PRICE"] <= MAX_BUY_CAP
    assert params["BTC5_RISK_FRACTION"] <= MAX_RISK_FRACTION
    assert params["BTC5_DOWN_MAX_BUY_PRICE"] >= params["BTC5_MIN_BUY_PRICE"]
    assert params["BTC5_UP_MAX_BUY_PRICE"] >= params["BTC5_MIN_BUY_PRICE"]


def test_pricing_evolution_returns_insufficient_data_when_no_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "btc5_empty.db"
    overrides_path = tmp_path / "autoresearch_overrides.json"
    _create_window_trades_table(db_path)

    result = run_pricing_evolution(
        db_path=db_path,
        overrides_path=overrides_path,
        lookback_hours=24,
        mutation_count=5,
        rng_seed=7,
    )
    assert result["status"] == "insufficient_data"
    assert result["replay_rows"] == 0
    assert not overrides_path.exists()
