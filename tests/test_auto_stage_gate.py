from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from bot.auto_stage_gate import run_stage_gate


def _write_env(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _create_window_trades_db(path: Path, rows: list[tuple[int, str, int, float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute(
        """
        CREATE TABLE window_trades (
            decision_ts INTEGER,
            order_status TEXT,
            won INTEGER,
            pnl_usd REAL
        )
        """
    )
    conn.executemany(
        "INSERT INTO window_trades (decision_ts, order_status, won, pnl_usd) VALUES (?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


def test_stage_promotion_caps_to_500_without_explicit_confirmation(tmp_path: Path) -> None:
    stage_env = tmp_path / "state" / "btc5_capital_stage.env"
    _write_env(
        stage_env,
        [
            "BTC5_BANKROLL_USD=390",
            "BTC5_STAGE1_MAX_TRADE_USD=100",
            "BTC5_DAILY_LOSS_LIMIT_USD=5",
        ],
    )
    btc_db = tmp_path / "data" / "btc_5min_maker.db"
    winning_rows = [(1700000000 + idx, "live_filled", 1, 1.0) for idx in range(45)]
    _create_window_trades_db(btc_db, winning_rows)

    result = run_stage_gate(
        stage_env_path=stage_env,
        multi_asset_config_path=tmp_path / "config" / "missing.json",
        asset_db_overrides={"btc": btc_db},
        asset_env_overrides={"btc": tmp_path / "config" / "btc5_strategy.env"},
        balance_json_path=tmp_path / "config" / "missing_balance.json",
        log_path=tmp_path / "data" / "stage_gate_log.json",
    )

    action = next(item for item in result["actions"] if item.get("type") == "stage_promotion")
    assert action["requested_stage1_max_trade_usd"] == 1000.0
    assert action["blocked_by_hard_cap"] is True
    assert action["effective_stage1_max_trade_usd"] == 500.0

    env_after = _read_env(stage_env)
    assert env_after["BTC5_STAGE1_MAX_TRADE_USD"] == "500"


def test_stage_promotion_allows_above_500_with_confirmation(tmp_path: Path) -> None:
    stage_env = tmp_path / "state" / "btc5_capital_stage.env"
    _write_env(
        stage_env,
        [
            "BTC5_BANKROLL_USD=390",
            "BTC5_STAGE1_MAX_TRADE_USD=100",
            "BTC5_DAILY_LOSS_LIMIT_USD=5",
            "BTC5_HUMAN_CONFIRMED_MAX_TRADE_ABOVE_500=true",
        ],
    )
    btc_db = tmp_path / "data" / "btc_5min_maker.db"
    winning_rows = [(1700000000 + idx, "live_filled", 1, 1.0) for idx in range(45)]
    _create_window_trades_db(btc_db, winning_rows)

    run_stage_gate(
        stage_env_path=stage_env,
        multi_asset_config_path=tmp_path / "config" / "missing.json",
        asset_db_overrides={"btc": btc_db},
        asset_env_overrides={"btc": tmp_path / "config" / "btc5_strategy.env"},
        balance_json_path=tmp_path / "config" / "missing_balance.json",
        log_path=tmp_path / "data" / "stage_gate_log.json",
    )

    env_after = _read_env(stage_env)
    assert env_after["BTC5_STAGE1_MAX_TRADE_USD"] == "1000"


def test_loss_streak_scales_asset_max_trade_and_halts_on_low_balance(tmp_path: Path) -> None:
    stage_env = tmp_path / "state" / "btc5_capital_stage.env"
    _write_env(
        stage_env,
        [
            "BTC5_BANKROLL_USD=200",
            "BTC5_STAGE1_MAX_TRADE_USD=100",
            "BTC5_DAILY_LOSS_LIMIT_USD=5",
        ],
    )
    eth_env = tmp_path / "config" / "eth5_strategy.env"
    _write_env(eth_env, ["BTC5_MAX_TRADE_USD=40"])

    eth_db = tmp_path / "data" / "eth_5min_maker.db"
    losing_rows = [(1800000000 + idx, "live_filled", 0, -1.0) for idx in range(5)]
    _create_window_trades_db(eth_db, losing_rows)

    balance_json = tmp_path / "config" / "remote_cycle_status.json"
    balance_json.parent.mkdir(parents=True, exist_ok=True)
    balance_json.write_text(
        json.dumps(
            {
                "capital_sources": [
                    {"account": "Polymarket", "amount_usd": 90.0},
                ]
            }
        ),
        encoding="utf-8",
    )

    result = run_stage_gate(
        stage_env_path=stage_env,
        multi_asset_config_path=tmp_path / "config" / "missing.json",
        asset_db_overrides={"eth": eth_db},
        asset_env_overrides={"eth": eth_env},
        balance_json_path=balance_json,
        log_path=tmp_path / "data" / "stage_gate_log.json",
    )

    eth_after = _read_env(eth_env)
    assert eth_after["BTC5_MAX_TRADE_USD"] == "20"
    assert eth_after["BTC5_STAGE1_MAX_TRADE_USD"] == "20"

    stage_after = _read_env(stage_env)
    assert stage_after["BTC5_DAILY_LOSS_LIMIT_USD"] == "0"

    loss_scale_action = next(
        item
        for item in result["actions"]
        if item.get("type") == "asset_loss_scale_down" and item.get("asset") == "eth"
    )
    assert loss_scale_action["applied"] is True

