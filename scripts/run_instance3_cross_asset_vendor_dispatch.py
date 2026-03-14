#!/usr/bin/env python3
"""Instance 3 runner for cross-asset history backfill and vendor ranking."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.cross_asset_vendor_dispatch import (
    ASSET_CONFIG,
    ASSET_ORDER,
    FeatureFlags,
    build_instance_artifact,
    build_vendor_stack,
    coinapi_ready,
    ensure_history_store,
    emit_finance_action_queue,
    env_text,
    insert_reference_bars,
    read_json,
    record_backfill_run,
    summarize_history_store,
    utc_now,
    write_json,
)


BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
COINAPI_OHLCV_URL = "https://rest.coinapi.io/v1/ohlcv/{symbol_id}/history"


def fetch_binance_1m_bars(*, symbol: str, start_ms: int, end_ms: int, timeout_seconds: float = 10.0) -> list[list[Any]]:
    cursor = start_ms
    rows: list[list[Any]] = []
    while cursor < end_ms:
        query = urlencode(
            {
                "symbol": symbol,
                "interval": "1m",
                "startTime": cursor,
                "endTime": end_ms,
                "limit": 1000,
            }
        )
        request = Request(f"{BINANCE_KLINES_URL}?{query}", headers={"User-Agent": "Elastifund/instance3"})
        with urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, list) or not payload:
            break
        batch = [row for row in payload if isinstance(row, list) and len(row) >= 6]
        if not batch:
            break
        rows.extend(batch)
        next_cursor = int(batch[-1][0]) + 60_000
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        if len(batch) < 1000:
            break
    return rows


def fetch_coinapi_1s_bars(
    *,
    symbol_id: str,
    start_dt: datetime,
    end_dt: datetime,
    api_key: str,
    timeout_seconds: float = 10.0,
) -> list[dict[str, Any]]:
    if not api_key.strip():
        return []

    cursor = start_dt
    rows: list[dict[str, Any]] = []
    max_chunk_seconds = 100_000
    while cursor < end_dt:
        chunk_end = min(end_dt, cursor + timedelta(seconds=max_chunk_seconds))
        query = urlencode(
            {
                "period_id": "1SEC",
                "time_start": cursor.isoformat().replace("+00:00", "Z"),
                "time_end": chunk_end.isoformat().replace("+00:00", "Z"),
                "limit": 100000,
            }
        )
        request = Request(
            COINAPI_OHLCV_URL.format(symbol_id=symbol_id) + f"?{query}",
            headers={
                "User-Agent": "Elastifund/instance3",
                "X-CoinAPI-Key": api_key.strip(),
            },
        )
        with urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, list) or not payload:
            cursor = chunk_end
            continue
        rows.extend(item for item in payload if isinstance(item, dict))
        last_end = payload[-1].get("time_period_end")
        if not isinstance(last_end, str) or not last_end:
            cursor = chunk_end
            continue
        next_cursor = datetime.fromisoformat(last_end.replace("Z", "+00:00"))
        if next_cursor <= cursor:
            cursor = chunk_end
            continue
        cursor = next_cursor
    return rows


def run_backfill(*, db_path: Path, days: int, skip_network: bool) -> dict[str, Any]:
    ensure_history_store(db_path)
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start = now - timedelta(days=days)
    inserted_per_asset: dict[str, int] = {}
    inserted_per_asset_1s: dict[str, int] = {}
    errors: list[dict[str, str]] = []
    coinapi_status = {
        "enabled": False,
        "configured": False,
        "ready": False,
        "reason": "coinapi_not_enabled_or_not_configured",
    }

    if skip_network:
        record_backfill_run(
            db_path,
            run_id=f"instance3-skip-{now.strftime('%Y%m%dT%H%M%SZ')}",
            requested_days=days,
            notes={"mode": "skip_network"},
        )
        return {
            "requested_days": days,
            "store_path": str(db_path),
            "inserted_per_asset": inserted_per_asset,
            "inserted_per_asset_1s": inserted_per_asset_1s,
            "errors": errors,
            "network_mode": "skipped",
            "coinapi_status": coinapi_status,
        }

    flags = FeatureFlags.from_env()
    coinapi_status["enabled"] = flags.coinapi_enabled
    coinapi_status["configured"] = bool(env_text("COINAPI_KEY"))
    coinapi_status["ready"] = coinapi_ready(flags)
    if coinapi_status["ready"]:
        coinapi_status["reason"] = "enabled"

    for asset in ASSET_ORDER:
        symbol = ASSET_CONFIG[asset]["binance_symbol"]
        try:
            raw_rows = fetch_binance_1m_bars(
                symbol=symbol,
                start_ms=int(start.timestamp() * 1000),
                end_ms=int(now.timestamp() * 1000),
            )
            inserted = insert_reference_bars(
                db_path,
                [
                    {
                        "venue": "binance",
                        "asset": asset,
                        "interval": "1m",
                        "open_time_ms": int(row[0]),
                        "close_time_ms": int(row[6]),
                        "open": float(row[1]),
                        "high": float(row[2]),
                        "low": float(row[3]),
                        "close": float(row[4]),
                        "volume": float(row[5]),
                        "source": "binance_api_v3_klines",
                        "inserted_at": utc_now(),
                    }
                    for row in raw_rows
                ],
            )
            inserted_per_asset[asset] = inserted
        except Exception as exc:
            errors.append({"asset": asset, "error": str(exc)})

    if coinapi_status["ready"]:
        api_key = env_text("COINAPI_KEY")
        for asset in ASSET_ORDER:
            symbol_id = ASSET_CONFIG[asset]["coinapi_symbol"]
            try:
                raw_rows = fetch_coinapi_1s_bars(
                    symbol_id=symbol_id,
                    start_dt=start,
                    end_dt=now,
                    api_key=api_key,
                )
                inserted_per_asset_1s[asset] = insert_reference_bars(
                    db_path,
                    [
                        {
                            "venue": "coinapi",
                            "asset": asset,
                            "interval": "1s",
                            "open_time_ms": int(
                                datetime.fromisoformat(str(row["time_period_start"]).replace("Z", "+00:00")).timestamp()
                                * 1000
                            ),
                            "close_time_ms": int(
                                datetime.fromisoformat(str(row["time_period_end"]).replace("Z", "+00:00")).timestamp()
                                * 1000
                            ),
                            "open": float(row.get("price_open", 0.0) or 0.0),
                            "high": float(row.get("price_high", 0.0) or 0.0),
                            "low": float(row.get("price_low", 0.0) or 0.0),
                            "close": float(row.get("price_close", 0.0) or 0.0),
                            "volume": float(row.get("volume_traded", 0.0) or 0.0),
                            "source": "coinapi_ohlcv_history",
                            "inserted_at": utc_now(),
                        }
                        for row in raw_rows
                        if row.get("time_period_start") and row.get("time_period_end")
                    ],
                )
            except Exception as exc:
                errors.append({"asset": asset, "error": str(exc), "vendor": "coinapi"})
    else:
        for asset in ASSET_ORDER:
            inserted_per_asset_1s[asset] = 0

    record_backfill_run(
        db_path,
        run_id=f"instance3-{now.strftime('%Y%m%dT%H%M%SZ')}",
        requested_days=days,
        notes={
            "inserted_per_asset": inserted_per_asset,
            "inserted_per_asset_1s": inserted_per_asset_1s,
            "errors": errors,
            "coinapi_status": coinapi_status,
        },
    )
    return {
        "requested_days": days,
        "store_path": str(db_path),
        "inserted_per_asset": inserted_per_asset,
        "inserted_per_asset_1s": inserted_per_asset_1s,
        "errors": errors,
        "network_mode": "live",
        "coinapi_status": coinapi_status,
    }


def build_history_report(*, db_path: Path, flags: FeatureFlags, backfill_stats: dict[str, Any]) -> dict[str, Any]:
    coverage = summarize_history_store(db_path)
    one_second_coverage = {
        row["asset"]: dict(row["intervals"]["1s"])
        for row in coverage.get("assets") or []
        if isinstance(row, dict) and isinstance(row.get("intervals"), dict) and isinstance(row["intervals"].get("1s"), dict)
    }
    return {
        "schema_version": "cross_asset_history.v1",
        "generated_at": utc_now(),
        "store_path": str(db_path),
        "requested_days": flags.backfill_days,
        "leader_asset": "BTC",
        "follower_assets": ["ETH", "SOL", "XRP", "DOGE"],
        "requested_intervals": ["1s", "1m"],
        "coverage": coverage,
        "backfill_stats": backfill_stats,
        "one_second_coverage_by_asset": one_second_coverage,
        "coinapi_status": backfill_stats.get("coinapi_status") or {
            "enabled": flags.coinapi_enabled,
            "configured": bool(env_text("COINAPI_KEY")),
            "ready": coinapi_ready(flags),
            "reason": "enabled" if coinapi_ready(flags) else "coinapi_not_enabled_or_not_configured",
        },
        "gaps": {
            "missing_1m_assets": coverage.get("missing_assets_1m") or [],
            "missing_1s_assets": coverage.get("missing_assets_1s") or [],
            "notes": [
                "1m history is sourced from Binance public klines in this lane.",
                "1s history is ingested from CoinAPI only when ELASTIFUND_COINAPI_ENABLED is true and COINAPI_KEY is configured.",
            ],
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history-db", type=Path, default=ROOT / "state" / "cross_asset_history.db")
    parser.add_argument("--history-report", type=Path, default=ROOT / "reports" / "cross_asset_history" / "latest.json")
    parser.add_argument("--vendor-report", type=Path, default=ROOT / "reports" / "vendor_stack" / "latest.json")
    parser.add_argument(
        "--instance-report",
        type=Path,
        default=ROOT / "reports" / "parallel" / "instance03_cross_asset_vendor_dispatch.json",
    )
    parser.add_argument(
        "--canonical-instance-report",
        type=Path,
        default=ROOT / "reports" / "instance3_vendor_backfill" / "latest.json",
    )
    parser.add_argument("--finance-latest", type=Path, default=ROOT / "reports" / "finance" / "latest.json")
    parser.add_argument("--finance-action-queue", type=Path, default=ROOT / "reports" / "finance" / "action_queue.json")
    parser.add_argument("--state-improvement", type=Path, default=ROOT / "reports" / "state_improvement_latest.json")
    parser.add_argument("--skip-network", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    flags = FeatureFlags.from_env()
    finance_latest = read_json(args.finance_latest)
    action_queue = read_json(args.finance_action_queue)
    state_improvement = read_json(args.state_improvement)

    backfill_stats = run_backfill(
        db_path=args.history_db,
        days=flags.backfill_days,
        skip_network=args.skip_network,
    )
    history_report = build_history_report(db_path=args.history_db, flags=flags, backfill_stats=backfill_stats)
    vendor_stack = build_vendor_stack(
        coverage=history_report["coverage"],
        finance_latest=finance_latest,
        action_queue=action_queue,
        flags=flags,
    )
    updated_action_queue, queue_emission = emit_finance_action_queue(
        action_queue=action_queue,
        finance_latest=finance_latest,
        vendor_stack=vendor_stack,
    )
    instance_artifact = build_instance_artifact(
        coverage=history_report["coverage"],
        vendor_stack=vendor_stack,
        finance_latest=finance_latest,
        state_improvement={
            **state_improvement,
            "coinapi_enabled": flags.coinapi_enabled,
            "coinapi_configured": bool(env_text("COINAPI_KEY")),
            "queue_emission": queue_emission,
        },
    )
    instance_artifact["details"]["finance_action_queue"] = queue_emission
    instance_artifact["details"]["one_second_coverage_by_asset"] = history_report["one_second_coverage_by_asset"]
    instance_artifact["details"]["coinapi_status"] = history_report["coinapi_status"]

    write_json(args.history_report, history_report)
    write_json(args.vendor_report, vendor_stack)
    write_json(args.finance_action_queue, updated_action_queue)
    write_json(args.canonical_instance_report, instance_artifact)
    write_json(args.instance_report, instance_artifact)
    print(
        json.dumps(
            {
                "history_report": str(args.history_report),
                "vendor_report": str(args.vendor_report),
                "canonical_instance_report": str(args.canonical_instance_report),
                "instance_report": str(args.instance_report),
                "finance_action_queue": str(args.finance_action_queue),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
