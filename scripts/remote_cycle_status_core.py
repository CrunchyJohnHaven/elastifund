#!/usr/bin/env python3
"""Write the compact remote-cycle status report."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shlex
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Sequence
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.runtime_profile import load_runtime_profile as load_runtime_profile_bundle
from bot.runtime_profile import write_effective_runtime_profile as write_runtime_profile_bundle
from flywheel.status_report import build_remote_cycle_status as build_base_remote_cycle_status
from infra.fast_json import dump_path_atomic, load_path, loads as fast_loads
from scripts.remote_cycle_status_io import (
    fetch_json_url as _fetch_json_url_io,
    load_json as _load_json_io,
    load_jsonl_rows as _load_jsonl_rows_io,
)
from scripts.remote_cycle_finance import (
    build_finance_gate_status as _build_finance_gate_status_impl,
    load_finance_gate_status as _load_finance_gate_status_impl,
)
from scripts.remote_cycle_launch_packet import (
    build_canonical_launch_packet as _build_canonical_launch_packet_impl,
)
from scripts.remote_cycle_reconciliation import (
    apply_canonical_launch_packet as _apply_canonical_launch_packet_impl,
    apply_canonical_launch_packet_to_status as _apply_canonical_launch_packet_to_status_impl,
)
from scripts.remote_cycle_public_snapshot import (
    build_public_headlines as _build_public_headlines_impl,
    build_public_runtime_snapshot as _build_public_runtime_snapshot_impl,
)
from scripts.remote_cycle_rendering import (
    build_operator_digest as _build_operator_digest_impl,
    format_signed_number as _format_signed_number_impl,
    render_remote_cycle_status_markdown as _render_remote_cycle_status_markdown_impl,
    render_runtime_mode_reconciliation_markdown as _render_runtime_mode_reconciliation_markdown_impl,
    render_state_improvement_digest_markdown as _render_state_improvement_digest_markdown_impl,
)
from scripts.remote_cycle_state_improvement import (
    build_state_improvement_evidence_freshness as _build_state_improvement_evidence_freshness_impl,
    build_state_improvement_truth_precedence as _build_state_improvement_truth_precedence_impl,
    count_recent_cap_breaches as _count_recent_cap_breaches_impl,
    hydrate_state_improvement_from_launch_contract as _hydrate_state_improvement_from_launch_contract_impl,
)

try:
    from src.polymarket_fee_model import maker_rebate_amount as _shared_maker_rebate_amount
except Exception:  # pragma: no cover - fallback keeps truth generation resilient
    _shared_maker_rebate_amount = None


from scripts.remote_cycle_constants import (
    BTC5_DB_PROBE_SCRIPT,
    BTC5_PUBLIC_FORECAST_PATHS,
    BTC5_RESEARCH_OPTIONAL_PATHS,
    BTC5_RESEARCH_PRIMARY_PATHS,
    BTC5_RESEARCH_STALE_HOURS,
    DEFAULT_ARB_STATUS_PATH,
    DEFAULT_BTC5_DB_PATH,
    DEFAULT_BTC5_WINDOW_ROWS_PATH,
    DEFAULT_CONFIG_PATH,
    DEFAULT_ENV_EXAMPLE_PATH,
    DEFAULT_ENV_PATH,
    DEFAULT_FAST_MARKET_SEARCH_LATEST_PATH,
    DEFAULT_FINANCE_LATEST_PATH,
    DEFAULT_JSON_PATH,
    DEFAULT_LAUNCH_CHECKLIST_PATH,
    DEFAULT_LAUNCH_PACKET_LATEST_PATH,
    DEFAULT_MARKDOWN_PATH,
    DEFAULT_PUBLIC_RUNTIME_SNAPSHOT_PATH,
    DEFAULT_ROOT_TEST_COMMAND,
    DEFAULT_ROOT_TEST_STATUS_PATH,
    DEFAULT_RUNTIME_OPERATOR_OVERRIDES_PATH,
    DEFAULT_RUNTIME_PROFILE_EFFECTIVE_PATH,
    DEFAULT_RUNTIME_MODE_RECONCILIATION_HISTORY_DIR,
    DEFAULT_TRADE_PROOF_LATEST_PATH,
    DEFAULT_RUNTIME_TRUTH_LATEST_PATH,
    DEFAULT_RUNTIME_TRUTH_HISTORY_DIR,
    DEFAULT_SERVICE_STATUS_PATH,
    DEFAULT_STATE_IMPROVEMENT_DIGEST_PATH,
    DEFAULT_STATE_IMPROVEMENT_HISTORY_DIR,
    DEFAULT_STATE_IMPROVEMENT_LATEST_PATH,
    DEFAULT_LAUNCH_PACKET_HISTORY_DIR,
    DEFAULT_TRADES_DB_PATH,
    DEFAULT_WALLET_DB_PATH,
    DEFAULT_WALLET_SCORES_PATH,
    REMOTE_BOT_DIR,
    REMOTE_PYTHONPATH,
    PRIMARY_RUNTIME_SERVICE_NAME,
    RESULT_SUMMARY_RE,
    RUNTIME_ENV_KEYS,
    WALLET_PROBE_SCRIPT,
)

LEGACY_ROOT_TEST_STATUS_PATH = Path("reports/root_test_status.json")
LEGACY_ARB_STATUS_PATH = Path("reports/arb_empirical_snapshot.json")
LEGACY_RUNTIME_OPERATOR_OVERRIDES_PATH = Path("reports/runtime_operator_overrides.env")
LEGACY_RUNTIME_PROFILE_EFFECTIVE_PATH = Path("reports/runtime_profile_effective.json")
LEGACY_ALIASES_INDEX_PATH = Path("reports/legacy_aliases_latest.json")
BTC5_DEPLOY_ACTIVATION_PATH = Path("reports/btc5_deploy_activation.json")
BTC5_CAPITAL_STAGE_ENV_PATH = Path("state/btc5_capital_stage.env")
BTC5_AUTORESEARCH_ENV_PATH = Path("state/btc5_autoresearch.env")
WALLET_RECONCILIATION_LATEST_PATH = Path("reports/wallet_reconciliation/latest.json")
WALLET_RECONCILIATION_MAX_FALLBACK_AGE_HOURS = 3.0
REQUIRED_COMPATIBILITY_ALIAS_NAMES: tuple[str, ...] = (
    "strategy_scale_comparison.json",
    "signal_source_audit.json",
    "root_test_status.json",
    "arb_empirical_snapshot.json",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fetch_json_url(url: str, *, timeout_seconds: int = 20) -> Any:
    return _fetch_json_url_io(url, timeout_seconds=timeout_seconds)


def _fetch_paginated_polymarket_endpoint(
    *,
    base_url: str,
    params: dict[str, Any],
    limit: int = 200,
    max_pages: int = 20,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    page_count = 0
    while page_count < max(1, int(max_pages)):
        query = dict(params)
        query["limit"] = str(max(1, int(limit)))
        query["offset"] = str(max(0, int(offset)))
        payload = _fetch_json_url(base_url + "?" + urllib.parse.urlencode(query))
        if not isinstance(payload, list) or not payload:
            break
        page_rows = [item for item in payload if isinstance(item, dict)]
        if not page_rows:
            break
        rows.extend(page_rows)
        page_count += 1
        if len(page_rows) < limit:
            break
        offset += len(page_rows)
    return rows


def _position_market_text(item: dict[str, Any]) -> str:
    parts = [
        item.get("title"),
        item.get("question"),
        item.get("market"),
        item.get("slug"),
        item.get("ticker"),
        item.get("conditionId"),
        item.get("asset"),
    ]
    return " ".join(str(part or "").strip().lower() for part in parts if part is not None).strip()


def _looks_like_btc5_contract(item: dict[str, Any]) -> bool:
    text = _position_market_text(item)
    if "btc" not in text:
        return False
    if any(token in text for token in ("5m", "5 min", "5-minute", "5 minute", "up or down", "up/down")):
        return True
    return "btc-updown" in text


def _extract_position_event_ts(item: dict[str, Any]) -> datetime | None:
    for key in (
        "endDate",
        "resolvedAt",
        "resolved_at",
        "updatedAt",
        "updated_at",
        "createdAt",
        "created_at",
        "timestamp",
    ):
        parsed = _parse_datetime_like(item.get(key))
        if parsed is not None:
            return parsed
    return None


def _position_cashflow_usd(item: dict[str, Any]) -> float:
    return round(
        _safe_float(
            _first_nonempty(
                item.get("cashPnl"),
                item.get("realizedPnl"),
                item.get("pnl"),
            ),
            0.0,
        ),
        4,
    )


def _wallet_closed_batch_metrics(
    *,
    open_positions: list[dict[str, Any]],
    closed_positions: list[dict[str, Any]],
) -> dict[str, Any]:
    btc_closed = [item for item in closed_positions if _looks_like_btc5_contract(item)]
    btc_cashflows = [_position_cashflow_usd(item) for item in btc_closed]
    btc_wins = [value for value in btc_cashflows if value > 0.0]
    btc_losses = [value for value in btc_cashflows if value < 0.0]
    btc_sum = round(sum(btc_cashflows), 4)
    gross_wins = round(sum(btc_wins), 4)
    gross_losses_abs = round(abs(sum(btc_losses)), 4)
    btc_profit_factor = None
    if gross_losses_abs > 0:
        btc_profit_factor = round(gross_wins / gross_losses_abs, 4)

    btc_ts = [ts for ts in (_extract_position_event_ts(item) for item in btc_closed) if ts is not None]
    btc_window_hours = None
    if len(btc_ts) >= 2:
        btc_window_hours = max(1.0 / 60.0, (max(btc_ts) - min(btc_ts)).total_seconds() / 3600.0)

    all_closed_cashflow = round(sum(_position_cashflow_usd(item) for item in closed_positions), 4)
    all_ts = [ts for ts in (_extract_position_event_ts(item) for item in closed_positions) if ts is not None]
    all_window_hours = None
    if len(all_ts) >= 2:
        all_window_hours = max(1.0 / 60.0, (max(all_ts) - min(all_ts)).total_seconds() / 3600.0)

    open_non_btc = [item for item in open_positions if not _looks_like_btc5_contract(item)]
    open_non_btc_notional = round(
        sum(
            _safe_float(
                _first_nonempty(item.get("initialValue"), item.get("currentValue"), item.get("size"), item.get("notional")),
                0.0,
            )
            for item in open_non_btc
        ),
        4,
    )
    conservative_closed_net = round(all_closed_cashflow - open_non_btc_notional, 4)

    return {
        "btc_closed_cashflow_usd": btc_sum,
        "btc_contracts_resolved": len(btc_closed),
        "btc_wins": len(btc_wins),
        "btc_losses": len(btc_losses),
        "btc_profit_factor": btc_profit_factor,
        "btc_average_win_usd": round((sum(btc_wins) / len(btc_wins)), 4) if btc_wins else None,
        "btc_average_loss_usd": round((sum(btc_losses) / len(btc_losses)), 4) if btc_losses else None,
        "btc_closed_window_hours": round(btc_window_hours, 4) if btc_window_hours is not None else None,
        "all_book_closed_cashflow_usd": all_closed_cashflow,
        "open_non_btc_notional_usd": open_non_btc_notional,
        "conservative_closed_net_usd": conservative_closed_net,
        "all_book_closed_window_hours": round(all_window_hours, 4) if all_window_hours is not None else None,
    }


def _wallet_export_candidates(root: Path) -> list[Path]:
    candidates: list[Path] = []
    seen: set[Path] = set()
    search_roots: list[Path] = [root, root / "data", root / "reports"]

    explicit_path = os.environ.get("ELASTIFUND_WALLET_EXPORT_PATH")
    if explicit_path:
        search_roots.insert(0, Path(explicit_path).expanduser())

    explicit_dirs = os.environ.get("ELASTIFUND_WALLET_EXPORT_DIRS")
    if explicit_dirs:
        for raw_item in explicit_dirs.split(os.pathsep):
            item = raw_item.strip()
            if item:
                search_roots.append(Path(item).expanduser())

    downloads_dir = Path.home() / "Downloads"
    if root.resolve() == ROOT and downloads_dir.exists():
        search_roots.append(downloads_dir)

    for base in search_roots:
        if not base.exists():
            continue
        if base.is_file():
            glob_paths = [base] if base.name.startswith("Polymarket-History") and base.suffix == ".csv" else []
        else:
            glob_paths = list(base.glob("Polymarket-History*.csv"))
        for path in glob_paths:
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            candidates.append(path)
    candidates.sort(key=lambda path: path.stat().st_mtime if path.exists() else 0.0, reverse=True)
    return candidates


def _normalize_wallet_row_key(value: Any) -> str:
    return (
        str(value or "")
        .replace("\ufeff", "")
        .strip()
        .strip('"')
        .strip("'")
        .strip()
        .lower()
        .replace(" ", "_")
    )


def _normalize_wallet_market_key(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    chars = [ch if ch.isalnum() else " " for ch in text]
    return " ".join("".join(chars).split())


def _wallet_row_value(row: dict[str, Any], keys: Sequence[str]) -> str:
    normalized_targets = {_normalize_wallet_row_key(key) for key in keys}
    for key in keys:
        if key in row and str(row.get(key) or "").strip():
            return str(row.get(key) or "").strip()
    for raw_key, raw_value in row.items():
        if _normalize_wallet_row_key(raw_key) in normalized_targets and str(raw_value or "").strip():
            return str(raw_value or "").strip()
    return ""


def _wallet_row_float(row: dict[str, Any], keys: Sequence[str]) -> float | None:
    raw = _wallet_row_value(row, keys)
    if not raw:
        return None
    cleaned = (
        raw.replace("$", "")
        .replace("USDC", "")
        .replace("USD", "")
        .replace(",", "")
        .strip()
    )
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _wallet_row_ts(row: dict[str, Any]) -> datetime | None:
    return _parse_datetime_like(
        _wallet_row_value(
            row,
            (
                "timestamp",
                "time",
                "datetime",
                "date",
                "updated_at",
                "created_at",
                "closed_at",
                "resolved_at",
            ),
        )
    )


def _wallet_export_summary_sort_key(summary: dict[str, Any], *, fallback_path: Path) -> tuple[float, int, float]:
    exported_at = _parse_datetime_like(summary.get("exported_at"))
    exported_ts = exported_at.timestamp() if exported_at is not None else 0.0
    row_count = int(_safe_float(summary.get("row_count"), 0.0) or 0)
    try:
        mtime = fallback_path.stat().st_mtime
    except OSError:
        mtime = 0.0
    return (exported_ts, row_count, mtime)


def _wallet_export_action_delta_usd(action: str, amount: float, *, include_rebates: bool) -> float:
    normalized = str(action or "").strip().lower()
    if normalized == "buy":
        return -amount
    if normalized in {"redeem", "sell"}:
        return amount
    if include_rebates and normalized in {"maker rebate", "maker_rebate", "rebate"}:
        return amount
    return 0.0


def _wallet_export_market_entry(
    *,
    market_name: str,
    rollup: dict[str, Any],
) -> dict[str, Any]:
    buy_usdc = round(float(rollup.get("buy_usdc_total") or 0.0), 6)
    redeem_usdc = round(float(rollup.get("redeem_usdc_total") or 0.0), 6)
    rebate_usdc = round(float(rollup.get("rebate_usdc_total") or 0.0), 6)
    net_excluding_rebates = round(redeem_usdc - buy_usdc, 6)
    net_including_rebates = round(redeem_usdc + rebate_usdc - buy_usdc, 6)
    latest_ts = rollup.get("latest_ts")
    latest_iso = latest_ts.isoformat() if isinstance(latest_ts, datetime) else None
    return {
        "market_name": market_name,
        "market_key": rollup.get("market_key"),
        "is_btc": bool(rollup.get("is_btc")),
        "buy_count": int(rollup.get("buy_count") or 0),
        "redeem_count": int(rollup.get("redeem_count") or 0),
        "rebate_count": int(rollup.get("rebate_count") or 0),
        "buy_usdc": buy_usdc,
        "redeem_usdc": redeem_usdc,
        "maker_rebate_usdc": rebate_usdc,
        "net_cash_flow_excluding_rebates_usd": net_excluding_rebates,
        "net_cash_flow_including_rebates_usd": net_including_rebates,
        "latest_timestamp": latest_iso,
    }


def _series_delta_1d(series: list[tuple[datetime, float]]) -> float | None:
    if not series:
        return None
    ordered = sorted(series, key=lambda item: item[0])
    latest_ts, latest_value = ordered[-1]
    target = latest_ts - timedelta(hours=24)
    prior_candidates = [item for item in ordered if item[0] <= target]
    if prior_candidates:
        prior_value = prior_candidates[-1][1]
    else:
        return None
    return round(latest_value - prior_value, 4)


def _age_hours_from_datetimes(
    *,
    reference_at: datetime | None,
    observed_at: datetime | None,
) -> float | None:
    if reference_at is None or observed_at is None:
        return None
    return max(0.0, (reference_at - observed_at).total_seconds() / 3600.0)


def _freshness_label_for_age_hours(
    age_hours: float | None,
    *,
    stale_after_hours: float = BTC5_RESEARCH_STALE_HOURS,
) -> str:
    if age_hours is None:
        return "unknown"
    if age_hours <= max(stale_after_hours / 2.0, 0.5):
        return "fresh"
    if age_hours <= stale_after_hours:
        return "aging"
    return "stale"


def _freshness_score_for_label(label: Any) -> float:
    text = str(label or "unknown").strip().lower()
    if text == "fresh":
        return 1.0
    if text == "aging":
        return 0.65
    if text == "stale":
        return 0.2
    return 0.35


def _confirmation_score_for_label(label: Any) -> float | None:
    text = str(label or "").strip().lower()
    if not text:
        return None
    if text == "strong":
        return 0.85
    if text == "moderate":
        return 0.55
    if text == "weak":
        return 0.2
    if text == "missing":
        return 0.0
    return None


def _normalize_unit_score(value: Any) -> float | None:
    parsed = _float_or_none(value)
    if parsed is None:
        return None
    if parsed > 1.0:
        parsed = parsed / 100.0
    return round(min(max(parsed, 0.0), 1.0), 4)


def _confidence_label_for_score(score: float | None) -> str:
    if score is None:
        return "unknown"
    if score >= 0.8:
        return "high"
    if score >= 0.55:
        return "medium"
    return "low"


def _load_wallet_export_summary(
    *,
    root: Path,
    generated_at: datetime,
    btc5_data_at: datetime | None,
) -> dict[str, Any] | None:
    candidates = _wallet_export_candidates(root)
    if not candidates:
        return None
    best_summary: dict[str, Any] | None = None
    best_sort_key: tuple[float, int, float] | None = None
    candidate_summaries: list[tuple[Path, dict[str, Any]]] = []

    for path in candidates:
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as fh:
                reader = csv.DictReader(fh)
                rows = [dict(row) for row in reader if isinstance(row, dict)]
        except (OSError, csv.Error):
            continue
        if not rows:
            continue

        btc_closed_markets = 0
        btc_closed_net_cashflow_usd = 0.0
        btc_open_markets = 0
        non_btc_open_buy_notional_usd = 0.0
        btc_closed_ts: list[datetime] = []
        export_latest_ts: datetime | None = None
        export_earliest_ts: datetime | None = None
        equity_series: list[tuple[datetime, float]] = []
        closed_cashflow_series: list[tuple[datetime, float]] = []
        open_notional_series: list[tuple[datetime, float]] = []
        trading_cashflow_series: list[tuple[datetime, float]] = []
        trading_cashflow_cumulative = 0.0
        buy_usdc_total = 0.0
        redeem_usdc_total = 0.0
        maker_rebate_usdc_total = 0.0
        deposit_usdc_total = 0.0
        zero_value_redeems = 0
        market_rollups: dict[str, dict[str, Any]] = {}

        for row in rows:
            ts = _wallet_row_ts(row)
            if ts is not None and (export_latest_ts is None or ts > export_latest_ts):
                export_latest_ts = ts
            if ts is not None and (export_earliest_ts is None or ts < export_earliest_ts):
                export_earliest_ts = ts

            market_text = _wallet_row_value(
                row,
                (
                    "marketName",
                    "market_name",
                    "market",
                    "market_title",
                    "title",
                    "question",
                    "event",
                    "ticker",
                    "slug",
                ),
            )
            market_key = _normalize_wallet_market_key(market_text)
            market_text_lower = market_text.lower()
            action = _wallet_row_value(row, ("action", "type", "side")).lower()
            status = _wallet_row_value(row, ("status", "state", "position_status", "order_status")).lower()
            is_btc = ("btc" in market_text_lower) or ("bitcoin" in market_text_lower)
            is_closed = any(token in status for token in ("closed", "resolved", "settled"))
            is_open = ("open" in status) and not is_closed
            usdc_amount = _wallet_row_float(
                row,
                (
                    "usdcAmount",
                    "usdc_amount",
                    "amount_usd",
                    "cashflow_usd",
                    "closed_cashflow_usd",
                    "realized_cashflow_usd",
                    "realized_pnl_usd",
                    "cash_pnl_usd",
                    "pnl_usd",
                ),
            )
            if usdc_amount is None:
                usdc_amount = 0.0

            if action == "buy":
                buy_usdc_total += usdc_amount
            elif action in {"redeem", "sell"}:
                redeem_usdc_total += usdc_amount
                if abs(usdc_amount) <= 1e-9:
                    zero_value_redeems += 1
            elif action in {"maker rebate", "maker_rebate", "rebate"}:
                maker_rebate_usdc_total += usdc_amount
            elif action == "deposit":
                deposit_usdc_total += usdc_amount

            cashflow = _wallet_row_float(
                row,
                (
                    "cashflow_usd",
                    "closed_cashflow_usd",
                    "realized_cashflow_usd",
                    "realized_pnl_usd",
                    "cash_pnl_usd",
                    "pnl_usd",
                ),
            )
            if cashflow is None:
                cashflow = 0.0
            buy_notional = _wallet_row_float(
                row,
                (
                    "open_buy_notional_usd",
                    "open_notional_usd",
                    "buy_notional_usd",
                    "buy_amount_usd",
                    "initial_value_usd",
                    "notional_usd",
                    "size_usd",
                ),
            )
            if buy_notional is None:
                buy_notional = 0.0

            if not action:
                if is_closed and is_btc:
                    btc_closed_markets += 1
                    btc_closed_net_cashflow_usd += cashflow
                    if ts is not None:
                        btc_closed_ts.append(ts)
                if is_open and is_btc:
                    btc_open_markets += 1
                if is_open and not is_btc:
                    non_btc_open_buy_notional_usd += max(0.0, buy_notional)

            if market_key and action in {"buy", "redeem", "sell", "maker rebate", "maker_rebate", "rebate"}:
                rollup = market_rollups.setdefault(
                    market_key,
                    {
                        "market_key": market_key,
                        "market_text": market_text,
                        "is_btc": is_btc,
                        "buy_count": 0,
                        "redeem_count": 0,
                        "rebate_count": 0,
                        "buy_usdc_total": 0.0,
                        "redeem_usdc_total": 0.0,
                        "rebate_usdc_total": 0.0,
                        "status_closed": False,
                        "status_open": False,
                        "latest_ts": None,
                        "latest_redeem_ts": None,
                    },
                )
                rollup["is_btc"] = bool(rollup["is_btc"] or is_btc)
                if market_text:
                    rollup["market_text"] = market_text
                if ts is not None and (rollup["latest_ts"] is None or ts > rollup["latest_ts"]):
                    rollup["latest_ts"] = ts
                if action == "buy":
                    rollup["buy_count"] = int(rollup["buy_count"]) + 1
                    rollup["buy_usdc_total"] = round(float(rollup["buy_usdc_total"]) + usdc_amount, 6)
                elif action in {"redeem", "sell"}:
                    rollup["redeem_count"] = int(rollup["redeem_count"]) + 1
                    rollup["redeem_usdc_total"] = round(float(rollup["redeem_usdc_total"]) + usdc_amount, 6)
                    if ts is not None and (rollup["latest_redeem_ts"] is None or ts > rollup["latest_redeem_ts"]):
                        rollup["latest_redeem_ts"] = ts
                elif action in {"maker rebate", "maker_rebate", "rebate"}:
                    rollup["rebate_count"] = int(rollup["rebate_count"]) + 1
                    rollup["rebate_usdc_total"] = round(float(rollup["rebate_usdc_total"]) + usdc_amount, 6)
                if is_closed:
                    rollup["status_closed"] = True
                if is_open:
                    rollup["status_open"] = True

            if ts is not None and action:
                delta_with_rebates = _wallet_export_action_delta_usd(action, usdc_amount, include_rebates=True)
                if delta_with_rebates != 0.0:
                    trading_cashflow_cumulative += delta_with_rebates
                    trading_cashflow_series.append((ts, trading_cashflow_cumulative))

            equity = _wallet_row_float(
                row,
                ("portfolio_equity_usd", "portfolio_value_usd", "equity_usd", "wallet_value_usd", "total_wallet_value_usd"),
            )
            cumulative_closed = _wallet_row_float(
                row,
                ("closed_cashflow_usd", "cumulative_closed_cashflow_usd", "closed_net_cashflow_usd", "realized_cashflow_usd"),
            )
            open_notional = _wallet_row_float(
                row,
                ("open_notional_usd", "open_buy_notional_usd", "open_positions_notional_usd"),
            )
            if ts is not None and equity is not None:
                equity_series.append((ts, equity))
            if ts is not None and cumulative_closed is not None:
                closed_cashflow_series.append((ts, cumulative_closed))
            if ts is not None and open_notional is not None:
                open_notional_series.append((ts, open_notional))

        realized_winners: list[dict[str, Any]] = []
        unresolved_exposures: list[dict[str, Any]] = []
        for rollup in market_rollups.values():
            action_open = int(rollup["buy_count"] or 0) > int(rollup["redeem_count"] or 0)
            action_closed = int(rollup["redeem_count"] or 0) > 0 and not action_open
            bucket_is_open = action_open or (bool(rollup["status_open"]) and not bool(rollup["status_closed"]))
            bucket_is_closed = action_closed or (bool(rollup["status_closed"]) and not action_open)
            market_entry = _wallet_export_market_entry(
                market_name=str(rollup.get("market_text") or ""),
                rollup=rollup,
            )
            if bucket_is_closed:
                realized_winners.append(market_entry)
            if bucket_is_open:
                unresolved_exposures.append(market_entry)
            if bucket_is_closed and bool(rollup["is_btc"]):
                btc_closed_markets += 1
                btc_closed_net_cashflow_usd += float(market_entry["net_cash_flow_including_rebates_usd"])
                closed_ts = rollup["latest_redeem_ts"] or rollup["latest_ts"]
                if isinstance(closed_ts, datetime):
                    btc_closed_ts.append(closed_ts)
            if bucket_is_open and bool(rollup["is_btc"]):
                btc_open_markets += 1
            if bucket_is_open and not bool(rollup["is_btc"]):
                non_btc_open_buy_notional_usd += max(0.0, float(rollup["buy_usdc_total"]))

        if export_latest_ts is None:
            export_latest_ts = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        export_age_hours = max(0.0, (generated_at - export_latest_ts).total_seconds() / 3600.0)
        wallet_export_fresh = export_age_hours <= BTC5_RESEARCH_STALE_HOURS
        fresher_than_btc = btc5_data_at is None or export_latest_ts >= btc5_data_at
        use_wallet_export_reporting = wallet_export_fresh and fresher_than_btc

        btc_closed_window_hours = None
        if len(btc_closed_ts) >= 2:
            btc_closed_window_hours = max(
                1.0 / 60.0,
                (max(btc_closed_ts) - min(btc_closed_ts)).total_seconds() / 3600.0,
            )

        top_realized_winners = sorted(
            (item for item in realized_winners if float(item.get("net_cash_flow_including_rebates_usd") or 0.0) > 0.0),
            key=lambda item: (
                -float(item.get("net_cash_flow_including_rebates_usd") or 0.0),
                -float(item.get("redeem_usdc") or 0.0),
                str(item.get("market_name") or ""),
            ),
        )[:10]
        top_unresolved_exposures = sorted(
            unresolved_exposures,
            key=lambda item: (
                float(item.get("net_cash_flow_including_rebates_usd") or 0.0),
                -float(item.get("buy_usdc") or 0.0),
                str(item.get("market_name") or ""),
            ),
        )[:10]
        latest_et = export_latest_ts.astimezone(ZoneInfo("America/New_York"))
        midnight_et = latest_et.replace(hour=0, minute=0, second=0, microsecond=0)
        midnight_utc = midnight_et.astimezone(timezone.utc)
        after_midnight_et_net = round(
            sum(
                _wallet_export_action_delta_usd(
                    _wallet_row_value(row, ("action", "type", "side")),
                    _wallet_row_float(
                        row,
                        (
                            "usdcAmount",
                            "usdc_amount",
                            "amount_usd",
                            "cashflow_usd",
                            "closed_cashflow_usd",
                            "realized_cashflow_usd",
                            "realized_pnl_usd",
                            "cash_pnl_usd",
                            "pnl_usd",
                        ),
                    )
                    or 0.0,
                    include_rebates=False,
                )
                for row in rows
                if (_wallet_row_ts(row) or midnight_utc) >= midnight_utc
            ),
            6,
        )

        summary = {
            "source_path": _relative_path_text(root, path) or str(path),
            "source_class": "wallet_export_csv",
            "row_count": len(rows),
            "market_count": len(market_rollups),
            "exported_at": export_latest_ts.isoformat(),
            "earliest_timestamp": export_earliest_ts.isoformat() if export_earliest_ts is not None else None,
            "latest_timestamp": export_latest_ts.isoformat(),
            "source_age_hours": round(export_age_hours, 4),
            "wallet_export_fresh": wallet_export_fresh,
            "wallet_export_freshness_label": _freshness_label_for_age_hours(export_age_hours),
            "fresher_than_btc_reporting_source": fresher_than_btc,
            "use_wallet_export_reporting": use_wallet_export_reporting,
            "buy_usdc": round(buy_usdc_total, 6),
            "redeem_usdc": round(redeem_usdc_total, 6),
            "maker_rebate_usdc": round(maker_rebate_usdc_total, 6),
            "deposit_usdc": round(deposit_usdc_total, 6),
            "net_trading_cash_flow_excluding_deposits_usd": round(redeem_usdc_total - buy_usdc_total, 6),
            "net_trading_cash_flow_including_rebates_usd": round(
                redeem_usdc_total + maker_rebate_usdc_total - buy_usdc_total,
                6,
            ),
            "after_midnight_et_net_trading_cash_flow_usd": after_midnight_et_net,
            "zero_value_redeems": zero_value_redeems,
            "btc_closed_markets": int(btc_closed_markets),
            "btc_closed_net_cashflow_usd": round(btc_closed_net_cashflow_usd, 4),
            "btc_open_markets": int(btc_open_markets),
            "non_btc_open_buy_notional_usd": round(non_btc_open_buy_notional_usd, 4),
            "btc_closed_window_hours": round(btc_closed_window_hours, 4) if btc_closed_window_hours is not None else None,
            "top_realized_winners": top_realized_winners,
            "top_unresolved_exposures": top_unresolved_exposures,
            "portfolio_equity_delta_1d": _series_delta_1d(equity_series),
            "closed_cashflow_delta_1d": _series_delta_1d(closed_cashflow_series)
            if closed_cashflow_series
            else _series_delta_1d(trading_cashflow_series),
            "open_notional_delta_1d": _series_delta_1d(open_notional_series),
        }
        candidate_summaries.append((path, summary))
        sort_key = _wallet_export_summary_sort_key(summary, fallback_path=path)
        if best_sort_key is None or sort_key > best_sort_key:
            best_sort_key = sort_key
            best_summary = summary

    if best_summary is None:
        return None

    selected_path = next(
        (
            candidate_path
            for candidate_path, candidate_summary in candidate_summaries
            if candidate_summary is best_summary
        ),
        None,
    )
    conflicting_candidates: list[dict[str, Any]] = []
    candidate_debug: list[dict[str, Any]] = []
    selected_row_count = int(_safe_float(best_summary.get("row_count"), 0.0) or 0)
    selected_market_count = int(_safe_float(best_summary.get("market_count"), 0.0) or 0)
    selected_net_cashflow = _float_or_none(
        best_summary.get("net_trading_cash_flow_excluding_deposits_usd")
    ) or 0.0
    for candidate_path, candidate_summary in candidate_summaries:
        debug_entry = {
            "source_path": candidate_summary.get("source_path"),
            "row_count": int(_safe_float(candidate_summary.get("row_count"), 0.0) or 0),
            "market_count": int(_safe_float(candidate_summary.get("market_count"), 0.0) or 0),
            "latest_timestamp": candidate_summary.get("latest_timestamp"),
            "net_trading_cash_flow_excluding_deposits_usd": _float_or_none(
                candidate_summary.get("net_trading_cash_flow_excluding_deposits_usd")
            ),
            "selected": candidate_summary is best_summary,
        }
        candidate_debug.append(debug_entry)
        if selected_path is not None and candidate_path.resolve() == selected_path.resolve():
            continue
        conflict_reasons: list[str] = []
        candidate_row_count = int(_safe_float(candidate_summary.get("row_count"), 0.0) or 0)
        candidate_market_count = int(_safe_float(candidate_summary.get("market_count"), 0.0) or 0)
        candidate_net_cashflow = _float_or_none(
            candidate_summary.get("net_trading_cash_flow_excluding_deposits_usd")
        ) or 0.0
        if candidate_row_count != selected_row_count:
            conflict_reasons.append("row_count_mismatch")
        if candidate_market_count != selected_market_count:
            conflict_reasons.append("market_count_mismatch")
        if abs(candidate_net_cashflow - selected_net_cashflow) > 1.0:
            conflict_reasons.append("net_trading_cash_flow_mismatch")
        if conflict_reasons:
            conflicting_candidates.append(
                {
                    "source_path": candidate_summary.get("source_path"),
                    "conflict_reasons": conflict_reasons,
                    "row_count": candidate_row_count,
                    "market_count": candidate_market_count,
                    "net_trading_cash_flow_excluding_deposits_usd": round(candidate_net_cashflow, 6),
                }
            )

    best_summary["candidate_count"] = len(candidate_summaries)
    best_summary["candidate_conflict_status"] = (
        "conflict" if conflicting_candidates else "consistent"
    )
    best_summary["candidate_conflicts"] = conflicting_candidates
    best_summary["candidate_debug"] = candidate_debug
    return best_summary


def _micro_usdc_to_usd(value: Any) -> float:
    parsed = _float_or_none(value)
    if parsed is None:
        return 0.0
    return round(parsed / 1_000_000.0, 6)


def _btc5_price_bucket(order_price: Any) -> str:
    price = _safe_float(order_price, 0.0)
    if price < 0.49:
        return "<0.49"
    if price < 0.50:
        return "0.49"
    if price < 0.51:
        return "0.50"
    return "0.51+"


def _estimate_btc5_maker_rebate_usd(
    *,
    order_price: Any,
    shares: Any = None,
    trade_size_usd: Any = None,
) -> float:
    price = _safe_float(order_price, None)
    if price is None or price <= 0.0 or price >= 1.0:
        return 0.0
    normalized_price = max(0.01, min(0.99, float(price)))
    share_count = _float_or_none(shares)
    if share_count is None or share_count <= 0.0:
        notional = _float_or_none(trade_size_usd)
        if notional is None or notional <= 0.0:
            return 0.0
        share_count = notional / normalized_price
    if share_count <= 0.0:
        return 0.0
    if _shared_maker_rebate_amount is not None:
        return round(float(_shared_maker_rebate_amount(normalized_price, "crypto", shares=share_count)), 6)
    uncertainty = normalized_price * (1.0 - normalized_price)
    effective_taker_rate = 0.25 * (uncertainty ** 2.0)
    taker_fee = share_count * normalized_price * effective_taker_rate
    return round(float(taker_fee * 0.20), 6)


def _enrich_btc5_fill_row(row: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(row)
    rebate = _estimate_btc5_maker_rebate_usd(
        order_price=enriched.get("order_price"),
        shares=enriched.get("shares"),
        trade_size_usd=enriched.get("trade_size_usd"),
    )
    enriched["estimated_maker_rebate_usd"] = rebate
    enriched["net_pnl_after_estimated_rebate_usd"] = round(
        (_safe_float(enriched.get("pnl_usd"), 0.0) or 0.0) + rebate,
        6,
    )
    return enriched


def _rollup_btc5_fill_group(group_rows: list[dict[str, Any]], *, label: str) -> dict[str, Any]:
    fills = len(group_rows)
    pnl = round(sum(_safe_float(row.get("pnl_usd"), 0.0) for row in group_rows), 4)
    estimated_rebate = round(
        sum(
            _estimate_btc5_maker_rebate_usd(
                order_price=row.get("order_price"),
                shares=row.get("shares"),
                trade_size_usd=row.get("trade_size_usd"),
            )
            for row in group_rows
        ),
        4,
    )
    net_pnl_after_rebate = round(pnl + estimated_rebate, 4)
    avg_pnl = round(pnl / fills, 4) if fills else 0.0
    avg_rebate = round(estimated_rebate / fills, 4) if fills else 0.0
    avg_net = round(net_pnl_after_rebate / fills, 4) if fills else 0.0
    avg_price = round(
        sum(_safe_float(row.get("order_price"), 0.0) for row in group_rows) / fills,
        4,
    ) if fills else 0.0
    return {
        "label": label,
        "fills": fills,
        "pnl_usd": pnl,
        "estimated_maker_rebate_usd": estimated_rebate,
        "net_pnl_after_estimated_rebate_usd": net_pnl_after_rebate,
        "avg_pnl_usd": avg_pnl,
        "avg_estimated_maker_rebate_usd": avg_rebate,
        "avg_net_pnl_after_estimated_rebate_usd": avg_net,
        "avg_order_price": avg_price,
    }


def _summarize_btc5_fill_attribution(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None

    direction_groups: dict[str, list[dict[str, Any]]] = {}
    price_bucket_groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        direction = str(row.get("direction") or "UNKNOWN").strip().upper() or "UNKNOWN"
        direction_groups.setdefault(direction, []).append(row)
        price_bucket_groups.setdefault(_btc5_price_bucket(row.get("order_price")), []).append(row)

    by_direction = sorted(
        (_rollup_btc5_fill_group(group_rows, label=direction) for direction, group_rows in direction_groups.items()),
        key=lambda item: (-item["pnl_usd"], -item["fills"], item["label"]),
    )
    bucket_order = {"<0.49": 0, "0.49": 1, "0.50": 2, "0.51+": 3}
    by_price_bucket = sorted(
        (_rollup_btc5_fill_group(group_rows, label=bucket) for bucket, group_rows in price_bucket_groups.items()),
        key=lambda item: bucket_order.get(item["label"], 99),
    )
    sorted_recent = sorted(
        rows,
        key=lambda row: _int_or_none(row.get("id")) or 0,
        reverse=True,
    )[:12]
    recent_summary = _rollup_btc5_fill_group(sorted_recent, label="recent_12_live_filled")
    recent_by_direction = sorted(
        (
            _rollup_btc5_fill_group(
                [row for row in sorted_recent if str(row.get("direction") or "").strip().upper() == direction],
                label=direction,
            )
            for direction in {str(row.get("direction") or "UNKNOWN").strip().upper() or "UNKNOWN" for row in sorted_recent}
        ),
        key=lambda item: (-item["pnl_usd"], -item["fills"], item["label"]),
    )
    recent_direction_regime: dict[str, Any] = {
        "fills_considered": sum(item["fills"] for item in recent_by_direction),
        "default_quote_ticks": 1,
        "weaker_direction_quote_ticks": 0,
        "min_fills_per_direction": 5,
        "min_pnl_gap_usd": 20.0,
        "by_direction": recent_by_direction,
        "triggered": False,
        "trigger_reason": "insufficient_directions",
        "direction_quote_ticks": {},
    }
    if len(recent_by_direction) >= 2:
        favored = recent_by_direction[0]
        weaker = recent_by_direction[1]
        pnl_gap = round(favored["pnl_usd"] - weaker["pnl_usd"], 4)
        recent_direction_regime.update(
            {
                "favored_direction": favored["label"],
                "weaker_direction": weaker["label"],
                "pnl_gap_usd": pnl_gap,
            }
        )
        if favored["fills"] < 5 or weaker["fills"] < 5:
            recent_direction_regime["trigger_reason"] = "insufficient_fills"
        elif favored["avg_pnl_usd"] <= weaker["avg_pnl_usd"]:
            recent_direction_regime["trigger_reason"] = "no_avg_pnl_edge"
        elif pnl_gap < 20.0:
            recent_direction_regime["trigger_reason"] = "pnl_gap_below_threshold"
        else:
            recent_direction_regime["triggered"] = True
            recent_direction_regime["trigger_reason"] = "weaker_direction_quote_tightened"
            recent_direction_regime["direction_quote_ticks"] = {
                favored["label"]: 1,
                weaker["label"]: 0,
            }

    best_direction = by_direction[0] if by_direction else None
    best_price_bucket = max(
        by_price_bucket,
        key=lambda item: (item["pnl_usd"], item["fills"], -bucket_order.get(item["label"], 99)),
        default=None,
    )
    return {
        "by_direction": by_direction,
        "by_price_bucket": by_price_bucket,
        "recent_live_filled_summary": recent_summary,
        "recent_live_filled_by_direction": recent_by_direction,
        "recent_direction_regime": recent_direction_regime,
        "best_direction": best_direction,
        "best_price_bucket": best_price_bucket,
    }


def _summarize_btc5_intraday_live(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "filled_rows_today": 0,
            "filled_pnl_usd_today": 0.0,
            "estimated_maker_rebate_usd_today": 0.0,
            "net_pnl_after_estimated_rebate_usd_today": 0.0,
            "win_rate_today": None,
            "recent_5_pnl_usd": 0.0,
            "recent_5_estimated_maker_rebate_usd": 0.0,
            "recent_5_net_pnl_after_estimated_rebate_usd": 0.0,
            "recent_12_pnl_usd": 0.0,
            "recent_12_estimated_maker_rebate_usd": 0.0,
            "recent_12_net_pnl_after_estimated_rebate_usd": 0.0,
            "recent_20_pnl_usd": 0.0,
            "recent_20_estimated_maker_rebate_usd": 0.0,
            "recent_20_net_pnl_after_estimated_rebate_usd": 0.0,
            "skip_price_count": 0,
            "order_failed_count": 0,
            "cancelled_unfilled_count": 0,
            "best_direction_today": None,
            "best_price_bucket_today": None,
        }

    parsed_rows: list[dict[str, Any]] = []
    latest_ts: datetime | None = None
    for row in rows:
        ts = _parse_datetime_like(_first_nonempty(row.get("updated_at"), row.get("created_at")))
        parsed = dict(row)
        parsed["_event_ts"] = ts
        parsed_rows.append(parsed)
        if ts is not None and (latest_ts is None or ts > latest_ts):
            latest_ts = ts

    if latest_ts is None:
        today_rows = parsed_rows
    else:
        today_rows = [row for row in parsed_rows if row.get("_event_ts") and row["_event_ts"].date() == latest_ts.date()]

    def _status_text(row: dict[str, Any]) -> str:
        return str(row.get("order_status") or "").strip().lower()

    today_live_filled = [
        row for row in today_rows if _status_text(row) == "live_filled"
    ]
    recent_live_filled = [
        row for row in parsed_rows if _status_text(row) == "live_filled"
    ]
    recent_live_filled.sort(
        key=lambda row: (
            _int_or_none(row.get("id")) or 0,
            (_parse_datetime_like(_first_nonempty(row.get("updated_at"), row.get("created_at")))
             or datetime.fromtimestamp(0, tz=timezone.utc)).timestamp(),
        ),
        reverse=True,
    )

    def _sum_recent(n: int) -> float:
        return round(sum(_safe_float(row.get("pnl_usd"), 0.0) for row in recent_live_filled[:n]), 4)

    def _sum_recent_rebate(n: int) -> float:
        return round(
            sum(
                _estimate_btc5_maker_rebate_usd(
                    order_price=row.get("order_price"),
                    shares=row.get("shares"),
                    trade_size_usd=row.get("trade_size_usd"),
                )
                for row in recent_live_filled[:n]
            ),
            4,
        )

    filled_rows_today = len(today_live_filled)
    filled_pnl_usd_today = round(sum(_safe_float(row.get("pnl_usd"), 0.0) for row in today_live_filled), 4)
    estimated_maker_rebate_usd_today = round(
        sum(
            _estimate_btc5_maker_rebate_usd(
                order_price=row.get("order_price"),
                shares=row.get("shares"),
                trade_size_usd=row.get("trade_size_usd"),
            )
            for row in today_live_filled
        ),
        4,
    )
    win_rate_today = (
        round(sum(1 for row in today_live_filled if _safe_float(row.get("pnl_usd"), 0.0) > 0) / filled_rows_today, 4)
        if filled_rows_today
        else None
    )

    status_rows_today = [_status_text(row) for row in today_rows]
    skip_price_count = sum(1 for status in status_rows_today if status == "skip_price_outside_guardrails" or "skip_price" in status)
    order_failed_count = sum(1 for status in status_rows_today if status == "live_order_failed" or "order_failed" in status or status.endswith("_failed"))
    cancelled_unfilled_count = sum(
        1 for status in status_rows_today if status == "live_cancelled_unfilled" or "cancelled_unfilled" in status
    )

    best_direction_today = None
    best_price_bucket_today = None
    if today_live_filled:
        by_direction: dict[str, list[dict[str, Any]]] = {}
        by_bucket: dict[str, list[dict[str, Any]]] = {}
        for row in today_live_filled:
            direction = str(row.get("direction") or "UNKNOWN").strip().upper() or "UNKNOWN"
            bucket = _btc5_price_bucket(row.get("order_price"))
            by_direction.setdefault(direction, []).append(row)
            by_bucket.setdefault(bucket, []).append(row)

        def _rollup(label: str, group_rows: list[dict[str, Any]]) -> dict[str, Any]:
            fills = len(group_rows)
            pnl = round(sum(_safe_float(item.get("pnl_usd"), 0.0) for item in group_rows), 4)
            return {"label": label, "fills": fills, "pnl_usd": pnl}

        direction_rollups = [_rollup(label, group_rows) for label, group_rows in by_direction.items()]
        direction_rollups.sort(key=lambda item: (-item["pnl_usd"], -item["fills"], item["label"]))
        if direction_rollups:
            best_direction_today = direction_rollups[0]

        bucket_order = {"<0.49": 0, "0.49": 1, "0.50": 2, "0.51+": 3}
        bucket_rollups = [_rollup(label, group_rows) for label, group_rows in by_bucket.items()]
        bucket_rollups.sort(key=lambda item: (-item["pnl_usd"], -item["fills"], bucket_order.get(item["label"], 99)))
        if bucket_rollups:
            best_price_bucket_today = bucket_rollups[0]

    return {
        "filled_rows_today": filled_rows_today,
        "filled_pnl_usd_today": filled_pnl_usd_today,
        "estimated_maker_rebate_usd_today": estimated_maker_rebate_usd_today,
        "net_pnl_after_estimated_rebate_usd_today": round(
            filled_pnl_usd_today + estimated_maker_rebate_usd_today,
            4,
        ),
        "win_rate_today": win_rate_today,
        "recent_5_pnl_usd": _sum_recent(5),
        "recent_5_estimated_maker_rebate_usd": _sum_recent_rebate(5),
        "recent_5_net_pnl_after_estimated_rebate_usd": round(_sum_recent(5) + _sum_recent_rebate(5), 4),
        "recent_12_pnl_usd": _sum_recent(12),
        "recent_12_estimated_maker_rebate_usd": _sum_recent_rebate(12),
        "recent_12_net_pnl_after_estimated_rebate_usd": round(_sum_recent(12) + _sum_recent_rebate(12), 4),
        "recent_20_pnl_usd": _sum_recent(20),
        "recent_20_estimated_maker_rebate_usd": _sum_recent_rebate(20),
        "recent_20_net_pnl_after_estimated_rebate_usd": round(_sum_recent(20) + _sum_recent_rebate(20), 4),
        "skip_price_count": skip_price_count,
        "order_failed_count": order_failed_count,
        "cancelled_unfilled_count": cancelled_unfilled_count,
        "best_direction_today": best_direction_today,
        "best_price_bucket_today": best_price_bucket_today,
    }


def _load_polymarket_wallet_state(root: Path) -> dict[str, Any]:
    env = _parse_env_file(root / DEFAULT_ENV_PATH)
    ssh_key = env.get("LIGHTSAIL_KEY")
    vps_ip = env.get("VPS_IP")
    vps_user = env.get("VPS_USER", "ubuntu")
    checked_at = _now_iso()

    if not ssh_key or not vps_ip:
        local_env = dict(os.environ)
        local_env.update(env)
        local_env["PYTHONPATH"] = str(root) + ":" + str(root / "bot") + ":" + str(root / "polymarket-bot")
        try:
            result = subprocess.run(
                ["/usr/bin/python3", "-c", WALLET_PROBE_SCRIPT],
                cwd=root,
                env=local_env,
                capture_output=True,
                text=True,
                check=False,
                timeout=90,
            )
        except Exception as exc:
            return {
                "status": "unavailable",
                "checked_at": checked_at,
                "reason": f"local_wallet_probe_failed:{exc}",
            }
    else:
        remote_cmd = """cd __REMOTE_BOT_DIR__ && set -a && source .env >/dev/null 2>&1 && set +a && export PYTHONPATH=__REMOTE_PYTHONPATH__ && /usr/bin/python3 - <<'PY'
__WALLET_PROBE_SCRIPT__
PY""".replace("__REMOTE_BOT_DIR__", shlex.quote(REMOTE_BOT_DIR)).replace(
            "__REMOTE_PYTHONPATH__",
            shlex.quote(REMOTE_PYTHONPATH),
        ).replace("__WALLET_PROBE_SCRIPT__", WALLET_PROBE_SCRIPT)

        try:
            result = subprocess.run(
                [
                    "ssh",
                    "-i",
                    ssh_key,
                    "-o",
                    "StrictHostKeyChecking=no",
                    f"{vps_user}@{vps_ip}",
                    remote_cmd,
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=90,
            )
        except Exception as exc:
            return {
                "status": "unavailable",
                "checked_at": checked_at,
                "reason": f"remote_wallet_probe_failed:{exc}",
            }

    if result.returncode != 0:
        return {
            "status": "unavailable",
            "checked_at": checked_at,
            "reason": "remote_wallet_probe_failed",
            "stderr_tail": (result.stderr or "").strip()[-300:],
        }

    try:
        remote_payload = fast_loads((result.stdout or "").strip())
    except ValueError:
        return {
            "status": "unavailable",
            "checked_at": checked_at,
            "reason": "remote_wallet_probe_invalid_json",
            "stdout_tail": (result.stdout or "").strip()[-300:],
        }

    maker_address = str(remote_payload.get("maker_address") or "").strip()
    if not maker_address:
        return {
            "status": "unavailable",
            "checked_at": checked_at,
            "reason": "remote_wallet_probe_missing_maker_address",
        }

    warnings: list[str] = []
    positions: list[dict[str, Any]] = []
    closed_positions: list[dict[str, Any]] = []
    try:
        payload = _fetch_json_url(
            "https://data-api.polymarket.com/positions?"
            + urllib.parse.urlencode({"user": maker_address, "sizeThreshold": ".01"})
        )
        if isinstance(payload, list):
            positions = [item for item in payload if isinstance(item, dict)]
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        warnings.append(f"positions_fetch_failed:{exc}")

    try:
        closed_positions = _fetch_paginated_polymarket_endpoint(
            base_url="https://data-api.polymarket.com/closed-positions",
            params={"user": maker_address},
            limit=200,
            max_pages=20,
        )
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        warnings.append(f"closed_positions_fetch_failed:{exc}")

    initial_value = round(sum(_safe_float(item.get("initialValue"), 0.0) for item in positions), 4)
    current_value = round(sum(_safe_float(item.get("currentValue"), 0.0) for item in positions), 4)
    unrealized_pnl = round(sum(_safe_float(item.get("cashPnl"), 0.0) for item in positions), 4)
    realized_pnl = round(sum(_safe_float(item.get("realizedPnl"), 0.0) for item in closed_positions), 4)
    free_collateral = _micro_usdc_to_usd(remote_payload.get("free_collateral_usd"))
    reserved_order_usd = round(_safe_float(remote_payload.get("reserved_order_usd"), 0.0), 4)
    closed_batch_metrics = _wallet_closed_batch_metrics(
        open_positions=positions,
        closed_positions=closed_positions,
    )

    return {
        "status": "ok",
        "checked_at": checked_at,
        "maker_address": maker_address,
        "signature_type": remote_payload.get("signature_type"),
        "free_collateral_usd": free_collateral,
        "reserved_order_usd": reserved_order_usd,
        "live_orders_count": len(remote_payload.get("live_orders") or []),
        "live_orders": list(remote_payload.get("live_orders") or []),
        "open_positions_count": len(positions),
        "positions_initial_value_usd": initial_value,
        "positions_current_value_usd": current_value,
        "positions_unrealized_pnl_usd": unrealized_pnl,
        "closed_positions_count": len(closed_positions),
        "closed_positions_realized_pnl_usd": realized_pnl,
        "closed_batch_metrics": closed_batch_metrics,
        "total_wallet_value_usd": round(free_collateral + reserved_order_usd + current_value, 4),
        "warnings": warnings,
    }


def _load_wallet_reconciliation_fallback_wallet_state(
    *,
    root: Path,
    generated_at: datetime,
) -> dict[str, Any] | None:
    path = root / WALLET_RECONCILIATION_LATEST_PATH
    payload = _load_json(path, default={})
    if not isinstance(payload, dict) or not payload:
        return None

    summary = dict(payload.get("wallet_reconciliation_summary") or {})
    capital_summary = dict(payload.get("capital_attribution") or {})
    open_positions = payload.get("open_positions")
    closed_positions = payload.get("closed_positions")

    checked_at = _parse_datetime_like(
        _first_nonempty(
            summary.get("checked_at"),
            payload.get("generated_at"),
            _safe_iso_mtime(path),
        )
    )
    age_hours = _age_hours_from_datetimes(
        reference_at=generated_at,
        observed_at=checked_at,
    )
    if age_hours is None or age_hours > WALLET_RECONCILIATION_MAX_FALLBACK_AGE_HOURS:
        return None

    summary_status = str(
        _first_nonempty(summary.get("status"), payload.get("status"), "unknown")
    ).strip().lower()
    if not (
        bool(summary.get("stage_gate_ready"))
        or summary_status in {"ready_for_launch_gate", "reconciled", "ok"}
    ):
        return None

    open_count = _int_or_none(
        _first_nonempty(
            (open_positions or {}).get("count") if isinstance(open_positions, dict) else None,
            summary.get("open_positions_count"),
        )
    )
    closed_count = _int_or_none(
        _first_nonempty(
            (closed_positions or {}).get("count") if isinstance(closed_positions, dict) else None,
            summary.get("closed_positions_count"),
        )
    )
    if open_count is None:
        open_count = 0
    if closed_count is None:
        closed_count = 0

    free_collateral = round(_safe_float(capital_summary.get("free_collateral_usd"), 0.0), 4)
    reserved_order_usd = round(_safe_float(capital_summary.get("reserved_order_usd"), 0.0), 4)
    positions_initial_value = round(
        _safe_float(capital_summary.get("open_position_costs_usd"), 0.0),
        4,
    )
    positions_current_value = round(
        _safe_float(capital_summary.get("open_position_current_value_usd"), 0.0),
        4,
    )
    wallet_total = round(
        _safe_float(
            _first_nonempty(
                capital_summary.get("wallet_value_usd"),
                capital_summary.get("component_expected_total_usd"),
            ),
            0.0,
        ),
        4,
    )
    if wallet_total <= 0:
        wallet_total = round(free_collateral + reserved_order_usd + positions_current_value, 4)
    if positions_current_value <= 0 and wallet_total > 0:
        positions_current_value = round(
            max(0.0, wallet_total - free_collateral - reserved_order_usd),
            4,
        )
    positions_unrealized_pnl = round(positions_current_value - positions_initial_value, 4)

    closed_realized_pnl = 0.0
    if isinstance(closed_positions, dict):
        rows = closed_positions.get("rows")
        if isinstance(rows, list):
            closed_realized_pnl = round(
                sum(
                    _safe_float(row.get("realized_pnl_usd"), 0.0)
                    for row in rows
                    if isinstance(row, dict)
                ),
                4,
            )

    source_path = _relative_path_text(root, path) or str(path)
    return {
        "status": "ok",
        "checked_at": checked_at.isoformat() if checked_at is not None else payload.get("generated_at"),
        "maker_address": payload.get("user_address"),
        "signature_type": None,
        "free_collateral_usd": free_collateral,
        "reserved_order_usd": reserved_order_usd,
        "live_orders_count": 0,
        "live_orders": [],
        "open_positions_count": int(open_count),
        "positions_initial_value_usd": positions_initial_value,
        "positions_current_value_usd": positions_current_value,
        "positions_unrealized_pnl_usd": positions_unrealized_pnl,
        "closed_positions_count": int(closed_count),
        "closed_positions_realized_pnl_usd": closed_realized_pnl,
        "closed_batch_metrics": {},
        "total_wallet_value_usd": wallet_total,
        "warnings": [
            f"wallet_reconciliation_fallback:{source_path}",
        ],
        "source": "wallet_reconciliation_fallback",
        "source_path": source_path,
        "fallback_age_hours": round(age_hours, 4),
        "fallback_freshness": _freshness_label_for_age_hours(
            age_hours,
            stale_after_hours=WALLET_RECONCILIATION_MAX_FALLBACK_AGE_HOURS,
        ),
    }


def _merge_polymarket_wallet_observation(
    status: dict[str, Any],
    polymarket_wallet: dict[str, Any],
) -> None:
    status["polymarket_wallet"] = polymarket_wallet

    capital = status.setdefault("capital", {})
    runtime = status.setdefault("runtime", {})
    if polymarket_wallet.get("status") != "ok":
        return

    free_collateral = round(_safe_float(polymarket_wallet.get("free_collateral_usd"), 0.0), 4)
    reserved_order_usd = round(_safe_float(polymarket_wallet.get("reserved_order_usd"), 0.0), 4)
    positions_initial_value = round(
        _safe_float(polymarket_wallet.get("positions_initial_value_usd"), 0.0),
        4,
    )
    positions_current_value = round(
        _safe_float(polymarket_wallet.get("positions_current_value_usd"), 0.0),
        4,
    )
    positions_unrealized_pnl = round(
        _safe_float(polymarket_wallet.get("positions_unrealized_pnl_usd"), 0.0),
        4,
    )
    realized_pnl = round(
        _safe_float(polymarket_wallet.get("closed_positions_realized_pnl_usd"), 0.0),
        4,
    )
    observed_total = round(_safe_float(polymarket_wallet.get("total_wallet_value_usd"), 0.0), 4)
    observed_deployed = round(positions_initial_value + reserved_order_usd, 4)
    tracked_polymarket_capital = round(
        sum(
            _safe_float(item.get("amount_usd"), 0.0)
            for item in capital.get("sources") or []
            if str(item.get("account") or "").strip().lower() == "polymarket"
        ),
        4,
    )
    net_pnl = round(realized_pnl + positions_unrealized_pnl, 4)
    accounting_expected_total = round(tracked_polymarket_capital + net_pnl, 4)
    accounting_delta = round(observed_total - accounting_expected_total, 4)

    capital.update(
        {
            "polymarket_tracked_capital_usd": tracked_polymarket_capital,
            "polymarket_actual_deployable_usd": free_collateral,
            "polymarket_reserved_order_usd": reserved_order_usd,
            "polymarket_positions_initial_value_usd": positions_initial_value,
            "polymarket_positions_current_value_usd": positions_current_value,
            "polymarket_observed_deployed_usd": observed_deployed,
            "polymarket_observed_total_usd": observed_total,
            "polymarket_net_pnl_usd": net_pnl,
            "polymarket_accounting_expected_total_usd": accounting_expected_total,
            "polymarket_accounting_delta_usd": accounting_delta,
            "polymarket_tracked_vs_observed_delta_usd": round(
                tracked_polymarket_capital - observed_total,
                4,
            ),
        }
    )
    runtime.update(
        {
            "polymarket_wallet_checked_at": polymarket_wallet.get("checked_at"),
            "polymarket_live_orders": int(polymarket_wallet.get("live_orders_count") or 0),
            "polymarket_open_positions": int(polymarket_wallet.get("open_positions_count") or 0),
            "polymarket_positions_current_value_usd": positions_current_value,
            "polymarket_positions_unrealized_pnl_usd": positions_unrealized_pnl,
            "polymarket_closed_positions": int(
                polymarket_wallet.get("closed_positions_count") or 0
            ),
            "polymarket_closed_positions_realized_pnl_usd": realized_pnl,
            "polymarket_wallet_value_usd": observed_total,
        }
    )


def _apply_wallet_truth_reconciliation(
    status: dict[str, Any],
    polymarket_wallet: dict[str, Any],
) -> None:
    runtime = status.setdefault("runtime", {})
    capital = status.setdefault("capital", {})
    if polymarket_wallet.get("status") != "ok":
        return

    observed_open_positions = int(polymarket_wallet.get("open_positions_count") or 0)
    observed_closed_positions = int(polymarket_wallet.get("closed_positions_count") or 0)
    observed_total_wallet = round(
        _safe_float(polymarket_wallet.get("total_wallet_value_usd"), 0.0),
        4,
    )
    local_open_positions = int(runtime.get("open_positions") or 0)
    local_closed_trades = int(runtime.get("closed_trades") or 0)
    local_total_trades = int(runtime.get("trade_db_total_trades") or runtime.get("total_trades") or 0)
    local_bankroll = _safe_float(runtime.get("bankroll_usd"), 0.0)
    observed_deployed_capital = round(
        _safe_float(capital.get("polymarket_observed_deployed_usd"), 0.0),
        4,
    )

    # Treat fresh wallet truth as authoritative when the local ledger has fallen
    # behind and is reporting zero exposure or zero closed-trade history.
    if local_open_positions <= 0 and observed_open_positions > 0:
        runtime["open_positions"] = observed_open_positions
    if local_closed_trades <= 0 and observed_closed_positions > 0:
        runtime["closed_trades"] = observed_closed_positions
    if local_total_trades <= 0 and (observed_open_positions > 0 or observed_closed_positions > 0):
        runtime["trade_db_total_trades"] = observed_open_positions + observed_closed_positions
        runtime["total_trades"] = observed_open_positions + observed_closed_positions
    if local_bankroll <= 0:
        runtime["bankroll_usd"] = observed_total_wallet
    if _safe_float(capital.get("deployed_capital_usd"), 0.0) <= 0 and observed_deployed_capital > 0:
        capital["deployed_capital_usd"] = observed_deployed_capital
        tracked_capital = _safe_float(
            _first_nonempty(
                capital.get("tracked_capital_usd"),
                capital.get("polymarket_tracked_capital_usd"),
                observed_total_wallet,
            ),
            observed_total_wallet,
        )
        undeployed = max(0.0, tracked_capital - observed_deployed_capital)
        capital["undeployed_capital_usd"] = round(undeployed, 4)
    runtime.update(
        {
            "wallet_truth_open_positions": observed_open_positions,
            "wallet_truth_closed_trades": observed_closed_positions,
            "wallet_truth_wallet_value_usd": observed_total_wallet,
            "wallet_truth_applied_at": polymarket_wallet.get("checked_at"),
            "wallet_truth_applied": True,
        }
    )
    status["wallet_reconciliation_override"] = {
        "source": _first_nonempty(
            polymarket_wallet.get("source"),
            polymarket_wallet.get("source_path"),
            "polymarket_wallet",
        ),
        "updated_at": polymarket_wallet.get("checked_at"),
        "open_positions": observed_open_positions,
        "closed_trades": observed_closed_positions,
        "wallet_total_usd": observed_total_wallet,
        "active": True,
    }


def _resolve_authoritative_trade_totals(
    *,
    runtime: dict[str, Any],
    polymarket_wallet: dict[str, Any],
    btc5_maker: dict[str, Any],
) -> None:
    """Resolve runtime total_trades from the strongest available observations."""

    observed_counts: dict[str, int] = {
        "runtime.total_trades": int(runtime.get("total_trades") or 0),
        "runtime.trade_db_total_trades": int(runtime.get("trade_db_total_trades") or 0),
        "runtime.closed_plus_open": max(
            0,
            int(runtime.get("closed_trades") or 0) + int(runtime.get("open_positions") or 0),
        ),
        "runtime.btc5_live_filled_rows": int(runtime.get("btc5_live_filled_rows") or 0),
        "btc5_maker.live_filled_rows": int(btc5_maker.get("live_filled_rows") or 0),
    }
    if str(polymarket_wallet.get("status") or "").strip().lower() == "ok":
        observed_counts["wallet.open_plus_closed"] = max(
            0,
            int(polymarket_wallet.get("open_positions_count") or 0)
            + int(polymarket_wallet.get("closed_positions_count") or 0),
        )
    else:
        observed_counts["wallet.open_plus_closed"] = 0

    authoritative_total = max(observed_counts.values(), default=0)
    sources = sorted(
        source for source, value in observed_counts.items() if value == authoritative_total
    )
    source_text = "max_observed" if not sources else "max_observed:" + ",".join(sources)

    runtime["total_trades"] = authoritative_total
    runtime["total_trades_source"] = source_text
    runtime["total_trades_observations"] = observed_counts


def _materialize_remote_btc5_window_rows_cache(root: Path, payload: dict[str, Any]) -> None:
    rows = payload.get("recent_window_rows")
    if not isinstance(rows, list):
        return
    normalized_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        normalized = dict(row)
        normalized.setdefault("source", "remote_probe:ssh")
        normalized.setdefault("source_priority", 4)
        normalized_rows.append(normalized)
    if not normalized_rows:
        return
    normalized_rows.sort(
        key=lambda row: (
            int(_safe_float(row.get("id"), 0.0)),
            int(_safe_float(row.get("window_start_ts"), 0.0)),
        )
    )
    target = root / DEFAULT_BTC5_WINDOW_ROWS_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(normalized_rows, indent=2, sort_keys=True))


def _ensure_local_btc5_window_trades_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS window_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            window_start_ts INTEGER NOT NULL UNIQUE,
            window_end_ts INTEGER NOT NULL,
            slug TEXT NOT NULL,
            decision_ts INTEGER NOT NULL,
            direction TEXT,
            open_price REAL,
            current_price REAL,
            delta REAL,
            token_id TEXT,
            best_bid REAL,
            best_ask REAL,
            order_price REAL,
            trade_size_usd REAL,
            shares REAL,
            order_id TEXT,
            order_status TEXT NOT NULL,
            filled INTEGER,
            reason TEXT,
            decision_reason_tags TEXT,
            edge_tier TEXT,
            sizing_reason_tags TEXT,
            size_adjustment_tags TEXT,
            sizing_target_usd REAL,
            sizing_cap_usd REAL,
            loss_cluster_suppressed INTEGER,
            session_policy_name TEXT,
            effective_stage INTEGER,
            resolved_side TEXT,
            won INTEGER,
            pnl_usd REAL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_window_trades_decision_ts
            ON window_trades(decision_ts);
        """
    )
    existing = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(window_trades)").fetchall()
    }
    for column_name, column_type in (
        ("decision_reason_tags", "TEXT"),
        ("edge_tier", "TEXT"),
        ("sizing_reason_tags", "TEXT"),
        ("size_adjustment_tags", "TEXT"),
        ("sizing_target_usd", "REAL"),
        ("sizing_cap_usd", "REAL"),
        ("loss_cluster_suppressed", "INTEGER"),
        ("session_policy_name", "TEXT"),
        ("effective_stage", "INTEGER"),
    ):
        if column_name not in existing:
            conn.execute(f"ALTER TABLE window_trades ADD COLUMN {column_name} {column_type}")


def _remote_btc5_decision_ts(row: dict[str, Any]) -> int:
    for key in ("updated_at", "created_at"):
        parsed = _parse_datetime_like(row.get(key))
        if parsed is not None:
            return int(parsed.timestamp())
    return int(_safe_float(row.get("window_start_ts"), 0.0))


def _ensure_local_trade_ledger_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS trades (
            id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            market_id TEXT NOT NULL,
            question TEXT,
            direction TEXT,
            entry_price REAL,
            raw_prob REAL,
            calibrated_prob REAL,
            edge REAL,
            taker_fee REAL,
            position_size_usd REAL,
            kelly_fraction REAL,
            category TEXT,
            confidence REAL,
            reasoning TEXT,
            token_id TEXT,
            order_id TEXT,
            paper INTEGER DEFAULT 0,
            outcome TEXT,
            resolution_price REAL,
            pnl REAL,
            resolved_at TEXT,
            bankroll_level INTEGER DEFAULT 1000,
            source TEXT,
            source_combo TEXT,
            source_components_json TEXT,
            source_count INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS orders (
            order_id TEXT PRIMARY KEY,
            trade_id TEXT,
            timestamp TEXT NOT NULL,
            placed_at_epoch REAL NOT NULL,
            market_id TEXT NOT NULL,
            token_id TEXT,
            question TEXT,
            category TEXT,
            side TEXT,
            direction TEXT,
            price REAL,
            size REAL,
            size_usd REAL,
            order_type TEXT,
            status TEXT DEFAULT 'open',
            paper INTEGER DEFAULT 0,
            fill_count INTEGER DEFAULT 0,
            filled_size REAL DEFAULT 0.0,
            avg_fill_price REAL,
            first_fill_at TEXT,
            first_fill_latency_seconds REAL,
            last_fill_at TEXT,
            last_fill_latency_seconds REAL,
            last_size_matched REAL DEFAULT 0.0,
            last_seen_at TEXT,
            cancelled_at TEXT,
            cancel_reason TEXT,
            metadata_json TEXT DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS fills (
            id TEXT PRIMARY KEY,
            order_id TEXT NOT NULL,
            trade_id TEXT,
            timestamp TEXT NOT NULL,
            market_id TEXT NOT NULL,
            token_id TEXT,
            fill_price REAL NOT NULL,
            fill_size REAL NOT NULL,
            fill_size_usd REAL NOT NULL,
            latency_seconds REAL NOT NULL,
            cumulative_size_matched REAL,
            raw_json TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_trade_ledger_trades_timestamp ON trades(timestamp);
        CREATE INDEX IF NOT EXISTS idx_trade_ledger_orders_timestamp ON orders(timestamp);
        CREATE INDEX IF NOT EXISTS idx_trade_ledger_fills_timestamp ON fills(timestamp);
        """
    )


def _btc5_row_represents_fill(row: dict[str, Any]) -> bool:
    status = str(row.get("order_status") or "").strip().lower()
    trade_size_usd = _float_or_none(row.get("trade_size_usd")) or 0.0
    filled = _float_or_none(row.get("filled")) or 0.0
    return status in {"live_filled", "filled", "paper_filled"} or filled > 0.0 or trade_size_usd > 0.0


def _mirror_remote_btc5_rows_to_trade_ledger(root: Path, payload: dict[str, Any]) -> None:
    rows = payload.get("recent_window_rows")
    if not isinstance(rows, list):
        return
    db_path = root / DEFAULT_TRADES_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(str(db_path))
        _ensure_local_trade_ledger_schema(conn)
        for raw_row in rows:
            if not isinstance(raw_row, dict) or not _btc5_row_represents_fill(raw_row):
                continue

            window_start_ts = int(_safe_float(raw_row.get("window_start_ts"), 0.0))
            if window_start_ts <= 0:
                continue
            slug = str(raw_row.get("slug") or f"btc-updown-5m-{window_start_ts}").strip()
            market_id = slug or f"btc5-window-{window_start_ts}"
            timestamp = str(raw_row.get("updated_at") or raw_row.get("created_at") or _now_iso())
            placed_at = str(raw_row.get("created_at") or raw_row.get("updated_at") or timestamp)
            placed_at_dt = _parse_datetime_like(placed_at) or _parse_datetime_like(timestamp)
            fill_dt = _parse_datetime_like(timestamp) or placed_at_dt
            placed_at_epoch = (
                float(placed_at_dt.timestamp()) if placed_at_dt is not None else float(window_start_ts)
            )
            fill_timestamp = fill_dt.isoformat() if fill_dt is not None else timestamp
            fill_latency_seconds = 0.0
            if placed_at_dt is not None and fill_dt is not None:
                fill_latency_seconds = max((fill_dt - placed_at_dt).total_seconds(), 0.0)

            order_price = _float_or_none(
                _first_nonempty(
                    raw_row.get("order_price"),
                    raw_row.get("best_bid"),
                    raw_row.get("open_price"),
                    raw_row.get("current_price"),
                )
            )
            trade_size_usd = abs(_float_or_none(raw_row.get("trade_size_usd")) or 0.0)
            if trade_size_usd <= 0.0:
                continue
            shares = _float_or_none(raw_row.get("shares"))
            if (shares is None or shares <= 0.0) and order_price is not None and order_price > 0.0:
                shares = trade_size_usd / order_price
            fill_size = abs(shares or 0.0)
            if fill_size <= 0.0:
                fill_size = trade_size_usd
            fill_price = order_price if order_price is not None else 0.0

            raw_order_id = str(raw_row.get("order_id") or "").strip()
            order_id = raw_order_id or f"btc5-mirror-order-{window_start_ts}"
            trade_key = raw_order_id or str(window_start_ts)
            trade_id = f"btc5-mirror-trade-{trade_key}"
            fill_id = "btc5-mirror-fill-" + hashlib.sha1(
                f"{trade_key}:{fill_timestamp}:{trade_size_usd:.8f}".encode("utf-8")
            ).hexdigest()[:16]

            won_flag = raw_row.get("won")
            outcome = None
            resolution_price = None
            resolved_at = None
            if won_flag is not None:
                outcome = "won" if bool(int(won_flag)) else "lost"
                resolution_price = 1.0 if outcome == "won" else 0.0
                resolved_at = fill_timestamp

            direction = str(raw_row.get("direction") or "").strip() or None
            source = "polymarket_btc5_remote_mirror"
            source_components_json = json.dumps(["btc5_remote_mirror"], sort_keys=True)
            metadata_json = json.dumps(
                {
                    "lane_id": "maker_bootstrap_live",
                    "strategy_family": "btc5_maker_bootstrap",
                    "window_start_ts": window_start_ts,
                    "raw_row": raw_row,
                },
                sort_keys=True,
            )

            conn.execute(
                """
                INSERT INTO trades (
                    id, timestamp, market_id, question, direction, entry_price,
                    position_size_usd, category, token_id, order_id, paper,
                    outcome, resolution_price, pnl, resolved_at, bankroll_level,
                    source, source_combo, source_components_json, source_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    timestamp=excluded.timestamp,
                    market_id=excluded.market_id,
                    question=excluded.question,
                    direction=COALESCE(excluded.direction, trades.direction),
                    entry_price=COALESCE(excluded.entry_price, trades.entry_price),
                    position_size_usd=COALESCE(excluded.position_size_usd, trades.position_size_usd),
                    token_id=COALESCE(excluded.token_id, trades.token_id),
                    order_id=COALESCE(excluded.order_id, trades.order_id),
                    paper=excluded.paper,
                    outcome=COALESCE(excluded.outcome, trades.outcome),
                    resolution_price=COALESCE(excluded.resolution_price, trades.resolution_price),
                    pnl=COALESCE(excluded.pnl, trades.pnl),
                    resolved_at=COALESCE(excluded.resolved_at, trades.resolved_at),
                    source=COALESCE(excluded.source, trades.source),
                    source_combo=COALESCE(excluded.source_combo, trades.source_combo),
                    source_components_json=COALESCE(excluded.source_components_json, trades.source_components_json),
                    source_count=excluded.source_count
                """,
                (
                    trade_id,
                    fill_timestamp,
                    market_id,
                    slug,
                    direction,
                    order_price,
                    trade_size_usd,
                    "crypto",
                    raw_row.get("token_id"),
                    order_id,
                    0,
                    outcome,
                    resolution_price,
                    _float_or_none(raw_row.get("pnl_usd")),
                    resolved_at,
                    1000,
                    source,
                    source,
                    source_components_json,
                    1,
                ),
            )
            conn.execute(
                """
                INSERT INTO orders (
                    order_id, trade_id, timestamp, placed_at_epoch, market_id, token_id,
                    question, category, side, direction, price, size, size_usd, order_type,
                    status, paper, fill_count, filled_size, avg_fill_price, first_fill_at,
                    first_fill_latency_seconds, last_fill_at, last_fill_latency_seconds,
                    last_size_matched, last_seen_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(order_id) DO UPDATE SET
                    trade_id=COALESCE(excluded.trade_id, orders.trade_id),
                    timestamp=excluded.timestamp,
                    placed_at_epoch=excluded.placed_at_epoch,
                    market_id=excluded.market_id,
                    token_id=COALESCE(excluded.token_id, orders.token_id),
                    question=COALESCE(excluded.question, orders.question),
                    category=excluded.category,
                    side=excluded.side,
                    direction=COALESCE(excluded.direction, orders.direction),
                    price=COALESCE(excluded.price, orders.price),
                    size=COALESCE(excluded.size, orders.size),
                    size_usd=COALESCE(excluded.size_usd, orders.size_usd),
                    order_type=excluded.order_type,
                    status=excluded.status,
                    paper=excluded.paper,
                    fill_count=MAX(orders.fill_count, excluded.fill_count),
                    filled_size=MAX(COALESCE(orders.filled_size, 0.0), COALESCE(excluded.filled_size, 0.0)),
                    avg_fill_price=COALESCE(excluded.avg_fill_price, orders.avg_fill_price),
                    first_fill_at=COALESCE(orders.first_fill_at, excluded.first_fill_at),
                    first_fill_latency_seconds=COALESCE(orders.first_fill_latency_seconds, excluded.first_fill_latency_seconds),
                    last_fill_at=COALESCE(excluded.last_fill_at, orders.last_fill_at),
                    last_fill_latency_seconds=COALESCE(excluded.last_fill_latency_seconds, orders.last_fill_latency_seconds),
                    last_size_matched=MAX(COALESCE(orders.last_size_matched, 0.0), COALESCE(excluded.last_size_matched, 0.0)),
                    last_seen_at=excluded.last_seen_at,
                    metadata_json=excluded.metadata_json
                """,
                (
                    order_id,
                    trade_id,
                    placed_at,
                    placed_at_epoch,
                    market_id,
                    raw_row.get("token_id"),
                    slug,
                    "crypto",
                    "BUY",
                    direction,
                    order_price,
                    fill_size,
                    trade_size_usd,
                    "maker",
                    "filled",
                    0,
                    1,
                    fill_size,
                    fill_price if fill_price > 0.0 else order_price,
                    fill_timestamp,
                    fill_latency_seconds,
                    fill_timestamp,
                    fill_latency_seconds,
                    fill_size,
                    fill_timestamp,
                    metadata_json,
                ),
            )
            conn.execute(
                """
                INSERT INTO fills (
                    id, order_id, trade_id, timestamp, market_id, token_id, fill_price,
                    fill_size, fill_size_usd, latency_seconds, cumulative_size_matched, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    order_id=excluded.order_id,
                    trade_id=excluded.trade_id,
                    timestamp=excluded.timestamp,
                    market_id=excluded.market_id,
                    token_id=COALESCE(excluded.token_id, fills.token_id),
                    fill_price=excluded.fill_price,
                    fill_size=excluded.fill_size,
                    fill_size_usd=excluded.fill_size_usd,
                    latency_seconds=excluded.latency_seconds,
                    cumulative_size_matched=excluded.cumulative_size_matched,
                    raw_json=excluded.raw_json
                """,
                (
                    fill_id,
                    order_id,
                    trade_id,
                    fill_timestamp,
                    market_id,
                    raw_row.get("token_id"),
                    fill_price,
                    fill_size,
                    trade_size_usd,
                    fill_latency_seconds,
                    fill_size,
                    json.dumps(raw_row, sort_keys=True),
                ),
            )
        conn.commit()
    except sqlite3.DatabaseError:
        return
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _mirror_remote_btc5_rows_to_local_db(root: Path, payload: dict[str, Any]) -> None:
    rows = payload.get("recent_window_rows")
    if not isinstance(rows, list):
        return
    db_path = root / DEFAULT_BTC5_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(str(db_path))
        _ensure_local_btc5_window_trades_schema(conn)
        for raw_row in rows:
            if not isinstance(raw_row, dict):
                continue
            window_start_ts = int(_safe_float(raw_row.get("window_start_ts"), 0.0))
            if window_start_ts <= 0:
                continue
            created_at = str(raw_row.get("created_at") or raw_row.get("updated_at") or _now_iso())
            updated_at = str(raw_row.get("updated_at") or raw_row.get("created_at") or created_at)
            order_status = str(raw_row.get("order_status") or "unknown").strip() or "unknown"
            filled = raw_row.get("filled")
            if filled in ("", None) and order_status.lower() == "live_filled":
                filled = 1
            payload_row = {
                "window_start_ts": window_start_ts,
                "window_end_ts": window_start_ts + 300,
                "slug": str(raw_row.get("slug") or f"btc-updown-5m-{window_start_ts}"),
                "decision_ts": _remote_btc5_decision_ts(raw_row),
                "direction": raw_row.get("direction"),
                "delta": raw_row.get("delta"),
                "order_price": raw_row.get("order_price"),
                "trade_size_usd": raw_row.get("trade_size_usd"),
                "shares": raw_row.get("shares"),
                "order_status": order_status,
                "filled": filled,
                "pnl_usd": raw_row.get("pnl_usd"),
                "created_at": created_at,
                "updated_at": updated_at,
            }
            conn.execute(
                """
                INSERT INTO window_trades (
                    window_start_ts, window_end_ts, slug, decision_ts, direction,
                    delta, order_price, trade_size_usd, shares, order_status,
                    filled, pnl_usd, created_at, updated_at
                ) VALUES (
                    :window_start_ts, :window_end_ts, :slug, :decision_ts, :direction,
                    :delta, :order_price, :trade_size_usd, :shares, :order_status,
                    :filled, :pnl_usd, :created_at, :updated_at
                )
                ON CONFLICT(window_start_ts) DO UPDATE SET
                    window_end_ts=excluded.window_end_ts,
                    slug=excluded.slug,
                    decision_ts=excluded.decision_ts,
                    direction=COALESCE(excluded.direction, window_trades.direction),
                    delta=COALESCE(excluded.delta, window_trades.delta),
                    order_price=COALESCE(excluded.order_price, window_trades.order_price),
                    trade_size_usd=COALESCE(excluded.trade_size_usd, window_trades.trade_size_usd),
                    shares=COALESCE(excluded.shares, window_trades.shares),
                    order_status=excluded.order_status,
                    filled=COALESCE(excluded.filled, window_trades.filled),
                    pnl_usd=COALESCE(excluded.pnl_usd, window_trades.pnl_usd),
                    created_at=COALESCE(window_trades.created_at, excluded.created_at),
                    updated_at=excluded.updated_at
                """,
                payload_row,
            )
        conn.commit()
    except sqlite3.DatabaseError:
        return
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _load_btc5_maker_state(root: Path) -> dict[str, Any]:
    env = _parse_env_file(root / DEFAULT_ENV_PATH)
    ssh_key = env.get("LIGHTSAIL_KEY")
    vps_ip = env.get("VPS_IP")
    vps_user = env.get("VPS_USER", "ubuntu")
    checked_at = _now_iso()

    if ssh_key and vps_ip:
        remote_cmd = """cd __REMOTE_BOT_DIR__ && /usr/bin/python3 - <<'PY'
__BTC5_DB_PROBE_SCRIPT__
PY""".replace("__REMOTE_BOT_DIR__", shlex.quote(REMOTE_BOT_DIR)).replace(
            "__BTC5_DB_PROBE_SCRIPT__",
            BTC5_DB_PROBE_SCRIPT.replace("__CHECKED_AT__", checked_at),
        )
        try:
            result = subprocess.run(
                [
                    "ssh",
                    "-i",
                    ssh_key,
                    "-o",
                    "StrictHostKeyChecking=no",
                    f"{vps_user}@{vps_ip}",
                    remote_cmd,
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            if result.returncode == 0:
                payload = fast_loads(result.stdout.strip() or "{}")
                if isinstance(payload, dict):
                    payload.setdefault("source", "remote_sqlite_probe")
                    _materialize_remote_btc5_window_rows_cache(root, payload)
                    _mirror_remote_btc5_rows_to_local_db(root, payload)
                    _mirror_remote_btc5_rows_to_trade_ledger(root, payload)
                    return _normalize_btc5_maker_observation(payload)
        except Exception:
            pass

    return _normalize_btc5_maker_observation(
        _load_btc5_maker_state_from_db(root / DEFAULT_BTC5_DB_PATH, checked_at=checked_at)
    )


def _load_btc5_maker_state_from_db(
    db_path: Path,
    *,
    checked_at: str,
) -> dict[str, Any]:
    if not db_path.exists():
        return {
            "status": "unavailable",
            "checked_at": checked_at,
            "reason": "missing_data/btc_5min_maker.db",
        }

    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        summary_row = conn.execute(
            """
            SELECT
                COUNT(*) AS total_rows,
                SUM(CASE WHEN order_status = 'live_filled' THEN 1 ELSE 0 END) AS live_filled_rows,
                SUM(CASE WHEN order_status = 'live_filled' THEN pnl_usd ELSE 0 END) AS live_filled_pnl_usd,
                AVG(CASE WHEN order_status = 'live_filled' THEN pnl_usd END) AS avg_live_filled_pnl_usd,
                MAX(CASE WHEN order_status = 'live_filled' THEN updated_at END) AS latest_live_filled_at
            FROM window_trades
            """
        ).fetchone()
        latest_row = conn.execute(
            """
            SELECT
                id,
                window_start_ts,
                slug,
                direction,
                order_status,
                order_price,
                trade_size_usd,
                shares,
                pnl_usd,
                created_at,
                updated_at
            FROM window_trades
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        recent_live_filled = conn.execute(
            """
            SELECT
                id,
                window_start_ts,
                slug,
                direction,
                order_price,
                trade_size_usd,
                shares,
                pnl_usd,
                updated_at
            FROM window_trades
            WHERE order_status = 'live_filled'
            ORDER BY id DESC
            LIMIT 5
            """
        ).fetchall()
        all_live_filled = conn.execute(
            """
            SELECT
                id,
                direction,
                ABS(delta) AS abs_delta,
                order_price,
                trade_size_usd,
                shares,
                pnl_usd
            FROM window_trades
            WHERE order_status = 'live_filled'
            """
        ).fetchall()
        intraday_rows = conn.execute(
            """
            SELECT
                id,
                direction,
                order_price,
                trade_size_usd,
                shares,
                pnl_usd,
                order_status,
                won,
                created_at,
                updated_at
            FROM window_trades
            """
        ).fetchall()
    except sqlite3.DatabaseError as exc:
        return {
            "status": "unavailable",
            "checked_at": checked_at,
            "reason": f"btc5_db_error:{exc}",
        }
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass

    latest_summary = dict(latest_row) if latest_row is not None else {}
    recent_rows = [dict(row) for row in recent_live_filled]
    all_live_filled_rows = [dict(row) for row in all_live_filled]
    intraday_rows_all = [dict(row) for row in intraday_rows]
    guardrail_recommendation = _recommend_btc5_guardrails(all_live_filled_rows)
    fill_attribution = _summarize_btc5_fill_attribution(all_live_filled_rows)
    intraday_live_summary = _summarize_btc5_intraday_live(intraday_rows_all)
    estimated_maker_rebate_usd = round(
        sum(
            _estimate_btc5_maker_rebate_usd(
                order_price=row.get("order_price"),
                shares=row.get("shares"),
                trade_size_usd=row.get("trade_size_usd"),
            )
            for row in all_live_filled_rows
        ),
        4,
    )
    live_filled_pnl_usd = round(
        _safe_float(summary_row["live_filled_pnl_usd"] if summary_row is not None else 0.0),
        4,
    )
    avg_live_filled_pnl_usd = round(
        _safe_float(
            summary_row["avg_live_filled_pnl_usd"] if summary_row is not None else 0.0
        ),
        4,
    )
    latest_summary = _enrich_btc5_fill_row(latest_summary) if latest_summary else {}
    recent_rows = [_enrich_btc5_fill_row(row) for row in recent_rows]
    live_filled_rows_count = int((summary_row["live_filled_rows"] or 0) if summary_row is not None else 0)
    avg_estimated_maker_rebate_usd = round(
        estimated_maker_rebate_usd / live_filled_rows_count,
        4,
    ) if live_filled_rows_count > 0 else 0.0
    return {
        "status": "ok",
        "checked_at": checked_at,
        "db_path": str(db_path),
        "source": "local_sqlite_db",
        "total_rows": int((summary_row["total_rows"] or 0) if summary_row is not None else 0),
        "live_filled_rows": live_filled_rows_count,
        "live_filled_pnl_usd": live_filled_pnl_usd,
        "estimated_maker_rebate_usd": estimated_maker_rebate_usd,
        "net_pnl_after_estimated_rebate_usd": round(live_filled_pnl_usd + estimated_maker_rebate_usd, 4),
        "avg_live_filled_pnl_usd": avg_live_filled_pnl_usd,
        "avg_estimated_maker_rebate_usd": avg_estimated_maker_rebate_usd,
        "avg_net_pnl_after_estimated_rebate_usd": round(
            avg_live_filled_pnl_usd + avg_estimated_maker_rebate_usd,
            4,
        ),
        "latest_live_filled_at": (
            summary_row["latest_live_filled_at"] if summary_row is not None else None
        ),
        "latest_trade": latest_summary,
        "recent_live_filled": recent_rows,
        "guardrail_recommendation": guardrail_recommendation,
        "fill_attribution": fill_attribution,
        "intraday_live_summary": intraday_live_summary,
    }


def _normalize_btc5_maker_observation(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return payload
    normalized = dict(payload)
    latest_trade = normalized.get("latest_trade")
    if isinstance(latest_trade, dict) and latest_trade:
        normalized["latest_trade"] = _enrich_btc5_fill_row(latest_trade)
    recent_rows = [
        _enrich_btc5_fill_row(row)
        for row in list(normalized.get("recent_live_filled") or [])
        if isinstance(row, dict)
    ]
    if recent_rows:
        normalized["recent_live_filled"] = recent_rows
        fill_attribution = dict(normalized.get("fill_attribution") or {})
        recent_summary = fill_attribution.get("recent_live_filled_summary")
        if not isinstance(recent_summary, dict) or "estimated_maker_rebate_usd" not in recent_summary:
            fill_attribution["recent_live_filled_summary"] = _rollup_btc5_fill_group(
                recent_rows[:12],
                label="recent_12_live_filled",
            )
        recent_by_direction = fill_attribution.get("recent_live_filled_by_direction")
        if not isinstance(recent_by_direction, list) or any(
            not isinstance(item, dict) or "estimated_maker_rebate_usd" not in item for item in recent_by_direction
        ):
            grouped: dict[str, list[dict[str, Any]]] = {}
            for row in recent_rows[:12]:
                direction = str(row.get("direction") or "UNKNOWN").strip().upper() or "UNKNOWN"
                grouped.setdefault(direction, []).append(row)
            fill_attribution["recent_live_filled_by_direction"] = sorted(
                (_rollup_btc5_fill_group(group_rows, label=direction) for direction, group_rows in grouped.items()),
                key=lambda item: (-item["pnl_usd"], -item["fills"], item["label"]),
            )
        if fill_attribution:
            normalized["fill_attribution"] = fill_attribution
    return normalized


def _recommend_btc5_guardrails(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if len(rows) < 10:
        return None

    max_abs_delta_candidates = [0.00002, 0.00005, 0.00010, 0.00015]
    down_caps = [0.48, 0.49, 0.50, 0.51]
    up_caps = [0.47, 0.48, 0.49, 0.50, 0.51]
    baseline_pnl = round(sum(_safe_float(row.get("pnl_usd"), 0.0) for row in rows), 4)
    best: tuple[tuple[float, int, float, float], dict[str, Any]] | None = None

    for max_abs_delta in max_abs_delta_candidates:
        for down_cap in down_caps:
            for up_cap in up_caps:
                subset = [
                    row
                    for row in rows
                    if _safe_float(row.get("abs_delta"), 0.0) <= max_abs_delta
                    and (
                        (
                            str(row.get("direction") or "").strip().upper() == "DOWN"
                            and _safe_float(row.get("order_price"), 0.0) <= down_cap
                        )
                        or (
                            str(row.get("direction") or "").strip().upper() == "UP"
                            and _safe_float(row.get("order_price"), 0.0) <= up_cap
                        )
                    )
                ]
                if not subset:
                    continue
                pnl = round(sum(_safe_float(row.get("pnl_usd"), 0.0) for row in subset), 4)
                candidate = {
                    "max_abs_delta": max_abs_delta,
                    "down_max_buy_price": down_cap,
                    "up_max_buy_price": up_cap,
                    "replay_live_filled_rows": len(subset),
                    "replay_live_filled_pnl_usd": pnl,
                }
                score = (
                    pnl,
                    len(subset),
                    -abs(down_cap - 0.50),
                    -abs(up_cap - 0.51),
                )
                if best is None or score > best[0]:
                    best = (score, candidate)

    if best is None:
        return None

    return {
        **best[1],
        "baseline_live_filled_rows": len(rows),
        "baseline_live_filled_pnl_usd": baseline_pnl,
    }


def _merge_btc5_maker_observation(
    status: dict[str, Any],
    btc5_maker: dict[str, Any],
) -> None:
    status["btc_5min_maker"] = btc5_maker
    if btc5_maker.get("status") != "ok":
        return

    runtime = status.setdefault("runtime", {})
    latest_trade = btc5_maker.get("latest_trade") or {}
    fill_attribution = btc5_maker.get("fill_attribution") or {}
    intraday_summary = btc5_maker.get("intraday_live_summary") or {}
    recent_regime = fill_attribution.get("recent_direction_regime") or {}
    runtime.update(
        {
            "btc5_checked_at": btc5_maker.get("checked_at"),
            "btc5_source": btc5_maker.get("source"),
            "btc5_db_path": btc5_maker.get("db_path"),
            "btc5_total_rows": int(btc5_maker.get("total_rows") or 0),
            "btc5_live_filled_rows": int(btc5_maker.get("live_filled_rows") or 0),
            "btc5_live_filled_pnl_usd": round(
                _safe_float(btc5_maker.get("live_filled_pnl_usd"), 0.0),
                4,
            ),
            "btc5_estimated_maker_rebate_usd": round(
                _safe_float(btc5_maker.get("estimated_maker_rebate_usd"), 0.0),
                4,
            ),
            "btc5_net_pnl_after_estimated_rebate_usd": round(
                _safe_float(btc5_maker.get("net_pnl_after_estimated_rebate_usd"), 0.0),
                4,
            ),
            "btc5_avg_live_filled_pnl_usd": round(
                _safe_float(btc5_maker.get("avg_live_filled_pnl_usd"), 0.0),
                4,
            ),
            "btc5_latest_order_status": latest_trade.get("order_status"),
            "btc5_latest_window_start_ts": _int_or_none(latest_trade.get("window_start_ts")),
            "btc5_latest_trade_pnl_usd": _float_or_none(latest_trade.get("pnl_usd")),
            "btc5_latest_trade_estimated_maker_rebate_usd": _float_or_none(
                latest_trade.get("estimated_maker_rebate_usd")
            ),
            "btc5_latest_trade_net_pnl_after_estimated_rebate_usd": _float_or_none(
                latest_trade.get("net_pnl_after_estimated_rebate_usd")
            ),
            "btc5_guardrail_recommendation": btc5_maker.get("guardrail_recommendation"),
            "btc5_best_direction": (fill_attribution.get("best_direction") or {}).get("label"),
            "btc5_best_direction_pnl_usd": _float_or_none(
                (fill_attribution.get("best_direction") or {}).get("pnl_usd")
            ),
            "btc5_best_price_bucket": (fill_attribution.get("best_price_bucket") or {}).get("label"),
            "btc5_best_price_bucket_pnl_usd": _float_or_none(
                (fill_attribution.get("best_price_bucket") or {}).get("pnl_usd")
            ),
            "btc5_recent_live_filled_pnl_usd": _float_or_none(
                (fill_attribution.get("recent_live_filled_summary") or {}).get("pnl_usd")
            ),
            "btc5_recent_live_filled_estimated_maker_rebate_usd": _float_or_none(
                (fill_attribution.get("recent_live_filled_summary") or {}).get("estimated_maker_rebate_usd")
            ),
            "btc5_recent_live_filled_net_pnl_after_estimated_rebate_usd": _float_or_none(
                (fill_attribution.get("recent_live_filled_summary") or {}).get("net_pnl_after_estimated_rebate_usd")
            ),
            "btc5_recent_live_filled_rows": _int_or_none(
                (fill_attribution.get("recent_live_filled_summary") or {}).get("fills")
            ),
            "btc5_recent_regime_triggered": bool(recent_regime.get("triggered")),
            "btc5_recent_regime_favored_direction": recent_regime.get("favored_direction"),
            "btc5_recent_regime_weaker_direction": recent_regime.get("weaker_direction"),
            "btc5_recent_regime_pnl_gap_usd": _float_or_none(recent_regime.get("pnl_gap_usd")),
            "btc5_intraday_live_summary": intraday_summary,
        }
    )


def _refresh_remote_observation_cadence(
    status: dict[str, Any],
    *,
    service: dict[str, Any],
    polymarket_wallet: dict[str, Any],
    btc5_maker: dict[str, Any],
) -> None:
    cadence = status.setdefault("data_cadence", {})
    runtime = status.setdefault("runtime", {})

    freshest_candidates: list[tuple[str, datetime]] = []
    baseline = _parse_datetime_like(
        runtime.get("last_remote_pull_at") or cadence.get("last_remote_pull_at")
    )
    if baseline is not None:
        freshest_candidates.append(("intel_snapshot", baseline))

    service_checked_at = _parse_datetime_like(service.get("checked_at"))
    if service_checked_at is not None and service.get("status") in {"running", "stopped"}:
        freshest_candidates.append(("service_probe", service_checked_at))

    wallet_checked_at = _parse_datetime_like(polymarket_wallet.get("checked_at"))
    if wallet_checked_at is not None and polymarket_wallet.get("status") == "ok":
        freshest_candidates.append(("polymarket_wallet_probe", wallet_checked_at))

    btc5_checked_at = _parse_datetime_like(btc5_maker.get("checked_at"))
    if btc5_checked_at is not None and btc5_maker.get("status") == "ok":
        freshest_candidates.append(("btc5_maker_probe", btc5_checked_at))

    if not freshest_candidates:
        return

    freshest_timestamp = max(timestamp for _, timestamp in freshest_candidates)
    freshest_sources = [
        source for source, timestamp in freshest_candidates if timestamp == freshest_timestamp
    ]

    freshness_sla_minutes = int(cadence.get("freshness_sla_minutes") or 45)
    pull_cadence_minutes = int(cadence.get("pull_cadence_minutes") or 30)
    full_cycle_cadence_minutes = int(cadence.get("full_cycle_cadence_minutes") or 60)
    data_age_minutes = round(
        max(0.0, (datetime.now(timezone.utc) - freshest_timestamp).total_seconds()) / 60.0,
        1,
    )
    freshest_iso = freshest_timestamp.isoformat()

    runtime["last_remote_pull_at"] = freshest_iso
    cadence.update(
        {
            "pull_cadence_minutes": pull_cadence_minutes,
            "full_cycle_cadence_minutes": full_cycle_cadence_minutes,
            "freshness_sla_minutes": freshness_sla_minutes,
            "last_remote_pull_at": freshest_iso,
            "next_expected_pull_at": (
                freshest_timestamp + timedelta(minutes=pull_cadence_minutes)
            ).isoformat(),
            "data_age_minutes": data_age_minutes,
            "stale": bool(data_age_minutes > freshness_sla_minutes),
            "freshness_basis": "remote_observation",
            "freshness_sources": freshest_sources,
        }
    )


def _source_freshness_confidence(
    *,
    checked_at: Any,
    source_status: str,
    source_path: str | None = None,
    warning_count: int = 0,
) -> dict[str, Any]:
    checked = _parse_datetime_like(checked_at)
    age_minutes = (
        round(max(0.0, (datetime.now(timezone.utc) - checked).total_seconds()) / 60.0, 1)
        if checked is not None
        else None
    )
    freshness = "unknown"
    if age_minutes is not None:
        if age_minutes <= 45.0:
            freshness = "fresh"
        elif age_minutes <= 180.0:
            freshness = "aging"
        else:
            freshness = "stale"

    confidence_score = 0.2
    confidence_label = "low"
    if source_status == "ok":
        confidence_score = 0.9
        confidence_label = "high"
        if warning_count > 0:
            confidence_score = max(0.55, confidence_score - (0.1 * min(warning_count, 3)))
            confidence_label = "medium" if confidence_score < 0.85 else "high"
        if freshness == "aging":
            confidence_score = max(0.5, confidence_score - 0.15)
            confidence_label = "medium"
        elif freshness == "stale":
            confidence_score = max(0.35, confidence_score - 0.3)
            confidence_label = "low"
    elif source_status in {"missing", "unavailable", "error"}:
        confidence_score = 0.1
        confidence_label = "low"

    return {
        "checked_at": checked.isoformat() if checked is not None else None,
        "age_minutes": age_minutes,
        "freshness": freshness,
        "confidence_score": round(confidence_score, 2),
        "confidence_label": confidence_label,
        "status": source_status,
        "source_path": source_path,
    }


def _build_accounting_reconciliation(status: dict[str, Any], *, root: Path) -> dict[str, Any]:
    runtime = status.get("runtime", {})
    capital = status.get("capital", {})
    polymarket_wallet = status.get("polymarket_wallet", {})
    btc5_maker = status.get("btc_5min_maker", {})
    wallet_reconciliation_override = status.get("wallet_reconciliation_override") or {}
    reconcile_with_wallet_truth = bool(wallet_reconciliation_override.get("active"))

    local_total_trades = int(runtime.get("trade_db_total_trades") or 0)
    local_closed_positions = int(runtime.get("closed_trades") or 0)
    local_open_positions = int(runtime.get("open_positions") or 0)

    wallet_status = str(polymarket_wallet.get("status") or "unavailable").strip().lower()
    remote_wallet_source = str(
        _first_nonempty(
            polymarket_wallet.get("source_path"),
            polymarket_wallet.get("source"),
            "remote CLOB + Polymarket data API",
        )
    )
    remote_open_positions = int(polymarket_wallet.get("open_positions_count") or 0)
    remote_closed_positions = int(polymarket_wallet.get("closed_positions_count") or 0)
    wallet_live_orders = int(polymarket_wallet.get("live_orders_count") or 0)

    btc5_status = str(btc5_maker.get("status") or "unavailable").strip().lower()
    btc5_live_filled_rows = int(btc5_maker.get("live_filled_rows") or 0)
    btc5_total_rows = int(btc5_maker.get("total_rows") or 0)

    open_delta = remote_open_positions - local_open_positions
    closed_delta = remote_closed_positions - local_closed_positions
    if reconcile_with_wallet_truth:
        accounting_delta_usd = 0.0
    else:
        accounting_delta_usd = round(
            _safe_float(capital.get("polymarket_accounting_delta_usd"), 0.0),
            4,
        )
    drift_reasons: list[str] = []
    if wallet_status != "ok":
        drift_reasons.append(
            f"remote_wallet_unavailable:{polymarket_wallet.get('reason') or 'unknown'}"
        )
    if open_delta != 0:
        drift_reasons.append(
            f"open_positions_mismatch: local={local_open_positions} remote={remote_open_positions} delta={open_delta:+d}"
        )
    if closed_delta != 0:
        drift_reasons.append(
            f"closed_positions_mismatch: local={local_closed_positions} remote={remote_closed_positions} delta={closed_delta:+d}"
        )
    if abs(accounting_delta_usd) >= 5.0:
        drift_reasons.append(
            f"capital_accounting_delta_usd={accounting_delta_usd:+.2f}"
        )

    local_trade_db_path = root / DEFAULT_TRADES_DB_PATH
    local_trade_db_checked_at = _safe_iso_mtime(local_trade_db_path)
    local_ledger_freshness = _source_freshness_confidence(
        checked_at=local_trade_db_checked_at or status.get("generated_at"),
        source_status=(
            "ok"
            if str(runtime.get("trade_db_source") or "").strip().lower() == "data/jj_trades.db"
            else "missing"
        ),
        source_path=_relative_path_text(root, local_trade_db_path),
    )
    remote_wallet_freshness = _source_freshness_confidence(
        checked_at=polymarket_wallet.get("checked_at"),
        source_status=wallet_status,
        source_path=remote_wallet_source,
        warning_count=len(polymarket_wallet.get("warnings") or []),
    )
    btc5_freshness = _source_freshness_confidence(
        checked_at=btc5_maker.get("checked_at"),
        source_status=btc5_status,
        source_path=(
            str(btc5_maker.get("source") or btc5_maker.get("db_path") or DEFAULT_BTC5_DB_PATH)
        ),
    )

    drift_detected = bool(drift_reasons)
    return {
        "status": (
            "drift_detected"
            if drift_detected
            else ("reconciled" if wallet_status == "ok" else "remote_wallet_unavailable")
        ),
        "drift_detected": drift_detected,
        "drift_reasons": drift_reasons,
        "local_ledger_counts": {
            "source": runtime.get("trade_db_source") or "unknown",
            "total_trades": local_total_trades,
            "open_positions": local_open_positions,
            "closed_positions": local_closed_positions,
        },
        "remote_wallet_counts": {
            "status": wallet_status,
            "source": remote_wallet_source,
            "open_positions": remote_open_positions,
            "closed_positions": remote_closed_positions,
            "live_orders": wallet_live_orders,
            "free_collateral_usd": _float_or_none(polymarket_wallet.get("free_collateral_usd")),
            "reserved_order_usd": _float_or_none(polymarket_wallet.get("reserved_order_usd")),
            "total_wallet_value_usd": _float_or_none(polymarket_wallet.get("total_wallet_value_usd")),
        },
        "btc_5min_maker_counts": {
            "status": btc5_status,
            "source": btc5_maker.get("source") or btc5_maker.get("db_path"),
            "total_rows": btc5_total_rows,
            "live_filled_rows": btc5_live_filled_rows,
            "live_filled_pnl_usd": _float_or_none(btc5_maker.get("live_filled_pnl_usd")),
            "latest_live_filled_at": btc5_maker.get("latest_live_filled_at"),
        },
        "unmatched_open_positions": {
            "local_ledger": local_open_positions,
            "remote_wallet": remote_open_positions,
            "delta_remote_minus_local": open_delta,
            "absolute_delta": abs(open_delta),
            "direction": (
                "remote_excess"
                if open_delta > 0
                else ("local_excess" if open_delta < 0 else "matched")
            ),
        },
        "unmatched_closed_positions": {
            "local_ledger": local_closed_positions,
            "remote_wallet": remote_closed_positions,
            "delta_remote_minus_local": closed_delta,
            "absolute_delta": abs(closed_delta),
            "direction": (
                "remote_excess"
                if closed_delta > 0
                else ("local_excess" if closed_delta < 0 else "matched")
            ),
        },
        "capital_accounting_delta_usd": accounting_delta_usd,
        "source_confidence_freshness": {
            "local_ledger": local_ledger_freshness,
            "remote_wallet": remote_wallet_freshness,
            "btc_5min_maker": btc5_freshness,
        },
    }


def build_remote_cycle_status(
    root: Path,
    *,
    config_path: Path | None = None,
    service_status_path: Path | None = None,
    root_test_status_path: Path | None = None,
    arb_status_path: Path | None = None,
) -> dict[str, Any]:
    """Build an enriched status payload from synced runtime artifacts."""

    repo_root = root.resolve()
    compatibility_aliases = _materialize_required_compatibility_aliases(repo_root)
    status = build_base_remote_cycle_status(repo_root, config_path=config_path or DEFAULT_CONFIG_PATH)
    status["compatibility_aliases"] = compatibility_aliases
    jj_state = _load_json(repo_root / "jj_state.json", default={})
    intel_snapshot = _load_json(repo_root / "data" / "intel_snapshot.json", default={})

    trade_counts = _load_trade_counts(repo_root)
    status["runtime"]["closed_trades"] = trade_counts["closed_trades"]
    status["runtime"]["trade_db_total_trades"] = trade_counts["total_trades"]
    status["runtime"]["trade_db_source"] = trade_counts["source"]

    service = _load_service_status(
        _resolve_path(repo_root, service_status_path or DEFAULT_SERVICE_STATUS_PATH)
    )
    root_test_status_target = _resolve_path(
        repo_root,
        root_test_status_path or DEFAULT_ROOT_TEST_STATUS_PATH,
    )
    if root_test_status_target == repo_root / DEFAULT_ROOT_TEST_STATUS_PATH:
        resolved = _resolve_compatibility_alias_path(
            repo_root,
            "root_test_status.json",
            materialize=False,
        )
        if resolved.exists():
            root_test_status_target = resolved
    root_tests = _load_root_test_status(root_test_status_target)
    deploy_evidence = _load_latest_deploy_evidence(repo_root)
    wallet_flow = _load_wallet_flow_status(repo_root)
    polymarket_wallet = _load_polymarket_wallet_state(repo_root)
    status_generated_at = _parse_datetime_like(status.get("generated_at")) or datetime.now(timezone.utc)
    wallet_fallback = _load_wallet_reconciliation_fallback_wallet_state(
        root=repo_root,
        generated_at=status_generated_at,
    )
    if str(polymarket_wallet.get("status") or "").strip().lower() != "ok" and wallet_fallback is not None:
        probe_reason = str(polymarket_wallet.get("reason") or "").strip()
        fallback_warnings = [
            str(item).strip()
            for item in list(wallet_fallback.get("warnings") or [])
            if str(item).strip()
        ]
        if probe_reason:
            fallback_warnings.append(f"remote_wallet_probe_unavailable:{probe_reason}")
        wallet_fallback["warnings"] = _dedupe_preserve_order(fallback_warnings)
        wallet_fallback["probe_status"] = polymarket_wallet.get("status")
        wallet_fallback["probe_reason"] = probe_reason or None
        polymarket_wallet = wallet_fallback
        status["wallet_reconciliation_fallback"] = {
            "active": True,
            "source_path": wallet_fallback.get("source_path"),
            "checked_at": wallet_fallback.get("checked_at"),
            "age_hours": wallet_fallback.get("fallback_age_hours"),
            "freshness": wallet_fallback.get("fallback_freshness"),
            "probe_reason": probe_reason or polymarket_wallet.get("reason"),
        }
    else:
        status["wallet_reconciliation_fallback"] = {"active": False}
    btc5_maker = _load_btc5_maker_state(repo_root)
    _merge_polymarket_wallet_observation(status, polymarket_wallet)
    _apply_wallet_truth_reconciliation(status, polymarket_wallet)
    _merge_btc5_maker_observation(status, btc5_maker)
    _resolve_authoritative_trade_totals(
        runtime=status["runtime"],
        polymarket_wallet=polymarket_wallet,
        btc5_maker=btc5_maker,
    )
    accounting_reconciliation = _build_accounting_reconciliation(status, root=repo_root)
    status["accounting_reconciliation"] = accounting_reconciliation
    _refresh_remote_observation_cadence(
        status,
        service=service,
        polymarket_wallet=polymarket_wallet,
        btc5_maker=btc5_maker,
    )

    arb_status_target = _resolve_path(repo_root, arb_status_path or DEFAULT_ARB_STATUS_PATH)
    if arb_status_target == repo_root / DEFAULT_ARB_STATUS_PATH:
        resolved = _resolve_compatibility_alias_path(
            repo_root,
            "arb_empirical_snapshot.json",
            materialize=False,
        )
        if resolved.exists():
            arb_status_target = resolved
    arb_payload = _load_arb_status_with_fallback(
        repo_root,
        arb_status_target,
    )
    a6_gate = _build_a6_gate_status(arb_payload)
    b1_gate = _build_b1_gate_status(arb_payload, jj_state=jj_state)

    launch = _build_launch_status(
        status=status,
        service=service,
        root_tests=root_tests,
        wallet_flow=wallet_flow,
        a6_gate=a6_gate,
        b1_gate=b1_gate,
        accounting_reconciliation=accounting_reconciliation,
        deploy_evidence=deploy_evidence,
    )
    runtime_truth = _build_runtime_truth(
        status=status,
        jj_state=jj_state,
        intel_snapshot=intel_snapshot,
        service=service,
        launch=launch,
        accounting_reconciliation=accounting_reconciliation,
    )
    generated_at = _parse_datetime_like(status.get("generated_at")) or datetime.now(timezone.utc)
    public_scoreboard = _build_public_performance_scoreboard(
        root=repo_root,
        generated_at=generated_at,
        capital=status["capital"],
        btc5_maker=btc5_maker,
        polymarket_wallet=polymarket_wallet,
        accounting_reconciliation=accounting_reconciliation,
    )
    wallet_reconciliation_summary = dict(
        public_scoreboard.get("wallet_reconciliation_summary") or {}
    )
    scale_summary = _load_strategy_scale_comparison_summary(
        root=repo_root,
        generated_at=generated_at,
    )
    audit_summary = _load_signal_source_audit_summary(
        root=repo_root,
        generated_at=generated_at,
    )
    current_probe_summary = _load_btc5_current_probe_summary(
        root=repo_root,
        generated_at=generated_at,
    )
    selected_package_summary = _load_btc5_selected_package_summary(
        root=repo_root,
        generated_at=generated_at,
    )
    fast_market_search = _summarize_fast_market_search(
        repo_root,
        repo_root / DEFAULT_FAST_MARKET_SEARCH_LATEST_PATH,
    )
    finance_gate = _load_finance_gate_summary(
        root=repo_root,
        generated_at=generated_at,
    )
    source_precedence = _build_source_precedence(
        root=repo_root,
        generated_at=generated_at,
        service=service,
        polymarket_wallet=polymarket_wallet,
        btc5_maker=btc5_maker,
        accounting_reconciliation=accounting_reconciliation,
        wallet_reconciliation_summary=wallet_reconciliation_summary,
    )
    btc5_stage_readiness = _build_btc5_stage_readiness(
        scale_summary=scale_summary,
        audit_summary=audit_summary,
        current_probe_summary=current_probe_summary,
    )
    deployment_confidence = _build_deployment_confidence(
        service=service,
        accounting_reconciliation=accounting_reconciliation,
        btc5_stage_readiness=btc5_stage_readiness,
        source_precedence=source_precedence,
        scale_summary=scale_summary,
        audit_summary=audit_summary,
        wallet_reconciliation_summary=wallet_reconciliation_summary,
        current_probe_summary=current_probe_summary,
        selected_package_summary=selected_package_summary,
    )
    if isinstance(deployment_confidence, dict):
        btc5_stage_readiness = dict(btc5_stage_readiness)
        deployment_can_trade_now = bool(deployment_confidence.get("can_btc5_trade_now"))
        btc5_stage_readiness.update(
            {
                "deployment_can_trade_now": deployment_can_trade_now,
                "deployment_trade_now_status": (
                    "unblocked" if deployment_can_trade_now else "blocked"
                ),
                "deployment_trade_now_blocking_checks": _dedupe_preserve_order(
                    list(deployment_confidence.get("stage_1_blockers") or [])
                ),
            }
        )
        if not deployment_can_trade_now:
            btc5_stage_readiness["deployment_trade_now_reasons"] = [
                str(
                    deployment_confidence.get("trade_now_reason")
                    or "BTC5 deployment confidence is blocking stage_1 live progression."
                )
            ]
            if not btc5_stage_readiness["deployment_trade_now_blocking_checks"]:
                btc5_stage_readiness["deployment_trade_now_blocking_checks"] = [
                    "deployment_confidence_not_ready"
                ]
    runtime_truth.update(
        {
            "can_btc5_trade_now": bool(deployment_confidence.get("can_btc5_trade_now")),
            "allowed_stage": int(btc5_stage_readiness.get("allowed_stage") or 0),
            "allowed_stage_label": btc5_stage_readiness.get("allowed_stage_label"),
            "deployment_confidence_label": deployment_confidence.get("confidence_label"),
        }
    )
    champion_lane_contract = _build_champion_lane_contract(
        generated_at=generated_at,
        fast_market_search=fast_market_search,
        deployment_confidence=deployment_confidence,
        selected_package_summary=selected_package_summary,
        finance_gate=finance_gate,
    )

    status["service"] = service
    status["root_tests"] = root_tests
    status["wallet_flow"] = wallet_flow
    status["polymarket_wallet"] = polymarket_wallet
    status["btc_5min_maker"] = btc5_maker
    status["btc5_stage_readiness"] = btc5_stage_readiness
    selected_package_summary = _enforce_canonical_live_package(selected_package_summary)
    status["btc5_selected_package"] = selected_package_summary
    status["attribution"] = build_trade_attribution_contract(
        root=repo_root,
        btc5_maker=btc5_maker,
        selected_package_summary=selected_package_summary,
        service_name=str(service.get("service_name") or PRIMARY_RUNTIME_SERVICE_NAME),
    )
    status["trade_confirmation"] = _build_btc5_trade_confirmation(
        btc5_maker=btc5_maker,
        selected_package_summary=selected_package_summary,
        service_name=str(service.get("service_name") or PRIMARY_RUNTIME_SERVICE_NAME),
        now=generated_at,
    )
    status["trade_proof"] = _build_btc5_trade_proof(
        attribution=dict(status.get("attribution") or {}),
        trade_confirmation=dict(status.get("trade_confirmation") or {}),
        now=generated_at,
    )
    status["deployment_confidence"] = deployment_confidence
    status["fast_market_search"] = fast_market_search
    status["finance_gate"] = finance_gate
    status["champion_lane_contract"] = champion_lane_contract
    status["deploy_evidence"] = deploy_evidence
    status["source_precedence"] = source_precedence
    status["structural_gates"] = {"a6": a6_gate, "b1": b1_gate}
    status["launch"] = launch
    status["runtime_truth"] = runtime_truth
    state_permissions = dict(runtime_truth.get("state_permissions") or {})
    operator_verdict = dict(runtime_truth.get("operator_verdict") or {})
    if status.get("baseline_live_allowed") is None:
        status["baseline_live_allowed"] = bool(
            state_permissions.get("baseline_live_allowed")
            if state_permissions.get("baseline_live_allowed") is not None
            else operator_verdict.get("baseline_live_allowed")
        )
    if status.get("stage_upgrade_allowed") is None:
        status["stage_upgrade_allowed"] = bool(
            state_permissions.get("stage_upgrade_allowed")
            if state_permissions.get("stage_upgrade_allowed") is not None
            else operator_verdict.get("stage_upgrade_allowed")
        )
    if status.get("capital_expansion_allowed") is None:
        status["capital_expansion_allowed"] = bool(
            state_permissions.get("capital_expansion_allowed")
            if state_permissions.get("capital_expansion_allowed") is not None
            else operator_verdict.get("capital_expansion_allowed")
        )
    if status.get("btc5_baseline_live_allowed") is None:
        status["btc5_baseline_live_allowed"] = bool(status.get("baseline_live_allowed"))
    if status.get("btc5_stage_upgrade_can_trade_now") is None:
        status["btc5_stage_upgrade_can_trade_now"] = bool(
            status.get("stage_upgrade_allowed")
        )
    if status.get("can_btc5_trade_now") is None:
        status["can_btc5_trade_now"] = bool(status.get("baseline_live_allowed"))
    status["deployment_finish"] = _reconcile_deployment_finish(
        status.get("deployment_finish") or {},
        service=service,
        launch=launch,
    )
    status["artifacts"] = {
        "launch_checklist": str(_resolve_path(repo_root, DEFAULT_LAUNCH_CHECKLIST_PATH)),
        "service_status_json": str(
            _resolve_path(repo_root, service_status_path or DEFAULT_SERVICE_STATUS_PATH)
        ),
        "root_test_status_json": str(
            _resolve_path(repo_root, root_test_status_path or DEFAULT_ROOT_TEST_STATUS_PATH)
        ),
        "arb_status_json": str(_resolve_path(repo_root, arb_status_path or DEFAULT_ARB_STATUS_PATH)),
    }
    return status


def render_remote_cycle_status_markdown(status: dict[str, Any]) -> str:
    return _render_remote_cycle_status_markdown_impl(status)


def write_remote_cycle_status(
    root: Path,
    *,
    markdown_path: Path | None = None,
    json_path: Path | None = None,
    runtime_truth_latest_path: Path | None = None,
    public_runtime_snapshot_path: Path | None = None,
    launch_packet_latest_path: Path | None = None,
    state_improvement_latest_path: Path | None = None,
    state_improvement_digest_path: Path | None = None,
    config_path: Path | None = None,
    service_status_path: Path | None = None,
    root_test_status_path: Path | None = None,
    arb_status_path: Path | None = None,
    refresh_root_tests: bool = False,
    root_test_command: Sequence[str] = DEFAULT_ROOT_TEST_COMMAND,
    root_test_timeout_seconds: int = 900,
) -> dict[str, Any]:
    """Write markdown and JSON status artifacts to disk."""

    repo_root = root.resolve()
    runtime_profile_refresh = _prepare_local_runtime_profile_evidence(repo_root)
    root_test_status_target = _resolve_path(
        repo_root,
        root_test_status_path or DEFAULT_ROOT_TEST_STATUS_PATH,
    )
    if refresh_root_tests:
        refresh_root_test_status(
            repo_root,
            status_path=root_test_status_target,
            command=root_test_command,
            timeout_seconds=root_test_timeout_seconds,
        )

    status = build_remote_cycle_status(
        repo_root,
        config_path=config_path or DEFAULT_CONFIG_PATH,
        service_status_path=service_status_path or DEFAULT_SERVICE_STATUS_PATH,
        root_test_status_path=root_test_status_target,
        arb_status_path=arb_status_path or DEFAULT_ARB_STATUS_PATH,
    )

    markdown_target = _resolve_path(repo_root, markdown_path or DEFAULT_MARKDOWN_PATH)
    json_target = _resolve_path(repo_root, json_path or DEFAULT_JSON_PATH)
    runtime_truth_latest_target = _resolve_path(
        repo_root,
        runtime_truth_latest_path or DEFAULT_RUNTIME_TRUTH_LATEST_PATH,
    )
    public_runtime_snapshot_target = _resolve_path(
        repo_root,
        public_runtime_snapshot_path or DEFAULT_PUBLIC_RUNTIME_SNAPSHOT_PATH,
    )
    trade_proof_latest_target = _resolve_path(
        repo_root,
        DEFAULT_TRADE_PROOF_LATEST_PATH,
    )
    launch_packet_latest_target = _resolve_path(
        repo_root,
        launch_packet_latest_path or DEFAULT_LAUNCH_PACKET_LATEST_PATH,
    )
    state_improvement_latest_target = _resolve_path(
        repo_root,
        state_improvement_latest_path or DEFAULT_STATE_IMPROVEMENT_LATEST_PATH,
    )
    state_improvement_digest_target = _resolve_path(
        repo_root,
        state_improvement_digest_path or DEFAULT_STATE_IMPROVEMENT_DIGEST_PATH,
    )
    timestamp_suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    runtime_truth_timestamped_target = (
        repo_root / DEFAULT_RUNTIME_TRUTH_HISTORY_DIR / f"runtime_truth_{timestamp_suffix}.json"
    )
    runtime_mode_reconciliation_target = (
        repo_root
        / DEFAULT_RUNTIME_MODE_RECONCILIATION_HISTORY_DIR
        / f"runtime_mode_reconciliation_{timestamp_suffix}.md"
    )
    launch_packet_timestamped_target = (
        repo_root / DEFAULT_LAUNCH_PACKET_HISTORY_DIR / f"launch_packet_{timestamp_suffix}.json"
    )
    state_improvement_timestamped_target = (
        repo_root / DEFAULT_STATE_IMPROVEMENT_HISTORY_DIR / f"state_improvement_{timestamp_suffix}.json"
    )
    previous_runtime_truth_snapshot = _load_json(runtime_truth_latest_target, default={})

    status.setdefault("artifacts", {}).update(
        {
            "remote_cycle_status_markdown": str(markdown_target),
            "remote_cycle_status_json": str(json_target),
            "runtime_truth_latest_json": str(runtime_truth_latest_target),
            "runtime_truth_timestamped_json": str(runtime_truth_timestamped_target),
            "public_runtime_snapshot_json": str(public_runtime_snapshot_target),
            "trade_proof_latest_json": str(trade_proof_latest_target),
            "launch_packet_latest_json": str(launch_packet_latest_target),
            "launch_packet_timestamped_json": str(launch_packet_timestamped_target),
            "state_improvement_latest_json": str(state_improvement_latest_target),
            "state_improvement_timestamped_json": str(state_improvement_timestamped_target),
            "state_improvement_digest_markdown": str(state_improvement_digest_target),
            "runtime_mode_reconciliation_markdown": str(runtime_mode_reconciliation_target),
        }
    )

    latest_edge_scan_path = _find_latest_report_path(repo_root, "edge_scan_*.json")
    latest_pipeline_path = _find_latest_report_path(repo_root, "pipeline_*.json")
    if latest_edge_scan_path is not None:
        status["artifacts"]["latest_edge_scan_json"] = str(latest_edge_scan_path)
    if latest_pipeline_path is not None:
        status["artifacts"]["latest_pipeline_json"] = str(latest_pipeline_path)

    runtime_truth_snapshot = build_runtime_truth_snapshot(
        repo_root,
        status=status,
        remote_cycle_status_path=json_target,
        service_status_path=_resolve_path(repo_root, service_status_path or DEFAULT_SERVICE_STATUS_PATH),
        root_test_status_path=root_test_status_target,
        latest_edge_scan_path=latest_edge_scan_path,
        latest_pipeline_path=latest_pipeline_path,
        runtime_truth_latest_path=runtime_truth_latest_target,
        runtime_truth_timestamped_path=runtime_truth_timestamped_target,
        public_runtime_snapshot_path=public_runtime_snapshot_target,
        previous_runtime_truth_snapshot=(
            previous_runtime_truth_snapshot
            if isinstance(previous_runtime_truth_snapshot, dict)
            else {}
        ),
    )
    runtime_truth_snapshot["attribution"] = dict(status.get("attribution") or {})
    runtime_truth_snapshot["trade_confirmation"] = dict(status.get("trade_confirmation") or {})
    runtime_truth_snapshot["trade_proof"] = dict(status.get("trade_proof") or {})
    runtime_mode_reconciliation = build_runtime_mode_reconciliation(
        repo_root,
        status=status,
        runtime_truth_snapshot=runtime_truth_snapshot,
        runtime_profile_refresh=runtime_profile_refresh,
        runtime_mode_reconciliation_path=runtime_mode_reconciliation_target,
    )
    runtime_truth_snapshot = apply_runtime_mode_reconciliation(
        runtime_truth_snapshot,
        root=repo_root,
        runtime_mode_reconciliation=runtime_mode_reconciliation,
        runtime_mode_reconciliation_path=runtime_mode_reconciliation_target,
    )
    status = apply_runtime_mode_reconciliation_to_status(
        status,
        runtime_mode_reconciliation=runtime_mode_reconciliation,
    )
    launch_packet = build_canonical_launch_packet(
        root=repo_root,
        runtime_truth_snapshot=runtime_truth_snapshot,
    )
    runtime_truth_snapshot = apply_canonical_launch_packet(
        runtime_truth_snapshot,
        root=repo_root,
        launch_packet=launch_packet,
        launch_packet_latest_path=launch_packet_latest_target,
        launch_packet_timestamped_path=launch_packet_timestamped_target,
    )
    status = apply_canonical_launch_packet_to_status(
        status,
        launch_packet=launch_packet,
    )
    state_improvement = dict(runtime_truth_snapshot.get("state_improvement") or {})
    state_improvement.setdefault("artifact", "state_improvement_report")
    state_improvement.setdefault("schema_version", 1)
    state_improvement.setdefault("generated_at", runtime_truth_snapshot.get("generated_at"))
    state_improvement = _hydrate_state_improvement_from_launch_contract(
        state_improvement,
        launch_packet=launch_packet,
        runtime_truth_snapshot=runtime_truth_snapshot,
    )
    runtime_truth_snapshot["state_improvement"] = state_improvement
    runtime_truth_snapshot = _apply_shared_truth_contract(runtime_truth_snapshot)
    status = _apply_shared_truth_contract_to_status(
        status,
        runtime_truth_snapshot=runtime_truth_snapshot,
    )
    launch_packet = build_canonical_launch_packet(
        root=repo_root,
        runtime_truth_snapshot=runtime_truth_snapshot,
    )
    runtime_truth_snapshot = apply_canonical_launch_packet(
        runtime_truth_snapshot,
        root=repo_root,
        launch_packet=launch_packet,
        launch_packet_latest_path=launch_packet_latest_target,
        launch_packet_timestamped_path=launch_packet_timestamped_target,
    )
    status = apply_canonical_launch_packet_to_status(
        status,
        launch_packet=launch_packet,
    )
    state_improvement = dict(runtime_truth_snapshot.get("state_improvement") or {})
    state_improvement.setdefault("artifact", "state_improvement_report")
    state_improvement.setdefault("schema_version", 1)
    state_improvement.setdefault("generated_at", runtime_truth_snapshot.get("generated_at"))
    state_improvement = _hydrate_state_improvement_from_launch_contract(
        state_improvement,
        launch_packet=launch_packet,
        runtime_truth_snapshot=runtime_truth_snapshot,
    )
    runtime_truth_snapshot["state_improvement"] = state_improvement
    runtime_truth_snapshot = _apply_shared_truth_contract(runtime_truth_snapshot)
    status = _apply_shared_truth_contract_to_status(
        status,
        runtime_truth_snapshot=runtime_truth_snapshot,
    )
    # Final canonical sync: shared-truth normalization can mutate next-action/profile
    # fields, so re-derive and re-apply the launch packet before writing artifacts.
    launch_packet = build_canonical_launch_packet(
        root=repo_root,
        runtime_truth_snapshot=runtime_truth_snapshot,
    )
    runtime_truth_snapshot = apply_canonical_launch_packet(
        runtime_truth_snapshot,
        root=repo_root,
        launch_packet=launch_packet,
        launch_packet_latest_path=launch_packet_latest_target,
        launch_packet_timestamped_path=launch_packet_timestamped_target,
    )
    status = apply_canonical_launch_packet_to_status(
        status,
        launch_packet=launch_packet,
    )
    status = _apply_shared_truth_contract_to_status(
        status,
        runtime_truth_snapshot=runtime_truth_snapshot,
    )
    status["attribution"] = dict(
        runtime_truth_snapshot.get("attribution") or status.get("attribution") or {}
    )
    status["trade_confirmation"] = dict(runtime_truth_snapshot.get("trade_confirmation") or status.get("trade_confirmation") or {})
    status["trade_proof"] = dict(
        runtime_truth_snapshot.get("trade_proof") or status.get("trade_proof") or {}
    )
    status.setdefault("runtime_truth", {})["attribution"] = dict(
        runtime_truth_snapshot.get("attribution") or {}
    )
    status.setdefault("runtime_truth", {})["trade_confirmation"] = dict(
        runtime_truth_snapshot.get("trade_confirmation") or {}
    )
    status.setdefault("runtime_truth", {})["trade_proof"] = dict(
        runtime_truth_snapshot.get("trade_proof") or {}
    )
    public_runtime_snapshot = build_public_runtime_snapshot(runtime_truth_snapshot)

    markdown_target.parent.mkdir(parents=True, exist_ok=True)
    json_target.parent.mkdir(parents=True, exist_ok=True)
    runtime_truth_latest_target.parent.mkdir(parents=True, exist_ok=True)
    public_runtime_snapshot_target.parent.mkdir(parents=True, exist_ok=True)
    trade_proof_latest_target.parent.mkdir(parents=True, exist_ok=True)
    launch_packet_latest_target.parent.mkdir(parents=True, exist_ok=True)
    state_improvement_latest_target.parent.mkdir(parents=True, exist_ok=True)
    state_improvement_digest_target.parent.mkdir(parents=True, exist_ok=True)
    runtime_mode_reconciliation_target.parent.mkdir(parents=True, exist_ok=True)

    markdown_target.write_text(render_remote_cycle_status_markdown(status))
    dump_path_atomic(json_target, status, indent=2, sort_keys=True, trailing_newline=False)
    dump_path_atomic(
        runtime_truth_timestamped_target,
        runtime_truth_snapshot,
        indent=2,
        sort_keys=True,
        trailing_newline=False,
    )
    dump_path_atomic(
        runtime_truth_latest_target,
        runtime_truth_snapshot,
        indent=2,
        sort_keys=True,
        trailing_newline=False,
    )
    dump_path_atomic(
        public_runtime_snapshot_target,
        public_runtime_snapshot,
        indent=2,
        sort_keys=True,
        trailing_newline=False,
    )
    dump_path_atomic(
        trade_proof_latest_target,
        runtime_truth_snapshot.get("trade_proof") or {},
        indent=2,
        sort_keys=True,
        trailing_newline=False,
    )
    dump_path_atomic(
        launch_packet_timestamped_target,
        launch_packet,
        indent=2,
        sort_keys=True,
        trailing_newline=False,
    )
    dump_path_atomic(
        launch_packet_latest_target,
        launch_packet,
        indent=2,
        sort_keys=True,
        trailing_newline=False,
    )
    dump_path_atomic(
        state_improvement_timestamped_target,
        state_improvement,
        indent=2,
        sort_keys=True,
        trailing_newline=False,
    )
    dump_path_atomic(
        state_improvement_latest_target,
        state_improvement,
        indent=2,
        sort_keys=True,
        trailing_newline=False,
    )
    state_improvement_digest_target.write_text(
        _render_state_improvement_digest_markdown(state_improvement)
    )
    runtime_mode_reconciliation_target.write_text(
        render_runtime_mode_reconciliation_markdown(runtime_mode_reconciliation)
    )

    return {
        "markdown": str(markdown_target),
        "json": str(json_target),
        "runtime_truth_latest": str(runtime_truth_latest_target),
        "runtime_truth_timestamped": str(runtime_truth_timestamped_target),
        "runtime_mode_reconciliation_markdown": str(runtime_mode_reconciliation_target),
        "public_runtime_snapshot": str(public_runtime_snapshot_target),
        "trade_proof_latest": str(trade_proof_latest_target),
        "launch_packet_latest": str(launch_packet_latest_target),
        "launch_packet_timestamped": str(launch_packet_timestamped_target),
        "state_improvement_latest": str(state_improvement_latest_target),
        "state_improvement_timestamped": str(state_improvement_timestamped_target),
        "state_improvement_digest": str(state_improvement_digest_target),
        "status": status,
    }


def _prepare_local_runtime_profile_evidence(root: Path) -> dict[str, Any]:
    local_env = _parse_env_file(root / DEFAULT_ENV_PATH)
    env_example = _parse_env_file(root / DEFAULT_ENV_EXAMPLE_PATH)
    capital_stage_env = _parse_env_file(root / BTC5_CAPITAL_STAGE_ENV_PATH)
    autoresearch_env = _parse_env_file(root / BTC5_AUTORESEARCH_ENV_PATH)
    operator_overrides = _parse_env_file(root / DEFAULT_RUNTIME_OPERATOR_OVERRIDES_PATH)
    if not operator_overrides:
        operator_overrides = _parse_env_file(root / LEGACY_RUNTIME_OPERATOR_OVERRIDES_PATH)
    effective_path = root / DEFAULT_RUNTIME_PROFILE_EFFECTIVE_PATH
    existing_effective = _load_json(effective_path, default={})
    if not existing_effective:
        existing_effective = _load_json(root / LEGACY_RUNTIME_PROFILE_EFFECTIVE_PATH, default={})

    normalized_stage_env = dict(capital_stage_env)
    stage_paper_trading = (
        capital_stage_env.get("PAPER_TRADING")
        or capital_stage_env.get("BTC5_PAPER_TRADING")
    )
    if stage_paper_trading is not None:
        normalized_stage_env["PAPER_TRADING"] = str(stage_paper_trading)

    selected_profile = (
        normalized_stage_env.get("JJ_RUNTIME_PROFILE")
        or local_env.get("JJ_RUNTIME_PROFILE")
        or env_example.get("JJ_RUNTIME_PROFILE")
        or "blocked_safe"
    )
    merged_env = {
        "JJ_RUNTIME_PROFILE": selected_profile,
        **local_env,
        **operator_overrides,
        **normalized_stage_env,
        **autoresearch_env,
    }
    bundle = load_runtime_profile_bundle(env=merged_env)

    expected_payload = _profile_contract_payload(bundle.config)
    existing_payload = _profile_contract_payload(existing_effective)
    stale_fields = _mapping_diff(existing_payload, expected_payload)
    refreshed = bool(local_env or operator_overrides)
    if refreshed:
        write_runtime_profile_bundle(
            bundle,
            output_path=effective_path,
        )
        existing_effective = _load_json(effective_path, default={})
        if existing_effective:
            dump_path_atomic(
                root / LEGACY_RUNTIME_PROFILE_EFFECTIVE_PATH,
                existing_effective,
                indent=2,
                sort_keys=True,
                trailing_newline=False,
            )

    return {
        "bundle": bundle,
        "effective_path": effective_path,
        "existing_effective": existing_effective,
        "env_example": env_example,
        "local_env": local_env,
        "capital_stage_env": capital_stage_env,
        "autoresearch_env": autoresearch_env,
        "operator_overrides": operator_overrides,
        "merged_env": merged_env,
        "refreshed": refreshed,
        "stale_before_refresh": bool(stale_fields),
        "stale_before_refresh_fields": stale_fields,
    }


def build_runtime_mode_reconciliation(
    root: Path,
    *,
    status: dict[str, Any],
    runtime_truth_snapshot: dict[str, Any],
    runtime_profile_refresh: dict[str, Any],
    runtime_mode_reconciliation_path: Path,
) -> dict[str, Any]:
    bundle = runtime_profile_refresh["bundle"]
    selected_profile = str(bundle.selected_profile or "blocked_safe").strip() or "blocked_safe"
    effective_config = dict(bundle.config)
    effective_mode = dict(effective_config.get("mode") or {})
    effective_flags = dict(effective_config.get("feature_flags") or {})
    risk_limits = dict(effective_config.get("risk_limits") or {})
    signal_thresholds = dict(effective_config.get("signal_thresholds") or {})
    market_filters = dict(effective_config.get("market_filters") or {})
    applied_overrides = list(bundle.profile.applied_overrides)
    override_env_by_field = {
        f"{override.section}.{override.key}": override.env_var
        for override in applied_overrides
    }
    base_bundle = load_runtime_profile_bundle(env={"JJ_RUNTIME_PROFILE": selected_profile})
    base_config = dict(base_bundle.config)
    base_risk_limits = dict(base_config.get("risk_limits") or {})
    base_signal_thresholds = dict(base_config.get("signal_thresholds") or {})
    base_market_filters = dict(base_config.get("market_filters") or {})

    deploy_evidence = _load_latest_deploy_evidence(root)
    remote_values = dict(deploy_evidence.get("remote_values") or {})
    launch = dict(status.get("launch") or {})
    safe_baseline_profile = str(launch.get("safe_baseline_profile") or "blocked_safe").strip() or "blocked_safe"
    safe_baseline_reason = str(launch.get("safe_baseline_reason") or "unknown").strip() or "unknown"
    remote_runtime_profile = (
        remote_values.get("JJ_RUNTIME_PROFILE")
        or deploy_evidence.get("remote_runtime_profile")
        or selected_profile
    )
    remote_mode_bundle = load_runtime_profile_bundle(
        env={"JJ_RUNTIME_PROFILE": str(remote_runtime_profile or selected_profile)}
    )
    remote_mode_config = dict(remote_mode_bundle.config)
    remote_mode = dict(remote_mode_config.get("mode") or {})
    inferred_agent_run_mode = str(
        remote_mode.get("effective_execution_mode")
        or remote_mode.get("execution_mode")
        or ""
    ).strip()
    agent_run_mode = (
        remote_values.get("ELASTIFUND_AGENT_RUN_MODE")
        or deploy_evidence.get("agent_run_mode")
        or "unknown"
    )
    if agent_run_mode == "unknown" and inferred_agent_run_mode:
        agent_run_mode = inferred_agent_run_mode
    remote_paper_trading = _bool_or_none(
        remote_values.get("PAPER_TRADING") or deploy_evidence.get("paper_trading")
    )
    if remote_paper_trading is None:
        remote_paper_trading = _bool_or_none(remote_mode.get("paper_trading"))
    force_live_attempt_requested = _bool_or_none(
        runtime_profile_refresh["merged_env"].get("JJ_FORCE_LIVE_ATTEMPT")
    ) or _bool_or_none(deploy_evidence.get("remote_values", {}).get("JJ_FORCE_LIVE_ATTEMPT"))
    force_live_attempt_requested = bool(force_live_attempt_requested)
    service_state = str(
        deploy_evidence.get("service_state")
        or status.get("service", {}).get("status")
        or "unknown"
    ).strip()
    process_state = str(deploy_evidence.get("process_state") or "unknown").strip()
    remote_agent_mode_from_env = str(
        remote_values.get("ELASTIFUND_AGENT_RUN_MODE") or ""
    ).strip().lower()
    remote_execution_mode = str(
        remote_mode.get("effective_execution_mode")
        or remote_mode.get("execution_mode")
        or ""
    ).strip().lower()
    remote_mode_authoritative = bool(
        service_state == "running"
        and str(remote_runtime_profile or "").strip()
        and remote_agent_mode_from_env in {"live", "micro_live"}
        and remote_execution_mode in {"live", "micro_live"}
    )
    launch_live_blocked = bool(status.get("launch", {}).get("live_launch_blocked"))
    launch_blocked_checks = {
        str(item).strip()
        for item in list((status.get("launch") or {}).get("blocked_checks") or [])
        if str(item).strip()
    }
    finance_gate = dict(runtime_truth_snapshot.get("finance_gate") or {})
    finance_gate_status = _build_finance_gate_status(root=root)
    finance_gate_pass = _bool_or_none(finance_gate.get("finance_gate_pass"))
    if finance_gate_pass is None:
        finance_gate_pass = str(finance_gate_status.get("status") or "").strip().lower() == "pass"
    selected_package_summary = dict(runtime_truth_snapshot.get("btc5_selected_package") or {})
    bounded_restart_advisory_checks = {"no_closed_trades", "finance_gate_blocked"}
    bounded_stage1_live_override = bool(
        service_state == "running"
        and bool(finance_gate_pass)
        and (
            bool(selected_package_summary.get("stage1_live_candidate"))
            or remote_mode_authoritative
        )
        and launch_blocked_checks.issubset(bounded_restart_advisory_checks)
    )
    if bounded_stage1_live_override:
        launch_live_blocked = False

    neutralized_overrides: list[dict[str, Any]] = []
    if force_live_attempt_requested:
        neutralized_overrides.append(
            {
                "env_var": "JJ_FORCE_LIVE_ATTEMPT",
                "field": "mode.force_live_attempt",
                "before": True,
                "after": False,
                "reason": "forced_live_attempt_neutralized",
            }
        )

    def _mark_widened_override(
        *,
        field: str,
        effective_value: Any,
        base_value: Any,
        widened: bool,
        reason: str,
    ) -> None:
        env_var = override_env_by_field.get(field)
        if not env_var or not widened:
            return
        neutralized_overrides.append(
            {
                "env_var": env_var,
                "field": field,
                "before": effective_value,
                "after": base_value,
                "reason": reason,
            }
        )

    _mark_widened_override(
        field="risk_limits.max_position_usd",
        effective_value=_float_or_none(risk_limits.get("max_position_usd")),
        base_value=_float_or_none(base_risk_limits.get("max_position_usd")),
        widened=(
            _float_or_none(risk_limits.get("max_position_usd")) is not None
            and _float_or_none(base_risk_limits.get("max_position_usd")) is not None
            and _float_or_none(risk_limits.get("max_position_usd"))
            > _float_or_none(base_risk_limits.get("max_position_usd"))
        ),
        reason="widened_position_cap_neutralized",
    )
    _mark_widened_override(
        field="risk_limits.max_open_positions",
        effective_value=_int_or_none(risk_limits.get("max_open_positions")),
        base_value=_int_or_none(base_risk_limits.get("max_open_positions")),
        widened=(
            _int_or_none(risk_limits.get("max_open_positions")) is not None
            and _int_or_none(base_risk_limits.get("max_open_positions")) is not None
            and _int_or_none(risk_limits.get("max_open_positions"))
            > _int_or_none(base_risk_limits.get("max_open_positions"))
        ),
        reason="widened_open_position_cap_neutralized",
    )
    _mark_widened_override(
        field="market_filters.max_resolution_hours",
        effective_value=_float_or_none(market_filters.get("max_resolution_hours")),
        base_value=_float_or_none(base_market_filters.get("max_resolution_hours")),
        widened=(
            _float_or_none(market_filters.get("max_resolution_hours")) is not None
            and _float_or_none(base_market_filters.get("max_resolution_hours")) is not None
            and _float_or_none(market_filters.get("max_resolution_hours"))
            > _float_or_none(base_market_filters.get("max_resolution_hours"))
        ),
        reason="widened_resolution_horizon_neutralized",
    )
    _mark_widened_override(
        field="signal_thresholds.yes_threshold",
        effective_value=_float_or_none(signal_thresholds.get("yes_threshold")),
        base_value=_float_or_none(base_signal_thresholds.get("yes_threshold")),
        widened=(
            _float_or_none(signal_thresholds.get("yes_threshold")) is not None
            and _float_or_none(base_signal_thresholds.get("yes_threshold")) is not None
            and _float_or_none(signal_thresholds.get("yes_threshold"))
            < _float_or_none(base_signal_thresholds.get("yes_threshold"))
        ),
        reason="widened_yes_threshold_neutralized",
    )
    _mark_widened_override(
        field="signal_thresholds.no_threshold",
        effective_value=_float_or_none(signal_thresholds.get("no_threshold")),
        base_value=_float_or_none(base_signal_thresholds.get("no_threshold")),
        widened=(
            _float_or_none(signal_thresholds.get("no_threshold")) is not None
            and _float_or_none(base_signal_thresholds.get("no_threshold")) is not None
            and _float_or_none(signal_thresholds.get("no_threshold"))
            < _float_or_none(base_signal_thresholds.get("no_threshold"))
        ),
        reason="widened_no_threshold_neutralized",
    )

    safe_baseline_profile = str(launch.get("safe_baseline_profile") or "blocked_safe").strip() or "blocked_safe"
    safe_baseline_reason = str(launch.get("safe_baseline_reason") or "unknown").strip() or "unknown"
    launch_guard_reasons: list[str] = []
    guarded_mode = dict(effective_mode)
    guarded_flags = dict(effective_flags)
    guarded_risk_limits = dict(risk_limits)
    guarded_signal_thresholds = dict(signal_thresholds)
    guarded_market_filters = dict(market_filters)
    effective_runtime_profile = selected_profile
    if remote_mode_authoritative:
        guarded_mode = dict(remote_mode)
        guarded_flags = dict(remote_mode_config.get("feature_flags") or {})
        guarded_risk_limits = dict(remote_mode_config.get("risk_limits") or {})
        guarded_signal_thresholds = dict(remote_mode_config.get("signal_thresholds") or {})
        guarded_market_filters = dict(remote_mode_config.get("market_filters") or {})
        effective_runtime_profile = str(remote_runtime_profile or selected_profile).strip() or selected_profile
        launch_guard_reasons.append("remote_runtime_profile_authoritative_while_service_running")

    invalid_service_launch_combo = (
        service_state == "running"
        and launch_live_blocked
        and bool(guarded_mode.get("allow_order_submission"))
    )
    safe_baseline_required = invalid_service_launch_combo

    safe_bundle: Any = None
    if safe_baseline_required:
        safe_bundle = load_runtime_profile_bundle(env={"JJ_RUNTIME_PROFILE": safe_baseline_profile})
        safe_config = dict(safe_bundle.config)
        guarded_mode = dict(safe_config.get("mode") or {})
        guarded_flags = dict(safe_config.get("feature_flags") or {})
        guarded_risk_limits = dict(safe_config.get("risk_limits") or {})
        guarded_signal_thresholds = dict(safe_config.get("signal_thresholds") or {})
        guarded_market_filters = dict(safe_config.get("market_filters") or {})
        effective_runtime_profile = safe_baseline_profile
        launch_guard_reasons.append(
            "invalid_running_blocked_allow_order_submission_combo_locked_to_safe_baseline"
        )
    elif neutralized_overrides:
        for item in neutralized_overrides:
            field = str(item.get("field") or "")
            if field == "risk_limits.max_position_usd":
                guarded_risk_limits["max_position_usd"] = item.get("after")
            elif field == "risk_limits.max_open_positions":
                guarded_risk_limits["max_open_positions"] = item.get("after")
            elif field == "market_filters.max_resolution_hours":
                guarded_market_filters["max_resolution_hours"] = item.get("after")
            elif field == "signal_thresholds.yes_threshold":
                guarded_signal_thresholds["yes_threshold"] = item.get("after")
            elif field == "signal_thresholds.no_threshold":
                guarded_signal_thresholds["no_threshold"] = item.get("after")
        launch_guard_reasons.append("widening_overrides_neutralized_for_launch_control")
    if not safe_baseline_required and bounded_stage1_live_override:
        effective_runtime_profile = str(remote_runtime_profile or selected_profile).strip() or selected_profile
        guarded_mode = dict(guarded_mode)
        guarded_mode["execution_mode"] = "live"
        guarded_mode["effective_execution_mode"] = "live"
        guarded_mode["paper_trading"] = False if remote_paper_trading is None else bool(remote_paper_trading)
        guarded_mode["allow_order_submission"] = True
        launch_guard_reasons.append(
            "bounded_stage1_live_override_kept_effective_runtime_profile"
        )
        launch_guard_reasons.append("bounded_stage1_live_override_forced_live_mode_contract")

    guarded_config = dict(effective_config)
    guarded_config["mode"] = guarded_mode
    guarded_config["feature_flags"] = guarded_flags
    guarded_config["risk_limits"] = guarded_risk_limits
    guarded_config["signal_thresholds"] = guarded_signal_thresholds
    guarded_config["market_filters"] = guarded_market_filters
    if safe_baseline_required and safe_bundle is not None:
        effective_path = Path(runtime_profile_refresh["effective_path"])
        write_runtime_profile_bundle(
            safe_bundle,
            output_path=effective_path,
        )
        refreshed_effective = _load_json(effective_path, default={})
        if refreshed_effective:
            dump_path_atomic(
                root / LEGACY_RUNTIME_PROFILE_EFFECTIVE_PATH,
                refreshed_effective,
                indent=2,
                sort_keys=True,
                trailing_newline=False,
            )

    execution_mode = str(
        guarded_mode.get("effective_execution_mode")
        or guarded_mode.get("execution_mode")
        or "unknown"
    ).strip()
    local_paper_trading = _bool_or_none(guarded_mode.get("paper_trading"))
    paper_trading = local_paper_trading
    raw_allow_order_submission = bool(guarded_mode.get("allow_order_submission"))
    force_live_attempt = False

    mode_ambiguity_fields: list[str] = []
    if not remote_runtime_profile:
        mode_ambiguity_fields.append("JJ_RUNTIME_PROFILE")
    if not agent_run_mode or agent_run_mode == "unknown":
        mode_ambiguity_fields.append("ELASTIFUND_AGENT_RUN_MODE")
    if paper_trading is None:
        mode_ambiguity_fields.append("PAPER_TRADING")
    if not execution_mode or execution_mode == "unknown":
        mode_ambiguity_fields.append("execution_mode")

    mode_inconsistency_reasons: list[str] = []
    if (
        remote_runtime_profile
        and remote_runtime_profile != selected_profile
        and not remote_mode_authoritative
    ):
        mode_inconsistency_reasons.append(
            f"remote JJ_RUNTIME_PROFILE={remote_runtime_profile} differs from local selected profile {selected_profile}"
        )
    compatible_agent_modes = {
        "shadow": {"shadow", "micro_live"},
        "micro_live": {"micro_live", "live"},
        "live": {"live"},
        "research": {"research"},
    }
    expected_agent_modes = compatible_agent_modes.get(execution_mode, {"micro_live", "live", "shadow"})
    if (
        agent_run_mode
        and agent_run_mode != "unknown"
        and execution_mode
        and execution_mode != "unknown"
        and agent_run_mode not in expected_agent_modes
    ):
        mode_inconsistency_reasons.append(
            f"remote ELASTIFUND_AGENT_RUN_MODE={agent_run_mode} differs from execution_mode={execution_mode}"
        )
    if (
        remote_paper_trading is not None
        and local_paper_trading is not None
        and remote_paper_trading != local_paper_trading
    ):
        mode_inconsistency_reasons.append(
            f"remote PAPER_TRADING={remote_paper_trading} differs from effective paper_trading={local_paper_trading}"
        )
    if service_state == "running" and launch_live_blocked and raw_allow_order_submission:
        mode_inconsistency_reasons.append(
            "service_state=running while launch_posture=blocked and allow_order_submission=true"
        )

    launch_posture = "clear" if force_live_attempt else (
        "blocked"
        if launch_live_blocked or mode_ambiguity_fields or mode_inconsistency_reasons
        else "clear"
    )
    allow_order_submission = bool(
        raw_allow_order_submission
        and launch_posture != "blocked"
        and not mode_ambiguity_fields
        and not mode_inconsistency_reasons
    )
    order_submit_enabled = bool(
        allow_order_submission and (
            force_live_attempt
            or service_state == "running"
        )
    )
    restart_recommended = bool(
        launch_posture != "blocked"
        and status.get("launch", {}).get("fast_flow_restart_ready")
        and service_state != "running"
    )

    jj_state = _load_json(root / "jj_state.json", default={})
    remote_probe = dict(deploy_evidence.get("remote_probe") or {})
    polymarket_wallet = status.get("polymarket_wallet") or {}
    local_counts = {
        "cycles_completed": int(status.get("runtime", {}).get("cycles_completed") or 0),
        "total_trades": int(status.get("runtime", {}).get("total_trades") or 0),
        "open_positions": int(status.get("runtime", {}).get("open_positions") or 0),
        "deployed_capital_usd": float(status.get("capital", {}).get("deployed_capital_usd") or 0.0),
    }
    metric_drifts = {
        "cycles_completed": _build_metric_drift(
            {
                "jj_state.json": _int_or_none(jj_state.get("cycles_completed")),
                "data/intel_snapshot.json": _int_or_none(
                    (_load_json(root / "data" / "intel_snapshot.json", default={}) or {}).get("total_cycles")
                ),
                "reports/remote_cycle_status.json": _int_or_none(status.get("runtime", {}).get("cycles_completed")),
            }
        ),
        "total_trades": _build_metric_drift(
            {
                "jj_state.json": _int_or_none(jj_state.get("total_trades")),
                "reports/remote_cycle_status.json": _int_or_none(status.get("runtime", {}).get("total_trades")),
                "deploy_status_command": _int_or_none(remote_probe.get("last_trades")),
            }
        ),
        "open_positions": _build_metric_drift(
            {
                "jj_state.json": len(jj_state.get("open_positions") or {}),
                "reports/remote_cycle_status.json": _int_or_none(status.get("runtime", {}).get("open_positions")),
                "deploy_status_command": _int_or_none(remote_probe.get("open_positions")),
                "polymarket_wallet_api": _int_or_none(polymarket_wallet.get("open_positions_count")),
            }
        ),
        "deployed_capital_usd": _build_metric_drift(
            {
                "jj_state.json": _float_or_none(jj_state.get("total_deployed")),
                "reports/runtime_truth_latest.json": _float_or_none(
                    status.get("capital", {}).get("deployed_capital_usd")
                ),
                "polymarket_wallet_api": _float_or_none(
                    status.get("capital", {}).get("polymarket_observed_deployed_usd")
                ),
            }
        ),
    }
    count_drift_detected = any(item["drift_detected"] for item in metric_drifts.values())
    wallet_balance_delta_usd = _float_or_none(
        status.get("capital", {}).get("polymarket_accounting_delta_usd")
    )
    wallet_balance_drift = bool(
        polymarket_wallet.get("status") == "ok"
        and wallet_balance_delta_usd is not None
        and abs(wallet_balance_delta_usd) >= 5.0
    )

    profile_contract_name = str(effective_runtime_profile or selected_profile).strip() or selected_profile
    profile_override_diff = _compare_profile_contract(
        profile_contract_name,
        guarded_config,
        applied_overrides=applied_overrides,
    )
    caps_threshold_drift = any(
        change["field"].startswith(("risk_limits.", "signal_thresholds.", "market_filters.max_resolution_hours"))
        for change in profile_override_diff["changed_fields"]
    )

    docs_drift = _build_docs_runtime_drift(root, local_counts)
    remote_probe_alignment = _build_remote_probe_alignment(
        effective_flags=guarded_flags,
        local_counts=local_counts,
        remote_probe=remote_probe,
    )
    local_remote_truth_mismatch = bool(
        remote_probe_alignment["count_mismatches"] or remote_probe_alignment["feature_mismatches"]
    )

    drift_reasons = _dedupe_preserve_order(
        [
            *(
                [f"{name} differs across local and synced sources" for name, item in metric_drifts.items() if item["drift_detected"]]
            ),
            "selected runtime profile differs from its effective override surface"
            if profile_override_diff["changed_fields"]
            else "",
            "effective caps/thresholds differ from the checked-in profile defaults"
            if caps_threshold_drift
            else "",
            "reports/runtime_profile_effective.json was stale before this reconciliation run"
            if runtime_profile_refresh.get("stale_before_refresh")
            else "",
            "public/operator docs still describe the stale 314-cycle / zero-activity runtime"
            if docs_drift["stale"]
            else "",
            (
                "tracked Polymarket capital differs materially from observed wallet value"
                if wallet_balance_drift
                else ""
            ),
            "remote status probe does not match the recomputed local effective profile"
            if local_remote_truth_mismatch
            else "",
            *list(remote_probe_alignment.get("feature_mismatches") or []),
            *list(remote_probe_alignment.get("count_mismatches") or []),
            *launch_guard_reasons,
            *(
                [
                    f"launch_guard_neutralized {item.get('env_var')} on {item.get('field')}"
                    for item in neutralized_overrides
                ]
            ),
            f"{PRIMARY_RUNTIME_SERVICE_NAME} is running while launch posture remains blocked"
            if service_state == "running" and launch_posture == "blocked"
            else "",
            *mode_inconsistency_reasons,
            (
                "mode fields are ambiguous: "
                + ", ".join(mode_ambiguity_fields)
                if mode_ambiguity_fields
                else ""
            ),
        ]
    )
    drift_reasons = [reason for reason in drift_reasons if reason]

    return {
        "generated_at": runtime_truth_snapshot.get("generated_at"),
        "service_state": service_state or "unknown",
        "process_state": process_state or "unknown",
        "remote_runtime_profile": remote_runtime_profile,
        "remote_mode_authoritative": remote_mode_authoritative,
        "agent_run_mode": agent_run_mode,
        "selected_runtime_profile": selected_profile,
        "effective_runtime_profile": effective_runtime_profile,
        "safe_baseline_profile": safe_baseline_profile,
        "safe_baseline_reason": safe_baseline_reason,
        "safe_baseline_required": safe_baseline_required,
        "execution_mode": execution_mode,
        "paper_trading": paper_trading,
        "allow_order_submission": allow_order_submission,
        "order_submit_enabled": order_submit_enabled,
        "effective_caps": _build_effective_caps(guarded_risk_limits),
        "effective_thresholds": _build_effective_thresholds(
            risk_limits=guarded_risk_limits,
            signal_thresholds=guarded_signal_thresholds,
            market_filters=guarded_market_filters,
        ),
        **local_counts,
        "drift_flags": {
            "count_drift": count_drift_detected,
            "counts": metric_drifts,
            "profile_override_drift": bool(profile_override_diff["changed_fields"]),
            "caps_threshold_drift": caps_threshold_drift,
            "docs_stale": docs_drift["stale"],
            "local_remote_truth_mismatch": local_remote_truth_mismatch,
            "mode_field_ambiguity": bool(mode_ambiguity_fields),
            "mode_field_ambiguity_fields": mode_ambiguity_fields,
            "mode_field_inconsistency": bool(mode_inconsistency_reasons),
            "mode_field_inconsistency_reasons": mode_inconsistency_reasons,
            "remote_mode_authoritative": remote_mode_authoritative,
            "service_running_while_launch_blocked": service_state == "running"
            and launch_posture == "blocked",
            "runtime_profile_effective_stale_before_refresh": bool(
                runtime_profile_refresh.get("stale_before_refresh")
            ),
            "wallet_balance_drift": wallet_balance_drift,
            "wallet_balance_delta_usd": wallet_balance_delta_usd,
            "safe_baseline_lock": safe_baseline_required,
            "safe_baseline_profile": safe_baseline_profile,
            "safe_baseline_reason": safe_baseline_reason,
            "effective_runtime_profile": effective_runtime_profile,
            "launch_guard_overrides_neutralized": bool(neutralized_overrides),
            "launch_guard_neutralized_overrides": neutralized_overrides,
            "drift_reasons": drift_reasons,
        },
        "launch_posture": launch_posture,
        "restart_recommended": restart_recommended,
        "launch_guard": {
            "force_live_attempt_requested": force_live_attempt_requested,
            "force_live_attempt_applied": force_live_attempt,
            "safe_baseline_profile": safe_baseline_profile,
            "safe_baseline_reason": safe_baseline_reason,
            "safe_baseline_required": safe_baseline_required,
            "bounded_stage1_live_override": bounded_stage1_live_override,
            "remote_mode_authoritative": remote_mode_authoritative,
            "lock_reasons": launch_guard_reasons,
            "neutralized_overrides": neutralized_overrides,
        },
        "mode_reconciliation": {
            "sources": {
                "local_env": _relative_path_text(root, root / DEFAULT_ENV_PATH),
                "env_example": _relative_path_text(root, root / DEFAULT_ENV_EXAMPLE_PATH),
                "runtime_operator_overrides": _relative_path_text(
                    root,
                    root / DEFAULT_RUNTIME_OPERATOR_OVERRIDES_PATH,
                ),
                "capital_stage_env": _relative_path_text(root, root / BTC5_CAPITAL_STAGE_ENV_PATH),
                "autoresearch_env": _relative_path_text(root, root / BTC5_AUTORESEARCH_ENV_PATH),
                "runtime_profile_effective": _relative_path_text(
                    root,
                    runtime_profile_refresh["effective_path"],
                ),
                "deploy_report": deploy_evidence.get("path"),
                "remote_service_status": _relative_path_text(
                    root,
                    root / DEFAULT_SERVICE_STATUS_PATH,
                ),
                "remote_cycle_status": _relative_path_text(root, root / DEFAULT_JSON_PATH),
                "runtime_mode_reconciliation_markdown": _relative_path_text(
                    root,
                    runtime_mode_reconciliation_path,
                ),
            },
            "local_env": _sanitize_env_subset(runtime_profile_refresh.get("local_env") or {}),
            "local_env_example": _sanitize_env_subset(runtime_profile_refresh.get("env_example") or {}),
            "capital_stage_env": _sanitize_env_subset(
                runtime_profile_refresh.get("capital_stage_env") or {}
            ),
            "autoresearch_env": _sanitize_env_subset(
                runtime_profile_refresh.get("autoresearch_env") or {}
            ),
            "runtime_operator_overrides": _sanitize_env_subset(
                runtime_profile_refresh.get("operator_overrides") or {}
            ),
            "runtime_profile_effective_refreshed": bool(runtime_profile_refresh.get("refreshed")),
            "runtime_profile_effective_stale_before_refresh_fields": list(
                runtime_profile_refresh.get("stale_before_refresh_fields") or []
            ),
            "selected_profile": selected_profile,
            "effective_profile": effective_runtime_profile,
            "safe_baseline_profile": safe_baseline_profile,
            "safe_baseline_reason": safe_baseline_reason,
            "safe_baseline_required": safe_baseline_required,
            "profile_override_diff": profile_override_diff,
            "remote_mode": {
                "generated_at": deploy_evidence.get("generated_at"),
                "remote_env_exists": deploy_evidence.get("remote_env_exists"),
                "values": _sanitize_env_subset(remote_values),
                "remote_runtime_profile": remote_runtime_profile,
                "agent_run_mode": agent_run_mode,
                "paper_trading": paper_trading,
            },
            "remote_probe": remote_probe,
            "remote_probe_alignment": remote_probe_alignment,
            "launch_guard": {
                "force_live_attempt_requested": force_live_attempt_requested,
                "force_live_attempt_applied": force_live_attempt,
                "remote_mode_authoritative": remote_mode_authoritative,
                "neutralized_overrides": neutralized_overrides,
                "lock_reasons": launch_guard_reasons,
            },
            "docs": docs_drift,
        },
    }


def apply_runtime_mode_reconciliation(
    runtime_truth_snapshot: dict[str, Any],
    *,
    root: Path,
    runtime_mode_reconciliation: dict[str, Any],
    runtime_mode_reconciliation_path: Path,
) -> dict[str, Any]:
    snapshot = dict(runtime_truth_snapshot)
    snapshot.update(
        {
            "service_state": runtime_mode_reconciliation["service_state"],
            "process_state": runtime_mode_reconciliation["process_state"],
            "remote_runtime_profile": runtime_mode_reconciliation["remote_runtime_profile"],
            "remote_mode_authoritative": runtime_mode_reconciliation.get("remote_mode_authoritative"),
            "agent_run_mode": runtime_mode_reconciliation["agent_run_mode"],
            "selected_runtime_profile": runtime_mode_reconciliation.get("selected_runtime_profile"),
            "effective_runtime_profile": runtime_mode_reconciliation.get("effective_runtime_profile"),
            "safe_baseline_profile": runtime_mode_reconciliation.get("safe_baseline_profile"),
            "safe_baseline_reason": runtime_mode_reconciliation.get("safe_baseline_reason"),
            "safe_baseline_required": runtime_mode_reconciliation.get("safe_baseline_required"),
            "execution_mode": runtime_mode_reconciliation["execution_mode"],
            "paper_trading": runtime_mode_reconciliation["paper_trading"],
            "allow_order_submission": runtime_mode_reconciliation["allow_order_submission"],
            "order_submit_enabled": runtime_mode_reconciliation["order_submit_enabled"],
            "effective_caps": runtime_mode_reconciliation["effective_caps"],
            "effective_thresholds": runtime_mode_reconciliation["effective_thresholds"],
            "cycles_completed": runtime_mode_reconciliation["cycles_completed"],
            "total_trades": runtime_mode_reconciliation["total_trades"],
            "open_positions": runtime_mode_reconciliation["open_positions"],
            "deployed_capital_usd": runtime_mode_reconciliation["deployed_capital_usd"],
            "drift_flags": runtime_mode_reconciliation["drift_flags"],
            "launch_posture": runtime_mode_reconciliation["launch_posture"],
            "restart_recommended": runtime_mode_reconciliation["restart_recommended"],
            "launch_guard": runtime_mode_reconciliation.get("launch_guard") or {},
            "mode_reconciliation": runtime_mode_reconciliation["mode_reconciliation"],
        }
    )
    snapshot.setdefault("summary", {}).update(
        {
            "remote_runtime_profile": runtime_mode_reconciliation["remote_runtime_profile"],
            "remote_mode_authoritative": runtime_mode_reconciliation.get("remote_mode_authoritative"),
            "agent_run_mode": runtime_mode_reconciliation["agent_run_mode"],
            "effective_runtime_profile": runtime_mode_reconciliation.get("effective_runtime_profile"),
            "safe_baseline_reason": runtime_mode_reconciliation.get("safe_baseline_reason"),
            "safe_baseline_required": runtime_mode_reconciliation.get("safe_baseline_required"),
            "execution_mode": runtime_mode_reconciliation["execution_mode"],
            "paper_trading": runtime_mode_reconciliation["paper_trading"],
            "allow_order_submission": runtime_mode_reconciliation["allow_order_submission"],
            "order_submit_enabled": runtime_mode_reconciliation["order_submit_enabled"],
        }
    )
    snapshot.setdefault("launch", {}).update(
        {
            "posture": runtime_mode_reconciliation["launch_posture"],
            "allow_order_submission": runtime_mode_reconciliation["allow_order_submission"],
            "execution_mode": runtime_mode_reconciliation["execution_mode"],
            "effective_runtime_profile": runtime_mode_reconciliation.get("effective_runtime_profile"),
            "safe_baseline_profile": runtime_mode_reconciliation.get("safe_baseline_profile"),
            "safe_baseline_reason": runtime_mode_reconciliation.get("safe_baseline_reason"),
            "safe_baseline_required": runtime_mode_reconciliation.get("safe_baseline_required"),
        }
    )
    snapshot.setdefault("artifacts", {})[
        "runtime_mode_reconciliation_markdown"
    ] = _relative_path_text(ROOT, runtime_mode_reconciliation_path)
    snapshot.setdefault("drift", {})["mode_contract"] = runtime_mode_reconciliation["drift_flags"]
    _attach_control_plane_consistency(snapshot, root=root)
    return snapshot


def apply_runtime_mode_reconciliation_to_status(
    status: dict[str, Any],
    *,
    runtime_mode_reconciliation: dict[str, Any],
) -> dict[str, Any]:
    payload = dict(status)
    launch = dict(payload.get("launch") or {})
    launch.update(
        {
            "posture": runtime_mode_reconciliation["launch_posture"],
            "allow_order_submission": runtime_mode_reconciliation["allow_order_submission"],
            "execution_mode": runtime_mode_reconciliation["execution_mode"],
            "effective_runtime_profile": runtime_mode_reconciliation.get("effective_runtime_profile"),
            "safe_baseline_profile": runtime_mode_reconciliation.get("safe_baseline_profile"),
            "safe_baseline_required": runtime_mode_reconciliation.get("safe_baseline_required"),
        }
    )
    payload["launch"] = launch
    payload["service_state"] = runtime_mode_reconciliation["service_state"]
    payload["launch_posture"] = runtime_mode_reconciliation["launch_posture"]
    payload["live_launch_blocked"] = bool(launch.get("live_launch_blocked"))
    payload["allow_order_submission"] = runtime_mode_reconciliation["allow_order_submission"]
    payload["execution_mode"] = runtime_mode_reconciliation["execution_mode"]
    payload["paper_trading"] = runtime_mode_reconciliation["paper_trading"]
    payload["order_submit_enabled"] = runtime_mode_reconciliation["order_submit_enabled"]
    payload["runtime_mode"] = {
        "selected_runtime_profile": runtime_mode_reconciliation.get("selected_runtime_profile"),
        "effective_runtime_profile": runtime_mode_reconciliation.get("effective_runtime_profile"),
        "safe_baseline_profile": runtime_mode_reconciliation.get("safe_baseline_profile"),
        "safe_baseline_reason": runtime_mode_reconciliation.get("safe_baseline_reason"),
        "safe_baseline_required": runtime_mode_reconciliation.get("safe_baseline_required"),
        "remote_mode_authoritative": runtime_mode_reconciliation.get("remote_mode_authoritative"),
        "execution_mode": runtime_mode_reconciliation["execution_mode"],
        "paper_trading": runtime_mode_reconciliation["paper_trading"],
        "allow_order_submission": runtime_mode_reconciliation["allow_order_submission"],
        "order_submit_enabled": runtime_mode_reconciliation["order_submit_enabled"],
    }
    payload["runtime_mode_reconciliation"] = {
        "effective_profile": runtime_mode_reconciliation.get("effective_runtime_profile"),
        "execution_mode": runtime_mode_reconciliation["execution_mode"],
        "allow_order_submission": runtime_mode_reconciliation["allow_order_submission"],
        "launch_posture": runtime_mode_reconciliation["launch_posture"],
        "service_state": runtime_mode_reconciliation["service_state"],
        "safe_baseline_reason": runtime_mode_reconciliation.get("safe_baseline_reason"),
        "safe_baseline_required": runtime_mode_reconciliation.get("safe_baseline_required"),
        "safe_baseline_profile": runtime_mode_reconciliation.get("safe_baseline_profile"),
    }
    runtime_truth = dict(payload.get("runtime_truth") or {})
    runtime_truth.update(
        {
            "service_state": runtime_mode_reconciliation["service_state"],
            "process_state": runtime_mode_reconciliation["process_state"],
            "remote_runtime_profile": runtime_mode_reconciliation["remote_runtime_profile"],
            "remote_mode_authoritative": runtime_mode_reconciliation.get("remote_mode_authoritative"),
            "agent_run_mode": runtime_mode_reconciliation["agent_run_mode"],
            "selected_runtime_profile": runtime_mode_reconciliation.get("selected_runtime_profile"),
            "effective_runtime_profile": runtime_mode_reconciliation.get("effective_runtime_profile"),
            "safe_baseline_profile": runtime_mode_reconciliation.get("safe_baseline_profile"),
            "safe_baseline_reason": runtime_mode_reconciliation.get("safe_baseline_reason"),
            "safe_baseline_required": runtime_mode_reconciliation.get("safe_baseline_required"),
            "execution_mode": runtime_mode_reconciliation["execution_mode"],
            "paper_trading": runtime_mode_reconciliation["paper_trading"],
            "allow_order_submission": runtime_mode_reconciliation["allow_order_submission"],
            "order_submit_enabled": runtime_mode_reconciliation["order_submit_enabled"],
            "launch_posture": runtime_mode_reconciliation["launch_posture"],
        }
    )
    payload["runtime_truth"] = runtime_truth
    return payload


def build_canonical_launch_packet(
    *,
    root: Path,
    runtime_truth_snapshot: dict[str, Any],
) -> dict[str, Any]:
    return _build_canonical_launch_packet_impl(
        root=root,
        runtime_truth_snapshot=runtime_truth_snapshot,
        launch_checklist_path=DEFAULT_LAUNCH_CHECKLIST_PATH,
    )


def apply_canonical_launch_packet(
    runtime_truth_snapshot: dict[str, Any],
    *,
    root: Path,
    launch_packet: dict[str, Any],
    launch_packet_latest_path: Path,
    launch_packet_timestamped_path: Path,
) -> dict[str, Any]:
    return _apply_canonical_launch_packet_impl(
        runtime_truth_snapshot,
        root=root,
        launch_packet=launch_packet,
        launch_packet_latest_path=launch_packet_latest_path,
        launch_packet_timestamped_path=launch_packet_timestamped_path,
    )


def apply_canonical_launch_packet_to_status(
    status: dict[str, Any],
    *,
    launch_packet: dict[str, Any],
) -> dict[str, Any]:
    return _apply_canonical_launch_packet_to_status_impl(
        status,
        launch_packet=launch_packet,
    )


def _load_strategy_scale_comparison_summary(
    *,
    root: Path,
    generated_at: datetime | None,
) -> dict[str, Any]:
    path = _resolve_compatibility_alias_path(
        root,
        "strategy_scale_comparison.json",
        materialize=False,
    )
    if not path.exists():
        path = root / "reports" / "strategy_scale_comparison.json"
    payload = _load_json(path, default={})
    summary = {
        "exists": path.exists() and isinstance(payload, dict),
        "path": _relative_path_text(root, path) or str(path),
        "generated_at": None,
        "age_hours": None,
        "freshness": "unknown",
        "polymarket_btc5_status": None,
        "next_1000_status": None,
        "next_1000_recommended_amount_usd": None,
        "stage_recommended": None,
        "stage_gate_reason": None,
        "stage_readiness": {},
        "stage_blocking_checks": [],
        "stage_reasons": [],
        "ready_for_stage_1": False,
        "ready_for_stage_2": False,
        "ready_for_stage_3": False,
        "wallet_export_freshness_hours": None,
        "probe_freshness_hours": None,
        "source_artifacts": [],
    }
    if not summary["exists"]:
        return summary

    payload = dict(payload)
    artifact_generated_at = _parse_datetime_like(
        _first_nonempty(payload.get("generated_at"), _safe_iso_mtime(path))
    )
    age_hours = _age_hours_from_datetimes(reference_at=generated_at, observed_at=artifact_generated_at)
    capital_allocation = (
        payload.get("capital_allocation_recommendation")
        if isinstance(payload.get("capital_allocation_recommendation"), dict)
        else {}
    )
    next_1000_alloc = (
        capital_allocation.get("next_1000_usd")
        if isinstance(capital_allocation.get("next_1000_usd"), dict)
        else {}
    )
    next_1000_payload = payload.get("next_1000_usd") if isinstance(payload.get("next_1000_usd"), dict) else {}
    venue_scoreboard = payload.get("venue_scoreboard") if isinstance(payload.get("venue_scoreboard"), list) else []
    polymarket_btc5_entry = next(
        (
            dict(item)
            for item in venue_scoreboard
            if isinstance(item, dict)
            and str(item.get("venue") or "").strip().lower() == "polymarket"
            and str(item.get("lane") or "").strip().lower() == "btc5"
        ),
        {},
    )
    next_1000_stage = (
        next_1000_alloc.get("stage_readiness")
        if isinstance(next_1000_alloc.get("stage_readiness"), dict)
        else {}
    )
    venue_stage = (
        polymarket_btc5_entry.get("stage_readiness")
        if isinstance(polymarket_btc5_entry.get("stage_readiness"), dict)
        else {}
    )
    selected_stage = (
        stage_payload
        if isinstance((stage_payload := payload.get("stage_readiness")), dict)
        else {}
    )
    if not selected_stage:
        selected_stage = next_1000_stage or venue_stage or {}
    selected_stage = dict(selected_stage)
    summary.update(
        {
            "generated_at": artifact_generated_at.isoformat() if artifact_generated_at is not None else None,
            "age_hours": round(age_hours, 4) if age_hours is not None else None,
            "freshness": _freshness_label_for_age_hours(age_hours),
            "polymarket_btc5_status": _first_nonempty(
                polymarket_btc5_entry.get("capital_status"),
                polymarket_btc5_entry.get("deployment_readiness"),
            ),
            "next_1000_status": _first_nonempty(
                next_1000_alloc.get("status"),
                next_1000_payload.get("status"),
            ),
            "next_1000_recommended_amount_usd": _float_or_none(
                _first_nonempty(
                    next_1000_alloc.get("recommended_amount_usd"),
                    next_1000_payload.get("recommended_amount_usd"),
                )
            ),
            "stage_recommended": _int_or_none(
                _first_nonempty(
                    selected_stage.get("recommended_stage"),
                    next_1000_stage.get("recommended_stage"),
                    venue_stage.get("recommended_stage"),
                )
            ),
            "stage_gate_reason": _first_nonempty(
                selected_stage.get("stage_gate_reason"),
                next_1000_payload.get("stage_gate_reason"),
                next_1000_alloc.get("stage_gate_reason"),
            ),
            "stage_readiness": selected_stage,
            "stage_blocking_checks": list(selected_stage.get("blocking_checks") or []),
            "stage_reasons": list(selected_stage.get("reasons") or []),
            "ready_for_stage_1": bool(
                _first_nonempty(selected_stage.get("ready_for_stage_1"), False)
            ),
            "ready_for_stage_2": bool(
                _first_nonempty(selected_stage.get("ready_for_stage_2"), False)
            ),
            "ready_for_stage_3": bool(
                _first_nonempty(selected_stage.get("ready_for_stage_3"), False)
            ),
            "wallet_export_freshness_hours": _float_or_none(
                selected_stage.get("wallet_export_freshness_hours")
            ),
            "probe_freshness_hours": _float_or_none(
                selected_stage.get("probe_freshness_hours")
            ),
            "source_artifacts": list(
                dict.fromkeys(
                    [
                        *list(next_1000_alloc.get("source_artifacts") or []),
                        *list(next_1000_payload.get("source_artifacts") or []),
                    ]
                )
            ),
        }
    )
    return summary


def _load_signal_source_audit_summary(
    *,
    root: Path,
    generated_at: datetime | None,
) -> dict[str, Any]:
    path = _resolve_compatibility_alias_path(
        root,
        "signal_source_audit.json",
        materialize=False,
    )
    if not path.exists():
        path = root / "reports" / "signal_source_audit.json"
    payload = _load_json(path, default={})
    summary = {
        "exists": path.exists() and isinstance(payload, dict),
        "path": _relative_path_text(root, path) or str(path),
        "generated_at": None,
        "age_hours": None,
        "freshness": "unknown",
        "stage_upgrade_support_status": None,
        "confirmation_support_status": None,
        "wallet_flow_confirmation_ready": None,
        "wallet_flow_archive_confirmation_ready": None,
        "lmsr_archive_confirmation_ready": None,
        "btc_fast_window_confirmation_ready": None,
        "supports_capital_allocation": None,
        "best_component_source": None,
        "best_source_combo": None,
        "stage_upgrade_blocking_checks": [],
        "confirmation_coverage_score": None,
        "confirmation_coverage_status": None,
        "confirmation_coverage_label": None,
        "confirmation_freshness_label": None,
        "confirmation_stale_sources": [],
        "confirmation_sources_ready": [],
        "best_confirmation_source": None,
        "confirmation_strength_label": None,
        "confirmation_strength_score": None,
        "confirmation_evidence_score": None,
        "confirmation_resolved_window_coverage": None,
        "confirmation_executed_window_coverage": None,
        "confirmation_false_suppression_cost_usd": None,
        "confirmation_false_confirmation_cost_usd": None,
        "confirmation_lift_avg_pnl_usd": None,
        "confirmation_lift_win_rate": None,
        "confirmation_contradiction_penalty": None,
        "confirmation_source_gap_vs_probe_hours": None,
        "confirmation_next_required_artifact": None,
        "confirmation_lift": None,
        "contradiction_penalty_score": None,
    }
    if not summary["exists"]:
        return summary

    payload = dict(payload)
    capital_support = (
        payload.get("capital_ranking_support")
        if isinstance(payload.get("capital_ranking_support"), dict)
        else {}
    )
    artifact_generated_at = _parse_datetime_like(
        _first_nonempty(
            capital_support.get("audit_generated_at"),
            payload.get("generated_at"),
            _safe_iso_mtime(path),
        )
    )
    age_hours = _age_hours_from_datetimes(reference_at=generated_at, observed_at=artifact_generated_at)
    confirmation_coverage_label = str(
        _first_nonempty(
            capital_support.get("confirmation_coverage_label"),
            capital_support.get("confirmation_coverage_status"),
            None,
        )
        or ""
    ).strip().lower() or None
    confirmation_coverage_score = _first_nonempty(
        capital_support.get("confirmation_coverage_score"),
        capital_support.get("confirmation_coverage_pct"),
        capital_support.get("resolved_window_coverage_score"),
        capital_support.get("resolved_window_coverage_pct"),
    )
    normalized_confirmation_score = _normalize_unit_score(confirmation_coverage_score)
    if normalized_confirmation_score is None:
        normalized_confirmation_score = _confirmation_score_for_label(confirmation_coverage_label)
    wallet_flow_confirmation_ready = _bool_or_none(
        capital_support.get("wallet_flow_confirmation_ready")
    )
    confirmation_strength_label = str(
        _first_nonempty(
            capital_support.get("confirmation_strength_label"),
            None,
        )
        or ""
    ).strip().lower() or None
    normalized_confirmation_strength = _normalize_unit_score(
        _first_nonempty(
            capital_support.get("confirmation_strength_score"),
            capital_support.get("confirmation_strength_pct"),
        )
    )
    if normalized_confirmation_strength is None:
        normalized_confirmation_strength = _confirmation_score_for_label(
            confirmation_strength_label
        )
    confirmation_freshness_label = str(
        _first_nonempty(
            capital_support.get("confirmation_freshness_label"),
            capital_support.get("confirmation_evidence_freshness"),
            None,
        )
        or ""
    ).strip().lower() or None
    if normalized_confirmation_score is None:
        if wallet_flow_confirmation_ready is True:
            normalized_confirmation_score = 0.75
        elif wallet_flow_confirmation_ready is False:
            normalized_confirmation_score = 0.2
        elif _bool_or_none(capital_support.get("supports_capital_allocation")) is True:
            normalized_confirmation_score = 0.35
        else:
            normalized_confirmation_score = 0.1
    elif confirmation_freshness_label == "stale":
        normalized_confirmation_score = min(normalized_confirmation_score, 0.25)
    elif confirmation_freshness_label == "aging":
        normalized_confirmation_score = min(normalized_confirmation_score, 0.5)
    confirmation_evidence_score = normalized_confirmation_strength
    if confirmation_evidence_score is None:
        confirmation_evidence_score = normalized_confirmation_score
    if confirmation_evidence_score is None:
        confirmation_evidence_score = 0.1
    if confirmation_freshness_label == "stale":
        confirmation_evidence_score = min(confirmation_evidence_score, 0.25)
    elif confirmation_freshness_label == "aging":
        confirmation_evidence_score = min(confirmation_evidence_score, 0.5)
    confirmation_evidence_score = round(confirmation_evidence_score, 4)
    stage_upgrade_blocking_checks = list(capital_support.get("stage_upgrade_blocking_checks") or [])
    stage_upgrade_support_status = _first_nonempty(
        capital_support.get("stage_upgrade_support_status"),
        capital_support.get("combined_sources_vs_single_source_status"),
        capital_support.get("wallet_flow_vs_llm_status"),
    )
    confirmation_support_status = _first_nonempty(
        capital_support.get("confirmation_support_status"),
        stage_upgrade_support_status,
    )
    confirmation_coverage_status = str(
        _first_nonempty(
            capital_support.get("confirmation_coverage_status"),
            confirmation_support_status,
            stage_upgrade_support_status,
            ("ready" if wallet_flow_confirmation_ready else None),
        )
        or "unknown"
    ).strip().lower()
    if not stage_upgrade_blocking_checks and (
        confirmation_evidence_score < 0.4
        or confirmation_coverage_status in {
            "limited",
            "insufficient_data",
            "collect_more_data",
            "not_ready",
            "unknown",
        }
    ):
        stage_upgrade_blocking_checks.append("confirmation_coverage_insufficient")
    if confirmation_freshness_label == "stale":
        stage_upgrade_blocking_checks.append("confirmation_evidence_stale")
    summary.update(
        {
            "generated_at": artifact_generated_at.isoformat() if artifact_generated_at is not None else None,
            "age_hours": round(age_hours, 4) if age_hours is not None else None,
            "freshness": _freshness_label_for_age_hours(age_hours),
            "stage_upgrade_support_status": stage_upgrade_support_status,
            "confirmation_support_status": confirmation_support_status,
            "wallet_flow_confirmation_ready": wallet_flow_confirmation_ready,
            "wallet_flow_archive_confirmation_ready": _bool_or_none(
                capital_support.get("wallet_flow_archive_confirmation_ready")
            ),
            "lmsr_archive_confirmation_ready": _bool_or_none(
                capital_support.get("lmsr_archive_confirmation_ready")
            ),
            "btc_fast_window_confirmation_ready": _bool_or_none(
                capital_support.get("btc_fast_window_confirmation_ready")
            ),
            "supports_capital_allocation": _bool_or_none(capital_support.get("supports_capital_allocation")),
            "best_component_source": capital_support.get("best_component_source"),
            "best_source_combo": capital_support.get("best_source_combo"),
            "stage_upgrade_blocking_checks": _dedupe_preserve_order(stage_upgrade_blocking_checks),
            "confirmation_coverage_score": normalized_confirmation_score,
            "confirmation_coverage_status": confirmation_coverage_status,
            "confirmation_coverage_label": confirmation_coverage_label,
            "confirmation_freshness_label": confirmation_freshness_label,
            "confirmation_stale_sources": list(capital_support.get("confirmation_stale_sources") or []),
            "confirmation_sources_ready": list(capital_support.get("confirmation_sources_ready") or []),
            "best_confirmation_source": capital_support.get("best_confirmation_source"),
            "confirmation_strength_label": confirmation_strength_label,
            "confirmation_strength_score": normalized_confirmation_strength,
            "confirmation_evidence_score": confirmation_evidence_score,
            "confirmation_resolved_window_coverage": _float_or_none(
                capital_support.get("confirmation_resolved_window_coverage")
            ),
            "confirmation_executed_window_coverage": _float_or_none(
                capital_support.get("confirmation_executed_window_coverage")
            ),
            "confirmation_false_suppression_cost_usd": _float_or_none(
                capital_support.get("confirmation_false_suppression_cost_usd")
            ),
            "confirmation_false_confirmation_cost_usd": _float_or_none(
                capital_support.get("confirmation_false_confirmation_cost_usd")
            ),
            "confirmation_lift_avg_pnl_usd": _float_or_none(
                capital_support.get("confirmation_lift_avg_pnl_usd")
            ),
            "confirmation_lift_win_rate": _float_or_none(
                capital_support.get("confirmation_lift_win_rate")
            ),
            "confirmation_contradiction_penalty": _normalize_unit_score(
                capital_support.get("confirmation_contradiction_penalty")
            ),
            "confirmation_source_gap_vs_probe_hours": capital_support.get(
                "confirmation_source_gap_vs_probe_hours"
            ),
            "confirmation_next_required_artifact": capital_support.get(
                "confirmation_next_required_artifact"
            ),
            "confirmation_lift": _float_or_none(
                _first_nonempty(
                    capital_support.get("confirmation_lift_avg_pnl_usd"),
                    capital_support.get("confirmation_lift"),
                    capital_support.get("confirmation_lift_pct"),
                )
            ),
            "contradiction_penalty_score": _normalize_unit_score(
                _first_nonempty(
                    capital_support.get("confirmation_contradiction_penalty"),
                    capital_support.get("contradiction_penalty_score"),
                    capital_support.get("contradiction_penalty_pct"),
                )
            ),
        }
    )
    return summary


def _load_btc5_current_probe_summary(
    *,
    root: Path,
    generated_at: datetime | None,
) -> dict[str, Any]:
    path = root / "reports" / "btc5_autoresearch_current_probe" / "latest.json"
    payload = _load_json(path, default={})
    summary = {
        "exists": path.exists() and isinstance(payload, dict),
        "path": _relative_path_text(root, path) or str(path),
        "generated_at": None,
        "age_hours": None,
        "freshness": "unknown",
        "probe_freshness_hours": None,
        "latest_decision_at": None,
        "trailing_12_live_filled_pnl_usd": None,
        "trailing_40_live_filled_pnl_usd": None,
        "trailing_120_live_filled_pnl_usd": None,
        "recent_order_failed_rate": None,
        "recent_direction_mix": {},
        "recent_price_bucket_mix": {},
        "recent_loss_cluster_flags": [],
        "stage_ready_reason_tags": [],
        "stage_not_ready_reason_tags": [],
    }
    if not summary["exists"]:
        return summary

    payload = dict(payload)
    artifact_generated_at = _parse_datetime_like(
        _first_nonempty(payload.get("generated_at"), _safe_iso_mtime(path))
    )
    age_hours = _age_hours_from_datetimes(
        reference_at=generated_at,
        observed_at=artifact_generated_at,
    )
    current_probe = (
        payload.get("current_probe")
        if isinstance(payload.get("current_probe"), dict)
        else {}
    )
    probe_payload = dict(current_probe) if current_probe else payload
    summary.update(
        {
            "generated_at": artifact_generated_at.isoformat() if artifact_generated_at is not None else None,
            "age_hours": round(age_hours, 4) if age_hours is not None else None,
            "freshness": _freshness_label_for_age_hours(age_hours),
            "probe_freshness_hours": _float_or_none(
                _first_nonempty(
                    probe_payload.get("probe_freshness_hours"),
                    probe_payload.get("freshness_hours"),
                    age_hours,
                )
            ),
            "latest_decision_at": _first_nonempty(
                probe_payload.get("latest_decision_timestamp"),
                probe_payload.get("latest_decision_at"),
                probe_payload.get("latest_decision_ts"),
            ),
            "trailing_12_live_filled_pnl_usd": _float_or_none(
                _first_nonempty(
                    probe_payload.get("trailing_12_live_filled_pnl_usd"),
                    probe_payload.get("trailing12_live_filled_pnl_usd"),
                )
            ),
            "trailing_40_live_filled_pnl_usd": _float_or_none(
                _first_nonempty(
                    probe_payload.get("trailing_40_live_filled_pnl_usd"),
                    probe_payload.get("trailing40_live_filled_pnl_usd"),
                )
            ),
            "trailing_120_live_filled_pnl_usd": _float_or_none(
                _first_nonempty(
                    probe_payload.get("trailing_120_live_filled_pnl_usd"),
                    probe_payload.get("trailing120_live_filled_pnl_usd"),
                )
            ),
            "recent_order_failed_rate": _float_or_none(
                _first_nonempty(
                    probe_payload.get("recent_order_failed_rate"),
                    probe_payload.get("order_failed_rate_recent_40"),
                )
            ),
            "recent_direction_mix": dict(
                probe_payload.get("recent_direction_mix")
                if isinstance(probe_payload.get("recent_direction_mix"), dict)
                else {}
            ),
            "recent_price_bucket_mix": dict(
                probe_payload.get("recent_price_bucket_mix")
                if isinstance(probe_payload.get("recent_price_bucket_mix"), dict)
                else {}
            ),
            "recent_loss_cluster_flags": list(
                probe_payload.get("recent_loss_cluster_flags")
                if isinstance(probe_payload.get("recent_loss_cluster_flags"), list)
                else (probe_payload.get("loss_cluster_flags") or [])
            ),
            "stage_ready_reason_tags": [
                str(tag)
                for tag in list(probe_payload.get("stage_ready_reason_tags") or [])
                if str(tag).strip()
            ],
            "stage_not_ready_reason_tags": [
                str(tag)
                for tag in list(
                    _first_nonempty(
                        probe_payload.get("stage_not_ready_reason_tags"),
                        probe_payload.get("not_ready_reason_tags"),
                        [],
                    )
                    or []
                )
                if str(tag).strip()
            ],
        }
    )
    return summary


def _runtime_package_profile_name(package: dict[str, Any] | None) -> str | None:
    if not isinstance(package, dict):
        return None
    profile = package.get("profile")
    if not isinstance(profile, dict):
        return None
    name = str(profile.get("name") or "").strip()
    return name or None


def _runtime_package_shape_signature(package: dict[str, Any] | None) -> tuple[Any, ...] | None:
    if not isinstance(package, dict):
        return None
    profile = package.get("profile") if isinstance(package.get("profile"), dict) else {}
    if not profile:
        return None

    normalized_policy: list[tuple[Any, ...]] = []
    session_policy = package.get("session_policy") if isinstance(package.get("session_policy"), list) else []
    for item in session_policy:
        if not isinstance(item, dict):
            continue
        normalized_policy.append(
            (
                tuple(sorted(int(hour) for hour in (item.get("et_hours") or []) if isinstance(hour, int))),
                _safe_float(item.get("max_abs_delta"), None),
                _safe_float(item.get("up_max_buy_price"), None),
                _safe_float(item.get("down_max_buy_price"), None),
            )
        )
    normalized_policy.sort()
    return (
        _safe_float(profile.get("max_abs_delta"), None),
        _safe_float(profile.get("up_max_buy_price"), None),
        _safe_float(profile.get("down_max_buy_price"), None),
        tuple(normalized_policy),
    )


def _canonicalize_runtime_package_alias(
    runtime_package: dict[str, Any] | None,
    *,
    preferred_runtime_package: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(runtime_package, dict):
        return runtime_package
    if not isinstance(preferred_runtime_package, dict):
        return runtime_package
    runtime_signature = _runtime_package_shape_signature(runtime_package)
    preferred_signature = _runtime_package_shape_signature(preferred_runtime_package)
    if not runtime_signature or runtime_signature != preferred_signature:
        return runtime_package
    runtime_name = _runtime_package_profile_name(runtime_package)
    preferred_name = _runtime_package_profile_name(preferred_runtime_package)
    if not runtime_name or not preferred_name or runtime_name == preferred_name:
        return runtime_package
    return dict(preferred_runtime_package)


def _load_btc5_runtime_override_summary(root: Path) -> dict[str, Any]:
    path = root / BTC5_AUTORESEARCH_ENV_PATH
    summary = {
        "exists": path.exists(),
        "path": _relative_path_text(root, path) or str(path),
        "candidate": None,
        "env": {},
    }
    if not path.exists():
        return summary

    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# candidate="):
            candidate = stripped.split("=", 1)[1].strip()
            summary["candidate"] = candidate or None
            break
    summary["env"] = _parse_env_file(path)
    return summary


def _load_btc5_policy_live_package_summary(
    *,
    root: Path,
    generated_at: datetime | None,
) -> dict[str, Any]:
    path = root / "reports" / "autoresearch" / "btc5_policy" / "latest.json"
    payload = _load_json(path, default={})
    summary = {
        "exists": path.exists() and isinstance(payload, dict),
        "path": _relative_path_text(root, path) or str(path),
        "generated_at": None,
        "age_hours": None,
        "freshness": "unknown",
        "candidate_profile_name": None,
        "candidate_policy_id": None,
        "active_profile_name": None,
        "deploy_recommendation": None,
        "confidence_label": "unknown",
        "promotion_state": None,
        "runtime_package": None,
        "active_runtime_package": None,
        "candidate_package_hash": None,
        "active_package_hash": None,
        "canonical_live_profile": None,
        "canonical_live_package_hash": None,
        "source_artifact": None,
        "frontier_gap_vs_incumbent": None,
    }
    if not summary["exists"]:
        return summary

    payload = dict(payload)
    live_package = payload.get("live_package") if isinstance(payload.get("live_package"), dict) else {}
    champion = payload.get("champion") if isinstance(payload.get("champion"), dict) else {}
    champion_runtime_package = (
        champion.get("runtime_package")
        if isinstance(champion.get("runtime_package"), dict)
        else {}
    )
    runtime_package = (
        live_package.get("runtime_package")
        if isinstance(live_package.get("runtime_package"), dict)
        else (
            payload.get("selected_best_runtime_package")
            if isinstance(payload.get("selected_best_runtime_package"), dict)
            else {}
        )
    )
    active_runtime_package = (
        payload.get("selected_active_runtime_package")
        if isinstance(payload.get("selected_active_runtime_package"), dict)
        else {}
    )
    runtime_package = _canonicalize_runtime_package_alias(
        runtime_package,
        preferred_runtime_package=champion_runtime_package,
    )
    active_runtime_package = _canonicalize_runtime_package_alias(
        active_runtime_package,
        preferred_runtime_package=champion_runtime_package,
    )
    runtime_package_from_champion = bool(
        champion_runtime_package
        and isinstance(runtime_package, dict)
        and runtime_package == champion_runtime_package
    )
    confidence_summary = (
        live_package.get("confidence_summary")
        if isinstance(live_package.get("confidence_summary"), dict)
        else {}
    )
    fold_results = live_package.get("fold_results") if isinstance(live_package.get("fold_results"), list) else []
    artifact_generated_at = _parse_datetime_like(
        _first_nonempty(
            live_package.get("generated_at"),
            payload.get("updated_at"),
            _safe_iso_mtime(path),
        )
    )
    age_hours = _age_hours_from_datetimes(reference_at=generated_at, observed_at=artifact_generated_at)
    confidence_label = "unknown"
    if confidence_summary:
        confidence_label = "high"
    elif fold_results:
        confidence_label = "medium"

    summary.update(
        {
            "generated_at": artifact_generated_at.isoformat() if artifact_generated_at is not None else None,
            "age_hours": round(age_hours, 4) if age_hours is not None else None,
            "freshness": _freshness_label_for_age_hours(age_hours),
            "candidate_profile_name": _runtime_package_profile_name(runtime_package),
            "candidate_policy_id": str(
                _first_nonempty(
                    champion.get("policy_id") if champion_runtime_package == runtime_package else None,
                    live_package.get("policy_id"),
                    (payload.get("champion") or {}).get("policy_id")
                    if isinstance(payload.get("champion"), dict)
                    else None,
                    payload.get("champion_id"),
                    _runtime_package_profile_name(runtime_package),
                )
                or ""
            ).strip()
            or None,
            "active_profile_name": _runtime_package_profile_name(active_runtime_package),
            "deploy_recommendation": str(
                _first_nonempty(
                    live_package.get("deploy_recommendation"),
                    payload.get("selected_deploy_recommendation"),
                )
                or ""
            ).strip().lower()
            or None,
            "confidence_label": confidence_label,
            "promotion_state": str(
                _first_nonempty(
                    live_package.get("promotion_state"),
                    (payload.get("champion") or {}).get("promotion_state")
                    if isinstance(payload.get("champion"), dict)
                    else None,
                    payload.get("promotion_state"),
                )
                or ""
            ).strip().lower()
            or None,
            "runtime_package": runtime_package if runtime_package else None,
            "active_runtime_package": active_runtime_package if active_runtime_package else None,
            "candidate_package_hash": str(
                _first_nonempty(
                    champion.get("package_hash") if runtime_package_from_champion else None,
                    live_package.get("package_hash"),
                    payload.get("canonical_live_package_hash"),
                )
                or ""
            ).strip()
            or None,
            "active_package_hash": str(
                _first_nonempty(
                    live_package.get("package_hash"),
                    champion.get("package_hash") if runtime_package_from_champion else None,
                    payload.get("canonical_live_package_hash"),
                )
                or ""
            ).strip()
            or None,
            "source_artifact": (
                champion.get("source_artifact")
                if runtime_package_from_champion
                else live_package.get("source_artifact")
            )
            or live_package.get("source_artifact")
            or summary["path"],
            "frontier_gap_vs_incumbent": _float_or_none(
                _first_nonempty(
                    (payload.get("candidate_vs_incumbent_summary") or {}).get("mean_fold_loss_improvement")
                    if isinstance(payload.get("candidate_vs_incumbent_summary"), dict)
                    else None,
                    payload.get("loss"),
                )
            ),
        }
    )
    summary["canonical_live_profile"] = (
        str(summary.get("active_profile_name") or "").strip()
        or str(summary.get("candidate_profile_name") or "").strip()
        or None
    )
    summary["canonical_live_package_hash"] = (
        str(summary.get("active_package_hash") or "").strip()
        or str(summary.get("candidate_package_hash") or "").strip()
        or None
    )
    return summary


def _load_btc5_selected_package_summary(
    *,
    root: Path,
    generated_at: datetime | None,
) -> dict[str, Any]:
    path = root / "reports" / "btc5_autoresearch" / "latest.json"
    payload = _load_json(path, default={})
    summary = {
        "exists": path.exists() and isinstance(payload, dict),
        "path": _relative_path_text(root, path) or str(path),
        "generated_at": None,
        "age_hours": None,
        "freshness": "unknown",
        "selected_deploy_recommendation": "hold",
        "selected_package_confidence_label": "low",
        "validation_live_filled_rows": 0,
        "generalization_ratio": None,
        "selected_active_profile_name": None,
        "selected_best_profile_name": None,
        "promoted_package_selected": False,
        "runtime_package_loaded": False,
        "runtime_load_required": False,
        "selection_source": None,
        "runtime_load_evidence_source": None,
        "selected_policy_id": None,
        "selected_best_runtime_package": None,
        "selected_active_package_hash": None,
        "selected_best_package_hash": None,
        "promotion_state": None,
        "blocking_checks": [],
        "validated_for_live_stage1": False,
        "median_arr_delta_pct": None,
        "canonical_live_profile": None,
        "canonical_live_package_hash": None,
        "shadow_comparator_profile": None,
        "canonical_package_drift_detected": False,
    }
    if not summary["exists"]:
        summary["blocking_checks"] = ["selected_runtime_package_missing"]
        return summary

    payload = dict(payload)
    runtime_package_selection = (
        payload.get("runtime_package_selection")
        if isinstance(payload.get("runtime_package_selection"), dict)
        else {}
    )
    capital_stage_recommendation = (
        payload.get("capital_stage_recommendation")
        if isinstance(payload.get("capital_stage_recommendation"), dict)
        else {}
    )
    arr_tracking = payload.get("arr_tracking") if isinstance(payload.get("arr_tracking"), dict) else {}
    best_live_package = payload.get("best_live_package") if isinstance(payload.get("best_live_package"), dict) else {}
    artifact_generated_at = _parse_datetime_like(
        _first_nonempty(payload.get("generated_at"), _safe_iso_mtime(path))
    )
    age_hours = _age_hours_from_datetimes(reference_at=generated_at, observed_at=artifact_generated_at)
    freshness = _freshness_label_for_age_hours(age_hours)

    selected_deploy_recommendation = str(
        _first_nonempty(
            payload.get("selected_deploy_recommendation"),
            payload.get("deploy_recommendation"),
            "hold",
        )
        or "hold"
    ).strip().lower()
    selected_package_confidence_label = str(
        _first_nonempty(
            payload.get("selected_package_confidence_label"),
            payload.get("package_confidence_label"),
            "low",
        )
        or "low"
    ).strip().lower()
    validation_live_filled_rows = max(
        0,
        int(
            _safe_float(
                _first_nonempty(
                    payload.get("validation_live_filled_rows"),
                    capital_stage_recommendation.get("validation_live_filled_rows"),
                    0,
                ),
                0.0,
            )
            or 0
        ),
    )
    generalization_ratio = _float_or_none(payload.get("generalization_ratio"))
    selected_active_runtime_package = (
        payload.get("selected_active_runtime_package")
        if isinstance(payload.get("selected_active_runtime_package"), dict)
        else {}
    )
    selected_best_runtime_package = (
        payload.get("selected_best_runtime_package")
        if isinstance(payload.get("selected_best_runtime_package"), dict)
        else {}
    )
    selected_active_profile_name = _runtime_package_profile_name(selected_active_runtime_package)
    selected_best_profile_name = _runtime_package_profile_name(selected_best_runtime_package)
    selected_policy_id = str(selected_best_profile_name or "").strip() or None
    promotion_state = str(
        _first_nonempty(
            payload.get("promotion_state"),
            (payload.get("latest_experiment") or {}).get("promotion_state")
            if isinstance(payload.get("latest_experiment"), dict)
            else None,
        )
        or ""
    ).strip().lower() or None
    promoted_package_selected = bool(payload.get("promoted_package_selected"))
    runtime_load_required = bool(capital_stage_recommendation.get("runtime_load_required"))
    runtime_package_loaded = bool(
        _first_nonempty(
            capital_stage_recommendation.get("runtime_package_loaded"),
            promoted_package_selected,
        )
    )
    runtime_load_evidence_source = None
    override_summary = _load_btc5_runtime_override_summary(root)
    override_candidate = str(override_summary.get("candidate") or "").strip()
    frontier_gap_vs_incumbent = _float_or_none(payload.get("frontier_gap_vs_incumbent"))
    policy_live_summary = _load_btc5_policy_live_package_summary(
        root=root,
        generated_at=generated_at,
    )
    policy_candidate = str(policy_live_summary.get("candidate_profile_name") or "").strip()
    policy_promotion_state = str(policy_live_summary.get("promotion_state") or "").strip().lower()
    policy_loaded_via_override = bool(
        policy_candidate and override_candidate and policy_candidate == override_candidate
    )
    prefer_policy_live_summary = bool(
        policy_live_summary.get("exists")
        and policy_candidate
        and (
            policy_loaded_via_override
            or policy_promotion_state in {"live_promoted", "live_activated"}
        )
        and (
            freshness == "stale"
            or selected_best_profile_name != policy_candidate
            or not promoted_package_selected
        )
    )
    if prefer_policy_live_summary:
        selected_best_profile_name = policy_candidate
        selected_policy_id = str(
            _first_nonempty(
                policy_live_summary.get("candidate_policy_id"),
                policy_candidate,
            )
            or ""
        ).strip() or None
        selected_active_profile_name = (
            str(policy_live_summary.get("active_profile_name") or selected_active_profile_name or "").strip()
            or None
        )
        selected_best_runtime_package = (
            dict(policy_live_summary.get("runtime_package") or {})
            if isinstance(policy_live_summary.get("runtime_package"), dict)
            else selected_best_runtime_package
        )
        selected_deploy_recommendation = (
            str(policy_live_summary.get("deploy_recommendation") or selected_deploy_recommendation or "hold")
            .strip()
            .lower()
            or "hold"
        )
        selected_package_confidence_label = (
            str(policy_live_summary.get("confidence_label") or selected_package_confidence_label or "medium")
            .strip()
            .lower()
            or "medium"
        )
        promotion_state = (
            str(policy_live_summary.get("promotion_state") or promotion_state or "").strip().lower()
            or None
        )
        promoted_package_selected = policy_promotion_state in {"live_promoted", "live_activated"}
        runtime_package_loaded = policy_loaded_via_override or promoted_package_selected
        runtime_load_required = not runtime_package_loaded
        runtime_load_evidence_source = (
            override_summary.get("path")
            if policy_loaded_via_override
            else (policy_live_summary.get("path") if promoted_package_selected else None)
        )
        frontier_gap_vs_incumbent = _float_or_none(
            _first_nonempty(
                policy_live_summary.get("frontier_gap_vs_incumbent"),
                payload.get("frontier_gap_vs_incumbent"),
            )
        )
        artifact_generated_at = _parse_datetime_like(
            _first_nonempty(
                policy_live_summary.get("generated_at"),
                artifact_generated_at.isoformat() if artifact_generated_at is not None else None,
            )
        )
        age_hours = _age_hours_from_datetimes(reference_at=generated_at, observed_at=artifact_generated_at)
        freshness = _freshness_label_for_age_hours(age_hours)
        summary["path"] = str(policy_live_summary.get("path") or summary["path"])
        summary["selection_source"] = str(
            policy_live_summary.get("source_artifact") or policy_live_summary.get("path") or summary["path"]
        )

    selected_active_package_hash = str(
        _first_nonempty(
            policy_live_summary.get("active_package_hash"),
            policy_live_summary.get("candidate_package_hash")
            if selected_active_profile_name
            and selected_active_profile_name == str(policy_live_summary.get("candidate_profile_name") or "").strip()
            else None,
            payload.get("canonical_live_package_hash"),
        )
        or ""
    ).strip() or None
    selected_best_package_hash = str(
        _first_nonempty(
            policy_live_summary.get("candidate_package_hash"),
            payload.get("canonical_live_package_hash"),
        )
        or ""
    ).strip() or None

    if (
        runtime_load_required
        and not runtime_package_loaded
        and selected_best_profile_name
        and override_candidate == selected_best_profile_name
    ):
        runtime_package_loaded = True
        runtime_load_required = False
        promoted_package_selected = True
        runtime_load_evidence_source = override_summary.get("path")

    frontier_gap_vs_incumbent = _float_or_none(
        _first_nonempty(frontier_gap_vs_incumbent, payload.get("frontier_gap_vs_incumbent"))
    )
    if not selected_policy_id and selected_best_profile_name:
        selected_policy_id = str(selected_best_profile_name).strip() or None
    if (
        runtime_package_loaded
        and selected_best_profile_name
        and selected_active_profile_name
        and selected_best_profile_name == selected_active_profile_name
        and selected_deploy_recommendation != "promote"
    ):
        promotion_state = "live_current"
    elif not promotion_state and promoted_package_selected:
        promotion_state = "live_promoted"
    loaded_live_override_candidate = bool(
        runtime_package_loaded
        and selected_best_profile_name
        and override_candidate == selected_best_profile_name
        and selected_active_profile_name
        and selected_best_profile_name != selected_active_profile_name
    )
    shadow_stage1_candidate = bool(
        freshness != "stale"
        and selected_package_confidence_label == "high"
        and validation_live_filled_rows >= 12
        and generalization_ratio is not None
        and generalization_ratio >= 0.80
        and selected_best_profile_name
        and selected_active_profile_name
        and selected_best_profile_name != selected_active_profile_name
        and (
            (
                selected_deploy_recommendation == "shadow_only"
                and frontier_gap_vs_incumbent is not None
                and frontier_gap_vs_incumbent > 0.0
            )
            or loaded_live_override_candidate
        )
    )

    blocking_checks: list[str] = []
    if freshness == "stale":
        blocking_checks.append("selected_runtime_package_stale")
    live_promoted_policy_candidate = bool(
        prefer_policy_live_summary
        and policy_promotion_state in {"live_promoted", "live_activated"}
        and runtime_package_loaded
    )
    if (
        selected_deploy_recommendation != "promote"
        and not shadow_stage1_candidate
        and not live_promoted_policy_candidate
    ):
        blocking_checks.append("selected_runtime_package_not_promote")
    if selected_package_confidence_label not in {"medium", "high"}:
        blocking_checks.append("selected_runtime_package_confidence_below_medium")
    if validation_live_filled_rows < 6 and not live_promoted_policy_candidate:
        blocking_checks.append("selected_runtime_package_validation_rows_below_6")
    if (generalization_ratio is None or generalization_ratio < 0.70) and not live_promoted_policy_candidate:
        blocking_checks.append("selected_runtime_package_generalization_below_0.70")
    if runtime_load_required:
        blocking_checks.append("runtime_package_load_pending")
    if runtime_load_required and (not promoted_package_selected or not runtime_package_loaded):
        blocking_checks.append("validated_runtime_package_not_loaded")

    summary.update(
        {
            "generated_at": artifact_generated_at.isoformat() if artifact_generated_at is not None else None,
            "age_hours": round(age_hours, 4) if age_hours is not None else None,
            "freshness": freshness,
            "selected_deploy_recommendation": selected_deploy_recommendation or "hold",
            "selected_package_confidence_label": selected_package_confidence_label or "low",
            "validation_live_filled_rows": validation_live_filled_rows,
            "generalization_ratio": generalization_ratio,
            "selected_active_profile_name": selected_active_profile_name,
            "selected_best_profile_name": selected_best_profile_name,
            "promoted_package_selected": promoted_package_selected,
            "runtime_package_loaded": runtime_package_loaded,
            "runtime_load_required": runtime_load_required,
            "runtime_load_evidence_source": runtime_load_evidence_source,
            "selection_source": summary.get("selection_source")
            or runtime_package_selection.get("source_artifact")
            or summary["path"],
            "selected_policy_id": selected_policy_id,
            "selected_active_package_hash": selected_active_package_hash,
            "selected_best_package_hash": selected_best_package_hash,
            "selected_best_runtime_package": (
                selected_best_runtime_package
                if isinstance(selected_best_runtime_package, dict) and selected_best_runtime_package
                else None
            ),
            "promotion_state": promotion_state,
            "frontier_gap_vs_incumbent": frontier_gap_vs_incumbent,
            "stage1_live_candidate": shadow_stage1_candidate or live_promoted_policy_candidate,
            "blocking_checks": _dedupe_preserve_order(blocking_checks),
            "validated_for_live_stage1": not blocking_checks,
            "median_arr_delta_pct": _float_or_none(
                _first_nonempty(
                    best_live_package.get("median_arr_delta_pct"),
                    arr_tracking.get("median_arr_delta_pct"),
                )
            ),
        }
    )
    return summary


def _enforce_canonical_live_package(summary: dict[str, Any]) -> dict[str, Any]:
    """Enforce the one-live-package rule on the selected package summary.

    When selected_active_profile_name and selected_best_profile_name differ,
    the active profile is canonical live and the best profile is shadow-only.
    This prevents downstream consumers from seeing multiple live-ready packages.
    """
    active = str(summary.get("selected_active_profile_name") or "").strip()
    best = str(summary.get("selected_best_profile_name") or "").strip()
    summary = dict(summary)
    summary["canonical_live_profile"] = active or best or None
    summary["canonical_live_package_hash"] = (
        str(summary.get("selected_active_package_hash") or "").strip()
        or str(summary.get("selected_best_package_hash") or "").strip()
        or None
    )
    if active and best and active != best:
        summary["shadow_comparator_profile"] = best
        summary["canonical_package_drift_detected"] = True
    else:
        summary["shadow_comparator_profile"] = None
        summary["canonical_package_drift_detected"] = False
    deploy_rec = str(summary.get("selected_deploy_recommendation") or "").strip().lower()
    if summary.get("canonical_package_drift_detected") and deploy_rec == "promote":
        summary["selected_deploy_recommendation"] = "shadow_only"
    return summary


def _split_btc5_stage_blockers(
    blocking_checks: Sequence[Any],
    *,
    ready_for_stage_1: bool,
    ready_for_stage_2: bool,
    ready_for_stage_3: bool,
) -> dict[str, list[str]]:
    stage_1_checks: list[str] = []
    stage_2_checks: list[str] = []
    stage_3_checks: list[str] = []
    stage_2_specific = {
        "stage_upgrade_probe_stale",
        "insufficient_trailing_40_live_fills",
        "trailing_40_live_filled_not_positive",
        "order_failed_rate_above_stage_2_limit",
    }
    stage_3_specific = {
        "insufficient_trailing_120_live_fills",
        "trailing_120_live_filled_not_positive",
        "confirmation_coverage_insufficient",
        "wallet_flow_confirmation_missing",
        "signal_source_audit_missing",
        "signal_source_audit_stale",
        "wallet_flow_vs_llm_not_ready",
        "contradiction_penalty_high",
    }
    normalized_checks = [
        str(check).strip()
        for check in list(dict.fromkeys(blocking_checks or []))
        if str(check).strip()
    ]
    for check in normalized_checks:
        lowered = check.lower()
        if (
            lowered.startswith("wallet_export_")
            or lowered.startswith("stage_1_")
            or lowered.startswith("trailing_12_")
            or lowered.startswith("insufficient_trailing_12_")
            or lowered == "order_failed_rate_above_stage_1_limit"
            or lowered == "btc5_forecast_not_promote_high"
        ):
            stage_1_checks.append(check)
            stage_2_checks.append(check)
            stage_3_checks.append(check)
            continue
        if lowered in stage_2_specific:
            stage_2_checks.append(check)
            stage_3_checks.append(check)
            continue
        if lowered in stage_3_specific:
            stage_3_checks.append(check)
            continue
        if not ready_for_stage_1:
            stage_1_checks.append(check)
        if not ready_for_stage_2:
            stage_2_checks.append(check)
        if not ready_for_stage_3:
            stage_3_checks.append(check)

    return {
        "stage_1_blockers": _dedupe_preserve_order(stage_1_checks),
        "stage_2_blockers": _dedupe_preserve_order(stage_2_checks),
        "stage_3_blockers": _dedupe_preserve_order(stage_3_checks),
    }


def _btc5_probe_activity_timestamp(btc5_maker: dict[str, Any]) -> datetime | None:
    latest_trade = btc5_maker.get("latest_trade") if isinstance(btc5_maker.get("latest_trade"), dict) else {}
    return _parse_datetime_like(
        _first_nonempty(
            btc5_maker.get("latest_live_filled_at"),
            latest_trade.get("updated_at"),
            latest_trade.get("created_at"),
            btc5_maker.get("checked_at"),
        )
    )


def _build_btc5_stage_readiness(
    *,
    scale_summary: dict[str, Any],
    audit_summary: dict[str, Any],
    current_probe_summary: dict[str, Any],
) -> dict[str, Any]:
    stage_payload = dict(scale_summary.get("stage_readiness") or {})
    allowed_stage = int(scale_summary.get("stage_recommended") or stage_payload.get("recommended_stage") or 0)
    ready_for_stage_1 = bool(scale_summary.get("ready_for_stage_1") or allowed_stage >= 1)
    ready_for_stage_2 = bool(scale_summary.get("ready_for_stage_2") or allowed_stage >= 2)
    ready_for_stage_3 = bool(scale_summary.get("ready_for_stage_3") or allowed_stage >= 3)
    blocking_checks = list(scale_summary.get("stage_blocking_checks") or [])
    reasons = list(scale_summary.get("stage_reasons") or [])

    if not scale_summary.get("exists"):
        blocking_checks.append("strategy_scale_comparison_missing")
        reasons.append("BTC5 stage readiness is missing because reports/strategy_scale_comparison.json is absent.")
    elif scale_summary.get("freshness") == "stale":
        blocking_checks.append("strategy_scale_comparison_stale")
        reasons.append("BTC5 stage readiness is using a stale strategy-scale comparison artifact.")

    stage_blockers = _split_btc5_stage_blockers(
        blocking_checks,
        ready_for_stage_1=ready_for_stage_1,
        ready_for_stage_2=ready_for_stage_2,
        ready_for_stage_3=ready_for_stage_3,
    )
    stage_2_blockers = list(stage_blockers["stage_2_blockers"])
    stage_3_blockers = list(stage_blockers["stage_3_blockers"])

    audit_blockers = list(audit_summary.get("stage_upgrade_blocking_checks") or [])
    if not audit_summary.get("exists"):
        audit_blockers.append("signal_source_audit_missing")
    elif audit_summary.get("freshness") == "stale":
        audit_blockers.append("signal_source_audit_stale")
    stage_3_blockers = _dedupe_preserve_order([*stage_3_blockers, *audit_blockers])

    trade_now_ready = allowed_stage >= 1 and not stage_blockers["stage_1_blockers"]
    trade_now_blockers = [] if trade_now_ready else (
        list(stage_blockers["stage_1_blockers"]) or list(dict.fromkeys(blocking_checks))
    )
    trade_now_reasons = [] if trade_now_ready else (
        reasons or ["BTC5 stage_1 readiness is blocked by launch gating checks."]
    )

    return {
        "source_artifact": scale_summary.get("path"),
        "source_artifacts": list(
            dict.fromkeys(
                [
                    str(scale_summary.get("path") or "reports/strategy_scale_comparison.json"),
                    *list(scale_summary.get("source_artifacts") or []),
                    str(current_probe_summary.get("path") or "reports/btc5_autoresearch_current_probe/latest.json"),
                    str(audit_summary.get("path") or "reports/signal_source_audit.json"),
                ]
            )
        ),
        "generated_at": scale_summary.get("generated_at"),
        "freshness": scale_summary.get("freshness") or "unknown",
        "age_hours": _float_or_none(scale_summary.get("age_hours")),
        "allowed_stage": allowed_stage,
        "allowed_stage_label": f"stage_{allowed_stage}",
        "ready_for_stage_1": ready_for_stage_1,
        "ready_for_stage_2": ready_for_stage_2,
        "ready_for_stage_3": ready_for_stage_3,
        "can_trade_now": trade_now_ready,
        "trade_now_status": "unblocked" if trade_now_ready else "blocked",
        "trade_now_blocking_checks": _dedupe_preserve_order(trade_now_blockers),
        "trade_now_reasons": trade_now_reasons,
        "blocking_checks": _dedupe_preserve_order(blocking_checks),
        "reasons": reasons,
        "stage_1_blockers": stage_blockers["stage_1_blockers"],
        "stage_2_blockers": stage_2_blockers,
        "stage_3_blockers": stage_3_blockers,
        "wallet_export_freshness_hours": _float_or_none(
            scale_summary.get("wallet_export_freshness_hours")
        ),
        "probe_freshness_hours": _float_or_none(
            _first_nonempty(
                scale_summary.get("probe_freshness_hours"),
                current_probe_summary.get("probe_freshness_hours"),
            )
        ),
        "current_probe_artifact": current_probe_summary.get("path"),
        "current_probe_freshness": current_probe_summary.get("freshness") or "unknown",
        "current_probe_generated_at": current_probe_summary.get("generated_at"),
        "current_probe_stage_ready_reason_tags": list(
            current_probe_summary.get("stage_ready_reason_tags") or []
        ),
        "current_probe_stage_not_ready_reason_tags": list(
            current_probe_summary.get("stage_not_ready_reason_tags") or []
        ),
    }


def _build_source_precedence(
    *,
    root: Path,
    generated_at: datetime,
    service: dict[str, Any],
    polymarket_wallet: dict[str, Any],
    btc5_maker: dict[str, Any],
    accounting_reconciliation: dict[str, Any],
    wallet_reconciliation_summary: dict[str, Any],
) -> dict[str, Any]:
    service_freshness = _source_freshness_confidence(
        checked_at=service.get("checked_at"),
        source_status=service.get("status") or "unknown",
        source_path=service.get("source") or "reports/remote_service_status.json",
    )
    remote_wallet_freshness = (
        ((accounting_reconciliation.get("source_confidence_freshness") or {}).get("remote_wallet"))
        or {}
    )
    btc5_freshness = (
        ((accounting_reconciliation.get("source_confidence_freshness") or {}).get("btc_5min_maker"))
        or {}
    )
    local_ledger_freshness = (
        ((accounting_reconciliation.get("source_confidence_freshness") or {}).get("local_ledger"))
        or {}
    )

    wallet_reporting_precedence = str(
        wallet_reconciliation_summary.get("reporting_precedence") or "btc5_runtime_db"
    ).strip().lower()
    wallet_selected_source = _first_nonempty(
        wallet_reconciliation_summary.get("source_artifact"),
        wallet_reconciliation_summary.get("btc5_probe_source_class"),
        "remote_wallet_probe",
    )
    wallet_freshness_label = str(
        _first_nonempty(
            wallet_reconciliation_summary.get("wallet_export_freshness_label"),
            remote_wallet_freshness.get("freshness"),
            "unknown",
        )
    ).strip().lower()
    if wallet_reporting_precedence != "wallet_export":
        wallet_freshness_label = str(
            _first_nonempty(
                wallet_reconciliation_summary.get("btc5_probe_freshness_label"),
                btc5_freshness.get("freshness"),
                wallet_freshness_label,
            )
        ).strip().lower()

    remote_wallet_selected = (
        remote_wallet_freshness.get("freshness") in {"fresh", "aging"}
        and polymarket_wallet.get("status") == "ok"
    )
    selected_position_source = (
        "remote_wallet"
        if remote_wallet_selected
        else _first_nonempty(
            (accounting_reconciliation.get("local_ledger_counts") or {}).get("source"),
            "data/jj_trades.db",
        )
    )
    selected_position_value = (
        accounting_reconciliation.get("remote_wallet_counts")
        if remote_wallet_selected
        else accounting_reconciliation.get("local_ledger_counts")
    ) or {}

    service_age_hours = _float_or_none(service_freshness.get("age_minutes"))
    if service_age_hours is not None:
        service_age_hours = round(service_age_hours / 60.0, 4)
    btc5_activity_at = _btc5_probe_activity_timestamp(btc5_maker)
    btc5_activity_age_hours = _age_hours_from_datetimes(
        reference_at=generated_at,
        observed_at=btc5_activity_at,
    )

    contradictions: list[dict[str, Any]] = []
    if (
        wallet_reporting_precedence == "wallet_export"
        and str(wallet_reconciliation_summary.get("btc5_probe_freshness_label") or "").strip().lower() == "stale"
    ):
        contradictions.append(
            {
                "code": "wallet_export_fresher_than_btc5_probe",
                "severity": "warning",
                "message": (
                    "Fresh wallet-export reporting overrides the stale BTC5 probe for sleeve accounting truth."
                ),
                "selected_source": wallet_selected_source,
                "shadowed_source": wallet_reconciliation_summary.get("btc5_probe_source_class") or "btc5_probe",
            }
        )
    if (
        service_freshness.get("freshness") == "stale"
        and btc5_freshness.get("freshness") in {"fresh", "aging"}
        and btc5_activity_age_hours is not None
        and btc5_activity_age_hours <= 1.5
    ):
        contradictions.append(
            {
                "code": "stale_service_file_with_fresh_btc5_probe",
                "severity": "warning",
                "message": (
                    "The remote service status file is stale while the BTC5 probe shows fresh sleeve activity; do not infer BTC5 readiness from the service file alone."
                ),
                "selected_source": btc5_maker.get("source") or btc5_maker.get("db_path") or "btc5_probe",
                "shadowed_source": service.get("source") or "reports/remote_service_status.json",
                "service_age_hours": service_age_hours,
                "btc5_activity_age_hours": round(btc5_activity_age_hours, 4),
            }
        )
    if (
        remote_wallet_selected
        and bool(accounting_reconciliation.get("drift_detected"))
        and (
            int(((accounting_reconciliation.get("unmatched_open_positions") or {}).get("absolute_delta") or 0)) > 0
            or int(((accounting_reconciliation.get("unmatched_closed_positions") or {}).get("absolute_delta") or 0)) > 0
        )
    ):
        contradictions.append(
            {
                "code": "local_ledger_drift_vs_remote_wallet",
                "severity": "warning",
                "message": (
                    "Fresh remote wallet counts override the local ledger for position truth because the local ledger is drifting."
                ),
                "selected_source": "remote_wallet",
                "shadowed_source": (accounting_reconciliation.get("local_ledger_counts") or {}).get("source"),
            }
        )

    fields = [
        {
            "field": "wallet_reporting",
            "selected_source": wallet_selected_source,
            "fallback_sources": [
                "remote_wallet_probe",
                btc5_maker.get("source") or btc5_maker.get("db_path") or "data/btc_5min_maker.db",
            ],
            "selected_value": wallet_reporting_precedence,
            "freshness": wallet_freshness_label,
            "reason": wallet_reconciliation_summary.get("reporting_precedence_reason"),
        },
        {
            "field": "btc5_runtime_activity",
            "selected_source": btc5_maker.get("source") or btc5_maker.get("db_path") or "unavailable",
            "fallback_sources": ["data/btc_5min_maker.db"],
            "selected_value": {
                "status": btc5_maker.get("status"),
                "checked_at": btc5_maker.get("checked_at"),
                "latest_live_filled_at": btc5_maker.get("latest_live_filled_at"),
            },
            "freshness": btc5_freshness.get("freshness") or "unknown",
            "reason": "fresh_btc5_probe" if btc5_freshness.get("freshness") == "fresh" else "btc5_probe_fallback",
        },
        {
            "field": "service_status",
            "selected_source": service.get("source") or "reports/remote_service_status.json",
            "fallback_sources": ["local_systemctl", "reports/runtime_truth_latest.json"],
            "selected_value": service.get("status"),
            "freshness": service_freshness.get("freshness") or "unknown",
            "reason": (
                "stale_service_file_retained_for_service_unit_status"
                if service_freshness.get("freshness") == "stale"
                else "fresh_service_status_file"
            ),
        },
        {
            "field": "position_counts",
            "selected_source": selected_position_source,
            "fallback_sources": [
                "remote_wallet",
                (accounting_reconciliation.get("local_ledger_counts") or {}).get("source") or "data/jj_trades.db",
            ],
            "selected_value": selected_position_value,
            "freshness": (
                remote_wallet_freshness.get("freshness")
                if selected_position_source == "remote_wallet"
                else local_ledger_freshness.get("freshness")
            )
            or "unknown",
            "reason": (
                "fresh_remote_wallet_supersedes_local_ledger_drift"
                if selected_position_source == "remote_wallet" and accounting_reconciliation.get("drift_detected")
                else "local_ledger_counts_retained"
            ),
        },
    ]

    truth_domains = {
        "launch": {
            "selected_source": "reports/launch_packet_latest.json",
            "fallback_sources": [
                "reports/runtime_truth_latest.json",
                "reports/remote_cycle_status.json",
            ],
            "reason": "canonical_launch_packet_contract",
        },
        "stage": {
            "selected_source": "reports/strategy_scale_comparison.json",
            "fallback_sources": [
                "reports/btc5_autoresearch_current_probe/latest.json",
                "reports/btc5_autoresearch/latest.json",
            ],
            "reason": "stage_readiness_with_probe_guardrails",
        },
        "pnl": {
            "selected_source": btc5_maker.get("source") or btc5_maker.get("db_path") or "data/btc_5min_maker.db",
            "fallback_sources": [
                wallet_selected_source,
                "reports/runtime_truth_latest.json",
            ],
            "reason": "freshest_live_fill_surface",
        },
        "candidate_flow": {
            "selected_source": "reports/fast_market_search/latest.json",
            "fallback_sources": [
                "reports/edge_scan_*.json",
                "reports/pipeline_*.json",
            ],
            "reason": "lane_candidates_and_blockers",
        },
        "capital": {
            "selected_source": "remote_wallet",
            "fallback_sources": [
                (accounting_reconciliation.get("local_ledger_counts") or {}).get("source") or "data/jj_trades.db",
                "reports/finance/latest.json",
            ],
            "reason": "remote_wallet_for_live_capital_truth",
        },
    }

    stale_input_fields = [
        str(item.get("field"))
        for item in fields
        if isinstance(item, dict) and str(item.get("freshness") or "").strip().lower() == "stale"
    ]

    return {
        "rule": (
            "Use the freshest artifact per truth domain: wallet export for wallet reporting, BTC5 probe for BTC5 activity, "
            "remote wallet for position counts when the local ledger drifts, and stale service files remain advisory only."
        ),
        "fields": fields,
        "truth_domains": truth_domains,
        "stale_input_fields": stale_input_fields,
        "contradictions": contradictions,
    }


def _build_deployment_confidence(
    *,
    service: dict[str, Any],
    accounting_reconciliation: dict[str, Any],
    btc5_stage_readiness: dict[str, Any],
    source_precedence: dict[str, Any],
    scale_summary: dict[str, Any],
    audit_summary: dict[str, Any],
    wallet_reconciliation_summary: dict[str, Any],
    current_probe_summary: dict[str, Any],
    selected_package_summary: dict[str, Any],
) -> dict[str, Any]:
    service_freshness = _source_freshness_confidence(
        checked_at=service.get("checked_at"),
        source_status=service.get("status") or "unknown",
        source_path=service.get("source") or "reports/remote_service_status.json",
    )
    remote_wallet_freshness = (
        ((accounting_reconciliation.get("source_confidence_freshness") or {}).get("remote_wallet"))
        or {}
    )
    btc5_freshness = (
        ((accounting_reconciliation.get("source_confidence_freshness") or {}).get("btc_5min_maker"))
        or {}
    )
    wallet_freshness_label = str(
        _first_nonempty(
            wallet_reconciliation_summary.get("wallet_export_freshness_label"),
            remote_wallet_freshness.get("freshness"),
            "unknown",
        )
    ).strip().lower()
    if str(wallet_reconciliation_summary.get("reporting_precedence") or "").strip().lower() != "wallet_export":
        wallet_freshness_label = str(
            _first_nonempty(
                wallet_reconciliation_summary.get("btc5_probe_freshness_label"),
                btc5_freshness.get("freshness"),
                wallet_freshness_label,
            )
        ).strip().lower()

    freshness_score = round(
        (
            0.35 * _freshness_score_for_label(wallet_freshness_label)
            + 0.35 * _freshness_score_for_label(
                _first_nonempty(
                    btc5_freshness.get("freshness"),
                    current_probe_summary.get("freshness"),
                    "unknown",
                )
            )
            + 0.15 * _freshness_score_for_label(service_freshness.get("freshness"))
            + 0.15 * _freshness_score_for_label(scale_summary.get("freshness"))
        ),
        4,
    )

    open_delta = int(
        ((accounting_reconciliation.get("unmatched_open_positions") or {}).get("absolute_delta") or 0)
    )
    closed_delta = int(
        ((accounting_reconciliation.get("unmatched_closed_positions") or {}).get("absolute_delta") or 0)
    )
    capital_delta = abs(_safe_float(accounting_reconciliation.get("capital_accounting_delta_usd"), 0.0))
    accounting_score = 1.0
    if str((accounting_reconciliation.get("remote_wallet_counts") or {}).get("status") or "").strip().lower() != "ok":
        accounting_score = 0.2
    else:
        accounting_score -= min(open_delta * 0.05, 0.25)
        accounting_score -= min(closed_delta * 0.01, 0.35)
        accounting_score -= min((capital_delta / 250.0) * 0.35, 0.35)
    accounting_coherence_score = round(min(max(accounting_score, 0.0), 1.0), 4)

    allowed_stage = int(btc5_stage_readiness.get("allowed_stage") or 0)
    stage_readiness_score = {0: 0.15, 1: 0.55, 2: 0.8, 3: 1.0}.get(allowed_stage, 0.15)
    if str(scale_summary.get("freshness") or "").strip().lower() == "stale":
        stage_readiness_score = max(0.1, stage_readiness_score - 0.1)
    stage_readiness_score = round(stage_readiness_score, 4)

    confirmation_coverage_score = _normalize_unit_score(audit_summary.get("confirmation_coverage_score"))
    if confirmation_coverage_score is None:
        confirmation_coverage_score = 0.1
    confirmation_evidence_score = _normalize_unit_score(
        _first_nonempty(
            audit_summary.get("confirmation_evidence_score"),
            audit_summary.get("confirmation_strength_score"),
            audit_summary.get("confirmation_coverage_score"),
        )
    )
    if confirmation_evidence_score is None:
        confirmation_evidence_score = confirmation_coverage_score
    confirmation_freshness_label = str(
        audit_summary.get("confirmation_freshness_label") or ""
    ).strip().lower()
    confirmation_live_support = (
        confirmation_evidence_score >= 0.4 and confirmation_freshness_label != "stale"
    )

    contradiction_codes = [
        str(item.get("code"))
        for item in list(source_precedence.get("contradictions") or [])
        if isinstance(item, dict) and str(item.get("code") or "").strip()
    ]
    allow_stage1_without_selected_package = (
        not bool(selected_package_summary.get("exists"))
        and int(btc5_stage_readiness.get("allowed_stage") or 0) >= 1
    )
    selected_package_blocking_checks = list(selected_package_summary.get("blocking_checks") or [])
    if allow_stage1_without_selected_package:
        selected_package_blocking_checks = [
            check
            for check in selected_package_blocking_checks
            if str(check) != "selected_runtime_package_missing"
        ]
    validated_for_live_stage1 = bool(
        selected_package_summary.get("validated_for_live_stage1")
    ) or allow_stage1_without_selected_package

    trade_now_blocking_checks = list(
        btc5_stage_readiness.get("trade_now_blocking_checks") or []
    )
    stage_1_blockers = _dedupe_preserve_order(
        [
            *trade_now_blocking_checks,
            *list(btc5_stage_readiness.get("stage_1_blockers") or []),
            *selected_package_blocking_checks,
            *(
                ["accounting_reconciliation_drift"]
                if bool(accounting_reconciliation.get("drift_detected"))
                else []
            ),
            *(
                ["service_status_stale"]
                if service_freshness.get("freshness") == "stale"
                else []
            ),
            *(
                ["confirmation_coverage_insufficient"]
                if confirmation_evidence_score < 0.4
                else []
            ),
            *(
                ["confirmation_evidence_stale"]
                if confirmation_freshness_label == "stale"
                else []
            ),
            *contradiction_codes,
        ]
    )
    stage_2_blockers = _dedupe_preserve_order(
        [
            *stage_1_blockers,
            *list(btc5_stage_readiness.get("stage_2_blockers") or []),
        ]
    )
    stage_3_blockers = _dedupe_preserve_order(
        [
            *stage_2_blockers,
            *list(btc5_stage_readiness.get("stage_3_blockers") or []),
        ]
    )
    blocking_checks = _dedupe_preserve_order(
        [
            *selected_package_blocking_checks,
            *trade_now_blocking_checks,
            *list(btc5_stage_readiness.get("stage_2_blockers") or []),
            *list(btc5_stage_readiness.get("stage_3_blockers") or []),
            *(
                ["accounting_reconciliation_drift"]
                if bool(accounting_reconciliation.get("drift_detected"))
                else []
            ),
            *(
                ["service_status_stale"]
                if service_freshness.get("freshness") == "stale"
                else []
            ),
            *(
                ["confirmation_coverage_insufficient"]
                if confirmation_evidence_score < 0.4
                else []
            ),
            *(
                ["confirmation_evidence_stale"]
                if confirmation_freshness_label == "stale"
                else []
            ),
            *contradiction_codes,
        ]
    )

    next_required_artifact = None
    if not selected_package_summary.get("exists") and not allow_stage1_without_selected_package:
        next_required_artifact = "reports/btc5_autoresearch/latest.json"
    elif any(
        check in blocking_checks
        for check in (
            "selected_runtime_package_stale",
            "selected_runtime_package_not_promote",
            "selected_runtime_package_confidence_below_medium",
            "selected_runtime_package_validation_rows_below_6",
            "selected_runtime_package_generalization_below_0.70",
            "runtime_package_load_pending",
            "validated_runtime_package_not_loaded",
        )
    ):
        next_required_artifact = "reports/btc5_autoresearch/latest.json"
    elif not scale_summary.get("exists"):
        next_required_artifact = "reports/strategy_scale_comparison.json"
    elif any(
        check in blocking_checks
        for check in ("stage_upgrade_probe_stale", "stage_1_probe_missing")
    ):
        next_required_artifact = "reports/btc5_autoresearch_current_probe/latest.json"
    elif any(str(check).startswith("wallet_export_") for check in blocking_checks):
        next_required_artifact = "data/Polymarket-History-*.csv"
    elif "stale_service_file_with_fresh_btc5_probe" in contradiction_codes or "service_status_stale" in blocking_checks:
        next_required_artifact = "reports/remote_service_status.json"
    elif "accounting_reconciliation_drift" in blocking_checks:
        next_required_artifact = "data/jj_trades.db"
    elif "confirmation_evidence_stale" in blocking_checks:
        next_required_artifact = audit_summary.get("confirmation_next_required_artifact")
        if not next_required_artifact:
            next_required_artifact = "reports/signal_source_audit.json"
    elif any(
        check in blocking_checks
        for check in (
            "confirmation_coverage_insufficient",
            "signal_source_audit_missing",
            "signal_source_audit_stale",
            "wallet_flow_confirmation_missing",
        )
    ):
        next_required_artifact = "reports/signal_source_audit.json"
    elif current_probe_summary.get("exists") is False:
        next_required_artifact = "reports/btc5_autoresearch_current_probe/latest.json"

    overall_score = round(
        (
            0.3 * freshness_score
            + 0.35 * accounting_coherence_score
            + 0.25 * stage_readiness_score
            + 0.1 * confirmation_evidence_score
        ),
        4,
    )
    confidence_label = _confidence_label_for_score(overall_score)
    if not validated_for_live_stage1:
        overall_score = min(overall_score, 0.49)
        confidence_label = "low"
    elif confirmation_evidence_score < 0.4 or confirmation_freshness_label == "stale":
        overall_score = min(overall_score, 0.49)
        confidence_label = "low"
    elif accounting_coherence_score < 0.35 or freshness_score < 0.3:
        confidence_label = "low"

    return {
        "confidence_label": confidence_label,
        "overall_score": overall_score,
        "freshness_score": freshness_score,
        "accounting_coherence_score": accounting_coherence_score,
        "stage_readiness_score": stage_readiness_score,
        "confirmation_coverage_score": round(confirmation_coverage_score, 4),
        "confirmation_evidence_score": round(confirmation_evidence_score, 4),
        "confirmation_support_status": audit_summary.get("confirmation_support_status"),
        "confirmation_coverage_label": audit_summary.get("confirmation_coverage_label"),
        "confirmation_strength_label": audit_summary.get("confirmation_strength_label"),
        "confirmation_strength_score": audit_summary.get("confirmation_strength_score"),
        "confirmation_freshness_label": confirmation_freshness_label or "unknown",
        "confirmation_sources_ready": list(audit_summary.get("confirmation_sources_ready") or []),
        "best_confirmation_source": audit_summary.get("best_confirmation_source"),
        "confirmation_contradiction_penalty": audit_summary.get("confirmation_contradiction_penalty"),
        "confirmation_next_required_artifact": audit_summary.get("confirmation_next_required_artifact"),
        "can_btc5_trade_now": (
            int(btc5_stage_readiness.get("allowed_stage") or 0) >= 1
            and not stage_1_blockers
            and validated_for_live_stage1
            and confirmation_live_support
        ),
        "allowed_stage": allowed_stage,
        "allowed_stage_label": btc5_stage_readiness.get("allowed_stage_label") or f"stage_{allowed_stage}",
        "stage_1_blockers": list(stage_1_blockers),
        "stage_2_blockers": list(stage_2_blockers),
        "stage_3_blockers": list(stage_3_blockers),
        "blocking_checks": blocking_checks,
        "warning_checks": contradiction_codes,
        "next_required_artifact": next_required_artifact,
        "service_status_freshness": service_freshness.get("freshness") or "unknown",
        "wallet_reporting_precedence": wallet_reconciliation_summary.get("reporting_precedence"),
        "current_probe_freshness": current_probe_summary.get("freshness") or "unknown",
        "validated_package": {
            "source_artifact": selected_package_summary.get("selection_source")
            or selected_package_summary.get("path"),
            "freshness": selected_package_summary.get("freshness") or "unknown",
            "generated_at": selected_package_summary.get("generated_at"),
            "selected_deploy_recommendation": selected_package_summary.get(
                "selected_deploy_recommendation"
            )
            or "hold",
            "selected_package_confidence_label": selected_package_summary.get(
                "selected_package_confidence_label"
            )
            or "low",
            "validation_live_filled_rows": int(
                selected_package_summary.get("validation_live_filled_rows") or 0
            ),
            "generalization_ratio": _float_or_none(
                selected_package_summary.get("generalization_ratio")
            ),
            "selected_active_profile_name": selected_package_summary.get(
                "selected_active_profile_name"
            ),
            "selected_best_profile_name": selected_package_summary.get(
                "selected_best_profile_name"
            ),
            "promoted_package_selected": bool(
                selected_package_summary.get("promoted_package_selected")
            ),
            "runtime_package_loaded": bool(selected_package_summary.get("runtime_package_loaded")),
            "runtime_load_required": bool(selected_package_summary.get("runtime_load_required")),
            "validated_for_live_stage1": validated_for_live_stage1,
            "blocking_checks": list(selected_package_summary.get("blocking_checks") or []),
        },
    }


def _attach_control_plane_consistency(snapshot: dict[str, Any], *, root: Path) -> None:
    strategy = (
        (((snapshot.get("state_improvement") or {}).get("strategy_recommendations")) or {})
        if isinstance(snapshot, dict)
        else {}
    )
    scoreboard = dict(strategy.get("public_performance_scoreboard") or {})
    capital_readiness = dict(strategy.get("capital_addition_readiness") or {})
    generated_at = _parse_datetime_like(snapshot.get("generated_at"))

    drift_flags = dict(snapshot.get("drift_flags") or {})
    mode = dict(snapshot.get("mode_reconciliation") or {})
    remote_probe_alignment = dict(mode.get("remote_probe_alignment") or {})
    local_env = dict(mode.get("local_env") or {})
    remote_mode = dict(mode.get("remote_mode") or {})
    remote_values = dict(remote_mode.get("values") or {})
    selected_profile = str(mode.get("selected_profile") or "").strip()
    local_selector = str(local_env.get("JJ_RUNTIME_PROFILE") or "").strip()
    remote_selector = str(remote_values.get("JJ_RUNTIME_PROFILE") or "").strip()
    observed_remote_runtime_profile = str(
        _first_nonempty(
            snapshot.get("remote_runtime_profile"),
            remote_mode.get("remote_runtime_profile"),
        )
        or ""
    ).strip()
    profile_mismatch_reasons: list[str] = []
    if bool(drift_flags.get("profile_override_drift")):
        profile_mismatch_reasons.append("profile_override_drift")
    if local_selector and selected_profile and local_selector != selected_profile:
        profile_mismatch_reasons.append("local_selector_differs_from_selected_profile")
    if remote_selector and selected_profile and remote_selector != selected_profile:
        profile_mismatch_reasons.append("remote_selector_differs_from_selected_profile")
    if observed_remote_runtime_profile and selected_profile and observed_remote_runtime_profile != selected_profile:
        profile_mismatch_reasons.append("observed_remote_runtime_profile_differs_from_selected_profile")
    if remote_selector and observed_remote_runtime_profile and remote_selector != observed_remote_runtime_profile:
        profile_mismatch_reasons.append("remote_selector_differs_from_observed_remote_runtime_profile")
    profile_mismatch_reasons.extend(
        str(item)
        for item in (remote_probe_alignment.get("feature_mismatches") or [])
        if str(item).strip()
    )
    profile_mismatch_reasons.extend(
        str(item)
        for item in (remote_probe_alignment.get("count_mismatches") or [])
        if str(item).strip()
    )
    profile_mismatch_reasons = _dedupe_preserve_order(profile_mismatch_reasons)

    service_mismatch_reasons: list[str] = []
    expected_primary_service = "btc-5min-maker.service"
    service_state = str((snapshot.get("service") or {}).get("status") or "unknown").strip().lower()
    observed_service_name = str((snapshot.get("service") or {}).get("service_name") or "").strip()
    btc5_source = str((snapshot.get("runtime") or {}).get("btc5_source") or "").strip().lower()
    launch_posture = str((snapshot.get("launch") or {}).get("posture") or "unknown").strip().lower()
    if observed_service_name and observed_service_name != expected_primary_service:
        service_mismatch_reasons.append(
            f"service_target_mismatch: expected {expected_primary_service}, observed {observed_service_name}"
        )
    if bool(drift_flags.get("service_running_while_launch_blocked")):
        service_mismatch_reasons.append("jj_live_non_primary_running_while_launch_blocked")
    if service_state == "running" and btc5_source in {"unavailable", "missing_data/btc_5min_maker.db", ""}:
        service_mismatch_reasons.append("service_running_without_btc5_runtime_source")
    if launch_posture == "blocked" and service_state == "running":
        service_mismatch_reasons.append("launch_blocked_but_service_running")
    service_mismatch_reasons = _dedupe_preserve_order(service_mismatch_reasons)

    wallet_reconciliation_summary = dict(scoreboard.get("wallet_reconciliation_summary") or {})
    precedence = str(wallet_reconciliation_summary.get("reporting_precedence") or "").strip().lower()
    realized_mode = str(scoreboard.get("realized_btc5_sleeve_window_mode") or "").strip().lower()
    wallet_export_freshness = str(
        wallet_reconciliation_summary.get("wallet_export_freshness_label") or "unknown"
    ).strip().lower()
    btc5_probe_freshness = str(
        wallet_reconciliation_summary.get("btc5_probe_freshness_label") or "unknown"
    ).strip().lower()
    truth_source_reasons: list[str] = []
    if wallet_export_freshness == "fresh" and btc5_probe_freshness == "stale":
        truth_source_reasons.append("fresh_wallet_export_with_stale_btc5_probe")
    if (
        wallet_export_freshness in {"fresh", "aging"}
        and btc5_probe_freshness == "stale"
        and precedence != "wallet_export"
    ):
        truth_source_reasons.append("fresh_wallet_export_not_selected_while_btc5_probe_stale")
    if wallet_export_freshness == "stale" and precedence == "wallet_export":
        truth_source_reasons.append("stale_wallet_export_selected_for_reporting")
    truth_source_reasons = _dedupe_preserve_order(truth_source_reasons)

    scale_recommendation = _load_strategy_scale_comparison_summary(root=root, generated_at=generated_at)
    audit_summary = _load_signal_source_audit_summary(root=root, generated_at=generated_at)
    capital_conflicts: list[str] = []
    if precedence == "wallet_export" and realized_mode and realized_mode != "wallet_closed_batch":
        capital_conflicts.append("wallet_export_precedence_not_reflected_in_realized_window_mode")
    fund_status = str((capital_readiness.get("fund") or {}).get("status") or "").strip().lower()
    next_1000_status = str((capital_readiness.get("next_1000_usd") or {}).get("status") or "").strip().lower()
    if fund_status == "hold" and next_1000_status not in {"", "hold"}:
        capital_conflicts.append("fund_hold_conflicts_with_next_1000_status")
    deploy_recommendation = str(scoreboard.get("deploy_recommendation") or "").strip().lower()
    polymarket_status = str((capital_readiness.get("polymarket_btc5") or {}).get("status") or "").strip().lower()
    if deploy_recommendation == "hold" and polymarket_status in {"ready_test_tranche", "ready_scale"}:
        capital_conflicts.append("forecast_hold_conflicts_with_polymarket_ready_status")
    scale_polymarket_status = str(scale_recommendation.get("polymarket_btc5_status") or "").strip().lower()
    if scale_polymarket_status and polymarket_status and scale_polymarket_status != polymarket_status:
        capital_conflicts.append(
            f"polymarket_btc5_status_conflict: runtime={polymarket_status} strategy_scale={scale_polymarket_status}"
        )
    scale_next_1000_status = str(scale_recommendation.get("next_1000_status") or "").strip().lower()
    if scale_next_1000_status and next_1000_status and scale_next_1000_status != next_1000_status:
        capital_conflicts.append(
            f"next_1000_status_conflict: runtime={next_1000_status} strategy_scale={scale_next_1000_status}"
        )
    audit_stage_status = str(audit_summary.get("stage_upgrade_support_status") or "").strip().lower()
    wallet_flow_confirmation_ready = audit_summary.get("wallet_flow_confirmation_ready")
    if audit_stage_status == "limited" and polymarket_status in {"ready_test_tranche", "ready_scale"}:
        capital_conflicts.append("signal_source_audit_limits_stage_upgrade_but_runtime_promotes_btc5")
    if audit_stage_status == "limited" and scale_next_1000_status in {"ready_test_tranche", "ready_scale"}:
        capital_conflicts.append("signal_source_audit_limits_stage_upgrade_but_strategy_scale_promotes")
    if wallet_flow_confirmation_ready is False and next_1000_status in {"ready_test_tranche", "ready_scale"}:
        capital_conflicts.append("wallet_flow_confirmation_missing_for_runtime_capital_upgrade")
    capital_conflicts = _dedupe_preserve_order(capital_conflicts)

    consistency = {
        "profile_consistency": {
            "status": "mismatch" if profile_mismatch_reasons else "consistent",
            "reasons": profile_mismatch_reasons,
            "selected_profile": selected_profile or None,
            "local_selector": local_selector or None,
            "remote_selector": remote_selector or None,
            "observed_remote_runtime_profile": observed_remote_runtime_profile or None,
        },
        "service_consistency": {
            "status": "mismatch" if service_mismatch_reasons else "consistent",
            "reasons": service_mismatch_reasons,
            "expected_primary_service": expected_primary_service,
            "observed_service_name": observed_service_name or None,
            "observed_service_status": service_state or "unknown",
        },
        "truth_source_consistency": {
            "status": "mismatch" if truth_source_reasons else "consistent",
            "reasons": truth_source_reasons,
            "reporting_precedence": precedence or "unknown",
            "reporting_precedence_reason": wallet_reconciliation_summary.get("reporting_precedence_reason"),
            "wallet_export_freshness": wallet_export_freshness,
            "wallet_export_age_hours": _float_or_none(wallet_reconciliation_summary.get("source_age_hours")),
            "btc5_probe_freshness": btc5_probe_freshness,
            "btc5_probe_age_hours": _float_or_none(wallet_reconciliation_summary.get("btc5_probe_age_hours")),
        },
        "capital_consistency": {
            "status": "conflict" if capital_conflicts else "consistent",
            "reasons": capital_conflicts,
            "artifacts": {
                "selected_forecast": {
                    "deploy_recommendation": scoreboard.get("deploy_recommendation"),
                    "forecast_confidence_label": scoreboard.get("forecast_confidence_label"),
                    "source_artifact": scoreboard.get("public_forecast_source_artifact"),
                },
                "runtime_capital_readiness": {
                    "fund_status": fund_status or None,
                    "polymarket_btc5_status": polymarket_status or None,
                    "next_1000_status": next_1000_status or None,
                },
                "strategy_scale_comparison": scale_recommendation,
                "signal_source_audit": audit_summary,
            },
        },
    }
    strategy["control_plane_consistency"] = consistency
    state_improvement = dict(snapshot.get("state_improvement") or {})
    state_improvement["strategy_recommendations"] = strategy
    snapshot["state_improvement"] = state_improvement


def render_runtime_mode_reconciliation_markdown(payload: dict[str, Any]) -> str:
    return _render_runtime_mode_reconciliation_markdown_impl(payload)


def build_runtime_truth_snapshot(
    root: Path,
    *,
    status: dict[str, Any],
    remote_cycle_status_path: Path,
    service_status_path: Path,
    root_test_status_path: Path,
    latest_edge_scan_path: Path | None,
    latest_pipeline_path: Path | None,
    runtime_truth_latest_path: Path,
    runtime_truth_timestamped_path: Path,
    public_runtime_snapshot_path: Path,
    previous_runtime_truth_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the canonical machine-readable runtime truth snapshot."""

    repo_root = root.resolve()
    jj_state = _load_json(repo_root / "jj_state.json", default={})
    intel_snapshot = _load_json(repo_root / "data" / "intel_snapshot.json", default={})

    cycle_reconciliation = _reconcile_cycle_count(status=status, jj_state=jj_state, intel_snapshot=intel_snapshot)
    root_tests = status["root_tests"]
    verification_summary = root_tests.get("display_summary") or root_tests.get("summary")
    launch = status["launch"]
    wallet_flow = status["wallet_flow"]
    service = status["service"]
    runtime_truth = status["runtime_truth"]
    btc5_stage_readiness = dict(status.get("btc5_stage_readiness") or {})
    deployment_confidence = dict(status.get("deployment_confidence") or {})
    status_source_precedence = dict(status.get("source_precedence") or {})
    service_drift_reason = next(
        (
            reason
            for reason in runtime_truth.get("drift_reasons") or []
            if f"{PRIMARY_RUNTIME_SERVICE_NAME} is running while launch posture remains blocked" in reason
        ),
        None,
    )
    launch_posture = "blocked" if launch["live_launch_blocked"] else "clear"
    latest_edge_scan = _summarize_edge_scan(repo_root, latest_edge_scan_path)
    latest_pipeline = _summarize_pipeline(repo_root, latest_pipeline_path)
    previous_snapshot = (
        previous_runtime_truth_snapshot if isinstance(previous_runtime_truth_snapshot, dict) else {}
    )
    champion_lane_contract = dict(status.get("champion_lane_contract") or {})
    finance_gate = dict(status.get("finance_gate") or {})
    selected_package_summary = dict(status.get("btc5_selected_package") or {})
    source_precedence_fields = [
        {
            "field": "cycles_completed",
            "selected_source": cycle_reconciliation["selected_source"],
            "fallback_sources": [
                "data/intel_snapshot.json",
                "reports/remote_cycle_status.json",
            ],
            "selected_value": cycle_reconciliation["selected_value"],
        },
        {
            "field": "wallet_flow_status",
            "selected_source": "data/smart_wallets.json + data/wallet_scores.db",
            "fallback_sources": ["reports/remote_cycle_status.json"],
            "selected_value": wallet_flow["status"],
        },
        {
            "field": "service_status",
            "selected_source": service.get("source") or "reports/remote_service_status.json",
            "fallback_sources": ["reports/remote_cycle_status.json"],
            "selected_value": service["status"],
        },
        {
            "field": "launch_posture",
            "selected_source": "reports/remote_cycle_status.json",
            "fallback_sources": ["reports/edge_scan_*.json (advisory only)"],
            "selected_value": launch_posture,
        },
        {
            "field": "verification_status",
            "selected_source": root_tests.get("source") or "reports/root_test_status.json",
            "fallback_sources": ["reports/pipeline_*.json.verification"],
            "selected_value": root_tests["status"],
        },
    ]
    existing_field_names = {
        str(item.get("field"))
        for item in source_precedence_fields
        if isinstance(item, dict) and str(item.get("field") or "").strip()
    }
    for item in list(status_source_precedence.get("fields") or []):
        if not isinstance(item, dict):
            continue
        field_name = str(item.get("field") or "").strip()
        if not field_name or field_name in existing_field_names:
            continue
        source_precedence_fields.append(item)
        existing_field_names.add(field_name)
    state_improvement = _build_state_improvement_report(
        root=repo_root,
        generated_at=datetime.now(timezone.utc),
        runtime=status["runtime"],
        capital=status["capital"],
        btc5_maker=status.get("btc_5min_maker") or {},
        polymarket_wallet=status.get("polymarket_wallet") or {},
        accounting_reconciliation=status.get("accounting_reconciliation") or {},
        launch=launch,
        latest_edge_scan=latest_edge_scan,
        latest_pipeline=latest_pipeline,
        previous_runtime_truth_snapshot=previous_snapshot,
    )
    if champion_lane_contract:
        improvement_deltas = (
            (state_improvement.get("improvement_velocity") or {}).get("deltas")
            if isinstance(state_improvement.get("improvement_velocity"), dict)
            else {}
        ) or {}
        strategy = dict(state_improvement.get("strategy_recommendations") or {})
        truth_lattice = dict(strategy.get("truth_lattice") or {})
        required_outputs = dict(champion_lane_contract.get("required_outputs") or {})
        required_outputs["expected_improvement_velocity_delta"] = round(
            _safe_float(
                _first_nonempty(
                    improvement_deltas.get("candidate_to_trade_conversion_delta"),
                    improvement_deltas.get("edge_reachability_delta"),
                    0.0,
                ),
                0.0,
            ),
            6,
        )
        if truth_lattice.get("repair_branch_required"):
            truth_checks = _dedupe_preserve_order(
                list(((champion_lane_contract.get("blocker_classes") or {}).get("truth") or {}).get("checks") or [])
                + list(truth_lattice.get("broken_reasons") or [])
            )
            blocker_classes = dict(champion_lane_contract.get("blocker_classes") or {})
            blocker_classes["truth"] = _blocker_bucket(
                truth_checks,
                retry_cadence_minutes=5,
            )
            champion_lane_contract["blocker_classes"] = blocker_classes
            champion_lane_contract["status"] = "hold_repair"
            champion_lane_contract["decision_reason"] = (
                "truth_lattice_repair_required_before_champion_lane_can_run"
            )
            required_outputs["block_reasons"] = _dedupe_preserve_order(
                list(required_outputs.get("block_reasons") or [])
                + list(truth_lattice.get("broken_reasons") or [])
            )
            required_outputs["one_next_cycle_action"] = str(
                truth_lattice.get("one_next_cycle_action")
                or required_outputs.get("one_next_cycle_action")
                or "Repair truth-lattice contradictions before any lane promotion."
            )
        champion_lane_contract["required_outputs"] = required_outputs
        strategy["champion_lane_contract"] = champion_lane_contract
        state_improvement["strategy_recommendations"] = strategy
        state_improvement["decision_status"] = champion_lane_contract.get("status")

    snapshot = {
        "artifact": "runtime_truth_snapshot",
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "cycles_completed": cycle_reconciliation["selected_value"],
            "service_status": service["status"],
            "wallet_flow_status": wallet_flow["status"],
            "launch_posture": launch_posture,
            "verification_status": root_tests["status"],
            "drift_detected": bool(
                cycle_reconciliation["drift_detected"] or runtime_truth.get("drift_detected")
            ),
            "btc5_can_trade_now": bool(deployment_confidence.get("can_btc5_trade_now")),
            "btc5_allowed_stage": deployment_confidence.get("allowed_stage_label"),
            "deployment_allowed_stage": deployment_confidence.get("allowed_stage"),
            "deployment_confidence_label": deployment_confidence.get("confidence_label"),
            "trading_cycle_status": champion_lane_contract.get("status"),
            "one_next_cycle_action": (
                (champion_lane_contract.get("required_outputs") or {}).get("one_next_cycle_action")
            ),
        },
        "source_precedence": {
            "rule": (
                _first_nonempty(
                    status_source_precedence.get("rule"),
                    "Prefer underlying synced/runtime artifacts over previously written summary outputs "
                    "when timestamps or content disagree.",
                )
            ),
            "fields": source_precedence_fields,
            "contradictions": list(status_source_precedence.get("contradictions") or []),
        },
        "reconciliation": {
            "cycles_completed": cycle_reconciliation,
            "wallet_flow": {
                "selected_source": "data/smart_wallets.json + data/wallet_scores.db",
                "status": wallet_flow["status"],
                "ready": wallet_flow["ready"],
                "wallet_count": wallet_flow["wallet_count"],
                "last_updated": wallet_flow.get("last_updated"),
                "reasons": list(wallet_flow.get("reasons") or []),
            },
            "service": {
                "selected_source": service.get("source") or "reports/remote_service_status.json",
                "status": service["status"],
                "systemctl_state": service.get("systemctl_state"),
                "checked_at": service.get("checked_at"),
                "drift_detected": bool(runtime_truth.get("service_drift_detected")),
                "drift_reason": service_drift_reason,
            },
            "launch": {
                "selected_source": "reports/remote_cycle_status.json",
                "posture": launch_posture,
                "fast_flow_restart_ready": launch["fast_flow_restart_ready"],
                "live_launch_blocked": launch["live_launch_blocked"],
                "blocked_checks": list(launch.get("blocked_checks") or []),
                "blocked_reasons": list(launch.get("blocked_reasons") or []),
                "next_operator_action": launch["next_operator_action"],
            },
            "verification": {
                "selected_source": root_tests.get("source") or "reports/root_test_status.json",
                "status": root_tests["status"],
                "summary": verification_summary,
                "checked_at": root_tests.get("checked_at"),
                "command": root_tests.get("command"),
            },
            "polymarket_wallet": {
                "selected_source": "remote CLOB + Polymarket data API",
                "status": status.get("polymarket_wallet", {}).get("status"),
                "checked_at": status.get("polymarket_wallet", {}).get("checked_at"),
                "free_collateral_usd": status.get("polymarket_wallet", {}).get(
                    "free_collateral_usd"
                ),
                "reserved_order_usd": status.get("polymarket_wallet", {}).get(
                    "reserved_order_usd"
                ),
                "open_positions_count": status.get("polymarket_wallet", {}).get(
                    "open_positions_count"
                ),
                "closed_positions_realized_pnl_usd": status.get("polymarket_wallet", {}).get(
                    "closed_positions_realized_pnl_usd"
                ),
                "warnings": list(status.get("polymarket_wallet", {}).get("warnings") or []),
            },
            "btc_5min_maker": {
                "selected_source": (
                    status.get("btc_5min_maker", {}).get("source")
                    or status.get("btc_5min_maker", {}).get("db_path")
                    or "data/btc_5min_maker.db"
                ),
                "status": status.get("btc_5min_maker", {}).get("status"),
                "checked_at": status.get("btc_5min_maker", {}).get("checked_at"),
                "db_path": status.get("btc_5min_maker", {}).get("db_path"),
                "live_filled_rows": status.get("btc_5min_maker", {}).get("live_filled_rows"),
                "live_filled_pnl_usd": status.get("btc_5min_maker", {}).get(
                    "live_filled_pnl_usd"
                ),
                "estimated_maker_rebate_usd": status.get("btc_5min_maker", {}).get(
                    "estimated_maker_rebate_usd"
                ),
                "net_pnl_after_estimated_rebate_usd": status.get("btc_5min_maker", {}).get(
                    "net_pnl_after_estimated_rebate_usd"
                ),
                "latest_live_filled_at": status.get("btc_5min_maker", {}).get(
                    "latest_live_filled_at"
                ),
                "latest_trade": status.get("btc_5min_maker", {}).get("latest_trade") or {},
                "fill_attribution": status.get("btc_5min_maker", {}).get("fill_attribution") or {},
                "intraday_live_summary": status.get("btc_5min_maker", {}).get("intraday_live_summary") or {},
            },
            "accounting": status.get("accounting_reconciliation") or {},
        },
        "capital": status["capital"],
        "runtime": status["runtime"],
        "finance_gate": finance_gate,
        "btc5_selected_package": selected_package_summary,
        "champion_lane_contract": champion_lane_contract,
        "attribution": dict(status.get("attribution") or {}),
        "trade_confirmation": dict(status.get("trade_confirmation") or {}),
        "trade_proof": dict(status.get("trade_proof") or {}),
        "wallet_flow": status["wallet_flow"],
        "polymarket_wallet": status.get("polymarket_wallet") or {},
        "btc_5min_maker": status.get("btc_5min_maker") or {},
        "btc5_stage_readiness": btc5_stage_readiness,
        "deployment_confidence": deployment_confidence,
        "accounting_reconciliation": status.get("accounting_reconciliation") or {},
        "service": {
            "status": service["status"],
            "service_name": service.get("service_name"),
            "systemctl_state": service.get("systemctl_state"),
            "detail": service.get("detail"),
            "checked_at": service.get("checked_at"),
            "drift_detected": bool(runtime_truth.get("service_drift_detected")),
            "drift_reason": service_drift_reason,
        },
        "launch": {
            "posture": launch_posture,
            **launch,
        },
        "structural_gates": status["structural_gates"],
        "verification": {
            "status": root_tests["status"],
            "summary": verification_summary,
            "checked_at": root_tests.get("checked_at"),
            "command": root_tests.get("command"),
        },
        "latest_edge_scan": latest_edge_scan,
        "latest_pipeline": latest_pipeline,
        "state_improvement": state_improvement,
        "drift": {
            "detected": bool(
                cycle_reconciliation["drift_detected"] or runtime_truth.get("drift_detected")
            ),
            "reasons": _dedupe_preserve_order(
                [
                    *list(cycle_reconciliation.get("drift_reasons") or []),
                    *list(runtime_truth.get("drift_reasons") or []),
                ]
            ),
            "cycle_drift": cycle_reconciliation,
            "service_running_while_launch_blocked": bool(runtime_truth.get("service_drift_detected")),
        },
        "artifacts": {
            "remote_cycle_status_json": _relative_path_text(repo_root, remote_cycle_status_path),
            "remote_service_status_json": _relative_path_text(repo_root, service_status_path),
            "root_test_status_json": _relative_path_text(repo_root, root_test_status_path),
            "runtime_truth_latest_json": _relative_path_text(repo_root, runtime_truth_latest_path),
            "runtime_truth_timestamped_json": _relative_path_text(
                repo_root,
                runtime_truth_timestamped_path,
            ),
            "public_runtime_snapshot_json": _relative_path_text(
                repo_root,
                public_runtime_snapshot_path,
            ),
            "state_improvement_latest_json": _relative_path_text(
                repo_root,
                DEFAULT_STATE_IMPROVEMENT_LATEST_PATH,
            ),
            "state_improvement_digest_markdown": _relative_path_text(
                repo_root,
                DEFAULT_STATE_IMPROVEMENT_DIGEST_PATH,
            ),
            "latest_edge_scan_json": _relative_path_text(repo_root, latest_edge_scan_path),
            "latest_pipeline_json": _relative_path_text(repo_root, latest_pipeline_path),
        },
    }
    return snapshot


def build_public_runtime_snapshot(runtime_truth_snapshot: dict[str, Any]) -> dict[str, Any]:
    return _build_public_runtime_snapshot_impl(runtime_truth_snapshot)


def refresh_root_test_status(
    root: Path,
    *,
    status_path: Path,
    command: Sequence[str] = DEFAULT_ROOT_TEST_COMMAND,
    timeout_seconds: int = 900,
) -> dict[str, Any]:
    """Run the root regression command and persist a compact status snapshot."""

    checked_at = datetime.now(timezone.utc).isoformat()
    command_text = " ".join(command)
    try:
        result = subprocess.run(
            list(command),
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
        output = "\n".join(
            chunk for chunk in (result.stdout.strip(), result.stderr.strip()) if chunk
        ).strip()
        status = "passing" if result.returncode == 0 else "failing"
        payload = {
            "checked_at": checked_at,
            "command": command_text,
            "status": status,
            "returncode": int(result.returncode),
            "summary": _summarize_test_output(output, success=result.returncode == 0),
            "output_tail": _tail_lines(output, limit=12),
        }
    except subprocess.TimeoutExpired as exc:
        output = "\n".join(
            chunk
            for chunk in (
                (exc.stdout or "").strip(),
                (exc.stderr or "").strip(),
            )
            if chunk
        ).strip()
        payload = {
            "checked_at": checked_at,
            "command": command_text,
            "status": "timeout",
            "returncode": None,
            "summary": f"Timed out after {timeout_seconds}s while running {command_text}.",
            "output_tail": _tail_lines(output, limit=12),
        }

    dump_path_atomic(status_path, payload, indent=2, sort_keys=True, trailing_newline=False)
    return payload


def _load_trade_counts(root: Path) -> dict[str, Any]:
    db_path = root / DEFAULT_TRADES_DB_PATH
    if not db_path.exists():
        return {"source": "jj_state_fallback", "total_trades": 0, "closed_trades": 0}

    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS total_trades,
                SUM(CASE WHEN outcome IS NOT NULL AND outcome != '' THEN 1 ELSE 0 END) AS closed_trades
            FROM trades
            """
        ).fetchone()
    except sqlite3.DatabaseError:
        return {"source": "jj_state_fallback", "total_trades": 0, "closed_trades": 0}
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass

    total_trades = int(row[0] or 0) if row else 0
    closed_trades = int(row[1] or 0) if row else 0
    return {
        "source": "data/jj_trades.db",
        "total_trades": total_trades,
        "closed_trades": closed_trades,
    }


def _load_service_status(path: Path) -> dict[str, Any]:
    return _load_service_status_with_fallback(_repo_root_from_reports_path(path), path)


def _service_status_sort_key(candidate: dict[str, Any]) -> tuple[int, float]:
    checked_at = _parse_datetime_like(candidate.get("checked_at"))
    timestamp = checked_at.timestamp() if checked_at is not None else float("-inf")
    status = str(candidate.get("status") or "unknown").strip().lower()
    known_rank = 1 if status in {"running", "stopped"} else 0
    return known_rank, timestamp


def _load_service_status_with_fallback(root: Path, path: Path) -> dict[str, Any]:
    candidate_services: list[dict[str, Any]] = []

    def _append_candidate(candidate: dict[str, Any] | None) -> None:
        if not isinstance(candidate, dict):
            return
        status = str(candidate.get("status") or "unknown").strip().lower()
        if status == "unknown":
            return
        candidate_services.append(candidate)

    raw = _load_json(path, default={})
    service = _normalize_service_status_payload(
        raw,
        default_service_name=PRIMARY_RUNTIME_SERVICE_NAME,
        source=_relative_path_text(root, path) or str(path),
    )
    _append_candidate(service)

    btc5_service_path = root / "reports" / "btc5_remote_service_status.json"
    if btc5_service_path != path and btc5_service_path.exists():
        _append_candidate(
            _normalize_service_status_payload(
                _load_json(btc5_service_path, default={}),
                default_service_name=PRIMARY_RUNTIME_SERVICE_NAME,
                source=_relative_path_text(root, btc5_service_path) or str(btc5_service_path),
            )
        )

    if not candidate_services:
        local_probe = _probe_local_systemctl_service_status(service["service_name"])
        _append_candidate(local_probe)

    fallback = _find_latest_artifact_payload(
        root,
        [
            Path("reports/btc5_deploy_activation.json"),
            Path("reports/btc5_remote_service_status.json"),
            Path("reports/runtime_truth_latest.json"),
            Path("reports/remote_cycle_status.json"),
            "reports/runtime_truth_*.json",
            "reports/runtime/runtime_truth/runtime_truth_*.json",
            "reports/deploy_*.json",
        ],
        extractor=_extract_service_status_candidate,
    )
    _append_candidate(fallback)

    if candidate_services:
        return max(candidate_services, key=_service_status_sort_key)
    return service


def _load_root_test_status(path: Path) -> dict[str, Any]:
    root = _repo_root_from_reports_path(path)
    canonical_default = root / DEFAULT_ROOT_TEST_STATUS_PATH
    resolved_path = path
    if path == canonical_default and not path.exists():
        alias_path = _resolve_compatibility_alias_path(
            root,
            "root_test_status.json",
            materialize=False,
        )
        if alias_path.exists():
            resolved_path = alias_path
    return _load_root_test_status_with_fallback(root, resolved_path)


def _repo_root_from_reports_path(path: Path) -> Path:
    resolved = path.resolve()
    for parent in [resolved, *resolved.parents]:
        if parent.name == "reports":
            return parent.parent
    return resolved.parent.parent


def _load_legacy_alias_index(root: Path) -> dict[str, Any]:
    payload = _load_json(root / LEGACY_ALIASES_INDEX_PATH, default={})
    if not isinstance(payload, dict):
        return {"aliases": {}, "allowlist": set()}
    aliases_raw = payload.get("aliases")
    allowlist_raw = payload.get("allowlist")
    aliases = (
        {
            str(key).strip(): str(value).strip()
            for key, value in dict(aliases_raw).items()
            if str(key).strip() and str(value).strip()
        }
        if isinstance(aliases_raw, dict)
        else {}
    )
    allowlist = (
        {
            str(item).strip()
            for item in list(allowlist_raw)
            if str(item).strip()
        }
        if isinstance(allowlist_raw, list)
        else set()
    )
    return {"aliases": aliases, "allowlist": allowlist}


def _resolve_allowlisted_target_from_reports(reports_dir: Path, name: str) -> Path | None:
    candidates: list[Path] = []
    for candidate in reports_dir.rglob(name):
        if candidate.parent == reports_dir:
            continue
        if candidate.exists() and candidate.is_file() and not candidate.is_symlink():
            candidates.append(candidate)
    if not candidates:
        return None
    candidates.sort(
        key=lambda path: (
            "reports/parallel/" in path.as_posix(),
            len(path.as_posix()),
            path.as_posix(),
        )
    )
    return candidates[0]


def _resolve_compatibility_alias_path(
    root: Path,
    name: str,
    *,
    materialize: bool,
) -> Path:
    reports_dir = root / "reports"
    top_level_path = reports_dir / name
    if top_level_path.exists():
        return top_level_path

    alias_index = _load_legacy_alias_index(root)
    aliases = dict(alias_index.get("aliases") or {})
    allowlist = set(alias_index.get("allowlist") or set())
    if allowlist and name not in allowlist:
        return top_level_path

    target_path: Path | None = None
    alias_target = aliases.get(f"reports/{name}")
    if alias_target:
        candidate = Path(alias_target)
        if not candidate.is_absolute():
            candidate = root / candidate
        if candidate.exists() and candidate.is_file():
            target_path = candidate
    if target_path is None:
        target_path = _resolve_allowlisted_target_from_reports(reports_dir, name)
    if target_path is None:
        return top_level_path

    if materialize:
        try:
            if top_level_path.is_symlink() and not top_level_path.exists():
                top_level_path.unlink(missing_ok=True)
            if not top_level_path.exists():
                rel_target = Path(os.path.relpath(target_path, start=top_level_path.parent))
                top_level_path.symlink_to(rel_target)
        except OSError:
            return target_path
    return top_level_path if top_level_path.exists() else target_path


def _materialize_required_compatibility_aliases(root: Path) -> dict[str, Any]:
    reports_dir = root / "reports"
    created: list[str] = []
    resolved: list[str] = []
    missing: list[str] = []
    for name in REQUIRED_COMPATIBILITY_ALIAS_NAMES:
        top_level_path = reports_dir / name
        existed_before = top_level_path.exists()
        resolved_path = _resolve_compatibility_alias_path(root, name, materialize=True)
        if top_level_path.exists():
            if not existed_before:
                created.append(name)
            else:
                resolved.append(name)
            continue
        if resolved_path.exists():
            resolved.append(name)
        else:
            missing.append(name)
    return {
        "created": created,
        "resolved": resolved,
        "missing": missing,
    }


def _load_root_test_status_with_fallback(root: Path, path: Path) -> dict[str, Any]:
    raw = _load_json(path, default={})
    root_tests = _normalize_root_test_status_payload(
        raw,
        source=_relative_path_text(root, path) or str(path),
    )
    if root_tests["status"] == "unknown" and path != root / LEGACY_ROOT_TEST_STATUS_PATH:
        legacy_raw = _load_json(root / LEGACY_ROOT_TEST_STATUS_PATH, default={})
        legacy_root_tests = _normalize_root_test_status_payload(
            legacy_raw,
            source=_relative_path_text(root, root / LEGACY_ROOT_TEST_STATUS_PATH)
            or str(root / LEGACY_ROOT_TEST_STATUS_PATH),
        )
        if legacy_root_tests["status"] != "unknown":
            return legacy_root_tests
    if root_tests["status"] != "unknown":
        return root_tests

    fallback = _find_latest_artifact_payload(
        root,
        [
            Path("reports/runtime_truth_latest.json"),
            Path("reports/remote_cycle_status.json"),
            "reports/runtime_truth_*.json",
            "reports/runtime/runtime_truth/runtime_truth_*.json",
            "reports/pipeline_*.json",
            "reports/pipeline_refresh_*.json",
        ],
        extractor=_extract_root_test_status_candidate,
    )
    if fallback is not None:
        return fallback
    return root_tests


def _load_arb_status_with_fallback(root: Path, path: Path) -> dict[str, Any]:
    if not path.exists():
        alias_path = _resolve_compatibility_alias_path(
            root,
            "arb_empirical_snapshot.json",
            materialize=False,
        )
        if alias_path.exists():
            path = alias_path
    payload = _load_json(path, default={})
    if payload or path == root / LEGACY_ARB_STATUS_PATH:
        return payload if isinstance(payload, dict) else {}
    legacy_payload = _load_json(root / LEGACY_ARB_STATUS_PATH, default={})
    return legacy_payload if isinstance(legacy_payload, dict) else {}


def _normalize_service_status_payload(
    raw: dict[str, Any],
    *,
    default_service_name: str,
    source: str | None,
) -> dict[str, Any]:
    systemctl_state = str(
        raw.get("systemctl_state")
        or raw.get("active_state")
        or raw.get("state")
        or raw.get("systemd_status")
        or "unknown"
    ).strip()
    status = str(raw.get("status") or raw.get("service_state") or "").strip().lower()
    if not status:
        lowered = systemctl_state.lower()
        if lowered == "active":
            status = "running"
        elif lowered in {"inactive", "failed", "deactivating"}:
            status = "stopped"
        else:
            status = "unknown"

    return {
        "status": status,
        "systemctl_state": systemctl_state or "unknown",
        "detail": raw.get("detail")
        or raw.get("error")
        or raw.get("systemd_status")
        or systemctl_state
        or "unknown",
        "checked_at": raw.get("checked_at"),
        "service_name": raw.get("service_name") or default_service_name,
        "host": raw.get("host"),
        "source": source,
    }


def _normalize_root_test_status_payload(
    raw: dict[str, Any],
    *,
    source: str | None,
) -> dict[str, Any]:
    output_tail = list(raw.get("output_tail") or [])
    summary = raw.get("summary") or "Root regression status has not been refreshed yet."
    status = _normalize_test_status(raw.get("status"))
    return {
        "status": status,
        "checked_at": raw.get("checked_at"),
        "command": raw.get("command") or "make test",
        "summary": summary,
        "display_summary": _summarize_test_output(
            "\n".join(output_tail),
            success=status == "passing",
            default=summary,
        ),
        "returncode": raw.get("returncode"),
        "output_tail": output_tail,
        "source": source,
    }


def _normalize_test_status(value: Any) -> str:
    normalized = str(value or "unknown").strip().lower()
    if normalized in {"passed", "pass", "ok", "success", "successful"}:
        return "passing"
    if normalized in {"failed", "fail", "error", "errors"}:
        return "failing"
    return normalized or "unknown"


def _probe_local_systemctl_service_status(service_name: str) -> dict[str, Any]:
    checked_at = datetime.now(timezone.utc).isoformat()
    try:
        result = subprocess.run(
            [
                "systemctl",
                "show",
                service_name,
                "--property=ActiveState,SubState",
                "--no-pager",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.SubprocessError, PermissionError):
        return {
            "status": "unknown",
            "systemctl_state": "unknown",
            "detail": "local systemctl probe unavailable",
            "checked_at": checked_at,
            "service_name": service_name,
            "host": None,
            "source": None,
        }

    fields: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        fields[key.strip()] = value.strip()
    active_state = fields.get("ActiveState") or "unknown"
    sub_state = fields.get("SubState") or ""
    service = _normalize_service_status_payload(
        {
            "systemctl_state": active_state,
            "detail": "/".join(part for part in (active_state, sub_state) if part),
            "checked_at": checked_at,
            "service_name": service_name,
        },
        default_service_name=service_name,
        source="local_systemctl",
    )
    if service["status"] == "unknown" and result.returncode != 0:
        stderr = (result.stderr or "").strip()
        if stderr:
            service["detail"] = stderr
    return service


def _find_latest_artifact_payload(
    root: Path,
    candidates: Sequence[Path | str],
    *,
    extractor: Callable[[dict[str, Any]], dict[str, Any] | None],
) -> dict[str, Any] | None:
    artifact_paths = _expand_artifact_candidates(root, candidates)
    if not artifact_paths:
        return None

    usable: list[tuple[Path, dict[str, Any]]] = []
    for artifact_path in artifact_paths:
        payload = _load_json(artifact_path, default={})
        if not isinstance(payload, dict):
            continue
        extracted = extractor(payload)
        if not extracted:
            continue
        status = str(extracted.get("status") or "unknown").strip().lower()
        if status == "unknown":
            continue
        extracted["source"] = _relative_path_text(root, artifact_path) or str(artifact_path)
        usable.append((artifact_path, extracted))

    if not usable:
        return None
    usable.sort(key=lambda item: _artifact_sort_key(item[0]), reverse=True)
    return usable[0][1]


def _expand_artifact_candidates(root: Path, candidates: Sequence[Path | str]) -> list[Path]:
    reports: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        if isinstance(candidate, Path):
            path = candidate if candidate.is_absolute() else root / candidate
            if path.is_file() and path not in seen:
                reports.append(path)
                seen.add(path)
            continue
        for path in (root / ".").glob(candidate):
            if path.is_file() and path not in seen:
                reports.append(path)
                seen.add(path)
    return reports


def _extract_service_status_candidate(payload: dict[str, Any]) -> dict[str, Any] | None:
    if isinstance(payload.get("service"), dict):
        return _normalize_service_status_payload(
            payload["service"],
            default_service_name=PRIMARY_RUNTIME_SERVICE_NAME,
            source=None,
        )
    if any(
        key in payload
        for key in ("status", "systemctl_state", "active_state", "state", "service_state")
    ):
        return _normalize_service_status_payload(
            payload,
            default_service_name=PRIMARY_RUNTIME_SERVICE_NAME,
            source=None,
        )
    return None


def _extract_root_test_status_candidate(payload: dict[str, Any]) -> dict[str, Any] | None:
    root_tests = payload.get("root_tests")
    if isinstance(root_tests, dict):
        return _normalize_root_test_status_payload(root_tests, source=None)

    verification = payload.get("verification")
    if isinstance(verification, dict):
        if any(key in verification for key in ("status", "summary", "output_tail")):
            return _normalize_root_test_status_payload(verification, source=None)
        pipeline_candidate = _normalize_pipeline_verification_payload(verification)
        if pipeline_candidate is not None:
            return _normalize_root_test_status_payload(pipeline_candidate, source=None)
    return None


def _normalize_pipeline_verification_payload(
    verification: dict[str, Any],
) -> dict[str, Any] | None:
    status = _normalize_test_status(
        verification.get("status")
        or verification.get("make_test_status")
        or verification.get("integrated_entrypoint_status")
    )
    summary_parts = [
        str(part).strip()
        for part in (
            verification.get("summary"),
            verification.get("root_suite"),
            verification.get("jj_live_import_boundary_suite"),
        )
        if str(part or "").strip()
    ]
    if status == "unknown" and not summary_parts:
        return None
    return {
        "status": status,
        "checked_at": verification.get("checked_at"),
        "command": verification.get("command") or "make test",
        "summary": "; ".join(summary_parts)
        or "Root regression status was recovered from the latest pipeline artifact.",
        "output_tail": summary_parts[-2:],
        "returncode": verification.get("returncode"),
    }


def _load_wallet_flow_status(root: Path) -> dict[str, Any]:
    scores_path = root / DEFAULT_WALLET_SCORES_PATH
    db_path = root / DEFAULT_WALLET_DB_PATH

    scores_exists = scores_path.exists()
    db_exists = db_path.exists()
    reasons: list[str] = []
    wallet_count = 0
    last_updated = None

    if not scores_exists:
        reasons.append("missing_data/smart_wallets.json")
    else:
        try:
            payload = load_path(scores_path)
            wallet_count = _extract_wallet_count(payload)
            last_updated = _extract_wallet_last_updated(payload)
        except ValueError:
            reasons.append("invalid_data/smart_wallets.json")

    if not db_exists:
        reasons.append("missing_data/wallet_scores.db")

    if wallet_count <= 0:
        reasons.append("no_scored_wallets")

    if last_updated is None:
        candidate_times = [
            _safe_iso_mtime(path)
            for path in (scores_path, db_path)
            if path.exists()
        ]
        last_updated = next((value for value in candidate_times if value), None)

    ready = scores_exists and db_exists and wallet_count > 0
    return {
        "status": "ready" if ready else "not_ready",
        "ready": ready,
        "reasons": reasons,
        "wallet_count": wallet_count,
        "scores_exists": scores_exists,
        "db_exists": db_exists,
        "last_updated": last_updated,
    }


def _build_a6_gate_status(payload: dict[str, Any]) -> dict[str, Any]:
    gating = payload.get("gating_metrics") or {}
    fill_proxy = payload.get("fill_proxy") or {}
    live_surface = payload.get("live_surface") or {}
    explicit = _extract_lane_payload(payload, lane_key="a6")

    status = _first_nonempty(
        explicit.get("status"),
        payload.get("a6_status"),
    )
    maker_fill_proxy_rate = _float_or_none(
        _first_nonempty(
            explicit.get("maker_fill_proxy_rate"),
            fill_proxy.get("full_fill_proxy_rate"),
        )
    )
    violation_half_life_seconds = _float_or_none(
        _first_nonempty(
            explicit.get("violation_half_life_seconds"),
            gating.get("half_life_seconds"),
            live_surface.get("a6_completed_half_life_seconds"),
            live_surface.get("a6_completed_half_life_p90_seconds"),
        )
    )
    settlement_evidence_count = int(
        _first_nonempty(
            explicit.get("settlement_evidence_count"),
            payload.get("settlement", {}).get("successful_operation_count"),
            payload.get("settlement", {}).get("operation_count"),
            0,
        )
        or 0
    )

    blocked_reasons = list(explicit.get("blocked_reasons") or [])
    if not blocked_reasons:
        if gating.get("fill_probability_gate") != "pass":
            blocked_reasons.append("maker_fill_proxy_not_proven")
        if gating.get("half_life_gate") != "pass":
            blocked_reasons.append("violation_half_life_below_gate")
        if gating.get("settlement_path_gate") != "pass" or settlement_evidence_count <= 0:
            blocked_reasons.append("settlement_path_unproven")
        blocked_reasons.append("public_data_audit_found_0_executable_a6_constructions_below_0.95_gate")

    if not status:
        status = "blocked"
        if gating.get("all_gates_pass"):
            status = "ready_for_shadow"

    summary = explicit.get("summary")
    if not summary:
        summary = (
            "Public-data audits still show 0 executable A-6 constructions below the 0.95 gate; "
            "maker-fill and settlement evidence remain insufficient."
        )

    return {
        "status": status,
        "summary": summary,
        "maker_fill_proxy_rate": maker_fill_proxy_rate,
        "violation_half_life_seconds": violation_half_life_seconds,
        "settlement_evidence_count": settlement_evidence_count,
        "blocked_reasons": blocked_reasons,
        "source": "reports/arb_empirical_snapshot.json",
    }


def _build_b1_gate_status(payload: dict[str, Any], *, jj_state: dict[str, Any]) -> dict[str, Any]:
    b1_payload = payload.get("b1") or {}
    explicit = _extract_lane_payload(payload, lane_key="b1")

    status = _first_nonempty(explicit.get("status"), payload.get("b1_status"))
    classification_accuracy = _float_or_none(
        _first_nonempty(
            explicit.get("classification_accuracy"),
            b1_payload.get("classification_accuracy"),
            (jj_state.get("b1_state") or {}).get("validation_accuracy"),
        )
    )
    false_positive_rate = _float_or_none(
        _first_nonempty(
            explicit.get("false_positive_rate"),
            b1_payload.get("false_positive_rate"),
        )
    )
    violation_half_life_seconds = _float_or_none(
        _first_nonempty(
            explicit.get("violation_half_life_seconds"),
            b1_payload.get("a6_or_b1_half_life_seconds"),
        )
    )

    blocked_reasons = list(explicit.get("blocked_reasons") or [])
    if not blocked_reasons:
        if classification_accuracy is None or classification_accuracy < 0.85:
            blocked_reasons.append("classification_accuracy_below_85pct")
        if false_positive_rate is None:
            blocked_reasons.append("false_positive_rate_unmeasured")
        elif false_positive_rate > 0.05:
            blocked_reasons.append("false_positive_rate_above_5pct")
        blocked_reasons.append(
            "public_data_audit_found_0_deterministic_template_pairs_in_first_1000_allowed_markets"
        )

    if not status:
        status = "blocked"
        if (
            classification_accuracy is not None
            and classification_accuracy >= 0.85
            and false_positive_rate is not None
            and false_positive_rate <= 0.05
        ):
            status = "ready_for_shadow"

    summary = explicit.get("summary")
    if not summary:
        summary = (
            "Public-data audits still show 0 deterministic template pairs in the first 1,000 "
            "allowed markets, so B-1 remains blocked."
        )

    return {
        "status": status,
        "summary": summary,
        "classification_accuracy": classification_accuracy,
        "false_positive_rate": false_positive_rate,
        "violation_half_life_seconds": violation_half_life_seconds,
        "blocked_reasons": blocked_reasons,
        "source": "reports/arb_empirical_snapshot.json",
    }


def _build_launch_status(
    *,
    status: dict[str, Any],
    service: dict[str, Any],
    root_tests: dict[str, Any],
    wallet_flow: dict[str, Any],
    a6_gate: dict[str, Any],
    b1_gate: dict[str, Any],
    accounting_reconciliation: dict[str, Any],
    deploy_evidence: dict[str, Any],
) -> dict[str, Any]:
    runtime = status["runtime"]
    flywheel = status["flywheel"]
    deploy_validation = dict(deploy_evidence.get("validation") or {})
    verification_checks = dict(deploy_evidence.get("verification_checks") or {})
    runtime_validation_passed = bool(
        _bool_or_none(
            _first_nonempty(
                deploy_validation.get("required_passed"),
                verification_checks.get("required_passed"),
                deploy_evidence.get("required_passed"),
                False,
            )
        )
    )

    blocked_checks: list[str] = []
    blocked_reasons: list[str] = []

    if root_tests["status"] != "passing" and not runtime_validation_passed:
        blocked_checks.append("root_tests_not_passing")
        blocked_reasons.append(
            f"Root regression suite is {root_tests['status']}: {root_tests.get('summary') or 'no summary'}"
        )
    if not wallet_flow["ready"]:
        blocked_checks.append("wallet_flow_not_ready")
        blocked_reasons.append(
            "Wallet-flow bootstrap is not ready: "
            + ", ".join(wallet_flow.get("reasons") or ["unknown"])
        )
    if service["status"] != "running":
        blocked_checks.append("service_not_running")
        blocked_reasons.append(
            f"Remote service is {service['status']} ({service.get('systemctl_state') or 'unknown'})."
        )
    if deploy_validation.get("storage_blocked"):
        blocked_checks.append("remote_runtime_storage_blocked")
        blocked_reasons.append(
            str(
                deploy_validation.get("storage_block_reason")
                or "Remote runtime validation failed because the VPS storage layer is not writable."
            )
        )
    validation_returncode = _int_or_none(deploy_validation.get("returncode"))
    if (
        validation_returncode is not None
        and validation_returncode != 0
        and not bool(deploy_validation.get("storage_blocked"))
    ):
        blocked_checks.append("remote_runtime_validation_incomplete")
        blocked_reasons.append(
            "Remote runtime validation did not complete successfully; launch-control truth is not confirmed."
        )
    if runtime.get("closed_trades", 0) <= 0:
        blocked_checks.append("no_closed_trades")
        blocked_reasons.append("No closed trades are available for calibration yet.")
    if status["capital"]["deployed_capital_usd"] <= 0:
        blocked_checks.append("no_deployed_capital")
        blocked_reasons.append("No capital is currently deployed.")
    if status["polymarket_wallet"].get("status") == "ok":
        actual_deployable = _safe_float(
            status["capital"].get("polymarket_actual_deployable_usd"),
            0.0,
        )
        if actual_deployable <= 0:
            blocked_checks.append("no_polymarket_free_collateral")
            blocked_reasons.append(
                "Observed Polymarket wallet has no free collateral for new maker orders."
            )
        if accounting_reconciliation.get("drift_detected"):
            open_delta = int(
                (accounting_reconciliation.get("unmatched_open_positions") or {}).get(
                    "delta_remote_minus_local", 0
                )
                or 0
            )
            closed_delta = int(
                (accounting_reconciliation.get("unmatched_closed_positions") or {}).get(
                    "delta_remote_minus_local", 0
                )
                or 0
            )
            accounting_delta = _safe_float(
                accounting_reconciliation.get("capital_accounting_delta_usd"),
                0.0,
            )
            blocked_checks.append("polymarket_capital_truth_drift")
            blocked_checks.append("accounting_reconciliation_drift")
            blocked_reasons.append(
                "Accounting drift: "
                f"local ledger open={((accounting_reconciliation.get('local_ledger_counts') or {}).get('open_positions', 0))} "
                f"vs remote wallet open={((accounting_reconciliation.get('remote_wallet_counts') or {}).get('open_positions', 0))} "
                f"(delta {open_delta:+d}); "
                f"local ledger closed={((accounting_reconciliation.get('local_ledger_counts') or {}).get('closed_positions', 0))} "
                f"vs remote wallet closed={((accounting_reconciliation.get('remote_wallet_counts') or {}).get('closed_positions', 0))} "
                f"(delta {closed_delta:+d}); "
                f"capital delta={_format_money(accounting_delta)}."
            )
    # Flywheel promotion posture is advisory for the always-on baseline. We keep
    # it in the operator packet, but it should not force capital idle when the
    # runtime, wallet truth, and risk guardrails are otherwise healthy.

    fast_flow_restart_ready = (
        (root_tests["status"] == "passing" or runtime_validation_passed)
        and wallet_flow["ready"]
        and not bool(deploy_validation.get("storage_blocked"))
    )
    safe_baseline_profile = "shadow_fast_flow" if fast_flow_restart_ready else "blocked_safe"
    if deploy_validation.get("storage_blocked"):
        safe_baseline_reason = "remote_runtime_storage_blocked"
    elif fast_flow_restart_ready:
        safe_baseline_reason = "fast_flow_restart_ready"
    else:
        safe_baseline_reason = "fast_flow_not_ready"

    if root_tests["status"] == "failing" and not runtime_validation_passed:
        next_operator_action = (
            "Merge the root regression repair and rerun `make test` before any restart or deploy."
        )
    elif deploy_validation.get("storage_blocked"):
        next_operator_action = (
            "hold_repair: free VPS disk, rerun remote runtime validation, and retry the launch-control lock in 10 minutes."
        )
    elif "remote_runtime_validation_incomplete" in blocked_checks:
        next_operator_action = (
            "hold_repair: remote runtime validation did not complete; repair the remote validation path and retry launch-control lock in 10 minutes."
        )
    elif root_tests["status"] != "passing" and not runtime_validation_passed:
        next_operator_action = (
            "Refresh the root regression status with `make test` before any restart or deploy."
        )
    elif not wallet_flow["ready"]:
        next_operator_action = (
            "Build wallet-flow bootstrap artifacts, confirm readiness, then restart `jj_live` in paper or shadow fast-flow mode."
        )
    elif service["status"] != "running":
        next_operator_action = (
            "Restart `jj_live` in paper or shadow with conservative caps, keep A-6/B-1 blocked, and collect the first closed trades or structural samples."
        )
    elif any(
        check in blocked_checks
        for check in ("no_polymarket_free_collateral", "polymarket_capital_truth_drift")
    ):
        open_delta = int(
            (accounting_reconciliation.get("unmatched_open_positions") or {}).get(
                "delta_remote_minus_local", 0
            )
            or 0
        )
        closed_delta = int(
            (accounting_reconciliation.get("unmatched_closed_positions") or {}).get(
                "delta_remote_minus_local", 0
            )
            or 0
        )
        next_operator_action = (
            "Resolve accounting drift before any restart: "
            f"open delta={open_delta:+d}, closed delta={closed_delta:+d}, "
            f"capital delta={_format_money(_safe_float(accounting_reconciliation.get('capital_accounting_delta_usd'), 0.0))}. "
            "Refresh runtime truth and do not route new orders until reconciliation is clean and free collateral is visible."
        )
    elif blocked_checks:
        next_operator_action = (
            "Confirm the running `jj_live` mode is paper or shadow; if it is unintentionally live, stop it. "
            "Keep A-6/B-1 blocked and collect the first closed trades or structural samples."
        )
    elif runtime.get("closed_trades", 0) <= 0:
        next_operator_action = (
            "Keep the fast-flow sleeve running until the first closed trades or structural samples appear."
        )
    else:
        next_operator_action = (
            "Advance wallet-flow and LMSR through paper -> shadow -> micro-live, and require explicit operator approval before any live capital deployment."
        )

    return {
        "fast_flow_restart_ready": fast_flow_restart_ready,
        "live_launch_blocked": bool(blocked_checks),
        "blocked_checks": blocked_checks,
        "blocked_reasons": blocked_reasons,
        "next_operator_action": next_operator_action,
        "safe_baseline_profile": safe_baseline_profile,
        "safe_baseline_reason": safe_baseline_reason,
    }


def _build_runtime_truth(
    *,
    status: dict[str, Any],
    jj_state: dict[str, Any],
    intel_snapshot: dict[str, Any],
    service: dict[str, Any],
    launch: dict[str, Any],
    accounting_reconciliation: dict[str, Any],
) -> dict[str, Any]:
    runtime = status["runtime"]

    cycles_completed = int(runtime.get("cycles_completed") or 0)
    jj_state_cycles_completed = int(jj_state.get("cycles_completed") or 0)
    intel_snapshot_cycles_completed = int(intel_snapshot.get("total_cycles") or 0)
    total_trades = int(runtime.get("total_trades") or 0)
    jj_state_total_trades = int(jj_state.get("total_trades") or 0)
    bankroll_usd = _float_or_none(runtime.get("bankroll_usd"))
    jj_state_bankroll_usd = _float_or_none(jj_state.get("bankroll"))

    jj_state_drift_detected = False
    drift_reasons: list[str] = []

    if cycles_completed != jj_state_cycles_completed:
        jj_state_drift_detected = True
        drift_reasons.append(
            "cycles_completed mismatch between refreshed status and jj_state.json "
            f"({cycles_completed} vs {jj_state_cycles_completed})"
        )
    if intel_snapshot_cycles_completed and cycles_completed != intel_snapshot_cycles_completed:
        jj_state_drift_detected = True
        drift_reasons.append(
            "cycles_completed mismatch between refreshed status and data/intel_snapshot.json "
            f"({cycles_completed} vs {intel_snapshot_cycles_completed})"
        )
    if total_trades != jj_state_total_trades:
        jj_state_drift_detected = True
        drift_reasons.append(
            "total_trades mismatch between refreshed status and jj_state.json "
            f"({total_trades} vs {jj_state_total_trades})"
        )
    wallet_truth_overridden = bool(runtime.get("wallet_truth_applied"))

    if (
        bankroll_usd is not None
        and jj_state_bankroll_usd is not None
        and not wallet_truth_overridden
        and abs(bankroll_usd - jj_state_bankroll_usd) > 1e-9
    ):
        jj_state_drift_detected = True
        drift_reasons.append(
            "bankroll mismatch between refreshed status and jj_state.json "
            f"({_format_money(bankroll_usd)} vs {_format_money(jj_state_bankroll_usd)})"
        )

    service_drift_detected = service["status"] == "running" and launch["live_launch_blocked"]
    if service_drift_detected:
        drift_reasons.append(
            f"Service-state drift: {PRIMARY_RUNTIME_SERVICE_NAME} is running while launch posture remains blocked; confirm the remote mode is paper or shadow."
        )
    accounting_drift_detected = bool(accounting_reconciliation.get("drift_detected"))
    if accounting_drift_detected:
        open_delta = int(
            (accounting_reconciliation.get("unmatched_open_positions") or {}).get(
                "delta_remote_minus_local", 0
            )
            or 0
        )
        closed_delta = int(
            (accounting_reconciliation.get("unmatched_closed_positions") or {}).get(
                "delta_remote_minus_local", 0
            )
            or 0
        )
        drift_reasons.append(
            "Accounting drift: "
            f"open delta {open_delta:+d}, "
            f"closed delta {closed_delta:+d}, "
            f"capital delta {_format_money(_safe_float(accounting_reconciliation.get('capital_accounting_delta_usd'), 0.0))}."
        )

    return {
        "service_status": service["status"],
        "cycles_completed": cycles_completed,
        "launch_blocked": launch["live_launch_blocked"],
        "drift_detected": bool(drift_reasons),
        "service_drift_detected": service_drift_detected,
        "accounting_drift_detected": accounting_drift_detected,
        "jj_state_drift_detected": jj_state_drift_detected,
        "next_action": launch["next_operator_action"],
        "drift_reasons": drift_reasons,
    }


def _reconcile_deployment_finish(
    finish: dict[str, Any],
    *,
    service: dict[str, Any],
    launch: dict[str, Any],
) -> dict[str, Any]:
    payload = dict(finish)
    blockers = [
        blocker
        for blocker in list(payload.get("blockers") or [])
        if blocker
        != f"{PRIMARY_RUNTIME_SERVICE_NAME} is intentionally stopped while structural alpha integration is completed."
    ]

    if service["status"] == "running" and launch["live_launch_blocked"]:
        blockers.insert(
            0,
            f"{PRIMARY_RUNTIME_SERVICE_NAME} is currently running on the VPS while launch posture remains blocked; treat this as operational drift until the remote mode is reconciled.",
        )
    elif service["status"] != "running":
        blockers.insert(
            0,
            f"{PRIMARY_RUNTIME_SERVICE_NAME} is {service['status']} ({service.get('systemctl_state') or 'unknown'}).",
        )

    payload["blockers"] = _dedupe_preserve_order(blockers)
    return payload


def _reconcile_cycle_count(
    *,
    status: dict[str, Any],
    jj_state: dict[str, Any],
    intel_snapshot: dict[str, Any],
) -> dict[str, Any]:
    remote_value = _int_or_none(status.get("runtime", {}).get("cycles_completed"))
    jj_state_value = _int_or_none(jj_state.get("cycles_completed"))
    intel_snapshot_value = _int_or_none(intel_snapshot.get("total_cycles"))
    selected_value = remote_value
    selected_source = "reports/remote_cycle_status.json"
    if selected_value is None:
        if jj_state_value is not None:
            selected_value = jj_state_value
            selected_source = "jj_state.json"
        else:
            selected_value = intel_snapshot_value
            selected_source = "data/intel_snapshot.json"
    elif jj_state_value is not None and selected_value == jj_state_value:
        selected_source = "jj_state.json"
    elif intel_snapshot_value is not None and selected_value == intel_snapshot_value:
        selected_source = "data/intel_snapshot.json"

    candidate_values = {
        "jj_state.json": jj_state_value,
        "data/intel_snapshot.json": intel_snapshot_value,
        "reports/remote_cycle_status.json": remote_value,
    }
    nonempty_values = [value for value in candidate_values.values() if value is not None]
    distinct_values = sorted(set(nonempty_values))
    drift_detected = len(distinct_values) > 1
    drift_reasons: list[str] = []
    if drift_detected:
        drift_reasons.append(
            "cycles_completed differs across jj_state.json, data/intel_snapshot.json, and reports/remote_cycle_status.json"
        )

    return {
        "selected_source": selected_source,
        "selected_value": selected_value,
        "candidates": candidate_values,
        "drift_detected": drift_detected,
        "drift_reasons": drift_reasons,
    }


def _summarize_edge_scan(root: Path, path: Path | None) -> dict[str, Any]:
    payload = _load_json(path, default={}) if path is not None else {}
    candidate_markets = payload.get("candidate_markets")
    candidate_count = len(candidate_markets) if isinstance(candidate_markets, list) else 0
    cross_platform = payload.get("cross_platform_arb") if isinstance(payload, dict) else {}
    per_venue_candidates = {
        "polymarket": candidate_count,
        "kalshi": int(
            (
                (cross_platform or {}).get("arb_opportunities")
                or (cross_platform or {}).get("matches")
                or 0
            )
        ),
    }
    per_venue_candidates["total"] = per_venue_candidates["polymarket"] + per_venue_candidates["kalshi"]
    return {
        "path": _relative_path_text(root, path),
        "generated_at": payload.get("generated_at"),
        "recommended_action": payload.get("recommended_action"),
        "action_reason": payload.get("action_reason"),
        "purpose": payload.get("purpose"),
        "markets_pulled": int(payload.get("markets_pulled") or 0),
        "markets_under_24h": int(payload.get("markets_under_24h") or 0),
        "viable_at_current_thresholds": int(payload.get("viable_at_current_thresholds") or 0),
        "viable_at_aggressive_thresholds": int(payload.get("viable_at_aggressive_thresholds") or 0),
        "viable_at_wide_open": int(payload.get("viable_at_wide_open") or 0),
        "per_venue_candidate_counts": per_venue_candidates,
        "candidate_reject_reason_counts": _count_candidate_reject_reasons(candidate_markets),
        "threshold_sensitivity": payload.get("threshold_sensitivity") if isinstance(payload, dict) else {},
    }


def _summarize_fast_market_search(root: Path, path: Path | None) -> dict[str, Any]:
    payload = _load_json(path, default={}) if path is not None else {}
    ranked_candidates = payload.get("ranked_candidates")
    if not isinstance(ranked_candidates, list):
        ranked_candidates = []
    lane_map = payload.get("lane_map")
    if not isinstance(lane_map, list):
        lane_map = []

    btc5_lane_candidates = [
        item
        for item in ranked_candidates
        if isinstance(item, dict)
        and str(item.get("market_scope") or "") == "btc_5m"
    ]
    btc5_candidates = [
        item
        for item in btc5_lane_candidates
        if isinstance(item, dict)
        and str(item.get("candidate_family") or "") != "loss_cluster_suppression"
    ]
    shadow_candidate = next(
        (
            item
            for item in btc5_candidates
            if str(item.get("deployment_mode") or "").strip().lower() == "shadow_only"
        ),
        None,
    )
    top_candidate = shadow_candidate or (btc5_candidates[0] if btc5_candidates else {})
    top_blocking_checks = [
        str(item)
        for item in list((top_candidate.get("blocking_checks") or [])[:10])
        if str(item or "").strip()
    ]
    normalized_lane_map: list[dict[str, Any]] = []
    for raw_lane in lane_map:
        if not isinstance(raw_lane, dict):
            continue
        lane_name = str(raw_lane.get("lane") or "").strip()
        if not lane_name:
            continue
        normalized_lane_map.append(
            {
                "lane": lane_name,
                "candidate_count": int(raw_lane.get("candidate_count") or 0),
                "top_candidate_id": raw_lane.get("top_candidate_id"),
                "top_deployment_class": raw_lane.get("top_deployment_class"),
                "top_evidence_band": raw_lane.get("top_evidence_band"),
                "top_ranking_score": _float_or_none(raw_lane.get("top_ranking_score")),
                "validation_live_filled_rows": int(raw_lane.get("validation_live_filled_rows") or 0),
                "comparison_only": lane_name != "btc_5m",
                "blocking_checks": [
                    str(item)
                    for item in list(raw_lane.get("blocking_checks") or [])
                    if str(item or "").strip()
                ],
            }
        )
    non_champion_lanes = [item for item in normalized_lane_map if item.get("lane") != "btc_5m"]
    challenger_lane = None
    if non_champion_lanes:
        challenger_lane = max(
            non_champion_lanes,
            key=lambda item: (
                int(item.get("candidate_count") or 0),
                _safe_float(item.get("top_ranking_score"), 0.0),
                int(item.get("validation_live_filled_rows") or 0),
            ),
        )
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}

    return {
        "path": _relative_path_text(root, path),
        "generated_at": payload.get("generated_at"),
        "btc5_candidate_count": len(btc5_lane_candidates),
        "btc5_tradeable_candidate_count": len(btc5_candidates),
        "top_candidate_id": top_candidate.get("candidate_id"),
        "top_candidate_name": top_candidate.get("candidate_name"),
        "top_candidate_family": top_candidate.get("candidate_family"),
        "top_deployment_class": top_candidate.get("deployment_class"),
        "top_deployment_mode": top_candidate.get("deployment_mode"),
        "top_blocking_checks": top_blocking_checks,
        "primary_blockers": [
            str(item)
            for item in list(summary.get("primary_blockers") or [])[:10]
            if str(item or "").strip()
        ],
        "shadow_candidate_available": shadow_candidate is not None,
        "confirmation_stale": "confirmation_evidence_stale" in top_blocking_checks,
        "top_candidate_arr_delta_pct": _float_or_none(
            ((top_candidate.get("arr_estimates") or {}).get("median_arr_delta_pct"))
            if isinstance(top_candidate.get("arr_estimates"), dict)
            else None
        ),
        "lane_map": normalized_lane_map,
        "champion_lane": next(
            (item for item in normalized_lane_map if item.get("lane") == "btc_5m"),
            None,
        ),
        "challenger_lane": challenger_lane,
        "comparison_only_lanes": [item["lane"] for item in non_champion_lanes],
    }


def _load_finance_gate_summary(
    *,
    root: Path,
    generated_at: datetime | None,
) -> dict[str, Any]:
    path = root / DEFAULT_FINANCE_LATEST_PATH
    payload = _load_json(path, default={})
    summary = {
        "exists": path.exists() and isinstance(payload, dict),
        "path": _relative_path_text(root, path) or str(path),
        "generated_at": None,
        "age_hours": None,
        "freshness": "unknown",
        "finance_gate_pass": None,
        "treasury_gate_pass": None,
        "stage1_live_trading_allowed": None,
        "treasury_expansion_allowed": None,
        "capital_expansion_only_hold": False,
        "finance_state": None,
        "stage_cap": None,
        "status": "unknown",
        "treasury_status": "unknown",
        "reason": None,
        "treasury_reason": None,
        "retry_at": None,
        "retry_in_minutes": None,
        "requested_mode": None,
        "action_key": None,
        "destination": None,
        "remediation": None,
        "block_reasons": [],
        "rollout_gates": {},
    }
    if not summary["exists"]:
        return summary

    payload = dict(payload)
    last_execute = payload.get("last_execute") if isinstance(payload.get("last_execute"), dict) else {}
    live_hold = last_execute.get("live_hold") if isinstance(last_execute.get("live_hold"), dict) else {}
    artifact_generated_at = _parse_datetime_like(
        _first_nonempty(
            last_execute.get("generated_at"),
            payload.get("generated_at"),
            _safe_iso_mtime(path),
        )
    )
    age_hours = _age_hours_from_datetimes(reference_at=generated_at, observed_at=artifact_generated_at)
    canonical_gate = _load_finance_gate_status_impl(root)
    finance_gate_pass = _bool_or_none(canonical_gate.get("finance_gate_pass"))
    treasury_gate_pass = _bool_or_none(canonical_gate.get("treasury_gate_pass"))
    capital_expansion_only_hold = bool(canonical_gate.get("capital_expansion_only_hold"))
    finance_state = str(canonical_gate.get("finance_state") or "").strip().lower() or None
    stage_cap = _int_or_none(canonical_gate.get("stage_cap"))
    capital_expansion_policy = (
        payload.get("capital_expansion_policy")
        if isinstance(payload.get("capital_expansion_policy"), dict)
        else {}
    )
    finance_gate_payload = payload.get("finance_gate") if isinstance(payload.get("finance_gate"), dict) else {}
    rollout_gates = dict(payload.get("rollout_gates") or last_execute.get("rollout_gates") or {})
    block_reasons = _dedupe_preserve_order(
        [
            str(item).strip()
            for item in list(capital_expansion_policy.get("block_reasons") or [])
            if str(item).strip()
        ]
        + [
            str(item).strip()
            for item in list(rollout_gates.get("reasons") or [])
            if str(item).strip()
        ]
    )
    summary.update(
        {
            "generated_at": artifact_generated_at.isoformat() if artifact_generated_at is not None else None,
            "age_hours": round(age_hours, 4) if age_hours is not None else None,
            "freshness": _freshness_label_for_age_hours(age_hours),
            "finance_gate_pass": finance_gate_pass,
            "treasury_gate_pass": treasury_gate_pass,
            "stage1_live_trading_allowed": finance_gate_pass,
            "treasury_expansion_allowed": treasury_gate_pass,
            "capital_expansion_only_hold": capital_expansion_only_hold,
            "finance_state": finance_state,
            "stage_cap": stage_cap,
            "status": str(
                _first_nonempty(
                    live_hold.get("status"),
                    "pass" if finance_gate_pass else "blocked",
                )
                or "unknown"
            ).strip().lower(),
            "treasury_status": "pass" if treasury_gate_pass else "blocked",
            "reason": _first_nonempty(
                canonical_gate.get("reason"),
                live_hold.get("reason"),
                finance_gate_payload.get("reason"),
            ),
            "treasury_reason": _first_nonempty(
                canonical_gate.get("treasury_reason"),
                finance_gate_payload.get("reason"),
                live_hold.get("reason"),
            ),
            "retry_at": live_hold.get("retry_at"),
            "retry_in_minutes": _int_or_none(live_hold.get("retry_in_minutes")),
            "requested_mode": _first_nonempty(
                live_hold.get("requested_mode"),
                last_execute.get("requested_mode"),
                last_execute.get("mode"),
            ),
            "action_key": live_hold.get("action_key"),
            "destination": live_hold.get("destination"),
            "remediation": _first_nonempty(
                canonical_gate.get("remediation"),
                live_hold.get("remediation"),
                finance_gate_payload.get("remediation"),
            ),
            "block_reasons": block_reasons,
            "rollout_gates": rollout_gates,
        }
    )
    return summary


def _classify_champion_lane_blocker(blocker: Any) -> str:
    normalized = str(blocker or "").strip().lower()
    if not normalized:
        return "candidate"
    if (
        normalized.startswith("confirmation_")
        or normalized.startswith("wallet_flow")
        or normalized.startswith("lmsr")
        or normalized.startswith("signal_source_audit")
        or normalized.startswith("btc_fast_window_confirmation")
        or normalized.startswith("contradiction_penalty")
    ):
        return "confirmation"
    if (
        normalized.startswith("destination_not_whitelisted")
        or normalized.startswith("finance_")
        or normalized.startswith("reserve_floor")
        or normalized.startswith("single_action_cap")
        or normalized.startswith("monthly_commitment")
        or normalized.startswith("whitelist_destination")
        or normalized.startswith("capital_")
        or normalized.startswith("fund_")
        or "not_whitelisted" in normalized
    ):
        return "capital"
    if (
        normalized.startswith("service_")
        or normalized.startswith("stale_service")
        or normalized.startswith("accounting_reconciliation")
        or normalized.startswith("wallet_export_")
        or normalized.startswith("profile_")
        or normalized.startswith("launch_blocked_but_service_running")
        or normalized.startswith("jj_live_non_primary_running_while_launch_blocked")
        or normalized.startswith("service_target_mismatch")
        or "drift" in normalized
        or "mismatch" in normalized
    ):
        return "truth"
    return "candidate"


def _blocker_bucket(
    checks: Sequence[Any],
    *,
    retry_cadence_minutes: int,
) -> dict[str, Any]:
    deduped = _dedupe_preserve_order(
        [str(item).strip() for item in checks if str(item or "").strip()]
    )
    return {
        "status": "blocked" if deduped else "clear",
        "checks": deduped,
        "retry_cadence_minutes": int(retry_cadence_minutes),
    }


def _build_champion_lane_contract(
    *,
    generated_at: datetime,
    fast_market_search: dict[str, Any],
    deployment_confidence: dict[str, Any],
    selected_package_summary: dict[str, Any],
    finance_gate: dict[str, Any],
) -> dict[str, Any]:
    blocking_checks = _dedupe_preserve_order(
        [
            *list(deployment_confidence.get("blocking_checks") or []),
            *list(selected_package_summary.get("blocking_checks") or []),
            *list(fast_market_search.get("top_blocking_checks") or []),
            *list(fast_market_search.get("primary_blockers") or []),
        ]
    )
    truth_blockers: list[str] = []
    candidate_blockers: list[str] = []
    confirmation_blockers: list[str] = []
    capital_blockers: list[str] = []
    for blocker in blocking_checks:
        category = _classify_champion_lane_blocker(blocker)
        if category == "truth":
            truth_blockers.append(str(blocker))
        elif category == "confirmation":
            confirmation_blockers.append(str(blocker))
        elif category == "capital":
            capital_blockers.append(str(blocker))
        else:
            candidate_blockers.append(str(blocker))
    if finance_gate.get("finance_gate_pass") is False and finance_gate.get("reason"):
        capital_blockers.append(str(finance_gate.get("reason")))

    truth_blockers = _dedupe_preserve_order(truth_blockers)
    candidate_blockers = _dedupe_preserve_order(candidate_blockers)
    confirmation_blockers = _dedupe_preserve_order(confirmation_blockers)
    capital_blockers = _dedupe_preserve_order(capital_blockers)

    champion_candidate_count = int(fast_market_search.get("btc5_candidate_count") or 0)
    can_trade_now = bool(deployment_confidence.get("can_btc5_trade_now"))
    shadow_candidate_available = bool(fast_market_search.get("shadow_candidate_available"))
    ignorable_shadow_truth_blockers = {
        "service_status_stale",
        "stale_service_file_with_fresh_btc5_probe",
    }
    hard_truth_blockers = list(truth_blockers)
    if champion_candidate_count > 0 and shadow_candidate_available:
        hard_truth_blockers = [
            blocker
            for blocker in truth_blockers
            if blocker not in ignorable_shadow_truth_blockers
        ]

    if hard_truth_blockers:
        status = "hold_repair"
        decision_reason = "truth_surface_repair_required_before_champion_lane_can_run"
    elif can_trade_now:
        status = "candidate_ready"
        decision_reason = "btc5_is_the_only_tradeable_champion_lane"
    elif champion_candidate_count > 0 and shadow_candidate_available:
        status = "shadow_only"
        decision_reason = "btc5_has_a_shadow_candidate_but_live_promotion_is_still_blocked"
    else:
        status = "hold_repair"
        decision_reason = "no_runnable_btc5_candidate_exists_for_this_cycle"

    retry_minutes = _int_or_none(finance_gate.get("retry_in_minutes"))
    if retry_minutes is None:
        retry_minutes = 10 if status == "shadow_only" else 5
    challenger_lane = dict(fast_market_search.get("challenger_lane") or {})
    # Match the canonical live-profile precedence used by
    # _resolve_canonical_live_profile_id in remote_cycle_reconciliation.py:
    # active (currently-running) first, then best (frontier candidate).
    selected_profile_name = _first_nonempty(
        selected_package_summary.get("selected_active_profile_name"),
        selected_package_summary.get("selected_best_profile_name"),
        fast_market_search.get("top_candidate_name"),
    )
    top_candidate_id = _first_nonempty(
        fast_market_search.get("top_candidate_id"),
        selected_package_summary.get("selected_best_profile_name"),
    )
    if status == "candidate_ready":
        next_action = (
            f"Run BTC5 as the only champion lane using {selected_profile_name or 'the selected runtime package'}; "
            f"keep {challenger_lane.get('lane') or 'all non-BTC5 lanes'} comparison-only and refresh the cycle packet in +{retry_minutes}m."
        )
    elif status == "shadow_only":
        next_action = (
            f"Keep BTC5 shadow-only via {top_candidate_id or 'the current shadow candidate'}; "
            f"repair {((confirmation_blockers or candidate_blockers) or ['the remaining promotion blockers'])[0]} and rerun the cycle packet in +{retry_minutes}m."
        )
    else:
        next_action = (
            f"Repair {((truth_blockers or capital_blockers or candidate_blockers or confirmation_blockers) or ['the active blocker set'])[0]} "
            f"before any lane promotion; rerun the cycle packet in +{retry_minutes}m."
        )

    return {
        "generated_at": generated_at.isoformat(),
        "status": status,
        "decision_reason": decision_reason,
        "champion_lane": {
            "lane": "btc_5m",
            "role": "champion",
            "candidate_count": champion_candidate_count,
            "top_candidate_id": fast_market_search.get("top_candidate_id"),
            "top_candidate_family": fast_market_search.get("top_candidate_family"),
            "top_deployment_mode": fast_market_search.get("top_deployment_mode"),
            "selected_profile_name": selected_profile_name,
            "selected_deploy_recommendation": selected_package_summary.get("selected_deploy_recommendation"),
            "selected_package_confidence_label": selected_package_summary.get("selected_package_confidence_label"),
            "selected_package_validated_for_live_stage1": bool(
                selected_package_summary.get("validated_for_live_stage1")
            ),
            "allowed_stage": deployment_confidence.get("allowed_stage"),
            "allowed_stage_label": deployment_confidence.get("allowed_stage_label"),
            "can_trade_now": can_trade_now,
        },
        "challenger_rule_set": {
            "policy": "comparison_only_until_replayable_evidence",
            "active_challenger_lane": challenger_lane.get("lane"),
            "active_challenger_status": "comparison_only" if challenger_lane else "none",
            "comparison_only_lanes": list(fast_market_search.get("comparison_only_lanes") or []),
        },
        "blocker_classes": {
            "truth": _blocker_bucket(truth_blockers, retry_cadence_minutes=5),
            "candidate": _blocker_bucket(candidate_blockers, retry_cadence_minutes=10),
            "confirmation": _blocker_bucket(confirmation_blockers, retry_cadence_minutes=10),
            "capital": _blocker_bucket(
                capital_blockers,
                retry_cadence_minutes=_int_or_none(finance_gate.get("retry_in_minutes")) or 30,
            ),
        },
        "finance_gate": {
            "finance_gate_pass": finance_gate.get("finance_gate_pass"),
            "status": finance_gate.get("status"),
            "reason": finance_gate.get("reason"),
            "retry_at": finance_gate.get("retry_at"),
            "retry_in_minutes": finance_gate.get("retry_in_minutes"),
            "requested_mode": finance_gate.get("requested_mode"),
            "destination": finance_gate.get("destination"),
            "remediation": finance_gate.get("remediation"),
        },
        "required_outputs": {
            "candidate_delta_arr_bps": int(
                round(_safe_float(selected_package_summary.get("median_arr_delta_pct"), 0.0) * 100.0)
            ),
            "expected_improvement_velocity_delta": 0.0,
            "arr_confidence_score": round(_safe_float(deployment_confidence.get("overall_score"), 0.0), 4),
            "block_reasons": _dedupe_preserve_order(
                [*truth_blockers, *candidate_blockers, *confirmation_blockers, *capital_blockers]
            ),
            "finance_gate_pass": bool(finance_gate.get("finance_gate_pass")),
            "one_next_cycle_action": next_action,
        },
    }


def _summarize_pipeline(root: Path, path: Path | None) -> dict[str, Any]:
    payload = _load_json(path, default={}) if path is not None else {}
    verdict = payload.get("pipeline_verdict") or {}
    verification = payload.get("verification") or {}
    threshold_sensitivity = payload.get("threshold_sensitivity") if isinstance(payload, dict) else {}
    current_threshold = threshold_sensitivity.get("current") if isinstance(threshold_sensitivity, dict) else {}
    new_viable = payload.get("new_viable_strategies")
    return {
        "path": _relative_path_text(root, path),
        "report_generated_at": payload.get("report_generated_at"),
        "run_timestamp": payload.get("run_timestamp"),
        "recommendation": verdict.get("recommendation"),
        "reasoning": verdict.get("reasoning"),
        "markets_pulled": int(payload.get("markets_pulled") or 0),
        "markets_under_24h": int(payload.get("markets_under_24h") or 0),
        "markets_in_allowed_categories": int(payload.get("markets_in_allowed_categories") or 0),
        "pipeline_candidate_count": len(new_viable) if isinstance(new_viable, list) else 0,
        "current_tradeable": int((current_threshold or {}).get("tradeable") or 0),
        "current_yes_reachable_markets": int((current_threshold or {}).get("yes_reachable_markets") or 0),
        "current_no_reachable_markets": int((current_threshold or {}).get("no_reachable_markets") or 0),
        "verification": {
            "integrated_entrypoint_status": verification.get("integrated_entrypoint_status"),
            "make_test_status": verification.get("make_test_status"),
            "root_suite": verification.get("root_suite"),
            "jj_live_import_boundary_suite": verification.get("jj_live_import_boundary_suite"),
        },
    }


def _normalize_runtime_policy_record(raw_policy: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(raw_policy, dict):
        return None
    name = str(raw_policy.get("name") or raw_policy.get("session_name") or "").strip()
    raw_hours = raw_policy.get("et_hours")
    et_hours: list[int] = []
    if isinstance(raw_hours, list):
        for value in raw_hours:
            try:
                hour = int(value)
            except (TypeError, ValueError):
                continue
            if 0 <= hour <= 23 and hour not in et_hours:
                et_hours.append(hour)
    if not name or not et_hours:
        return None

    payload: dict[str, Any] = {"name": name, "et_hours": et_hours}
    for key in (
        "min_delta",
        "max_abs_delta",
        "up_max_buy_price",
        "down_max_buy_price",
    ):
        value = _float_or_none(raw_policy.get(key))
        if value is not None:
            payload[key] = value
    maker_ticks = _int_or_none(raw_policy.get("maker_improve_ticks"))
    if maker_ticks is not None and maker_ticks >= 0:
        payload["maker_improve_ticks"] = maker_ticks
    return payload


def _derive_session_policy_from_hypothesis(raw_hypothesis: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(raw_hypothesis, dict):
        return []
    normalized = _normalize_runtime_policy_record(raw_hypothesis)
    return [normalized] if normalized is not None else []


def _pick_first_policy_list(*candidates: Any) -> list[dict[str, Any]]:
    for candidate in candidates:
        if not isinstance(candidate, list):
            continue
        policies: list[dict[str, Any]] = []
        for item in candidate:
            if not isinstance(item, dict):
                continue
            normalized = _normalize_runtime_policy_record(item)
            if normalized is not None:
                policies.append(normalized)
        if policies:
            return policies
    return []


def _extract_btc5_research_snapshot(
    *,
    root: Path,
    generated_at: datetime,
) -> dict[str, Any]:
    paths = [*BTC5_RESEARCH_PRIMARY_PATHS, *BTC5_RESEARCH_OPTIONAL_PATHS]
    artifacts: dict[str, dict[str, Any]] = {}
    for relative_path in paths:
        absolute_path = root / relative_path
        payload = _load_json(absolute_path, default={})
        timestamp = None
        if isinstance(payload, dict):
            timestamp = _parse_datetime_like(
                _first_nonempty(
                    payload.get("generated_at"),
                    payload.get("summary", {}).get("last_cycle_finished_at") if isinstance(payload.get("summary"), dict) else None,
                    payload.get("latest_entry", {}).get("finished_at") if isinstance(payload.get("latest_entry"), dict) else None,
                )
            )
        if timestamp is None and absolute_path.exists():
            timestamp = _parse_datetime_like(_safe_iso_mtime(absolute_path))
        age_hours = (
            (generated_at - timestamp).total_seconds() / 3600.0
            if timestamp is not None
            else None
        )
        artifacts[str(relative_path)] = {
            "path": str(relative_path),
            "exists": absolute_path.exists(),
            "payload": payload if isinstance(payload, dict) else {},
            "timestamp": timestamp,
            "age_hours": age_hours,
            "stale": bool(age_hours is not None and age_hours > BTC5_RESEARCH_STALE_HOURS),
            "primary": relative_path in BTC5_RESEARCH_PRIMARY_PATHS,
        }
    return artifacts


def _build_btc5_research_recommendation(
    *,
    root: Path,
    generated_at: datetime,
    btc5_maker: dict[str, Any],
) -> dict[str, Any]:
    artifacts = _extract_btc5_research_snapshot(root=root, generated_at=generated_at)
    autoresearch = artifacts[str(Path("reports/btc5_autoresearch/latest.json"))]["payload"]
    loop_latest = artifacts[str(Path("reports/btc5_autoresearch_loop/latest.json"))]["payload"]
    hypothesis_summary = artifacts[str(Path("reports/btc5_hypothesis_lab/summary.json"))]["payload"]
    regime_summary = artifacts[str(Path("reports/btc5_regime_policy_lab/summary.json"))]["payload"]

    loop_entry = loop_latest.get("latest_entry") if isinstance(loop_latest, dict) else {}
    if not isinstance(loop_entry, dict):
        loop_entry = {}

    arr_tracking = autoresearch.get("arr_tracking") if isinstance(autoresearch, dict) else {}
    if not isinstance(arr_tracking, dict):
        arr_tracking = {}
    loop_arr = loop_entry.get("arr") if isinstance(loop_entry, dict) else {}
    if not isinstance(loop_arr, dict):
        loop_arr = {}

    active_median_arr_pct = _float_or_none(
        _first_nonempty(arr_tracking.get("current_median_arr_pct"), loop_arr.get("active_median_arr_pct"))
    )
    best_median_arr_pct = _float_or_none(
        _first_nonempty(arr_tracking.get("best_median_arr_pct"), loop_arr.get("best_median_arr_pct"))
    )
    median_arr_delta_pct = _float_or_none(
        _first_nonempty(arr_tracking.get("median_arr_delta_pct"), loop_arr.get("median_arr_delta_pct"))
    )
    active_p05_arr_pct = _float_or_none(
        _first_nonempty(arr_tracking.get("current_p05_arr_pct"), loop_arr.get("active_p05_arr_pct"))
    )
    best_p05_arr_pct = _float_or_none(
        _first_nonempty(arr_tracking.get("best_p05_arr_pct"), loop_arr.get("best_p05_arr_pct"))
    )

    best_summary = {}
    if isinstance(hypothesis_summary.get("best_hypothesis"), dict):
        candidate = hypothesis_summary["best_hypothesis"].get("summary")
        if isinstance(candidate, dict):
            best_summary = candidate
    loop_hypothesis = loop_entry.get("hypothesis_lab") if isinstance(loop_entry, dict) else {}
    if not best_summary and isinstance(loop_hypothesis, dict):
        candidate = loop_hypothesis.get("best_summary")
        if isinstance(candidate, dict):
            best_summary = candidate
    regime_best_summary = regime_summary.get("best_summary") if isinstance(regime_summary, dict) else None
    if not best_summary and isinstance(regime_best_summary, dict):
        best_summary = regime_best_summary

    validation_live_filled_rows = _int_or_none(best_summary.get("validation_live_filled_rows"))
    generalization_ratio = _float_or_none(best_summary.get("generalization_ratio"))
    evidence_band = _first_nonempty(
        best_summary.get("evidence_band"),
        regime_summary.get("evidence_band") if isinstance(regime_summary, dict) else None,
    )

    baseline = hypothesis_summary.get("baseline") if isinstance(hypothesis_summary, dict) else {}
    baseline_live_filled_rows = _int_or_none(
        _first_nonempty(
            baseline.get("deduped_live_filled_rows") if isinstance(baseline, dict) else None,
            baseline.get("rows") if isinstance(baseline, dict) else None,
        )
    )
    if baseline_live_filled_rows is None:
        baseline_live_filled_rows = _int_or_none(btc5_maker.get("live_filled_rows"))

    decision = autoresearch.get("decision") if isinstance(autoresearch, dict) else {}
    if not isinstance(decision, dict):
        decision = {}
    if not decision:
        candidate = loop_entry.get("decision")
        if isinstance(candidate, dict):
            decision = candidate

    active_profile = _first_nonempty(
        autoresearch.get("active_profile") if isinstance(autoresearch, dict) else None,
        loop_entry.get("active_profile") if isinstance(loop_entry, dict) else None,
    )
    best_profile = _first_nonempty(
        (autoresearch.get("best_candidate") or {}).get("profile") if isinstance(autoresearch, dict) else None,
        loop_entry.get("best_profile") if isinstance(loop_entry, dict) else None,
    )

    hypothesis_best = {}
    if isinstance(hypothesis_summary.get("best_hypothesis"), dict):
        hypothesis_best = hypothesis_summary["best_hypothesis"].get("hypothesis") or {}
    if not isinstance(hypothesis_best, dict):
        hypothesis_best = {}
    loop_best_hypothesis = {}
    if isinstance(loop_hypothesis, dict):
        loop_best_hypothesis = loop_hypothesis.get("best_hypothesis") or {}
    if not isinstance(loop_best_hypothesis, dict):
        loop_best_hypothesis = {}

    recommended_session_policy = _pick_first_policy_list(
        regime_summary.get("recommended_session_policy") if isinstance(regime_summary, dict) else None,
        hypothesis_summary.get("recommended_session_policy") if isinstance(hypothesis_summary, dict) else None,
        loop_entry.get("recommended_session_policy") if isinstance(loop_entry, dict) else None,
        _derive_session_policy_from_hypothesis(hypothesis_best),
        _derive_session_policy_from_hypothesis(loop_best_hypothesis),
    )

    source_artifacts = [
        item["path"]
        for item in artifacts.values()
        if item["exists"]
    ]

    confidence_reasons: list[str] = []
    for relative_path in BTC5_RESEARCH_PRIMARY_PATHS:
        info = artifacts[str(relative_path)]
        if not info["exists"]:
            confidence_reasons.append(f"missing_primary_research_artifact:{info['path']}")
            continue
        if info["stale"]:
            age = info.get("age_hours")
            if age is None:
                confidence_reasons.append(f"stale_primary_research_artifact:{info['path']}:unknown_age")
            else:
                confidence_reasons.append(
                    f"stale_primary_research_artifact:{info['path']}:{age:.2f}h>{BTC5_RESEARCH_STALE_HOURS:.1f}h"
                )

    required_missing = [
        name
        for name, value in (
            ("validation_live_filled_rows", validation_live_filled_rows),
            ("generalization_ratio", generalization_ratio),
            ("best_p05_arr_pct", best_p05_arr_pct),
            ("active_p05_arr_pct", active_p05_arr_pct),
        )
        if value is None
    ]
    if required_missing:
        confidence_reasons.append("missing_required_fields:" + ",".join(required_missing))

    confidence_label = "low"
    if (
        validation_live_filled_rows is not None
        and generalization_ratio is not None
        and best_p05_arr_pct is not None
        and active_p05_arr_pct is not None
    ):
        if (
            validation_live_filled_rows >= 12
            and generalization_ratio >= 0.80
            and best_p05_arr_pct >= active_p05_arr_pct
        ):
            confidence_label = "high"
        elif validation_live_filled_rows >= 6 and generalization_ratio >= 0.70:
            confidence_label = "medium"
    confidence_reasons.append(f"confidence_rule:{confidence_label}")

    forecast_confidence = {
        "confidence_label": confidence_label,
        "confidence_reasons": confidence_reasons,
        "active_median_arr_pct": active_median_arr_pct,
        "best_median_arr_pct": best_median_arr_pct,
        "median_arr_delta_pct": median_arr_delta_pct,
        "active_p05_arr_pct": active_p05_arr_pct,
        "best_p05_arr_pct": best_p05_arr_pct,
        "validation_live_filled_rows": validation_live_filled_rows,
        "baseline_live_filled_rows": baseline_live_filled_rows,
        "generalization_ratio": generalization_ratio,
        "decision_action": decision.get("action"),
        "decision_reason": decision.get("reason"),
        "source_artifacts": source_artifacts,
    }

    local_fill_rows = _int_or_none(btc5_maker.get("live_filled_rows"))
    edge_profile = dict((btc5_maker.get("fill_attribution") or {}))
    if local_fill_rows is None or local_fill_rows < 6:
        edge_profile.update(
            {
                "active_profile": active_profile or {},
                "best_profile": best_profile or {},
                "recommended_session_policy": recommended_session_policy,
                "evidence_band": evidence_band,
                "validation_live_filled_rows": validation_live_filled_rows,
                "generalization_ratio": generalization_ratio,
                "source_artifacts": source_artifacts,
            }
        )

    return {
        "btc5_forecast_confidence": forecast_confidence,
        "btc5_edge_profile": edge_profile,
    }


def _confidence_rank(label: str | None) -> int:
    normalized = str(label or "").strip().lower()
    if normalized == "high":
        return 3
    if normalized == "medium":
        return 2
    return 1


def _deploy_rank(value: str | None) -> int:
    normalized = str(value or "").strip().lower()
    if normalized == "promote":
        return 3
    if normalized == "shadow_only":
        return 2
    return 1


def _forecast_source_kind(path: Path) -> str:
    normalized = str(path).replace("\\", "/")
    if normalized.endswith("reports/btc5_autoresearch/latest.json"):
        return "standard"
    if normalized.endswith("reports/btc5_autoresearch_current_probe/latest.json"):
        return "current_probe"
    if normalized.endswith("reports/btc5_autoresearch_loop/latest.json"):
        return "loop"
    return "other"


def _forecast_authority_rank(source_kind: str) -> int:
    return {
        "standard": 3,
        "loop": 2,
        "current_probe": 1,
    }.get(str(source_kind or "").strip().lower(), 0)


def _extract_public_forecast_candidate(
    *,
    root: Path,
    path: Path,
    payload: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    latest_entry = payload.get("latest_entry") if isinstance(payload.get("latest_entry"), dict) else {}
    arr_root = payload.get("arr") if isinstance(payload.get("arr"), dict) else {}
    arr_tracking = payload.get("arr_tracking") if isinstance(payload.get("arr_tracking"), dict) else {}
    arr_loop = latest_entry.get("arr") if isinstance(latest_entry.get("arr"), dict) else {}

    active_arr = _float_or_none(
        _first_nonempty(
            arr_root.get("active_median_arr_pct"),
            arr_tracking.get("current_median_arr_pct"),
            arr_loop.get("active_median_arr_pct"),
        )
    )
    best_arr = _float_or_none(
        _first_nonempty(
            arr_root.get("best_median_arr_pct"),
            arr_tracking.get("best_median_arr_pct"),
            arr_loop.get("best_median_arr_pct"),
        )
    )
    arr_delta = _float_or_none(
        _first_nonempty(
            arr_root.get("median_arr_delta_pct"),
            arr_tracking.get("median_arr_delta_pct"),
            arr_loop.get("median_arr_delta_pct"),
        )
    )

    decision_payload = payload.get("decision") if isinstance(payload.get("decision"), dict) else {}
    if not decision_payload and isinstance(latest_entry.get("decision"), dict):
        decision_payload = latest_entry["decision"]
    deploy_recommendation = _first_nonempty(
        payload.get("deploy_recommendation"),
        latest_entry.get("deploy_recommendation") if isinstance(latest_entry, dict) else None,
        "promote" if str(decision_payload.get("action") or "").strip().lower() == "promote" else "hold",
    )
    confidence_label = _first_nonempty(
        payload.get("package_confidence_label"),
        payload.get("forecast_confidence_label"),
        latest_entry.get("package_confidence_label") if isinstance(latest_entry, dict) else None,
        "low",
    )
    confidence_reasons = _first_nonempty(
        payload.get("package_confidence_reasons"),
        payload.get("forecast_confidence_reasons"),
        latest_entry.get("package_confidence_reasons") if isinstance(latest_entry, dict) else None,
        [],
    )
    if not isinstance(confidence_reasons, list):
        confidence_reasons = []

    generated_at = _parse_datetime_like(
        _first_nonempty(
            payload.get("generated_at"),
            payload.get("summary", {}).get("last_cycle_finished_at") if isinstance(payload.get("summary"), dict) else None,
            latest_entry.get("finished_at") if isinstance(latest_entry, dict) else None,
            _safe_iso_mtime(path),
        )
    )
    age_hours = (
        (now - generated_at).total_seconds() / 3600.0
        if generated_at is not None
        else None
    )
    fresh = bool(age_hours is not None and age_hours <= BTC5_RESEARCH_STALE_HOURS)
    source_kind = _forecast_source_kind(path)
    runtime_package_selection = (
        payload.get("runtime_package_selection")
        if isinstance(payload.get("runtime_package_selection"), dict)
        else {}
    )
    frontier_authoritative = bool(
        source_kind == "standard"
        and str(runtime_package_selection.get("selection_source") or "").strip().lower() == "frontier_policy_loss"
    )

    return {
        "path": _relative_path_text(root, path),
        "exists": path.exists(),
        "generated_at": generated_at,
        "age_hours": age_hours,
        "fresh": fresh,
        "source_kind": source_kind,
        "authority_rank": _forecast_authority_rank(source_kind),
        "frontier_authoritative": frontier_authoritative,
        "deploy_recommendation": str(deploy_recommendation or "hold"),
        "confidence_label": str(confidence_label or "low"),
        "confidence_reasons": confidence_reasons,
        "active_arr_pct": active_arr,
        "best_arr_pct": best_arr,
        "arr_delta_pct": arr_delta,
    }


def _select_public_forecast_candidate(*, root: Path, generated_at: datetime) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for relative_path in BTC5_PUBLIC_FORECAST_PATHS:
        absolute_path = root / relative_path
        payload = _load_json(absolute_path, default={})
        if not absolute_path.exists() or not isinstance(payload, dict):
            continue
        candidates.append(
            _extract_public_forecast_candidate(
                root=root,
                path=absolute_path,
                payload=payload,
                now=generated_at,
            )
        )

    if not candidates:
        return {
            "selected": None,
            "considered": [],
            "selection_reason": "no_forecast_artifacts_available",
        }

    fresh_candidates = [item for item in candidates if item.get("fresh")]
    pool = fresh_candidates if fresh_candidates else candidates
    selected = max(
        pool,
        key=lambda item: (
            bool(item.get("frontier_authoritative")),
            _confidence_rank(item.get("confidence_label")),
            _deploy_rank(item.get("deploy_recommendation")),
            int(item.get("authority_rank") or 0),
            item["generated_at"].timestamp() if isinstance(item.get("generated_at"), datetime) else float("-inf"),
        ),
    )
    return {
        "selected": selected,
        "considered": candidates,
        "selection_reason": (
            "fresh_authoritative_frontier_ranked_selection"
            if fresh_candidates and bool(selected.get("frontier_authoritative"))
            else ("fresh_ranked_selection" if fresh_candidates else "stale_fallback_selection")
        ),
    }


def _build_truth_lattice(
    *,
    runtime: dict[str, Any],
    launch: dict[str, Any],
    public_performance_scoreboard: dict[str, Any],
    wallet_reconciliation_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    broken_reasons: list[str] = []
    trade_source = str(runtime.get("total_trades_source") or "").strip()
    trade_observations = {
        key: int(value or 0)
        for key, value in dict(runtime.get("total_trades_observations") or {}).items()
    }
    contract_trade_keys = (
        "runtime.trade_db_total_trades",
        "runtime.closed_plus_open",
        "wallet.open_plus_closed",
    )
    contract_trade_observations = {
        key: value
        for key, value in trade_observations.items()
        if key in contract_trade_keys
    }
    distinct_positive_trade_counts = sorted(
        {
            value
            for value in contract_trade_observations.values()
            if value > 0
        }
    )
    if len(distinct_positive_trade_counts) > 1:
        broken_reasons.append("trade_count_divergence_requires_repair_branch")
    if bool(public_performance_scoreboard.get("deploy_recommendation_conflict")):
        broken_reasons.append("forecast_deploy_recommendation_conflict_requires_repair_branch")
    wallet_summary = wallet_reconciliation_summary if isinstance(wallet_reconciliation_summary, dict) else {}
    wallet_export_candidate_conflicts = list(wallet_summary.get("candidate_conflicts") or [])
    wallet_reporting_precedence = str(wallet_summary.get("reporting_precedence") or "").strip().lower()
    if wallet_export_candidate_conflicts and wallet_reporting_precedence == "wallet_export":
        broken_reasons.append("wallet_export_candidate_conflict_requires_repair_branch")

    broken_reasons = _dedupe_preserve_order(broken_reasons)
    repair_branch_required = bool(broken_reasons)
    if "trade_count_divergence_requires_repair_branch" in broken_reasons:
        next_action = (
            "Repair total-trade truth divergence across runtime, wallet, and BTC5 sources before any promotion; "
            "rerun `python3 scripts/write_remote_cycle_status.py` after the trade-count contract is coherent."
        )
    elif "forecast_deploy_recommendation_conflict_requires_repair_branch" in broken_reasons:
        next_action = (
            "Repair contradictory forecast deploy recommendations across BTC5 artifacts, then rerun "
            "`python3 scripts/write_remote_cycle_status.py` before promoting any lane."
        )
    elif "wallet_export_candidate_conflict_requires_repair_branch" in broken_reasons:
        next_action = (
            "Reconcile conflicting Polymarket wallet exports that are currently being used for reporting, then rerun "
            "`python3 scripts/write_remote_cycle_status.py` before promoting any lane."
        )
    else:
        next_action = "Truth lattice is coherent; continue with the current launch and champion-lane contract."

    return {
        "status": "broken" if repair_branch_required else "consistent",
        "repair_branch_required": repair_branch_required,
        "broken_reasons": broken_reasons,
        "selected_values": {
            "launch_posture": launch.get("posture"),
            "total_trades": runtime.get("total_trades"),
            "total_trades_source": trade_source or None,
            "selected_deploy_recommendation": public_performance_scoreboard.get(
                "selected_deploy_recommendation"
            ),
            "effective_deploy_recommendation": public_performance_scoreboard.get(
                "deploy_recommendation"
            ),
            "wallet_reporting_precedence": wallet_reporting_precedence or None,
        },
        "observations": {
            "total_trades_observations": trade_observations,
            "contract_trade_observations": contract_trade_observations,
            "distinct_positive_trade_counts": distinct_positive_trade_counts,
            "forecast_considered_artifacts": list(
                public_performance_scoreboard.get("forecast_considered_artifacts") or []
            ),
            "forecast_selection_reason": public_performance_scoreboard.get(
                "forecast_selection_reason"
            ),
            "wallet_export_candidate_conflicts": wallet_export_candidate_conflicts,
        },
        "one_next_cycle_action": next_action,
    }


def _derive_btc5_selection_compat_fields(snapshot: dict[str, Any]) -> dict[str, Any]:
    selected_package = dict(snapshot.get("btc5_selected_package") or {})
    selected_best_profile = str(
        _first_nonempty(
            snapshot.get("selected_best_profile"),
            selected_package.get("selected_best_profile_name"),
            selected_package.get("selected_active_profile_name"),
            snapshot.get("selected_policy_id"),
        )
        or ""
    ).strip() or None
    selected_policy_id = str(
        _first_nonempty(
            snapshot.get("selected_policy_id"),
            selected_package.get("selected_policy_id"),
            selected_best_profile,
        )
        or ""
    ).strip() or None
    selected_best_runtime_package = (
        snapshot.get("selected_best_runtime_package")
        if isinstance(snapshot.get("selected_best_runtime_package"), dict)
        else (
            selected_package.get("selected_best_runtime_package")
            if isinstance(selected_package.get("selected_best_runtime_package"), dict)
            else None
        )
    )
    promotion_state = str(
        _first_nonempty(
            snapshot.get("promotion_state"),
            selected_package.get("promotion_state"),
            "live_promoted" if bool(selected_package.get("promoted_package_selected")) else None,
        )
        or ""
    ).strip().lower() or None
    return {
        "selected_best_profile": selected_best_profile,
        "selected_policy_id": selected_policy_id,
        "selected_best_runtime_package": selected_best_runtime_package,
        "promotion_state": promotion_state,
        "selected_runtime_package_freshness": selected_package.get("freshness"),
        "selected_runtime_package_generated_at": selected_package.get("generated_at"),
    }


def _apply_shared_truth_contract(
    runtime_truth_snapshot: dict[str, Any],
) -> dict[str, Any]:
    snapshot = dict(runtime_truth_snapshot)
    state_improvement = dict(snapshot.get("state_improvement") or {})
    strategy = dict(state_improvement.get("strategy_recommendations") or {})
    truth_lattice = dict(strategy.get("truth_lattice") or {})
    wallet_reconciliation_summary = dict(strategy.get("wallet_reconciliation_summary") or {})
    public_performance_scoreboard = dict(strategy.get("public_performance_scoreboard") or {})
    champion_lane_contract = dict(strategy.get("champion_lane_contract") or {})
    truth_precedence = dict(
        snapshot.get("truth_precedence")
        or state_improvement.get("truth_precedence")
        or {}
    )

    broken_reasons = list(truth_lattice.get("broken_reasons") or [])
    launch_posture = str(
        _first_nonempty(
            snapshot.get("launch_posture"),
            ((snapshot.get("launch") or {}).get("posture")),
            ((snapshot.get("summary") or {}).get("launch_posture")),
        )
        or "unknown"
    ).strip().lower()
    service_state = str(
        _first_nonempty(
            snapshot.get("service_state"),
            ((snapshot.get("service") or {}).get("status")),
        )
        or "unknown"
    ).strip().lower()
    allow_order_submission = bool(snapshot.get("allow_order_submission"))
    deployment_confidence = dict(snapshot.get("deployment_confidence") or {})
    confirmation_label = str(
        _first_nonempty(
            deployment_confidence.get("confirmation_coverage_label"),
            deployment_confidence.get("confirmation_freshness_label"),
            "unknown",
        )
        or "unknown"
    ).strip().lower()
    confirmation_blocking_checks = {
        str(item).strip()
        for item in (
            deployment_confidence.get("blocking_checks")
            or []
        )
        if str(item).strip()
    }
    deploy_conflict = bool(public_performance_scoreboard.get("deploy_recommendation_conflict"))
    wallet_export_candidate_conflicts = list(wallet_reconciliation_summary.get("candidate_conflicts") or [])
    wallet_reporting_precedence = str(wallet_reconciliation_summary.get("reporting_precedence") or "").strip().lower()
    launch_contract_not_runnable = (
        launch_posture == "blocked"
        and service_state != "running"
        and not allow_order_submission
    )
    confirmation_not_decision_ready = (
        confirmation_label in {"missing", "weak", "stale", "unknown"}
        or bool(
            {
                "confirmation_coverage_insufficient",
                "signal_source_audit_missing",
                "signal_source_audit_stale",
                "wallet_flow_vs_llm_not_ready",
            }
            & confirmation_blocking_checks
        )
    )

    if launch_contract_not_runnable:
        broken_reasons.append("launch_contract_not_runnable_requires_repair_branch")
    if launch_contract_not_runnable and confirmation_not_decision_ready:
        broken_reasons.append("launch_contract_confirmation_not_ready_requires_repair_branch")
    if deploy_conflict:
        broken_reasons.append("forecast_deploy_recommendation_conflict_requires_repair_branch")
    if wallet_export_candidate_conflicts and wallet_reporting_precedence == "wallet_export":
        broken_reasons.append("wallet_export_candidate_conflict_requires_repair_branch")

    broken_reasons = _dedupe_preserve_order(broken_reasons)
    repair_branch_required = bool(broken_reasons)
    truth_gate_status = "hold_repair" if repair_branch_required else "consistent"
    one_next_cycle_action = str(
        truth_lattice.get("one_next_cycle_action")
        or "Truth lattice is coherent; continue with the current launch and champion-lane contract."
    )
    if "wallet_export_candidate_conflict_requires_repair_branch" in broken_reasons:
        one_next_cycle_action = (
            "Reconcile conflicting Polymarket wallet-export candidates before any strategy promotion; "
            "keep the newest export, explain the drift, then rerun `python3 scripts/write_remote_cycle_status.py`."
        )
    elif "launch_contract_confirmation_not_ready_requires_repair_branch" in broken_reasons:
        one_next_cycle_action = (
            "Repair the blocked launch contract and confirmation coverage together before any strategy experiment; "
            "launch/service/submission truth must agree and confirmation must stay machine-readable."
        )
    elif "launch_contract_not_runnable_requires_repair_branch" in broken_reasons:
        one_next_cycle_action = (
            "Repair the blocked launch contract before any strategy experiment; "
            "service state, launch posture, and order-submission state must agree."
        )

    truth_lattice.update(
        {
            "status": "broken" if repair_branch_required else "consistent",
            "repair_branch_required": repair_branch_required,
            "broken_reasons": broken_reasons,
            "selected_values": {
                **dict(truth_lattice.get("selected_values") or {}),
                "launch_posture": launch_posture,
                "service_state": service_state,
                "allow_order_submission": allow_order_submission,
                "confirmation_coverage_label": confirmation_label,
                "wallet_reporting_precedence": wallet_reporting_precedence or None,
                "truth_gate_status": truth_gate_status,
            },
            "observations": {
                **dict(truth_lattice.get("observations") or {}),
                "launch_contract_not_runnable": launch_contract_not_runnable,
                "confirmation_not_decision_ready": confirmation_not_decision_ready,
                "confirmation_blocking_checks": sorted(confirmation_blocking_checks),
                "wallet_export_candidate_conflicts": wallet_export_candidate_conflicts,
            },
            "one_next_cycle_action": one_next_cycle_action,
        }
    )
    strategy["truth_lattice"] = truth_lattice

    if champion_lane_contract and repair_branch_required:
        blocker_classes = dict(champion_lane_contract.get("blocker_classes") or {})
        truth_bucket = dict(blocker_classes.get("truth") or {})
        truth_checks = _dedupe_preserve_order(
            list(truth_bucket.get("checks") or [])
            + list(broken_reasons)
        )
        blocker_classes["truth"] = _blocker_bucket(
            truth_checks,
            retry_cadence_minutes=5,
        )
        required_outputs = dict(champion_lane_contract.get("required_outputs") or {})
        required_outputs["block_reasons"] = _dedupe_preserve_order(
            list(required_outputs.get("block_reasons") or [])
            + list(broken_reasons)
        )
        required_outputs["one_next_cycle_action"] = one_next_cycle_action
        champion_lane_contract["blocker_classes"] = blocker_classes
        champion_lane_contract["required_outputs"] = required_outputs
        champion_lane_contract["status"] = "hold_repair"
        champion_lane_contract["decision_reason"] = (
            "truth_lattice_repair_required_before_champion_lane_can_run"
        )
        strategy["champion_lane_contract"] = champion_lane_contract
        state_improvement["decision_status"] = "hold_repair"

    state_improvement["strategy_recommendations"] = strategy
    state_improvement["truth_precedence"] = truth_precedence
    snapshot["state_improvement"] = state_improvement
    snapshot["truth_precedence"] = truth_precedence
    snapshot["truth_lattice"] = truth_lattice
    snapshot["truth_gate_status"] = truth_gate_status
    snapshot["truth_gate_blocking_checks"] = list(broken_reasons)
    snapshot.update(_derive_btc5_selection_compat_fields(snapshot))

    summary = dict(snapshot.get("summary") or {})
    if repair_branch_required:
        summary["trading_cycle_status"] = "hold_repair"
        summary["one_next_cycle_action"] = one_next_cycle_action
    snapshot["summary"] = summary
    return snapshot


def _apply_shared_truth_contract_to_status(
    payload: dict[str, Any],
    *,
    runtime_truth_snapshot: dict[str, Any],
) -> dict[str, Any]:
    status = dict(payload)
    truth_precedence = dict(runtime_truth_snapshot.get("truth_precedence") or {})
    truth_lattice = dict(runtime_truth_snapshot.get("truth_lattice") or {})
    truth_gate_status = str(runtime_truth_snapshot.get("truth_gate_status") or "consistent")
    truth_gate_blocking_checks = list(runtime_truth_snapshot.get("truth_gate_blocking_checks") or [])
    state_permissions = dict(runtime_truth_snapshot.get("state_permissions") or {})
    operator_verdict = dict(runtime_truth_snapshot.get("operator_verdict") or {})

    status["truth_precedence"] = truth_precedence
    status["truth_lattice"] = truth_lattice
    status["truth_gate_status"] = truth_gate_status
    status["truth_gate_blocking_checks"] = truth_gate_blocking_checks
    status["attribution"] = dict(
        runtime_truth_snapshot.get("attribution") or status.get("attribution") or {}
    )
    status["trade_confirmation"] = dict(
        runtime_truth_snapshot.get("trade_confirmation")
        or status.get("trade_confirmation")
        or {}
    )
    status["trade_proof"] = dict(
        runtime_truth_snapshot.get("trade_proof") or status.get("trade_proof") or {}
    )
    compatibility_fields = _derive_btc5_selection_compat_fields(runtime_truth_snapshot)
    status.update(compatibility_fields)
    status["btc5_stage_readiness"] = dict(
        runtime_truth_snapshot.get("btc5_stage_readiness") or status.get("btc5_stage_readiness") or {}
    )
    status["deployment_confidence"] = dict(
        runtime_truth_snapshot.get("deployment_confidence") or status.get("deployment_confidence") or {}
    )
    for key in (
        "can_btc5_trade_now",
        "btc5_baseline_live_allowed",
        "btc5_stage_upgrade_can_trade_now",
        "launch_state",
        "launch_packet",
    ):
        if key in runtime_truth_snapshot:
            status[key] = runtime_truth_snapshot.get(key)
    status.setdefault("runtime_truth", {}).update(
        {
            "truth_precedence": truth_precedence,
            "truth_lattice": truth_lattice,
            "truth_gate_status": truth_gate_status,
            "truth_gate_blocking_checks": truth_gate_blocking_checks,
            "attribution": dict(status.get("attribution") or {}),
            "trade_confirmation": dict(status.get("trade_confirmation") or {}),
            "trade_proof": dict(status.get("trade_proof") or {}),
            "btc5_stage_readiness": dict(status.get("btc5_stage_readiness") or {}),
            "deployment_confidence": dict(status.get("deployment_confidence") or {}),
            **compatibility_fields,
        }
    )
    if status.get("baseline_live_allowed") is None:
        derived_baseline_live_allowed = state_permissions.get("baseline_live_allowed")
        if derived_baseline_live_allowed is None:
            derived_baseline_live_allowed = operator_verdict.get("baseline_live_allowed")
        if derived_baseline_live_allowed is not None:
            status["baseline_live_allowed"] = bool(derived_baseline_live_allowed)
    if status.get("stage_upgrade_allowed") is None:
        derived_stage_upgrade_allowed = state_permissions.get("stage_upgrade_allowed")
        if derived_stage_upgrade_allowed is None:
            derived_stage_upgrade_allowed = operator_verdict.get("stage_upgrade_allowed")
        if derived_stage_upgrade_allowed is not None:
            status["stage_upgrade_allowed"] = bool(derived_stage_upgrade_allowed)
    if status.get("capital_expansion_allowed") is None:
        derived_capital_expansion_allowed = state_permissions.get("capital_expansion_allowed")
        if derived_capital_expansion_allowed is None:
            derived_capital_expansion_allowed = operator_verdict.get("capital_expansion_allowed")
        if derived_capital_expansion_allowed is not None:
            status["capital_expansion_allowed"] = bool(derived_capital_expansion_allowed)
    if status.get("can_btc5_trade_now") is None:
        stage_readiness = dict(status.get("btc5_stage_readiness") or {})
        can_trade_now = stage_readiness.get("can_trade_now")
        if can_trade_now is None:
            can_trade_now = state_permissions.get("baseline_live_allowed")
        status["can_btc5_trade_now"] = bool(can_trade_now)
    if status.get("btc5_baseline_live_allowed") is None:
        derived_btc5_baseline_live_allowed = status.get("baseline_live_allowed")
        if derived_btc5_baseline_live_allowed is None:
            derived_btc5_baseline_live_allowed = state_permissions.get("baseline_live_allowed")
        if derived_btc5_baseline_live_allowed is None:
            derived_btc5_baseline_live_allowed = operator_verdict.get("baseline_live_allowed")
        status["btc5_baseline_live_allowed"] = bool(derived_btc5_baseline_live_allowed)
    if status.get("btc5_stage_upgrade_can_trade_now") is None:
        stage_readiness = dict(status.get("btc5_stage_readiness") or {})
        stage_upgrade_can_trade_now = stage_readiness.get("stage_upgrade_can_trade_now")
        if stage_upgrade_can_trade_now is None:
            stage_upgrade_can_trade_now = state_permissions.get("stage_upgrade_allowed")
        if stage_upgrade_can_trade_now is None:
            stage_upgrade_can_trade_now = operator_verdict.get("stage_upgrade_allowed")
        status["btc5_stage_upgrade_can_trade_now"] = bool(stage_upgrade_can_trade_now)
    if truth_gate_status == "hold_repair":
        status["status"] = "hold_repair"
        status["one_next_cycle_action"] = truth_lattice.get("one_next_cycle_action")
    return status


def _compute_realized_btc5_sleeve_window(
    *,
    root: Path,
    btc5_maker: dict[str, Any],
    deployed_capital_usd: float | None,
) -> dict[str, Any]:
    def _load_cached_rows(path: Path) -> list[dict[str, Any]]:
        payload = _load_json(path, default=[])
        candidates: list[Any]
        if isinstance(payload, list):
            candidates = payload
        elif isinstance(payload, dict):
            for key in ("rows", "window_trades", "trades", "data"):
                value = payload.get(key)
                if isinstance(value, list):
                    candidates = value
                    break
            else:
                candidates = []
        else:
            candidates = []

        rows = [
            dict(item)
            for item in candidates
            if isinstance(item, dict)
            and str(item.get("order_status") or "").strip().lower() == "live_filled"
        ]
        rows.sort(
            key=lambda row: (
                int(_safe_float(row.get("id"), 0.0)),
                _safe_float(row.get("window_start_ts"), 0.0),
                (_parse_datetime_like(_first_nonempty(row.get("updated_at"), row.get("created_at")))
                 or datetime.fromtimestamp(0, tz=timezone.utc)).timestamp(),
            )
        )
        return rows

    db_path = root / DEFAULT_BTC5_DB_PATH
    rows: list[dict[str, Any]] = []
    if db_path.exists():
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT id, pnl_usd, created_at, updated_at
                FROM window_trades
                WHERE order_status = 'live_filled'
                ORDER BY id ASC
                """
            )
            rows = [dict(row) for row in cursor.fetchall()]

    cached_rows_path = root / DEFAULT_BTC5_WINDOW_ROWS_PATH
    cached_rows = _load_cached_rows(cached_rows_path) if cached_rows_path.exists() else []
    if cached_rows and (not rows or len(cached_rows) > len(rows)):
        rows = cached_rows

    if not rows:
        return {
            "window_pnl_usd": _float_or_none(btc5_maker.get("live_filled_pnl_usd")),
            "window_live_fills": _int_or_none(btc5_maker.get("live_filled_rows")),
            "window_hours": None,
            "run_rate_pct": None,
            "window_mode": "unavailable",
        }

    selected = rows[-12:] if len(rows) >= 12 else rows
    timestamps: list[datetime] = []
    for row in selected:
        parsed = _parse_datetime_like(_first_nonempty(row.get("updated_at"), row.get("created_at")))
        if parsed is not None:
            timestamps.append(parsed)

    elapsed_hours = None
    if timestamps:
        earliest = min(timestamps)
        latest = max(timestamps)
        elapsed_hours = max((latest - earliest).total_seconds() / 3600.0, 5.0 / 60.0)

    window_pnl_usd = round(sum(_safe_float(row.get("pnl_usd"), 0.0) for row in selected), 4)
    window_live_fills = len(selected)

    run_rate_pct = None
    if (
        elapsed_hours is not None
        and elapsed_hours > 0
        and deployed_capital_usd is not None
        and deployed_capital_usd > 0
    ):
        annualization = 24.0 * 365.0 / elapsed_hours
        run_rate_pct = round((window_pnl_usd / deployed_capital_usd) * annualization * 100.0, 4)

    return {
        "window_pnl_usd": window_pnl_usd,
        "window_live_fills": window_live_fills,
        "window_hours": round(elapsed_hours, 4) if elapsed_hours is not None else None,
        "run_rate_pct": run_rate_pct,
        "window_mode": "trailing_12_live_fills" if len(rows) >= 12 else "since_first_live_fill",
    }


def _build_public_performance_scoreboard(
    *,
    root: Path,
    generated_at: datetime,
    capital: dict[str, Any],
    btc5_maker: dict[str, Any],
    polymarket_wallet: dict[str, Any],
    accounting_reconciliation: dict[str, Any],
) -> dict[str, Any]:
    deployed_capital_usd = _float_or_none(capital.get("deployed_capital_usd"))
    if deployed_capital_usd is None or deployed_capital_usd <= 0:
        deployed_capital_usd = _float_or_none(
            _first_nonempty(
                capital.get("polymarket_observed_deployed_usd"),
                capital.get("polymarket_positions_initial_value_usd"),
            )
        )
    realized_window = _compute_realized_btc5_sleeve_window(
        root=root,
        btc5_maker=btc5_maker,
        deployed_capital_usd=deployed_capital_usd,
    )
    btc5_data_at = _parse_datetime_like(
        _first_nonempty(
            btc5_maker.get("latest_live_filled_at"),
            (btc5_maker.get("latest_trade") or {}).get("updated_at")
            if isinstance(btc5_maker.get("latest_trade"), dict)
            else None,
            btc5_maker.get("checked_at"),
        )
    )
    wallet_export_summary = _load_wallet_export_summary(
        root=root,
        generated_at=generated_at,
        btc5_data_at=btc5_data_at,
    )
    btc5_probe_age_hours = _age_hours_from_datetimes(reference_at=generated_at, observed_at=btc5_data_at)
    btc5_probe_freshness_label = _freshness_label_for_age_hours(btc5_probe_age_hours)
    forecast_selection = _select_public_forecast_candidate(root=root, generated_at=generated_at)
    selected = forecast_selection.get("selected") or {}
    considered_forecasts = [
        dict(item)
        for item in list(forecast_selection.get("considered") or [])
        if isinstance(item, dict)
    ]
    forecast_conflict_pool = [
        item for item in considered_forecasts if bool(item.get("fresh"))
    ] or considered_forecasts
    authoritative_forecast_pool = [
        item for item in forecast_conflict_pool if bool(item.get("frontier_authoritative"))
    ]
    deploy_conflict_pool = authoritative_forecast_pool or forecast_conflict_pool
    deploy_recommendation_values = _dedupe_preserve_order(
        [
            str(item.get("deploy_recommendation") or "hold").strip().lower()
            for item in deploy_conflict_pool
            if str(item.get("deploy_recommendation") or "").strip()
        ]
    )
    selected_deploy_recommendation = str(
        selected.get("deploy_recommendation") or "hold"
    ).strip().lower() or "hold"
    deploy_recommendation_conflict = len(deploy_recommendation_values) > 1
    effective_deploy_recommendation = (
        "hold" if deploy_recommendation_conflict else selected_deploy_recommendation
    )
    drift_open = bool(accounting_reconciliation.get("drift_detected"))
    fund_claim_status = "blocked" if drift_open else "unblocked"
    fund_claim_reason = (
        "fund_realized_arr_claim_blocked_until_ledger_wallet_reconciliation_closes"
        if drift_open
        else "fund_realized_arr_claim_unblocked"
    )

    confidence_reasons = list(selected.get("confidence_reasons") or [])
    if not selected:
        confidence_reasons.append("public_forecast_missing")
    elif not selected.get("fresh"):
        confidence_reasons.append("public_forecast_stale_over_6h")
    if deploy_recommendation_conflict:
        confidence_reasons.append("forecast_artifact_deploy_conflict")
    velocity_window_hours = _float_or_none(selected.get("age_hours"))
    velocity_gain_pct = _float_or_none(selected.get("arr_delta_pct"))
    velocity_gain_pct_per_day = None
    if (
        velocity_window_hours is not None
        and velocity_window_hours > 0
        and velocity_gain_pct is not None
    ):
        velocity_gain_pct_per_day = round((velocity_gain_pct / velocity_window_hours) * 24.0, 4)
    intraday_summary = dict(btc5_maker.get("intraday_live_summary") or {})
    closed_batch = dict(polymarket_wallet.get("closed_batch_metrics") or {})
    wallet_reconciliation_summary = {
        "source_class": "polymarket_data_api",
        "source_artifact": "polymarket_wallet_probe",
        "source_age_hours": None,
        "wallet_export_fresh": False,
        "wallet_export_freshness_label": "unknown",
        "reporting_precedence": "btc5_runtime_db",
        "reporting_precedence_reason": "wallet_export_missing",
        "btc_closed_markets": int(_safe_float(closed_batch.get("btc_contracts_resolved"), 0.0) or 0),
        "btc_closed_net_cashflow_usd": round(_safe_float(closed_batch.get("btc_closed_cashflow_usd"), 0.0), 4),
        "btc_open_markets": None,
        "non_btc_open_buy_notional_usd": _float_or_none(closed_batch.get("open_non_btc_notional_usd")),
        "btc5_probe_source_class": btc5_maker.get("source"),
        "btc5_probe_checked_at": btc5_data_at.isoformat() if btc5_data_at is not None else None,
        "btc5_probe_age_hours": round(btc5_probe_age_hours, 4) if btc5_probe_age_hours is not None else None,
        "btc5_probe_freshness_label": btc5_probe_freshness_label,
        "btc5_probe_live_filled_rows": _int_or_none(btc5_maker.get("live_filled_rows")),
        "btc5_probe_live_filled_pnl_usd": _float_or_none(btc5_maker.get("live_filled_pnl_usd")),
    }
    portfolio_equity_delta_1d = None
    closed_cashflow_delta_1d = None
    open_notional_delta_1d = None
    reporting_precedence = "btc5_runtime_db"
    reporting_precedence_reason = "wallet_export_missing"
    if isinstance(wallet_export_summary, dict):
        wallet_export_fresh = bool(wallet_export_summary.get("wallet_export_fresh"))
        wallet_export_fresher_than_btc = bool(wallet_export_summary.get("fresher_than_btc_reporting_source"))
        use_wallet_export_reporting = bool(wallet_export_summary.get("use_wallet_export_reporting"))
        wallet_reconciliation_summary.update(
            {
                "source_class": str(wallet_export_summary.get("source_class") or "wallet_export_csv"),
                "source_artifact": wallet_export_summary.get("source_path"),
                "row_count": int(_safe_float(wallet_export_summary.get("row_count"), 0.0) or 0),
                "market_count": int(_safe_float(wallet_export_summary.get("market_count"), 0.0) or 0),
                "candidate_count": int(_safe_float(wallet_export_summary.get("candidate_count"), 0.0) or 0),
                "candidate_conflict_status": str(
                    wallet_export_summary.get("candidate_conflict_status") or "consistent"
                ),
                "candidate_conflicts": list(wallet_export_summary.get("candidate_conflicts") or []),
                "earliest_timestamp": wallet_export_summary.get("earliest_timestamp"),
                "latest_timestamp": wallet_export_summary.get("latest_timestamp"),
                "source_age_hours": _float_or_none(wallet_export_summary.get("source_age_hours")),
                "wallet_export_fresh": wallet_export_fresh,
                "wallet_export_freshness_label": str(
                    wallet_export_summary.get("wallet_export_freshness_label")
                    or _freshness_label_for_age_hours(_float_or_none(wallet_export_summary.get("source_age_hours")))
                ),
                "buy_usdc": _float_or_none(wallet_export_summary.get("buy_usdc")),
                "redeem_usdc": _float_or_none(wallet_export_summary.get("redeem_usdc")),
                "maker_rebate_usdc": _float_or_none(wallet_export_summary.get("maker_rebate_usdc")),
                "deposit_usdc": _float_or_none(wallet_export_summary.get("deposit_usdc")),
                "net_trading_cash_flow_excluding_deposits_usd": _float_or_none(
                    wallet_export_summary.get("net_trading_cash_flow_excluding_deposits_usd")
                ),
                "net_trading_cash_flow_including_rebates_usd": _float_or_none(
                    wallet_export_summary.get("net_trading_cash_flow_including_rebates_usd")
                ),
                "after_midnight_et_net_trading_cash_flow_usd": _float_or_none(
                    wallet_export_summary.get("after_midnight_et_net_trading_cash_flow_usd")
                ),
                "zero_value_redeems": int(_safe_float(wallet_export_summary.get("zero_value_redeems"), 0.0) or 0),
                "btc_closed_markets": int(_safe_float(wallet_export_summary.get("btc_closed_markets"), 0.0) or 0),
                "btc_closed_net_cashflow_usd": round(
                    _safe_float(wallet_export_summary.get("btc_closed_net_cashflow_usd"), 0.0),
                    4,
                ),
                "btc_open_markets": int(_safe_float(wallet_export_summary.get("btc_open_markets"), 0.0) or 0),
                "non_btc_open_buy_notional_usd": _float_or_none(
                    wallet_export_summary.get("non_btc_open_buy_notional_usd")
                ),
                "top_realized_winners": list(wallet_export_summary.get("top_realized_winners") or []),
                "top_unresolved_exposures": list(wallet_export_summary.get("top_unresolved_exposures") or []),
            }
        )
        portfolio_equity_delta_1d = _float_or_none(wallet_export_summary.get("portfolio_equity_delta_1d"))
        closed_cashflow_delta_1d = _float_or_none(wallet_export_summary.get("closed_cashflow_delta_1d"))
        open_notional_delta_1d = _float_or_none(wallet_export_summary.get("open_notional_delta_1d"))
        if use_wallet_export_reporting:
            reporting_precedence = "wallet_export"
            reporting_precedence_reason = "wallet_export_fresh_and_at_least_as_recent_as_btc5_probe"
            wallet_closed_fills = int(_safe_float(wallet_export_summary.get("btc_closed_markets"), 0.0) or 0)
            wallet_closed_pnl = round(
                _safe_float(wallet_export_summary.get("btc_closed_net_cashflow_usd"), 0.0),
                4,
            )
            wallet_closed_hours = _float_or_none(wallet_export_summary.get("btc_closed_window_hours"))
            if wallet_closed_fills > 0:
                run_rate_pct = None
                if (
                    wallet_closed_hours is not None
                    and wallet_closed_hours > 0
                    and deployed_capital_usd is not None
                    and deployed_capital_usd > 0
                ):
                    annualization = 24.0 * 365.0 / wallet_closed_hours
                    run_rate_pct = round((wallet_closed_pnl / deployed_capital_usd) * annualization * 100.0, 4)
                realized_window = {
                    "window_pnl_usd": wallet_closed_pnl,
                    "window_live_fills": wallet_closed_fills,
                    "window_hours": wallet_closed_hours,
                    "run_rate_pct": run_rate_pct,
                    "window_mode": "wallet_closed_batch",
                }
        elif wallet_export_fresh and not wallet_export_fresher_than_btc:
            reporting_precedence_reason = "btc5_probe_is_fresher_than_wallet_export"
        elif not wallet_export_fresh:
            reporting_precedence_reason = "wallet_export_stale"
        else:
            reporting_precedence_reason = "btc5_probe_retained_as_reporting_source"
    wallet_reconciliation_summary["reporting_precedence"] = reporting_precedence
    wallet_reconciliation_summary["reporting_precedence_reason"] = reporting_precedence_reason
    denominator_initial = _float_or_none(
        _first_nonempty(
            capital.get("polymarket_tracked_capital_usd"),
            capital.get("tracked_capital_usd"),
        )
    )
    denominator_current = _float_or_none(
        _first_nonempty(
            polymarket_wallet.get("total_wallet_value_usd"),
            capital.get("polymarket_observed_total_usd"),
        )
    )
    btc_closed_cashflow = _safe_float(closed_batch.get("btc_closed_cashflow_usd"), 0.0)
    btc_closed_window_hours = _float_or_none(closed_batch.get("btc_closed_window_hours"))
    conservative_closed_net = _safe_float(closed_batch.get("conservative_closed_net_usd"), 0.0)
    all_book_closed_window_hours = _float_or_none(closed_batch.get("all_book_closed_window_hours"))

    def _annualize(pnl_usd: float, denom_usd: float | None, window_hours: float | None) -> float | None:
        if denom_usd is None or denom_usd <= 0 or window_hours is None or window_hours <= 0:
            return None
        annualization = (24.0 * 365.0) / window_hours
        return round((pnl_usd / denom_usd) * annualization * 100.0, 4)

    btc_closed_run_rate_initial = _annualize(btc_closed_cashflow, denominator_initial, btc_closed_window_hours)
    btc_closed_run_rate_current = _annualize(btc_closed_cashflow, denominator_current, btc_closed_window_hours)
    conservative_run_rate_initial = _annualize(conservative_closed_net, denominator_initial, all_book_closed_window_hours)

    return {
        "fund_realized_arr_claim_status": fund_claim_status,
        "fund_realized_arr_claim_reason": fund_claim_reason,
        "realized_btc5_sleeve_run_rate_pct": realized_window.get("run_rate_pct"),
        "realized_btc5_sleeve_window_pnl_usd": realized_window.get("window_pnl_usd"),
        "realized_btc5_sleeve_window_live_fills": realized_window.get("window_live_fills"),
        "realized_btc5_sleeve_window_hours": realized_window.get("window_hours"),
        "realized_btc5_sleeve_window_mode": realized_window.get("window_mode"),
        "forecast_active_arr_pct": _float_or_none(selected.get("active_arr_pct")),
        "forecast_best_arr_pct": _float_or_none(selected.get("best_arr_pct")),
        "forecast_arr_delta_pct": _float_or_none(selected.get("arr_delta_pct")),
        "forecast_confidence_label": str(selected.get("confidence_label") or "low"),
        "forecast_confidence_reasons": confidence_reasons,
        "selected_deploy_recommendation": selected_deploy_recommendation,
        "deploy_recommendation": effective_deploy_recommendation,
        "deploy_recommendation_conflict": deploy_recommendation_conflict,
        "deploy_recommendation_conflict_values": deploy_recommendation_values,
        "forecast_selection_reason": forecast_selection.get("selection_reason"),
        "forecast_considered_artifacts": [
            {
                "path": item.get("path"),
                "fresh": bool(item.get("fresh")),
                "age_hours": (
                    round(float(item["age_hours"]), 4)
                    if item.get("age_hours") is not None
                    else None
                ),
                "deploy_recommendation": str(
                    item.get("deploy_recommendation") or "hold"
                ).strip().lower(),
                "confidence_label": str(item.get("confidence_label") or "low"),
            }
            for item in considered_forecasts
        ],
        "timebound_velocity_window_hours": round(velocity_window_hours, 4) if velocity_window_hours is not None else None,
        "timebound_velocity_forecast_gain_pct": velocity_gain_pct,
        "timebound_velocity_forecast_gain_pct_per_day": velocity_gain_pct_per_day,
        "public_forecast_source_artifact": selected.get("path"),
        "realized_closed_btc_cashflow_usd": _float_or_none(
            wallet_reconciliation_summary.get("btc_closed_net_cashflow_usd")
        ),
        "open_non_btc_notional_usd": _float_or_none(
            wallet_reconciliation_summary.get("non_btc_open_buy_notional_usd")
        ),
        "forecast_arr_pct": _float_or_none(selected.get("active_arr_pct")),
        "wallet_reconciliation_summary": wallet_reconciliation_summary,
        "portfolio_equity_delta_1d": portfolio_equity_delta_1d,
        "closed_cashflow_delta_1d": closed_cashflow_delta_1d,
        "open_notional_delta_1d": open_notional_delta_1d,
        "intraday_live_summary": intraday_summary,
        "wallet_closed_batch": {
            "btc_closed_cashflow_usd": round(btc_closed_cashflow, 4),
            "btc_contracts_resolved": int(_safe_float(closed_batch.get("btc_contracts_resolved"), 0.0) or 0),
            "btc_wins": int(_safe_float(closed_batch.get("btc_wins"), 0.0) or 0),
            "btc_losses": int(_safe_float(closed_batch.get("btc_losses"), 0.0) or 0),
            "btc_profit_factor": _float_or_none(closed_batch.get("btc_profit_factor")),
            "btc_average_win_usd": _float_or_none(closed_batch.get("btc_average_win_usd")),
            "btc_average_loss_usd": _float_or_none(closed_batch.get("btc_average_loss_usd")),
            "btc_closed_window_hours": btc_closed_window_hours,
            "btc_closed_run_rate_pct_initial_capital": btc_closed_run_rate_initial,
            "btc_closed_run_rate_pct_current_portfolio": btc_closed_run_rate_current,
            "all_book_closed_cashflow_usd": _float_or_none(closed_batch.get("all_book_closed_cashflow_usd")),
            "open_non_btc_notional_usd": _float_or_none(closed_batch.get("open_non_btc_notional_usd")),
            "conservative_closed_net_usd": round(conservative_closed_net, 4),
            "conservative_all_book_run_rate_pct_initial_capital": conservative_run_rate_initial,
            "all_book_closed_window_hours": all_book_closed_window_hours,
            "interpretation": "short_window_sleeve_run_rate_directional_not_fund_realized_claim",
        },
    }


def _load_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    return _load_jsonl_rows_io(path)


def _artifact_age_hours(root: Path, relative_path: str, *, now: datetime) -> float | None:
    path = root / relative_path
    if not path.exists():
        return None
    payload = _load_json(path, default={})
    ts = None
    if isinstance(payload, dict):
        ts = _parse_datetime_like(
            _first_nonempty(
                payload.get("generated_at"),
                payload.get("report_generated_at"),
                payload.get("checked_at"),
            )
        )
    if ts is None:
        ts = _parse_datetime_like(_safe_iso_mtime(path))
    if ts is None:
        return None
    return max(0.0, (now - ts).total_seconds() / 3600.0)


def _btc5_trailing_fill_window(root: Path, *, fills: int = 12) -> dict[str, Any]:
    db_path = root / DEFAULT_BTC5_DB_PATH
    if not db_path.exists():
        return {"fills": 0, "pnl_usd": 0.0}
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT pnl_usd
            FROM window_trades
            WHERE order_status = 'live_filled'
            ORDER BY id DESC
            LIMIT ?
            """,
            (max(1, int(fills)),),
        ).fetchall()
    pnl = round(sum(_safe_float(row["pnl_usd"], 0.0) for row in rows), 4)
    return {"fills": len(rows), "pnl_usd": pnl}


def _kalshi_settlement_summary(root: Path) -> dict[str, Any]:
    settlements_path = root / "data" / "kalshi_weather_settlements.jsonl"
    rows = _load_jsonl_rows(settlements_path)
    matched = 0
    total = 0
    for row in rows:
        total += 1
        is_matched = _first_nonempty(
            row.get("matched"),
            row.get("decision_matched"),
            row.get("match"),
            row.get("settlement_matched"),
        )
        if isinstance(is_matched, bool):
            matched += 1 if is_matched else 0
            continue
        status_text = str(
            _first_nonempty(row.get("match_status"), row.get("reconciliation_status"), row.get("status")) or ""
        ).strip().lower()
        if status_text in {"matched", "match"}:
            matched += 1
    rate = (matched / total) if total > 0 else 0.0
    return {
        "path": "data/kalshi_weather_settlements.jsonl",
        "exists": settlements_path.exists(),
        "total_rows": total,
        "matched_rows": matched,
        "match_rate": round(rate, 4),
    }


def _build_capital_addition_readiness(
    *,
    root: Path,
    generated_at: datetime,
    launch: dict[str, Any],
    accounting_reconciliation: dict[str, Any],
) -> dict[str, Any]:
    blocked_checks = list(launch.get("blocked_checks") or [])
    fund_blocking_checks = []
    if bool(accounting_reconciliation.get("drift_detected")):
        fund_blocking_checks.append("accounting_reconciliation_drift")
    if "polymarket_capital_truth_drift" in blocked_checks:
        fund_blocking_checks.append("polymarket_capital_truth_drift")
    fund_blocking_checks = _dedupe_preserve_order(fund_blocking_checks)
    fund_blocked = bool(fund_blocking_checks)

    forecast = _select_public_forecast_candidate(root=root, generated_at=generated_at).get("selected") or {}
    forecast_is_promote_high = (
        str(forecast.get("deploy_recommendation") or "").strip().lower() == "promote"
        and str(forecast.get("confidence_label") or "").strip().lower() == "high"
        and bool(forecast.get("fresh"))
    )
    trailing_12 = _btc5_trailing_fill_window(root, fills=12)
    trailing_12_positive = trailing_12.get("fills", 0) >= 12 and _safe_float(trailing_12.get("pnl_usd"), 0.0) > 0.0
    scale_summary = _load_strategy_scale_comparison_summary(root=root, generated_at=generated_at)
    audit_summary = _load_signal_source_audit_summary(root=root, generated_at=generated_at)
    audit_stage_status = str(audit_summary.get("stage_upgrade_support_status") or "").strip().lower()
    wallet_flow_confirmation_ready = audit_summary.get("wallet_flow_confirmation_ready")
    supports_capital_allocation = audit_summary.get("supports_capital_allocation")
    scale_artifact_ready = (
        bool(scale_summary.get("exists"))
        and str(scale_summary.get("freshness") or "").strip().lower() != "stale"
    )
    audit_artifact_ready = (
        bool(audit_summary.get("exists"))
        and str(audit_summary.get("freshness") or "").strip().lower() != "stale"
    )
    upgrade_support_ready = (
        scale_artifact_ready
        and audit_artifact_ready
        and audit_stage_status in {"ready", "supported", "strong"}
        and wallet_flow_confirmation_ready is True
        and supports_capital_allocation is not False
    )

    polymarket_status = "hold"
    polymarket_amount = 0
    polymarket_reasons = []
    polymarket_blocking_checks = []
    if forecast_is_promote_high and trailing_12_positive:
        if fund_blocked:
            polymarket_status = "ready_test_tranche"
            polymarket_amount = 100
            polymarket_reasons.append("btc5_promote_high_fresh_and_trailing12_positive_but_fund_reconciliation_blocked")
            polymarket_blocking_checks.extend(fund_blocking_checks)
        elif not upgrade_support_ready:
            polymarket_status = "ready_test_tranche"
            polymarket_amount = 100
            polymarket_reasons.append(
                "btc5_promote_high_fresh_and_trailing12_positive_but_stage_upgrade_support_is_limited"
            )
            if not scale_artifact_ready:
                polymarket_blocking_checks.append("strategy_scale_comparison_stale_or_missing")
            if not audit_artifact_ready:
                polymarket_blocking_checks.append("signal_source_audit_stale_or_missing")
            if audit_stage_status and audit_stage_status not in {"ready", "supported", "strong"}:
                polymarket_blocking_checks.append("signal_source_audit_limits_stage_upgrade")
            if wallet_flow_confirmation_ready is False:
                polymarket_blocking_checks.append("wallet_flow_confirmation_missing_for_runtime_capital_upgrade")
            if supports_capital_allocation is False:
                polymarket_blocking_checks.append("signal_source_audit_does_not_support_capital_allocation")
        else:
            polymarket_status = "ready_scale"
            polymarket_amount = 1000
            polymarket_reasons.append("btc5_promote_high_fresh_and_trailing12_positive")
    else:
        polymarket_blocking_checks.extend(
            check
            for check, condition in (
                ("btc5_forecast_not_promote_high_fresh", not forecast_is_promote_high),
                ("btc5_trailing12_not_net_positive", not trailing_12_positive),
            )
            if condition
        )
        polymarket_reasons.append("btc5_capital_addition_conditions_not_met")

    strategy_age = _artifact_age_hours(root, "reports/strategy_scale_comparison.json", now=generated_at)
    audit_age = _artifact_age_hours(root, "reports/signal_source_audit.json", now=generated_at)
    strategy_stale = strategy_age is None or strategy_age > BTC5_RESEARCH_STALE_HOURS
    audit_stale = audit_age is None or audit_age > BTC5_RESEARCH_STALE_HOURS
    settlements = _kalshi_settlement_summary(root)
    kalshi_blocking_checks = []
    if not settlements.get("exists"):
        kalshi_blocking_checks.append("kalshi_settlement_log_missing")
    if _safe_float(settlements.get("match_rate"), 0.0) <= 0.0:
        kalshi_blocking_checks.append("kalshi_settlement_match_rate_zero")
    if strategy_stale or audit_stale:
        kalshi_blocking_checks.append("venue_ranking_artifacts_stale")
    kalshi_blocking_checks = _dedupe_preserve_order(kalshi_blocking_checks)

    fund_ready_for_scale = (not fund_blocked) and polymarket_status == "ready_scale"
    fund_status = "ready_scale" if fund_ready_for_scale else "hold"
    fund_amount = 1000 if fund_ready_for_scale else 0
    fund_confidence = "medium" if fund_ready_for_scale else "low"

    kalshi_status = "hold" if kalshi_blocking_checks else "ready_test_tranche"
    kalshi_amount = 0 if kalshi_status == "hold" else 100

    next_1000_status = "ready_scale" if fund_ready_for_scale else "hold"
    next_1000_amount = 1000 if next_1000_status == "ready_scale" else 0

    return {
        "fund": {
            "status": fund_status,
            "recommended_amount_usd": fund_amount,
            "confidence_label": fund_confidence,
            "reasons": (
                ["fund_capital_truth_reconciled"] if not fund_blocked else ["fund_capital_truth_not_reconciled"]
            ),
            "blocking_checks": fund_blocking_checks,
            "source_artifacts": ["reports/runtime_truth_latest.json", "reports/public_runtime_snapshot.json"],
        },
        "polymarket_btc5": {
            "status": polymarket_status,
            "recommended_amount_usd": polymarket_amount,
            "confidence_label": "high" if polymarket_status != "hold" else "medium",
            "reasons": polymarket_reasons,
            "blocking_checks": _dedupe_preserve_order(polymarket_blocking_checks),
            "source_artifacts": _dedupe_preserve_order(
                [
                    str(forecast.get("path") or "reports/btc5_autoresearch/latest.json"),
                    "data/btc_5min_maker.db",
                    "reports/public_runtime_snapshot.json",
                ]
            ),
        },
        "kalshi_weather": {
            "status": kalshi_status,
            "recommended_amount_usd": kalshi_amount,
            "confidence_label": "low" if kalshi_status == "hold" else "medium",
            "reasons": (
                ["kalshi_weather_capital_blocked_until_settlement_and_fresh_ranking"]
                if kalshi_status == "hold"
                else ["kalshi_weather_meets_test_tranche_readiness"]
            ),
            "blocking_checks": kalshi_blocking_checks,
            "source_artifacts": _dedupe_preserve_order(
                [
                    settlements["path"],
                    "reports/strategy_scale_comparison.json",
                    "reports/signal_source_audit.json",
                ]
            ),
        },
        "next_1000_usd": {
            "status": next_1000_status,
            "recommended_amount_usd": next_1000_amount,
            "confidence_label": "low" if next_1000_status == "hold" else "medium",
            "reasons": (
                ["full_1000_add_blocked_until_fund_capital_truth_reconciles"]
                if next_1000_status == "hold"
                else ["fund_reconciled_and_ready_for_scale_add"]
            ),
            "blocking_checks": fund_blocking_checks if next_1000_status == "hold" else [],
            "source_artifacts": ["reports/runtime_truth_latest.json", "reports/public_runtime_snapshot.json"],
        },
    }


def _build_finance_gate_status(*, root: Path) -> dict[str, Any]:
    return _build_finance_gate_status_impl(root=root)


def _build_five_metric_scorecard(
    *,
    generated_at: datetime,
    candidate_total: int | None,
    executed_notional_hourly_usd: float | None,
    candidate_to_trade_conversion: float | None,
    conversion_reason: str | None,
    recent_resolved_pnl_usd: float | None,
    recent_resolved_pnl_reason: str | None,
    finance_gate_status: dict[str, Any],
    confirmation_summary: dict[str, Any],
) -> dict[str, Any]:
    metrics = {
        "candidate_count": candidate_total,
        "executed_notional_usd": executed_notional_hourly_usd,
        "candidate_to_trade_conversion": candidate_to_trade_conversion,
        "recent_resolved_pnl_usd": recent_resolved_pnl_usd,
        "finance_gate_status": finance_gate_status.get("status_label"),
    }

    attribution = {
        "candidate_count": {
            "status": "updated" if candidate_total is not None else "defect",
            "reason": None if candidate_total is not None else "candidate_count_missing",
            "value_source": "state_improvement.per_venue_candidate_counts.total",
        },
        "executed_notional_usd": {
            "status": "updated" if executed_notional_hourly_usd is not None else "defect",
            "reason": None if executed_notional_hourly_usd is not None else "execution_notional_missing",
            "value_source": "state_improvement.per_venue_executed_notional_usd.combined_hourly",
        },
        "candidate_to_trade_conversion": {
            "status": "updated" if candidate_to_trade_conversion is not None else "defect",
            "reason": conversion_reason if candidate_to_trade_conversion is None else None,
            "value_source": "state_improvement.execution_summary.per_venue_trade_counts.combined_hourly / candidate_count",
        },
        "recent_resolved_pnl_usd": {
            "status": "updated" if recent_resolved_pnl_usd is not None else "defect",
            "reason": recent_resolved_pnl_reason if recent_resolved_pnl_usd is None else None,
            "value_source": "state_improvement.strategy_recommendations.closed_cashflow_delta_1d",
        },
        "finance_gate_status": {
            "status": "updated" if finance_gate_status.get("status_label") else "defect",
            "reason": None if finance_gate_status.get("status_label") else "finance_gate_status_unknown",
            "value_source": ",".join(finance_gate_status.get("source_artifacts") or []),
        },
    }
    unresolved = sorted(
        metric_name
        for metric_name, info in attribution.items()
        if str(info.get("status") or "").strip().lower() != "updated"
    )
    return {
        "artifact": "cycle_five_metric_scorecard",
        "schema_version": 1,
        "generated_at": generated_at.isoformat(),
        "metrics": metrics,
        "attribution": attribution,
        "unresolved_metrics": unresolved,
        "all_metrics_attributed": not unresolved,
        "confirmation_readiness": {
            "status": confirmation_summary.get("confirmation_support_status"),
            "coverage_label": confirmation_summary.get("confirmation_coverage_label"),
            "strength_label": confirmation_summary.get("confirmation_strength_label"),
            "source_ready_count": len(list(confirmation_summary.get("confirmation_sources_ready") or [])),
            "blocking_checks_count": len(list(confirmation_summary.get("stage_upgrade_blocking_checks") or [])),
        },
        "finance_gate": {
            "status": finance_gate_status.get("status"),
            "block_reasons": list(finance_gate_status.get("block_reasons") or []),
            "source_artifacts": list(finance_gate_status.get("source_artifacts") or []),
        },
    }


def _build_state_improvement_report(
    *,
    root: Path,
    generated_at: datetime,
    runtime: dict[str, Any],
    capital: dict[str, Any],
    btc5_maker: dict[str, Any],
    polymarket_wallet: dict[str, Any],
    accounting_reconciliation: dict[str, Any],
    launch: dict[str, Any],
    latest_edge_scan: dict[str, Any],
    latest_pipeline: dict[str, Any],
    previous_runtime_truth_snapshot: dict[str, Any],
) -> dict[str, Any]:
    profile = _load_json(root / DEFAULT_RUNTIME_PROFILE_EFFECTIVE_PATH, default={})
    if not profile:
        profile = _load_json(root / LEGACY_RUNTIME_PROFILE_EFFECTIVE_PATH, default={})
    execution_summary = _compute_execution_notional_summary(root=root, now=generated_at, btc5_maker=btc5_maker)
    fast_market_search = _summarize_fast_market_search(
        root,
        root / DEFAULT_FAST_MARKET_SEARCH_LATEST_PATH,
    )
    per_venue_candidate_counts = dict(
        latest_edge_scan.get("per_venue_candidate_counts")
        or {"polymarket": 0, "kalshi": 0, "total": 0}
    )
    fast_market_candidate_count = int(fast_market_search.get("btc5_candidate_count") or 0)
    if int(per_venue_candidate_counts.get("polymarket") or 0) <= 0 and fast_market_candidate_count > 0:
        per_venue_candidate_counts["polymarket"] = fast_market_candidate_count
    per_venue_candidate_counts["total"] = int(per_venue_candidate_counts.get("polymarket") or 0) + int(
        per_venue_candidate_counts.get("kalshi") or 0
    )

    risk_limits = profile.get("risk_limits") if isinstance(profile, dict) else {}
    hourly_budget_cap = _first_nonempty(
        (risk_limits or {}).get("hourly_notional_budget_usd"),
        (risk_limits or {}).get("max_hourly_notional_usd"),
        (risk_limits or {}).get("campaign_hourly_notional_usd"),
        (risk_limits or {}).get("hourly_campaign_notional_usd"),
    )
    hourly_budget_cap_value = _float_or_none(hourly_budget_cap)
    hourly_notional_used = float(execution_summary.get("hourly_notional_usd") or 0.0)
    hourly_budget_progress_pct = (
        (hourly_notional_used / hourly_budget_cap_value) * 100.0
        if hourly_budget_cap_value and hourly_budget_cap_value > 0
        else None
    )

    active_thresholds = {
        "profile_name": profile.get("profile_name"),
        "yes_threshold": _float_or_none((profile.get("signal_thresholds") or {}).get("yes_threshold")),
        "no_threshold": _float_or_none((profile.get("signal_thresholds") or {}).get("no_threshold")),
        "max_resolution_hours": _float_or_none((profile.get("market_filters") or {}).get("max_resolution_hours")),
        "max_position_usd": _float_or_none((risk_limits or {}).get("max_position_usd")),
    }

    candidate_total = int(per_venue_candidate_counts.get("total") or 0)
    hourly_trade_count = int((execution_summary.get("per_venue_trade_counts") or {}).get("combined_hourly") or 0)
    conversion_rate: float | None = None
    conversion_defect_reason: str | None = None
    if candidate_total > 0:
        conversion_rate = round(hourly_trade_count / candidate_total, 6)
    else:
        conversion_defect_reason = (
            "candidate_count_zero_with_nonzero_hourly_trade_count"
            if hourly_trade_count > 0
            else "candidate_count_zero_with_zero_hourly_trade_count"
        )

    expected_pnl_usd = _estimate_expected_pnl_from_edge_scan(root, latest_edge_scan)
    realized_pnl_usd = _float_or_none(runtime.get("daily_pnl_usd"))
    pnl_drift_usd = (
        (realized_pnl_usd - expected_pnl_usd)
        if realized_pnl_usd is not None and expected_pnl_usd is not None
        else None
    )

    current_tradeable = int(latest_pipeline.get("current_tradeable") or 0)
    current_reachability = max(
        int(latest_pipeline.get("current_yes_reachable_markets") or 0),
        int(latest_pipeline.get("current_no_reachable_markets") or 0),
        current_tradeable,
    )

    previous_state_improvement = (
        previous_runtime_truth_snapshot.get("state_improvement")
        if isinstance(previous_runtime_truth_snapshot, dict)
        else {}
    ) or {}
    previous_metrics = previous_state_improvement.get("metrics") or {}

    current_metrics = {
        "edge_reachability": float(current_reachability),
        "candidate_to_trade_conversion": conversion_rate,
        "candidate_to_trade_conversion_reason": conversion_defect_reason,
        "realized_pnl_usd": realized_pnl_usd,
        "expected_pnl_usd": expected_pnl_usd,
        "realized_expected_pnl_drift_usd": pnl_drift_usd,
    }

    deltas = {
        "edge_reachability_delta": _delta_or_none(
            current_metrics["edge_reachability"],
            _float_or_none(previous_metrics.get("edge_reachability")),
        ),
        "candidate_to_trade_conversion_delta": _delta_or_none(
            current_metrics["candidate_to_trade_conversion"],
            _float_or_none(previous_metrics.get("candidate_to_trade_conversion")),
        ),
        "realized_expected_pnl_drift_delta_usd": _delta_or_none(
            current_metrics["realized_expected_pnl_drift_usd"],
            _float_or_none(previous_metrics.get("realized_expected_pnl_drift_usd")),
        ),
    }

    reject_reasons = _dedupe_preserve_order(
        [
            *list(launch.get("blocked_checks") or []),
            *list(launch.get("blocked_reasons") or []),
            *list((latest_edge_scan.get("candidate_reject_reason_counts") or {}).keys()),
            str(latest_edge_scan.get("action_reason") or "").strip(),
            str(latest_pipeline.get("reasoning") or "").strip(),
        ]
    )
    reject_reasons = [reason for reason in reject_reasons if reason]
    if fast_market_candidate_count > 0:
        reject_reasons = [
            reason
            for reason in reject_reasons
            if reason
            != "Zero viable markets even at wide-open thresholds (YES=0.05, NO=0.02); Platt parameters may be stale."
        ]
        reject_reasons = _dedupe_preserve_order(
            reject_reasons
            + list(fast_market_search.get("top_blocking_checks") or [])
            + list(fast_market_search.get("primary_blockers") or [])
        )

    hourly_budget_progress = {
        "cap_usd": hourly_budget_cap_value,
        "used_usd": round(hourly_notional_used, 4),
        "remaining_usd": (
            round(max(hourly_budget_cap_value - hourly_notional_used, 0.0), 4)
            if hourly_budget_cap_value is not None
            else None
        ),
        "progress_pct": round(hourly_budget_progress_pct, 4) if hourly_budget_progress_pct is not None else None,
        "window_minutes": 60,
    }

    btc5_research_recommendation = _build_btc5_research_recommendation(
        root=root,
        generated_at=generated_at,
        btc5_maker=btc5_maker,
    )
    public_performance_scoreboard = _build_public_performance_scoreboard(
        root=root,
        generated_at=generated_at,
        capital=capital,
        btc5_maker=btc5_maker,
        polymarket_wallet=polymarket_wallet,
        accounting_reconciliation=accounting_reconciliation,
    )
    wallet_reconciliation_summary = dict(public_performance_scoreboard.get("wallet_reconciliation_summary") or {})
    capital_addition_readiness = _build_capital_addition_readiness(
        root=root,
        generated_at=generated_at,
        launch=launch,
        accounting_reconciliation=accounting_reconciliation,
    )
    public_performance_scoreboard["capital_stage_readiness"] = str(
        ((capital_addition_readiness.get("polymarket_btc5") or {}).get("status") or "hold")
    )
    public_performance_scoreboard["next_1000_usd_status"] = str(
        ((capital_addition_readiness.get("next_1000_usd") or {}).get("status") or "hold")
    )
    public_performance_scoreboard["next_1000_usd_recommended_amount_usd"] = _float_or_none(
        ((capital_addition_readiness.get("next_1000_usd") or {}).get("recommended_amount_usd"))
    )
    public_performance_scoreboard["performance_split"] = {
        "realized_closed_btc_cashflow_usd": _float_or_none(
            public_performance_scoreboard.get("realized_closed_btc_cashflow_usd")
        ),
        "open_non_btc_notional_usd": _float_or_none(
            public_performance_scoreboard.get("open_non_btc_notional_usd")
        ),
        "forecast_arr_pct": _float_or_none(public_performance_scoreboard.get("forecast_arr_pct")),
        "capital_stage_readiness": public_performance_scoreboard.get("capital_stage_readiness"),
        "deploy_recommendation": public_performance_scoreboard.get("deploy_recommendation"),
    }
    truth_lattice = _build_truth_lattice(
        runtime=runtime,
        launch=launch,
        public_performance_scoreboard=public_performance_scoreboard,
        wallet_reconciliation_summary=wallet_reconciliation_summary,
    )
    recent_resolved_pnl_usd = _float_or_none(public_performance_scoreboard.get("closed_cashflow_delta_1d"))
    recent_resolved_pnl_reason: str | None = None
    if recent_resolved_pnl_usd is None:
        recent_resolved_pnl_reason = "closed_cashflow_delta_1d_missing"
    finance_gate_status = _build_finance_gate_status(root=root)
    confirmation_summary = _load_signal_source_audit_summary(root=root, generated_at=generated_at)
    five_metric_scorecard = _build_five_metric_scorecard(
        generated_at=generated_at,
        candidate_total=candidate_total,
        executed_notional_hourly_usd=_float_or_none(
            (execution_summary.get("per_venue_notional_usd") or {}).get("combined_hourly")
        ),
        candidate_to_trade_conversion=conversion_rate,
        conversion_reason=conversion_defect_reason,
        recent_resolved_pnl_usd=recent_resolved_pnl_usd,
        recent_resolved_pnl_reason=recent_resolved_pnl_reason,
        finance_gate_status=finance_gate_status,
        confirmation_summary=confirmation_summary,
    )

    report = {
        "artifact": "state_improvement_report",
        "schema_version": 1,
        "generated_at": generated_at.isoformat(),
        "hourly_budget_progress": hourly_budget_progress,
        "active_thresholds": active_thresholds,
        "per_venue_candidate_counts": per_venue_candidate_counts,
        "per_venue_executed_notional_usd": dict(execution_summary.get("per_venue_notional_usd") or {}),
        "per_venue_trade_counts": dict(execution_summary.get("per_venue_trade_counts") or {}),
        "reject_reasons": reject_reasons,
        "improvement_velocity": {
            "deltas": deltas,
            "previous_snapshot_generated_at": previous_runtime_truth_snapshot.get("generated_at")
            if isinstance(previous_runtime_truth_snapshot, dict)
            else None,
        },
        "strategy_recommendations": {
            "btc5_guardrails": btc5_maker.get("guardrail_recommendation"),
            "btc5_edge_profile": btc5_research_recommendation.get("btc5_edge_profile") or {},
            "btc5_forecast_confidence": btc5_research_recommendation.get("btc5_forecast_confidence") or {},
            "btc5_candidate_recovery": fast_market_search,
            "public_performance_scoreboard": public_performance_scoreboard,
            "performance_split": public_performance_scoreboard.get("performance_split") or {},
            "wallet_reconciliation_summary": public_performance_scoreboard.get("wallet_reconciliation_summary") or {},
            "portfolio_equity_delta_1d": _float_or_none(public_performance_scoreboard.get("portfolio_equity_delta_1d")),
            "closed_cashflow_delta_1d": _float_or_none(public_performance_scoreboard.get("closed_cashflow_delta_1d")),
            "open_notional_delta_1d": _float_or_none(public_performance_scoreboard.get("open_notional_delta_1d")),
            "capital_addition_readiness": capital_addition_readiness,
            "truth_lattice": truth_lattice,
        },
        "reconciliation_summary": {
            "drift_detected": bool(accounting_reconciliation.get("drift_detected")),
            "unmatched_open_positions": (
                accounting_reconciliation.get("unmatched_open_positions") or {}
            ),
            "unmatched_closed_positions": (
                accounting_reconciliation.get("unmatched_closed_positions") or {}
            ),
            "capital_accounting_delta_usd": _float_or_none(
                accounting_reconciliation.get("capital_accounting_delta_usd")
            ),
        },
        "five_metric_scorecard": five_metric_scorecard,
        "metrics": current_metrics,
    }
    report["operator_digest"] = _build_operator_digest(report, launch=launch)
    return report


def _estimate_expected_pnl_from_edge_scan(root: Path, latest_edge_scan: dict[str, Any]) -> float | None:
    path_text = latest_edge_scan.get("path")
    if not path_text:
        return None
    path = root / str(path_text)
    payload = _load_json(path, default={})
    candidates = payload.get("candidate_markets")
    if not isinstance(candidates, list):
        return None
    expected = 0.0
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        edge = _float_or_none(candidate.get("edge"))
        size = _float_or_none(candidate.get("recommended_size_usd"))
        if edge is None or size is None:
            continue
        expected += edge * size
    return round(expected, 6)


def _summarize_recent_btc5_execution(*, btc5_maker: dict[str, Any], now: datetime) -> dict[str, Any]:
    recent_rows = list(btc5_maker.get("recent_live_filled") or [])
    if not recent_rows:
        latest_trade = btc5_maker.get("latest_trade")
        if isinstance(latest_trade, dict):
            recent_rows = [latest_trade]

    one_hour_ago = now.timestamp() - 3600.0
    hourly_notional = 0.0
    hourly_trade_count = 0
    for row in recent_rows:
        if not isinstance(row, dict):
            continue
        trade_size = abs(_float_or_none(row.get("trade_size_usd")) or 0.0)
        if trade_size <= 0:
            continue
        parsed_ts = _parse_trade_timestamp(
            row.get("updated_at") or row.get("created_at") or row.get("decision_ts") or row.get("window_start_ts")
        )
        if parsed_ts is None or parsed_ts < one_hour_ago:
            continue
        hourly_notional += trade_size
        hourly_trade_count += 1

    return {
        "hourly_notional_usd": round(hourly_notional, 6),
        "hourly_trade_count": int(hourly_trade_count),
        "source": str(btc5_maker.get("source") or btc5_maker.get("db_path") or "btc5_recent_live_filled"),
    }


def _selected_btc5_profile_id(selected_package_summary: dict[str, Any]) -> str | None:
    return (
        str(
            selected_package_summary.get("canonical_live_profile")
            or selected_package_summary.get("canonical_live_profile_id")
            or selected_package_summary.get("selected_active_profile_name")
            or selected_package_summary.get("selected_best_profile_name")
            or ""
        ).strip()
        or None
    )


def _load_latest_btc5_fill_from_trade_ledger(root: Path) -> dict[str, Any]:
    db_path = root / DEFAULT_TRADES_DB_PATH
    if not db_path.exists():
        return {}

    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT
                f.id,
                f.timestamp,
                f.market_id,
                f.order_id,
                f.trade_id,
                f.fill_price,
                f.fill_size_usd,
                f.raw_json,
                o.metadata_json,
                o.direction AS order_direction,
                t.direction AS trade_direction,
                t.entry_price,
                t.source,
                t.source_combo
            FROM fills AS f
            LEFT JOIN orders AS o
                ON o.order_id = f.order_id
            LEFT JOIN trades AS t
                ON t.id = COALESCE(f.trade_id, o.trade_id)
            WHERE
                COALESCE(t.source, '') = 'polymarket_btc5_remote_mirror'
                OR COALESCE(t.source_combo, '') = 'polymarket_btc5_remote_mirror'
                OR f.market_id LIKE 'btc-updown-5m-%'
                OR f.order_id LIKE 'btc5-mirror-order-%'
            ORDER BY f.timestamp DESC, f.id DESC
            LIMIT 1
            """
        ).fetchone()
    except sqlite3.DatabaseError:
        return {}
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass

    if row is None:
        return {}
    return dict(row)


def build_trade_attribution_contract(
    *,
    root: Path,
    btc5_maker: dict[str, Any],
    selected_package_summary: dict[str, Any] | None = None,
    service_name: str | None = None,
) -> dict[str, Any]:
    selected_package = (
        dict(selected_package_summary or {})
        if isinstance(selected_package_summary, dict)
        else {}
    )
    if not selected_package:
        selected_package = _load_btc5_selected_package_summary(root)

    latest_trade = (
        dict(btc5_maker.get("latest_trade") or {})
        if isinstance(btc5_maker.get("latest_trade"), dict)
        else {}
    )
    latest_trade_status = str(latest_trade.get("order_status") or "").strip().lower()
    latest_fill = _load_latest_btc5_fill_from_trade_ledger(root)
    raw_fill_payload = fast_loads(latest_fill.get("raw_json") or "{}") if latest_fill.get("raw_json") else {}
    fill_metadata = (
        fast_loads(latest_fill.get("metadata_json") or "{}")
        if latest_fill.get("metadata_json")
        else {}
    )
    lane_id = (
        str(
            fill_metadata.get("lane_id")
            or raw_fill_payload.get("lane_id")
            or "maker_bootstrap_live"
        ).strip()
        or "maker_bootstrap_live"
    )
    strategy_family = (
        str(
            fill_metadata.get("strategy_family")
            or raw_fill_payload.get("strategy_family")
            or "btc5_maker_bootstrap"
        ).strip()
        or "btc5_maker_bootstrap"
    )
    profile_id = _selected_btc5_profile_id(selected_package)
    latest_filled_trade_at = (
        str(
            latest_fill.get("timestamp")
            or btc5_maker.get("latest_live_filled_at")
            or (
                latest_trade.get("updated_at")
                if latest_trade_status == "live_filled"
                else None
            )
            or (
                latest_trade.get("created_at")
                if latest_trade_status == "live_filled"
                else None
            )
            or ""
        ).strip()
        or None
    )
    trade_size_usd = _float_or_none(
        _first_nonempty(
            latest_fill.get("fill_size_usd"),
            raw_fill_payload.get("trade_size_usd"),
            latest_trade.get("trade_size_usd"),
        )
    )
    order_price = _float_or_none(
        _first_nonempty(
            latest_fill.get("fill_price"),
            raw_fill_payload.get("order_price"),
            latest_fill.get("entry_price"),
            latest_trade.get("order_price"),
            latest_trade.get("best_bid"),
            latest_trade.get("open_price"),
            latest_trade.get("current_price"),
        )
    )
    fill_confirmed = bool(
        latest_fill
        or (
            latest_trade_status == "live_filled"
            and trade_size_usd is not None
            and trade_size_usd > 0.0
        )
    )
    attribution_mode = (
        "db_backed_attribution_ready"
        if latest_fill
        else ("trade_log_fallback_only" if fill_confirmed else "not_ready")
    )
    source_of_truth = (
        "data/jj_trades.db#fills"
        if latest_fill
        else str(
            btc5_maker.get("source")
            or btc5_maker.get("db_path")
            or DEFAULT_BTC5_DB_PATH
        )
    )

    return {
        "artifact": "btc5_trade_attribution",
        "schema_version": 1,
        "generated_at": _now_iso(),
        "service_name": str(service_name or PRIMARY_RUNTIME_SERVICE_NAME).strip()
        or PRIMARY_RUNTIME_SERVICE_NAME,
        "source_of_truth": source_of_truth,
        "attribution_mode": attribution_mode,
        "fill_confirmed": fill_confirmed,
        "latest_filled_trade_at": latest_filled_trade_at,
        "lane_id": lane_id,
        "strategy_family": strategy_family,
        "profile_id": profile_id,
        "trade_size_usd": trade_size_usd,
        "order_price": order_price,
        "market_id": latest_fill.get("market_id") or latest_trade.get("slug"),
        "order_id": latest_fill.get("order_id") or latest_trade.get("order_id"),
        "trade_id": latest_fill.get("trade_id"),
    }


def _build_btc5_trade_confirmation(
    *,
    btc5_maker: dict[str, Any],
    selected_package_summary: dict[str, Any],
    service_name: str,
    now: datetime,
) -> dict[str, Any]:
    latest_trade = (
        dict(btc5_maker.get("latest_trade") or {})
        if isinstance(btc5_maker.get("latest_trade"), dict)
        else {}
    )
    latest_order_status = str(latest_trade.get("order_status") or "").strip().lower() or None
    latest_trade_size_usd = _float_or_none(latest_trade.get("trade_size_usd"))
    latest_fill_at = _first_nonempty(
        btc5_maker.get("latest_live_filled_at"),
        latest_trade.get("updated_at") if latest_order_status == "live_filled" else None,
        latest_trade.get("created_at") if latest_order_status == "live_filled" else None,
    )
    latest_fill_dt = _parse_datetime_like(latest_fill_at)
    latest_fill_age_minutes = (
        round(max((now - latest_fill_dt).total_seconds() / 60.0, 0.0), 4)
        if latest_fill_dt is not None
        else None
    )
    live_filled_rows = _int_or_none(btc5_maker.get("live_filled_rows")) or 0
    fill_confirmed = bool(
        latest_order_status == "live_filled"
        and latest_trade_size_usd is not None
        and latest_trade_size_usd > 0.0
    )
    if fill_confirmed:
        status = "filled_confirmed"
    elif latest_order_status:
        status = "latest_trade_not_filled"
    elif live_filled_rows > 0:
        status = "historical_fill_present_latest_trade_missing"
    else:
        status = "no_live_fill_observed"
    return {
        "status": status,
        "proof_status": "fill_confirmed" if fill_confirmed else "no_fill_yet",
        "service_name": service_name,
        "source_of_truth": str(
            btc5_maker.get("source") or btc5_maker.get("db_path") or "data/btc_5min_maker.db"
        ),
        "canonical_live_profile": _selected_btc5_profile_id(selected_package_summary),
        "profile_id": _selected_btc5_profile_id(selected_package_summary),
        "canonical_live_package_hash": str(
            selected_package_summary.get("canonical_live_package_hash") or ""
        ).strip()
        or None,
        "lane_id": "maker_bootstrap_live",
        "strategy_family": "btc5_maker_bootstrap",
        "latest_order_status": latest_order_status,
        "latest_trade_window_start_ts": _int_or_none(latest_trade.get("window_start_ts")),
        "latest_trade_direction": latest_trade.get("direction"),
        "latest_trade_size_usd": latest_trade_size_usd,
        "trade_size_usd": latest_trade_size_usd,
        "order_price": _float_or_none(
            _first_nonempty(
                latest_trade.get("order_price"),
                latest_trade.get("best_bid"),
                latest_trade.get("open_price"),
                latest_trade.get("current_price"),
            )
        ),
        "latest_trade_pnl_usd": _float_or_none(latest_trade.get("pnl_usd")),
        "latest_filled_trade_at": latest_fill_dt.isoformat() if latest_fill_dt is not None else None,
        "latest_filled_trade_age_minutes": latest_fill_age_minutes,
        "live_filled_rows": live_filled_rows,
        "fill_confirmed": fill_confirmed,
    }


def _build_btc5_trade_proof(
    *,
    attribution: dict[str, Any],
    trade_confirmation: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    fill_confirmed = bool(
        attribution.get("fill_confirmed")
        or trade_confirmation.get("fill_confirmed")
    )
    latest_filled_trade_at = (
        str(
            attribution.get("latest_filled_trade_at")
            or trade_confirmation.get("latest_filled_trade_at")
            or ""
        ).strip()
        or None
    )
    trade_size_usd = _float_or_none(
        _first_nonempty(
            attribution.get("trade_size_usd"),
            trade_confirmation.get("trade_size_usd"),
            trade_confirmation.get("latest_trade_size_usd"),
        )
    )
    order_price = _float_or_none(
        _first_nonempty(
            attribution.get("order_price"),
            trade_confirmation.get("order_price"),
        )
    )
    proof_status = "fill_confirmed" if fill_confirmed else "no_fill_yet"
    payload = {
        "artifact": "btc5_trade_proof",
        "schema_version": 1,
        "generated_at": now.isoformat(),
        "proof_status": proof_status,
        "fill_confirmed": fill_confirmed,
        "service_name": str(
            attribution.get("service_name")
            or trade_confirmation.get("service_name")
            or PRIMARY_RUNTIME_SERVICE_NAME
        ).strip()
        or PRIMARY_RUNTIME_SERVICE_NAME,
        "source_of_truth": str(
            attribution.get("source_of_truth")
            or trade_confirmation.get("source_of_truth")
            or ""
        ).strip()
        or None,
        "lane_id": str(attribution.get("lane_id") or trade_confirmation.get("lane_id") or "").strip() or None,
        "strategy_family": str(
            attribution.get("strategy_family")
            or trade_confirmation.get("strategy_family")
            or ""
        ).strip()
        or None,
        "profile_id": str(
            attribution.get("profile_id")
            or trade_confirmation.get("profile_id")
            or trade_confirmation.get("canonical_live_profile")
            or ""
        ).strip()
        or None,
        "trade_size_usd": trade_size_usd,
        "order_price": order_price,
        "latest_filled_trade_at": latest_filled_trade_at,
        "attribution_mode": str(attribution.get("attribution_mode") or "").strip() or None,
        "freshness_sla_minutes": 45,
    }
    required_fields = [
        "service_name",
        "source_of_truth",
        "lane_id",
        "strategy_family",
        "profile_id",
        "attribution_mode",
    ]
    if fill_confirmed:
        required_fields.extend(
            [
                "latest_filled_trade_at",
                "trade_size_usd",
                "order_price",
            ]
        )
    payload["missing_fields"] = [
        field_name
        for field_name in required_fields
        if payload.get(field_name) in (None, "")
    ]
    return payload


def _compute_execution_notional_summary(*, root: Path, now: datetime, btc5_maker: dict[str, Any]) -> dict[str, Any]:
    db_path = root / DEFAULT_TRADES_DB_PATH
    if not db_path.exists():
        result = {
            "hourly_notional_usd": 0.0,
            "hourly_trade_count": 0,
            "per_venue_notional_usd": {
                "polymarket_hourly": 0.0,
                "kalshi_hourly": 0.0,
                "polymarket_total": 0.0,
                "kalshi_total": 0.0,
                "combined_hourly": 0.0,
                "combined_total": 0.0,
            },
            "per_venue_trade_counts": {
                "polymarket_hourly": 0,
                "kalshi_hourly": 0,
                "polymarket_total": 0,
                "kalshi_total": 0,
                "combined_hourly": 0,
                "combined_total": 0,
            },
            "source": "missing_data/jj_trades.db",
        }
        fallback = _summarize_recent_btc5_execution(btc5_maker=btc5_maker, now=now)
        if fallback["hourly_trade_count"] > 0:
            result["hourly_notional_usd"] = fallback["hourly_notional_usd"]
            result["hourly_trade_count"] = fallback["hourly_trade_count"]
            result["per_venue_notional_usd"]["polymarket_hourly"] = fallback["hourly_notional_usd"]
            result["per_venue_notional_usd"]["combined_hourly"] = fallback["hourly_notional_usd"]
            result["per_venue_trade_counts"]["polymarket_hourly"] = fallback["hourly_trade_count"]
            result["per_venue_trade_counts"]["combined_hourly"] = fallback["hourly_trade_count"]
            result["source"] = f"{result['source']}+{fallback['source']}.recent_live_filled"
        return result

    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(db_path)
        columns = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(trades)")
        }
        if "position_size_usd" not in columns:
            return {
                "hourly_notional_usd": 0.0,
                "hourly_trade_count": 0,
                "per_venue_notional_usd": {
                    "polymarket_hourly": 0.0,
                    "kalshi_hourly": 0.0,
                    "polymarket_total": 0.0,
                    "kalshi_total": 0.0,
                    "combined_hourly": 0.0,
                    "combined_total": 0.0,
                },
                "per_venue_trade_counts": {
                    "polymarket_hourly": 0,
                    "kalshi_hourly": 0,
                    "polymarket_total": 0,
                    "kalshi_total": 0,
                    "combined_hourly": 0,
                    "combined_total": 0,
                },
                "source": "data/jj_trades.db#trades.position_size_usd_missing",
            }
        if "timestamp" not in columns and "source" not in columns:
            query = "SELECT '' AS timestamp, position_size_usd, '' AS source FROM trades"
        elif "timestamp" not in columns:
            query = "SELECT '' AS timestamp, position_size_usd, source FROM trades"
        elif "source" not in columns:
            query = "SELECT timestamp, position_size_usd, '' AS source FROM trades"
        else:
            query = "SELECT timestamp, position_size_usd, source FROM trades"
        rows = list(conn.execute(query))
    except sqlite3.DatabaseError:
        return {
            "hourly_notional_usd": 0.0,
            "hourly_trade_count": 0,
            "per_venue_notional_usd": {
                "polymarket_hourly": 0.0,
                "kalshi_hourly": 0.0,
                "polymarket_total": 0.0,
                "kalshi_total": 0.0,
                "combined_hourly": 0.0,
                "combined_total": 0.0,
            },
            "per_venue_trade_counts": {
                "polymarket_hourly": 0,
                "kalshi_hourly": 0,
                "polymarket_total": 0,
                "kalshi_total": 0,
                "combined_hourly": 0,
                "combined_total": 0,
            },
            "source": "data/jj_trades.db#read_error",
        }
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass

    one_hour_ago = now.timestamp() - 3600.0
    totals = {
        "polymarket_hourly": 0.0,
        "kalshi_hourly": 0.0,
        "polymarket_total": 0.0,
        "kalshi_total": 0.0,
    }
    trade_counts = {
        "polymarket_hourly": 0,
        "kalshi_hourly": 0,
        "polymarket_total": 0,
        "kalshi_total": 0,
    }
    for row in rows:
        if len(row) == 2:
            timestamp_value = None
            size_value, source_value = row
        else:
            timestamp_value, size_value, source_value = row
        size = abs(_float_or_none(size_value) or 0.0)
        if size <= 0:
            continue
        venue = _infer_venue(source_value)
        totals[f"{venue}_total"] += size
        trade_counts[f"{venue}_total"] += 1

        parsed_ts = _parse_trade_timestamp(timestamp_value)
        if parsed_ts is not None and parsed_ts >= one_hour_ago:
            totals[f"{venue}_hourly"] += size
            trade_counts[f"{venue}_hourly"] += 1

    combined_hourly = totals["polymarket_hourly"] + totals["kalshi_hourly"]
    combined_total = totals["polymarket_total"] + totals["kalshi_total"]
    combined_hourly_count = trade_counts["polymarket_hourly"] + trade_counts["kalshi_hourly"]
    combined_total_count = trade_counts["polymarket_total"] + trade_counts["kalshi_total"]
    source = "data/jj_trades.db"

    if combined_hourly_count == 0 and combined_hourly <= 0.0:
        fallback = _summarize_recent_btc5_execution(btc5_maker=btc5_maker, now=now)
        if fallback["hourly_trade_count"] > 0:
            totals["polymarket_hourly"] = fallback["hourly_notional_usd"]
            trade_counts["polymarket_hourly"] = fallback["hourly_trade_count"]
            combined_hourly = totals["polymarket_hourly"] + totals["kalshi_hourly"]
            combined_hourly_count = trade_counts["polymarket_hourly"] + trade_counts["kalshi_hourly"]
            source = f"{source}+{fallback['source']}.recent_live_filled"

    return {
        "hourly_notional_usd": round(combined_hourly, 6),
        "hourly_trade_count": int(combined_hourly_count),
        "per_venue_notional_usd": {
            **{k: round(v, 6) for k, v in totals.items()},
            "combined_hourly": round(combined_hourly, 6),
            "combined_total": round(combined_total, 6),
        },
        "per_venue_trade_counts": {
            **{k: int(v) for k, v in trade_counts.items()},
            "combined_hourly": int(combined_hourly_count),
            "combined_total": int(combined_total_count),
        },
        "source": source,
    }


def _parse_trade_timestamp(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        parsed = _parse_datetime_like(text)
        if parsed is None:
            return None
        return parsed.timestamp()


def _infer_venue(source_value: Any) -> str:
    text = str(source_value or "").strip().lower()
    if "kalshi" in text:
        return "kalshi"
    return "polymarket"


def _count_candidate_reject_reasons(candidate_markets: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    if not isinstance(candidate_markets, list):
        return counts
    for candidate in candidate_markets:
        if not isinstance(candidate, dict):
            continue
        failures = candidate.get("kill_rule_failures")
        if not isinstance(failures, list):
            continue
        for reason in failures:
            key = str(reason).strip()
            if not key:
                continue
            counts[key] = int(counts.get(key, 0)) + 1
    return counts


def _delta_or_none(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None:
        return None
    return round(current - previous, 6)


def _build_operator_digest(report: dict[str, Any], *, launch: dict[str, Any]) -> str:
    return _build_operator_digest_impl(report, launch=launch)


def _count_recent_cap_breaches(
    *,
    btc5_maker: dict[str, Any],
    max_position_usd: float | None,
) -> tuple[int, int]:
    return _count_recent_cap_breaches_impl(
        btc5_maker=btc5_maker,
        max_position_usd=max_position_usd,
    )


def _build_state_improvement_truth_precedence(
    *,
    runtime_truth_snapshot: dict[str, Any],
    expected_service_name: str,
    observed_service_name: str | None,
) -> dict[str, Any]:
    return _build_state_improvement_truth_precedence_impl(
        runtime_truth_snapshot=runtime_truth_snapshot,
        expected_service_name=expected_service_name,
        observed_service_name=observed_service_name,
    )


def _build_state_improvement_evidence_freshness(
    *,
    runtime_truth_snapshot: dict[str, Any],
) -> dict[str, Any]:
    return _build_state_improvement_evidence_freshness_impl(
        runtime_truth_snapshot=runtime_truth_snapshot,
    )


def _hydrate_state_improvement_from_launch_contract(
    report: dict[str, Any],
    *,
    launch_packet: dict[str, Any],
    runtime_truth_snapshot: dict[str, Any],
) -> dict[str, Any]:
    return _hydrate_state_improvement_from_launch_contract_impl(
        report,
        launch_packet=launch_packet,
        runtime_truth_snapshot=runtime_truth_snapshot,
        build_operator_digest=lambda payload, launch_payload: _build_operator_digest(payload, launch=launch_payload),
    )


def _format_signed_number(value: Any) -> str:
    return _format_signed_number_impl(value)


def _render_state_improvement_digest_markdown(report: dict[str, Any]) -> str:
    return _render_state_improvement_digest_markdown_impl(report)


def _parse_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    payload: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw_value = stripped.split("=", 1)
        key = key.strip()
        if not key:
            continue
        value = _strip_env_inline_comment(raw_value.strip())
        if value.startswith(("'", '"')) and value.endswith(("'", '"')) and len(value) >= 2:
            value = value[1:-1]
        payload[key] = value
    return payload


def _strip_env_inline_comment(value: str) -> str:
    if " #" not in value:
        return value
    return value.split(" #", 1)[0].rstrip()


def _sanitize_env_subset(values: dict[str, Any]) -> dict[str, Any]:
    return {key: values[key] for key in RUNTIME_ENV_KEYS if key in values}


def _profile_contract_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    return {
        "selected_profile": payload.get("selected_profile") or payload.get("profile_name"),
        "mode": dict(payload.get("mode") or {}),
        "feature_flags": dict(payload.get("feature_flags") or {}),
        "risk_limits": dict(payload.get("risk_limits") or {}),
        "market_filters": dict(payload.get("market_filters") or {}),
        "signal_thresholds": dict(payload.get("signal_thresholds") or {}),
    }


def _mapping_diff(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    before_flat = _flatten_mapping(before)
    after_flat = _flatten_mapping(after)
    diffs: list[dict[str, Any]] = []
    for field in sorted(set(before_flat) | set(after_flat)):
        if before_flat.get(field) == after_flat.get(field):
            continue
        diffs.append(
            {
                "field": field,
                "before": before_flat.get(field),
                "after": after_flat.get(field),
            }
        )
    return diffs


def _flatten_mapping(value: Any, *, prefix: str = "") -> dict[str, Any]:
    if not isinstance(value, dict):
        return {prefix: value} if prefix else {}

    flattened: dict[str, Any] = {}
    for key, inner in value.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(inner, dict):
            flattened.update(_flatten_mapping(inner, prefix=path))
        else:
            flattened[path] = inner
    return flattened


def _extract_nested_value(payload: dict[str, Any], field: str) -> Any:
    current: Any = payload
    for part in field.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _build_metric_drift(candidates: dict[str, Any]) -> dict[str, Any]:
    normalized = {key: value for key, value in candidates.items() if value is not None}
    values = list(normalized.values())
    drift_detected = len(set(values)) > 1
    return {
        "candidates": candidates,
        "drift_detected": drift_detected,
    }


def _compare_profile_contract(
    selected_profile: str,
    effective_config: dict[str, Any],
    *,
    applied_overrides: list[Any],
) -> dict[str, Any]:
    base_bundle = load_runtime_profile_bundle(env={"JJ_RUNTIME_PROFILE": selected_profile})
    base_payload = _profile_contract_payload(base_bundle.config)
    effective_payload = _profile_contract_payload(effective_config)
    override_env_by_field = {
        f"{override.section}.{override.key}": override.env_var
        for override in applied_overrides
    }
    changed_fields: list[dict[str, Any]] = []
    for diff in _mapping_diff(base_payload, effective_payload):
        diff["env_var"] = override_env_by_field.get(diff["field"])
        changed_fields.append(diff)

    return {
        "selected_profile": selected_profile,
        "base_profile_path": str(base_bundle.source_path),
        "changed_fields": changed_fields,
    }


def _build_effective_caps(risk_limits: dict[str, Any]) -> dict[str, Any]:
    return {
        "max_position_usd": _float_or_none(risk_limits.get("max_position_usd")),
        "max_daily_loss_usd": _float_or_none(risk_limits.get("max_daily_loss_usd")),
        "max_open_positions": _int_or_none(risk_limits.get("max_open_positions")),
        "kelly_fraction": _float_or_none(risk_limits.get("kelly_fraction")),
        "max_kelly_fraction": _float_or_none(risk_limits.get("max_kelly_fraction")),
        "hourly_notional_budget_usd": _float_or_none(risk_limits.get("hourly_notional_budget_usd")),
        "max_exposure_pct": _float_or_none(risk_limits.get("max_exposure_pct")),
        "initial_bankroll": _float_or_none(risk_limits.get("initial_bankroll")),
    }


def _build_effective_thresholds(
    *,
    risk_limits: dict[str, Any],
    signal_thresholds: dict[str, Any],
    market_filters: dict[str, Any],
) -> dict[str, Any]:
    return {
        "yes_threshold": _float_or_none(signal_thresholds.get("yes_threshold")),
        "no_threshold": _float_or_none(signal_thresholds.get("no_threshold")),
        "lmsr_entry_threshold": _float_or_none(signal_thresholds.get("lmsr_entry_threshold")),
        "min_edge": _float_or_none(risk_limits.get("min_edge")),
        "max_resolution_hours": _float_or_none(market_filters.get("max_resolution_hours")),
        "min_category_priority": _int_or_none(market_filters.get("min_category_priority")),
    }


def _load_latest_deploy_evidence(root: Path) -> dict[str, Any]:
    reports_dir = root / "reports"
    candidates = [path for path in reports_dir.glob("deploy*.json") if path.is_file()]
    activation_path = root / BTC5_DEPLOY_ACTIVATION_PATH
    if activation_path.is_file():
        candidates.append(activation_path)
    if not candidates:
        return {
            "path": None,
            "generated_at": None,
            "remote_env_exists": None,
            "remote_values": {},
            "remote_runtime_profile": None,
            "agent_run_mode": None,
            "paper_trading": None,
            "service_state": None,
            "process_state": "unknown",
            "remote_probe": {},
            "validation": {
                "returncode": None,
                "stdout_tail": [],
                "stderr_tail": [],
                "storage_blocked": False,
                "storage_block_reason": None,
            },
        }

    latest_path = max(candidates, key=_artifact_sort_key)
    payload = _load_json(latest_path, default={})
    if latest_path == activation_path:
        override_env = dict(payload.get("override_env") or {})
        tracked_values = dict(override_env.get("tracked_values") or {})
        deploy_mode = str(payload.get("deploy_mode") or "").strip().lower()
        runtime_profile = str(payload.get("runtime_profile") or "").strip() or None
        paper_trading = payload.get("paper_trading")
        if paper_trading is None:
            paper_trading = _bool_or_none(tracked_values.get("PAPER_TRADING"))
        if paper_trading is None:
            paper_trading = _bool_or_none(
                tracked_values.get("BTC5_PAPER_TRADING")
            )
        agent_run_mode = "live" if deploy_mode.startswith("live") else None
        remote_values = dict(tracked_values)
        if runtime_profile:
            remote_values["JJ_RUNTIME_PROFILE"] = runtime_profile
        if paper_trading is not None:
            remote_values["PAPER_TRADING"] = "true" if bool(paper_trading) else "false"
        if agent_run_mode:
            remote_values["ELASTIFUND_AGENT_RUN_MODE"] = agent_run_mode

        verification_checks = dict(payload.get("verification_checks") or {})
        required_passed = bool(verification_checks.get("required_passed"))
        validation = {
            "returncode": 0 if required_passed else 1,
            "stdout_tail": [],
            "stderr_tail": list(verification_checks.get("failed_required_checks") or []),
            "storage_blocked": False,
            "storage_block_reason": None,
        }
        remote_probe = {
            "ok": required_passed,
            "open_positions": None,
            "last_trades": _int_or_none((payload.get("status_summary") or {}).get("fills")),
            "feature_status": {},
        }
        process_state = (
            "activation_verified"
            if required_passed
            else ("not_running" if str(payload.get("service_status") or "").strip() == "stopped" else "activation_failed")
        )
        return {
            "path": _relative_path_text(root, latest_path),
            "generated_at": _first_nonempty(payload.get("checked_at"), payload.get("generated_at")),
            "remote_env_exists": override_env.get("exists"),
            "remote_values": remote_values,
            "remote_runtime_profile": runtime_profile,
            "agent_run_mode": agent_run_mode,
            "paper_trading": paper_trading,
            "deploy_mode": payload.get("deploy_mode"),
            "service_name": payload.get("service_name"),
            "service_state": payload.get("service_status"),
            "process_state": process_state,
            "remote_probe": remote_probe,
            "required_passed": required_passed,
            "verification_checks": verification_checks,
            "validation": validation,
        }

    remote_mode = dict(payload.get("remote_mode") or {})
    remote_values = dict(remote_mode.get("values") or {})
    if not remote_values:
        service_mode_confirmed = dict(payload.get("service_mode_confirmed") or {})
        for line in service_mode_confirmed.get("remote_env_lines") or []:
            if isinstance(line, str) and "=" in line:
                key, value = line.split("=", 1)
                remote_values[key.strip()] = value.strip()

    pre_service = dict(payload.get("pre_service") or {})
    post_service = dict(payload.get("post_service") or {})
    service_state = str(
        post_service.get("status")
        or pre_service.get("status")
        or ""
    ).strip() or None
    remote_probe = _summarize_deploy_status_probe(
        dict((payload.get("validation") or {}).get("status_command") or {})
    )
    if remote_probe.get("ok"):
        process_state = "status_probe_ok"
    elif service_state == "running":
        process_state = "service_running_unprobed"
    elif service_state == "stopped":
        process_state = "not_running"
    else:
        process_state = "unknown"
    validation = _summarize_deploy_validation(payload)

    return {
        "path": _relative_path_text(root, latest_path),
        "generated_at": payload.get("generated_at"),
        "remote_env_exists": remote_mode.get("remote_env_exists"),
        "remote_values": remote_values,
        "remote_runtime_profile": remote_mode.get("runtime_profile"),
        "agent_run_mode": remote_mode.get("agent_run_mode"),
        "paper_trading": remote_mode.get("paper_trading"),
        "service_state": service_state,
        "process_state": process_state,
        "remote_probe": remote_probe,
        "validation": validation,
    }


def _summarize_deploy_status_probe(payload: dict[str, Any]) -> dict[str, Any]:
    lines = list(payload.get("stdout_tail") or [])
    feature_status: dict[str, str] = {}
    open_positions = None
    last_trades = None

    for index, line in enumerate(lines):
        stripped = str(line).strip()
        feature_match = re.match(
            r"^(llm|wallet_flow|lmsr|cross_platform_arb|combinatorial):\s*([a-z_]+)",
            stripped,
        )
        if feature_match:
            feature_status[feature_match.group(1)] = feature_match.group(2)
            continue

        if stripped == "Open Positions:":
            count = 0
            for candidate in lines[index + 1:]:
                candidate_text = str(candidate).strip()
                if not candidate_text:
                    break
                count += 1
            open_positions = count
            continue

        if stripped == "Last 5 trades:":
            count = 0
            for candidate in lines[index + 1:]:
                candidate_text = str(candidate).strip()
                if not candidate_text or candidate_text.startswith("="):
                    break
                if candidate_text.startswith("["):
                    count += 1
            last_trades = count

    return {
        "ok": payload.get("returncode") == 0,
        "returncode": payload.get("returncode"),
        "open_positions": open_positions,
        "last_trades": last_trades,
        "feature_status": feature_status,
    }


def _summarize_deploy_validation(payload: dict[str, Any]) -> dict[str, Any]:
    status_command = dict((payload.get("validation") or {}).get("status_command") or {})
    stdout_tail = list(status_command.get("stdout_tail") or [])
    stderr_tail = list(status_command.get("stderr_tail") or [])
    storage_block_reason = _detect_storage_block_reason(stderr_tail)
    return {
        "returncode": status_command.get("returncode"),
        "stdout_tail": stdout_tail,
        "stderr_tail": stderr_tail,
        "storage_blocked": bool(storage_block_reason),
        "storage_block_reason": storage_block_reason,
    }


def _detect_storage_block_reason(lines: Sequence[Any]) -> str | None:
    lowered_lines = [str(line).strip().lower() for line in lines if str(line).strip()]
    if any("no space left on device" in line for line in lowered_lines):
        return (
            "Remote runtime validation hit `No space left on device`; the VPS root filesystem is full "
            "and launch-control changes cannot be validated safely."
        )
    if any("disk i/o error" in line for line in lowered_lines):
        return (
            "Remote runtime validation hit a disk I/O error; treat VPS storage as unhealthy until "
            "disk space and SQLite writeability are repaired."
        )
    return None


def _build_remote_probe_alignment(
    *,
    effective_flags: dict[str, Any],
    local_counts: dict[str, Any],
    remote_probe: dict[str, Any],
) -> dict[str, Any]:
    feature_expectations = {
        "llm": bool(effective_flags.get("enable_llm_signals")),
        "wallet_flow": bool(effective_flags.get("enable_wallet_flow")),
        "lmsr": bool(effective_flags.get("enable_lmsr")),
        "cross_platform_arb": bool(effective_flags.get("enable_cross_platform_arb")),
    }
    feature_mismatches: list[str] = []
    for feature, enabled in feature_expectations.items():
        observed = str((remote_probe.get("feature_status") or {}).get(feature) or "").strip()
        expected = "active" if enabled else "disabled"
        if observed and observed != expected:
            feature_mismatches.append(
                f"{feature}: expected {expected}, observed {observed}"
            )

    count_mismatches: list[str] = []
    if remote_probe.get("open_positions") is not None and remote_probe.get("open_positions") != local_counts["open_positions"]:
        count_mismatches.append(
            f"open_positions: local={local_counts['open_positions']} remote_probe={remote_probe.get('open_positions')}"
        )
    if remote_probe.get("last_trades") is not None and remote_probe.get("last_trades") != local_counts["total_trades"]:
        count_mismatches.append(
            f"total_trades: local={local_counts['total_trades']} remote_probe={remote_probe.get('last_trades')}"
        )

    return {
        "feature_mismatches": feature_mismatches,
        "count_mismatches": count_mismatches,
        "aligned": not feature_mismatches and not count_mismatches,
    }


def _build_docs_runtime_drift(root: Path, authoritative_counts: dict[str, Any]) -> dict[str, Any]:
    zero_trade_re = re.compile(
        r"\b0\s+(?:trades|live trades|total trades|closed trades)\b",
        re.IGNORECASE,
    )
    zero_deployed_re = re.compile(r"\b0\s+deployed capital\b", re.IGNORECASE)
    stale_references: list[dict[str, Any]] = []
    for path in (root / "README.md", root / "PROJECT_INSTRUCTIONS.md"):
        if not path.exists():
            continue
        for line_number, line in enumerate(path.read_text().splitlines(), start=1):
            lowered = line.lower()
            if (
                authoritative_counts["cycles_completed"] > 314
                and "314" in line
                and "cycle" in lowered
            ):
                stale_references.append(
                    {
                        "path": _relative_path_text(root, path),
                        "line": line_number,
                        "excerpt": line.strip(),
                    }
                )
                continue
            if authoritative_counts["total_trades"] > 0 and zero_trade_re.search(line):
                stale_references.append(
                    {
                        "path": _relative_path_text(root, path),
                        "line": line_number,
                        "excerpt": line.strip(),
                    }
                )
                continue
            if authoritative_counts["deployed_capital_usd"] > 0 and (
                zero_deployed_re.search(line)
                or "no closed trades or deployed capital yet" in lowered
            ):
                stale_references.append(
                    {
                        "path": _relative_path_text(root, path),
                        "line": line_number,
                        "excerpt": line.strip(),
                    }
                )

    return {
        "stale": bool(stale_references),
        "stale_references": stale_references,
    }


def _bool_or_none(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return None
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return None


def _build_public_headlines(
    *,
    launch: dict[str, Any],
    wallet_flow: dict[str, Any],
    service: dict[str, Any],
    verification: dict[str, Any],
    drift: dict[str, Any],
) -> list[str]:
    return _build_public_headlines_impl(
        launch=launch,
        wallet_flow=wallet_flow,
        service=service,
        verification=verification,
        drift=drift,
    )


def _extract_lane_payload(payload: dict[str, Any], *, lane_key: str) -> dict[str, Any]:
    candidates = [
        payload.get("lanes", {}).get(lane_key),
        payload.get(f"{lane_key}_gate"),
        payload.get(lane_key) if isinstance(payload.get(lane_key), dict) else None,
    ]
    for candidate in candidates:
        if isinstance(candidate, dict) and (
            "status" in candidate
            or "blocked_reasons" in candidate
            or "summary" in candidate
        ):
            return candidate
    return {}


def _extract_wallet_count(payload: Any) -> int:
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        for key in ("wallets", "smart_wallets", "scores"):
            value = payload.get(key)
            if isinstance(value, list):
                return len(value)
            if isinstance(value, dict):
                return len(value)
        if "wallet_count" in payload:
            return int(payload.get("wallet_count") or 0)
    return 0


def _extract_wallet_last_updated(payload: Any) -> str | None:
    if isinstance(payload, dict):
        for key in ("last_updated", "updated_at", "generated_at", "timestamp"):
            value = payload.get(key)
            if value:
                return str(value)
    return None


def _summarize_test_output(output: str, *, success: bool, default: str | None = None) -> str:
    result_lines = _dedupe_preserve_order(
        [
            line.strip()
            for line in output.splitlines()
            if line.strip() and RESULT_SUMMARY_RE.search(line)
        ]
    )
    if result_lines:
        return "; ".join(result_lines)
    if default is not None:
        return default
    return _summarize_command_output(output, success=success)


def _summarize_command_output(output: str, *, success: bool) -> str:
    if not output:
        return "Command passed cleanly." if success else "Command failed without output."

    for line in reversed(output.splitlines()):
        stripped = line.strip()
        if stripped:
            return stripped
    return "Command passed cleanly." if success else "Command failed without output."


def _tail_lines(output: str, *, limit: int) -> list[str]:
    lines = [line for line in output.splitlines() if line.strip()]
    return lines[-limit:]


def _find_latest_report_path(root: Path, pattern: str) -> Path | None:
    reports_dir = root / "reports"
    candidates = [path for path in reports_dir.rglob(pattern) if path.is_file()]
    if not candidates:
        return None
    return max(candidates, key=_artifact_sort_key)


def _artifact_sort_key(path: Path) -> tuple[float, str]:
    payload = _load_json(path, default={})
    embedded_timestamps = []
    if isinstance(payload, dict):
        embedded_timestamps.extend(
            [
                payload.get("generated_at"),
                payload.get("report_generated_at"),
                payload.get("run_timestamp"),
                payload.get("checked_at"),
            ]
        )
    for candidate in embedded_timestamps:
        parsed = _parse_datetime_like(candidate)
        if parsed is not None:
            return (parsed.timestamp(), path.name)

    filename_timestamp = _parse_datetime_like(_extract_timestamp_from_filename(path.name))
    if filename_timestamp is not None:
        return (filename_timestamp.timestamp(), path.name)
    return (path.stat().st_mtime, path.name)


def _dedupe_preserve_order(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _load_json(path: Path, *, default: Any) -> Any:
    return _load_json_io(path, default=default)


def _relative_path_text(root: Path, path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _resolve_path(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _format_money(value: float) -> str:
    return f"${float(value):,.2f}"


def _safe_float(value: Any, default: float = 0.0) -> float:
    parsed = _float_or_none(value)
    return default if parsed is None else parsed


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _first_nonempty(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", []):
            return value
    return None


def _extract_timestamp_from_filename(name: str) -> str | None:
    match = re.search(r"(\d{8}T\d{6}Z)", name)
    if match is None:
        return None
    return match.group(1)


def _parse_datetime_like(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        numeric = float(text)
    except ValueError:
        numeric = None
    if numeric is not None and abs(numeric) >= 1_000_000_000:
        if abs(numeric) >= 1_000_000_000_000:
            numeric = numeric / 1000.0
        try:
            return datetime.fromtimestamp(numeric, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    compact = _extract_timestamp_from_filename(text)
    if compact:
        try:
            return datetime.strptime(compact, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _safe_iso_mtime(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    except FileNotFoundError:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Write the remote-cycle status artifact.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--output-md", default=str(DEFAULT_MARKDOWN_PATH))
    parser.add_argument("--output-json", default=str(DEFAULT_JSON_PATH))
    parser.add_argument(
        "--runtime-truth-latest-json",
        default=str(DEFAULT_RUNTIME_TRUTH_LATEST_PATH),
    )
    parser.add_argument(
        "--public-runtime-snapshot-json",
        default=str(DEFAULT_PUBLIC_RUNTIME_SNAPSHOT_PATH),
    )
    parser.add_argument(
        "--launch-packet-latest-json",
        default=str(DEFAULT_LAUNCH_PACKET_LATEST_PATH),
    )
    parser.add_argument("--service-status-json", default=str(DEFAULT_SERVICE_STATUS_PATH))
    parser.add_argument("--root-test-status-json", default=str(DEFAULT_ROOT_TEST_STATUS_PATH))
    parser.add_argument("--arb-status-json", default=str(DEFAULT_ARB_STATUS_PATH))
    parser.add_argument("--refresh-root-tests", action="store_true")
    parser.add_argument("--root-test-timeout-seconds", type=int, default=900)
    args = parser.parse_args()

    result = write_remote_cycle_status(
        ROOT,
        markdown_path=Path(args.output_md),
        json_path=Path(args.output_json),
        runtime_truth_latest_path=Path(args.runtime_truth_latest_json),
        public_runtime_snapshot_path=Path(args.public_runtime_snapshot_json),
        launch_packet_latest_path=Path(args.launch_packet_latest_json),
        config_path=Path(args.config),
        service_status_path=Path(args.service_status_json),
        root_test_status_path=Path(args.root_test_status_json),
        arb_status_path=Path(args.arb_status_json),
        refresh_root_tests=args.refresh_root_tests,
        root_test_timeout_seconds=args.root_test_timeout_seconds,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
