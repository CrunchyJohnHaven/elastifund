#!/usr/bin/env python3
"""Execution liveness monitor: detects when the bot is alive but not trading.

The existing health_monitor.py checks process liveness (heartbeat age, service
status).  This module checks *execution* liveness -- whether the bot is
actually producing fills, maintaining a healthy skip rate, and staying
consistent with wallet state.

Alerting channels:
  1. Telegram  (via TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)
  2. JSONL log (always, ``reports/liveness_alerts.jsonl``)
  3. Console   (stdout via logging)

All thresholds are configurable through environment variables.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, List, Optional

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("execution_liveness")

# ---------------------------------------------------------------------------
# Defaults (all overridable via env vars)
# ---------------------------------------------------------------------------

DEFAULT_FILL_TIMEOUT_MINUTES = int(
    os.environ.get("LIVENESS_FILL_TIMEOUT_MINUTES", "60")
)
DEFAULT_MAX_SKIP_RATE = float(
    os.environ.get("LIVENESS_MAX_SKIP_RATE", "0.80")
)
DEFAULT_PIPELINE_STALE_HOURS = int(
    os.environ.get("LIVENESS_PIPELINE_STALE_HOURS", "48")
)
DEFAULT_PNL_DROP_THRESHOLD = float(
    os.environ.get("LIVENESS_PNL_DROP_THRESHOLD", "25.0")
)
DEFAULT_CHECK_INTERVAL_SECONDS = int(
    os.environ.get("LIVENESS_CHECK_INTERVAL_SECONDS", "300")
)
DEFAULT_DB_PATH = Path(
    os.environ.get("JJ_DB_FILE", "data/jj_trades.db")
)
DEFAULT_BTC5_DB_PATH = Path(
    os.environ.get("BTC5_DB_FILE", "data/btc_5min_maker.db")
)
DEFAULT_ALERT_LOG_PATH = Path(
    os.environ.get("LIVENESS_ALERT_LOG", "reports/liveness_alerts.jsonl")
)
DEFAULT_PIPELINE_FILE = Path(
    os.environ.get("LIVENESS_PIPELINE_FILE", "FAST_TRADE_EDGE_ANALYSIS.md")
)
DEFAULT_WALLET_STATE_FILE = Path(
    os.environ.get("LIVENESS_WALLET_STATE_FILE", "data/wallet_state.json")
)

MONITORED_SERVICES = [
    s.strip()
    for s in os.environ.get(
        "LIVENESS_SERVICES", "jj-live.service,btc-5min-maker.service,wallet-poller.service"
    ).split(",")
    if s.strip()
]

# Cooldown: suppress duplicate alerts for the same check within this window.
ALERT_COOLDOWN_SECONDS = int(
    os.environ.get("LIVENESS_ALERT_COOLDOWN_SECONDS", "900")
)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class Severity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass
class AlertResult:
    """Outcome of a single liveness check."""

    check_name: str
    passed: bool
    severity: Severity = Severity.INFO
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: _utc_now().isoformat())

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["severity"] = self.severity.value
        return d


@dataclass
class LivenessConfig:
    """Aggregated configuration for all liveness checks."""

    fill_timeout_minutes: int = DEFAULT_FILL_TIMEOUT_MINUTES
    max_skip_rate: float = DEFAULT_MAX_SKIP_RATE
    pipeline_stale_hours: int = DEFAULT_PIPELINE_STALE_HOURS
    pnl_drop_threshold: float = DEFAULT_PNL_DROP_THRESHOLD
    check_interval_seconds: int = DEFAULT_CHECK_INTERVAL_SECONDS
    db_path: Path = DEFAULT_DB_PATH
    btc5_db_path: Path = DEFAULT_BTC5_DB_PATH
    alert_log_path: Path = DEFAULT_ALERT_LOG_PATH
    pipeline_file: Path = DEFAULT_PIPELINE_FILE
    wallet_state_file: Path = DEFAULT_WALLET_STATE_FILE
    monitored_services: list[str] = field(default_factory=lambda: list(MONITORED_SERVICES))
    alert_cooldown_seconds: int = ALERT_COOLDOWN_SECONDS

    @classmethod
    def from_env(cls) -> "LivenessConfig":
        """Build config entirely from environment variables / defaults."""
        return cls()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _connect_db(db_path: Path) -> Optional[sqlite3.Connection]:
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error:
        return None


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
            (table_name,),
        ).fetchone()
        return row is not None
    except sqlite3.Error:
        return False


def _build_telegram_sender() -> Optional[Callable[[str], bool]]:
    """Reuse the health_monitor pattern for Telegram."""
    try:
        try:
            from bot.health_monitor import build_telegram_sender
        except ImportError:
            from health_monitor import build_telegram_sender  # type: ignore[no-redef]
        return build_telegram_sender()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# LivenessMonitor
# ---------------------------------------------------------------------------

class LivenessMonitor:
    """Monitors whether the bot is actually executing trades, not just alive."""

    def __init__(
        self,
        config: Optional[LivenessConfig] = None,
        telegram_sender: Optional[Callable[[str], bool]] = None,
        *,
        _now_fn: Optional[Callable[[], datetime]] = None,
    ):
        self.config = config or LivenessConfig.from_env()
        self._telegram_sender = telegram_sender
        self._telegram_initialized = telegram_sender is not None
        self._now = _now_fn or _utc_now
        self._cooldown_tracker: dict[str, datetime] = {}

    # -- lazy Telegram init ------------------------------------------------

    @property
    def telegram_sender(self) -> Optional[Callable[[str], bool]]:
        if not self._telegram_initialized:
            self._telegram_sender = _build_telegram_sender()
            self._telegram_initialized = True
        return self._telegram_sender

    # -- individual checks -------------------------------------------------

    def check_fill_flow(self) -> AlertResult:
        """Alert if no fills recorded in the last N minutes."""
        now = self._now()
        cutoff = now - timedelta(minutes=self.config.fill_timeout_minutes)
        cutoff_iso = cutoff.isoformat()

        fill_count = 0
        last_fill_ts: Optional[str] = None

        # Check jj_trades.db
        conn = _connect_db(self.config.db_path)
        if conn is not None:
            try:
                if _table_exists(conn, "trades"):
                    row = conn.execute(
                        "SELECT COUNT(*) AS cnt, MAX(timestamp) AS last_ts "
                        "FROM trades WHERE timestamp >= ?",
                        (cutoff_iso,),
                    ).fetchone()
                    if row:
                        fill_count += row["cnt"] or 0
                        last_fill_ts = row["last_ts"] or last_fill_ts
            finally:
                conn.close()

        # Check btc_5min_maker.db (window_trades table)
        conn2 = _connect_db(self.config.btc5_db_path)
        if conn2 is not None:
            try:
                if _table_exists(conn2, "window_trades"):
                    cutoff_epoch = int(cutoff.timestamp())
                    row2 = conn2.execute(
                        "SELECT COUNT(*) AS cnt, MAX(decision_ts) AS last_ts "
                        "FROM window_trades "
                        "WHERE order_status = 'filled' AND decision_ts >= ?",
                        (cutoff_epoch,),
                    ).fetchone()
                    if row2:
                        fill_count += row2["cnt"] or 0
                        if row2["last_ts"]:
                            ts_str = datetime.fromtimestamp(
                                row2["last_ts"], tz=timezone.utc
                            ).isoformat()
                            if last_fill_ts is None or ts_str > last_fill_ts:
                                last_fill_ts = ts_str
            finally:
                conn2.close()

        if fill_count > 0:
            return AlertResult(
                check_name="fill_flow",
                passed=True,
                severity=Severity.INFO,
                message=f"{fill_count} fills in last {self.config.fill_timeout_minutes}m",
                details={"fill_count": fill_count, "last_fill": last_fill_ts},
            )

        return AlertResult(
            check_name="fill_flow",
            passed=False,
            severity=Severity.CRITICAL,
            message=(
                f"Zero fills in last {self.config.fill_timeout_minutes} minutes. "
                f"Last fill: {last_fill_ts or 'never'}"
            ),
            details={
                "fill_count": 0,
                "last_fill": last_fill_ts,
                "timeout_minutes": self.config.fill_timeout_minutes,
            },
        )

    def check_skip_rate(self) -> AlertResult:
        """Alert if skip rate exceeds threshold in the last hour."""
        now = self._now()
        cutoff_epoch = int((now - timedelta(hours=1)).timestamp())
        total = 0
        skips = 0

        conn = _connect_db(self.config.btc5_db_path)
        if conn is not None:
            try:
                if _table_exists(conn, "window_trades"):
                    row = conn.execute(
                        "SELECT COUNT(*) AS total, "
                        "SUM(CASE WHEN order_status LIKE 'skip_%' THEN 1 ELSE 0 END) AS skips "
                        "FROM window_trades WHERE decision_ts >= ?",
                        (cutoff_epoch,),
                    ).fetchone()
                    if row:
                        total = row["total"] or 0
                        skips = row["skips"] or 0
            finally:
                conn.close()

        if total == 0:
            return AlertResult(
                check_name="skip_rate",
                passed=True,
                severity=Severity.INFO,
                message="No decisions recorded in last hour (nothing to evaluate)",
                details={"total": 0, "skips": 0, "skip_rate": 0.0},
            )

        skip_rate = skips / total
        passed = skip_rate <= self.config.max_skip_rate

        return AlertResult(
            check_name="skip_rate",
            passed=passed,
            severity=Severity.WARNING if not passed else Severity.INFO,
            message=(
                f"Skip rate {skip_rate:.1%} ({skips}/{total}) in last hour"
                + ("" if passed else f" -- exceeds threshold {self.config.max_skip_rate:.0%}")
            ),
            details={
                "total": total,
                "skips": skips,
                "skip_rate": round(skip_rate, 4),
                "threshold": self.config.max_skip_rate,
            },
        )

    def check_wallet_drift(self) -> AlertResult:
        """Alert if wallet reconciliation state shows unmatched positions."""
        ws_path = self.config.wallet_state_file
        if not ws_path.exists():
            return AlertResult(
                check_name="wallet_drift",
                passed=True,
                severity=Severity.INFO,
                message="No wallet state file found (skipping drift check)",
                details={"file": str(ws_path)},
            )

        try:
            data = json.loads(ws_path.read_text())
        except (json.JSONDecodeError, OSError):
            return AlertResult(
                check_name="wallet_drift",
                passed=False,
                severity=Severity.WARNING,
                message=f"Could not read wallet state from {ws_path}",
                details={"file": str(ws_path)},
            )

        unmatched = data.get("unmatched_positions", [])
        last_reconcile = data.get("last_reconcile_ts")

        if unmatched:
            return AlertResult(
                check_name="wallet_drift",
                passed=False,
                severity=Severity.CRITICAL,
                message=f"{len(unmatched)} unmatched positions detected in wallet reconciliation",
                details={
                    "unmatched_count": len(unmatched),
                    "unmatched": unmatched[:5],  # cap detail size
                    "last_reconcile": last_reconcile,
                },
            )

        return AlertResult(
            check_name="wallet_drift",
            passed=True,
            severity=Severity.INFO,
            message="Wallet reconciliation clean",
            details={"last_reconcile": last_reconcile},
        )

    def check_pipeline_freshness(self) -> AlertResult:
        """Alert if FAST_TRADE_EDGE_ANALYSIS.md is stale."""
        p = self.config.pipeline_file
        if not p.exists():
            return AlertResult(
                check_name="pipeline_freshness",
                passed=False,
                severity=Severity.WARNING,
                message=f"Pipeline file not found: {p}",
                details={"file": str(p)},
            )

        try:
            mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
        except OSError:
            return AlertResult(
                check_name="pipeline_freshness",
                passed=False,
                severity=Severity.WARNING,
                message=f"Cannot stat pipeline file: {p}",
                details={"file": str(p)},
            )

        age_hours = (self._now() - mtime).total_seconds() / 3600
        threshold = self.config.pipeline_stale_hours
        passed = age_hours <= threshold

        return AlertResult(
            check_name="pipeline_freshness",
            passed=passed,
            severity=Severity.WARNING if not passed else Severity.INFO,
            message=(
                f"Pipeline file age: {age_hours:.1f}h"
                + ("" if passed else f" -- stale (threshold {threshold}h)")
            ),
            details={
                "age_hours": round(age_hours, 2),
                "threshold_hours": threshold,
                "mtime": mtime.isoformat(),
            },
        )

    def check_pnl_anomaly(self) -> AlertResult:
        """Alert if realized PnL drops more than threshold in a single day."""
        conn = _connect_db(self.config.db_path)
        if conn is None:
            return AlertResult(
                check_name="pnl_anomaly",
                passed=True,
                severity=Severity.INFO,
                message="Trade database not available (skipping PnL check)",
                details={},
            )

        try:
            today_iso = self._now().strftime("%Y-%m-%d")

            # Check trades table for resolved_at today with negative pnl
            if not _table_exists(conn, "trades"):
                return AlertResult(
                    check_name="pnl_anomaly",
                    passed=True,
                    severity=Severity.INFO,
                    message="No trades table found",
                    details={},
                )

            row = conn.execute(
                "SELECT COALESCE(SUM(pnl), 0.0) AS day_pnl "
                "FROM trades WHERE resolved_at >= ?",
                (today_iso,),
            ).fetchone()

            day_pnl = float(row["day_pnl"]) if row else 0.0
        finally:
            conn.close()

        threshold = self.config.pnl_drop_threshold
        passed = day_pnl >= -threshold

        return AlertResult(
            check_name="pnl_anomaly",
            passed=passed,
            severity=Severity.CRITICAL if not passed else Severity.INFO,
            message=(
                f"Today realized PnL: ${day_pnl:+.2f}"
                + ("" if passed else f" -- exceeds -${threshold:.2f} threshold")
            ),
            details={
                "day_pnl": round(day_pnl, 2),
                "threshold": threshold,
                "date": today_iso,
            },
        )

    def check_service_health(self) -> AlertResult:
        """Check if monitored systemd services are running."""
        services = self.config.monitored_services
        if not services:
            return AlertResult(
                check_name="service_health",
                passed=True,
                severity=Severity.INFO,
                message="No services configured for monitoring",
                details={},
            )

        down: list[str] = []
        up: list[str] = []
        unknown: list[str] = []

        for svc in services:
            try:
                result = subprocess.run(
                    ["systemctl", "is-active", svc],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                status = result.stdout.strip()
                if status == "active":
                    up.append(svc)
                else:
                    down.append(svc)
            except FileNotFoundError:
                # systemctl not available (macOS dev, CI, etc.)
                unknown.append(svc)
            except subprocess.TimeoutExpired:
                unknown.append(svc)
            except Exception:
                unknown.append(svc)

        if unknown and not down and not up:
            # systemctl not available at all (dev machine)
            return AlertResult(
                check_name="service_health",
                passed=True,
                severity=Severity.INFO,
                message="systemctl not available (dev environment), skipping",
                details={"unknown": unknown},
            )

        if down:
            return AlertResult(
                check_name="service_health",
                passed=False,
                severity=Severity.CRITICAL,
                message=f"Services DOWN: {', '.join(down)}",
                details={"down": down, "up": up, "unknown": unknown},
            )

        return AlertResult(
            check_name="service_health",
            passed=True,
            severity=Severity.INFO,
            message=f"All {len(up)} monitored services active",
            details={"up": up, "unknown": unknown},
        )

    # -- orchestration -----------------------------------------------------

    def run_all_checks(self) -> List[AlertResult]:
        """Run every liveness check and return all results."""
        checks = [
            self.check_fill_flow,
            self.check_skip_rate,
            self.check_wallet_drift,
            self.check_pipeline_freshness,
            self.check_pnl_anomaly,
            self.check_service_health,
        ]
        results: list[AlertResult] = []
        for check_fn in checks:
            try:
                results.append(check_fn())
            except Exception as exc:
                results.append(
                    AlertResult(
                        check_name=check_fn.__name__.replace("check_", ""),
                        passed=False,
                        severity=Severity.WARNING,
                        message=f"Check raised exception: {exc}",
                        details={"error": str(exc)},
                    )
                )
        return results

    # -- alerting ----------------------------------------------------------

    def _is_cooled_down(self, check_name: str) -> bool:
        last = self._cooldown_tracker.get(check_name)
        if last is None:
            return False
        elapsed = (self._now() - last).total_seconds()
        return elapsed < self.config.alert_cooldown_seconds

    def _record_cooldown(self, check_name: str) -> None:
        self._cooldown_tracker[check_name] = self._now()

    def send_alert(self, alert: AlertResult) -> None:
        """Send a failed alert through all configured channels."""
        # Always log to JSONL
        self._log_to_jsonl(alert)

        # Console
        level = logging.WARNING if alert.severity == Severity.WARNING else logging.CRITICAL
        logger.log(level, "[%s] %s: %s", alert.severity.value, alert.check_name, alert.message)

        # Telegram (with cooldown)
        if not self._is_cooled_down(alert.check_name):
            sender = self.telegram_sender
            if sender is not None:
                text = (
                    f"LIVENESS {alert.severity.value}\n"
                    f"Check: {alert.check_name}\n"
                    f"{alert.message}"
                )
                try:
                    sender(text)
                except Exception as exc:
                    logger.warning("Telegram send failed: %s", exc)
            self._record_cooldown(alert.check_name)

    def _log_to_jsonl(self, alert: AlertResult) -> None:
        log_path = self.config.alert_log_path
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a") as f:
                f.write(json.dumps(alert.to_dict()) + "\n")
        except OSError as exc:
            logger.warning("Could not write alert log to %s: %s", log_path, exc)

    def process_results(self, results: List[AlertResult]) -> List[AlertResult]:
        """Send alerts for failed checks and return only failures."""
        failures = [r for r in results if not r.passed]
        for alert in failures:
            self.send_alert(alert)
        return failures

    # -- continuous runner -------------------------------------------------

    def run_continuous(self, interval_seconds: Optional[int] = None) -> None:
        """Run all checks on a repeating loop. Blocks forever."""
        interval = interval_seconds or self.config.check_interval_seconds
        logger.info(
            "Execution liveness monitor starting (interval=%ds, fill_timeout=%dm, "
            "max_skip_rate=%.0f%%, pipeline_stale=%dh, pnl_threshold=$%.0f)",
            interval,
            self.config.fill_timeout_minutes,
            self.config.max_skip_rate * 100,
            self.config.pipeline_stale_hours,
            self.config.pnl_drop_threshold,
        )
        while True:
            try:
                results = self.run_all_checks()
                failures = self.process_results(results)
                passed = len(results) - len(failures)
                logger.info(
                    "Liveness sweep: %d/%d passed, %d alerts",
                    passed,
                    len(results),
                    len(failures),
                )
            except Exception as exc:
                logger.error("Liveness sweep error: %s", exc, exc_info=True)
            time.sleep(interval)

    # -- one-shot runner (for systemd timer / cron) ------------------------

    def run_once(self) -> int:
        """Run all checks once, send alerts, return exit code (0=ok, 1=failures)."""
        results = self.run_all_checks()
        failures = self.process_results(results)
        passed = len(results) - len(failures)
        logger.info(
            "Liveness check: %d/%d passed, %d alerts",
            passed,
            len(results),
            len(failures),
        )
        return 0 if not failures else 1


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Execution liveness monitor")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run checks once and exit (for systemd timer / cron)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=None,
        help="Override check interval in seconds (default: 300)",
    )
    parser.add_argument(
        "--db",
        type=str,
        default=None,
        help="Path to jj_trades.db",
    )
    parser.add_argument(
        "--btc5-db",
        type=str,
        default=None,
        help="Path to btc_5min_maker.db",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )

    config = LivenessConfig.from_env()
    if args.db:
        config.db_path = Path(args.db)
    if args.btc5_db:
        config.btc5_db_path = Path(args.btc5_db)

    monitor = LivenessMonitor(config=config)

    if args.once:
        exit_code = monitor.run_once()
        raise SystemExit(exit_code)
    else:
        monitor.run_continuous(interval_seconds=args.interval)


if __name__ == "__main__":
    main()
