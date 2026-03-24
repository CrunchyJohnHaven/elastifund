"""Rolling edge tracker for BTC5 self-improving mode selection.

Reads the last N resolved trades from SQLite, computes rolling win rate and PnL
by direction, and returns a mode recommendation. Does NOT auto-switch modes;
logs recommendations to a JSON file for human or dispatch review.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("RollingEdgeTracker")

DEFAULT_LOOKBACK = 100
DEFAULT_MIN_FILLS = 50


@dataclass(frozen=True)
class DirectionStats:
    direction: str
    fills: int
    wins: int
    losses: int
    total_pnl_usd: float

    @property
    def win_rate(self) -> float:
        return self.wins / self.fills if self.fills > 0 else 0.0

    @property
    def avg_pnl_usd(self) -> float:
        return self.total_pnl_usd / self.fills if self.fills > 0 else 0.0

    @property
    def profit_factor(self) -> float:
        gross_win = sum_val if (sum_val := self.total_pnl_usd) > 0 else 0.0
        gross_loss = abs(self.total_pnl_usd) if self.total_pnl_usd < 0 else 0.0
        return gross_win / gross_loss if gross_loss > 0 else float("inf") if gross_win > 0 else 0.0


@dataclass(frozen=True)
class EdgeRecommendation:
    down_wr: float
    up_wr: float
    down_fills: int
    up_fills: int
    down_pnl_usd: float
    up_pnl_usd: float
    recommended_mode: str
    confidence: float
    reason: str
    timestamp: str


def _query_resolved_fills(
    db_path: Path,
    *,
    limit: int = DEFAULT_LOOKBACK,
) -> list[dict[str, Any]]:
    """Pull the last N resolved fills from the BTC5 decisions DB."""
    if not db_path.exists():
        return []
    try:
        conn = sqlite3.connect(str(db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT direction, won, pnl_usd
            FROM window_trades
            WHERE filled = 1
              AND won IS NOT NULL
              AND direction IN ('UP', 'DOWN')
            ORDER BY id DESC
            LIMIT ?
            """,
            (max(1, int(limit)),),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.warning("Failed to query resolved fills from %s: %s", db_path, exc)
        return []


def _compute_direction_stats(
    rows: list[dict[str, Any]],
    direction: str,
) -> DirectionStats:
    filtered = [r for r in rows if str(r.get("direction", "")).strip().upper() == direction]
    fills = len(filtered)
    wins = sum(1 for r in filtered if int(r.get("won", 0)) == 1)
    losses = fills - wins
    total_pnl = sum(float(r.get("pnl_usd") or 0.0) for r in filtered)
    return DirectionStats(
        direction=direction,
        fills=fills,
        wins=wins,
        losses=losses,
        total_pnl_usd=round(total_pnl, 4),
    )


