#!/usr/bin/env python3
"""Automated capital stage-gate updates for multi-asset maker lanes."""

from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DEFAULT_STATE_ENV_PATH = Path("state/btc5_capital_stage.env")
DEFAULT_STAGE_GATE_LOG_PATH = Path("data/stage_gate_log.json")
DEFAULT_DATA_DIR = Path("data")
DEFAULT_LOOKBACK_HOURS = 0.0
DEFAULT_ASSETS = ("btc", "eth", "sol", "bnb", "doge", "xrp")
MAX_LOG_EVENTS = 500


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return int(default)
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _parse_bool_int(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "won"}:
        return 1
    if text in {"0", "false", "no", "lost"}:
        return 0
    try:
        numeric = int(float(text))
    except (TypeError, ValueError):
        return None
    if numeric not in {0, 1}:
        return None
    return numeric


def _parse_iso_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_env_kv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        values[key] = value.strip().strip('"').strip("'")
    return values


def _update_env_file(path: Path, updates: dict[str, str]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    out_lines: list[str] = []
    replaced: set[str] = set()
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in raw_line:
            out_lines.append(raw_line)
            continue
        key, _ = raw_line.split("=", 1)
        normalized_key = key.strip()
        if normalized_key in updates:
            out_lines.append(f"{normalized_key}={updates[normalized_key]}")
            replaced.add(normalized_key)
        else:
            out_lines.append(raw_line)
    for key, value in updates.items():
        if key in replaced:
            continue
        out_lines.append(f"{key}={value}")
    if not out_lines:
        out_lines = [f"{key}={value}" for key, value in updates.items()]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")


def _infer_asset_name(db_path: Path) -> str:
    stem = db_path.stem.lower()
    for token in DEFAULT_ASSETS:
        if token in stem:
            return token
    return stem


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    try:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    except sqlite3.Error:
        return set()
    return {str(row[1]) for row in rows}


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
    except sqlite3.Error:
        return False
    return row is not None


@dataclass(frozen=True)
class FillRecord:
    asset: str
    db_path: str
    won: int
    pnl_usd: float
    sort_key: float
    created_at: str | None


@dataclass(frozen=True)
class StageGateMetrics:
    fills: int
    wins: int
    losses: int
    win_rate: float
    total_pnl_usd: float
    consecutive_losses: int
    by_asset: dict[str, dict[str, Any]]
    db_paths_scanned: list[str]
    lookback_hours: float


@dataclass(frozen=True)
class StageGateDecision:
    action: str
    reason: str
    current_max_trade_usd: float
    target_max_trade_usd: float
    applied_max_trade_usd: float
    bankroll_usd: float
    risk_fraction: float
    risk_cap_usd: float
    balance_usd: float
    halted: bool
    safeguards: list[str]


def _row_sort_key(row: sqlite3.Row, columns: set[str], fallback: int) -> float:
    if "decision_ts" in columns:
        decision_ts = _safe_float(row["decision_ts"], 0.0)
        if decision_ts > 0:
            return decision_ts
    if "window_start_ts" in columns:
        window_start_ts = _safe_float(row["window_start_ts"], 0.0)
        if window_start_ts > 0:
            return window_start_ts
    if "created_at" in columns:
        dt = _parse_iso_datetime(row["created_at"])
        if dt is not None:
            return dt.timestamp()
    return float(fallback)


def _row_created_at_text(row: sqlite3.Row, columns: set[str]) -> str | None:
    if "created_at" not in columns:
        return None
    text = str(row["created_at"] or "").strip()
    return text or None


def _load_fills_from_db(db_path: Path, *, lookback_hours: float) -> tuple[list[FillRecord], list[str]]:
    diagnostics: list[str] = []
    if not db_path.exists():
        diagnostics.append(f"missing_db:{db_path}")
        return [], diagnostics
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        if not _table_exists(conn, "window_trades"):
            diagnostics.append(f"missing_table:{db_path}:window_trades")
            return [], diagnostics
        columns = _table_columns(conn, "window_trades")
        if "won" not in columns or "pnl_usd" not in columns:
            diagnostics.append(f"missing_columns:{db_path}:won_or_pnl_usd")
            return [], diagnostics

        select_columns = ["won", "pnl_usd"]
        for optional in ("decision_ts", "window_start_ts", "created_at", "order_status", "filled"):
            if optional in columns:
                select_columns.append(optional)
        where_predicates: list[str] = []
        if "order_status" in columns:
            where_predicates.append("LOWER(order_status) = 'live_filled'")
        if "filled" in columns:
            where_predicates.append("filled = 1")
        if not where_predicates:
            where_predicates.append("won IS NOT NULL")
        where_sql = "(" + " OR ".join(where_predicates) + ")"
        query = f"SELECT {', '.join(select_columns)} FROM window_trades WHERE {where_sql}"
        rows = conn.execute(query).fetchall()
    except sqlite3.Error as exc:
        diagnostics.append(f"sqlite_error:{db_path}:{exc}")
        return [], diagnostics
    finally:
        conn.close()

    now_ts = _utc_now().timestamp()
    lookback_cutoff = None
    if lookback_hours > 0:
        lookback_cutoff = now_ts - max(0.0, float(lookback_hours)) * 3600.0

    fills: list[FillRecord] = []
    asset = _infer_asset_name(db_path)
    for index, row in enumerate(rows):
        won_value = _parse_bool_int(row["won"])
        if won_value is None:
            continue
        pnl = _safe_float(row["pnl_usd"], 0.0)
        sort_key = _row_sort_key(row, columns, fallback=index + 1)
        if lookback_cutoff is not None and sort_key < lookback_cutoff:
            continue
        fills.append(
            FillRecord(
                asset=asset,
                db_path=str(db_path),
                won=won_value,
                pnl_usd=pnl,
                sort_key=sort_key,
                created_at=_row_created_at_text(row, columns),
            )
        )
    return fills, diagnostics


def aggregate_stage_gate_metrics(
    db_paths: list[Path],
    *,
    lookback_hours: float = DEFAULT_LOOKBACK_HOURS,
) -> tuple[StageGateMetrics, list[str]]:
    all_fills: list[FillRecord] = []
    diagnostics: list[str] = []
    scanned: list[str] = []
    for db_path in db_paths:
        scanned.append(str(db_path))
        fills, db_diagnostics = _load_fills_from_db(db_path, lookback_hours=lookback_hours)
        diagnostics.extend(db_diagnostics)
        all_fills.extend(fills)

    wins = sum(1 for record in all_fills if record.won == 1)
    losses = sum(1 for record in all_fills if record.won == 0)
    fills = len(all_fills)
    win_rate = (wins / fills) if fills else 0.0
    total_pnl = sum(record.pnl_usd for record in all_fills)

    per_asset: dict[str, dict[str, Any]] = {}
    for record in all_fills:
        bucket = per_asset.setdefault(record.asset, {"fills": 0, "wins": 0, "losses": 0, "pnl_usd": 0.0})
        bucket["fills"] += 1
        bucket["wins"] += 1 if record.won == 1 else 0
        bucket["losses"] += 1 if record.won == 0 else 0
        bucket["pnl_usd"] = round(float(bucket["pnl_usd"]) + float(record.pnl_usd), 4)
    for bucket in per_asset.values():
        bucket["win_rate"] = round((bucket["wins"] / bucket["fills"]) if bucket["fills"] else 0.0, 6)

    sorted_recent = sorted(all_fills, key=lambda item: item.sort_key, reverse=True)
    consecutive_losses = 0
    for record in sorted_recent:
        if record.won == 0:
            consecutive_losses += 1
            continue
        break

    metrics = StageGateMetrics(
        fills=fills,
        wins=wins,
        losses=losses,
        win_rate=win_rate,
        total_pnl_usd=round(total_pnl, 4),
        consecutive_losses=consecutive_losses,
        by_asset=dict(sorted(per_asset.items())),
        db_paths_scanned=scanned,
        lookback_hours=float(lookback_hours),
    )
    return metrics, diagnostics


def _evaluate_target_from_rules(metrics: StageGateMetrics, current_max_trade_usd: float) -> tuple[float, str, str, bool]:
    if metrics.consecutive_losses >= 5:
        return max(0.0, current_max_trade_usd * 0.5), "scale_down", "five_consecutive_losses", False
    if metrics.fills >= 40 and metrics.win_rate >= 0.65:
        return 1000.0, "scale_up", "fills_gte_40_and_wr_gte_65pct", False
    if metrics.fills >= 20 and metrics.win_rate >= 0.60 and metrics.total_pnl_usd > 0:
        return 750.0, "scale_up", "fills_gte_20_wr_gte_60pct_and_positive_pnl", False
    return current_max_trade_usd, "hold", "insufficient_stage_gate_edge", False


def evaluate_stage_gate(
    *,
    metrics: StageGateMetrics,
    bankroll_usd: float,
    risk_fraction: float,
    current_max_trade_usd: float,
    balance_usd: float,
) -> StageGateDecision:
    clamped_bankroll = max(0.0, float(bankroll_usd))
    clamped_risk_fraction = max(0.0, float(risk_fraction))
    current_max = max(0.0, float(current_max_trade_usd))
    risk_cap = max(0.0, clamped_bankroll * clamped_risk_fraction)
    safeguards: list[str] = []

    if clamped_bankroll > 0 and balance_usd < clamped_bankroll * 0.5:
        action = "halt"
        reason = "balance_below_50pct_of_bankroll"
        target = 0.0
        halted = True
    else:
        target, action, reason, halted = _evaluate_target_from_rules(metrics, current_max_trade_usd=current_max)

    if target > risk_cap:
        target = risk_cap
        safeguards.append("capped_by_bankroll_times_risk_fraction")
    if current_max > 0 and target > (current_max * 2.0):
        target = current_max * 2.0
        safeguards.append("capped_by_max_2x_step")

    applied = round(max(0.0, target), 2)
    return StageGateDecision(
        action=action,
        reason=reason,
        current_max_trade_usd=round(current_max, 2),
        target_max_trade_usd=round(max(0.0, target), 2),
        applied_max_trade_usd=applied,
        bankroll_usd=round(clamped_bankroll, 4),
        risk_fraction=round(clamped_risk_fraction, 6),
        risk_cap_usd=round(risk_cap, 4),
        balance_usd=round(float(balance_usd), 4),
        halted=bool(halted),
        safeguards=safeguards,
    )


def _default_db_paths(data_dir: Path) -> list[Path]:
    return [data_dir / f"{asset}_5min_maker.db" for asset in DEFAULT_ASSETS]


def _resolve_db_paths(args: argparse.Namespace) -> list[Path]:
    configured = [Path(item).expanduser() for item in list(args.db_path or []) if str(item).strip()]
    if configured:
        return configured
    return _default_db_paths(Path(args.data_dir).expanduser())


def _choose_balance(env_values: dict[str, str], *, bankroll_usd: float, fallback_pnl_usd: float) -> float:
    for key in ("BTC5_BALANCE_USD", "BALANCE_USD", "PORTFOLIO_BALANCE_USD"):
        if key in env_values:
            return max(0.0, _safe_float(env_values.get(key), bankroll_usd))
    return max(0.0, bankroll_usd + float(fallback_pnl_usd))


def run_stage_gate(
    *,
    state_env_path: Path,
    db_paths: list[Path],
    log_path: Path,
    lookback_hours: float,
    bankroll_override: float | None = None,
    risk_fraction_override: float | None = None,
    balance_override: float | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    env_values = _read_env_kv(state_env_path)
    bankroll = (
        float(bankroll_override)
        if bankroll_override is not None
        else _safe_float(env_values.get("BTC5_BANKROLL_USD"), 0.0)
    )
    risk_fraction = (
        float(risk_fraction_override)
        if risk_fraction_override is not None
        else _safe_float(env_values.get("BTC5_RISK_FRACTION"), 0.0)
    )
    current_max = _safe_float(
        env_values.get("BTC5_STAGE1_MAX_TRADE_USD", env_values.get("BTC5_MAX_TRADE_USD")),
        0.0,
    )

    metrics, diagnostics = aggregate_stage_gate_metrics(db_paths, lookback_hours=lookback_hours)
    derived_balance = _choose_balance(env_values, bankroll_usd=bankroll, fallback_pnl_usd=metrics.total_pnl_usd)
    balance = float(balance_override) if balance_override is not None else derived_balance

    decision = evaluate_stage_gate(
        metrics=metrics,
        bankroll_usd=bankroll,
        risk_fraction=risk_fraction,
        current_max_trade_usd=current_max,
        balance_usd=balance,
    )
    now_iso = _utc_now().isoformat()

    updates = {
        "BTC5_MAX_TRADE_USD": f"{decision.applied_max_trade_usd:.2f}",
        "BTC5_STAGE1_MAX_TRADE_USD": f"{decision.applied_max_trade_usd:.2f}",
        "BTC5_AUTO_STAGE_GATE_LAST_AT": now_iso,
        "BTC5_AUTO_STAGE_GATE_ACTION": decision.action,
        "BTC5_AUTO_STAGE_GATE_REASON": decision.reason,
        "BTC5_AUTO_STAGE_GATE_HALTED": "true" if decision.halted else "false",
    }

    env_values_after = dict(env_values)
    env_values_after.update(updates)

    event = {
        "run_at": now_iso,
        "dry_run": bool(dry_run),
        "state_env_path": str(state_env_path),
        "db_paths": [str(path) for path in db_paths],
        "diagnostics": diagnostics,
        "metrics": {
            "fills": metrics.fills,
            "wins": metrics.wins,
            "losses": metrics.losses,
            "win_rate": round(metrics.win_rate, 6),
            "total_pnl_usd": metrics.total_pnl_usd,
            "consecutive_losses": metrics.consecutive_losses,
            "lookback_hours": metrics.lookback_hours,
            "by_asset": metrics.by_asset,
        },
        "decision": {
            "action": decision.action,
            "reason": decision.reason,
            "current_max_trade_usd": decision.current_max_trade_usd,
            "target_max_trade_usd": decision.target_max_trade_usd,
            "applied_max_trade_usd": decision.applied_max_trade_usd,
            "bankroll_usd": decision.bankroll_usd,
            "risk_fraction": decision.risk_fraction,
            "risk_cap_usd": decision.risk_cap_usd,
            "balance_usd": decision.balance_usd,
            "halted": decision.halted,
            "safeguards": decision.safeguards,
        },
        "env_updates": updates,
    }

    if not dry_run:
        _update_env_file(state_env_path, updates)

    log_payload = _load_json(log_path)
    events = list(log_payload.get("events") or [])
    events.append(event)
    if len(events) > MAX_LOG_EVENTS:
        events = events[-MAX_LOG_EVENTS:]
    result = {
        "generated_at": now_iso,
        "latest": event,
        "events": events,
        "event_count": len(events),
    }
    if not dry_run:
        _write_json(log_path, result)

    return {
        "generated_at": now_iso,
        "dry_run": bool(dry_run),
        "decision": event["decision"],
        "metrics": event["metrics"],
        "diagnostics": diagnostics,
        "state_env_path": str(state_env_path),
        "log_path": str(log_path),
        "env_updates": updates,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Automated multi-asset capital stage gate")
    parser.add_argument("--state-env", default=str(DEFAULT_STATE_ENV_PATH))
    parser.add_argument("--log-path", default=str(DEFAULT_STAGE_GATE_LOG_PATH))
    parser.add_argument(
        "--db-path",
        action="append",
        default=[],
        help="Repeatable DB path. Defaults to six asset DBs in --data-dir.",
    )
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--lookback-hours", type=float, default=DEFAULT_LOOKBACK_HOURS)
    parser.add_argument("--bankroll", type=float, default=None)
    parser.add_argument("--risk-fraction", type=float, default=None)
    parser.add_argument("--balance-usd", type=float, default=None)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    result = run_stage_gate(
        state_env_path=Path(args.state_env).expanduser(),
        db_paths=_resolve_db_paths(args),
        log_path=Path(args.log_path).expanduser(),
        lookback_hours=max(0.0, float(args.lookback_hours)),
        bankroll_override=args.bankroll,
        risk_fraction_override=args.risk_fraction,
        balance_override=args.balance_usd,
        dry_run=bool(args.dry_run),
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
