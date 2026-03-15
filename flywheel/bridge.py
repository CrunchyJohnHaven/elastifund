"""Bridge bot SQLite state into canonical flywheel cycle packets."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from infra.fast_json import dump_path_atomic
from .contracts import CyclePacket


def build_cycle_packet_from_bot_db(
    bot_db_path: str | Path,
    *,
    strategy_key: str,
    version_label: str,
    lane: str,
    environment: str,
    capital_cap_usd: float,
    artifact_uri: str | None = None,
    git_sha: str | None = None,
    lookback_days: int = 7,
) -> dict[str, Any]:
    """Construct one flywheel cycle packet for one strategy from a bot SQLite DB."""

    conn = sqlite3.connect(str(bot_db_path))
    conn.row_factory = sqlite3.Row
    try:
        tables = _table_names(conn)
        if "portfolio_snapshots" in tables:
            snapshot = _build_snapshot_from_portfolio_schema(conn, tables, lookback_days)
            schema_mode = "portfolio"
        elif "bot_state" in tables:
            snapshot = _build_snapshot_from_runtime_schema(conn, tables, lookback_days)
            schema_mode = "runtime"
        elif _looks_like_jj_live_schema(tables):
            snapshot = _build_snapshot_from_jj_live_schema(conn, tables, lookback_days)
            schema_mode = "jj_live"
        else:
            raise RuntimeError(
                "Unsupported bot DB schema; expected portfolio, runtime, or jj_live tables. "
                f"Found tables: {sorted(tables)}"
            )

        cycle_packet = {
            "cycle_key": _cycle_key(snapshot["snapshot_date"]),
            "strategies": [
                {
                    "strategy_key": strategy_key,
                    "version_label": version_label,
                    "lane": lane,
                    "artifact_uri": artifact_uri,
                    "git_sha": git_sha,
                    "status": "candidate",
                    "config": {
                        "bridge_schema": schema_mode,
                        "bot_db_path": str(bot_db_path),
                        "lookback_days": lookback_days,
                    },
                    "deployments": [
                        {
                            "environment": environment,
                            "capital_cap_usd": capital_cap_usd,
                            "status": "active",
                            "notes": f"Bridged from {bot_db_path}",
                            "snapshot": snapshot,
                        }
                    ],
                }
            ],
        }
        return CyclePacket.from_dict(cycle_packet).to_dict()
    finally:
        conn.close()


def build_payload_from_bot_db(
    bot_db_path: str | Path,
    *,
    strategy_key: str,
    version_label: str,
    lane: str,
    environment: str,
    capital_cap_usd: float,
    artifact_uri: str | None = None,
    git_sha: str | None = None,
    lookback_days: int = 7,
) -> dict[str, Any]:
    """Backward-compatible alias for `build_cycle_packet_from_bot_db`."""
    return build_cycle_packet_from_bot_db(
        bot_db_path,
        strategy_key=strategy_key,
        version_label=version_label,
        lane=lane,
        environment=environment,
        capital_cap_usd=capital_cap_usd,
        artifact_uri=artifact_uri,
        git_sha=git_sha,
        lookback_days=lookback_days,
    )


def write_cycle_packet(cycle_packet: dict[str, Any], output_path: str | Path) -> str:
    """Write one flywheel cycle packet JSON document to disk."""

    path = Path(output_path)
    dump_path_atomic(path, cycle_packet, indent=2, sort_keys=True, trailing_newline=False)
    return str(path)


def write_payload(payload: dict[str, Any], output_path: str | Path) -> str:
    """Backward-compatible alias for `write_cycle_packet`."""
    return write_cycle_packet(payload, output_path)


def _build_snapshot_from_portfolio_schema(
    conn: sqlite3.Connection,
    tables: set[str],
    lookback_days: int,
) -> dict[str, Any]:
    latest = conn.execute(
        """
        SELECT date, cash_usd, total_value_usd, realized_pnl, unrealized_pnl, open_positions, win_rate
        FROM portfolio_snapshots
        ORDER BY date DESC
        LIMIT 1
        """
    ).fetchone()
    if latest is None:
        raise RuntimeError("portfolio_snapshots is empty; cannot build flywheel payload")

    lookback_start = _lookback_start(_parse_timestamp(latest["date"]), lookback_days)
    previous = conn.execute(
        """
        SELECT total_value_usd
        FROM portfolio_snapshots
        WHERE date < ?
        ORDER BY date DESC
        LIMIT 1
        """,
        (latest["date"],),
    ).fetchone()
    starting_bankroll = (
        float(previous["total_value_usd"])
        if previous is not None
        else float(latest["total_value_usd"] or 0.0) - float(latest["realized_pnl"] or 0.0)
    )

    closed_trades = (
        _count_rows(
            conn,
            "SELECT COUNT(*) FROM exit_events WHERE date(created_at) >= ?",
            (lookback_start,),
        )
        if "exit_events" in tables
        else _count_closed_orders(conn, tables, lookback_start)
    )
    risk_events = _count_risk_events(conn, tables, lookback_start)
    fill_rate = _fill_rate(conn, tables, lookback_start)
    avg_slippage_bps = _avg_slippage_bps(conn, tables, lookback_start)
    max_drawdown_pct = _max_drawdown_from_portfolio(conn, lookback_start)

    return {
        "snapshot_date": str(latest["date"]),
        "starting_bankroll": starting_bankroll,
        "ending_bankroll": float(latest["total_value_usd"] or 0.0),
        "realized_pnl": float(latest["realized_pnl"] or 0.0),
        "unrealized_pnl": float(latest["unrealized_pnl"] or 0.0),
        "open_positions": int(latest["open_positions"] or 0),
        "closed_trades": int(closed_trades),
        "win_rate": _float_or_none(latest["win_rate"]),
        "fill_rate": fill_rate,
        "avg_slippage_bps": avg_slippage_bps,
        "rolling_brier": None,
        "rolling_ece": None,
        "max_drawdown_pct": max_drawdown_pct,
        "kill_events": int(risk_events),
        "metrics": {
            "schema_mode": "portfolio",
        },
    }


def _build_snapshot_from_runtime_schema(
    conn: sqlite3.Connection,
    tables: set[str],
    lookback_days: int,
) -> dict[str, Any]:
    anchor = _latest_activity_timestamp(conn, tables) or datetime.now(timezone.utc)
    lookback_start = _lookback_start(anchor, lookback_days)
    bot_state = _bot_state(conn, tables)

    bankroll_points = _bankroll_series(conn, tables, lookback_start)
    starting_bankroll, ending_bankroll = _bankroll_bounds(bankroll_points)

    open_positions = _scalar_query(
        conn,
        "SELECT COUNT(*) FROM positions WHERE ABS(size) > 0",
        default=0,
    ) if "positions" in tables else 0
    realized_pnl = _scalar_query(
        conn,
        "SELECT COALESCE(SUM(realized_pnl), 0.0) FROM positions",
        default=0.0,
    ) if "positions" in tables else 0.0
    unrealized_pnl = _scalar_query(
        conn,
        "SELECT COALESCE(SUM(unrealized_pnl), 0.0) FROM positions",
        default=0.0,
    ) if "positions" in tables else 0.0
    closed_trades = _count_closed_orders(conn, tables, lookback_start)
    win_rate = _position_win_rate(conn, tables, lookback_start)
    fill_rate = _fill_rate(conn, tables, lookback_start)
    avg_slippage_bps = _avg_slippage_bps(conn, tables, lookback_start)
    max_drawdown_pct = _max_drawdown_from_bankroll(bankroll_points)
    risk_events = _count_risk_events(conn, tables, lookback_start)
    kill_events = risk_events + (1 if bot_state["kill_switch"] else 0)

    if ending_bankroll == 0.0 and starting_bankroll == 0.0 and "positions" in tables:
        approximate_position_value = _scalar_query(
            conn,
            "SELECT COALESCE(SUM(size * avg_entry_price), 0.0) FROM positions",
            default=0.0,
        )
        ending_bankroll = float(approximate_position_value)
        starting_bankroll = float(approximate_position_value)

    opportunity_count = (
        _count_rows(
            conn,
            "SELECT COUNT(*) FROM detector_opportunities WHERE date(detected_at) >= ?",
            (lookback_start,),
        )
        if "detector_opportunities" in tables
        else 0
    )
    sizing_count = (
        _count_rows(
            conn,
            "SELECT COUNT(*) FROM sizing_decisions WHERE date(created_at) >= ?",
            (lookback_start,),
        )
        if "sizing_decisions" in tables
        else 0
    )
    trade_decisions = (
        _count_rows(
            conn,
            """
            SELECT COUNT(*)
            FROM sizing_decisions
            WHERE date(created_at) >= ? AND decision = 'trade'
            """,
            (lookback_start,),
        )
        if "sizing_decisions" in tables
        else 0
    )
    avg_edge_after_fee = (
        _scalar_query(
            conn,
            """
            SELECT AVG(edge_after_fee)
            FROM sizing_decisions
            WHERE date(created_at) >= ?
            """,
            (lookback_start,),
            default=None,
        )
        if "sizing_decisions" in tables
        else None
    )

    return {
        "snapshot_date": anchor.date().isoformat(),
        "starting_bankroll": float(starting_bankroll),
        "ending_bankroll": float(ending_bankroll),
        "realized_pnl": float(realized_pnl),
        "unrealized_pnl": float(unrealized_pnl),
        "open_positions": int(open_positions),
        "closed_trades": int(closed_trades),
        "win_rate": win_rate,
        "fill_rate": fill_rate,
        "avg_slippage_bps": avg_slippage_bps,
        "rolling_brier": None,
        "rolling_ece": None,
        "max_drawdown_pct": float(max_drawdown_pct),
        "kill_events": int(kill_events),
        "metrics": {
            "schema_mode": "runtime",
            "bot_version": bot_state["version"],
            "bot_is_running": bot_state["is_running"],
            "kill_switch": bot_state["kill_switch"],
            "last_heartbeat": bot_state["last_heartbeat"],
            "orders_submitted": _count_orders(conn, tables, lookback_start),
            "fills_recorded": _count_fill_rows(conn, tables, lookback_start),
            "sizing_decisions": int(sizing_count),
            "trade_decisions": int(trade_decisions),
            "detector_opportunities": int(opportunity_count),
            "avg_edge_after_fee": _float_or_none(avg_edge_after_fee),
        },
    }


def _build_snapshot_from_jj_live_schema(
    conn: sqlite3.Connection,
    tables: set[str],
    lookback_days: int,
) -> dict[str, Any]:
    anchor = _latest_activity_timestamp(conn, tables) or datetime.now(timezone.utc)
    lookback_start = _lookback_start(anchor, lookback_days)
    latest_cycle = _latest_jj_live_cycle(conn, tables)
    latest_report = _latest_jj_live_daily_report(conn, tables)
    paper_mode = _jj_live_paper_mode(conn, tables, latest_cycle)

    bankroll_points = _jj_live_bankroll_series(
        conn,
        tables,
        lookback_start,
        paper_mode=paper_mode,
    )
    starting_bankroll, ending_bankroll = _bankroll_bounds(bankroll_points)
    if latest_cycle is not None and not bankroll_points:
        current_bankroll = _float_or_none(latest_cycle["bankroll"]) or 0.0
        starting_bankroll = current_bankroll
        ending_bankroll = current_bankroll

    latest_total_pnl = (
        _float_or_none(latest_report["cumulative_pnl"])
        if latest_report is not None
        else _float_or_none(
            _scalar_query(
                conn,
                "SELECT COALESCE(SUM(pnl), 0.0) FROM trades WHERE pnl IS NOT NULL",
                default=0.0,
            )
        )
    )
    daily_pnl = (
        _float_or_none(latest_cycle["daily_pnl"])
        if latest_cycle is not None
        else None
    )
    if daily_pnl is None and latest_report is not None:
        daily_pnl = _float_or_none(latest_report["daily_pnl"])

    rolling_brier = _trade_brier(
        conn,
        tables,
        lookback_start,
        paper_mode=paper_mode,
    )
    if rolling_brier is None and latest_report is not None:
        rolling_brier = _float_or_none(latest_report["brier_score"])

    snapshot_date = (
        str(latest_report["date"])
        if latest_report is not None and latest_report["date"] is not None
        else anchor.date().isoformat()
    )
    open_positions = (
        int(latest_cycle["open_positions"] or 0)
        if latest_cycle is not None and latest_cycle["open_positions"] is not None
        else _count_unresolved_trades(conn, tables, paper_mode=paper_mode)
    )
    cycles_logged = _count_jj_live_cycles(conn, tables, lookback_start, paper_mode=paper_mode)
    trades_placed = _sum_jj_live_cycle_metric(
        conn,
        tables,
        lookback_start,
        "trades_placed",
        paper_mode=paper_mode,
    )
    if trades_placed == 0 and "trades" in tables:
        trade_columns = _table_columns(conn, "trades")
        paper_clause, paper_params = _paper_filter(trade_columns, paper_mode)
        trades_placed = _count_rows(
            conn,
            f"SELECT COUNT(*) FROM trades WHERE date(timestamp) >= ?{paper_clause}",  # noqa: S608
            (lookback_start, *paper_params),
        )
    signals_found = _sum_jj_live_cycle_metric(
        conn,
        tables,
        lookback_start,
        "signals_found",
        paper_mode=paper_mode,
    )
    reports_logged = _count_jj_live_reports(conn, tables, lookback_start)

    return {
        "snapshot_date": snapshot_date,
        "starting_bankroll": float(starting_bankroll),
        "ending_bankroll": float(ending_bankroll),
        "realized_pnl": float(
            _resolved_trade_pnl(conn, tables, lookback_start, paper_mode=paper_mode)
        ),
        "unrealized_pnl": 0.0,
        "open_positions": int(open_positions),
        "closed_trades": int(
            _count_resolved_trades(conn, tables, lookback_start, paper_mode=paper_mode)
        ),
        "win_rate": _trade_win_rate(conn, tables, lookback_start, paper_mode=paper_mode),
        "fill_rate": _fill_rate(conn, tables, lookback_start, paper_mode=paper_mode),
        "avg_slippage_bps": _avg_slippage_bps(
            conn,
            tables,
            lookback_start,
            paper_mode=paper_mode,
        ),
        "rolling_brier": rolling_brier,
        "rolling_ece": None,
        "max_drawdown_pct": float(_max_drawdown_from_bankroll(bankroll_points)),
        "kill_events": int(_count_risk_events(conn, tables, lookback_start)),
        "metrics": {
            "schema_mode": "jj_live",
            "paper_mode": paper_mode,
            "cycles_logged": int(cycles_logged),
            "reports_logged": int(reports_logged),
            "signals_found": int(signals_found),
            "trades_placed": int(trades_placed),
            "unresolved_trades": int(
                _count_unresolved_trades(conn, tables, paper_mode=paper_mode)
            ),
            "latest_daily_pnl": daily_pnl,
            "cumulative_pnl": latest_total_pnl,
            "brier_score": rolling_brier,
        },
    }


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
        """
    ).fetchall()
    return {str(row["name"]) for row in rows}


