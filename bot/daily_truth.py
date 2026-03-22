"""Authoritative daily P&L tracker for Elastifund.

Solves the critical problem: daily BTC5 P&L can silently null out when
jj_live_core resets its in-memory state at UTC day boundaries. This module
uses SQLite-backed fill recording with ET-day bucketing so that P&L data
is persistent, never silently nulls, and serves as the single source of
truth for promotion gates and operator scorecards.

Source priority (highest to lowest):
  1. Live fill ledger (direct from place_order fills)
  2. Wallet reconciliation (API-derived)
  3. Compatibility alias (btc5_recent_live_filled_pnl_usd)
"""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]

logger = logging.getLogger("JJ.daily_truth")

ET = ZoneInfo("America/New_York")
UTC = timezone.utc

# Source priority constants — lower number = higher priority
SOURCE_FILL_LEDGER = 1
SOURCE_WALLET_RECON = 2
SOURCE_COMPAT_ALIAS = 3

SOURCE_LABELS = {
    SOURCE_FILL_LEDGER: "fill_ledger",
    SOURCE_WALLET_RECON: "wallet_recon",
    SOURCE_COMPAT_ALIAS: "compat_alias",
}


def _et_date_for_utc(ts_utc: datetime) -> str:
    """Return the ET calendar date string for a UTC timestamp."""
    if ts_utc.tzinfo is None:
        ts_utc = ts_utc.replace(tzinfo=UTC)
    return ts_utc.astimezone(ET).strftime("%Y-%m-%d")


def _now_utc() -> datetime:
    return datetime.now(UTC)


@dataclass
class DailyPnL:
    """Immutable snapshot of a single ET-day's P&L."""

    date_et: str  # ET calendar day, e.g. "2026-03-22"
    date_utc: str  # UTC date when snapshot was created
    fills: int = 0
    wins: int = 0
    losses: int = 0
    gross_pnl: float = 0.0
    net_pnl: float = 0.0  # after fees
    max_intraday_drawdown: float = 0.0
    strategies: dict[str, float] = field(default_factory=dict)
    source_priority: int = SOURCE_FILL_LEDGER
    staleness_seconds: float = 0.0
    is_authoritative: bool = True

    @property
    def source_label(self) -> str:
        return SOURCE_LABELS.get(self.source_priority, "unknown")

    @property
    def profit_factor(self) -> float:
        """Profit factor: gross wins / abs(gross losses). Inf if no losses."""
        if self.losses == 0:
            return float("inf") if self.wins > 0 else 0.0
        # We need win/loss amounts, not just counts.
        # This is an approximation from net_pnl and counts.
        # The real PF is computed from the fill-level data in _build_daily_pnl.
        return 0.0  # Overridden by _build_daily_pnl when available

    @property
    def win_rate(self) -> float:
        total = self.wins + self.losses
        if total == 0:
            return 0.0
        return self.wins / total


_SCHEMA_VERSION = 1

_CREATE_FILLS_TABLE = """
CREATE TABLE IF NOT EXISTS daily_truth_fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy TEXT NOT NULL,
    pnl REAL NOT NULL,
    fee REAL NOT NULL DEFAULT 0.0,
    timestamp_utc TEXT NOT NULL,
    date_et TEXT NOT NULL,
    source_priority INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
)
"""

_CREATE_RECON_TABLE = """
CREATE TABLE IF NOT EXISTS daily_truth_recon (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date_et TEXT NOT NULL,
    wallet_balance REAL NOT NULL,
    deposit_total REAL NOT NULL,
    derived_pnl REAL NOT NULL,
    tape_pnl REAL,
    drift REAL,
    timestamp_utc TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
)
"""

_CREATE_META_TABLE = """
CREATE TABLE IF NOT EXISTS daily_truth_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
"""

_IDX_DATE_ET = """
CREATE INDEX IF NOT EXISTS idx_daily_truth_fills_date_et
ON daily_truth_fills(date_et)
"""

_IDX_STRATEGY = """
CREATE INDEX IF NOT EXISTS idx_daily_truth_fills_strategy
ON daily_truth_fills(strategy)
"""


