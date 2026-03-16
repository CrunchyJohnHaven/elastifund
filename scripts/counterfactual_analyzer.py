#!/usr/bin/env python3
"""Replay skipped windows and estimate counterfactual skip-cost by reason."""

from __future__ import annotations

import argparse
import glob
import json
import sqlite3
import urllib.parse
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
DEFAULT_DB_GLOBS = ("data/*_maker.db",)
DEFAULT_OUTPUT_PATH = Path("data/counterfactual_report.json")
DEFAULT_TRADE_SIZE_USD = 5.0

ASSET_TO_BINANCE_SYMBOL = {
    "btc": "BTCUSDT",
    "eth": "ETHUSDT",
    "sol": "SOLUSDT",
    "bnb": "BNBUSDT",
    "doge": "DOGEUSDT",
    "xrp": "XRPUSDT",
    "ada": "ADAUSDT",
    "ltc": "LTCUSDT",
}


@dataclass
class SkipObservation:
    db_name: str
    db_path: str
    window_start_ts: int
    slug: str | None
    skip_reason: str
    direction: str | None
    direction_source: str
    delta: float | None
    best_bid: float | None
    best_ask: float | None
    ask_used: float | None
    ask_source: str | None
    resolved_side: str | None
    symbol: str
    interval: str
    implied_trade_size_usd: float


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _normalize_side(value: Any) -> str | None:
    side = str(value or "").strip().upper()
    if side in {"UP", "DOWN", "FLAT"}:
        return side
    return None


def _infer_direction(raw_direction: Any, delta: Any) -> tuple[str | None, str]:
    direct = _normalize_side(raw_direction)
    if direct in {"UP", "DOWN"}:
        return direct, "row_direction"
    parsed_delta = _safe_float(delta, None)
    if parsed_delta is None:
        return None, "missing"
    if parsed_delta > 0:
        return "UP", "delta_sign"
    if parsed_delta < 0:
        return "DOWN", "delta_sign"
    return None, "delta_zero"


def _valid_ask(value: Any) -> float | None:
    parsed = _safe_float(value, None)
    if parsed is None:
        return None
    if parsed <= 0.0 or parsed >= 1.0:
        return None
    return float(parsed)


def _normalize_interval(value: Any, default: str = "5m") -> str:
    text = str(value or "").strip().lower()
    if not text:
        return default
    if text.endswith("m") and text[:-1].isdigit():
        return text
    if text.endswith("h") and text[:-1].isdigit():
        return text
    return default


def _interval_seconds(interval: str) -> int | None:
    text = _normalize_interval(interval, "")
    if text.endswith("m") and text[:-1].isdigit():
        return int(text[:-1]) * 60
    if text.endswith("h") and text[:-1].isdigit():
        return int(text[:-1]) * 3600
    return None


def _extract_market_meta(slug: str | None, db_path: Path) -> tuple[str, str]:
    # Defaults are intentionally conservative and mirror BTC5 baseline behavior.
    fallback_asset = db_path.name.split("_", 1)[0].strip().lower() or "btc"
    fallback_minutes = "5m"
    parts = db_path.name.lower().split("_")
    if len(parts) >= 2 and parts[1].endswith("min") and parts[1][:-3].isdigit():
        fallback_minutes = f"{parts[1][:-3]}m"

    raw_slug = str(slug or "").strip().lower()
    if "-updown-" not in raw_slug:
        asset = fallback_asset
        symbol = ASSET_TO_BINANCE_SYMBOL.get(asset, f"{asset.upper()}USDT")
        return symbol, fallback_minutes

    # Expected format: "<asset>-updown-<minutes>m-<ts>".
    before, after = raw_slug.split("-updown-", 1)
    asset = before.strip() or fallback_asset
    minutes_token = after.split("-", 1)[0].strip()
    interval = _normalize_interval(minutes_token, fallback_minutes)
    symbol = ASSET_TO_BINANCE_SYMBOL.get(asset, f"{asset.upper()}USDT")
    return symbol, interval


