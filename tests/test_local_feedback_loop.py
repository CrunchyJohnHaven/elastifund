from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from scripts.build_local_feedback_loop import build_local_feedback_loop


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_build_local_feedback_loop_compiles_cross_venue_metrics(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    _write_json(
        tmp_path / "reports" / "local_live_status.json",
        {
            "generated_at": now,
            "requested_live_venues": ["polymarket"],
            "venues": {
                "alpaca": {
                    "effective_mode": "paper",
                    "feedback_loop_ready": True,
                    "requested_live": False,
                    "blockers": [],
                },
                "kalshi": {
                    "effective_mode": "paper",
                    "feedback_loop_ready": True,
                    "requested_live": False,
                    "blockers": [],
                },
                "polymarket": {
                    "effective_mode": "paper",
                    "feedback_loop_ready": True,
                    "requested_live": True,
                    "blockers": ["launch_posture_blocked"],
                },
            },
        },
    )

    _write_json(
        tmp_path / "reports" / "parallel" / "alpaca_crypto_lane.json",
        {
            "generated_at": now,
            "candidate_count": 0,
            "candidate_rows": [],
        },
    )
    _write_json(
        tmp_path / "reports" / "alpaca_first_trade" / "latest.json",
        {
            "generated_at": now,
            "status": "blocked",
            "action": "blocked",
            "blockers": ["no_unconsumed_alpaca_candidates"],
        },
    )
    _write_json(
        tmp_path / "state" / "alpaca_first_trade_state.json",
        {
            "variant_live_returns": {"btcusd_momo_1": [0.01, -0.02]},
            "open_trade": None,
        },
    )

    kalshi_decision = {
        "timestamp": now,
        "market_ticker": "KXHIGHNY-TEST",
        "side": "yes",
        "execution_mode": "paper",
        "execution_result": "paper",
        "order_client_id": "kalshi-1",
    }
    for relpath, row in (
        ("data/kalshi_weather_signals.jsonl", {"timestamp": now, "market_ticker": "KXHIGHNY-TEST"}),
        ("data/kalshi_weather_orders.jsonl", kalshi_decision),
        ("data/kalshi_weather_decisions.jsonl", kalshi_decision),
        ("data/kalshi_weather_settlements.jsonl", {**kalshi_decision, "settled": True}),
    ):
        path = tmp_path / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(row) + "\n", encoding="utf-8")

    db_path = tmp_path / "data" / "local_btc_5min_maker.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE window_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filled INTEGER,
                order_status TEXT,
                won INTEGER,
                decision_ts INTEGER,
                pnl_usd REAL,
                resolved_side TEXT,
                shares REAL,
                token_id TEXT,
                order_price REAL,
                direction TEXT
            )
            """
        )
        now_ts = int(datetime.now(timezone.utc).timestamp())
        for idx in range(12):
            conn.execute(
                """
                INSERT INTO window_trades (
                    filled, order_status, won, decision_ts, pnl_usd, resolved_side,
                    shares, token_id, order_price, direction
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (1, "live_filled", 1 if idx % 2 == 0 else 0, now_ts - idx * 60, 1.25, "DOWN", 10.0, f"tok-{idx}", 0.52, "DOWN"),
            )

    artifact = build_local_feedback_loop(root=tmp_path)

    assert artifact["overall"]["venue_count"] == 3
    assert artifact["overall"]["feedback_ready_count"] == 3
    assert artifact["venues"]["alpaca"]["candidate_count"] == 0
    assert any(hint["code"] == "candidate_density_zero" for hint in artifact["venues"]["alpaca"]["hints"])
    assert artifact["venues"]["kalshi"]["settlement_match_rate"] == 1.0
    assert artifact["venues"]["polymarket"]["trailing_12_live_filled_count"] == 12
    assert any(hint["code"] == "live_gate_blocked" for hint in artifact["venues"]["polymarket"]["hints"])
