#!/usr/bin/env python3
"""
Promotion Stage Manager — Proof-to-Capital Ladder Enforcement
=============================================================
Tracks which strategies are at which stage and enforces promotion/demotion
gates per the canonical spec in docs/architecture/promotion_ladder.md.

Every stage transition requires passing all quantitative gates. Hope is not
a position size.

March 2026 — Elastifund / JJ

v2 additions (DISPATCH_111):
- StrategyRecord.net_returns: per-trade net returns after fees
- check_promotion_v2(): Bayesian log-growth posterior gate
- check_demotion_v2(): Bayesian demotion gate
- promote_v2(): uses check_promotion_v2
- FalsePromotionTracker: logs promotions and tracks reversion within 21 days
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
import time
from dataclasses import dataclass, field, asdict
from enum import IntEnum
from typing import Any, Optional

from bot.bayesian_promoter import LogGrowthPosterior

logger = logging.getLogger("JJ.promotion_manager")

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class PromotionStage(IntEnum):
    HYPOTHESIS = 0
    BACKTESTED = 1
    SHADOW = 2
    MICRO_LIVE = 3
    SEED = 4
    SCALE = 5
    CORE = 6


# ---------------------------------------------------------------------------
# Stage Gate Definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StageGate:
    """Quantitative thresholds required to enter a given stage."""
    min_fills: int = 0
    min_days: int = 0
    min_win_rate: float = 0.0
    min_profit_factor: float = 0.0
    max_drawdown_pct: float = 1.0
    min_sharpe: float = 0.0
    min_fill_rate: float = 0.0
    binomial_p_threshold: float = 1.0       # require p < this vs H0: WR=50%
    min_kelly: float = 0.0


# Gates to ENTER each stage (key = target stage)
STAGE_GATES: dict[PromotionStage, StageGate] = {
    PromotionStage.MICRO_LIVE: StageGate(
        min_fills=50,
        min_days=14,
        min_win_rate=0.52,
        min_profit_factor=1.05,
        max_drawdown_pct=0.20,
        min_sharpe=0.5,
        min_fill_rate=0.30,
        binomial_p_threshold=0.05,
    ),
    PromotionStage.SEED: StageGate(
        min_fills=200,
        min_days=30,
        min_win_rate=0.53,
        min_profit_factor=1.10,
        max_drawdown_pct=0.15,
        min_sharpe=1.0,
        min_fill_rate=0.30,
        min_kelly=0.02,
    ),
}

# ---------------------------------------------------------------------------
# Capital & Position Policy
# ---------------------------------------------------------------------------

# Fraction of total bankroll allocated to each stage (combined across all
# strategies at that stage).
STAGE_ALLOCATION_PCT: dict[PromotionStage, float] = {
    PromotionStage.SHADOW: 0.00,
    PromotionStage.MICRO_LIVE: 0.10,
    PromotionStage.SEED: 0.20,
    PromotionStage.SCALE: 0.50,
    PromotionStage.CORE: 1.00,      # Kelly-limited, no fixed cap
}

RESERVE_PCT = 0.10  # minimum reserve

# Max USD per trade at each stage
POSITION_CAP: dict[PromotionStage, float] = {
    PromotionStage.HYPOTHESIS: 0.0,
    PromotionStage.BACKTESTED: 0.0,
    PromotionStage.SHADOW: 0.0,
    PromotionStage.MICRO_LIVE: 5.0,
    PromotionStage.SEED: 25.0,
    PromotionStage.SCALE: 100.0,
    PromotionStage.CORE: float("inf"),   # Kelly-optimal
}

# Cool-off days after demotion from a stage
COOLOFF_DAYS: dict[PromotionStage, int] = {
    PromotionStage.MICRO_LIVE: 7,
    PromotionStage.SEED: 14,
    PromotionStage.SCALE: 21,
}

# ---------------------------------------------------------------------------
# Strategy Record
# ---------------------------------------------------------------------------

@dataclass
class StrategyRecord:
    strategy_id: str
    current_stage: PromotionStage
    stage_entered_at: float                      # epoch seconds
    fills: int = 0
    wins: int = 0
    losses: int = 0
    gross_pnl: float = 0.0
    max_drawdown: float = 0.0
    daily_pnl_history: list[float] = field(default_factory=list)
    fill_rate: float = 0.0
    orders_submitted: int = 0
    sharpe: float = 0.0
    slippage_values: list[float] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    cooloff_until: float = 0.0                   # epoch; 0 = no cooloff
    demotion_reason: str = ""
    created_at: float = field(default_factory=time.time)
    net_returns: list[float] = field(default_factory=list)  # per-trade net returns after fees

    # -- derived properties --------------------------------------------------

    @property
    def win_rate(self) -> float:
        total = self.wins + self.losses
        if total == 0:
            return 0.0
        return self.wins / total

    @property
    def profit_factor(self) -> float:
        """Gross wins / gross losses.  Stored as gross_pnl, we need win/loss
        totals.  We approximate from win_rate * avg_win / (loss_rate * avg_loss).
        Since we don't track per-trade P&L, we use a simpler model:
        PF = (wins * avg_win) / (losses * avg_loss).
        For simplicity we track gross_pnl and compute PF from metadata if
        available, otherwise from pnl direction."""
        if "gross_wins" in self.metadata and "gross_losses" in self.metadata:
            gw = self.metadata["gross_wins"]
            gl = self.metadata["gross_losses"]
            if gl == 0:
                return float("inf") if gw > 0 else 0.0
            return gw / gl
        # Fallback: can't compute without per-trade data
        return 0.0

    @property
    def kelly_fraction(self) -> float:
        """Kelly fraction = WR - (1 - WR) / (avg_win / avg_loss).
        Simplified: if PF known, kelly = WR - (1-WR)/PF_ratio."""
        pf = self.profit_factor
        wr = self.win_rate
        if pf <= 0 or wr <= 0 or wr >= 1.0:
            return 0.0
        # b = avg_win / avg_loss = PF * (1-WR) / WR ... but simpler:
        # kelly = WR - (1-WR) / b  where b = PF
        # Using standard formula: f* = (b*p - q) / b  where p=WR, q=1-WR, b=PF
        b = pf
        q = 1.0 - wr
        return (b * wr - q) / b

    @property
    def days_at_stage(self) -> float:
        return (time.time() - self.stage_entered_at) / 86400.0

    @property
    def peak_equity(self) -> float:
        """Peak cumulative daily equity (for drawdown)."""
        if not self.daily_pnl_history:
            return 0.0
        cum = 0.0
        peak = 0.0
        for d in self.daily_pnl_history:
            cum += d
            if cum > peak:
                peak = cum
        return peak

    @property
    def current_drawdown(self) -> float:
        """Current drawdown from peak as a positive number."""
        if not self.daily_pnl_history:
            return 0.0
        cum = 0.0
        peak = 0.0
        for d in self.daily_pnl_history:
            cum += d
            if cum > peak:
                peak = cum
        dd = peak - cum
        return max(0.0, dd)


# ---------------------------------------------------------------------------
# Binomial Test (exact, one-tailed)
# ---------------------------------------------------------------------------

def binomial_test(n: int, k: int, p0: float = 0.50) -> float:
    """Exact one-tailed binomial p-value: P(X >= k | X ~ Binomial(n, p0)).

    Uses math.comb from stdlib (Python 3.8+).  No scipy needed.
    """
    if n <= 0 or k < 0:
        return 1.0
    if k > n:
        return 0.0
    if p0 <= 0.0:
        return 0.0 if k > 0 else 1.0
    if p0 >= 1.0:
        return 1.0

    p_value = 0.0
    q0 = 1.0 - p0
    for i in range(k, n + 1):
        # P(X=i) = C(n,i) * p0^i * q0^(n-i)
        coeff = math.comb(n, i)
        prob = coeff * (p0 ** i) * (q0 ** (n - i))
        p_value += prob

    return min(p_value, 1.0)


# ---------------------------------------------------------------------------
# Promotion Manager
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS strategies (
    strategy_id TEXT PRIMARY KEY,
    current_stage INTEGER NOT NULL,
    stage_entered_at REAL NOT NULL,
    fills INTEGER NOT NULL DEFAULT 0,
    wins INTEGER NOT NULL DEFAULT 0,
    losses INTEGER NOT NULL DEFAULT 0,
    gross_pnl REAL NOT NULL DEFAULT 0.0,
    max_drawdown REAL NOT NULL DEFAULT 0.0,
    daily_pnl_history TEXT NOT NULL DEFAULT '[]',
    fill_rate REAL NOT NULL DEFAULT 0.0,
    orders_submitted INTEGER NOT NULL DEFAULT 0,
    sharpe REAL NOT NULL DEFAULT 0.0,
    slippage_values TEXT NOT NULL DEFAULT '[]',
    metadata TEXT NOT NULL DEFAULT '{}',
    cooloff_until REAL NOT NULL DEFAULT 0.0,
    demotion_reason TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    net_returns TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS promotion_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id TEXT NOT NULL,
    from_stage INTEGER NOT NULL,
    to_stage INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    timestamp REAL NOT NULL,
    gate_results TEXT,
    reason TEXT
);
"""

