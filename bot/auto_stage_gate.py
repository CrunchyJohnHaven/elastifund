#!/usr/bin/env python3
"""Automatic stage-gate controls for 5-minute maker sleeves.

DISPATCH_110 Bot 4:
- Read fills from all 6 asset DBs.
- Compute aggregate fills / WR / consecutive losses / cumulative PnL.
- Promote BTC stage sizing when aggregate thresholds are met.
- De-risk per-asset sizing after 5 consecutive losses.
- Halt trading when CLOB balance drops below 50% of configured bankroll.
- Persist every decision to data/stage_gate_log.json.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional in tests.
    load_dotenv = None


ASSET_ORDER: tuple[str, ...] = ("btc", "eth", "sol", "bnb", "doge", "xrp")

DEFAULT_ASSET_DB_PATHS: dict[str, Path] = {
    "btc": Path("data/btc_5min_maker.db"),
    "eth": Path("data/eth_5min_maker.db"),
    "sol": Path("data/sol_5min_maker.db"),
    "bnb": Path("data/bnb_5min_maker.db"),
    "doge": Path("data/doge_5min_maker.db"),
    "xrp": Path("data/xrp_5min_maker.db"),
}

DEFAULT_ASSET_ENV_PATHS: dict[str, Path] = {
    "btc": Path("config/btc5_strategy.env"),
    "eth": Path("config/eth5_strategy.env"),
    "sol": Path("config/sol5_strategy.env"),
    "bnb": Path("config/bnb5_strategy.env"),
    "doge": Path("config/doge5_strategy.env"),
    "xrp": Path("config/xrp5_strategy.env"),
}

DEFAULT_STAGE_ENV_PATH = Path("state/btc5_capital_stage.env")
DEFAULT_MULTI_ASSET_CONFIG_PATH = Path("config/multi_asset_slugs.json")
DEFAULT_BALANCE_JSON_PATH = Path("config/remote_cycle_status.json")
DEFAULT_STAGE_GATE_LOG_PATH = Path("data/stage_gate_log.json")

STAGE1_MAX_TRADE_KEY = "BTC5_STAGE1_MAX_TRADE_USD"
GENERIC_MAX_TRADE_KEY = "BTC5_MAX_TRADE_USD"
DAILY_LOSS_LIMIT_KEY = "BTC5_DAILY_LOSS_LIMIT_USD"
BANKROLL_KEY = "BTC5_BANKROLL_USD"

HUMAN_CONFIRMATION_KEYS: tuple[str, ...] = (
    "BTC5_HUMAN_CONFIRMED_MAX_TRADE_ABOVE_500",
    "BTC5_ALLOW_MAX_TRADE_ABOVE_500",
)

MAX_TRADE_WITHOUT_CONFIRMATION = 500.0


def _iso_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _is_truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "y"}


def _format_env_float(value: float) -> str:
    rounded = round(float(value), 6)
    return f"{rounded:.6f}".rstrip("0").rstrip(".")


def _parse_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        values[key] = value.strip()
    return values


def _upsert_env_values(path: Path, updates: dict[str, str], *, header_comment: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    original_lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    out_lines: list[str] = []
    seen: set[str] = set()

    if not original_lines and header_comment:
        out_lines.append(f"# {header_comment}")
        out_lines.append(f"# generated_at={_iso_utc_now()}")

    for raw_line in original_lines:
        if "=" not in raw_line or raw_line.lstrip().startswith("#"):
            out_lines.append(raw_line)
            continue
        key, _value = raw_line.split("=", 1)
        key = key.strip()
        if key in updates:
            out_lines.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            out_lines.append(raw_line)

    for key in sorted(updates):
        if key not in seen:
            out_lines.append(f"{key}={updates[key]}")

    path.write_text("\n".join(out_lines).rstrip() + "\n", encoding="utf-8")


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parse_key_value_paths(values: list[str] | None, *, arg_name: str) -> dict[str, Path]:
    parsed: dict[str, Path] = {}
    for raw in values or []:
        if "=" not in raw:
            raise ValueError(f"{arg_name} entry must be asset=path, got: {raw!r}")
        asset, path = raw.split("=", 1)
        asset = asset.strip().lower()
        if not asset:
            raise ValueError(f"{arg_name} entry has empty asset: {raw!r}")
        parsed[asset] = Path(path.strip())
    return parsed


def _merge_path_overrides(defaults: dict[str, Path], overrides: dict[str, Path] | None) -> dict[str, Path]:
    merged = dict(defaults)
    for asset, path in (overrides or {}).items():
        merged[asset.lower()] = path
    return merged


def _load_paths_from_multi_asset_config(config_path: Path) -> tuple[dict[str, Path], dict[str, Path]]:
    db_paths = dict(DEFAULT_ASSET_DB_PATHS)
    env_paths = dict(DEFAULT_ASSET_ENV_PATHS)
    payload = _load_json(config_path, default={})
    if not isinstance(payload, dict):
        return db_paths, env_paths
    assets = payload.get("assets")
    if not isinstance(assets, dict):
        return db_paths, env_paths

    for _symbol, raw_meta in assets.items():
        if not isinstance(raw_meta, dict):
            continue
        asset = str(raw_meta.get("asset_slug_prefix") or "").strip().lower()
        if asset not in ASSET_ORDER:
            continue
        db_raw = str(raw_meta.get("db") or "").strip()
        env_raw = str(raw_meta.get("strategy_env") or "").strip()
        if db_raw:
            db_paths[asset] = Path(db_raw)
        if env_raw:
            env_paths[asset] = Path(env_raw)
    return db_paths, env_paths


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
            (table_name,),
        ).fetchone()
    except sqlite3.Error:
        return False
    return row is not None


def _coerce_won(won_value: Any, *, pnl_usd: float) -> int:
    if isinstance(won_value, bool):
        return 1 if won_value else 0
    if isinstance(won_value, (int, float)):
        return 1 if float(won_value) > 0 else 0
    text = str(won_value or "").strip().lower()
    if text in {"won", "win", "true", "t", "yes", "y", "1"}:
        return 1
    if text in {"lost", "lose", "false", "f", "no", "n", "0"}:
        return 0
    return 1 if pnl_usd > 0.0 else 0


def _read_asset_fill_metrics(asset: str, db_path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "asset": asset,
        "db_path": str(db_path),
        "db_exists": db_path.exists(),
        "status": "ok",
        "query_error": None,
        "fills": 0,
        "wins": 0,
        "losses": 0,
        "win_rate": None,
        "pnl_usd": 0.0,
        "consecutive_losses_current": 0,
        "consecutive_losses_max": 0,
        "latest_fill_ts": None,
        "events": [],
    }
    if not db_path.exists():
        result["status"] = "db_missing"
        return result

    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        if not _table_exists(conn, "window_trades"):
            result["status"] = "missing_window_trades_table"
            return result

        rows = conn.execute(
            """
            SELECT
                COALESCE(CAST(decision_ts AS INTEGER), 0) AS decision_ts,
                rowid,
                CAST(COALESCE(pnl_usd, 0) AS REAL) AS pnl_usd,
                won
            FROM window_trades
            WHERE LOWER(COALESCE(order_status, '')) LIKE '%filled%'
               OR LOWER(COALESCE(order_status, '')) = 'live_partial_fill_cancelled'
            ORDER BY COALESCE(CAST(decision_ts AS INTEGER), 0) ASC, rowid ASC
            """
        ).fetchall()
    except sqlite3.Error as exc:
        result["status"] = "query_failed"
        result["query_error"] = str(exc)
        return result
    finally:
        if conn is not None:
            conn.close()

    running_loss_streak = 0
    max_loss_streak = 0
    wins = 0
    pnl_total = 0.0
    events: list[dict[str, Any]] = []
    latest_fill_ts: int | None = None

    for row in rows:
        decision_ts = _safe_int(row["decision_ts"], default=0)
        rowid = _safe_int(row["rowid"], default=0)
        pnl_usd = float(_safe_float(row["pnl_usd"], default=0.0) or 0.0)
        won = _coerce_won(row["won"], pnl_usd=pnl_usd)

        if won > 0:
            wins += 1
            running_loss_streak = 0
        else:
            running_loss_streak += 1
            max_loss_streak = max(max_loss_streak, running_loss_streak)

        pnl_total += pnl_usd
        latest_fill_ts = max(latest_fill_ts or decision_ts, decision_ts)
        events.append(
            {
                "asset": asset,
                "decision_ts": decision_ts,
                "rowid": rowid,
                "won": won,
                "pnl_usd": pnl_usd,
            }
        )

    fills = len(rows)
    losses = fills - wins
    result.update(
        {
            "fills": fills,
            "wins": wins,
            "losses": losses,
            "win_rate": round((wins / fills), 6) if fills > 0 else None,
            "pnl_usd": round(pnl_total, 6),
            "consecutive_losses_current": running_loss_streak,
            "consecutive_losses_max": max_loss_streak,
            "latest_fill_ts": latest_fill_ts,
            "events": events,
        }
    )
    return result


def _build_aggregate_metrics(per_asset: list[dict[str, Any]]) -> dict[str, Any]:
    total_fills = sum(int(row.get("fills") or 0) for row in per_asset)
    total_wins = sum(int(row.get("wins") or 0) for row in per_asset)
    total_losses = sum(int(row.get("losses") or 0) for row in per_asset)
    cumulative_pnl = sum(float(row.get("pnl_usd") or 0.0) for row in per_asset)

    all_events: list[dict[str, Any]] = []
    for row in per_asset:
        for event in list(row.get("events") or []):
            if isinstance(event, dict):
                all_events.append(event)
    all_events.sort(key=lambda item: (_safe_int(item.get("decision_ts"), 0), _safe_int(item.get("rowid"), 0), str(item.get("asset") or "")))

    running_losses = 0
    max_losses = 0
    for event in all_events:
        if int(event.get("won") or 0) > 0:
            running_losses = 0
        else:
            running_losses += 1
            max_losses = max(max_losses, running_losses)

    return {
        "total_fills": total_fills,
        "wins": total_wins,
        "losses": total_losses,
        "win_rate": round((total_wins / total_fills), 6) if total_fills > 0 else None,
        "consecutive_losses_current": running_losses,
        "consecutive_losses_max": max_losses,
        "cumulative_pnl_usd": round(cumulative_pnl, 6),
    }


def _should_allow_above_500(env_values: dict[str, str]) -> tuple[bool, str | None]:
    for key in HUMAN_CONFIRMATION_KEYS:
        if _is_truthy(env_values.get(key)):
            return True, key
    return False, None


def _enforce_max_trade_cap(
    *,
    requested_value: float,
    env_values: dict[str, str],
) -> tuple[float, bool, str | None]:
    requested = float(requested_value)
    if requested <= MAX_TRADE_WITHOUT_CONFIRMATION:
        return requested, False, None
    allowed, confirmation_key = _should_allow_above_500(env_values)
    if allowed:
        return requested, False, confirmation_key
    return MAX_TRADE_WITHOUT_CONFIRMATION, True, None


def _stage_target_from_metrics(aggregate: dict[str, Any]) -> tuple[float | None, str]:
    total_fills = int(aggregate.get("total_fills") or 0)
    win_rate = float(aggregate.get("win_rate") or 0.0)
    pnl_usd = float(aggregate.get("cumulative_pnl_usd") or 0.0)

    if total_fills >= 40 and win_rate >= 0.65:
        return 1000.0, "fills>=40_and_wr>=0.65"
    if total_fills >= 20 and win_rate >= 0.60 and pnl_usd > 0.0:
        return 750.0, "fills>=20_and_wr>=0.60_and_pnl>0"
    return None, "no_threshold_met"


def _append_log_entry(log_path: Path, entry: dict[str, Any], *, max_entries: int = 2000) -> None:
    existing = _load_json(log_path, default=[])
    if not isinstance(existing, list):
        existing = []
    existing.append(entry)
    if len(existing) > max_entries:
        existing = existing[-max_entries:]
    _write_json(log_path, existing)


def _already_scaled_for_latest_fill(log_path: Path, *, asset: str, latest_fill_ts: int) -> bool:
    existing = _load_json(log_path, default=[])
    if not isinstance(existing, list):
        return False
    for run in reversed(existing):
        if not isinstance(run, dict):
            continue
        for action in list(run.get("actions") or []):
            if not isinstance(action, dict):
                continue
            if action.get("type") != "asset_loss_scale_down":
                continue
            if str(action.get("asset") or "").lower() != asset.lower():
                continue
            if int(action.get("latest_fill_ts") or 0) != int(latest_fill_ts):
                continue
            if bool(action.get("applied")):
                return True
    return False


def _resolve_relative(path: Path, *, cwd: Path) -> Path:
    return path if path.is_absolute() else (cwd / path)


def _extract_clob_balance(balance_json_path: Path) -> tuple[float | None, str]:
    env_override = _safe_float(os.environ.get("AUTO_STAGE_GATE_CLOB_BALANCE_USD"))
    if env_override is not None:
        return float(env_override), "env:AUTO_STAGE_GATE_CLOB_BALANCE_USD"

    payload = _load_json(balance_json_path, default={})
    if not isinstance(payload, dict):
        return None, "missing"

    polymarket_wallet = payload.get("polymarket_wallet")
    if isinstance(polymarket_wallet, dict):
        for key in ("free_collateral_usd", "wallet_balance_usd", "total_wallet_value_usd", "wallet_value_usd"):
            value = _safe_float(polymarket_wallet.get(key))
            if value is not None:
                return float(value), f"json:polymarket_wallet.{key}"

    portfolio = payload.get("portfolio")
    if isinstance(portfolio, dict):
        for key in ("free_collateral_usd", "wallet_value_usd", "total_wallet_value_usd"):
            value = _safe_float(portfolio.get(key))
            if value is not None:
                return float(value), f"json:portfolio.{key}"

    for key in ("free_collateral_usd", "wallet_value_usd", "total_wallet_value_usd", "wallet_balance_usd"):
        value = _safe_float(payload.get(key))
        if value is not None:
            return float(value), f"json:{key}"

    capital_sources = payload.get("capital_sources")
    if isinstance(capital_sources, list):
        for row in capital_sources:
            if not isinstance(row, dict):
                continue
            account = str(row.get("account") or "").strip().lower()
            if account != "polymarket":
                continue
            amount = _safe_float(row.get("amount_usd"))
            if amount is not None:
                return float(amount), "json:capital_sources.polymarket.amount_usd"

    return None, "missing"


def run_stage_gate(
    *,
    stage_env_path: Path = DEFAULT_STAGE_ENV_PATH,
    multi_asset_config_path: Path = DEFAULT_MULTI_ASSET_CONFIG_PATH,
    asset_db_overrides: dict[str, Path] | None = None,
    asset_env_overrides: dict[str, Path] | None = None,
    balance_json_path: Path = DEFAULT_BALANCE_JSON_PATH,
    log_path: Path = DEFAULT_STAGE_GATE_LOG_PATH,
    dry_run: bool = False,
) -> dict[str, Any]:
    cwd = Path.cwd()
    stage_env_path = _resolve_relative(stage_env_path, cwd=cwd)
    multi_asset_config_path = _resolve_relative(multi_asset_config_path, cwd=cwd)
    balance_json_path = _resolve_relative(balance_json_path, cwd=cwd)
    log_path = _resolve_relative(log_path, cwd=cwd)

    config_db_paths, config_env_paths = _load_paths_from_multi_asset_config(multi_asset_config_path)
    db_paths = _merge_path_overrides(config_db_paths, asset_db_overrides)
    env_paths = _merge_path_overrides(config_env_paths, asset_env_overrides)

    stage_env = _parse_env_file(stage_env_path)
    actions: list[dict[str, Any]] = []

    per_asset: list[dict[str, Any]] = []
    for asset in ASSET_ORDER:
        db_path = _resolve_relative(db_paths.get(asset, DEFAULT_ASSET_DB_PATHS[asset]), cwd=cwd)
        metrics = _read_asset_fill_metrics(asset, db_path)
        metrics.pop("events", None)
        metrics["strategy_env_path"] = str(_resolve_relative(env_paths.get(asset, DEFAULT_ASSET_ENV_PATHS[asset]), cwd=cwd))
        per_asset.append(metrics)

    # Re-read events separately so the log payload stays compact.
    per_asset_with_events: list[dict[str, Any]] = []
    for asset in ASSET_ORDER:
        db_path = _resolve_relative(db_paths.get(asset, DEFAULT_ASSET_DB_PATHS[asset]), cwd=cwd)
        per_asset_with_events.append(_read_asset_fill_metrics(asset, db_path))
    aggregate = _build_aggregate_metrics(per_asset_with_events)

    requested_stage1, stage_reason = _stage_target_from_metrics(aggregate)
    stage_action: dict[str, Any] = {
        "type": "stage_promotion",
        "rule_reason": stage_reason,
        "requested_stage1_max_trade_usd": requested_stage1,
        "applied": False,
    }
    if requested_stage1 is not None:
        prior_value = _safe_float(stage_env.get(STAGE1_MAX_TRADE_KEY))
        if prior_value is None:
            prior_value = _safe_float(stage_env.get(GENERIC_MAX_TRADE_KEY), default=0.0) or 0.0
        effective_target, blocked, confirmation_key = _enforce_max_trade_cap(
            requested_value=float(requested_stage1),
            env_values=stage_env,
        )
        stage_action.update(
            {
                "prior_stage1_max_trade_usd": round(float(prior_value), 6),
                "effective_stage1_max_trade_usd": round(float(effective_target), 6),
                "blocked_by_hard_cap": bool(blocked),
                "confirmation_key_used": confirmation_key,
            }
        )
        if abs(float(prior_value) - float(effective_target)) > 1e-9:
            if not dry_run:
                _upsert_env_values(
                    stage_env_path,
                    {STAGE1_MAX_TRADE_KEY: _format_env_float(effective_target)},
                    header_comment="state/btc5_capital_stage.env — auto stage gate",
                )
            stage_env[STAGE1_MAX_TRADE_KEY] = _format_env_float(effective_target)
            stage_action["applied"] = True
    actions.append(stage_action)

    for asset_metrics in per_asset:
        asset = str(asset_metrics.get("asset") or "").lower()
        streak = int(asset_metrics.get("consecutive_losses_current") or 0)
        latest_fill_ts = _safe_int(asset_metrics.get("latest_fill_ts"), default=0)
        if asset not in ASSET_ORDER or streak < 5 or latest_fill_ts <= 0:
            continue
        if _already_scaled_for_latest_fill(log_path, asset=asset, latest_fill_ts=latest_fill_ts):
            actions.append(
                {
                    "type": "asset_loss_scale_down",
                    "asset": asset,
                    "latest_fill_ts": latest_fill_ts,
                    "applied": False,
                    "reason": "already_scaled_for_latest_fill",
                }
            )
            continue

        env_path = _resolve_relative(env_paths.get(asset, DEFAULT_ASSET_ENV_PATHS[asset]), cwd=cwd)
        env_values = _parse_env_file(env_path)
        current_max = _safe_float(env_values.get(STAGE1_MAX_TRADE_KEY))
        if current_max is None:
            current_max = _safe_float(env_values.get(GENERIC_MAX_TRADE_KEY))
        if current_max is None:
            current_max = _safe_float(stage_env.get(STAGE1_MAX_TRADE_KEY))
        if current_max is None:
            current_max = _safe_float(stage_env.get(GENERIC_MAX_TRADE_KEY))
        if current_max is None or current_max <= 0.0:
            actions.append(
                {
                    "type": "asset_loss_scale_down",
                    "asset": asset,
                    "latest_fill_ts": latest_fill_ts,
                    "applied": False,
                    "reason": "missing_or_non_positive_max_trade",
                    "strategy_env_path": str(env_path),
                }
            )
            continue

        requested_scaled = round(float(current_max) * 0.5, 6)
        effective_scaled, blocked, confirmation_key = _enforce_max_trade_cap(
            requested_value=requested_scaled,
            env_values=env_values,
        )
        if abs(float(current_max) - float(effective_scaled)) <= 1e-9:
            actions.append(
                {
                    "type": "asset_loss_scale_down",
                    "asset": asset,
                    "latest_fill_ts": latest_fill_ts,
                    "applied": False,
                    "reason": "no_change",
                    "strategy_env_path": str(env_path),
                    "prior_max_trade_usd": round(float(current_max), 6),
                    "effective_max_trade_usd": round(float(effective_scaled), 6),
                }
            )
            continue

        if not dry_run:
            _upsert_env_values(
                env_path,
                {
                    STAGE1_MAX_TRADE_KEY: _format_env_float(effective_scaled),
                    GENERIC_MAX_TRADE_KEY: _format_env_float(effective_scaled),
                },
                header_comment=f"{asset.upper()} strategy overrides — auto stage gate",
            )
        actions.append(
            {
                "type": "asset_loss_scale_down",
                "asset": asset,
                "latest_fill_ts": latest_fill_ts,
                "applied": True,
                "strategy_env_path": str(env_path),
                "prior_max_trade_usd": round(float(current_max), 6),
                "requested_max_trade_usd": round(float(requested_scaled), 6),
                "effective_max_trade_usd": round(float(effective_scaled), 6),
                "blocked_by_hard_cap": bool(blocked),
                "confirmation_key_used": confirmation_key,
                "reason": "consecutive_losses>=5",
            }
        )

    bankroll_usd = _safe_float(stage_env.get(BANKROLL_KEY), default=0.0) or 0.0
    clob_balance_usd, clob_balance_source = _extract_clob_balance(balance_json_path)
    halt_threshold_usd = bankroll_usd * 0.5 if bankroll_usd > 0.0 else None
    halt_triggered = bool(
        clob_balance_usd is not None
        and halt_threshold_usd is not None
        and clob_balance_usd < halt_threshold_usd
    )
    halt_action: dict[str, Any] = {
        "type": "balance_halt",
        "applied": False,
        "triggered": halt_triggered,
        "bankroll_usd": round(float(bankroll_usd), 6),
        "threshold_usd": (round(float(halt_threshold_usd), 6) if halt_threshold_usd is not None else None),
        "clob_balance_usd": (round(float(clob_balance_usd), 6) if clob_balance_usd is not None else None),
        "clob_balance_source": clob_balance_source,
    }
    if halt_triggered:
        prior_daily_loss = _safe_float(stage_env.get(DAILY_LOSS_LIMIT_KEY))
        halt_action["prior_daily_loss_limit_usd"] = prior_daily_loss
        if prior_daily_loss is None or abs(prior_daily_loss) > 1e-9:
            if not dry_run:
                _upsert_env_values(
                    stage_env_path,
                    {DAILY_LOSS_LIMIT_KEY: "0"},
                    header_comment="state/btc5_capital_stage.env — auto stage gate",
                )
            stage_env[DAILY_LOSS_LIMIT_KEY] = "0"
            halt_action["applied"] = True
    actions.append(halt_action)

    run_payload = {
        "generated_at": _iso_utc_now(),
        "dry_run": bool(dry_run),
        "stage_env_path": str(stage_env_path),
        "balance_json_path": str(balance_json_path),
        "multi_asset_config_path": str(multi_asset_config_path),
        "asset_db_paths": {asset: str(_resolve_relative(db_paths.get(asset, DEFAULT_ASSET_DB_PATHS[asset]), cwd=cwd)) for asset in ASSET_ORDER},
        "asset_env_paths": {asset: str(_resolve_relative(env_paths.get(asset, DEFAULT_ASSET_ENV_PATHS[asset]), cwd=cwd)) for asset in ASSET_ORDER},
        "aggregate": aggregate,
        "per_asset": per_asset,
        "actions": actions,
    }
    _append_log_entry(log_path, run_payload)
    run_payload["log_path"] = str(log_path)
    return run_payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage-env", type=Path, default=DEFAULT_STAGE_ENV_PATH)
    parser.add_argument("--multi-asset-config", type=Path, default=DEFAULT_MULTI_ASSET_CONFIG_PATH)
    parser.add_argument("--balance-json", type=Path, default=DEFAULT_BALANCE_JSON_PATH)
    parser.add_argument("--log-file", type=Path, default=DEFAULT_STAGE_GATE_LOG_PATH)
    parser.add_argument(
        "--asset-db",
        action="append",
        default=[],
        help="Override DB path per asset as asset=path (repeatable).",
    )
    parser.add_argument(
        "--asset-env",
        action="append",
        default=[],
        help="Override strategy env path per asset as asset=path (repeatable).",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    if load_dotenv is not None:
        load_dotenv()

    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        asset_db_overrides = _parse_key_value_paths(args.asset_db, arg_name="--asset-db")
        asset_env_overrides = _parse_key_value_paths(args.asset_env, arg_name="--asset-env")
    except ValueError as exc:
        parser.error(str(exc))
        return 2

    payload = run_stage_gate(
        stage_env_path=args.stage_env,
        multi_asset_config_path=args.multi_asset_config,
        asset_db_overrides=asset_db_overrides,
        asset_env_overrides=asset_env_overrides,
        balance_json_path=args.balance_json,
        log_path=args.log_file,
        dry_run=bool(args.dry_run),
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