def _fetch_binance_outcomes_for_group(
    *,
    symbol: str,
    interval: str,
    requested_window_starts: set[int],
    timeout_seconds: float,
) -> dict[int, str]:
    if not requested_window_starts:
        return {}

    interval_secs = _interval_seconds(interval)
    if interval_secs is None or interval_secs <= 0:
        return {}

    start_ts = min(requested_window_starts)
    end_ts = max(requested_window_starts)
    cursor_ms = int(start_ts * 1000)
    hard_end_ms = int((end_ts + interval_secs) * 1000)

    outcomes: dict[int, str] = {}
    while cursor_ms <= hard_end_ms:
        query = urllib.parse.urlencode(
            {
                "symbol": symbol,
                "interval": interval,
                "startTime": cursor_ms,
                "endTime": hard_end_ms,
                "limit": 1000,
            }
        )
        request = Request(
            f"{BINANCE_KLINES_URL}?{query}",
            headers={
                "User-Agent": "elastifund-counterfactual-analyzer/1.0",
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:  # nosec B310
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError):
            break

        if not isinstance(payload, list) or not payload:
            break

        last_open_ms = cursor_ms
        for kline in payload:
            if not isinstance(kline, list) or len(kline) < 5:
                continue
            open_ms = _safe_int(kline[0], 0)
            open_px = _safe_float(kline[1], None)
            close_px = _safe_float(kline[4], None)
            if open_ms <= 0 or open_px is None or close_px is None:
                continue
            window_start = open_ms // 1000
            if window_start not in requested_window_starts:
                continue
            if close_px > open_px:
                outcomes[window_start] = "UP"
            elif close_px < open_px:
                outcomes[window_start] = "DOWN"
            else:
                outcomes[window_start] = "FLAT"
            last_open_ms = max(last_open_ms, open_ms)

        if len(payload) < 1000:
            break
        # Advance to the next candle open to avoid duplicate pages.
        cursor_ms = last_open_ms + (interval_secs * 1000)

    return outcomes


def _fetch_missing_outcomes(
    observations: list[SkipObservation],
    *,
    timeout_seconds: float,
) -> dict[tuple[str, str, int], str]:
    needed: dict[tuple[str, str], set[int]] = defaultdict(set)
    for obs in observations:
        if obs.resolved_side in {"UP", "DOWN", "FLAT"}:
            continue
        needed[(obs.symbol, obs.interval)].add(int(obs.window_start_ts))

    fetched: dict[tuple[str, str, int], str] = {}
    for (symbol, interval), starts in needed.items():
        outcomes = _fetch_binance_outcomes_for_group(
            symbol=symbol,
            interval=interval,
            requested_window_starts=starts,
            timeout_seconds=timeout_seconds,
        )
        for window_start_ts, side in outcomes.items():
            fetched[(symbol, interval, int(window_start_ts))] = side
    return fetched


def _existing_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row[1]) for row in rows}


def _load_window_rows(db_path: Path) -> list[dict[str, Any]]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        columns = _existing_columns(conn, "window_trades")
        if not columns:
            return []

        wanted = (
            "id",
            "window_start_ts",
            "slug",
            "direction",
            "delta",
            "best_bid",
            "best_ask",
            "order_status",
            "resolved_side",
            "trade_size_usd",
        )

        select_bits: list[str] = []
        for name in wanted:
            if name in columns:
                select_bits.append(name)
            else:
                select_bits.append(f"NULL AS {name}")
        query = (
            f"SELECT {', '.join(select_bits)} "
            "FROM window_trades ORDER BY window_start_ts ASC, id ASC"
        )
        rows = conn.execute(query).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _simulate_pnl(
    *,
    direction: str,
    resolved_side: str,
    ask: float,
    trade_size_usd: float,
) -> tuple[int, float, float]:
    won = 1 if direction == resolved_side else 0
    pnl_per_share = (1.0 - ask) if won else -ask
    pnl_usd = (trade_size_usd * ((1.0 / ask) - 1.0)) if won else -trade_size_usd
    return won, pnl_per_share, pnl_usd


