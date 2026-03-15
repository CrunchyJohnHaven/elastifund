#!/usr/bin/env python3
"""Cycle heartbeat, daily summary, and service recovery helpers."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sqlite3
import subprocess
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv

load_dotenv()

DEFAULT_HEARTBEAT_FILE = Path(os.environ.get("JJ_HEARTBEAT_FILE", "data/heartbeat.json"))
DEFAULT_MONITOR_STATE_FILE = Path(
    os.environ.get("JJ_HEALTH_MONITOR_STATE_FILE", "data/health_monitor_state.json")
)
DEFAULT_DB_PATH = Path(os.environ.get("JJ_DB_FILE", "data/jj_trades.db"))
DEFAULT_JJ_STATE_FILE = Path(os.environ.get("JJ_STATE_FILE", "jj_state.json"))
DEFAULT_TIMEOUT_SECONDS = int(os.environ.get("JJ_HEARTBEAT_TIMEOUT_SECONDS", "600"))
DEFAULT_RESTART_COOLDOWN_SECONDS = int(
    os.environ.get("JJ_HEALTH_RESTART_COOLDOWN_SECONDS", "900")
)
DEFAULT_SERVICE_NAME = os.environ.get("JJ_HEALTH_SERVICE_NAME", "jj-live.service").strip() or "jj-live.service"
DEFAULT_DAILY_SUMMARY_HOUR_UTC = int(os.environ.get("JJ_DAILY_SUMMARY_HOUR_UTC", "0"))
DEFAULT_DAILY_SUMMARY_MINUTE_UTC = int(os.environ.get("JJ_DAILY_SUMMARY_MINUTE_UTC", "0"))
ERROR_HISTORY_DAYS = 14


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _json_default(payload: dict[str, Any]) -> dict[str, Any]:
    return payload if isinstance(payload, dict) else {}


def _read_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        return dict(default or {})
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return dict(default or {})
    if not isinstance(raw, dict):
        return dict(default or {})
    return raw


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_float(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _truncate_error(message: str, limit: int = 500) -> str:
    text = str(message or "").strip()
    return text[:limit]


def _prune_error_counts(error_counts: dict[str, Any], *, now: datetime) -> dict[str, int]:
    cutoff = (now.date() - timedelta(days=ERROR_HISTORY_DAYS))
    pruned: dict[str, int] = {}
    for key, value in (error_counts or {}).items():
        try:
            bucket_date = date.fromisoformat(str(key))
        except ValueError:
            continue
        if bucket_date < cutoff:
            continue
        pruned[bucket_date.isoformat()] = _coerce_int(value, default=0)
    return pruned


def load_heartbeat(path: Path = DEFAULT_HEARTBEAT_FILE) -> dict[str, Any]:
    payload = _read_json(path, default={})
    payload["error_counts_by_date"] = dict(payload.get("error_counts_by_date") or {})
    return payload


def load_monitor_state(path: Path = DEFAULT_MONITOR_STATE_FILE) -> dict[str, Any]:
    payload = _read_json(path, default={})
    payload.setdefault("last_health_status", "unknown")
    payload.setdefault("last_restart_at", None)
    payload.setdefault("last_daily_summary_for_date", None)
    return payload


class HeartbeatWriter:
    """Persist service liveness and per-day error counts for out-of-process checks."""

    def __init__(self, path: Path = DEFAULT_HEARTBEAT_FILE):
        self.path = Path(path)

    def _load(self) -> dict[str, Any]:
        now = utc_now()
        payload = load_heartbeat(self.path)
        payload["error_counts_by_date"] = _prune_error_counts(
            payload.get("error_counts_by_date", {}),
            now=now,
        )
        return payload

    def _save(self, payload: dict[str, Any]) -> dict[str, Any]:
        _write_json(self.path, payload)
        return payload

    def mark_startup(
        self,
        *,
        profile_name: str,
        runtime_mode: str,
        paper_mode: bool,
        scan_interval_seconds: int,
    ) -> dict[str, Any]:
        now = utc_now()
        now_iso = now.isoformat()
        payload = self._load()
        payload.update(
            {
                "status": "starting",
                "started_at": payload.get("started_at") or now_iso,
                "last_updated_at": now_iso,
                "profile_name": str(profile_name),
                "runtime_mode": str(runtime_mode),
                "paper_mode": bool(paper_mode),
                "scan_interval_seconds": int(scan_interval_seconds),
            }
        )
        return self._save(payload)

    def mark_cycle_started(
        self,
        cycle_number: int,
        *,
        profile_name: str,
        runtime_mode: str,
        paper_mode: bool,
        scan_interval_seconds: int,
    ) -> dict[str, Any]:
        now = utc_now()
        now_iso = now.isoformat()
        payload = self._load()
        payload.update(
            {
                "status": "running",
                "cycle_number": int(cycle_number),
                "last_cycle_started_at": now_iso,
                "last_updated_at": now_iso,
                "profile_name": str(profile_name),
                "runtime_mode": str(runtime_mode),
                "paper_mode": bool(paper_mode),
                "scan_interval_seconds": int(scan_interval_seconds),
            }
        )
        return self._save(payload)

    def mark_cycle_completed(
        self,
        summary: dict[str, Any],
        *,
        profile_name: str,
        runtime_mode: str,
        paper_mode: bool,
        scan_interval_seconds: int,
        total_trades: int,
        trades_today: int,
        open_positions: int,
    ) -> dict[str, Any]:
        now = utc_now()
        now_iso = now.isoformat()
        payload = self._load()
        payload.update(
            {
                "status": str(summary.get("status", "ok") or "ok"),
                "cycle_number": _coerce_int(summary.get("cycle"), _coerce_int(payload.get("cycle_number"), 0)),
                "last_updated_at": now_iso,
                "last_cycle_completed_at": now_iso,
                "profile_name": str(profile_name),
                "runtime_mode": str(runtime_mode),
                "paper_mode": bool(paper_mode),
                "scan_interval_seconds": int(scan_interval_seconds),
                "signals_found": _coerce_int(summary.get("signals"), 0),
                "trades_placed": _coerce_int(summary.get("trades_placed"), 0),
                "open_positions": _coerce_int(summary.get("open_positions"), open_positions),
                "total_trades": int(total_trades),
                "trades_today": int(trades_today),
                "bankroll": _coerce_float(summary.get("bankroll")),
                "elapsed_seconds": _coerce_float(summary.get("elapsed_seconds")),
                "lane_health": _json_default(summary.get("lane_health", {})),
                "last_cycle_summary": {
                    "status": str(summary.get("status", "ok") or "ok"),
                    "cycle": _coerce_int(summary.get("cycle"), 0),
                    "signals": _coerce_int(summary.get("signals"), 0),
                    "trades_placed": _coerce_int(summary.get("trades_placed"), 0),
                    "open_positions": _coerce_int(summary.get("open_positions"), open_positions),
                    "bankroll": _coerce_float(summary.get("bankroll")),
                    "reason": str(summary.get("reason", "") or ""),
                },
            }
        )
        return self._save(payload)

    def mark_cycle_error(
        self,
        message: str,
        *,
        cycle_number: int | None = None,
        profile_name: str | None = None,
        runtime_mode: str | None = None,
        paper_mode: bool | None = None,
        scan_interval_seconds: int | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        now_iso = now.isoformat()
        payload = self._load()
        bucket = now.date().isoformat()
        error_counts = dict(payload.get("error_counts_by_date") or {})
        error_counts[bucket] = _coerce_int(error_counts.get(bucket), 0) + 1
        payload["error_counts_by_date"] = _prune_error_counts(error_counts, now=now)
        payload.update(
            {
                "status": "error",
                "last_updated_at": now_iso,
                "last_error_at": now_iso,
                "last_error": _truncate_error(message),
            }
        )
        if cycle_number is not None:
            payload["cycle_number"] = int(cycle_number)
        if profile_name is not None:
            payload["profile_name"] = str(profile_name)
        if runtime_mode is not None:
            payload["runtime_mode"] = str(runtime_mode)
        if paper_mode is not None:
            payload["paper_mode"] = bool(paper_mode)
        if scan_interval_seconds is not None:
            payload["scan_interval_seconds"] = int(scan_interval_seconds)
        return self._save(payload)


def evaluate_heartbeat(
    heartbeat: dict[str, Any],
    *,
    now: datetime | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    current_time = now or utc_now()
    if not heartbeat:
        return {
            "status": "missing",
            "healthy": False,
            "reason": "heartbeat_missing",
            "timeout_seconds": int(timeout_seconds),
        }

    reference_field = "last_cycle_completed_at"
    reference_value = heartbeat.get(reference_field)
    if not reference_value:
        reference_field = "last_updated_at"
        reference_value = heartbeat.get(reference_field) or heartbeat.get("started_at")

    reference_at = _parse_timestamp(reference_value)
    if reference_at is None:
        return {
            "status": "missing",
            "healthy": False,
            "reason": "heartbeat_unreadable",
            "timeout_seconds": int(timeout_seconds),
        }

    age_seconds = max(0.0, (current_time - reference_at).total_seconds())
    healthy = age_seconds <= int(timeout_seconds)
    return {
        "status": "healthy" if healthy else "stale",
        "healthy": healthy,
        "reason": "ok" if healthy else "stale_cycle",
        "timeout_seconds": int(timeout_seconds),
        "age_seconds": round(age_seconds, 1),
        "reference_at": reference_at.isoformat(),
        "reference_field": reference_field,
        "heartbeat_status": str(heartbeat.get("status", "unknown") or "unknown"),
        "cycle_number": _coerce_int(heartbeat.get("cycle_number"), 0),
        "profile_name": str(heartbeat.get("profile_name", "") or ""),
        "runtime_mode": str(heartbeat.get("runtime_mode", "") or ""),
        "paper_mode": bool(heartbeat.get("paper_mode", False)),
        "last_error_at": heartbeat.get("last_error_at"),
        "last_error": heartbeat.get("last_error"),
    }


def _connect_db(db_path: Path) -> sqlite3.Connection | None:
    if not Path(db_path).exists():
        return None
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _query_row(conn: sqlite3.Connection | None, sql: str, params: tuple[Any, ...]) -> sqlite3.Row | None:
    if conn is None:
        return None
    try:
        return conn.execute(sql, params).fetchone()
    except sqlite3.Error:
        return None


def _state_snapshot(path: Path) -> dict[str, Any]:
    state = _read_json(path, default={})
    open_positions = state.get("open_positions")
    if not isinstance(open_positions, dict):
        open_positions = {}
    return {
        "bankroll": _coerce_float(state.get("bankroll"), 0.0) or 0.0,
        "total_trades": _coerce_int(state.get("total_trades"), 0),
        "open_positions": len(open_positions),
        "trades_today": _coerce_int(state.get("trades_today"), 0),
    }


def build_daily_summary_snapshot(
    *,
    target_date: date,
    db_path: Path = DEFAULT_DB_PATH,
    jj_state_path: Path = DEFAULT_JJ_STATE_FILE,
    heartbeat_path: Path = DEFAULT_HEARTBEAT_FILE,
) -> dict[str, Any]:
    day_prefix = target_date.isoformat()
    like_arg = (f"{day_prefix}%",)
    conn = _connect_db(db_path)
    try:
        cycles_row = _query_row(
            conn,
            """
            SELECT
                COUNT(*) AS cycles_run,
                COALESCE(SUM(signals_found), 0) AS signals_found,
                COALESCE(SUM(trades_placed), 0) AS trades_logged
            FROM cycles
            WHERE timestamp LIKE ?
            """,
            like_arg,
        )
        trades_row = _query_row(
            conn,
            """
            SELECT
                COALESCE(SUM(CASE WHEN paper = 1 THEN 1 ELSE 0 END), 0) AS paper_trades,
                COALESCE(SUM(CASE WHEN paper = 0 THEN 1 ELSE 0 END), 0) AS live_trades
            FROM trades
            WHERE timestamp LIKE ?
            """,
            like_arg,
        )
        resolved_row = _query_row(
            conn,
            """
            SELECT
                COUNT(*) AS resolved_trades,
                COALESCE(SUM(CASE WHEN outcome = 'won' THEN 1 ELSE 0 END), 0) AS wins,
                COALESCE(SUM(CASE WHEN outcome = 'lost' THEN 1 ELSE 0 END), 0) AS losses,
                COALESCE(SUM(pnl), 0) AS pnl
            FROM trades
            WHERE resolved_at LIKE ?
            """,
            like_arg,
        )
    finally:
        if conn is not None:
            conn.close()

    heartbeat = load_heartbeat(heartbeat_path)
    state = _state_snapshot(jj_state_path)
    last_cycle_summary = _json_default(heartbeat.get("last_cycle_summary", {}))

    return {
        "target_date": day_prefix,
        "profile_name": str(heartbeat.get("profile_name", "") or ""),
        "runtime_mode": str(heartbeat.get("runtime_mode", "") or ""),
        "paper_mode": bool(heartbeat.get("paper_mode", False)),
        "cycles_run": _coerce_int(cycles_row["cycles_run"], 0) if cycles_row else 0,
        "signals_found": _coerce_int(cycles_row["signals_found"], 0) if cycles_row else 0,
        "trades_logged": _coerce_int(cycles_row["trades_logged"], 0) if cycles_row else 0,
        "paper_trades": _coerce_int(trades_row["paper_trades"], 0) if trades_row else 0,
        "live_trades": _coerce_int(trades_row["live_trades"], 0) if trades_row else 0,
        "resolved_trades": _coerce_int(resolved_row["resolved_trades"], 0) if resolved_row else 0,
        "wins": _coerce_int(resolved_row["wins"], 0) if resolved_row else 0,
        "losses": _coerce_int(resolved_row["losses"], 0) if resolved_row else 0,
        "daily_pnl": _coerce_float(resolved_row["pnl"], 0.0) if resolved_row else 0.0,
        "error_count": _coerce_int((heartbeat.get("error_counts_by_date") or {}).get(day_prefix), 0),
        "bankroll": state["bankroll"],
        "open_positions": state["open_positions"],
        "total_trades": state["total_trades"],
        "last_cycle_number": _coerce_int(last_cycle_summary.get("cycle"), _coerce_int(heartbeat.get("cycle_number"), 0)),
        "last_cycle_status": str(last_cycle_summary.get("status", heartbeat.get("status", "unknown")) or "unknown"),
        "last_cycle_signals": _coerce_int(last_cycle_summary.get("signals"), 0),
        "last_cycle_trades_placed": _coerce_int(last_cycle_summary.get("trades_placed"), 0),
    }


def format_daily_summary(snapshot: dict[str, Any]) -> str:
    resolved_trades = _coerce_int(snapshot.get("resolved_trades"), 0)
    wins = _coerce_int(snapshot.get("wins"), 0)
    win_rate = f"{wins / resolved_trades:.0%}" if resolved_trades > 0 else "n/a"
    mode = str(snapshot.get("runtime_mode", "unknown") or "unknown")
    profile = str(snapshot.get("profile_name", "") or "unknown")
    paper_mode = "paper" if snapshot.get("paper_mode") else "live"
    return "\n".join(
        [
            f"JJ DAILY SUMMARY - {snapshot.get('target_date')} UTC",
            f"Profile: {profile} | Mode: {mode} | Trading: {paper_mode}",
            (
                f"Cycles: {snapshot.get('cycles_run', 0)} | "
                f"Signals: {snapshot.get('signals_found', 0)} | "
                f"Paper trades: {snapshot.get('paper_trades', 0)} | "
                f"Live trades: {snapshot.get('live_trades', 0)}"
            ),
            (
                f"Resolved: {resolved_trades} | "
                f"Wins: {wins} | "
                f"Losses: {snapshot.get('losses', 0)} | "
                f"Win rate: {win_rate}"
            ),
            (
                f"P&L: ${_coerce_float(snapshot.get('daily_pnl'), 0.0) or 0.0:+.2f} | "
                f"Errors: {snapshot.get('error_count', 0)} | "
                f"Open positions: {snapshot.get('open_positions', 0)}"
            ),
            (
                f"Bankroll: ${_coerce_float(snapshot.get('bankroll'), 0.0) or 0.0:.2f} | "
                f"Last cycle: #{snapshot.get('last_cycle_number', 0)} "
                f"({snapshot.get('last_cycle_status', 'unknown')}, "
                f"signals={snapshot.get('last_cycle_signals', 0)}, "
                f"trades={snapshot.get('last_cycle_trades_placed', 0)})"
            ),
        ]
    )


def build_telegram_sender() -> Callable[[str], bool] | None:
    try:
        try:
            from bot.polymarket_runtime import TelegramBot
        except ImportError:
            from polymarket_runtime import TelegramBot  # type: ignore
    except Exception:
        return None

    try:
        bot = TelegramBot()
    except Exception:
        return None

    if not getattr(bot, "enabled", False):
        return None

    def _send(message: str) -> bool:
        try:
            return bool(bot.send(message, parse_mode=""))
        except Exception:
            return False

    return _send


def restart_service(
    *,
    service_name: str,
    use_sudo: bool = False,
) -> dict[str, Any]:
    prefix = ["sudo"] if use_sudo else []
    restart_cmd = prefix + ["systemctl", "restart", service_name]
    status_cmd = prefix + ["systemctl", "is-active", service_name]
    restart_proc = subprocess.run(restart_cmd, capture_output=True, text=True)
    status_proc = subprocess.run(status_cmd, capture_output=True, text=True)
    active_state = (status_proc.stdout or status_proc.stderr).strip() or "unknown"
    return {
        "ok": restart_proc.returncode == 0 and active_state == "active",
        "restart_command": shlex.join(restart_cmd),
        "status_command": shlex.join(status_cmd),
        "restart_returncode": restart_proc.returncode,
        "status_returncode": status_proc.returncode,
        "active_state": active_state,
        "restart_stdout": (restart_proc.stdout or "").strip(),
        "restart_stderr": (restart_proc.stderr or "").strip(),
        "status_stdout": (status_proc.stdout or "").strip(),
        "status_stderr": (status_proc.stderr or "").strip(),
    }


def _summary_target_date(
    *,
    now: datetime,
    state: dict[str, Any],
    summary_hour_utc: int,
    summary_minute_utc: int,
) -> date | None:
    target = now.date() - timedelta(days=1)
    scheduled_at = datetime.combine(
        target + timedelta(days=1),
        dt_time(hour=summary_hour_utc, minute=summary_minute_utc, tzinfo=timezone.utc),
    )
    if now < scheduled_at:
        return None
    if str(state.get("last_daily_summary_for_date") or "") == target.isoformat():
        return None
    return target


def run_health_check(
    *,
    heartbeat_path: Path = DEFAULT_HEARTBEAT_FILE,
    state_path: Path = DEFAULT_MONITOR_STATE_FILE,
    db_path: Path = DEFAULT_DB_PATH,
    jj_state_path: Path = DEFAULT_JJ_STATE_FILE,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    auto_restart: bool = False,
    service_name: str = DEFAULT_SERVICE_NAME,
    use_sudo_systemctl: bool = False,
    restart_cooldown_seconds: int = DEFAULT_RESTART_COOLDOWN_SECONDS,
    send_daily_summary: bool = False,
    daily_summary_hour_utc: int = DEFAULT_DAILY_SUMMARY_HOUR_UTC,
    daily_summary_minute_utc: int = DEFAULT_DAILY_SUMMARY_MINUTE_UTC,
    now: datetime | None = None,
    send_message: Callable[[str], bool] | None = None,
    restart_func: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    current_time = now or utc_now()
    heartbeat = load_heartbeat(heartbeat_path)
    monitor_state = load_monitor_state(state_path)
    evaluation = evaluate_heartbeat(
        heartbeat,
        now=current_time,
        timeout_seconds=timeout_seconds,
    )
    previous_status = str(monitor_state.get("last_health_status", "unknown") or "unknown")
    sender = send_message if send_message is not None else build_telegram_sender()
    restart_impl = restart_func or restart_service
    actions: list[str] = []
    restart_result: dict[str, Any] | None = None

    def _notify(message: str) -> None:
        if sender is None:
            return
        sender(message)

    if evaluation["status"] != "healthy":
        if previous_status != evaluation["status"]:
            last_error = evaluation.get("last_error")
            error_suffix = f"\nLast error: {last_error}" if last_error else ""
            _notify(
                "JJ HEALTH ALERT\n"
                f"Status: {evaluation['status']}\n"
                f"Reason: {evaluation['reason']}\n"
                f"Age: {evaluation.get('age_seconds', 'n/a')}s\n"
                f"Cycle: {evaluation.get('cycle_number', 0)}\n"
                f"Profile: {evaluation.get('profile_name', 'unknown')} | "
                f"Mode: {evaluation.get('runtime_mode', 'unknown')}"
                f"{error_suffix}"
            )
            actions.append("health_alert_sent")

        last_restart_at = _parse_timestamp(monitor_state.get("last_restart_at"))
        cooldown_active = (
            last_restart_at is not None
            and (current_time - last_restart_at).total_seconds() < int(restart_cooldown_seconds)
        )
        if auto_restart and service_name and not cooldown_active:
            restart_result = restart_impl(
                service_name=service_name,
                use_sudo=use_sudo_systemctl,
            )
            monitor_state["last_restart_at"] = current_time.isoformat()
            monitor_state["last_restart_result"] = restart_result
            actions.append("service_restart_attempted")
            _notify(
                "JJ HEALTH ACTION\n"
                f"Restart attempted for {service_name}\n"
                f"Result: {'ok' if restart_result.get('ok') else 'failed'}\n"
                f"Active state: {restart_result.get('active_state', 'unknown')}"
            )
        elif auto_restart and cooldown_active:
            actions.append("restart_cooldown_active")
    elif previous_status != "healthy" and previous_status != "unknown":
        _notify(
            "JJ HEALTH RECOVERY\n"
            f"Cycle: {evaluation.get('cycle_number', 0)}\n"
            f"Age: {evaluation.get('age_seconds', 'n/a')}s\n"
            f"Profile: {evaluation.get('profile_name', 'unknown')} | "
            f"Mode: {evaluation.get('runtime_mode', 'unknown')}"
        )
        actions.append("health_recovery_sent")

    summary_snapshot: dict[str, Any] | None = None
    target_date = None
    if send_daily_summary:
        target_date = _summary_target_date(
            now=current_time,
            state=monitor_state,
            summary_hour_utc=daily_summary_hour_utc,
            summary_minute_utc=daily_summary_minute_utc,
        )
        if target_date is not None:
            summary_snapshot = build_daily_summary_snapshot(
                target_date=target_date,
                db_path=db_path,
                jj_state_path=jj_state_path,
                heartbeat_path=heartbeat_path,
            )
            _notify(format_daily_summary(summary_snapshot))
            monitor_state["last_daily_summary_for_date"] = target_date.isoformat()
            actions.append("daily_summary_sent")

    monitor_state["last_health_status"] = evaluation["status"]
    monitor_state["last_checked_at"] = current_time.isoformat()
    _write_json(state_path, monitor_state)

    return {
        "checked_at": current_time.isoformat(),
        "heartbeat_path": str(heartbeat_path),
        "state_path": str(state_path),
        "status": evaluation["status"],
        "evaluation": evaluation,
        "actions": actions,
        "restart_result": restart_result,
        "daily_summary": summary_snapshot,
        "daily_summary_target_date": target_date.isoformat() if target_date is not None else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="JJ heartbeat health monitor")
    parser.add_argument("--heartbeat-file", default=str(DEFAULT_HEARTBEAT_FILE))
    parser.add_argument("--state-file", default=str(DEFAULT_MONITOR_STATE_FILE))
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--jj-state-file", default=str(DEFAULT_JJ_STATE_FILE))
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--auto-restart", action="store_true")
    parser.add_argument("--service-name", default=DEFAULT_SERVICE_NAME)
    parser.add_argument("--sudo-systemctl", action="store_true")
    parser.add_argument(
        "--restart-cooldown-seconds",
        type=int,
        default=DEFAULT_RESTART_COOLDOWN_SECONDS,
    )
    parser.add_argument("--send-daily-summary", action="store_true")
    parser.add_argument(
        "--daily-summary-hour-utc",
        type=int,
        default=DEFAULT_DAILY_SUMMARY_HOUR_UTC,
    )
    parser.add_argument(
        "--daily-summary-minute-utc",
        type=int,
        default=DEFAULT_DAILY_SUMMARY_MINUTE_UTC,
    )
    args = parser.parse_args()

    result = run_health_check(
        heartbeat_path=Path(args.heartbeat_file),
        state_path=Path(args.state_file),
        db_path=Path(args.db_path),
        jj_state_path=Path(args.jj_state_file),
        timeout_seconds=args.timeout_seconds,
        auto_restart=args.auto_restart,
        service_name=args.service_name,
        use_sudo_systemctl=args.sudo_systemctl,
        restart_cooldown_seconds=args.restart_cooldown_seconds,
        send_daily_summary=args.send_daily_summary,
        daily_summary_hour_utc=args.daily_summary_hour_utc,
        daily_summary_minute_utc=args.daily_summary_minute_utc,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
