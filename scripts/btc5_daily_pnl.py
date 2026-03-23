#!/usr/bin/env python3
"""BTC5 Daily PnL — canonical ET-day and rolling-24h live PnL computation.

Computes:
  - ET-day realized live PnL (calendar day in America/New_York)
  - Rolling-24h realized live PnL
  - Fill counts, gross PnL, estimated maker rebate, net-after-rebate

Source: BTC5 live-fill ledger (window_trades table, order_status='live_filled').

All timestamps in the DB are assumed to be Unix epoch seconds (window_start_ts).
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# Default maker rebate rate (Polymarket 5-min markets)
DEFAULT_MAKER_REBATE_RATE = 0.0025  # 0.25%


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class DailyPnLMetrics:
    """Canonical BTC5 daily PnL metrics for a single time window."""

    window_label: str               # "et_day" or "rolling_24h"
    window_start_utc: str           # ISO 8601
    window_end_utc: str             # ISO 8601
    fill_count: int = 0
    gross_realized_pnl_usd: float = 0.0
    estimated_maker_rebate_usd: float = 0.0
    net_after_rebate_pnl_usd: float = 0.0
    latest_fill_ts_utc: str | None = None
    status: str = "fresh"           # "fresh", "stale", "blocked", "empty"

    def to_dict(self) -> dict[str, Any]:
        return {
            "window_label": self.window_label,
            "window_start_utc": self.window_start_utc,
            "window_end_utc": self.window_end_utc,
            "fill_count": self.fill_count,
            "gross_realized_pnl_usd": round(self.gross_realized_pnl_usd, 4),
            "estimated_maker_rebate_usd": round(self.estimated_maker_rebate_usd, 4),
            "net_after_rebate_pnl_usd": round(self.net_after_rebate_pnl_usd, 4),
            "latest_fill_ts_utc": self.latest_fill_ts_utc,
            "status": self.status,
        }


@dataclass(frozen=True)
class BTC5DailyPnLPacket:
    """Bundle of ET-day and rolling-24h metrics."""

    et_day: DailyPnLMetrics
    rolling_24h: DailyPnLMetrics
    legacy_recent_pnl_usd: float | None = None  # compatibility with btc5_recent_live_filled_pnl_usd
    generated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "btc5_daily_pnl.v1",
            "generated_at": self.generated_at,
            "et_day": self.et_day.to_dict(),
            "rolling_24h": self.rolling_24h.to_dict(),
            "legacy_recent_pnl_usd": self.legacy_recent_pnl_usd,
        }

    def runtime_truth_fields(self) -> dict[str, Any]:
        """Flat dict of fields to merge into runtime truth."""
        return {
            "btc5_realized_live_pnl_et_day_usd": round(self.et_day.gross_realized_pnl_usd, 4),
            "btc5_realized_live_pnl_et_day_net_after_rebate_usd": round(self.et_day.net_after_rebate_pnl_usd, 4),
            "btc5_realized_live_fills_et_day": self.et_day.fill_count,
            "btc5_realized_live_pnl_rolling_24h_usd": round(self.rolling_24h.gross_realized_pnl_usd, 4),
            "btc5_realized_live_pnl_rolling_24h_net_after_rebate_usd": round(self.rolling_24h.net_after_rebate_pnl_usd, 4),
            "btc5_realized_live_fills_rolling_24h": self.rolling_24h.fill_count,
        }


def _et_day_bounds(now_utc: datetime) -> tuple[datetime, datetime]:
    """Return (start_utc, end_utc) of the current ET calendar day in UTC."""
    now_et = now_utc.astimezone(ET)
    day_start_et = now_et.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end_et = day_start_et + timedelta(days=1)
    return day_start_et.astimezone(timezone.utc), day_end_et.astimezone(timezone.utc)


def _rolling_24h_bounds(now_utc: datetime) -> tuple[datetime, datetime]:
    """Return (start_utc, end_utc) for the trailing 24h window."""
    return now_utc - timedelta(hours=24), now_utc


def _compute_window_metrics(
    rows: list[dict[str, Any]],
    *,
    window_label: str,
    window_start_utc: datetime,
    window_end_utc: datetime,
    maker_rebate_rate: float = DEFAULT_MAKER_REBATE_RATE,
) -> DailyPnLMetrics:
    """Compute PnL metrics for rows within [window_start, window_end)."""
    start_epoch = window_start_utc.timestamp()
    end_epoch = window_end_utc.timestamp()

    matched = []
    for row in rows:
        ts = _safe_float(row.get("window_start_ts"), 0.0)
        if start_epoch <= ts < end_epoch:
            matched.append(row)

    if not matched:
        return DailyPnLMetrics(
            window_label=window_label,
            window_start_utc=window_start_utc.isoformat(),
            window_end_utc=window_end_utc.isoformat(),
            status="empty",
        )

    gross_pnl = 0.0
    total_trade_size = 0.0
    latest_ts: float = 0.0

    for row in matched:
        pnl = _safe_float(row.get("pnl_usd"), 0.0)
        gross_pnl += pnl
        trade_size = _safe_float(row.get("trade_size_usd"), 5.0)
        total_trade_size += trade_size
        ts = _safe_float(row.get("window_start_ts"), 0.0)
        if ts > latest_ts:
            latest_ts = ts

    rebate = total_trade_size * maker_rebate_rate
    net_pnl = gross_pnl + rebate

    latest_fill_utc = (
        datetime.fromtimestamp(latest_ts, tz=timezone.utc).isoformat()
        if latest_ts > 0
        else None
    )

    return DailyPnLMetrics(
        window_label=window_label,
        window_start_utc=window_start_utc.isoformat(),
        window_end_utc=window_end_utc.isoformat(),
        fill_count=len(matched),
        gross_realized_pnl_usd=gross_pnl,
        estimated_maker_rebate_usd=rebate,
        net_after_rebate_pnl_usd=net_pnl,
        latest_fill_ts_utc=latest_fill_utc,
        status="fresh",
    )


def load_live_fills(db_path: Path) -> list[dict[str, Any]]:
    """Load all live_filled rows from window_trades."""
    if not db_path.exists():
        return []
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """
                SELECT pnl_usd, won, trade_size_usd, window_start_ts, order_status, direction
                FROM window_trades
                WHERE LOWER(COALESCE(order_status, '')) = 'live_filled'
                ORDER BY window_start_ts ASC
                """
            ).fetchall()
        finally:
            conn.close()
        return [dict(r) for r in rows]
    except sqlite3.Error:
        return []


def compute_btc5_daily_pnl(
    *,
    db_path: Path | None = None,
    fills: list[dict[str, Any]] | None = None,
    now_utc: datetime | None = None,
    maker_rebate_rate: float = DEFAULT_MAKER_REBATE_RATE,
    legacy_recent_pnl_usd: float | None = None,
) -> BTC5DailyPnLPacket:
    """Compute the canonical BTC5 daily PnL packet.

    Supply either db_path (will query) or fills (pre-loaded rows).
    """
    now_utc = now_utc or datetime.now(timezone.utc)

    if fills is None:
        fills = load_live_fills(db_path) if db_path else []

    et_start, et_end = _et_day_bounds(now_utc)
    r24_start, r24_end = _rolling_24h_bounds(now_utc)

    et_day = _compute_window_metrics(
        fills,
        window_label="et_day",
        window_start_utc=et_start,
        window_end_utc=et_end,
        maker_rebate_rate=maker_rebate_rate,
    )

    rolling_24h = _compute_window_metrics(
        fills,
        window_label="rolling_24h",
        window_start_utc=r24_start,
        window_end_utc=r24_end,
        maker_rebate_rate=maker_rebate_rate,
    )

    generated_at = now_utc.replace(microsecond=0).isoformat().replace("+00:00", "Z")

    return BTC5DailyPnLPacket(
        et_day=et_day,
        rolling_24h=rolling_24h,
        legacy_recent_pnl_usd=legacy_recent_pnl_usd,
        generated_at=generated_at,
    )


def write_scoreboard(
    packet: BTC5DailyPnLPacket,
    output_path: Path,
) -> Path:
    """Write the live PnL scoreboard artifact."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(packet.to_dict(), indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return output_path