def _counterfactual_summary(observations: list[SkipObservation]) -> dict[str, Any]:
    by_reason: dict[str, dict[str, Any]] = {}

    def _init_bucket() -> dict[str, Any]:
        return {
            "skip_windows": 0,
            "priced_windows": 0,
            "directional_windows": 0,
            "resolved_windows": 0,
            "simulated_trades": 0,
            "wins": 0,
            "losses": 0,
            "flats": 0,
            "pnl_per_share_total_usd": 0.0,
            "pnl_usd_total": 0.0,
            "ask_sum": 0.0,
            "ask_source_counts": Counter(),
            "db_counts": Counter(),
            "direction_source_counts": Counter(),
        }

    for obs in observations:
        bucket = by_reason.setdefault(obs.skip_reason, _init_bucket())
        bucket["skip_windows"] += 1
        bucket["db_counts"][obs.db_name] += 1
        bucket["direction_source_counts"][obs.direction_source] += 1

        if obs.ask_used is not None:
            bucket["priced_windows"] += 1
            bucket["ask_sum"] += float(obs.ask_used)
        if obs.ask_source:
            bucket["ask_source_counts"][obs.ask_source] += 1

        if obs.direction in {"UP", "DOWN"}:
            bucket["directional_windows"] += 1
        if obs.resolved_side in {"UP", "DOWN", "FLAT"}:
            bucket["resolved_windows"] += 1

        if obs.resolved_side == "FLAT":
            bucket["flats"] += 1
            continue

        if (
            obs.direction in {"UP", "DOWN"}
            and obs.resolved_side in {"UP", "DOWN"}
            and obs.ask_used is not None
        ):
            won, pnl_per_share, pnl_usd = _simulate_pnl(
                direction=obs.direction,
                resolved_side=obs.resolved_side,
                ask=obs.ask_used,
                trade_size_usd=obs.implied_trade_size_usd,
            )
            bucket["simulated_trades"] += 1
            if won:
                bucket["wins"] += 1
            else:
                bucket["losses"] += 1
            bucket["pnl_per_share_total_usd"] += pnl_per_share
            bucket["pnl_usd_total"] += pnl_usd

    final: dict[str, Any] = {}
    for reason, bucket in by_reason.items():
        simulated = int(bucket["simulated_trades"])
        wins = int(bucket["wins"])
        losses = int(bucket["losses"])
        avg_ask = (
            float(bucket["ask_sum"]) / float(bucket["priced_windows"])
            if int(bucket["priced_windows"]) > 0
            else None
        )
        final[reason] = {
            "skip_windows": int(bucket["skip_windows"]),
            "priced_windows": int(bucket["priced_windows"]),
            "directional_windows": int(bucket["directional_windows"]),
            "resolved_windows": int(bucket["resolved_windows"]),
            "simulated_trades": simulated,
            "wins": wins,
            "losses": losses,
            "flats": int(bucket["flats"]),
            "win_rate": (wins / simulated) if simulated else None,
            "pnl_per_share_total_usd": round(float(bucket["pnl_per_share_total_usd"]), 6),
            "pnl_usd_total": round(float(bucket["pnl_usd_total"]), 6),
            "avg_ask_used": round(avg_ask, 6) if avg_ask is not None else None,
            "ask_source_counts": dict(sorted(bucket["ask_source_counts"].items())),
            "db_counts": dict(sorted(bucket["db_counts"].items())),
            "direction_source_counts": dict(sorted(bucket["direction_source_counts"].items())),
        }
    return dict(sorted(final.items(), key=lambda item: item[0]))


def _expand_db_paths(db_globs: Sequence[str], explicit_dbs: Sequence[str]) -> list[Path]:
    resolved: dict[str, Path] = {}
    for token in explicit_dbs:
        candidate = Path(token)
        if candidate.exists():
            resolved[str(candidate.resolve())] = candidate.resolve()

    for pattern in db_globs:
        for raw in glob.glob(pattern):
            candidate = Path(raw)
            if candidate.exists():
                resolved[str(candidate.resolve())] = candidate.resolve()

    return sorted(resolved.values(), key=lambda path: path.name)


