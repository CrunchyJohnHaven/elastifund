#!/usr/bin/env python3
"""Emit a per-source trade attribution summary from jj_state.json and/or jj_trades.db."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from bot.combinatorial_integration import canonical_source_key, normalize_source_components

DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "jj_trades.db"
DEFAULT_STATE_PATH = PROJECT_ROOT / "jj_state.json"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "reports" / "signal_attribution.json"


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _load_jsonish(raw: Any) -> Any:
    if not isinstance(raw, str):
        return raw
    text = raw.strip()
    if not text:
        return raw
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return raw


def _decode_sources(payload: Mapping[str, Any]) -> list[str]:
    raw_sources = payload.get("signal_sources")
    if raw_sources in (None, "", [], (), set()):
        raw_sources = payload.get("signal_sources_json")
    if raw_sources in (None, "", [], (), set()):
        raw_sources = payload.get("source_components_json")
    if raw_sources in (None, "", [], (), set()):
        raw_sources = payload.get("source_components")
    if raw_sources in (None, "", [], (), set()):
        raw_sources = payload.get("source_combo") or payload.get("source") or ""

    sources = list(normalize_source_components(_load_jsonish(raw_sources)))
    if sources:
        return sources

    primary = canonical_source_key(str(payload.get("source") or ""))
    if primary and primary != "unknown":
        return [primary]
    return []


def _load_state_snapshot(state_path: Path) -> dict[str, Any]:
    if not state_path.exists():
        return {
            "state_file_exists": False,
            "open_positions": 0,
            "trade_log_entries": 0,
            "trade_log_has_signal_sources": False,
            "trade_log_has_signal_metadata": False,
        }

    payload = json.loads(state_path.read_text())
    trade_log = payload.get("trade_log") or []
    open_positions = payload.get("open_positions") or {}
    return {
        "state_file_exists": True,
        "open_positions": len(open_positions) if isinstance(open_positions, dict) else 0,
        "trade_log_entries": len(trade_log) if isinstance(trade_log, list) else 0,
        "trade_log_has_signal_sources": all(
            isinstance(entry, dict) and "signal_sources" in entry for entry in trade_log
        )
        if isinstance(trade_log, list)
        else False,
        "trade_log_has_signal_metadata": all(
            isinstance(entry, dict) and "signal_metadata" in entry for entry in trade_log
        )
        if isinstance(trade_log, list)
        else False,
    }


def _load_state_rows(state_path: Path) -> list[dict[str, Any]]:
    if not state_path.exists():
        return []
    payload = json.loads(state_path.read_text())
    trade_log = payload.get("trade_log")
    if not isinstance(trade_log, list):
        return []
    return [dict(entry) for entry in trade_log if isinstance(entry, dict)]


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _load_db_rows(db_path: Path) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        if not _table_exists(conn, "trades"):
            return []

        columns = {row[1] for row in conn.execute("PRAGMA table_info(trades)").fetchall()}

        def _column(name: str) -> str:
            return name if name in columns else f"NULL AS {name}"

        rows = conn.execute(
            f"""
            SELECT
                {_column("timestamp")},
                {_column("market_id")},
                {_column("question")},
                {_column("direction")},
                {_column("edge")},
                {_column("confidence")},
                {_column("source")},
                {_column("source_combo")},
                {_column("signal_sources_json")},
                {_column("source_components_json")},
                {_column("outcome")},
                {_column("pnl")}
            FROM trades
            ORDER BY timestamp ASC
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _empty_bucket() -> dict[str, Any]:
    return {
        "trade_count": 0,
        "resolved_trade_count": 0,
        "wins": 0,
        "losses": 0,
        "unresolved_trade_count": 0,
        "total_pnl": 0.0,
        "_edge_sum": 0.0,
        "_confidence_sum": 0.0,
    }


def _update_bucket(bucket: dict[str, Any], row: Mapping[str, Any]) -> None:
    bucket["trade_count"] += 1
    bucket["_edge_sum"] += _safe_float(row.get("edge"))
    bucket["_confidence_sum"] += _safe_float(row.get("confidence"))

    outcome = str(row.get("outcome") or "").strip().lower()
    if outcome == "won":
        bucket["resolved_trade_count"] += 1
        bucket["wins"] += 1
    elif outcome == "lost":
        bucket["resolved_trade_count"] += 1
        bucket["losses"] += 1
    else:
        bucket["unresolved_trade_count"] += 1

    bucket["total_pnl"] += _safe_float(row.get("pnl"))


def _finalize_bucket(bucket: Mapping[str, Any]) -> dict[str, Any]:
    trade_count = int(bucket["trade_count"])
    resolved = int(bucket["resolved_trade_count"])
    wins = int(bucket["wins"])
    total_pnl = round(_safe_float(bucket["total_pnl"]), 6)
    return {
        "trade_count": trade_count,
        "resolved_trade_count": resolved,
        "wins": wins,
        "losses": int(bucket["losses"]),
        "unresolved_trade_count": int(bucket["unresolved_trade_count"]),
        "win_rate": (wins / resolved) if resolved > 0 else None,
        "avg_edge": round(bucket["_edge_sum"] / trade_count, 6) if trade_count > 0 else 0.0,
        "avg_confidence": round(bucket["_confidence_sum"] / trade_count, 6) if trade_count > 0 else 0.0,
        "total_pnl": total_pnl,
    }


def build_signal_attribution_report(
    *,
    db_path: Path = DEFAULT_DB_PATH,
    state_path: Path = DEFAULT_STATE_PATH,
) -> dict[str, Any]:
    db_rows = _load_db_rows(db_path)
    state_rows = _load_state_rows(state_path)
    source_basis = "db" if db_rows else "state"
    rows = db_rows or state_rows

    by_source: dict[str, dict[str, Any]] = {}
    resolved_trades = 0
    unresolved_trades = 0

    for row in rows:
        sources = _decode_sources(row) or ["unknown"]
        outcome = str(row.get("outcome") or "").strip().lower()
        if outcome in {"won", "lost"}:
            resolved_trades += 1
        else:
            unresolved_trades += 1

        for source in sources:
            bucket = by_source.setdefault(source, _empty_bucket())
            _update_bucket(bucket, row)

    finalized_sources = {
        source: _finalize_bucket(bucket)
        for source, bucket in sorted(
            by_source.items(),
            key=lambda item: (-int(item[1]["trade_count"]), item[0]),
        )
    }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "db_path": str(db_path),
            "state_path": str(state_path),
            "source_basis": source_basis,
        },
        "trade_totals": {
            "unique_trade_count": len(rows),
            "resolved_trade_count": resolved_trades,
            "unresolved_trade_count": unresolved_trades,
        },
        "state_snapshot": _load_state_snapshot(state_path),
        "by_source": finalized_sources,
    }


def write_signal_attribution_report(
    payload: Mapping[str, Any],
    *,
    output_path: Path = DEFAULT_OUTPUT_PATH,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a per-source signal attribution summary.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="SQLite trade DB path")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH, help="JJ state JSON path")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH, help="Output JSON path")
    args = parser.parse_args()

    payload = build_signal_attribution_report(db_path=args.db, state_path=args.state)
    output_path = write_signal_attribution_report(payload, output_path=args.output)
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
