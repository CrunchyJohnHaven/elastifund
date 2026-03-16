from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from bot import autoresearch_loop
from scripts import autoresearch_deploy


def test_generate_price_floor_hypotheses_sweeps_requested_grid() -> None:
    observation = {"total_pnl": 3.25, "segments": {}}
    hypotheses = autoresearch_loop.generate_hypotheses(observation)
    price_hypotheses = [
        h for h in hypotheses if h.hypothesis_id.startswith("h_price_")
    ]
    assert len(price_hypotheses) == len(autoresearch_loop.PRICE_FLOOR_SWEEP) * len(
        autoresearch_loop.PRICE_CAP_SWEEP
    )
    assert any(
        h.params.get("BTC5_MIN_BUY_PRICE") == 0.90
        and h.params.get("BTC5_DOWN_MAX_BUY_PRICE") == 0.93
        and h.params.get("BTC5_UP_MAX_BUY_PRICE") == 0.93
        for h in price_hypotheses
    )


def test_build_kelly_recommendation_outputs_fraction_and_size(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "maker.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE window_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_status TEXT,
            won INTEGER,
            order_price REAL,
            pnl_usd REAL,
            created_at TEXT
        )
        """
    )
    rows = [
        ("live_filled", 1, 0.90, 0.50, "2026-03-16T00:00:00+00:00"),
        ("live_filled", 1, 0.91, 0.40, "2026-03-16T00:05:00+00:00"),
        ("live_filled", 0, 0.92, -0.92, "2026-03-16T00:10:00+00:00"),
        ("live_filled", 1, 0.88, 0.10, "2026-03-16T00:15:00+00:00"),  # filtered out (<0.90)
    ]
    conn.executemany(
        "INSERT INTO window_trades(order_status, won, order_price, pnl_usd, created_at) VALUES (?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(autoresearch_loop, "DB_PATH", db_path)
    monkeypatch.setenv("BTC5_BANKROLL_USD", "390")
    recommendation = autoresearch_loop.build_kelly_recommendation(min_entry=0.90, limit=50)

    assert recommendation["n_qualifying_fills"] == 3
    assert recommendation["win_rate"] == 0.6667
    assert recommendation["avg_entry_price"] == 0.91
    assert recommendation["recommended_kelly_fraction"] >= 0.0
    assert recommendation["recommended_trade_size_usd"] >= 0.0


def test_validate_params_applies_hard_bounds_and_logs_guardrails() -> None:
    safe, events = autoresearch_deploy._validate_params(
        {
            "BTC5_MIN_BUY_PRICE": 0.70,
            "BTC5_DOWN_MAX_BUY_PRICE": 0.99,
            "BTC5_DIRECTIONAL_MODE": "off",
        },
        hypothesis_id="hyp_test",
    )
    assert safe["BTC5_MIN_BUY_PRICE"] == 0.85
    assert safe["BTC5_DOWN_MAX_BUY_PRICE"] == 0.95
    assert "BTC5_DIRECTIONAL_MODE" not in safe
    assert any(event["status"] == "autoresearch_guardrail_triggered" for event in events)
    assert any(event["reason"] == "below_hard_min" for event in events)
    assert any(event["reason"] == "above_hard_max" for event in events)
    assert any(event["reason"] == "directional_mode_invalid" for event in events)


def test_run_cycle_triggers_pricing_evolution_even_with_low_fill_count(monkeypatch) -> None:
    called: dict[str, object] = {}

    monkeypatch.setattr(
        autoresearch_loop,
        "build_kelly_recommendation",
        lambda: {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "n_qualifying_fills": 0,
            "win_rate": 0.0,
            "recommended_kelly_fraction": 0.0,
            "recommended_trade_size_usd": 0.0,
        },
    )
    monkeypatch.setattr(
        autoresearch_loop,
        "observe_recent_performance",
        lambda hours=24: {"total_fills": 0, "total_pnl": 0.0, "win_rate": 0.0, "segments": {}},
    )
    monkeypatch.setattr(autoresearch_loop, "_write_json", lambda path, payload: None)

    def _fake_run_pricing_evolution(**kwargs):
        called.update(kwargs)
        return {"status": "insufficient_data"}

    monkeypatch.setattr(autoresearch_loop, "run_pricing_evolution", _fake_run_pricing_evolution)

    result = autoresearch_loop.run_cycle()
    assert result is None
    assert called["db_path"] == autoresearch_loop.DB_PATH
    assert called["overrides_path"] == autoresearch_loop.AUTORESEARCH_OVERRIDES_PATH
    assert called["lookback_hours"] == 24