def build_counterfactual_report(
    *,
    db_paths: Sequence[Path],
    trade_size_usd: float,
    use_last_known_ask_for_bad_book: bool,
    enable_binance_backfill: bool,
    binance_timeout_seconds: float,
) -> dict[str, Any]:
    observations: list[SkipObservation] = []
    skipped_db_reasons: dict[str, str] = {}

    for db_path in db_paths:
        try:
            rows = _load_window_rows(db_path)
        except sqlite3.Error as exc:
            skipped_db_reasons[str(db_path)] = f"sqlite_error:{exc.__class__.__name__}"
            continue

        if not rows:
            skipped_db_reasons[str(db_path)] = "no_window_trades_rows"
            continue

        last_known_ask_any: float | None = None
        last_known_ask_by_direction: dict[str, float] = {}
        for row in rows:
            status = str(row.get("order_status") or "").strip().lower()
            direction, direction_source = _infer_direction(row.get("direction"), row.get("delta"))
            ask = _valid_ask(row.get("best_ask"))
            if ask is not None:
                last_known_ask_any = ask
                if direction in {"UP", "DOWN"}:
                    last_known_ask_by_direction[direction] = ask

            if not status.startswith("skip_"):
                continue

            ask_used = ask
            ask_source = "best_ask" if ask is not None else None
            if ask_used is None and status == "skip_bad_book" and use_last_known_ask_for_bad_book:
                if direction in {"UP", "DOWN"} and direction in last_known_ask_by_direction:
                    ask_used = last_known_ask_by_direction[direction]
                    ask_source = "last_known_directional_ask"
                elif last_known_ask_any is not None:
                    ask_used = last_known_ask_any
                    ask_source = "last_known_any_ask"

            symbol, interval = _extract_market_meta(row.get("slug"), db_path)
            resolved_side = _normalize_side(row.get("resolved_side"))
            implied_trade_size_usd = max(0.01, float(trade_size_usd))

            observations.append(
                SkipObservation(
                    db_name=db_path.name,
                    db_path=str(db_path),
                    window_start_ts=_safe_int(row.get("window_start_ts"), 0),
                    slug=str(row.get("slug")) if row.get("slug") is not None else None,
                    skip_reason=status,
                    direction=direction,
                    direction_source=direction_source,
                    delta=_safe_float(row.get("delta"), None),
                    best_bid=_safe_float(row.get("best_bid"), None),
                    best_ask=ask,
                    ask_used=ask_used,
                    ask_source=ask_source,
                    resolved_side=resolved_side,
                    symbol=symbol,
                    interval=interval,
                    implied_trade_size_usd=implied_trade_size_usd,
                )
            )

    if enable_binance_backfill and observations:
        fetched = _fetch_missing_outcomes(observations, timeout_seconds=binance_timeout_seconds)
        for obs in observations:
            if obs.resolved_side in {"UP", "DOWN", "FLAT"}:
                continue
            obs.resolved_side = fetched.get((obs.symbol, obs.interval, int(obs.window_start_ts)))

    by_reason = _counterfactual_summary(observations)

    total_simulated = sum(int(bucket["simulated_trades"]) for bucket in by_reason.values())
    total_wins = sum(int(bucket["wins"]) for bucket in by_reason.values())
    total_pnl = round(sum(float(bucket["pnl_usd_total"]) for bucket in by_reason.values()), 6)
    summary_lines = []
    for reason, bucket in sorted(
        by_reason.items(),
        key=lambda item: (
            float(item[1].get("pnl_usd_total") or 0.0),
            int(item[1].get("simulated_trades") or 0),
        ),
        reverse=True,
    ):
        wr = bucket.get("win_rate")
        wr_text = "n/a" if wr is None else f"{100.0 * float(wr):.2f}%"
        summary_lines.append(
            (
                f"If we'd traded all {reason} windows: "
                f"simulated={bucket['simulated_trades']}, WR={wr_text}, "
                f"counterfactual_pnl_usd={bucket['pnl_usd_total']:.4f}"
            )
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "trade_size_usd_assumption": float(trade_size_usd),
        "db_paths": [str(path) for path in db_paths],
        "skipped_db_reasons": skipped_db_reasons,
        "skip_windows_analyzed": len(observations),
        "overall": {
            "simulated_trades": total_simulated,
            "wins": total_wins,
            "losses": total_simulated - total_wins,
            "win_rate": (total_wins / total_simulated) if total_simulated else None,
            "counterfactual_pnl_usd": total_pnl,
        },
        "by_skip_reason": by_reason,
        "summary_lines": summary_lines,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db-glob",
        action="append",
        default=list(DEFAULT_DB_GLOBS),
        help="Glob for maker DBs (repeatable). Default: data/*_maker.db",
    )
    parser.add_argument(
        "--db",
        action="append",
        default=[],
        help="Explicit DB path to include (repeatable).",
    )
    parser.add_argument(
        "--trade-size-usd",
        type=float,
        default=DEFAULT_TRADE_SIZE_USD,
        help="Per-trade notional assumption for counterfactual PnL.",
    )
    parser.add_argument(
        "--disable-last-known-ask-fallback",
        action="store_true",
        help="Disable last-known ask fallback for skip_bad_book rows.",
    )
    parser.add_argument(
        "--disable-binance-backfill",
        action="store_true",
        help="Disable Binance kline backfill for rows missing resolved_side.",
    )
    parser.add_argument(
        "--binance-timeout-seconds",
        type=float,
        default=8.0,
        help="Binance HTTP timeout per request.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Output JSON path.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db_paths = _expand_db_paths(args.db_glob, args.db)
    if not db_paths:
        raise SystemExit("No DB files matched --db/--db-glob.")

    report = build_counterfactual_report(
        db_paths=db_paths,
        trade_size_usd=max(0.01, float(args.trade_size_usd)),
        use_last_known_ask_for_bad_book=not bool(args.disable_last_known_ask_fallback),
        enable_binance_backfill=not bool(args.disable_binance_backfill),
        binance_timeout_seconds=max(1.0, float(args.binance_timeout_seconds)),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["overall"], indent=2))
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
