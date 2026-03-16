#!/usr/bin/env python3
"""Cross-asset lead/lag scanner for 5m maker windows.

Scans resolved windows across BTC/ETH/SOL/BNB/DOGE/XRP maker DBs, identifies
which asset signaled first per shared window_start_ts, and computes follower lag
statistics using decision_ts.

Primary output contract:
  data/cross_asset_leadlag.json

Default runtime mode is continuous (every 5 minutes), with --once for one-shot.
"""

from __future__ import annotations

import argparse
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import logging
from pathlib import Path
import sqlite3
import time
from typing import Any


LOGGER = logging.getLogger("JJ.cross_asset_arb")

ASSET_ORDER: tuple[str, ...] = ("BTC", "ETH", "SOL", "BNB", "DOGE", "XRP")
DEFAULT_DB_PATHS: dict[str, Path] = {
    "BTC": Path("data/btc_5min_maker.db"),
    "ETH": Path("data/eth_5min_maker.db"),
    "SOL": Path("data/sol_5min_maker.db"),
    "BNB": Path("data/bnb_5min_maker.db"),
    "DOGE": Path("data/doge_5min_maker.db"),
    "XRP": Path("data/xrp_5min_maker.db"),
}

DEFAULT_CONFIG_PATH = Path("config/multi_asset_slugs.json")
DEFAULT_OUTPUT_PATH = Path("data/cross_asset_leadlag.json")
DEFAULT_INTERVAL_SECONDS = 300
DEFAULT_BTC_FIRST_DELTA_THRESHOLD = 0.002


@dataclass(frozen=True)
class SignalRow:
    asset: str
    window_start_ts: int
    decision_ts: int
    delta: float
    abs_delta: float
    direction: str
    resolved_side: str
    order_status: str


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _resolve_path(path: Path, *, root: Path) -> Path:
    return path if path.is_absolute() else (root / path)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return int(default)
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return float(values[0])
    quantile = max(0.0, min(1.0, float(q)))
    ordered = sorted(float(v) for v in values)
    index = quantile * (len(ordered) - 1)
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    if lower == upper:
        return float(ordered[lower])
    weight = index - lower
    return float(ordered[lower] * (1.0 - weight) + ordered[upper] * weight)


def _lag_summary(lags_seconds: list[int]) -> dict[str, Any] | None:
    if not lags_seconds:
        return None
    ordered = [int(x) for x in sorted(lags_seconds)]
    count = len(ordered)
    mean = sum(ordered) / count
    p50 = _percentile([float(x) for x in ordered], 0.50)
    p90 = _percentile([float(x) for x in ordered], 0.90)
    return {
        "count": count,
        "min": int(ordered[0]),
        "max": int(ordered[-1]),
        "mean": round(float(mean), 3),
        "median": round(float(p50), 3) if p50 is not None else None,
        "p90": round(float(p90), 3) if p90 is not None else None,
    }


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ? LIMIT 1",
        (str(table_name),),
    ).fetchone()
    return row is not None


def _read_config_db_paths(config_path: Path) -> dict[str, Path]:
    if not config_path.exists():
        return {}
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    assets_payload = payload.get("assets")
    if not isinstance(assets_payload, dict):
        return {}

    paths: dict[str, Path] = {}
    for item in assets_payload.values():
        if not isinstance(item, dict):
            continue
        asset = str(item.get("asset_slug_prefix") or "").strip().upper()
        db_raw = str(item.get("db") or "").strip()
        if asset in ASSET_ORDER and db_raw:
            paths[asset] = Path(db_raw)
    return paths


def _parse_asset_db_overrides(values: list[str]) -> dict[str, Path]:
    overrides: dict[str, Path] = {}
    for raw in values:
        token = str(raw or "").strip()
        if not token:
            continue
        if "=" not in token:
            raise ValueError(f"--asset-db entry must be asset=path, got {raw!r}")
        asset_raw, path_raw = token.split("=", 1)
        asset = asset_raw.strip().upper()
        path_value = path_raw.strip()
        if asset not in ASSET_ORDER:
            raise ValueError(f"--asset-db asset must be one of {ASSET_ORDER}, got {asset!r}")
        if not path_value:
            raise ValueError(f"--asset-db path is empty for asset {asset}")
        overrides[asset] = Path(path_value)
    return overrides


