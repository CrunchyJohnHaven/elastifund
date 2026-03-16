#!/usr/bin/env python3
"""Verify 5-minute crypto market support across multiple assets.

This script executes the Instance-4 reconnaissance tasks:
1) ETH zero-fill diagnostics query (if the ETH sqlite DB exists locally)
2) Slug resolution + near-term book checks for ETH/SOL and peers
3) Additional asset discovery for candidate deployment
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

GAMMA_SLUG_URL = "https://gamma-api.polymarket.com/markets/slug/{slug}"
DEFAULT_ASSETS = ("btc", "eth", "sol", "xrp", "doge")
DISCOVERY_CANDIDATES = ("btc", "eth", "sol", "xrp", "doge", "bnb", "ada", "ltc")


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fetch_slug(slug: str, timeout_seconds: float) -> dict[str, Any] | None:
    url = GAMMA_SLUG_URL.format(slug=slug)
    try:
        with urlopen(url, timeout=timeout_seconds) as response:  # nosec B310 - fixed trusted domain
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    except URLError:
        return None
    return payload if isinstance(payload, dict) else None


@dataclass
class WindowSnapshot:
    window_start_ts: int
    slug: str
    exists: bool
    closed: bool | None
    active: bool | None
    accepting_orders: bool | None
    best_bid: float | None
    best_ask: float | None
    ask_in_guardrails: bool


def _window_probe(
    *,
    asset: str,
    window_timestamps: list[int],
    min_buy_price: float,
    max_buy_price: float,
    timeout_seconds: float,
) -> list[WindowSnapshot]:
    snapshots: list[WindowSnapshot] = []
    for window_start_ts in window_timestamps:
        slug = f"{asset}-updown-5m-{window_start_ts}"
        market = _fetch_slug(slug, timeout_seconds)
        if market is None:
            snapshots.append(
                WindowSnapshot(
                    window_start_ts=window_start_ts,
                    slug=slug,
                    exists=False,
                    closed=None,
                    active=None,
                    accepting_orders=None,
                    best_bid=None,
                    best_ask=None,
                    ask_in_guardrails=False,
                )
            )
            continue

        best_bid = _safe_float(market.get("bestBid"))
        best_ask = _safe_float(market.get("bestAsk"))
        ask_in_guardrails = (
            best_ask is not None
            and min_buy_price <= best_ask <= max_buy_price
        )
        snapshots.append(
            WindowSnapshot(
                window_start_ts=window_start_ts,
                slug=slug,
                exists=True,
                closed=bool(market.get("closed")),
                active=bool(market.get("active")),
                accepting_orders=bool(market.get("acceptingOrders")),
                best_bid=best_bid,
                best_ask=best_ask,
                ask_in_guardrails=ask_in_guardrails,
            )
        )
    return snapshots


def _summarize_asset(snapshots: list[WindowSnapshot]) -> dict[str, Any]:
    existing = [row for row in snapshots if row.exists]
    accepting = [row for row in existing if row.accepting_orders]
    two_sided = [
        row
        for row in accepting
        if row.best_bid is not None and row.best_ask is not None
    ]
    guardrail_ok = [row for row in two_sided if row.ask_in_guardrails]
    return {
        "windows_checked": len(snapshots),
        "windows_with_slug": len(existing),
        "accepting_orders_windows": len(accepting),
        "two_sided_book_windows": len(two_sided),
        "ask_in_guardrail_windows": len(guardrail_ok),
        "sample": [asdict(row) for row in snapshots[: min(5, len(snapshots))]],
    }


def _query_eth_recent_windows(db_path: Path) -> dict[str, Any]:
    if not db_path.exists():
        return {
            "db_path": str(db_path),
            "available": False,
            "note": "ETH maker DB is not present in this workspace; run on runtime host.",
            "rows": [],
        }

    query = (
        "SELECT order_status, best_ask, best_bid, direction, delta "
        "FROM window_trades ORDER BY window_start_ts DESC LIMIT 20"
    )
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(query)
        rows = cursor.fetchall()
    serializable_rows = [
        {
            "order_status": row[0],
            "best_ask": _safe_float(row[1]),
            "best_bid": _safe_float(row[2]),
            "direction": row[3],
            "delta": _safe_float(row[4]),
        }
        for row in rows
    ]
    status_counts: dict[str, int] = {}
    for row in serializable_rows:
        key = str(row["order_status"] or "unknown")
        status_counts[key] = status_counts.get(key, 0) + 1
    return {
        "db_path": str(db_path),
        "available": True,
        "query": query,
        "status_counts": status_counts,
        "rows": serializable_rows,
    }


def _discover_additional_assets(
    *,
    timestamp: int,
    timeout_seconds: float,
    candidates: tuple[str, ...] = DISCOVERY_CANDIDATES,
) -> dict[str, Any]:
    discovered: dict[str, Any] = {}
    for asset in candidates:
        slug = f"{asset}-updown-5m-{timestamp}"
        market = _fetch_slug(slug, timeout_seconds)
        if market is None:
            continue
        discovered[asset] = {
            "slug": slug,
            "question": market.get("question"),
            "accepting_orders": bool(market.get("acceptingOrders")),
            "best_bid": _safe_float(market.get("bestBid")),
            "best_ask": _safe_float(market.get("bestAsk")),
        }
    return discovered


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--assets",
        default=",".join(DEFAULT_ASSETS),
        help="Comma-separated asset slug prefixes to probe (default: btc,eth,sol,xrp,doge).",
    )
    parser.add_argument(
        "--minutes-ahead",
        type=int,
        default=60,
        help="How many future minutes to probe from the current 5-minute window.",
    )
    parser.add_argument(
        "--min-buy-price",
        type=float,
        default=0.90,
        help="Lower guardrail bound used for ask-in-range summaries.",
    )
    parser.add_argument(
        "--max-buy-price",
        type=float,
        default=0.95,
        help="Upper guardrail bound used for ask-in-range summaries.",
    )
    parser.add_argument(
        "--eth-db-path",
        default="data/eth_5min_maker.db",
        help="Path to ETH maker sqlite DB for zero-fill diagnostics.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=8.0,
        help="HTTP timeout for Gamma slug checks.",
    )
    parser.add_argument(
        "--output",
        default="data/multi_asset_5m_probe.json",
        help="JSON output report path.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    assets = [token.strip().lower() for token in args.assets.split(",") if token.strip()]
    if not assets:
        raise SystemExit("no assets provided")

    now_ts = int(time.time())
    current_window = (now_ts // 300) * 300
    num_windows = max(1, (args.minutes_ahead // 5) + 1)
    windows = [current_window + idx * 300 for idx in range(num_windows)]

    asset_probe: dict[str, Any] = {}
    for asset in assets:
        snapshots = _window_probe(
            asset=asset,
            window_timestamps=windows,
            min_buy_price=args.min_buy_price,
            max_buy_price=args.max_buy_price,
            timeout_seconds=args.timeout_seconds,
        )
        asset_probe[asset] = _summarize_asset(snapshots)

    discovery = _discover_additional_assets(
        timestamp=current_window,
        timeout_seconds=args.timeout_seconds,
    )
    eth_diag = _query_eth_recent_windows(Path(args.eth_db_path))

    report = {
        "generated_at_unix": now_ts,
        "current_window_start_ts": current_window,
        "guardrails": {
            "min_buy_price": args.min_buy_price,
            "max_buy_price": args.max_buy_price,
        },
        "assets_checked": assets,
        "asset_probe": asset_probe,
        "eth_zero_fill_diagnostic": eth_diag,
        "discovered_assets_current_window": discovery,
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