def _cycle_key(snapshot_date: str) -> str:
    return f"bridge-{snapshot_date}"


def _looks_like_jj_live_schema(tables: set[str]) -> bool:
    return "trades" in tables and ("cycles" in tables or "daily_reports" in tables or "multi_bankroll" in tables)


def _lookback_start(anchor: datetime, lookback_days: int) -> str:
    return (anchor - timedelta(days=lookback_days - 1)).date().isoformat()


def _parse_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if value is None:
        raise ValueError("timestamp value is required")
    text = str(value).strip()
    if len(text) == 10:
        dt = datetime.strptime(text, "%Y-%m-%d")
    else:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _latest_activity_timestamp(conn: sqlite3.Connection, tables: set[str]) -> datetime | None:
    candidates: list[datetime] = []
    columns_by_table = {table: _table_columns(conn, table) for table in tables}
    for table, column in (
        ("fills", "timestamp"),
        ("fills", "created_at"),
        ("orders", "timestamp"),
        ("orders", "updated_at"),
        ("orders", "created_at"),
        ("positions", "updated_at"),
        ("sizing_decisions", "created_at"),
        ("detector_opportunities", "detected_at"),
        ("risk_events", "created_at"),
        ("bot_state", "updated_at"),
        ("bot_state", "last_heartbeat"),
        ("trades", "resolved_at"),
        ("trades", "timestamp"),
        ("cycles", "timestamp"),
        ("daily_reports", "date"),
        ("multi_bankroll", "timestamp"),
    ):
        if table not in tables:
            continue
        if column not in columns_by_table[table]:
            continue
        row = conn.execute(f"SELECT MAX({column}) AS value FROM {table}").fetchone()  # noqa: S608
        if row is None or row["value"] is None:
            continue
        candidates.append(_parse_timestamp(row["value"]))
    if not candidates:
        return None
    return max(candidates)


