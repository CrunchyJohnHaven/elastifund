#!/usr/bin/env python3
"""Compare shadow signal lanes against BTC5 live fills.

Reads:
  - data/shadow_signals.db (shadow signals from wallet-flow and LMSR)
  - data/btc_5min_maker.db (BTC5 live fills)

Produces:
  - reports/shadow_vs_live_comparison.json (machine-readable)
  - reports/shadow_vs_live_comparison.md  (human-readable)

Usage:
  python scripts/compare_shadow_vs_live.py
  python scripts/compare_shadow_vs_live.py --since 2026-03-14
  python scripts/compare_shadow_vs_live.py --output-dir reports/
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


SHADOW_DB = Path("data/shadow_signals.db")
BTC5_DB = Path("data/btc_5min_maker.db")
OUTPUT_DIR = Path("reports")


def _connect(path: Path) -> Optional[sqlite3.Connection]:
    if not path.exists():
        return None
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def _get_shadow_summary(
    conn: sqlite3.Connection, lane: str, since: Optional[str] = None
) -> dict[str, Any]:
    """Aggregate shadow lane statistics."""
    where = "WHERE lane=?"
    params: list[Any] = [lane]
    if since:
        where += " AND timestamp_utc >= ?"
        params.append(since)

    total = conn.execute(
        f"SELECT COUNT(*) FROM shadow_signals {where}", params
    ).fetchone()[0]

    resolved = conn.execute(
        f"SELECT COUNT(*) FROM shadow_signals {where} AND resolved=1", params
    ).fetchone()[0]

    pnl = conn.execute(
        f"SELECT COALESCE(SUM(hypothetical_pnl), 0) FROM shadow_signals {where} AND resolved=1",
        params,
    ).fetchone()[0]

    wins = conn.execute(
        f"SELECT COUNT(*) FROM shadow_signals {where} AND resolved=1 AND hypothetical_pnl > 0",
        params,
    ).fetchone()[0]

    avg_edge = conn.execute(
        f"SELECT COALESCE(AVG(edge), 0) FROM shadow_signals {where}", params
    ).fetchone()[0]

    avg_conf = conn.execute(
        f"SELECT COALESCE(AVG(confidence), 0) FROM shadow_signals {where}", params
    ).fetchone()[0]

    return {
        "lane": lane,
        "total_signals": total,
        "resolved": resolved,
        "wins": wins,
        "losses": resolved - wins,
        "win_rate": round(wins / max(1, resolved), 4),
        "hypothetical_pnl": round(pnl, 4),
        "avg_edge": round(avg_edge, 4),
        "avg_confidence": round(avg_conf, 4),
    }


def _get_btc5_summary(
    conn: sqlite3.Connection, since: Optional[str] = None
) -> dict[str, Any]:
    """Aggregate BTC5 live fill statistics."""
    # Try to find the fills/cycles table
    tables = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    ]

    # Look for a fills or cycles table
    fill_table = None
    for candidate in ("fills", "cycles", "orders"):
        if candidate in tables:
            fill_table = candidate
            break

    if not fill_table:
        return {
            "lane": "btc5_live",
            "error": f"no fill table found (tables: {tables})",
            "total_fills": 0,
        }

    # Get column names to adapt query
    cols = [
        row[1]
        for row in conn.execute(f"PRAGMA table_info({fill_table})").fetchall()
    ]

    # Build adaptive query based on available columns
    pnl_col = None
    for candidate in ("pnl", "realized_pnl", "profit", "hypothetical_pnl"):
        if candidate in cols:
            pnl_col = candidate
            break

    ts_col = None
    for candidate in ("created_at", "timestamp", "timestamp_utc", "filled_at"):
        if candidate in cols:
            ts_col = candidate
            break

    status_col = None
    for candidate in ("status", "fill_status", "order_status"):
        if candidate in cols:
            status_col = candidate
            break

    where_parts = []
    params: list[Any] = []

    if since and ts_col:
        where_parts.append(f"{ts_col} >= ?")
        params.append(since)

    # Filter to live fills if status column exists
    if status_col:
        where_parts.append(
            f"{status_col} IN ('live_filled', 'live_partial_fill_cancelled')"
        )

    where = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

    total = conn.execute(
        f"SELECT COUNT(*) FROM {fill_table} {where}", params
    ).fetchone()[0]

    total_pnl = 0.0
    wins = 0
    if pnl_col:
        pnl_row = conn.execute(
            f"SELECT COALESCE(SUM({pnl_col}), 0) FROM {fill_table} {where}",
            params,
        ).fetchone()
        total_pnl = pnl_row[0] if pnl_row else 0.0

        wins = conn.execute(
            f"SELECT COUNT(*) FROM {fill_table} {where}"
            + (f" AND {pnl_col} > 0" if where else f" WHERE {pnl_col} > 0"),
            params,
        ).fetchone()[0]

    return {
        "lane": "btc5_live",
        "total_fills": total,
        "wins": wins,
        "losses": total - wins,
        "win_rate": round(wins / max(1, total), 4),
        "total_pnl": round(total_pnl, 4),
        "fill_table": fill_table,
        "pnl_column": pnl_col,
    }


def _get_overlap_analysis(
    shadow_conn: sqlite3.Connection,
    btc5_conn: sqlite3.Connection,
    since: Optional[str] = None,
) -> dict[str, Any]:
    """Check if shadow signals overlap with BTC5 markets."""
    where = ""
    params: list[Any] = []
    if since:
        where = "WHERE timestamp_utc >= ?"
        params = [since]

    shadow_markets = set()
    for row in shadow_conn.execute(
        f"SELECT DISTINCT market_id FROM shadow_signals {where}", params
    ).fetchall():
        shadow_markets.add(row[0])

    # Get BTC5 market IDs
    tables = [
        row[0]
        for row in btc5_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    ]

    btc5_markets = set()
    for table in ("fills", "cycles", "orders"):
        if table not in tables:
            continue
        cols = [
            row[1]
            for row in btc5_conn.execute(f"PRAGMA table_info({table})").fetchall()
        ]
        market_col = None
        for candidate in ("market_id", "condition_id", "token_id"):
            if candidate in cols:
                market_col = candidate
                break
        if market_col:
            for row in btc5_conn.execute(
                f"SELECT DISTINCT {market_col} FROM {table}"
            ).fetchall():
                btc5_markets.add(row[0])

    overlap = shadow_markets & btc5_markets

    return {
        "shadow_unique_markets": len(shadow_markets),
        "btc5_unique_markets": len(btc5_markets),
        "overlapping_markets": len(overlap),
        "shadow_only_markets": len(shadow_markets - btc5_markets),
        "btc5_only_markets": len(btc5_markets - shadow_markets),
    }


def generate_report(since: Optional[str] = None) -> dict[str, Any]:
    """Generate the full comparison report."""
    now = datetime.now(timezone.utc).isoformat()
    report: dict[str, Any] = {
        "generated_at": now,
        "since": since,
    }

    # Shadow signals
    shadow_conn = _connect(SHADOW_DB)
    if shadow_conn:
        report["wallet_flow"] = _get_shadow_summary(shadow_conn, "wallet_flow", since)
        report["lmsr"] = _get_shadow_summary(shadow_conn, "lmsr", since)
    else:
        report["wallet_flow"] = {"error": "shadow DB not found"}
        report["lmsr"] = {"error": "shadow DB not found"}

    # BTC5 live
    btc5_conn = _connect(BTC5_DB)
    if btc5_conn:
        report["btc5_live"] = _get_btc5_summary(btc5_conn, since)
    else:
        report["btc5_live"] = {"error": "BTC5 DB not found"}

    # Overlap
    if shadow_conn and btc5_conn:
        report["overlap"] = _get_overlap_analysis(shadow_conn, btc5_conn, since)
    else:
        report["overlap"] = {"error": "missing DB(s)"}

    # Head-to-head verdict
    lanes = []
    for key in ("wallet_flow", "lmsr", "btc5_live"):
        data = report.get(key, {})
        if "error" not in data:
            pnl = data.get("hypothetical_pnl", data.get("total_pnl", 0))
            wr = data.get("win_rate", 0)
            n = data.get("total_signals", data.get("total_fills", 0))
            lanes.append({"lane": key, "pnl": pnl, "win_rate": wr, "n": n})

    lanes.sort(key=lambda x: x["pnl"], reverse=True)
    report["ranking"] = lanes

    if shadow_conn:
        shadow_conn.close()
    if btc5_conn:
        btc5_conn.close()

    return report


def _format_markdown(report: dict) -> str:
    """Format the report as Markdown."""
    lines = [
        "# Shadow vs Live Comparison Report",
        "",
        f"Generated: {report.get('generated_at', 'unknown')}",
        f"Since: {report.get('since', 'all time')}",
        "",
        "## Lane Summary",
        "",
        "| Lane | Signals/Fills | Win Rate | P&L | Avg Edge | Avg Conf |",
        "|------|--------------|----------|-----|----------|----------|",
    ]

    for key in ("wallet_flow", "lmsr", "btc5_live"):
        data = report.get(key, {})
        if "error" in data:
            lines.append(f"| {key} | ERROR: {data['error']} | - | - | - | - |")
            continue

        n = data.get("total_signals", data.get("total_fills", 0))
        wr = data.get("win_rate", 0)
        pnl = data.get("hypothetical_pnl", data.get("total_pnl", 0))
        edge = data.get("avg_edge", "-")
        conf = data.get("avg_confidence", "-")
        pnl_label = "hyp" if key != "btc5_live" else "real"

        lines.append(
            f"| {key} | {n} | {wr:.1%} | ${pnl:.2f} ({pnl_label}) "
            f"| {edge if isinstance(edge, str) else f'{edge:.4f}'} "
            f"| {conf if isinstance(conf, str) else f'{conf:.4f}'} |"
        )

    overlap = report.get("overlap", {})
    if "error" not in overlap:
        lines.extend([
            "",
            "## Market Overlap",
            "",
            f"- Shadow unique markets: {overlap.get('shadow_unique_markets', 0)}",
            f"- BTC5 unique markets: {overlap.get('btc5_unique_markets', 0)}",
            f"- Overlapping: {overlap.get('overlapping_markets', 0)}",
            f"- Shadow-only: {overlap.get('shadow_only_markets', 0)}",
            f"- BTC5-only: {overlap.get('btc5_only_markets', 0)}",
        ])

    ranking = report.get("ranking", [])
    if ranking:
        lines.extend([
            "",
            "## Ranking (by P&L)",
            "",
        ])
        for i, lane in enumerate(ranking, 1):
            lines.append(
                f"{i}. **{lane['lane']}**: ${lane['pnl']:.2f} "
                f"(WR: {lane['win_rate']:.1%}, n={lane['n']})"
            )

    lines.extend(["", "---", "*Auto-generated by scripts/compare_shadow_vs_live.py*"])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Compare shadow vs live fills")
    parser.add_argument("--since", help="Only include signals/fills after this date (ISO)")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    report = generate_report(since=args.since)

    json_path = output_dir / "shadow_vs_live_comparison.json"
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"JSON report: {json_path}")

    md_path = output_dir / "shadow_vs_live_comparison.md"
    with open(md_path, "w") as f:
        f.write(_format_markdown(report))
    print(f"Markdown report: {md_path}")

    # Print summary
    print("\n" + _format_markdown(report))


if __name__ == "__main__":
    main()