def analyze(
    db_path: Path,
    *,
    lookback: int = DEFAULT_LOOKBACK,
    min_fills: int = DEFAULT_MIN_FILLS,
) -> EdgeRecommendation:
    """Analyze rolling performance and return a mode recommendation."""
    rows = _query_resolved_fills(db_path, limit=lookback)
    down = _compute_direction_stats(rows, "DOWN")
    up = _compute_direction_stats(rows, "UP")

    now_iso = datetime.now(timezone.utc).isoformat()

    # Insufficient data
    if down.fills < min_fills or up.fills < min_fills:
        insufficient_side = "DOWN" if down.fills < min_fills else "UP"
        return EdgeRecommendation(
            down_wr=down.win_rate,
            up_wr=up.win_rate,
            down_fills=down.fills,
            up_fills=up.fills,
            down_pnl_usd=down.total_pnl_usd,
            up_pnl_usd=up.total_pnl_usd,
            recommended_mode="both",
            confidence=0.0,
            reason=f"insufficient data: {insufficient_side} has {down.fills if insufficient_side == 'DOWN' else up.fills}/{min_fills} fills",
            timestamp=now_iso,
        )

    # Neither side profitable
    if down.win_rate <= 0.50 and up.win_rate <= 0.50:
        return EdgeRecommendation(
            down_wr=down.win_rate,
            up_wr=up.win_rate,
            down_fills=down.fills,
            up_fills=up.fills,
            down_pnl_usd=down.total_pnl_usd,
            up_pnl_usd=up.total_pnl_usd,
            recommended_mode="pause",
            confidence=max(0.0, 1.0 - (down.win_rate + up.win_rate)),
            reason=f"both sides losing: DOWN WR={down.win_rate:.1%} UP WR={up.win_rate:.1%}",
            timestamp=now_iso,
        )

    # DOWN dominant: DOWN > 55% and UP < 48%
    if down.win_rate > 0.55 and up.win_rate < 0.48:
        gap = down.win_rate - up.win_rate
        return EdgeRecommendation(
            down_wr=down.win_rate,
            up_wr=up.win_rate,
            down_fills=down.fills,
            up_fills=up.fills,
            down_pnl_usd=down.total_pnl_usd,
            up_pnl_usd=up.total_pnl_usd,
            recommended_mode="down_only",
            confidence=min(1.0, gap * 5),
            reason=f"DOWN dominant: WR={down.win_rate:.1%} vs UP WR={up.win_rate:.1%} gap={gap:.1%}",
            timestamp=now_iso,
        )

    # UP dominant: UP > 55% and DOWN < 48%
    if up.win_rate > 0.55 and down.win_rate < 0.48:
        gap = up.win_rate - down.win_rate
        return EdgeRecommendation(
            down_wr=down.win_rate,
            up_wr=up.win_rate,
            down_fills=down.fills,
            up_fills=up.fills,
            down_pnl_usd=down.total_pnl_usd,
            up_pnl_usd=up.total_pnl_usd,
            recommended_mode="up_only",
            confidence=min(1.0, gap * 5),
            reason=f"UP dominant: WR={up.win_rate:.1%} vs DOWN WR={down.win_rate:.1%} gap={gap:.1%}",
            timestamp=now_iso,
        )

    # Both profitable: both > 52%
    if down.win_rate > 0.52 and up.win_rate > 0.52:
        avg_wr = (down.win_rate + up.win_rate) / 2
        return EdgeRecommendation(
            down_wr=down.win_rate,
            up_wr=up.win_rate,
            down_fills=down.fills,
            up_fills=up.fills,
            down_pnl_usd=down.total_pnl_usd,
            up_pnl_usd=up.total_pnl_usd,
            recommended_mode="both",
            confidence=min(1.0, (avg_wr - 0.52) * 10),
            reason=f"both profitable: DOWN WR={down.win_rate:.1%} UP WR={up.win_rate:.1%}",
            timestamp=now_iso,
        )

    # Default: mild asymmetry, keep both
    return EdgeRecommendation(
        down_wr=down.win_rate,
        up_wr=up.win_rate,
        down_fills=down.fills,
        up_fills=up.fills,
        down_pnl_usd=down.total_pnl_usd,
        up_pnl_usd=up.total_pnl_usd,
        recommended_mode="both",
        confidence=0.3,
        reason=f"no strong signal: DOWN WR={down.win_rate:.1%} UP WR={up.win_rate:.1%}",
        timestamp=now_iso,
    )


def log_recommendation(
    rec: EdgeRecommendation,
    log_path: Path,
    *,
    max_entries: int = 500,
) -> None:
    """Append a recommendation to the JSON log file."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []
    if log_path.exists():
        try:
            raw = json.loads(log_path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                entries = raw
        except Exception:
            pass
    entry = {
        "down_wr": round(rec.down_wr, 4),
        "up_wr": round(rec.up_wr, 4),
        "down_fills": rec.down_fills,
        "up_fills": rec.up_fills,
        "down_pnl_usd": round(rec.down_pnl_usd, 4),
        "up_pnl_usd": round(rec.up_pnl_usd, 4),
        "recommended_mode": rec.recommended_mode,
        "confidence": round(rec.confidence, 4),
        "reason": rec.reason,
        "timestamp": rec.timestamp,
    }
    entries.append(entry)
    if len(entries) > max_entries:
        entries = entries[-max_entries:]
    log_path.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")


def load_recent_recommendations(
    log_path: Path,
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Load the last N recommendations from the log."""
    if not log_path.exists():
        return []
    try:
        raw = json.loads(log_path.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            return raw[-limit:]
    except Exception:
        pass
    return []