def _bot_state(conn: sqlite3.Connection, tables: set[str]) -> dict[str, Any]:
    if "bot_state" not in tables:
        return {
            "is_running": False,
            "kill_switch": False,
            "last_heartbeat": None,
            "version": None,
        }

    columns = _table_columns(conn, "bot_state")
    select_parts = ["is_running", "kill_switch", "version"]
    if "last_heartbeat" in columns:
        select_parts.append("last_heartbeat")
    else:
        select_parts.append("NULL AS last_heartbeat")

    order_column = "updated_at" if "updated_at" in columns else "id"
    row = conn.execute(
        f"SELECT {', '.join(select_parts)} FROM bot_state ORDER BY {order_column} DESC LIMIT 1"  # noqa: S608
    ).fetchone()
    if row is None:
        return {
            "is_running": False,
            "kill_switch": False,
            "last_heartbeat": None,
            "version": None,
        }
    return {
        "is_running": bool(row["is_running"]),
        "kill_switch": bool(row["kill_switch"]),
        "last_heartbeat": row["last_heartbeat"],
        "version": row["version"],
    }


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()  # noqa: S608
    return {str(row["name"]) for row in rows}


def _first_present(columns: set[str], *candidates: str) -> str | None:
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


def _paper_filter(
    columns: set[str],
    paper_mode: bool | None,
    *,
    table_alias: str | None = None,
) -> tuple[str, tuple[int, ...]]:
    if paper_mode is None or "paper" not in columns:
        return "", ()
    qualifier = f"{table_alias}." if table_alias else ""
    return f" AND {qualifier}paper = ?", (1 if paper_mode else 0,)