# Migration SQL: add net_returns column to existing tables that lack it
_MIGRATION_ADD_NET_RETURNS = """
ALTER TABLE strategies ADD COLUMN net_returns TEXT NOT NULL DEFAULT '[]';
"""


class PromotionManager:
    """SQLite-backed strategy stage tracker with promotion/demotion logic."""

    def __init__(self, db_path: str = "promotion_manager.db") -> None:
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()
        self._strategies: dict[str, StrategyRecord] = {}
        self._load_all()
        logger.info(
            "PromotionManager initialised — %d strategies loaded from %s",
            len(self._strategies),
            db_path,
        )

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _init_schema(self) -> None:
        self._conn.executescript(_SCHEMA)
        # Add net_returns column if it doesn't exist yet (migration for existing DBs)
        try:
            self._conn.execute(_MIGRATION_ADD_NET_RETURNS)
            self._conn.commit()
            logger.info("Migration: added net_returns column to strategies table")
        except sqlite3.OperationalError as exc:
            if "duplicate column name" in str(exc).lower():
                pass  # Column already exists — no action needed
            else:
                raise
        self._conn.commit()

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _row_to_record(self, row: sqlite3.Row) -> StrategyRecord:
        # net_returns may be absent in very old schema snapshots
        try:
            net_returns = json.loads(row["net_returns"])
        except (IndexError, KeyError):
            net_returns = []
        return StrategyRecord(
            strategy_id=row["strategy_id"],
            current_stage=PromotionStage(row["current_stage"]),
            stage_entered_at=row["stage_entered_at"],
            fills=row["fills"],
            wins=row["wins"],
            losses=row["losses"],
            gross_pnl=row["gross_pnl"],
            max_drawdown=row["max_drawdown"],
            daily_pnl_history=json.loads(row["daily_pnl_history"]),
            fill_rate=row["fill_rate"],
            orders_submitted=row["orders_submitted"],
            sharpe=row["sharpe"],
            slippage_values=json.loads(row["slippage_values"]),
            metadata=json.loads(row["metadata"]),
            cooloff_until=row["cooloff_until"],
            demotion_reason=row["demotion_reason"],
            created_at=row["created_at"],
            net_returns=net_returns,
        )

    def _save_record(self, rec: StrategyRecord) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO strategies
               (strategy_id, current_stage, stage_entered_at, fills, wins, losses,
                gross_pnl, max_drawdown, daily_pnl_history, fill_rate,
                orders_submitted, sharpe, slippage_values, metadata,
                cooloff_until, demotion_reason, created_at, net_returns)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                rec.strategy_id,
                int(rec.current_stage),
                rec.stage_entered_at,
                rec.fills,
                rec.wins,
                rec.losses,
                rec.gross_pnl,
                rec.max_drawdown,
                json.dumps(rec.daily_pnl_history),
                rec.fill_rate,
                rec.orders_submitted,
                rec.sharpe,
                json.dumps(rec.slippage_values),
                json.dumps(rec.metadata),
                rec.cooloff_until,
                rec.demotion_reason,
                rec.created_at,
                json.dumps(rec.net_returns),
            ),
        )
        self._conn.commit()

    def _log_event(
        self,
        strategy_id: str,
        from_stage: PromotionStage,
        to_stage: PromotionStage,
        event_type: str,
        gate_results: Optional[dict] = None,
        reason: str = "",
    ) -> None:
        self._conn.execute(
            """INSERT INTO promotion_events
               (strategy_id, from_stage, to_stage, event_type, timestamp,
                gate_results, reason)
               VALUES (?,?,?,?,?,?,?)""",
            (
                strategy_id,
                int(from_stage),
                int(to_stage),
                event_type,
                time.time(),
                json.dumps(gate_results) if gate_results else None,
                reason,
            ),
        )
        self._conn.commit()

    def _load_all(self) -> None:
        cursor = self._conn.execute("SELECT * FROM strategies")
        for row in cursor.fetchall():
            rec = self._row_to_record(row)
            self._strategies[rec.strategy_id] = rec

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register_strategy(
        self,
        strategy_id: str,
        initial_stage: PromotionStage = PromotionStage.HYPOTHESIS,
    ) -> StrategyRecord:
        """Register a new strategy. Returns existing record if already registered."""
        if strategy_id in self._strategies:
            logger.debug("Strategy %s already registered", strategy_id)
            return self._strategies[strategy_id]

        rec = StrategyRecord(
            strategy_id=strategy_id,
            current_stage=initial_stage,
            stage_entered_at=time.time(),
        )
        self._strategies[strategy_id] = rec
        self._save_record(rec)
        self._log_event(
            strategy_id,
            initial_stage,
            initial_stage,
            "registration",
            reason=f"Registered at {initial_stage.name}",
        )
        logger.info("Registered strategy %s at stage %s", strategy_id, initial_stage.name)
        return rec

    def record_fill(
        self,
        strategy_id: str,
        won: bool,
        pnl: float,
        fill_price: float = 0.0,
        expected_price: float = 0.0,
    ) -> StrategyRecord:
        """Record a single fill (trade resolved).  Updates stats."""
        rec = self._strategies[strategy_id]
        rec.fills += 1
        rec.metadata.setdefault("gross_wins", 0.0)
        rec.metadata.setdefault("gross_losses", 0.0)
        if won:
            rec.wins += 1
            rec.metadata["gross_wins"] += abs(pnl)
        else:
            rec.losses += 1
            rec.metadata["gross_losses"] += abs(pnl)
        rec.gross_pnl += pnl

        # Track slippage
        if expected_price > 0:
            slip = abs(fill_price - expected_price) / expected_price
            rec.slippage_values.append(slip)

        # Update fill rate
        rec.orders_submitted = max(rec.orders_submitted, rec.fills)
        if rec.orders_submitted > 0:
            rec.fill_rate = rec.fills / rec.orders_submitted

        self._save_record(rec)
        return rec

    def record_trade_return(self, strategy_id: str, net_return: float) -> StrategyRecord:
        """Append a per-trade net return (after fees) to the strategy record.

        This feeds the Bayesian log-growth posterior used by check_promotion_v2()
        and check_demotion_v2().  Call this in addition to (not instead of)
        record_fill() so that both legacy gates and v2 gates receive data.

        Args:
            strategy_id: the strategy to update
            net_return: fractional return after fees, e.g. 0.05 for +5%, -0.02 for -2%.
        """
        rec = self._strategies[strategy_id]
        rec.net_returns.append(net_return)
        self._save_record(rec)
        return rec

    def record_order_submitted(self, strategy_id: str) -> None:
        """Increment the submitted-order counter (for fill rate tracking)."""
        rec = self._strategies[strategy_id]
        rec.orders_submitted += 1
        if rec.orders_submitted > 0:
            rec.fill_rate = rec.fills / rec.orders_submitted
        self._save_record(rec)

    def record_day_close(self, strategy_id: str, daily_pnl: float) -> StrategyRecord:
        """Record end-of-day P&L.  Updates drawdown and daily history."""
        rec = self._strategies[strategy_id]
        rec.daily_pnl_history.append(daily_pnl)

        # Recompute max drawdown
        cum = 0.0
        peak = 0.0
        worst_dd = 0.0
        for d in rec.daily_pnl_history:
            cum += d
            if cum > peak:
                peak = cum
            dd = peak - cum
            if dd > worst_dd:
                worst_dd = dd
        rec.max_drawdown = worst_dd

        # Recompute annualised Sharpe (daily returns)
        if len(rec.daily_pnl_history) >= 2:
            mean_d = sum(rec.daily_pnl_history) / len(rec.daily_pnl_history)
            var_d = sum((x - mean_d) ** 2 for x in rec.daily_pnl_history) / len(
                rec.daily_pnl_history
            )
            std_d = math.sqrt(var_d) if var_d > 0 else 0.0
            rec.sharpe = (mean_d / std_d * math.sqrt(365)) if std_d > 0 else 0.0
        else:
            rec.sharpe = 0.0

        self._save_record(rec)
        return rec

    # ------------------------------------------------------------------
    # Promotion logic
    # ------------------------------------------------------------------

    def check_promotion(self, strategy_id: str) -> dict[str, Any]:
        """Check whether a strategy is eligible for promotion to the next stage.

        Returns:
            {
                "eligible": bool,
                "target_stage": int,
                "gates_passed": [str, ...],
                "gates_failed": [str, ...],
                "details": { gate_name: {required: ..., actual: ..., passed: bool} }
            }
        """
        rec = self._strategies[strategy_id]
        current = rec.current_stage
        target = PromotionStage(current + 1) if current < PromotionStage.CORE else None

        if target is None:
            return {
                "eligible": False,
                "target_stage": None,
                "gates_passed": [],
                "gates_failed": ["already_at_max_stage"],
                "details": {},
            }

        # Stage 6 requires human approval — block automated promotion
        if target == PromotionStage.CORE:
            return {
                "eligible": False,
                "target_stage": int(target),
                "gates_passed": [],
                "gates_failed": ["requires_human_approval"],
                "details": {"requires_human_approval": {
                    "required": "John's explicit sign-off",
                    "actual": "automated check",
                    "passed": False,
                }},
            }

        # Check cool-off
        if rec.cooloff_until > time.time():
            remaining = (rec.cooloff_until - time.time()) / 86400.0
            return {
                "eligible": False,
                "target_stage": int(target),
                "gates_passed": [],
                "gates_failed": ["cooloff_active"],
                "details": {"cooloff_active": {
                    "required": 0,
                    "actual": round(remaining, 1),
                    "passed": False,
                    "message": f"{remaining:.1f} days remaining in cool-off",
                }},
            }

        gate = STAGE_GATES.get(target)
        if gate is None:
            # Stages 0-2 have qualitative gates, not quantitative.
            # For now, allow promotion through them without quant gates.
            return {
                "eligible": True,
                "target_stage": int(target),
                "gates_passed": ["no_quantitative_gate"],
                "gates_failed": [],
                "details": {},
            }

        passed: list[str] = []
        failed: list[str] = []
        details: dict[str, dict] = {}

        # -- min fills --
        ok = rec.fills >= gate.min_fills
        entry = {"required": gate.min_fills, "actual": rec.fills, "passed": ok}
        details["min_fills"] = entry
        (passed if ok else failed).append("min_fills")

        # -- min days --
        days = rec.days_at_stage
        ok = days >= gate.min_days
        entry = {"required": gate.min_days, "actual": round(days, 1), "passed": ok}
        details["min_days"] = entry
        (passed if ok else failed).append("min_days")

        # -- win rate --
        wr = rec.win_rate
        ok = wr >= gate.min_win_rate
        entry = {"required": gate.min_win_rate, "actual": round(wr, 4), "passed": ok}
        details["min_win_rate"] = entry
        (passed if ok else failed).append("min_win_rate")

        # -- profit factor --
        pf = rec.profit_factor
        ok = pf >= gate.min_profit_factor
        entry = {"required": gate.min_profit_factor, "actual": round(pf, 4), "passed": ok}
        details["min_profit_factor"] = entry
        (passed if ok else failed).append("min_profit_factor")

        # -- max drawdown --
        # DD as fraction of allocated capital for the stage
        allocated = self._stage_capital(rec.current_stage)
        dd_pct = (rec.max_drawdown / allocated) if allocated > 0 else 0.0
        ok = dd_pct <= gate.max_drawdown_pct
        entry = {
            "required": f"<= {gate.max_drawdown_pct:.0%}",
            "actual": round(dd_pct, 4),
            "passed": ok,
        }
        details["max_drawdown_pct"] = entry
        (passed if ok else failed).append("max_drawdown_pct")

        # -- Sharpe --
        ok = rec.sharpe >= gate.min_sharpe
        entry = {"required": gate.min_sharpe, "actual": round(rec.sharpe, 2), "passed": ok}
        details["min_sharpe"] = entry
        (passed if ok else failed).append("min_sharpe")

        # -- fill rate --
        ok = rec.fill_rate >= gate.min_fill_rate
        entry = {"required": gate.min_fill_rate, "actual": round(rec.fill_rate, 4), "passed": ok}
        details["min_fill_rate"] = entry
        (passed if ok else failed).append("min_fill_rate")

        # -- binomial test (Stage 3 gate) --
        if gate.binomial_p_threshold < 1.0:
            p_val = binomial_test(rec.fills, rec.wins, 0.50)
            ok = p_val < gate.binomial_p_threshold
            entry = {
                "required": f"< {gate.binomial_p_threshold}",
                "actual": round(p_val, 6),
                "passed": ok,
            }
            details["binomial_test"] = entry
            (passed if ok else failed).append("binomial_test")

        # -- min Kelly (Stage 4 gate) --
        if gate.min_kelly > 0:
            kf = rec.kelly_fraction
            ok = kf >= gate.min_kelly
            entry = {"required": gate.min_kelly, "actual": round(kf, 4), "passed": ok}
            details["min_kelly"] = entry
            (passed if ok else failed).append("min_kelly")

        eligible = len(failed) == 0
        return {
            "eligible": eligible,
            "target_stage": int(target),
            "gates_passed": passed,
            "gates_failed": failed,
            "details": details,
        }

    def promote(self, strategy_id: str) -> StrategyRecord:
        """Move strategy to next stage if eligible.  Raises ValueError if not."""
        result = self.check_promotion(strategy_id)
        if not result["eligible"]:
            raise ValueError(
                f"Strategy {strategy_id} not eligible for promotion: "
                f"failed gates: {result['gates_failed']}"
            )

        rec = self._strategies[strategy_id]
        old_stage = rec.current_stage
        new_stage = PromotionStage(old_stage + 1)

        self._log_event(
            strategy_id, old_stage, new_stage, "promotion",
            gate_results=result["details"],
        )

        rec.current_stage = new_stage
        rec.stage_entered_at = time.time()
        # Reset per-stage counters for the new stage
        rec.fills = 0
        rec.wins = 0
        rec.losses = 0
        rec.gross_pnl = 0.0
        rec.max_drawdown = 0.0
        rec.daily_pnl_history = []
        rec.fill_rate = 0.0
        rec.orders_submitted = 0
        rec.sharpe = 0.0
        rec.slippage_values = []
        rec.metadata["gross_wins"] = 0.0
        rec.metadata["gross_losses"] = 0.0
        rec.cooloff_until = 0.0
        rec.demotion_reason = ""

        self._save_record(rec)
        logger.info(
            "PROMOTED %s: %s -> %s",
            strategy_id, old_stage.name, new_stage.name,
        )
        return rec

    # ------------------------------------------------------------------
    # Demotion logic
    # ------------------------------------------------------------------

    def check_demotion(self, strategy_id: str) -> dict[str, Any]:
        """Check whether any demotion triggers are active.

        Returns:
            {
                "should_demote": bool,
                "severity": "severe" | "moderate" | None,
                "triggers": [str, ...],
                "details": {...}
            }
        """
        rec = self._strategies[strategy_id]
        if rec.current_stage < PromotionStage.MICRO_LIVE:
            return {"should_demote": False, "severity": None, "triggers": [], "details": {}}

        triggers: list[str] = []
        details: dict[str, Any] = {}
        severity: Optional[str] = None

        allocated = self._stage_capital(rec.current_stage)

        # -- SEVERE: drawdown > stage cap --
        gate = STAGE_GATES.get(rec.current_stage)
        if gate and allocated > 0:
            dd_pct = rec.max_drawdown / allocated
            if dd_pct > gate.max_drawdown_pct:
                triggers.append("drawdown_breach")
                details["drawdown_breach"] = {
                    "cap": gate.max_drawdown_pct,
                    "actual": round(dd_pct, 4),
                }
                severity = "severe"

        # -- SEVERE: PF < 0.90 (rolling) --
        pf = rec.profit_factor
        if rec.fills >= 10 and pf < 0.90:
            triggers.append("profit_factor_collapse")
            details["profit_factor_collapse"] = {"threshold": 0.90, "actual": round(pf, 4)}
            severity = "severe"

        # -- SEVERE: fill rate < 10% --
        if rec.orders_submitted >= 20 and rec.fill_rate < 0.10:
            triggers.append("fill_rate_collapse")
            details["fill_rate_collapse"] = {"threshold": 0.10, "actual": round(rec.fill_rate, 4)}
            severity = "severe"

        # -- MODERATE: 3 consecutive losing days --
        if len(rec.daily_pnl_history) >= 3:
            last3 = rec.daily_pnl_history[-3:]
            if all(d < 0 for d in last3):
                triggers.append("three_consecutive_losing_days")
                details["three_consecutive_losing_days"] = {"last_3": last3}
                if severity is None:
                    severity = "moderate"

        # -- MODERATE: win rate below stage minimum --
        if gate and rec.fills >= 20:
            if rec.win_rate < gate.min_win_rate:
                triggers.append("win_rate_below_minimum")
                details["win_rate_below_minimum"] = {
                    "required": gate.min_win_rate,
                    "actual": round(rec.win_rate, 4),
                }
                if severity is None:
                    severity = "moderate"

        should_demote = len(triggers) > 0
        return {
            "should_demote": should_demote,
            "severity": severity,
            "triggers": triggers,
            "details": details,
        }

    def demote(self, strategy_id: str, reason: str = "") -> StrategyRecord:
        """Demote strategy by one stage.  Applies cool-off period."""
        rec = self._strategies[strategy_id]
        old_stage = rec.current_stage
        if old_stage <= PromotionStage.HYPOTHESIS:
            logger.warning("Cannot demote %s below HYPOTHESIS", strategy_id)
            return rec

        new_stage = PromotionStage(old_stage - 1)

        # Severe PF collapse: skip one stage per spec
        if "profit_factor_collapse" in reason and new_stage > PromotionStage.HYPOTHESIS:
            new_stage = PromotionStage(new_stage - 1)

        # Fill rate collapse: demote to SHADOW per spec
        if "fill_rate_collapse" in reason:
            new_stage = PromotionStage.SHADOW

        self._log_event(
            strategy_id, old_stage, new_stage, "demotion",
            reason=reason,
        )

        rec.current_stage = new_stage
        rec.stage_entered_at = time.time()
        rec.demotion_reason = reason

        # Apply cool-off
        cooloff_days = COOLOFF_DAYS.get(old_stage, 7)
        rec.cooloff_until = time.time() + (cooloff_days * 86400)

        # Reset per-stage stats for new stage
        rec.fills = 0
        rec.wins = 0
        rec.losses = 0
        rec.gross_pnl = 0.0
        rec.max_drawdown = 0.0
        rec.daily_pnl_history = []
        rec.fill_rate = 0.0
        rec.orders_submitted = 0
        rec.sharpe = 0.0
        rec.slippage_values = []
        rec.metadata["gross_wins"] = 0.0
        rec.metadata["gross_losses"] = 0.0

        self._save_record(rec)
        logger.info(
            "DEMOTED %s: %s -> %s (reason: %s, cooloff: %d days)",
            strategy_id, old_stage.name, new_stage.name, reason, cooloff_days,
        )
        return rec

    # ------------------------------------------------------------------
    # Bayesian v2 promotion / demotion gates (DISPATCH_111)
    # ------------------------------------------------------------------

    # Stage-dependent minimum observation counts for v2 gates
    _V2_MIN_OBS: dict[PromotionStage, int] = {
        PromotionStage.MICRO_LIVE: 10,   # shadow -> microlive
        PromotionStage.SEED: 30,          # microlive -> seed
        PromotionStage.SCALE: 100,        # seed -> scale
    }

    # P(mu>0) thresholds required to PROMOTE to each target stage
    _V2_PROMOTE_THRESHOLD: dict[PromotionStage, float] = {
        PromotionStage.MICRO_LIVE: 0.80,
        PromotionStage.SEED: 0.90,
        PromotionStage.SCALE: 0.95,
    }

    # P(mu>0) thresholds BELOW which we demote FROM each stage
    # (lower than promotion to prevent oscillation)
    _V2_DEMOTE_THRESHOLD: dict[PromotionStage, float] = {
        PromotionStage.MICRO_LIVE: 0.30,
        PromotionStage.SEED: 0.40,
        PromotionStage.SCALE: 0.50,
    }

    def _build_posterior(self, net_returns: list[float]) -> LogGrowthPosterior:
        """Construct a LogGrowthPosterior from a list of net returns."""
        posterior = LogGrowthPosterior()
        for r in net_returns:
            log_ret = math.log(1.0 + max(-0.99, r))
            posterior.update(log_ret)
        return posterior

    def check_promotion_v2(self, strategy_id: str) -> dict[str, Any]:
        """Bayesian log-growth promotion gate.

        Computes P(mu_ell > 0 | data) using Student-t posterior.
        Stage-dependent thresholds:
          shadow -> microlive: P >= 0.80, min 10 observations
          microlive -> seed:   P >= 0.90, min 30 observations
          seed -> scale:       P >= 0.95, min 100 observations

        Execution health gates (fill rate, drawdown) remain unchanged;
        this method only replaces the edge-quality gate.

        Returns the same dict shape as check_promotion() for easy comparison.
        """
        rec = self._strategies[strategy_id]
        current = rec.current_stage
        target = PromotionStage(current + 1) if current < PromotionStage.CORE else None

        base: dict[str, Any] = {
            "eligible": False,
            "target_stage": int(target) if target is not None else None,
            "gates_passed": [],
            "gates_failed": [],
            "details": {},
            "bayesian": {},
        }

        if target is None:
            base["gates_failed"].append("already_at_max_stage")
            return base

        if target == PromotionStage.CORE:
            base["gates_failed"].append("requires_human_approval")
            base["details"]["requires_human_approval"] = {
                "required": "John's explicit sign-off",
                "actual": "automated check",
                "passed": False,
            }
            return base

        # Cool-off check (same as v1)
        if rec.cooloff_until > time.time():
            remaining = (rec.cooloff_until - time.time()) / 86400.0
            base["gates_failed"].append("cooloff_active")
            base["details"]["cooloff_active"] = {
                "required": 0,
                "actual": round(remaining, 1),
                "passed": False,
                "message": f"{remaining:.1f} days remaining in cool-off",
            }
            return base

        # Stages without a v2 bayesian gate (HYPOTHESIS, BACKTESTED, SHADOW)
        promote_threshold = self._V2_PROMOTE_THRESHOLD.get(target)
        min_obs = self._V2_MIN_OBS.get(target)
        if promote_threshold is None:
            base["eligible"] = True
            base["gates_passed"].append("no_quantitative_gate")
            return base

        # ---- Bayesian edge-quality gate ----
        n_obs = len(rec.net_returns)
        posterior = self._build_posterior(rec.net_returns)
        p_pos = posterior.prob_positive()

        base["bayesian"] = posterior.to_dict()

        # Min observations gate
        obs_ok = n_obs >= min_obs
        base["details"]["min_observations"] = {
            "required": min_obs,
            "actual": n_obs,
            "passed": obs_ok,
        }
        (base["gates_passed"] if obs_ok else base["gates_failed"]).append("min_observations")

        # Posterior probability gate
        prob_ok = p_pos >= promote_threshold
        base["details"]["prob_positive"] = {
            "required": promote_threshold,
            "actual": round(p_pos, 6),
            "passed": prob_ok,
        }
        (base["gates_passed"] if prob_ok else base["gates_failed"]).append("prob_positive")

        # ---- Execution health gates (fill rate + drawdown, unchanged from v1) ----
        gate = STAGE_GATES.get(target)
        if gate is not None:
            # Fill rate
            fill_ok = rec.fill_rate >= gate.min_fill_rate
            base["details"]["min_fill_rate"] = {
                "required": gate.min_fill_rate,
                "actual": round(rec.fill_rate, 4),
                "passed": fill_ok,
            }
            (base["gates_passed"] if fill_ok else base["gates_failed"]).append("min_fill_rate")

            # Max drawdown
            allocated = self._stage_capital(rec.current_stage)
            dd_pct = (rec.max_drawdown / allocated) if allocated > 0 else 0.0
            dd_ok = dd_pct <= gate.max_drawdown_pct
            base["details"]["max_drawdown_pct"] = {
                "required": f"<= {gate.max_drawdown_pct:.0%}",
                "actual": round(dd_pct, 4),
                "passed": dd_ok,
            }
            (base["gates_passed"] if dd_ok else base["gates_failed"]).append("max_drawdown_pct")

        base["eligible"] = len(base["gates_failed"]) == 0
        return base

    def check_demotion_v2(self, strategy_id: str) -> dict[str, Any]:
        """Bayesian demotion gate.

        Demote thresholds (lower than promotion to prevent oscillation):
          microlive: P(mu>0) < 0.30
          seed:      P(mu>0) < 0.40
          scale:     P(mu>0) < 0.50

        Also retains the existing hard execution-health triggers (drawdown,
        fill-rate collapse) from check_demotion().
        """
        rec = self._strategies[strategy_id]
        if rec.current_stage < PromotionStage.MICRO_LIVE:
            return {
                "should_demote": False,
                "severity": None,
                "triggers": [],
                "details": {},
                "bayesian": {},
            }

        triggers: list[str] = []
        details: dict[str, Any] = {}
        severity: Optional[str] = None

        # ---- Bayesian edge-quality demotion gate ----
        demote_threshold = self._V2_DEMOTE_THRESHOLD.get(rec.current_stage)
        n_obs = len(rec.net_returns)
        posterior = self._build_posterior(rec.net_returns)
        p_pos = posterior.prob_positive()
        bayesian_info = posterior.to_dict()

        if demote_threshold is not None:
            min_obs_for_kill = 15  # Need at least 15 obs to pull the kill trigger
            if n_obs >= min_obs_for_kill and p_pos < demote_threshold:
                triggers.append("bayesian_edge_collapse")
                details["bayesian_edge_collapse"] = {
                    "threshold": demote_threshold,
                    "actual_prob_positive": round(p_pos, 6),
                    "n_observations": n_obs,
                    "posterior_mean": round(posterior.posterior_mean, 8),
                }
                severity = "severe"

        # ---- Hard execution-health triggers (same as v1) ----
        allocated = self._stage_capital(rec.current_stage)
        gate = STAGE_GATES.get(rec.current_stage)
        if gate and allocated > 0:
            dd_pct = rec.max_drawdown / allocated
            if dd_pct > gate.max_drawdown_pct:
                triggers.append("drawdown_breach")
                details["drawdown_breach"] = {
                    "cap": gate.max_drawdown_pct,
                    "actual": round(dd_pct, 4),
                }
                severity = "severe"

        pf = rec.profit_factor
        if rec.fills >= 10 and pf < 0.90:
            triggers.append("profit_factor_collapse")
            details["profit_factor_collapse"] = {"threshold": 0.90, "actual": round(pf, 4)}
            severity = "severe"

        if rec.orders_submitted >= 20 and rec.fill_rate < 0.10:
            triggers.append("fill_rate_collapse")
            details["fill_rate_collapse"] = {"threshold": 0.10, "actual": round(rec.fill_rate, 4)}
            severity = "severe"

        if len(rec.daily_pnl_history) >= 3:
            last3 = rec.daily_pnl_history[-3:]
            if all(d < 0 for d in last3):
                triggers.append("three_consecutive_losing_days")
                details["three_consecutive_losing_days"] = {"last_3": last3}
                if severity is None:
                    severity = "moderate"

        return {
            "should_demote": len(triggers) > 0,
            "severity": severity,
            "triggers": triggers,
            "details": details,
            "bayesian": bayesian_info,
        }

    def promote_v2(self, strategy_id: str) -> StrategyRecord:
        """Move strategy to next stage if eligible per Bayesian v2 gate.

        Uses check_promotion_v2() instead of check_promotion().
        Raises ValueError if not eligible.
        """
        result = self.check_promotion_v2(strategy_id)
        if not result["eligible"]:
            raise ValueError(
                f"Strategy {strategy_id} not eligible for v2 promotion: "
                f"failed gates: {result['gates_failed']}"
            )

        rec = self._strategies[strategy_id]
        old_stage = rec.current_stage
        new_stage = PromotionStage(old_stage + 1)

        self._log_event(
            strategy_id, old_stage, new_stage, "promotion_v2",
            gate_results=result["details"],
        )

        rec.current_stage = new_stage
        rec.stage_entered_at = time.time()
        # Reset per-stage counters for the new stage
        rec.fills = 0
        rec.wins = 0
        rec.losses = 0
        rec.gross_pnl = 0.0
        rec.max_drawdown = 0.0
        rec.daily_pnl_history = []
        rec.fill_rate = 0.0
        rec.orders_submitted = 0
        rec.sharpe = 0.0
        rec.slippage_values = []
        rec.net_returns = []
        rec.metadata["gross_wins"] = 0.0
        rec.metadata["gross_losses"] = 0.0
        rec.cooloff_until = 0.0
        rec.demotion_reason = ""

        self._save_record(rec)
        logger.info(
            "PROMOTED_V2 %s: %s -> %s (bayesian gate)",
            strategy_id, old_stage.name, new_stage.name,
        )
        return rec

    # ------------------------------------------------------------------
    # Capital & position queries
    # ------------------------------------------------------------------

    def get_position_cap(self, strategy_id: str) -> float:
        """Max position size USD for this strategy's current stage."""
        rec = self._strategies[strategy_id]
        return POSITION_CAP.get(rec.current_stage, 0.0)

    def get_capital_allocation(
        self, strategy_id: str, bankroll: float = 1000.0,
    ) -> float:
        """Max capital allocated to this strategy based on its stage and
        the number of strategies at that stage."""
        rec = self._strategies[strategy_id]
        stage_pct = STAGE_ALLOCATION_PCT.get(rec.current_stage, 0.0)
        total_stage_capital = bankroll * stage_pct

        # Count strategies at same stage
        same_stage = [
            s for s in self._strategies.values()
            if s.current_stage == rec.current_stage
        ]
        n = len(same_stage)
        if n == 0:
            return 0.0
        return total_stage_capital / n

    def _stage_capital(self, stage: PromotionStage, bankroll: float = 1000.0) -> float:
        """Total capital allocated to a stage."""
        pct = STAGE_ALLOCATION_PCT.get(stage, 0.0)
        return bankroll * pct

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_strategy(self, strategy_id: str) -> Optional[StrategyRecord]:
        return self._strategies.get(strategy_id)

    def get_all_strategies(self) -> list[StrategyRecord]:
        return list(self._strategies.values())

    def get_stage_summary(self, bankroll: float = 1000.0) -> dict[str, Any]:
        """Counts per stage, total capital per stage."""
        counts: dict[str, int] = {}
        capital: dict[str, float] = {}
        for stage in PromotionStage:
            name = stage.name
            strats = [s for s in self._strategies.values() if s.current_stage == stage]
            counts[name] = len(strats)
            pct = STAGE_ALLOCATION_PCT.get(stage, 0.0)
            capital[name] = bankroll * pct if strats else 0.0

        # Reserve
        deployed_pct = sum(
            STAGE_ALLOCATION_PCT.get(s.current_stage, 0.0)
            for s in self._strategies.values()
            if s.current_stage >= PromotionStage.MICRO_LIVE
        )
        reserve = max(bankroll * RESERVE_PCT, bankroll * (1.0 - deployed_pct))

        return {
            "counts": counts,
            "capital": capital,
            "reserve": round(reserve, 2),
            "bankroll": bankroll,
            "total_strategies": len(self._strategies),
        }

    def get_events(self, strategy_id: Optional[str] = None) -> list[dict]:
        """Retrieve promotion/demotion events from the DB."""
        if strategy_id:
            cursor = self._conn.execute(
                "SELECT * FROM promotion_events WHERE strategy_id = ? ORDER BY timestamp",
                (strategy_id,),
            )
        else:
            cursor = self._conn.execute(
                "SELECT * FROM promotion_events ORDER BY timestamp"
            )
        return [dict(row) for row in cursor.fetchall()]

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the SQLite connection."""
        if self._conn:
            self._conn.close()
            self._conn = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# False Promotion Tracker (DISPATCH_111)
# ---------------------------------------------------------------------------

@dataclass
class _PromotionRecord:
    """Internal record tracking a single promotion event."""
    strategy_id: str
    from_stage: PromotionStage
    to_stage: PromotionStage
    promoted_at: float
    demoted_at: Optional[float] = None
    reverted: bool = False


class FalsePromotionTracker:
    """Tracks promotions and flags strategies that get demoted within 21 days.

    A "false promotion" is a promotion that is reversed by a demotion within
    the lookback window.  This metric measures whether the promotion gate is
    too lenient.

    Usage:
        tracker = FalsePromotionTracker()
        tracker.record_promotion("strat_a", PromotionStage.SHADOW, PromotionStage.MICRO_LIVE)
        # ... later, if the strategy is demoted ...
        tracker.record_demotion("strat_a", PromotionStage.MICRO_LIVE, PromotionStage.SHADOW)
        summary = tracker.summary()
    """

    LOOKBACK_DAYS: float = 21.0

    def __init__(self) -> None:
        self._records: list[_PromotionRecord] = []

    def record_promotion(
        self,
        strategy_id: str,
        from_stage: PromotionStage,
        to_stage: PromotionStage,
        timestamp: Optional[float] = None,
    ) -> None:
        """Log a promotion event."""
        self._records.append(
            _PromotionRecord(
                strategy_id=strategy_id,
                from_stage=from_stage,
                to_stage=to_stage,
                promoted_at=timestamp if timestamp is not None else time.time(),
            )
        )
        logger.debug(
            "FalsePromotionTracker: recorded promotion %s %s->%s",
            strategy_id, from_stage.name, to_stage.name,
        )

    def record_demotion(
        self,
        strategy_id: str,
        from_stage: PromotionStage,
        to_stage: PromotionStage,
        timestamp: Optional[float] = None,
    ) -> None:
        """Log a demotion event; marks matching promotions as reverted if within lookback."""
        now = timestamp if timestamp is not None else time.time()
        lookback_cutoff = now - self.LOOKBACK_DAYS * 86400.0

        for rec in self._records:
            if (
                rec.strategy_id == strategy_id
                and rec.to_stage == from_stage
                and not rec.reverted
                and rec.demoted_at is None
                and rec.promoted_at >= lookback_cutoff
            ):
                rec.demoted_at = now
                rec.reverted = True
                logger.warning(
                    "FalsePromotionTracker: FALSE PROMOTION detected for %s "
                    "(%s->%s, reversed after %.1f days)",
                    strategy_id,
                    rec.from_stage.name,
                    rec.to_stage.name,
                    (now - rec.promoted_at) / 86400.0,
                )
                break  # Mark only the most-recent matching promotion

    def false_promotion_rate(self) -> float:
        """Fraction of promotions that were reversed within the lookback window.

        Only counts promotions old enough to have completed the full lookback
        period (or that have already been reverted).
        """
        now = time.time()
        lookback_secs = self.LOOKBACK_DAYS * 86400.0
        eligible = [
            r for r in self._records
            if (now - r.promoted_at) >= lookback_secs or r.reverted
        ]
        if not eligible:
            return 0.0
        reverted = sum(1 for r in eligible if r.reverted)
        return reverted / len(eligible)

    def get_false_promotions(self) -> list[dict[str, Any]]:
        """Return all confirmed false promotions."""
        return [
            {
                "strategy_id": r.strategy_id,
                "from_stage": r.from_stage.name,
                "to_stage": r.to_stage.name,
                "promoted_at": r.promoted_at,
                "demoted_at": r.demoted_at,
                "days_before_demotion": (
                    (r.demoted_at - r.promoted_at) / 86400.0
                    if r.demoted_at is not None else None
                ),
            }
            for r in self._records
            if r.reverted
        ]

    def summary(self) -> dict[str, Any]:
        """Full tracker summary."""
        return {
            "total_promotions": len(self._records),
            "false_promotions": len(self.get_false_promotions()),
            "false_promotion_rate": round(self.false_promotion_rate(), 4),
            "lookback_days": self.LOOKBACK_DAYS,
            "records": self.get_false_promotions(),
        }
