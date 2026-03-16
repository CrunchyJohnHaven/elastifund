from __future__ import annotations

import sqlite3
from pathlib import Path

from bot.auto_stage_gate import run_stage_gate


def _create_window_db(path: Path, rows: list[tuple[int, int, float]]) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE window_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            decision_ts INTEGER,
            order_status TEXT,
            filled INTEGER,
            won INTEGER,
            pnl_usd REAL,
            created_at TEXT
        );
        """
    )
    conn.executemany(
        """
        INSERT INTO window_trades(decision_ts, order_status, filled, won, pnl_usd, created_at)
        VALUES (?, 'live_filled', 1, ?, ?, '2026-03-16T00:00:00+00:00')
        """,
        rows,
    )
    conn.commit()
    conn.close()


def _write_stage_env(path: Path, *, bankroll: float, risk_fraction: float, stage1_max: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                f"BTC5_BANKROLL_USD={bankroll}",
                f"BTC5_RISK_FRACTION={risk_fraction}",
                f"BTC5_MAX_TRADE_USD={stage1_max}",
                f"BTC5_STAGE1_MAX_TRADE_USD={stage1_max}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_run_stage_gate_scales_to_750_and_writes_stage1_cap(tmp_path: Path) -> None:
    db_path = tmp_path / "btc_5min_maker.db"
    env_path = tmp_path / "state" / "btc5_capital_stage.env"
    log_path = tmp_path / "data" / "stage_gate_log.json"
    rows = [(1_000_000 + i, 1 if i < 12 else 0, 1.0 if i < 12 else -0.5) for i in range(20)]
    _create_window_db(db_path, rows)
    _write_stage_env(env_path, bankroll=5000, risk_fraction=0.33, stage1_max=500)

    result = run_stage_gate(
        state_env_path=env_path,
        db_paths=[db_path],
        log_path=log_path,
        lookback_hours=0.0,
    )

    assert result["decision"]["action"] == "scale_up"
    assert result["decision"]["applied_max_trade_usd"] == 750.0
    rendered_env = env_path.read_text(encoding="utf-8")
    assert "BTC5_MAX_TRADE_USD=750.00" in rendered_env
    assert "BTC5_STAGE1_MAX_TRADE_USD=750.00" in rendered_env
    assert log_path.exists()


def test_run_stage_gate_caps_to_2x_step_when_stage3_target_is_higher(tmp_path: Path) -> None:
    db_path = tmp_path / "eth_5min_maker.db"
    env_path = tmp_path / "state" / "btc5_capital_stage.env"
    log_path = tmp_path / "data" / "stage_gate_log.json"
    rows = [(2_000_000 + i, 1 if i < 30 else 0, 1.0 if i < 30 else -0.5) for i in range(40)]
    _create_window_db(db_path, rows)
    _write_stage_env(env_path, bankroll=5000, risk_fraction=0.5, stage1_max=300)

    result = run_stage_gate(
        state_env_path=env_path,
        db_paths=[db_path],
        log_path=log_path,
        lookback_hours=0.0,
    )

    assert result["decision"]["action"] == "scale_up"
    assert result["decision"]["target_max_trade_usd"] == 600.0
    assert "capped_by_max_2x_step" in result["decision"]["safeguards"]


def test_run_stage_gate_scales_down_after_five_consecutive_losses(tmp_path: Path) -> None:
    db_path = tmp_path / "sol_5min_maker.db"
    env_path = tmp_path / "state" / "btc5_capital_stage.env"
    log_path = tmp_path / "data" / "stage_gate_log.json"
    rows = []
    for i in range(10):
        won = 1
        pnl = 1.0
        rows.append((3_000_000 + i, won, pnl))
    for i in range(10, 15):
        rows.append((3_000_000 + i, 0, -1.0))
    _create_window_db(db_path, rows)
    _write_stage_env(env_path, bankroll=5000, risk_fraction=0.33, stage1_max=500)

    result = run_stage_gate(
        state_env_path=env_path,
        db_paths=[db_path],
        log_path=log_path,
        lookback_hours=0.0,
    )

    assert result["decision"]["action"] == "scale_down"
    assert result["decision"]["reason"] == "five_consecutive_losses"
    assert result["decision"]["applied_max_trade_usd"] == 250.0


def test_run_stage_gate_halts_when_balance_drops_below_half_bankroll(tmp_path: Path) -> None:
    db_path = tmp_path / "xrp_5min_maker.db"
    env_path = tmp_path / "state" / "btc5_capital_stage.env"
    log_path = tmp_path / "data" / "stage_gate_log.json"
    rows = [(4_000_000 + i, 1, 1.0) for i in range(25)]
    _create_window_db(db_path, rows)
    _write_stage_env(env_path, bankroll=1308, risk_fraction=0.33, stage1_max=500)

    result = run_stage_gate(
        state_env_path=env_path,
        db_paths=[db_path],
        log_path=log_path,
        lookback_hours=0.0,
        balance_override=500.0,
    )

    assert result["decision"]["action"] == "halt"
    assert result["decision"]["halted"] is True
    assert result["decision"]["applied_max_trade_usd"] == 0.0
    rendered_env = env_path.read_text(encoding="utf-8")
    assert "BTC5_STAGE1_MAX_TRADE_USD=0.00" in rendered_env
    assert "BTC5_AUTO_STAGE_GATE_HALTED=true" in rendered_env