def _count_rows(conn: sqlite3.Connection, query: str, params: tuple[Any, ...]) -> int:
    row = conn.execute(query, params).fetchone()
    return int(row[0] or 0) if row is not None else 0


def _scalar_query(
    conn: sqlite3.Connection,
    query: str,
    params: tuple[Any, ...] = (),
    *,
    default: Any,
) -> Any:
    row = conn.execute(query, params).fetchone()
    if row is None or row[0] is None:
        return default
    return row[0]


def _count_orders(conn: sqlite3.Connection, tables: set[str], lookback_start: str) -> int:
    if "orders" not in tables:
        return 0
    columns = _table_columns(conn, "orders")
    time_column = _first_present(columns, "created_at", "timestamp")
    if time_column is None:
        return 0
    return _count_rows(
        conn,
        f"SELECT COUNT(*) FROM orders WHERE date({time_column}) >= ?",  # noqa: S608
        (lookback_start,),
    )


def _count_fill_rows(conn: sqlite3.Connection, tables: set[str], lookback_start: str) -> int:
    if "fills" not in tables:
        return 0
    columns = _table_columns(conn, "fills")
    time_column = _first_present(columns, "created_at", "timestamp")
    if time_column is None:
        return 0
    return _count_rows(
        conn,
        f"SELECT COUNT(*) FROM fills WHERE date({time_column}) >= ?",  # noqa: S608
        (lookback_start,),
    )