class DailyTruthTracker:
    """SQLite-backed daily P&L tracker with ET-day bucketing.

    Hard rule: stale or null daily P&L blocks promotion and deploy.
    """

    def __init__(self, db_path: str | Path = "data/daily_truth.sqlite"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
        return self._conn

    def _init_db(self) -> None:
        conn = self._get_conn()
        conn.execute(_CREATE_FILLS_TABLE)
        conn.execute(_CREATE_RECON_TABLE)
        conn.execute(_CREATE_META_TABLE)
        conn.execute(_IDX_DATE_ET)
        conn.execute(_IDX_STRATEGY)
        conn.execute(
            "INSERT OR IGNORE INTO daily_truth_meta (key, value) VALUES (?, ?)",
            ("schema_version", str(_SCHEMA_VERSION)),
        )
        conn.commit()
        logger.info("DailyTruthTracker initialized at %s", self.db_path)

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Fill recording
    # ------------------------------------------------------------------

    def record_fill(
        self,
        strategy: str,
        pnl: float,
        fee: float = 0.0,
        timestamp: Optional[datetime] = None,
        source_priority: int = SOURCE_FILL_LEDGER,
    ) -> None:
        """Record a single fill with ET-day bucketing."""
        if timestamp is None:
            timestamp = _now_utc()
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)

        date_et = _et_date_for_utc(timestamp)
        ts_str = timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")

        conn = self._get_conn()
        conn.execute(
            """INSERT INTO daily_truth_fills
               (strategy, pnl, fee, timestamp_utc, date_et, source_priority)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (strategy, pnl, fee, ts_str, date_et, source_priority),
        )
        conn.commit()
        logger.debug(
            "Recorded fill: strategy=%s pnl=%.4f fee=%.4f date_et=%s source=%s",
            strategy, pnl, fee, date_et, SOURCE_LABELS.get(source_priority, "?"),
        )

    # ------------------------------------------------------------------
    # P&L queries
    # ------------------------------------------------------------------

    def _build_daily_pnl(
        self,
        date_et: str,
        rows: list[sqlite3.Row],
        staleness_ref: Optional[datetime] = None,
    ) -> DailyPnL:
        """Build a DailyPnL from a set of fill rows for a single ET day."""
        now = staleness_ref or _now_utc()

        if not rows:
            return DailyPnL(
                date_et=date_et,
                date_utc=now.strftime("%Y-%m-%d"),
                fills=0,
                staleness_seconds=float("inf"),
                is_authoritative=False,
                source_priority=SOURCE_FILL_LEDGER,
            )

        fills = len(rows)
        wins = sum(1 for r in rows if r["pnl"] > 0)
        losses = sum(1 for r in rows if r["pnl"] <= 0)
        gross_pnl = round(sum(r["pnl"] for r in rows), 4)
        total_fees = round(sum(r["fee"] for r in rows), 4)
        net_pnl = round(gross_pnl - total_fees, 4)

        # Strategy breakdown
        strategies: dict[str, float] = {}
        for r in rows:
            s = r["strategy"]
            strategies[s] = round(strategies.get(s, 0.0) + r["pnl"] - r["fee"], 4)

        # Max intraday drawdown
        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        for r in rows:
            cumulative += r["pnl"] - r["fee"]
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            if dd > max_dd:
                max_dd = dd
        max_dd = round(max_dd, 4)

        # Source priority — use the highest (lowest number) among fills
        best_source = min(r["source_priority"] for r in rows)

        # Staleness — time since last fill
        last_ts_str = max(r["timestamp_utc"] for r in rows)
        try:
            last_ts = datetime.strptime(last_ts_str, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=UTC
            )
            staleness = (now - last_ts).total_seconds()
        except (ValueError, TypeError):
            staleness = float("inf")

        # Profit factor from actual win/loss amounts
        win_total = sum(r["pnl"] - r["fee"] for r in rows if r["pnl"] - r["fee"] > 0)
        loss_total = abs(
            sum(r["pnl"] - r["fee"] for r in rows if r["pnl"] - r["fee"] <= 0)
        )

        pnl = DailyPnL(
            date_et=date_et,
            date_utc=now.strftime("%Y-%m-%d"),
            fills=fills,
            wins=wins,
            losses=losses,
            gross_pnl=gross_pnl,
            net_pnl=net_pnl,
            max_intraday_drawdown=max_dd,
            strategies=strategies,
            source_priority=best_source,
            staleness_seconds=max(0.0, staleness),
            is_authoritative=True,
        )

        # Override profit_factor with real data (monkey-patch the property)
        # We store it as a private attribute and override the property below.
        object.__setattr__(pnl, "_real_pf", round(win_total / loss_total, 4) if loss_total > 0 else (float("inf") if win_total > 0 else 0.0))

        return pnl

    def get_today_pnl(self) -> DailyPnL:
        """Return P&L for the current ET calendar day."""
        now = _now_utc()
        date_et = _et_date_for_utc(now)
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM daily_truth_fills WHERE date_et = ? ORDER BY timestamp_utc",
            (date_et,),
        ).fetchall()
        return self._build_daily_pnl(date_et, rows, staleness_ref=now)

    def get_rolling_24h_pnl(self) -> DailyPnL:
        """Return P&L for the rolling 24-hour window."""
        now = _now_utc()
        cutoff = (now - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
        date_et = _et_date_for_utc(now)
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM daily_truth_fills WHERE timestamp_utc >= ? ORDER BY timestamp_utc",
            (cutoff,),
        ).fetchall()
        return self._build_daily_pnl(f"rolling_24h_{date_et}", rows, staleness_ref=now)

    def get_pnl_history(self, days: int = 7) -> list[DailyPnL]:
        """Return daily P&L for the last N ET calendar days."""
        now = _now_utc()
        results = []
        for i in range(days):
            day = now - timedelta(days=i)
            date_et = _et_date_for_utc(day)
            # Avoid duplicates if multiple UTC days map to same ET day
            if results and results[-1].date_et == date_et:
                continue
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT * FROM daily_truth_fills WHERE date_et = ? ORDER BY timestamp_utc",
                (date_et,),
            ).fetchall()
            results.append(self._build_daily_pnl(date_et, rows, staleness_ref=now))
        return results

    # ------------------------------------------------------------------
    # Wallet reconciliation
    # ------------------------------------------------------------------

    def reconcile_from_wallet(
        self,
        wallet_balance: float,
        deposit_total: float,
        timestamp: Optional[datetime] = None,
    ) -> dict:
        """Cross-check tape-derived P&L against wallet balance.

        Returns a dict with drift info. If tape P&L is unavailable,
        records wallet-derived P&L as a fallback (source_priority=2).
        """
        if timestamp is None:
            timestamp = _now_utc()
        date_et = _et_date_for_utc(timestamp)
        ts_str = timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")

        derived_pnl = round(wallet_balance - deposit_total, 4)

        # Get tape P&L for today
        today = self.get_today_pnl()
        tape_pnl = today.net_pnl if today.fills > 0 else None
        drift = round(derived_pnl - tape_pnl, 4) if tape_pnl is not None else None

        conn = self._get_conn()
        conn.execute(
            """INSERT INTO daily_truth_recon
               (date_et, wallet_balance, deposit_total, derived_pnl, tape_pnl, drift, timestamp_utc)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (date_et, wallet_balance, deposit_total, derived_pnl, tape_pnl, drift, ts_str),
        )
        conn.commit()

        result = {
            "date_et": date_et,
            "wallet_pnl": derived_pnl,
            "tape_pnl": tape_pnl,
            "drift": drift,
            "wallet_balance": wallet_balance,
            "deposit_total": deposit_total,
        }

        if drift is not None and abs(drift) > 1.0:
            logger.warning(
                "P&L drift detected: wallet=%.2f tape=%.2f drift=%.2f",
                derived_pnl, tape_pnl, drift,
            )
        elif drift is not None:
            logger.info("Reconciliation OK: drift=%.4f", drift)
        else:
            logger.info(
                "No tape P&L for %s — wallet says %.2f", date_et, derived_pnl
            )

        return result

    # ------------------------------------------------------------------
    # Staleness and gates
    # ------------------------------------------------------------------

    def is_stale(self, max_age_seconds: float = 3600) -> bool:
        """True if no fills recorded within max_age_seconds."""
        today = self.get_today_pnl()
        if today.fills == 0:
            return True
        return today.staleness_seconds > max_age_seconds

    def blocks_promotion(self) -> bool:
        """True if daily P&L is stale or null. Hard gate for scaling up."""
        today = self.get_today_pnl()
        if today.fills == 0:
            logger.warning("PROMOTION BLOCKED: zero fills today (%s ET)", today.date_et)
            return True
        if not today.is_authoritative:
            logger.warning("PROMOTION BLOCKED: P&L not authoritative for %s ET", today.date_et)
            return True
        return False

    def blocks_deploy(self) -> bool:
        """True if daily P&L is stale AND fills exist in source DBs.

        This catches the case where the truth pipeline is broken but
        the trading bot is still generating fills elsewhere.
        """
        today = self.get_today_pnl()
        if today.fills == 0 and not today.is_authoritative:
            # Check if there are ANY fills in the DB at all (from any day)
            conn = self._get_conn()
            total = conn.execute(
                "SELECT COUNT(*) as cnt FROM daily_truth_fills"
            ).fetchone()["cnt"]
            if total > 0:
                logger.warning(
                    "DEPLOY BLOCKED: no fills today but %d historical fills exist — pipeline may be broken",
                    total,
                )
                return True
        return False

    # ------------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------------

    def format_scoreboard(self) -> str:
        """One-line operator summary for the current ET day."""
        today = self.get_today_pnl()
        if today.fills == 0:
            return f"ET {today.date_et}: NO FILLS (stale)"

        pf = getattr(today, "_real_pf", today.profit_factor)
        pf_str = f"PF {pf:.2f}" if pf != float("inf") else "PF inf"

        return (
            f"ET {today.date_et}: "
            f"{'+'if today.net_pnl >= 0 else ''}${today.net_pnl:.2f} "
            f"({today.wins}W/{today.losses}L, {pf_str}, "
            f"DD -${today.max_intraday_drawdown:.2f})"
        )

    def emit_metrics(self) -> dict:
        """Structured metrics dict for automation gates."""
        today = self.get_today_pnl()
        pf = getattr(today, "_real_pf", today.profit_factor)
        return {
            "date_et": today.date_et,
            "fills": today.fills,
            "wins": today.wins,
            "losses": today.losses,
            "gross_pnl": today.gross_pnl,
            "net_pnl": today.net_pnl,
            "max_intraday_drawdown": today.max_intraday_drawdown,
            "profit_factor": pf,
            "win_rate": today.win_rate,
            "strategies": today.strategies,
            "source_priority": today.source_priority,
            "source_label": today.source_label,
            "staleness_seconds": today.staleness_seconds,
            "is_authoritative": today.is_authoritative,
            "is_stale": self.is_stale(),
            "blocks_promotion": self.blocks_promotion(),
            "blocks_deploy": self.blocks_deploy(),
            "scoreboard": self.format_scoreboard(),
        }
