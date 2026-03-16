import json
import sqlite3
from pathlib import Path

from bot.cascade_max import record_cascade_event, run_cascade_detection


def _seed_window_table(db_path: Path, rows: list[tuple[int, float, int | None]]) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS window_trades (
                window_start_ts INTEGER PRIMARY KEY,
                decision_ts INTEGER,
                delta REAL,
                won INTEGER,
                updated_at TEXT
            )
            """
        )
        for window_start_ts, delta, won in rows:
            conn.execute(
                """
                INSERT OR REPLACE INTO window_trades(window_start_ts, decision_ts, delta, won, updated_at)
                VALUES (?, ?, ?, ?, datetime('now'))
                """,
                (window_start_ts, window_start_ts, delta, won),
            )


def test_run_cascade_detection_writes_active_signal(tmp_path: Path) -> None:
    btc_db = tmp_path / "btc.db"
    eth_db = tmp_path / "eth.db"
    sol_db = tmp_path / "sol.db"
    signal_path = tmp_path / "cascade_signal.json"
    _seed_window_table(btc_db, [(1, -0.0030, None)])
    _seed_window_table(eth_db, [(1, -0.0025, None)])
    _seed_window_table(sol_db, [(1, -0.0040, None)])

    payload = run_cascade_detection(
        window_start_ts=12345,
        btc_db_path=btc_db,
        eth_db_path=eth_db,
        sol_db_path=sol_db,
        signal_path=signal_path,
    )

    assert payload["active"] is True
    assert payload["direction"] == "DOWN"
    persisted = json.loads(signal_path.read_text(encoding="utf-8"))
    assert persisted["active"] is True
    assert persisted["direction"] == "DOWN"
    assert persisted["confidence"] == 1.0
    assert persisted["detected_at"] == 12345


def test_record_cascade_event_enables_live_after_shadow_wr_gate(tmp_path: Path) -> None:
    btc_db = tmp_path / "btc.db"
    log_path = tmp_path / "cascade_log.json"
    _seed_window_table(
        btc_db,
        [(idx, -0.003, 1) for idx in range(1, 11)],
    )
    bootstrap_log = {
        "events": [
            {
                "window_start_ts": idx,
                "mode": "shadow",
                "won": None,
                "detected_at": idx,
                "cascade_direction": "DOWN",
                "bot_direction": "DOWN",
                "best_ask": 0.92,
                "bot_delta": -0.003,
            }
            for idx in range(1, 11)
        ],
        "stats": {},
    }
    log_path.write_text(json.dumps(bootstrap_log), encoding="utf-8")

    result = record_cascade_event(
        window_start_ts=11,
        cascade_signal={"active": True, "direction": "DOWN"},
        bot_direction="DOWN",
        bot_delta=-0.004,
        best_ask=0.91,
        btc_db_path=btc_db,
        log_path=log_path,
    )

    assert result["cascade_boost_candidate"] is True
    assert result["cascade_boost_live_enabled"] is True
    assert result["cascade_boost_apply"] is True
    assert result["cascade_mode"] == "live"
    persisted = json.loads(log_path.read_text(encoding="utf-8"))
    assert persisted["stats"]["detection_count"] == 11