def _count_closed_orders(conn: sqlite3.Connection, tables: set[str], lookback_start: str) -> int:
    if "orders" not in tables:
        return 0
    columns = _table_columns(conn, "orders")
    time_column = _first_present(columns, "created_at", "timestamp")
    if time_column is None or "size" not in columns:
        return 0
    filled_expr = "filled_size >= size" if "filled_size" in columns else "0"
    status_expr = (
        "LOWER(status) = 'filled'"
        if "status" in columns
        else "0"
    )
    return _count_rows(
        conn,
        f"""
        SELECT COUNT(*)
        FROM orders
        WHERE date({time_column}) >= ?
          AND ({status_expr} OR {filled_expr})
        """,  # noqa: S608
        (lookback_start,),
    )


def _count_risk_events(conn: sqlite3.Connection, tables: set[str], lookback_start: str) -> int:
    if "risk_events" not in tables:
        return 0
    return _count_rows(
        conn,
        "SELECT COUNT(*) FROM risk_events WHERE date(created_at) >= ?",
        (lookback_start,),
    )


def _fill_rate(
    conn: sqlite3.Connection,
    tables: set[str],
    lookback_start: str,
    paper_mode: bool | None = None,
) -> float | None:
    if "execution_stats" in tables:
        row = conn.execute(
            """
            SELECT
                SUM(CASE WHEN was_filled = 1 THEN 1 ELSE 0 END) AS filled,
                COUNT(*) AS total
            FROM execution_stats
            WHERE date(created_at) >= ?
            """,
            (lookback_start,),
        ).fetchone()
        if row is None or not row["total"]:
            return None
        return float(row["filled"] or 0) / float(row["total"])

    if "orders" not in tables:
        return None

    columns = _table_columns(conn, "orders")
    time_column = _first_present(columns, "created_at", "timestamp")
    if time_column is None:
        return None
    paper_clause, paper_params = _paper_filter(columns, paper_mode)
    filled_expr = (
        "filled_size > 0 OR LOWER(status) IN ('filled', 'partially_filled')"
        if "filled_size" in columns and "status" in columns
        else (
            "filled_size > 0"
            if "filled_size" in columns
            else (
                "LOWER(status) IN ('filled', 'partially_filled')"
                if "status" in columns
                else None
            )
        )
    )
    if filled_expr is None:
        return None
    row = conn.execute(
        f"""
        SELECT
            SUM(CASE WHEN {filled_expr} THEN 1 ELSE 0 END) AS filled,
            COUNT(*) AS total
        FROM orders
        WHERE date({time_column}) >= ?{paper_clause}
        """,  # noqa: S608
        (lookback_start, *paper_params),
    ).fetchone()
    if row is None or not row["total"]:
        return None
    return float(row["filled"] or 0) / float(row["total"])


