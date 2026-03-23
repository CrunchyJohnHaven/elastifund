from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Mapping

from scripts.remote_cycle_common import relative_path_text


DEFAULT_TRADES_DB_PATH = Path("data/jj_trades.db")


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ? LIMIT 1",
        (table_name,),
    ).fetchone()
    return row is not None


def _scalar_int(conn: sqlite3.Connection, query: str) -> int:
    row = conn.execute(query).fetchone()
    if not row:
        return 0
    try:
        return int(row[0] or 0)
    except (TypeError, ValueError):
        return 0


def _fallback_source_of_truth(btc5_maker: Mapping[str, Any] | None) -> str:
    if isinstance(btc5_maker, Mapping):
        source = str(
            btc5_maker.get("source")
            or btc5_maker.get("db_path")
            or "data/btc_5min_maker.db#window_trades"
        ).strip()
        if source:
            return source
    return "data/jj_trades.db#trades"


def build_trade_attribution_contract(
    *,
    root: Path | None = None,
    db_path: Path | None = None,
    btc5_maker: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if db_path is None:
        if root is None:
            raise ValueError("build_trade_attribution_contract requires root or db_path")
        root = root.resolve()
        db_path = root / DEFAULT_TRADES_DB_PATH
    else:
        db_path = db_path.resolve()
        if root is None:
            root = db_path.parent.parent if db_path.parent.name == "data" else db_path.parent
        root = root.resolve()

    result = {
        "attribution_mode": "trade_log_fallback_only",
        "source_of_truth": _fallback_source_of_truth(btc5_maker),
        "fill_confirmed": False,
        "db_file_exists": db_path.exists(),
        "trade_count": 0,
        "order_count": 0,
        "fill_count": 0,
        "trade_log_fallback_available": False,
        "orders_table_ready": False,
        "fills_table_ready": False,
        "latest_fill_at": None,
    }
    if not db_path.exists():
        return result

    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(str(db_path))
        trades_ready = _table_exists(conn, "trades")
        orders_ready = _table_exists(conn, "orders")
        fills_ready = _table_exists(conn, "fills")

        result["orders_table_ready"] = orders_ready
        result["fills_table_ready"] = fills_ready

        if trades_ready:
            result["trade_count"] = _scalar_int(conn, "SELECT COUNT(*) FROM trades")
            result["trade_log_fallback_available"] = result["trade_count"] > 0
            if result["trade_log_fallback_available"]:
                result["source_of_truth"] = "data/jj_trades.db#trades"

        if orders_ready:
            result["order_count"] = _scalar_int(conn, "SELECT COUNT(*) FROM orders")

        if fills_ready:
            result["fill_count"] = _scalar_int(conn, "SELECT COUNT(*) FROM fills")
            fill_row = conn.execute("SELECT MAX(timestamp) FROM fills").fetchone()
            if fill_row and fill_row[0]:
                result["latest_fill_at"] = str(fill_row[0])
            if result["fill_count"] > 0:
                result["attribution_mode"] = "db_backed_attribution_ready"
                result["source_of_truth"] = "data/jj_trades.db#fills"
                result["fill_confirmed"] = True

        if result["source_of_truth"].startswith("/"):
            result["source_of_truth"] = (
                relative_path_text(root, Path(result["source_of_truth"]))
                or result["source_of_truth"]
            )
    except sqlite3.DatabaseError:
        return result
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    return result