def _load_resolved_rows(db_path: Path, *, asset: str) -> tuple[list[SignalRow], str | None]:
    if not db_path.exists():
        return [], "db_missing"
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
    except sqlite3.Error as exc:
        return [], f"connect_failed:{exc}"

    try:
        if not _table_exists(conn, "window_trades"):
            return [], "missing_window_trades_table"
        rows = conn.execute(
            """
            SELECT
                window_start_ts,
                decision_ts,
                delta,
                direction,
                resolved_side,
                order_status
            FROM window_trades
            WHERE window_start_ts IS NOT NULL
              AND decision_ts IS NOT NULL
              AND resolved_side IS NOT NULL
            ORDER BY window_start_ts ASC
            """
        ).fetchall()
    except sqlite3.Error as exc:
        return [], f"query_failed:{exc}"
    finally:
        conn.close()

    out: list[SignalRow] = []
    for row in rows:
        window_start_ts = _safe_int(row["window_start_ts"], default=0)
        decision_ts = _safe_int(row["decision_ts"], default=0)
        if window_start_ts <= 0 or decision_ts <= 0:
            continue
        delta = _safe_float(row["delta"], default=0.0)
        out.append(
            SignalRow(
                asset=asset,
                window_start_ts=window_start_ts,
                decision_ts=decision_ts,
                delta=delta,
                abs_delta=abs(delta),
                direction=str(row["direction"] or "").strip().upper(),
                resolved_side=str(row["resolved_side"] or "").strip().upper(),
                order_status=str(row["order_status"] or "").strip().lower(),
            )
        )
    return out, None