def _avg_slippage_bps(
    conn: sqlite3.Connection,
    tables: set[str],
    lookback_start: str,
    paper_mode: bool | None = None,
) -> float | None:
    if "execution_stats" in tables:
        rows = conn.execute(
            """
            SELECT slippage_vs_mid
            FROM execution_stats
            WHERE date(created_at) >= ? AND slippage_vs_mid IS NOT NULL
            """,
            (lookback_start,),
        ).fetchall()
        if not rows:
            return None
        values = []
        for row in rows:
            value = float(row["slippage_vs_mid"])
            values.append(abs(value) * 10_000 if abs(value) <= 1 else abs(value))
        return sum(values) / len(values)

    if not {"orders", "fills"}.issubset(tables):
        return None

    order_columns = _table_columns(conn, "orders")
    fill_columns = _table_columns(conn, "fills")
    fill_time_column = _first_present(fill_columns, "created_at", "timestamp")
    fill_price_column = _first_present(fill_columns, "price", "fill_price")
    if fill_time_column is None or fill_price_column is None or "price" not in order_columns:
        return None
    if "id" in order_columns and "order_id" in fill_columns:
        join_expr = "o.id = f.order_id"
    elif "order_id" in order_columns and "order_id" in fill_columns:
        join_expr = "o.order_id = f.order_id"
    else:
        return None
    paper_clause, paper_params = _paper_filter(order_columns, paper_mode, table_alias="o")
    rows = conn.execute(
        f"""
        SELECT ABS(f.{fill_price_column} - o.price) / NULLIF(o.price, 0) * 10000.0 AS slippage_bps
        FROM fills f
        JOIN orders o ON {join_expr}
        WHERE date(f.{fill_time_column}) >= ? AND o.price > 0{paper_clause}
        """,  # noqa: S608
        (lookback_start, *paper_params),
    ).fetchall()
    values = [float(row["slippage_bps"]) for row in rows if row["slippage_bps"] is not None]
    if not values:
        return None
    return sum(values) / len(values)


def _max_drawdown_from_portfolio(conn: sqlite3.Connection, lookback_start: str) -> float:
    rows = conn.execute(
        """
        SELECT total_value_usd
        FROM portfolio_snapshots
        WHERE date >= ?
        ORDER BY date ASC
        """,
        (lookback_start,),
    ).fetchall()
    return _max_drawdown_from_values(float(row["total_value_usd"] or 0.0) for row in rows)


def _bankroll_series(
    conn: sqlite3.Connection,
    tables: set[str],
    lookback_start: str,
) -> list[float]:
    if "sizing_decisions" not in tables:
        return []
    rows = conn.execute(
        """
        SELECT bankroll
        FROM sizing_decisions
        WHERE date(created_at) >= ?
        ORDER BY created_at ASC
        """,
        (lookback_start,),
    ).fetchall()
    return [float(row["bankroll"] or 0.0) for row in rows]


def _jj_live_bankroll_series(
    conn: sqlite3.Connection,
    tables: set[str],
    lookback_start: str,
    paper_mode: bool | None = None,
) -> list[float]:
    if "cycles" in tables:
        cycle_columns = _table_columns(conn, "cycles")
        paper_clause, paper_params = _paper_filter(cycle_columns, paper_mode)
        rows = conn.execute(
            f"""
            SELECT bankroll
            FROM cycles
            WHERE date(timestamp) >= ?{paper_clause}
            ORDER BY timestamp ASC
            """,  # noqa: S608
            (lookback_start, *paper_params),
        ).fetchall()
        values = [float(row["bankroll"] or 0.0) for row in rows if row["bankroll"] is not None]
        if values:
            return values

    if "multi_bankroll" not in tables:
        return []

    columns = _table_columns(conn, "multi_bankroll")
    if "running_bankroll" not in columns or "timestamp" not in columns:
        return []
    bankroll_level_clause = ""
    if "bankroll_level" in columns:
        bankroll_level_clause = """
            AND bankroll_level = (
                SELECT MIN(bankroll_level)
                FROM multi_bankroll
                WHERE bankroll_level IS NOT NULL
            )
        """
    rows = conn.execute(
        f"""
        SELECT running_bankroll
        FROM multi_bankroll
        WHERE date(timestamp) >= ?
        {bankroll_level_clause}
        ORDER BY timestamp ASC
        """,  # noqa: S608
        (lookback_start,),
    ).fetchall()
    return [float(row["running_bankroll"] or 0.0) for row in rows if row["running_bankroll"] is not None]


