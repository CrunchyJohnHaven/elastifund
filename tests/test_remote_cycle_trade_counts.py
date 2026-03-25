from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts.remote_cycle_status_core import _load_trade_counts


def test_load_trade_counts_prefers_wallet_position_mirror_when_present(tmp_path: Path) -> None:
    db_path = tmp_path / "data" / "jj_trades.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE trades (id TEXT, outcome TEXT)")
        conn.executemany(
            "INSERT INTO trades (id, outcome) VALUES (?, ?)",
            [("t1", None), ("t2", "won")],
        )
        conn.execute("CREATE TABLE wallet_open_positions (user_address TEXT)")
        conn.execute("CREATE TABLE wallet_closed_positions (user_address TEXT)")
        conn.executemany(
            "INSERT INTO wallet_open_positions (user_address) VALUES (?)",
            [("0xabc",), ("0xabc",), ("0xabc",)],
        )
        conn.executemany(
            "INSERT INTO wallet_closed_positions (user_address) VALUES (?)",
            [("0xabc",), ("0xabc",), ("0xabc",), ("0xabc",)],
        )

    counts = _load_trade_counts(tmp_path)

    assert counts["total_trades"] == 2
    assert counts["closed_trades"] == 1
    assert counts["wallet_open_positions"] == 3
    assert counts["wallet_closed_positions"] == 4
    assert counts["wallet_position_source"] == "data/jj_trades.db:wallet_position_mirror"