def build_leadlag_payload(
    *,
    root: Path,
    db_paths: dict[str, Path],
    btc_first_delta_threshold: float,
    window_details_limit: int,
) -> dict[str, Any]:
    resolved_db_paths = {
        asset: _resolve_path(path, root=root).resolve()
        for asset, path in db_paths.items()
    }

    windows: dict[int, dict[str, SignalRow]] = defaultdict(dict)
    missing_assets: list[str] = []
    query_errors: dict[str, str] = {}
    per_asset_rows: dict[str, int] = {}
    total_resolved_rows = 0

    for asset in ASSET_ORDER:
        db_path = resolved_db_paths[asset]
        rows, error = _load_resolved_rows(db_path, asset=asset)
        if error is not None:
            query_errors[asset] = error
            if error == "db_missing":
                missing_assets.append(asset)
        per_asset_rows[asset] = len(rows)
        total_resolved_rows += len(rows)
        for row in rows:
            windows[row.window_start_ts][asset] = row

    leader_first_windows: dict[str, int] = {asset: 0 for asset in ASSET_ORDER}
    unique_first_windows: dict[str, int] = {asset: 0 for asset in ASSET_ORDER}
    tied_first_windows = 0
    pair_lags: dict[tuple[str, str], list[int]] = defaultdict(list)
    btc_follow_lags: dict[str, list[int]] = defaultdict(list)
    btc_qualifying_windows = 0
    window_samples: deque[dict[str, Any]] = deque(maxlen=max(0, int(window_details_limit)))

    multi_asset_window_count = 0
    all_asset_window_count = 0
    windows_sorted = sorted(windows.keys())
    for window_start_ts in windows_sorted:
        bucket = windows[window_start_ts]
        if len(bucket) < 2:
            continue
        multi_asset_window_count += 1
        if len(bucket) == len(ASSET_ORDER):
            all_asset_window_count += 1

        first_decision_ts = min(sig.decision_ts for sig in bucket.values())
        first_assets = sorted(
            asset for asset, sig in bucket.items() if sig.decision_ts == first_decision_ts
        )

        for leader in first_assets:
            leader_first_windows[leader] += 1
            for follower, sig in bucket.items():
                if follower == leader:
                    continue
                lag = max(0, int(sig.decision_ts - first_decision_ts))
                pair_lags[(leader, follower)].append(lag)
        if len(first_assets) == 1:
            unique_first_windows[first_assets[0]] += 1
        else:
            tied_first_windows += 1

        btc_signal = bucket.get("BTC")
        if (
            btc_signal is not None
            and "BTC" in first_assets
            and btc_signal.abs_delta >= float(btc_first_delta_threshold)
        ):
            btc_qualifying_windows += 1
            for follower in (asset for asset in ASSET_ORDER if asset != "BTC"):
                follower_signal = bucket.get(follower)
                if follower_signal is None:
                    continue
                follower_lag = max(0, int(follower_signal.decision_ts - btc_signal.decision_ts))
                btc_follow_lags[follower].append(follower_lag)

        if window_details_limit > 0:
            decisions = {
                asset: {
                    "decision_ts": sig.decision_ts,
                    "lag_vs_first_seconds": int(sig.decision_ts - first_decision_ts),
                    "delta": round(sig.delta, 8),
                    "abs_delta": round(sig.abs_delta, 8),
                    "direction": sig.direction or None,
                    "resolved_side": sig.resolved_side or None,
                    "order_status": sig.order_status or None,
                }
                for asset, sig in sorted(bucket.items())
            }
            window_samples.append(
                {
                    "window_start_ts": int(window_start_ts),
                    "asset_count": len(bucket),
                    "first_assets": first_assets,
                    "first_decision_ts": int(first_decision_ts),
                    "decisions": decisions,
                }
            )

    pair_table: list[dict[str, Any]] = []
    for leader in ASSET_ORDER:
        for follower in ASSET_ORDER:
            if leader == follower:
                continue
            lags = pair_lags.get((leader, follower), [])
            leader_windows = leader_first_windows[leader]
            pair_table.append(
                {
                    "leader_asset": leader,
                    "follower_asset": follower,
                    "leader_first_windows": leader_windows,
                    "follower_present_windows": len(lags),
                    "follower_present_rate": (
                        round(len(lags) / leader_windows, 6) if leader_windows > 0 else None
                    ),
                    "lag_seconds": _lag_summary(lags),
                }
            )

    btc_followers: dict[str, Any] = {}
    for follower in (asset for asset in ASSET_ORDER if asset != "BTC"):
        lags = btc_follow_lags.get(follower, [])
        btc_followers[follower] = {
            "windows_with_follower_data": len(lags),
            "follow_rate_of_btc_first_windows": (
                round(len(lags) / btc_qualifying_windows, 6)
                if btc_qualifying_windows > 0
                else None
            ),
            "lag_seconds": _lag_summary(lags),
        }

    unique_multi_windows = max(1, multi_asset_window_count)
    first_share = {
        asset: round(unique_first_windows[asset] / unique_multi_windows, 6)
        for asset in ASSET_ORDER
    }

    return {
        "schema_version": "cross_asset_leadlag.v1",
        "generated_at": _utc_now_iso(),
        "assets": list(ASSET_ORDER),
        "db_paths": {asset: str(path) for asset, path in resolved_db_paths.items()},
        "missing_assets": missing_assets,
        "query_errors": query_errors,
        "stats": {
            "total_resolved_rows": int(total_resolved_rows),
            "resolved_rows_by_asset": per_asset_rows,
            "unique_resolved_windows": len(windows_sorted),
            "multi_asset_windows": int(multi_asset_window_count),
            "all_asset_windows": int(all_asset_window_count),
            "tied_first_windows": int(tied_first_windows),
        },
        "first_asset_counts": unique_first_windows,
        "first_asset_share": first_share,
        "leader_first_windows_including_ties": leader_first_windows,
        "correlation_table": pair_table,
        "btc_first_threshold_follow": {
            "leader_asset": "BTC",
            "threshold_abs_delta": float(btc_first_delta_threshold),
            "qualifying_windows": int(btc_qualifying_windows),
            "followers": btc_followers,
        },
        "window_samples_recent": list(window_samples),
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _seconds_until_next_boundary(interval_seconds: int) -> float:
    interval = max(1, int(interval_seconds))
    now = time.time()
    wait = interval - (now % interval)
    if wait <= 0.001:
        return float(interval)
    return float(wait)


def run_loop(
    *,
    root: Path,
    db_paths: dict[str, Path],
    output_path: Path,
    interval_seconds: int,
    btc_first_delta_threshold: float,
    window_details_limit: int,
    once: bool,
) -> int:
    while True:
        started = time.monotonic()
        try:
            payload = build_leadlag_payload(
                root=root,
                db_paths=db_paths,
                btc_first_delta_threshold=btc_first_delta_threshold,
                window_details_limit=window_details_limit,
            )
            _write_json(output_path, payload)
            duration = time.monotonic() - started
            stats = payload.get("stats") if isinstance(payload.get("stats"), dict) else {}
            LOGGER.info(
                "cross_asset_arb cycle complete: multi_asset_windows=%s all_asset_windows=%s duration=%.2fs output=%s",
                stats.get("multi_asset_windows"),
                stats.get("all_asset_windows"),
                duration,
                output_path,
            )
        except Exception:
            LOGGER.exception("cross_asset_arb cycle failed")
        if once:
            return 0
        sleep_seconds = _seconds_until_next_boundary(interval_seconds)
        LOGGER.info("sleeping %.2fs until next %ss boundary", sleep_seconds, int(interval_seconds))
        time.sleep(sleep_seconds)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--output-path", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--interval-seconds", type=int, default=DEFAULT_INTERVAL_SECONDS)
    parser.add_argument("--btc-first-delta-threshold", type=float, default=DEFAULT_BTC_FIRST_DELTA_THRESHOLD)
    parser.add_argument(
        "--window-details-limit",
        type=int,
        default=500,
        help="How many recent multi-asset windows to include in output (0 disables samples).",
    )
    parser.add_argument(
        "--asset-db",
        action="append",
        default=[],
        help="Override DB path per asset as ASSET=path (repeatable).",
    )
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit.")
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=str(args.log_level).upper(),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    root = Path(__file__).resolve().parents[1]
    config_path = _resolve_path(Path(args.config), root=root)
    output_path = _resolve_path(Path(args.output_path), root=root)

    db_paths = dict(DEFAULT_DB_PATHS)
    db_paths.update(_read_config_db_paths(config_path))
    try:
        db_paths.update(_parse_asset_db_overrides(args.asset_db))
    except ValueError as exc:
        LOGGER.error(str(exc))
        return 2

    return run_loop(
        root=root,
        db_paths=db_paths,
        output_path=output_path,
        interval_seconds=max(1, int(args.interval_seconds)),
        btc_first_delta_threshold=max(0.0, float(args.btc_first_delta_threshold)),
        window_details_limit=max(0, int(args.window_details_limit)),
        once=bool(args.once),
    )


if __name__ == "__main__":
    raise SystemExit(main())
