#!/usr/bin/env python3
"""Momentum persistence detector for short-horizon candle markets."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any


VALID_SIDES = {"UP", "DOWN"}


@dataclass(frozen=True)
class ResolvedWindowOutcome:
    window_start_ts: int
    resolved_side: str


@dataclass(frozen=True)
class MomentumSnapshot:
    asset_symbol: str
    as_of_window_start_ts: int | None
    lookback_windows: int
    outcome_count: int
    streak_direction: str | None
    streak_length: int
    break_from_direction: str | None
    break_to_direction: str | None
    break_streak_length: int
    windows_since_break: int | None
    favored_direction: str | None
    mode: str
    reason: str
    favored_min_delta_multiplier: float
    opposed_min_delta_multiplier: float
    generated_at: str
    recent_outcomes: list[dict[str, Any]]

    def min_delta_multiplier_for_direction(self, direction: str | None) -> float:
        normalized = str(direction or "").strip().upper()
        if normalized not in VALID_SIDES:
            return 1.0
        if self.mode not in {"momentum", "reversal"}:
            return 1.0
        if not self.favored_direction:
            return 1.0
        return (
            float(self.favored_min_delta_multiplier)
            if normalized == self.favored_direction
            else float(self.opposed_min_delta_multiplier)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_symbol": self.asset_symbol,
            "as_of_window_start_ts": self.as_of_window_start_ts,
            "lookback_windows": self.lookback_windows,
            "outcome_count": self.outcome_count,
            "streak_direction": self.streak_direction,
            "streak_length": self.streak_length,
            "break_from_direction": self.break_from_direction,
            "break_to_direction": self.break_to_direction,
            "break_streak_length": self.break_streak_length,
            "windows_since_break": self.windows_since_break,
            "favored_direction": self.favored_direction,
            "mode": self.mode,
            "reason": self.reason,
            "favored_min_delta_multiplier": self.favored_min_delta_multiplier,
            "opposed_min_delta_multiplier": self.opposed_min_delta_multiplier,
            "generated_at": self.generated_at,
            "recent_outcomes": list(self.recent_outcomes),
        }


class MomentumDetector:
    """Infer short-horizon momentum/reversal regimes from resolved windows."""

    def __init__(
        self,
        *,
        db_path: Path,
        state_path: Path = Path("data/momentum_state.json"),
        asset_symbol: str = "BTCUSDT",
        lookback_windows: int = 96,
        streak_min_windows: int = 3,
        reversal_boost_windows: int = 2,
        favored_min_delta_multiplier: float = 0.8,
        opposed_min_delta_multiplier: float = 1.2,
    ) -> None:
        self.db_path = Path(db_path)
        self.state_path = Path(state_path)
        self.asset_symbol = str(asset_symbol or "BTCUSDT").strip().upper() or "BTCUSDT"
        self.lookback_windows = max(4, int(lookback_windows))
        self.streak_min_windows = max(2, int(streak_min_windows))
        self.reversal_boost_windows = max(1, int(reversal_boost_windows))
        self.favored_min_delta_multiplier = max(0.01, float(favored_min_delta_multiplier))
        self.opposed_min_delta_multiplier = max(0.01, float(opposed_min_delta_multiplier))

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _table_exists(self, conn: sqlite3.Connection, table_name: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
            (table_name,),
        ).fetchone()
        return row is not None

    def _load_recent_resolved_outcomes(
        self,
        *,
        as_of_window_start_ts: int | None = None,
    ) -> list[ResolvedWindowOutcome]:
        if not self.db_path.exists():
            return []

        with self._connect() as conn:
            if not self._table_exists(conn, "window_trades"):
                return []
            where = ["resolved_side IN ('UP', 'DOWN')"]
            params: list[Any] = []
            if as_of_window_start_ts is not None:
                where.append("window_start_ts < ?")
                params.append(int(as_of_window_start_ts))
            rows = conn.execute(
                f"""
                SELECT
                    window_start_ts,
                    resolved_side
                FROM window_trades
                WHERE {" AND ".join(where)}
                ORDER BY window_start_ts DESC
                LIMIT ?
                """,
                (*params, int(self.lookback_windows)),
            ).fetchall()
        outcomes = [
            ResolvedWindowOutcome(
                window_start_ts=int(row["window_start_ts"]),
                resolved_side=str(row["resolved_side"]).upper(),
            )
            for row in reversed(rows)
            if str(row["resolved_side"]).upper() in VALID_SIDES
        ]
        return outcomes

    @staticmethod
    def _tail_streak(outcomes: list[ResolvedWindowOutcome]) -> tuple[str | None, int]:
        if not outcomes:
            return None, 0
        tail_direction = outcomes[-1].resolved_side
        length = 0
        for outcome in reversed(outcomes):
            if outcome.resolved_side != tail_direction:
                break
            length += 1
        return tail_direction, length

    def _latest_break_event(
        self,
        outcomes: list[ResolvedWindowOutcome],
    ) -> tuple[int, str, str, int] | None:
        if len(outcomes) < 2:
            return None
        sides = [outcome.resolved_side for outcome in outcomes]
        for idx in range(len(sides) - 1, 0, -1):
            if sides[idx] == sides[idx - 1]:
                continue
            previous = sides[idx - 1]
            start = idx - 1
            while start > 0 and sides[start - 1] == previous:
                start -= 1
            prior_streak_length = (idx - 1) - start + 1
            if prior_streak_length >= self.streak_min_windows:
                return idx, previous, sides[idx], prior_streak_length
        return None

    def snapshot(self, *, as_of_window_start_ts: int | None = None) -> MomentumSnapshot:
        outcomes = self._load_recent_resolved_outcomes(as_of_window_start_ts=as_of_window_start_ts)
        streak_direction, streak_length = self._tail_streak(outcomes)

        favored_direction: str | None = None
        mode = "neutral"
        reason = "insufficient_resolved_history"
        break_from_direction: str | None = None
        break_to_direction: str | None = None
        break_streak_length = 0
        windows_since_break: int | None = None

        if streak_direction is not None and streak_length >= self.streak_min_windows:
            mode = "momentum"
            favored_direction = streak_direction
            reason = f"momentum_streak_{streak_length}"
        else:
            break_event = self._latest_break_event(outcomes)
            if break_event is not None:
                break_idx, break_from, break_to, prior_streak = break_event
                windows_since_break = (len(outcomes) - 1) - break_idx
                break_from_direction = break_from
                break_to_direction = break_to
                break_streak_length = prior_streak
                if windows_since_break < self.reversal_boost_windows:
                    mode = "reversal"
                    favored_direction = break_to
                    reason = (
                        f"reversal_after_{prior_streak}_{break_from.lower()}"
                        f"_windows_since_break_{windows_since_break}"
                    )
                else:
                    reason = "break_detected_but_boost_expired"

        recent_outcomes = [
            {
                "window_start_ts": item.window_start_ts,
                "resolved_side": item.resolved_side,
            }
            for item in outcomes[-20:]
        ]
        return MomentumSnapshot(
            asset_symbol=self.asset_symbol,
            as_of_window_start_ts=as_of_window_start_ts,
            lookback_windows=self.lookback_windows,
            outcome_count=len(outcomes),
            streak_direction=streak_direction,
            streak_length=streak_length,
            break_from_direction=break_from_direction,
            break_to_direction=break_to_direction,
            break_streak_length=break_streak_length,
            windows_since_break=windows_since_break,
            favored_direction=favored_direction,
            mode=mode,
            reason=reason,
            favored_min_delta_multiplier=self.favored_min_delta_multiplier,
            opposed_min_delta_multiplier=self.opposed_min_delta_multiplier,
            generated_at=datetime.now(timezone.utc).isoformat(),
            recent_outcomes=recent_outcomes,
        )

    def write_state(self, snapshot: MomentumSnapshot) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(snapshot.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def update(self, *, as_of_window_start_ts: int | None = None) -> MomentumSnapshot:
        snapshot = self.snapshot(as_of_window_start_ts=as_of_window_start_ts)
        self.write_state(snapshot)
        return snapshot