def _bankroll_bounds(series: list[float]) -> tuple[float, float]:
    if not series:
        return 0.0, 0.0
    return float(series[0]), float(series[-1])


def _max_drawdown_from_bankroll(series: list[float]) -> float:
    return _max_drawdown_from_values(series)


def _max_drawdown_from_values(values: Iterable[float]) -> float:
    numbers = [float(value) for value in values]
    if not numbers:
        return 0.0
    peak = numbers[0]
    if peak <= 0:
        return 0.0
    max_drawdown = 0.0
    for total in numbers:
        peak = max(peak, total)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - total) / peak)
    return max_drawdown


def _position_win_rate(
    conn: sqlite3.Connection,
    tables: set[str],
    lookback_start: str,
) -> float | None:
    if "positions" not in tables:
        return None
    row = conn.execute(
        """
        SELECT
            SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) AS wins,
            SUM(CASE WHEN realized_pnl != 0 THEN 1 ELSE 0 END) AS closed_positions
        FROM positions
        WHERE date(updated_at) >= ?
        """,
        (lookback_start,),
    ).fetchone()
    if row is None or not row["closed_positions"]:
        return None
    return float(row["wins"] or 0) / float(row["closed_positions"])


def _trade_time_expr(columns: set[str]) -> str | None:
    if "resolved_at" in columns and "timestamp" in columns:
        return "COALESCE(resolved_at, timestamp)"
    return _first_present(columns, "resolved_at", "timestamp")


def _count_resolved_trades(
    conn: sqlite3.Connection,
    tables: set[str],
    lookback_start: str,
    *,
    paper_mode: bool | None = None,
) -> int:
    if "trades" not in tables:
        return 0
    columns = _table_columns(conn, "trades")
    time_expr = _trade_time_expr(columns)
    if time_expr is None or "outcome" not in columns:
        return 0
    paper_clause, paper_params = _paper_filter(columns, paper_mode)
    return _count_rows(
        conn,
        f"""
        SELECT COUNT(*)
        FROM trades
        WHERE outcome IS NOT NULL
          AND date({time_expr}) >= ?{paper_clause}
        """,  # noqa: S608
        (lookback_start, *paper_params),
    )


def _count_unresolved_trades(
    conn: sqlite3.Connection,
    tables: set[str],
    *,
    paper_mode: bool | None = None,
) -> int:
    if "trades" not in tables:
        return 0
    columns = _table_columns(conn, "trades")
    if "outcome" not in columns:
        return 0
    paper_clause, paper_params = _paper_filter(columns, paper_mode)
    return _count_rows(
        conn,
        f"SELECT COUNT(*) FROM trades WHERE outcome IS NULL{paper_clause}",  # noqa: S608
        paper_params,
    )


def _resolved_trade_pnl(
    conn: sqlite3.Connection,
    tables: set[str],
    lookback_start: str,
    *,
    paper_mode: bool | None = None,
) -> float:
    if "trades" not in tables:
        return 0.0
    columns = _table_columns(conn, "trades")
    time_expr = _trade_time_expr(columns)
    if time_expr is None or "outcome" not in columns or "pnl" not in columns:
        return 0.0
    paper_clause, paper_params = _paper_filter(columns, paper_mode)
    return float(
        _scalar_query(
            conn,
            f"""
            SELECT COALESCE(SUM(pnl), 0.0)
            FROM trades
            WHERE outcome IS NOT NULL
              AND date({time_expr}) >= ?{paper_clause}
            """,  # noqa: S608
            (lookback_start, *paper_params),
            default=0.0,
        )
    )


def _trade_win_rate(
    conn: sqlite3.Connection,
    tables: set[str],
    lookback_start: str,
    *,
    paper_mode: bool | None = None,
) -> float | None:
    if "trades" not in tables:
        return None
    columns = _table_columns(conn, "trades")
    time_expr = _trade_time_expr(columns)
    if time_expr is None or "outcome" not in columns:
        return None
    paper_clause, paper_params = _paper_filter(columns, paper_mode)
    row = conn.execute(
        f"""
        SELECT
            SUM(CASE WHEN outcome = 'won' THEN 1 ELSE 0 END) AS wins,
            COUNT(*) AS resolved
        FROM trades
        WHERE outcome IS NOT NULL
          AND date({time_expr}) >= ?{paper_clause}
        """,  # noqa: S608
        (lookback_start, *paper_params),
    ).fetchone()
    if row is None or not row["resolved"]:
        return None
    return float(row["wins"] or 0) / float(row["resolved"])


def _trade_brier(
    conn: sqlite3.Connection,
    tables: set[str],
    lookback_start: str,
    *,
    paper_mode: bool | None = None,
) -> float | None:
    if "trades" not in tables:
        return None
    columns = _table_columns(conn, "trades")
    time_expr = _trade_time_expr(columns)
    if time_expr is None or not {"calibrated_prob", "resolution_price", "outcome"}.issubset(columns):
        return None
    paper_clause, paper_params = _paper_filter(columns, paper_mode)
    rows = conn.execute(
        f"""
        SELECT calibrated_prob, resolution_price
        FROM trades
        WHERE outcome IS NOT NULL
          AND calibrated_prob IS NOT NULL
          AND resolution_price IS NOT NULL
          AND date({time_expr}) >= ?{paper_clause}
        """,  # noqa: S608
        (lookback_start, *paper_params),
    ).fetchall()
    values = [
        (float(row["calibrated_prob"]) - float(row["resolution_price"])) ** 2
        for row in rows
    ]
    if not values:
        return None
    return sum(values) / len(values)


def _latest_jj_live_cycle(conn: sqlite3.Connection, tables: set[str]) -> sqlite3.Row | None:
    if "cycles" not in tables:
        return None
    columns = _table_columns(conn, "cycles")
    select_parts = []
    for column in ("timestamp", "bankroll", "daily_pnl", "open_positions", "paper"):
        if column in columns:
            select_parts.append(column)
        else:
            select_parts.append(f"NULL AS {column}")
    return conn.execute(
        f"SELECT {', '.join(select_parts)} FROM cycles ORDER BY timestamp DESC LIMIT 1"  # noqa: S608
    ).fetchone()


def _latest_jj_live_daily_report(conn: sqlite3.Connection, tables: set[str]) -> sqlite3.Row | None:
    if "daily_reports" not in tables:
        return None
    columns = _table_columns(conn, "daily_reports")
    select_parts = []
    for column in ("date", "daily_pnl", "cumulative_pnl", "brier_score"):
        if column in columns:
            select_parts.append(column)
        else:
            select_parts.append(f"NULL AS {column}")
    return conn.execute(
        f"SELECT {', '.join(select_parts)} FROM daily_reports ORDER BY date DESC LIMIT 1"  # noqa: S608
    ).fetchone()


def _count_jj_live_cycles(
    conn: sqlite3.Connection,
    tables: set[str],
    lookback_start: str,
    *,
    paper_mode: bool | None = None,
) -> int:
    if "cycles" not in tables:
        return 0
    columns = _table_columns(conn, "cycles")
    paper_clause, paper_params = _paper_filter(columns, paper_mode)
    return _count_rows(
        conn,
        f"SELECT COUNT(*) FROM cycles WHERE date(timestamp) >= ?{paper_clause}",  # noqa: S608
        (lookback_start, *paper_params),
    )


def _count_jj_live_reports(conn: sqlite3.Connection, tables: set[str], lookback_start: str) -> int:
    if "daily_reports" not in tables:
        return 0
    return _count_rows(
        conn,
        "SELECT COUNT(*) FROM daily_reports WHERE date >= ?",
        (lookback_start,),
    )


def _sum_jj_live_cycle_metric(
    conn: sqlite3.Connection,
    tables: set[str],
    lookback_start: str,
    column: str,
    *,
    paper_mode: bool | None = None,
) -> int:
    if "cycles" not in tables:
        return 0
    columns = _table_columns(conn, "cycles")
    if column not in columns:
        return 0
    paper_clause, paper_params = _paper_filter(columns, paper_mode)
    return int(
        _scalar_query(
            conn,
            f"SELECT COALESCE(SUM({column}), 0) FROM cycles WHERE date(timestamp) >= ?{paper_clause}",  # noqa: S608
            (lookback_start, *paper_params),
            default=0,
        )
    )


def _jj_live_paper_mode(
    conn: sqlite3.Connection,
    tables: set[str],
    latest_cycle: sqlite3.Row | None,
) -> bool | None:
    if latest_cycle is not None and latest_cycle["paper"] is not None:
        return bool(latest_cycle["paper"])
    if "trades" not in tables:
        return None
    columns = _table_columns(conn, "trades")
    if "paper" not in columns:
        return None
    latest_value = _scalar_query(
        conn,
        "SELECT paper FROM trades ORDER BY timestamp DESC LIMIT 1",
        default=None,
    )
    if latest_value is None:
        return None
    return bool(latest_value)


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)
