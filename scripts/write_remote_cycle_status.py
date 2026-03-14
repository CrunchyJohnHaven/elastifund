#!/usr/bin/env python3
"""Write the compact remote-cycle status report."""

from __future__ import annotations

import argparse
import csv
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

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.runtime_profile import load_runtime_profile as load_runtime_profile_bundle
from bot.runtime_profile import write_effective_runtime_profile as write_runtime_profile_bundle
from flywheel.status_report import build_remote_cycle_status as build_base_remote_cycle_status
from scripts.remote_cycle_status_core import (  # noqa: E402
    _apply_shared_truth_contract_to_status,
    _load_btc5_selected_package_summary,
    _resolve_authoritative_trade_totals,
)


DEFAULT_CONFIG_PATH = Path("config/remote_cycle_status.json")
DEFAULT_MARKDOWN_PATH = Path("reports/remote_cycle_status.md")
DEFAULT_JSON_PATH = Path("reports/remote_cycle_status.json")
DEFAULT_RUNTIME_TRUTH_LATEST_PATH = Path("reports/runtime_truth_latest.json")
DEFAULT_PUBLIC_RUNTIME_SNAPSHOT_PATH = Path("reports/public_runtime_snapshot.json")
DEFAULT_STATE_IMPROVEMENT_LATEST_PATH = Path("reports/state_improvement_latest.json")
DEFAULT_STATE_IMPROVEMENT_DIGEST_PATH = Path("reports/state_improvement_digest.md")
DEFAULT_SERVICE_STATUS_PATH = Path("reports/remote_service_status.json")
DEFAULT_ROOT_TEST_STATUS_PATH = Path("reports/root_test_status.json")
DEFAULT_ARB_STATUS_PATH = Path("reports/arb_empirical_snapshot.json")
DEFAULT_ENV_PATH = Path(".env")
DEFAULT_ENV_EXAMPLE_PATH = Path(".env.example")
DEFAULT_RUNTIME_OPERATOR_OVERRIDES_PATH = Path("reports/runtime_operator_overrides.env")
DEFAULT_RUNTIME_PROFILE_EFFECTIVE_PATH = Path("reports/runtime_profile_effective.json")
DEFAULT_WALLET_SCORES_PATH = Path("data/smart_wallets.json")
DEFAULT_WALLET_DB_PATH = Path("data/wallet_scores.db")
DEFAULT_TRADES_DB_PATH = Path("data/jj_trades.db")
DEFAULT_BTC5_DB_PATH = Path("data/btc_5min_maker.db")
DEFAULT_BTC5_WINDOW_ROWS_PATH = Path("reports/tmp_remote_btc5_window_rows.json")
DEFAULT_LAUNCH_CHECKLIST_PATH = Path("docs/ops/TRADING_LAUNCH_CHECKLIST.md")
BTC5_RESEARCH_STALE_HOURS = 6.0
BTC5_RESEARCH_PRIMARY_PATHS: tuple[Path, ...] = (
    Path("reports/btc5_autoresearch/latest.json"),
    Path("reports/btc5_autoresearch_loop/latest.json"),
)
BTC5_RESEARCH_OPTIONAL_PATHS: tuple[Path, ...] = (
    Path("reports/btc5_hypothesis_lab/summary.json"),
    Path("reports/btc5_regime_policy_lab/summary.json"),
)
BTC5_PUBLIC_FORECAST_PATHS: tuple[Path, ...] = (
    Path("reports/btc5_autoresearch/latest.json"),
    Path("reports/btc5_autoresearch_current_probe/latest.json"),
    Path("reports/btc5_autoresearch_loop/latest.json"),
)
DEFAULT_ROOT_TEST_COMMAND = ("make", "test")
RESULT_SUMMARY_RE = re.compile(
    r"\b\d+\s+(?:passed|failed|error|errors|skipped|xfailed|xpassed)\b",
    re.IGNORECASE,
)
RUNTIME_ENV_KEYS = (
    "JJ_RUNTIME_PROFILE",
    "ELASTIFUND_AGENT_RUN_MODE",
    "PAPER_TRADING",
    "JJ_ALLOW_ORDER_SUBMISSION",
    "JJ_MAX_POSITION_USD",
    "JJ_MAX_DAILY_LOSS_USD",
    "JJ_MAX_OPEN_POSITIONS",
    "JJ_KELLY_FRACTION",
    "JJ_HOURLY_NOTIONAL_BUDGET_USD",
    "JJ_MAX_RESOLUTION_HOURS",
    "JJ_YES_THRESHOLD",
    "JJ_NO_THRESHOLD",
    "JJ_MIN_EDGE",
    "ENABLE_LLM_SIGNALS",
    "ENABLE_WALLET_FLOW",
    "ENABLE_LMSR",
    "ENABLE_CROSS_PLATFORM_ARB",
    "JJ_FAST_FLOW_ONLY",
)
REMOTE_BOT_DIR = "/home/ubuntu/polymarket-trading-bot"
REMOTE_PYTHONPATH = (
    f"{REMOTE_BOT_DIR}:{REMOTE_BOT_DIR}/bot:{REMOTE_BOT_DIR}/polymarket-bot"
)
WALLET_PROBE_SCRIPT = """import json
import os
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import AssetType, BalanceAllowanceParams

pk = os.environ.get("POLY_PRIVATE_KEY") or os.environ.get("PRIVATE_KEY") or os.environ.get("POLYMARKET_PK") or ""
maker = os.environ.get("POLY_SAFE_ADDRESS") or os.environ.get("POLYMARKET_FUNDER") or ""
sig = int(os.environ.get("JJ_CLOB_SIGNATURE_TYPE", "1"))
if pk and not pk.startswith("0x"):
    pk = "0x" + pk

client = ClobClient(
    host="https://clob.polymarket.com",
    key=pk,
    chain_id=137,
    signature_type=sig,
    funder=maker,
)
creds = client.create_or_derive_api_creds()
client.set_api_creds(creds)
orders = client.get_orders()
live_orders = []
for order in orders if isinstance(orders, list) else []:
    if str(order.get("status") or "").upper() != "LIVE":
        continue
    original_size = float(order.get("original_size") or 0.0)
    size_matched = float(order.get("size_matched") or 0.0)
    price = float(order.get("price") or 0.0)
    remaining_shares = max(0.0, original_size - size_matched)
    live_orders.append(
        {
            "id": order.get("id"),
            "market": order.get("market"),
            "asset_id": order.get("asset_id"),
            "outcome": order.get("outcome"),
            "price": price,
            "original_size": original_size,
            "size_matched": size_matched,
            "remaining_shares": remaining_shares,
            "reserved_usd": round(remaining_shares * price, 4),
        }
    )

balance = client.get_balance_allowance(
    BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=sig)
)
print(
    json.dumps(
        {
            "maker_address": maker,
            "signature_type": sig,
            "free_collateral_usd": balance.get("balance"),
            "live_orders": live_orders,
            "reserved_order_usd": round(sum(item["reserved_usd"] for item in live_orders), 4),
        },
        sort_keys=True,
    )
)"""
BTC5_DB_PROBE_SCRIPT = """import json
import sqlite3
from pathlib import Path

db_path = Path("data/btc_5min_maker.db")
checked_at = "__CHECKED_AT__"
if not db_path.exists():
    print(json.dumps({"status": "unavailable", "checked_at": checked_at, "reason": "missing_data/btc_5min_maker.db"}))
    raise SystemExit(0)

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
summary_row = conn.execute(
    \"\"\"
    SELECT
        COUNT(*) AS total_rows,
        SUM(CASE WHEN order_status = 'live_filled' THEN 1 ELSE 0 END) AS live_filled_rows,
        SUM(CASE WHEN order_status = 'live_filled' THEN pnl_usd ELSE 0 END) AS live_filled_pnl_usd,
        AVG(CASE WHEN order_status = 'live_filled' THEN pnl_usd END) AS avg_live_filled_pnl_usd,
        MAX(CASE WHEN order_status = 'live_filled' THEN updated_at END) AS latest_live_filled_at
    FROM window_trades
    \"\"\"
).fetchone()
latest_row = conn.execute(
    \"\"\"
    SELECT
        id,
        window_start_ts,
        slug,
        direction,
        order_status,
        order_price,
        trade_size_usd,
        pnl_usd,
        created_at,
        updated_at
    FROM window_trades
    ORDER BY id DESC
    LIMIT 1
    \"\"\"
).fetchone()
recent_live_filled = conn.execute(
    \"\"\"
    SELECT
        id,
        window_start_ts,
        slug,
        direction,
        order_price,
        trade_size_usd,
        pnl_usd,
        updated_at
    FROM window_trades
    WHERE order_status = 'live_filled'
    ORDER BY id DESC
    LIMIT 5
    \"\"\"
).fetchall()

all_live_filled = [dict(row) for row in conn.execute(
    \"\"\"
    SELECT
        id,
        direction,
        ABS(delta) AS abs_delta,
        order_price,
        pnl_usd
    FROM window_trades
    WHERE order_status = 'live_filled'
    \"\"\"
).fetchall()]
conn.close()

def f(value):
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0

def recommend_guardrails(rows):
    if len(rows) < 10:
        return None
    max_abs_delta_candidates = [0.00002, 0.00005, 0.0001, 0.00015]
    down_caps = [0.48, 0.49, 0.50, 0.51]
    up_caps = [0.47, 0.48, 0.49, 0.50, 0.51]
    best = None
    baseline_pnl = round(sum(f(row.get("pnl_usd")) for row in rows), 4)
    for max_abs_delta in max_abs_delta_candidates:
        for down_cap in down_caps:
            for up_cap in up_caps:
                subset = [
                    row for row in rows
                    if f(row.get("abs_delta")) <= max_abs_delta
                    and (
                        (str(row.get("direction") or "").upper() == "DOWN" and f(row.get("order_price")) <= down_cap)
                        or (str(row.get("direction") or "").upper() == "UP" and f(row.get("order_price")) <= up_cap)
                    )
                ]
                if not subset:
                    continue
                pnl = round(sum(f(row.get("pnl_usd")) for row in subset), 4)
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
                if best is None or score > best["score"]:
                    best = {"score": score, "candidate": candidate}
    if best is None:
        return None
    return {
        **best["candidate"],
        "baseline_live_filled_rows": len(rows),
        "baseline_live_filled_pnl_usd": baseline_pnl,
    }

def price_bucket(order_price):
    price = f(order_price)
    if price < 0.49:
        return "<0.49"
    if price < 0.50:
        return "0.49"
    if price < 0.51:
        return "0.50"
    return "0.51+"

def summarize_fill_attribution(rows):
    if not rows:
        return None

    def rollup(group_rows, label):
        fills = len(group_rows)
        pnl = round(sum(f(row.get("pnl_usd")) for row in group_rows), 4)
        avg_pnl = round(pnl / fills, 4) if fills else 0.0
        avg_price = round(sum(f(row.get("order_price")) for row in group_rows) / fills, 4) if fills else 0.0
        return {
            "label": label,
            "fills": fills,
            "pnl_usd": pnl,
            "avg_pnl_usd": avg_pnl,
            "avg_order_price": avg_price,
        }

    direction_groups = {}
    price_groups = {}
    for row in rows:
        direction = (str(row.get("direction") or "UNKNOWN").strip().upper() or "UNKNOWN")
        direction_groups.setdefault(direction, []).append(row)
        price_groups.setdefault(price_bucket(row.get("order_price")), []).append(row)

    by_direction = sorted(
        [rollup(group_rows, direction) for direction, group_rows in direction_groups.items()],
        key=lambda item: (-item["pnl_usd"], -item["fills"], item["label"]),
    )
    bucket_order = {"<0.49": 0, "0.49": 1, "0.50": 2, "0.51+": 3}
    by_price_bucket = sorted(
        [rollup(group_rows, bucket) for bucket, group_rows in price_groups.items()],
        key=lambda item: bucket_order.get(item["label"], 99),
    )
    recent = sorted(rows, key=lambda row: int(row.get("id") or 0), reverse=True)[:12]
    recent_directions = sorted({
        (str(row.get("direction") or "UNKNOWN").strip().upper() or "UNKNOWN")
        for row in recent
    })
    recent_by_direction = sorted(
        [
            rollup(
                [row for row in recent if (str(row.get("direction") or "UNKNOWN").strip().upper() or "UNKNOWN") == direction],
                direction,
            )
            for direction in recent_directions
        ],
        key=lambda item: (-item["pnl_usd"], -item["fills"], item["label"]),
    )
    recent_direction_regime = {
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
    ) if by_price_bucket else None
    return {
        "by_direction": by_direction,
        "by_price_bucket": by_price_bucket,
        "recent_live_filled_summary": rollup(recent, "recent_12_live_filled"),
        "recent_live_filled_by_direction": recent_by_direction,
        "recent_direction_regime": recent_direction_regime,
        "best_direction": best_direction,
        "best_price_bucket": best_price_bucket,
    }

print(json.dumps({
    "status": "ok",
    "checked_at": checked_at,
    "db_path": str(db_path.resolve()),
    "total_rows": int(summary_row["total_rows"] or 0),
    "live_filled_rows": int(summary_row["live_filled_rows"] or 0),
    "live_filled_pnl_usd": round(f(summary_row["live_filled_pnl_usd"]), 4),
    "avg_live_filled_pnl_usd": round(f(summary_row["avg_live_filled_pnl_usd"]), 4),
    "latest_live_filled_at": summary_row["latest_live_filled_at"],
    "latest_trade": dict(latest_row) if latest_row is not None else {},
    "recent_live_filled": [dict(row) for row in recent_live_filled],
    "guardrail_recommendation": recommend_guardrails(all_live_filled),
    "fill_attribution": summarize_fill_attribution(all_live_filled),
}, sort_keys=True))
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fetch_json_url(url: str, *, timeout_seconds: int = 20) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "elastifund-runtime-truth/1.0"})
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"))


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
    for base in (root, root / "data", root / "reports"):
        if not base.exists():
            continue
        for path in base.glob("Polymarket-History*.csv"):
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            candidates.append(path)
    candidates.sort(key=lambda path: path.stat().st_mtime if path.exists() else 0.0, reverse=True)
    return candidates


def _wallet_row_value(row: dict[str, Any], keys: Sequence[str]) -> str:
    for key in keys:
        if key in row and str(row.get(key) or "").strip():
            return str(row.get(key) or "").strip()
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

    path = candidates[0]
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            rows = [dict(row) for row in reader if isinstance(row, dict)]
    except (OSError, csv.Error):
        return None
    if not rows:
        return None

    btc_closed_markets = 0
    btc_closed_net_cashflow_usd = 0.0
    btc_open_markets = 0
    non_btc_open_buy_notional_usd = 0.0
    btc_closed_ts: list[datetime] = []
    export_latest_ts: datetime | None = None
    equity_series: list[tuple[datetime, float]] = []
    closed_cashflow_series: list[tuple[datetime, float]] = []
    open_notional_series: list[tuple[datetime, float]] = []

    for row in rows:
        ts = _wallet_row_ts(row)
        if ts is not None and (export_latest_ts is None or ts > export_latest_ts):
            export_latest_ts = ts

        market_text = (
            _wallet_row_value(row, ("market", "market_title", "title", "question", "event", "ticker", "slug"))
            .lower()
        )
        status = _wallet_row_value(row, ("status", "state", "position_status", "order_status")).lower()
        is_btc = "btc" in market_text
        is_closed = any(token in status for token in ("closed", "resolved", "settled"))
        is_open = ("open" in status) and not is_closed

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

        if is_closed and is_btc:
            btc_closed_markets += 1
            btc_closed_net_cashflow_usd += cashflow
            if ts is not None:
                btc_closed_ts.append(ts)
        if is_open and is_btc:
            btc_open_markets += 1
        if is_open and not is_btc:
            non_btc_open_buy_notional_usd += max(0.0, buy_notional)

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

    return {
        "source_path": _relative_path_text(root, path) or str(path),
        "source_class": "wallet_export_csv",
        "exported_at": export_latest_ts.isoformat(),
        "source_age_hours": round(export_age_hours, 4),
        "wallet_export_fresh": wallet_export_fresh,
        "wallet_export_freshness_label": _freshness_label_for_age_hours(export_age_hours),
        "fresher_than_btc_reporting_source": fresher_than_btc,
        "use_wallet_export_reporting": use_wallet_export_reporting,
        "btc_closed_markets": int(btc_closed_markets),
        "btc_closed_net_cashflow_usd": round(btc_closed_net_cashflow_usd, 4),
        "btc_open_markets": int(btc_open_markets),
        "non_btc_open_buy_notional_usd": round(non_btc_open_buy_notional_usd, 4),
        "btc_closed_window_hours": round(btc_closed_window_hours, 4) if btc_closed_window_hours is not None else None,
        "portfolio_equity_delta_1d": _series_delta_1d(equity_series),
        "closed_cashflow_delta_1d": _series_delta_1d(closed_cashflow_series),
        "open_notional_delta_1d": _series_delta_1d(open_notional_series),
    }


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


def _summarize_btc5_fill_attribution(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None

    def _rollup(group_rows: list[dict[str, Any]], *, label: str) -> dict[str, Any]:
        fills = len(group_rows)
        pnl = round(sum(_safe_float(row.get("pnl_usd"), 0.0) for row in group_rows), 4)
        avg_pnl = round(pnl / fills, 4) if fills else 0.0
        avg_price = round(
            sum(_safe_float(row.get("order_price"), 0.0) for row in group_rows) / fills,
            4,
        ) if fills else 0.0
        return {
            "label": label,
            "fills": fills,
            "pnl_usd": pnl,
            "avg_pnl_usd": avg_pnl,
            "avg_order_price": avg_price,
        }

    direction_groups: dict[str, list[dict[str, Any]]] = {}
    price_bucket_groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        direction = str(row.get("direction") or "UNKNOWN").strip().upper() or "UNKNOWN"
        direction_groups.setdefault(direction, []).append(row)
        price_bucket_groups.setdefault(_btc5_price_bucket(row.get("order_price")), []).append(row)

    by_direction = sorted(
        (_rollup(group_rows, label=direction) for direction, group_rows in direction_groups.items()),
        key=lambda item: (-item["pnl_usd"], -item["fills"], item["label"]),
    )
    bucket_order = {"<0.49": 0, "0.49": 1, "0.50": 2, "0.51+": 3}
    by_price_bucket = sorted(
        (_rollup(group_rows, label=bucket) for bucket, group_rows in price_bucket_groups.items()),
        key=lambda item: bucket_order.get(item["label"], 99),
    )
    sorted_recent = sorted(
        rows,
        key=lambda row: _int_or_none(row.get("id")) or 0,
        reverse=True,
    )[:12]
    recent_summary = _rollup(sorted_recent, label="recent_12_live_filled")
    recent_by_direction = sorted(
        (
            _rollup([row for row in sorted_recent if str(row.get("direction") or "").strip().upper() == direction], label=direction)
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
            "win_rate_today": None,
            "recent_5_pnl_usd": 0.0,
            "recent_12_pnl_usd": 0.0,
            "recent_20_pnl_usd": 0.0,
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

    filled_rows_today = len(today_live_filled)
    filled_pnl_usd_today = round(sum(_safe_float(row.get("pnl_usd"), 0.0) for row in today_live_filled), 4)
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
        "win_rate_today": win_rate_today,
        "recent_5_pnl_usd": _sum_recent(5),
        "recent_12_pnl_usd": _sum_recent(12),
        "recent_20_pnl_usd": _sum_recent(20),
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
        remote_payload = json.loads((result.stdout or "").strip())
    except json.JSONDecodeError:
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
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        warnings.append(f"positions_fetch_failed:{exc}")

    try:
        closed_positions = _fetch_paginated_polymarket_endpoint(
            base_url="https://data-api.polymarket.com/closed-positions",
            params={"user": maker_address},
            limit=200,
            max_pages=20,
        )
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
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
                payload = json.loads(result.stdout.strip() or "{}")
                if isinstance(payload, dict):
                    payload.setdefault("source", "remote_sqlite_probe")
                    return payload
        except Exception:
            pass

    return _load_btc5_maker_state_from_db(root / DEFAULT_BTC5_DB_PATH, checked_at=checked_at)


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
                pnl_usd,
                order_status,
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
    return {
        "status": "ok",
        "checked_at": checked_at,
        "db_path": str(db_path),
        "source": "local_sqlite_db",
        "total_rows": int((summary_row["total_rows"] or 0) if summary_row is not None else 0),
        "live_filled_rows": int(
            (summary_row["live_filled_rows"] or 0) if summary_row is not None else 0
        ),
        "live_filled_pnl_usd": round(
            _safe_float(summary_row["live_filled_pnl_usd"] if summary_row is not None else 0.0),
            4,
        ),
        "avg_live_filled_pnl_usd": round(
            _safe_float(
                summary_row["avg_live_filled_pnl_usd"] if summary_row is not None else 0.0
            ),
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
            "btc5_avg_live_filled_pnl_usd": round(
                _safe_float(btc5_maker.get("avg_live_filled_pnl_usd"), 0.0),
                4,
            ),
            "btc5_latest_order_status": latest_trade.get("order_status"),
            "btc5_latest_window_start_ts": _int_or_none(latest_trade.get("window_start_ts")),
            "btc5_latest_trade_pnl_usd": _float_or_none(latest_trade.get("pnl_usd")),
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
    data_age_minutes = round(
        max(0.0, (datetime.now(timezone.utc) - freshest_timestamp).total_seconds()) / 60.0,
        1,
    )
    freshest_iso = freshest_timestamp.isoformat()

    runtime["last_remote_pull_at"] = freshest_iso
    cadence.update(
        {
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

    local_total_trades = int(runtime.get("trade_db_total_trades") or 0)
    local_closed_positions = int(runtime.get("closed_trades") or 0)
    local_open_positions = int(runtime.get("open_positions") or 0)

    wallet_status = str(polymarket_wallet.get("status") or "unavailable").strip().lower()
    remote_open_positions = int(polymarket_wallet.get("open_positions_count") or 0)
    remote_closed_positions = int(polymarket_wallet.get("closed_positions_count") or 0)
    wallet_live_orders = int(polymarket_wallet.get("live_orders_count") or 0)

    btc5_status = str(btc5_maker.get("status") or "unavailable").strip().lower()
    btc5_live_filled_rows = int(btc5_maker.get("live_filled_rows") or 0)
    btc5_total_rows = int(btc5_maker.get("total_rows") or 0)

    open_delta = remote_open_positions - local_open_positions
    closed_delta = remote_closed_positions - local_closed_positions
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
        source_path="remote CLOB + Polymarket data API",
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
            "source": "remote CLOB + Polymarket data API",
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
    status = build_base_remote_cycle_status(repo_root, config_path=config_path or DEFAULT_CONFIG_PATH)
    jj_state = _load_json(repo_root / "jj_state.json", default={})
    intel_snapshot = _load_json(repo_root / "data" / "intel_snapshot.json", default={})

    trade_counts = _load_trade_counts(repo_root)
    status["runtime"]["closed_trades"] = trade_counts["closed_trades"]
    status["runtime"]["trade_db_total_trades"] = trade_counts["total_trades"]
    status["runtime"]["trade_db_source"] = trade_counts["source"]

    service = _load_service_status(
        _resolve_path(repo_root, service_status_path or DEFAULT_SERVICE_STATUS_PATH)
    )
    root_tests = _load_root_test_status(
        _resolve_path(repo_root, root_test_status_path or DEFAULT_ROOT_TEST_STATUS_PATH)
    )
    wallet_flow = _load_wallet_flow_status(repo_root)
    polymarket_wallet = _load_polymarket_wallet_state(repo_root)
    btc5_maker = _load_btc5_maker_state(repo_root)
    _merge_polymarket_wallet_observation(status, polymarket_wallet)
    _merge_btc5_maker_observation(status, btc5_maker)
    accounting_reconciliation = _build_accounting_reconciliation(status, root=repo_root)
    status["accounting_reconciliation"] = accounting_reconciliation
    _refresh_remote_observation_cadence(
        status,
        service=service,
        polymarket_wallet=polymarket_wallet,
        btc5_maker=btc5_maker,
    )

    arb_payload = _load_json(
        _resolve_path(repo_root, arb_status_path or DEFAULT_ARB_STATUS_PATH),
        default={},
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
    )
    runtime_truth.update(
        {
            "can_btc5_trade_now": bool(btc5_stage_readiness.get("can_trade_now")),
            "allowed_stage": int(btc5_stage_readiness.get("allowed_stage") or 0),
            "allowed_stage_label": btc5_stage_readiness.get("allowed_stage_label"),
            "deployment_confidence_label": deployment_confidence.get("confidence_label"),
        }
    )

    status["service"] = service
    status["root_tests"] = root_tests
    status["wallet_flow"] = wallet_flow
    status["polymarket_wallet"] = polymarket_wallet
    status["btc_5min_maker"] = btc5_maker
    status["btc5_stage_readiness"] = btc5_stage_readiness
    status["deployment_confidence"] = deployment_confidence
    status["source_precedence"] = source_precedence
    status["structural_gates"] = {"a6": a6_gate, "b1": b1_gate}
    status["launch"] = launch
    status["runtime_truth"] = runtime_truth
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
    """Render the remote-cycle status artifact in markdown."""

    capital = status["capital"]
    runtime = status["runtime"]
    flywheel = status["flywheel"]
    cadence = status["data_cadence"]
    forecast = status["velocity_forecast"]
    finish = status["deployment_finish"]
    service = status["service"]
    root_tests = status["root_tests"]
    wallet_flow = status["wallet_flow"]
    polymarket_wallet = status.get("polymarket_wallet") or {}
    btc5_maker = status.get("btc_5min_maker") or {}
    gates = status["structural_gates"]
    launch = status["launch"]
    truth = status["runtime_truth"]
    accounting_reconciliation = status.get("accounting_reconciliation") or {}
    btc5_stage_readiness = status.get("btc5_stage_readiness") or {}
    deployment_confidence = status.get("deployment_confidence") or {}
    source_precedence = status.get("source_precedence") or {}

    lines = [
        "# Remote Cycle Status",
        "",
        f"- Generated: {status['generated_at']}",
        f"- Service: {service['status']} ({service.get('systemctl_state') or 'unknown'})",
        f"- Root regression suite: {root_tests['status']}",
        f"- Wallet-flow bootstrap: {wallet_flow['status']}",
        f"- A-6 gate: {gates['a6']['status']}",
        f"- B-1 gate: {gates['b1']['status']}",
        f"- Runtime drift detected: {'yes' if truth['drift_detected'] else 'no'}",
        f"- Accounting reconciliation drift: {'yes' if accounting_reconciliation.get('drift_detected') else 'no'}",
        f"- BTC5 can trade now: {'yes' if btc5_stage_readiness.get('can_trade_now') else 'no'}",
        f"- BTC5 allowed stage: {btc5_stage_readiness.get('allowed_stage_label') or 'stage_0'}",
        f"- Deployment confidence: {deployment_confidence.get('confidence_label') or 'unknown'}",
        f"- Live launch blocked: {'yes' if launch['live_launch_blocked'] else 'no'}",
        f"- Next operator action: {launch['next_operator_action']}",
        "",
        "## Capital",
        "",
        "| Account | Tracked USD | Source |",
        "|---------|-------------|--------|",
    ]

    for item in capital["sources"]:
        lines.append(
            f"| {item['account']} | {_format_money(item['amount_usd'])} | {item['source']} |"
        )

    lines.extend(
        [
            "",
            f"- Total tracked capital: {_format_money(capital['tracked_capital_usd'])}",
            f"- Capital currently deployed: {_format_money(capital['deployed_capital_usd'])}",
            f"- Capital still undeployed: {_format_money(capital['undeployed_capital_usd'])}",
            f"- Deployment progress: {capital['deployment_progress_pct']:.2f}%",
            (
                f"- Polymarket actual deployable USD: "
                f"{_format_money(capital['polymarket_actual_deployable_usd'])}"
                if capital.get("polymarket_actual_deployable_usd") is not None
                else "- Polymarket actual deployable USD: n/a"
            ),
            (
                f"- Polymarket tracked vs observed delta: "
                f"{_format_money(capital['polymarket_tracked_vs_observed_delta_usd'])}"
                if capital.get("polymarket_tracked_vs_observed_delta_usd") is not None
                else "- Polymarket tracked vs observed delta: n/a"
            ),
            "",
            "## Runtime",
            "",
            f"- Bankroll: {_format_money(runtime['bankroll_usd'])}",
            f"- Daily PnL: {_format_money(runtime['daily_pnl_usd'])} ({runtime.get('daily_pnl_date') or 'n/a'})",
            f"- Total PnL: {_format_money(runtime['total_pnl_usd'])}",
            f"- Total trades: {runtime['total_trades']}",
            f"- Closed trades: {runtime.get('closed_trades', 0)}",
            f"- Open positions: {runtime['open_positions']}",
            f"- Trades today: {runtime['trades_today']}",
            f"- Cycles completed: {runtime['cycles_completed']}",
            f"- Last remote pull: {runtime.get('last_remote_pull_at') or 'unknown'}",
            "",
            "## Polymarket Wallet",
            "",
            f"- Wallet status: {polymarket_wallet.get('status') or 'unknown'}",
            f"- Wallet checked at: {polymarket_wallet.get('checked_at') or 'unknown'}",
        ]
    )

    if polymarket_wallet.get("status") == "ok":
        lines.extend(
            [
                f"- Free collateral: {_format_money(polymarket_wallet.get('free_collateral_usd') or 0.0)}",
                f"- Reserved by live orders: {_format_money(polymarket_wallet.get('reserved_order_usd') or 0.0)}",
                f"- Live orders: {polymarket_wallet.get('live_orders_count') or 0}",
                f"- Open positions: {polymarket_wallet.get('open_positions_count') or 0}",
                f"- Position mark value: {_format_money(polymarket_wallet.get('positions_current_value_usd') or 0.0)}",
                f"- Unrealized PnL: {_format_money(polymarket_wallet.get('positions_unrealized_pnl_usd') or 0.0)}",
                f"- Realized PnL: {_format_money(polymarket_wallet.get('closed_positions_realized_pnl_usd') or 0.0)}",
                f"- Total observed wallet value: {_format_money(polymarket_wallet.get('total_wallet_value_usd') or 0.0)}",
                "",
                "### Wallet Warnings",
                "",
            ]
        )
        wallet_warnings = polymarket_wallet.get("warnings") or ["none"]
        lines.extend(f"- {warning}" for warning in wallet_warnings)
    else:
        lines.extend(
            [
                f"- Wallet probe reason: {polymarket_wallet.get('reason') or 'unknown'}",
                "",
            ]
        )

    lines.extend(
        [
            "## BTC 5-Min Maker",
            "",
            f"- Status: {btc5_maker.get('status') or 'unknown'}",
            f"- Checked at: {btc5_maker.get('checked_at') or 'unknown'}",
        ]
    )
    if btc5_maker.get("status") == "ok":
        latest_trade = btc5_maker.get("latest_trade") or {}
        fill_attribution = btc5_maker.get("fill_attribution") or {}
        best_direction = fill_attribution.get("best_direction") or {}
        best_price_bucket = fill_attribution.get("best_price_bucket") or {}
        recent_summary = fill_attribution.get("recent_live_filled_summary") or {}
        recent_regime = fill_attribution.get("recent_direction_regime") or {}
        lines.extend(
            [
                f"- Live filled rows: {btc5_maker.get('live_filled_rows') or 0}",
                f"- Live filled PnL: {_format_money(btc5_maker.get('live_filled_pnl_usd') or 0.0)}",
                f"- Average filled PnL: {_format_money(btc5_maker.get('avg_live_filled_pnl_usd') or 0.0)}",
                f"- Latest live fill at: {btc5_maker.get('latest_live_filled_at') or 'unknown'}",
                f"- Latest trade status: {latest_trade.get('order_status') or 'unknown'}",
                f"- Latest trade direction: {latest_trade.get('direction') or 'unknown'}",
                f"- Latest trade PnL: {_format_money(latest_trade.get('pnl_usd') or 0.0)}",
                (
                    f"- Best direction: {best_direction.get('label')} "
                    f"({best_direction.get('fills', 0)} fills, {_format_money(best_direction.get('pnl_usd') or 0.0)})"
                    if best_direction
                    else "- Best direction: n/a"
                ),
                (
                    f"- Best price bucket: {best_price_bucket.get('label')} "
                    f"({best_price_bucket.get('fills', 0)} fills, {_format_money(best_price_bucket.get('pnl_usd') or 0.0)})"
                    if best_price_bucket
                    else "- Best price bucket: n/a"
                ),
                (
                    f"- Recent 12 live fills: {recent_summary.get('fills', 0)} fills, "
                    f"{_format_money(recent_summary.get('pnl_usd') or 0.0)} total, "
                    f"{_format_money(recent_summary.get('avg_pnl_usd') or 0.0)} avg"
                    if recent_summary
                    else "- Recent 12 live fills: n/a"
                ),
                (
                    f"- Recent regime: favored={recent_regime.get('favored_direction')} "
                    f"weaker={recent_regime.get('weaker_direction')} "
                    f"gap={_format_money(recent_regime.get('pnl_gap_usd') or 0.0)} "
                    f"triggered={'yes' if recent_regime.get('triggered') else 'no'}"
                    if recent_regime
                    else "- Recent regime: n/a"
                ),
                "",
            ]
        )
    else:
        lines.extend(
            [
                f"- BTC 5-min reason: {btc5_maker.get('reason') or 'unknown'}",
                "",
            ]
        )

    lines.extend(
        [
            "## BTC5 Stage Readiness",
            "",
            f"- Can BTC5 trade now: {'yes' if btc5_stage_readiness.get('can_trade_now') else 'no'}",
            f"- Allowed stage now: {btc5_stage_readiness.get('allowed_stage_label') or 'stage_0'}",
            f"- Stage artifact freshness: {btc5_stage_readiness.get('freshness') or 'unknown'}",
            (
                f"- Probe freshness hours: {btc5_stage_readiness.get('probe_freshness_hours')}"
                if btc5_stage_readiness.get("probe_freshness_hours") is not None
                else "- Probe freshness hours: unknown"
            ),
            "",
            "### Stage 2 Blockers",
            "",
        ]
    )
    lines.extend(
        f"- {item}" for item in (btc5_stage_readiness.get("stage_2_blockers") or ["none"])
    )
    lines.extend(
        [
            "",
            "### Stage 3 Blockers",
            "",
        ]
    )
    lines.extend(
        f"- {item}" for item in (btc5_stage_readiness.get("stage_3_blockers") or ["none"])
    )

    lines.extend(
        [
            "## Service And Validation",
            "",
            f"- Service status: {service['status']}",
            f"- Service detail: {service.get('detail') or 'n/a'}",
            f"- Service checked at: {service.get('checked_at') or 'unknown'}",
            f"- Root regression status: {root_tests['status']}",
            f"- Root regression checked at: {root_tests.get('checked_at') or 'unknown'}",
            f"- Root regression summary: {root_tests.get('display_summary') or root_tests.get('summary') or 'n/a'}",
            f"- Wallet-flow readiness: {wallet_flow['status']}",
            f"- Wallet-flow wallet count: {wallet_flow['wallet_count']}",
            f"- Wallet-flow scores file exists: {'yes' if wallet_flow['scores_exists'] else 'no'}",
            f"- Wallet-flow DB exists: {'yes' if wallet_flow['db_exists'] else 'no'}",
            f"- Wallet-flow last updated: {wallet_flow.get('last_updated') or 'unknown'}",
            "",
            "### Wallet-Flow Reasons",
            "",
        ]
    )

    wallet_reasons = wallet_flow.get("reasons") or ["none"]
    lines.extend(f"- {reason}" for reason in wallet_reasons)
    lines.extend(
        [
            "",
            "## Structural Gates",
            "",
            f"- A-6 status: {gates['a6']['status']}",
            f"- A-6 summary: {gates['a6']['summary']}",
            f"- A-6 maker-fill proxy rate: {_format_optional_float(gates['a6'].get('maker_fill_proxy_rate'))}",
            f"- A-6 violation half-life seconds: {_format_optional_float(gates['a6'].get('violation_half_life_seconds'))}",
            f"- A-6 settlement evidence count: {gates['a6'].get('settlement_evidence_count', 0)}",
            "",
            "### A-6 Blocked Reasons",
            "",
        ]
    )

    a6_reasons = gates["a6"].get("blocked_reasons") or ["none"]
    lines.extend(f"- {reason}" for reason in a6_reasons)
    lines.extend(
        [
            "",
            f"- B-1 status: {gates['b1']['status']}",
            f"- B-1 summary: {gates['b1']['summary']}",
            f"- B-1 classification accuracy: {_format_optional_pct(gates['b1'].get('classification_accuracy'))}",
            f"- B-1 false positive rate: {_format_optional_pct(gates['b1'].get('false_positive_rate'))}",
            f"- B-1 violation half-life seconds: {_format_optional_float(gates['b1'].get('violation_half_life_seconds'))}",
            "",
            "### B-1 Blocked Reasons",
            "",
        ]
    )

    b1_reasons = gates["b1"].get("blocked_reasons") or ["none"]
    lines.extend(f"- {reason}" for reason in b1_reasons)
    lines.extend(
        [
            "",
            "## Flywheel",
            "",
            f"- Latest cycle: {flywheel.get('cycle_key') or 'n/a'}",
            f"- Deploy decision: {flywheel.get('decision') or 'n/a'}",
            f"- Reason: {flywheel.get('reason_code') or 'n/a'}",
            f"- Notes: {flywheel.get('notes') or 'n/a'}",
            f"- Summary artifact: {(flywheel.get('artifacts') or {}).get('summary_md', 'n/a')}",
            f"- Scorecard artifact: {(flywheel.get('artifacts') or {}).get('scorecard', 'n/a')}",
            "",
            "## Launch Path",
            "",
            f"- Fast-flow restart ready: {'yes' if launch['fast_flow_restart_ready'] else 'no'}",
            f"- Live launch blocked: {'yes' if launch['live_launch_blocked'] else 'no'}",
            f"- Next operator action: {launch['next_operator_action']}",
            f"- Launch checklist: {status['artifacts']['launch_checklist']}",
            "",
            "### Launch Blockers",
            "",
        ]
    )

    launch_reasons = launch.get("blocked_reasons") or ["none"]
    lines.extend(f"- {reason}" for reason in launch_reasons)
    lines.extend(
        [
            "",
            "## Runtime Truth",
            "",
            f"- Service status: {truth['service_status']}",
            f"- Cycles completed: {truth['cycles_completed']}",
            f"- Launch blocked: {'yes' if truth['launch_blocked'] else 'no'}",
            f"- Drift detected: {'yes' if truth['drift_detected'] else 'no'}",
            f"- Next action: {truth['next_action']}",
            "",
            "### Drift Reasons",
            "",
        ]
    )

    drift_reasons = truth.get("drift_reasons") or ["none"]
    lines.extend(f"- {reason}" for reason in drift_reasons)
    lines.extend(
        [
            "",
            "## Accounting Reconciliation",
            "",
            f"- Status: {accounting_reconciliation.get('status') or 'unknown'}",
            f"- Drift detected: {'yes' if accounting_reconciliation.get('drift_detected') else 'no'}",
            (
                f"- Local ledger counts: total={((accounting_reconciliation.get('local_ledger_counts') or {}).get('total_trades', 0))}, "
                f"open={((accounting_reconciliation.get('local_ledger_counts') or {}).get('open_positions', 0))}, "
                f"closed={((accounting_reconciliation.get('local_ledger_counts') or {}).get('closed_positions', 0))}"
            ),
            (
                f"- Remote wallet counts: open={((accounting_reconciliation.get('remote_wallet_counts') or {}).get('open_positions', 0))}, "
                f"closed={((accounting_reconciliation.get('remote_wallet_counts') or {}).get('closed_positions', 0))}, "
                f"live_orders={((accounting_reconciliation.get('remote_wallet_counts') or {}).get('live_orders', 0))}"
            ),
            (
                f"- BTC 5-min maker counts: total_rows={((accounting_reconciliation.get('btc_5min_maker_counts') or {}).get('total_rows', 0))}, "
                f"live_filled_rows={((accounting_reconciliation.get('btc_5min_maker_counts') or {}).get('live_filled_rows', 0))}"
            ),
            (
                f"- Unmatched open positions: {((accounting_reconciliation.get('unmatched_open_positions') or {}).get('delta_remote_minus_local', 0)):+d} "
                f"(local={((accounting_reconciliation.get('unmatched_open_positions') or {}).get('local_ledger', 0))}, "
                f"remote={((accounting_reconciliation.get('unmatched_open_positions') or {}).get('remote_wallet', 0))})"
            ),
            (
                f"- Unmatched closed positions: {((accounting_reconciliation.get('unmatched_closed_positions') or {}).get('delta_remote_minus_local', 0)):+d} "
                f"(local={((accounting_reconciliation.get('unmatched_closed_positions') or {}).get('local_ledger', 0))}, "
                f"remote={((accounting_reconciliation.get('unmatched_closed_positions') or {}).get('remote_wallet', 0))})"
            ),
            "",
            "### Reconciliation Drift Reasons",
            "",
        ]
    )
    accounting_drift_reasons = accounting_reconciliation.get("drift_reasons") or ["none"]
    lines.extend(f"- {reason}" for reason in accounting_drift_reasons)
    lines.extend(
        [
            "",
            "## Deployment Confidence",
            "",
            f"- Confidence label: {deployment_confidence.get('confidence_label') or 'unknown'}",
            f"- Freshness score: {_format_optional_float(deployment_confidence.get('freshness_score'))}",
            f"- Accounting coherence score: {_format_optional_float(deployment_confidence.get('accounting_coherence_score'))}",
            f"- Stage readiness score: {_format_optional_float(deployment_confidence.get('stage_readiness_score'))}",
            f"- Confirmation coverage score: {_format_optional_float(deployment_confidence.get('confirmation_coverage_score'))}",
            f"- Next required artifact: {deployment_confidence.get('next_required_artifact') or 'none'}",
            "",
            "### Deployment Blocking Checks",
            "",
        ]
    )
    lines.extend(
        f"- {item}" for item in (deployment_confidence.get("blocking_checks") or ["none"])
    )
    lines.extend(
        [
            "",
            "## Source Precedence",
            "",
            f"- Rule: {source_precedence.get('rule') or 'n/a'}",
            "",
            "### Precedence Contradictions",
            "",
        ]
    )
    contradictions = source_precedence.get("contradictions") or []
    if contradictions:
        for item in contradictions:
            if isinstance(item, dict):
                lines.append(f"- {item.get('code')}: {item.get('message')}")
            else:
                lines.append(f"- {item}")
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Data Cadence",
            "",
            f"- Pull cadence: every {cadence['pull_cadence_minutes']} minutes",
            f"- Full development cycle cadence: every {cadence['full_cycle_cadence_minutes']} minutes",
            f"- Freshness SLA: {cadence['freshness_sla_minutes']} minutes",
            f"- Last remote pull: {cadence.get('last_remote_pull_at') or 'unknown'}",
            f"- Next expected pull: {cadence.get('next_expected_pull_at') or 'unknown'}",
            f"- Current data age: {cadence.get('data_age_minutes') if cadence.get('data_age_minutes') is not None else 'unknown'} minutes",
            f"- Data stale: {'yes' if cadence.get('stale') else 'no'}",
            f"- Next data expectation: {cadence.get('expected_next_data_note') or 'n/a'}",
            "",
            "### Mandatory Extra Pulls",
            "",
        ]
    )

    triggers = cadence.get("manual_pull_triggers") or ["None recorded."]
    lines.extend(f"- {item}" for item in triggers)
    lines.extend(
        [
            "",
            "## Velocity Forecast",
            "",
            f"- Metric: {forecast['metric_name']}",
            f"- Definition: {forecast['definition']}",
            f"- Status: {forecast['status']}",
            f"- Confidence: {forecast['confidence']}",
            f"- Current annualized return run-rate: {forecast['current_annualized_return_pct']:.2f}% ({_format_money(forecast['current_annualized_return_usd'])}/year on tracked capital)",
            (
                f"- Next target annualized return run-rate: "
                f"{forecast['next_target_annualized_return_pct']:.2f}% "
                f"({_format_money(forecast['next_target_annualized_return_usd'])}/year) "
                f"after about {forecast['next_target_after_hours_of_work']:.1f} more engineering hours"
                if forecast.get("next_target_annualized_return_pct") is not None
                and forecast.get("next_target_after_hours_of_work") is not None
                else "- Next target annualized return run-rate: n/a"
            ),
            f"- Basis: {forecast.get('basis') or 'n/a'}",
            "",
            "### Forecast Assumptions",
            "",
        ]
    )

    assumptions = forecast.get("assumptions") or ["None recorded."]
    lines.extend(f"- {item}" for item in assumptions)
    lines.extend(
        [
            "",
            "### Forecast Invalidators",
            "",
        ]
    )
    invalidators = forecast.get("invalidators") or ["None recorded."]
    lines.extend(f"- {item}" for item in invalidators)
    lines.extend(
        [
            "",
            "## Deployment Finish",
            "",
            f"- Status: {finish['status']}",
            f"- ETA: {finish['eta']}",
            "",
            "### Current Blockers",
            "",
        ]
    )

    blockers = finish.get("blockers") or ["None recorded."]
    lines.extend(f"- {item}" for item in blockers)
    lines.extend(
        [
            "",
            "### Exit Criteria",
            "",
        ]
    )
    exit_criteria = finish.get("exit_criteria") or ["None recorded."]
    lines.extend(f"- {item}" for item in exit_criteria)
    lines.append("")
    return "\n".join(lines)


def write_remote_cycle_status(
    root: Path,
    *,
    markdown_path: Path | None = None,
    json_path: Path | None = None,
    runtime_truth_latest_path: Path | None = None,
    public_runtime_snapshot_path: Path | None = None,
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
    state_improvement_latest_target = _resolve_path(
        repo_root,
        state_improvement_latest_path or DEFAULT_STATE_IMPROVEMENT_LATEST_PATH,
    )
    state_improvement_digest_target = _resolve_path(
        repo_root,
        state_improvement_digest_path or DEFAULT_STATE_IMPROVEMENT_DIGEST_PATH,
    )
    timestamp_suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    runtime_truth_timestamped_target = repo_root / "reports" / f"runtime_truth_{timestamp_suffix}.json"
    runtime_mode_reconciliation_target = (
        repo_root / "reports" / f"runtime_mode_reconciliation_{timestamp_suffix}.md"
    )
    state_improvement_timestamped_target = (
        repo_root / "reports" / f"state_improvement_{timestamp_suffix}.json"
    )
    previous_runtime_truth_snapshot = _load_json(runtime_truth_latest_target, default={})

    status.setdefault("artifacts", {}).update(
        {
            "remote_cycle_status_markdown": str(markdown_target),
            "remote_cycle_status_json": str(json_target),
            "runtime_truth_latest_json": str(runtime_truth_latest_target),
            "runtime_truth_timestamped_json": str(runtime_truth_timestamped_target),
            "public_runtime_snapshot_json": str(public_runtime_snapshot_target),
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
    public_runtime_snapshot = build_public_runtime_snapshot(runtime_truth_snapshot)
    state_improvement = dict(runtime_truth_snapshot.get("state_improvement") or {})
    state_improvement.setdefault("artifact", "state_improvement_report")
    state_improvement.setdefault("schema_version", 1)
    state_improvement.setdefault("generated_at", runtime_truth_snapshot.get("generated_at"))

    markdown_target.parent.mkdir(parents=True, exist_ok=True)
    json_target.parent.mkdir(parents=True, exist_ok=True)
    runtime_truth_latest_target.parent.mkdir(parents=True, exist_ok=True)
    public_runtime_snapshot_target.parent.mkdir(parents=True, exist_ok=True)
    state_improvement_latest_target.parent.mkdir(parents=True, exist_ok=True)
    state_improvement_digest_target.parent.mkdir(parents=True, exist_ok=True)
    runtime_mode_reconciliation_target.parent.mkdir(parents=True, exist_ok=True)

    markdown_target.write_text(render_remote_cycle_status_markdown(status))
    json_target.write_text(json.dumps(status, indent=2, sort_keys=True))
    runtime_truth_timestamped_target.write_text(json.dumps(runtime_truth_snapshot, indent=2, sort_keys=True))
    runtime_truth_latest_target.write_text(json.dumps(runtime_truth_snapshot, indent=2, sort_keys=True))
    public_runtime_snapshot_target.write_text(
        json.dumps(public_runtime_snapshot, indent=2, sort_keys=True)
    )
    state_improvement_timestamped_target.write_text(json.dumps(state_improvement, indent=2, sort_keys=True))
    state_improvement_latest_target.write_text(json.dumps(state_improvement, indent=2, sort_keys=True))
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
        "state_improvement_latest": str(state_improvement_latest_target),
        "state_improvement_timestamped": str(state_improvement_timestamped_target),
        "state_improvement_digest": str(state_improvement_digest_target),
        "status": status,
    }


def _prepare_local_runtime_profile_evidence(root: Path) -> dict[str, Any]:
    local_env = _parse_env_file(root / DEFAULT_ENV_PATH)
    env_example = _parse_env_file(root / DEFAULT_ENV_EXAMPLE_PATH)
    operator_overrides = _parse_env_file(root / DEFAULT_RUNTIME_OPERATOR_OVERRIDES_PATH)
    effective_path = root / DEFAULT_RUNTIME_PROFILE_EFFECTIVE_PATH
    existing_effective = _load_json(effective_path, default={})

    selected_profile = (
        local_env.get("JJ_RUNTIME_PROFILE")
        or env_example.get("JJ_RUNTIME_PROFILE")
        or "blocked_safe"
    )
    merged_env = {"JJ_RUNTIME_PROFILE": selected_profile, **local_env, **operator_overrides}
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

    return {
        "bundle": bundle,
        "effective_path": effective_path,
        "existing_effective": existing_effective,
        "env_example": env_example,
        "local_env": local_env,
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
    effective_config = dict(bundle.config)
    effective_mode = dict(effective_config.get("mode") or {})
    effective_flags = dict(effective_config.get("feature_flags") or {})
    risk_limits = dict(effective_config.get("risk_limits") or {})
    signal_thresholds = dict(effective_config.get("signal_thresholds") or {})
    market_filters = dict(effective_config.get("market_filters") or {})

    deploy_evidence = _load_latest_deploy_evidence(root)
    remote_values = dict(deploy_evidence.get("remote_values") or {})
    remote_runtime_profile = (
        remote_values.get("JJ_RUNTIME_PROFILE")
        or deploy_evidence.get("remote_runtime_profile")
        or bundle.selected_profile
    )
    agent_run_mode = (
        remote_values.get("ELASTIFUND_AGENT_RUN_MODE")
        or deploy_evidence.get("agent_run_mode")
        or "unknown"
    )
    remote_paper_trading = _bool_or_none(
        remote_values.get("PAPER_TRADING") or deploy_evidence.get("paper_trading")
    )
    paper_trading = (
        remote_paper_trading
        if remote_paper_trading is not None
        else _bool_or_none(effective_mode.get("paper_trading"))
    )
    execution_mode = str(
        effective_mode.get("effective_execution_mode")
        or effective_mode.get("execution_mode")
        or "unknown"
    ).strip()
    allow_order_submission = bool(effective_mode.get("allow_order_submission"))
    service_state = str(
        deploy_evidence.get("service_state")
        or status.get("service", {}).get("status")
        or "unknown"
    ).strip()
    process_state = str(deploy_evidence.get("process_state") or "unknown").strip()

    launch_live_blocked = bool(status.get("launch", {}).get("live_launch_blocked"))
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
    if remote_runtime_profile and remote_runtime_profile != bundle.selected_profile:
        mode_inconsistency_reasons.append(
            f"remote JJ_RUNTIME_PROFILE={remote_runtime_profile} differs from local selected profile {bundle.selected_profile}"
        )
    if (
        agent_run_mode
        and agent_run_mode != "unknown"
        and execution_mode
        and execution_mode != "unknown"
        and agent_run_mode != execution_mode
    ):
        mode_inconsistency_reasons.append(
            f"remote ELASTIFUND_AGENT_RUN_MODE={agent_run_mode} differs from effective execution_mode={execution_mode}"
        )
    local_paper_trading = _bool_or_none(effective_mode.get("paper_trading"))
    if (
        remote_paper_trading is not None
        and local_paper_trading is not None
        and remote_paper_trading != local_paper_trading
    ):
        mode_inconsistency_reasons.append(
            f"remote PAPER_TRADING={remote_paper_trading} differs from effective paper_trading={local_paper_trading}"
        )
    if service_state == "running" and launch_live_blocked and allow_order_submission:
        mode_inconsistency_reasons.append(
            "service_state=running while launch_posture=blocked and allow_order_submission=true"
        )

    launch_posture = (
        "blocked"
        if launch_live_blocked or mode_ambiguity_fields or mode_inconsistency_reasons
        else "clear"
    )
    order_submit_enabled = bool(
        allow_order_submission
        and launch_posture != "blocked"
        and not mode_ambiguity_fields
        and not mode_inconsistency_reasons
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

    profile_override_diff = _compare_profile_contract(
        bundle.selected_profile,
        effective_config,
        applied_overrides=list(bundle.profile.applied_overrides),
    )
    caps_threshold_drift = any(
        change["field"].startswith(("risk_limits.", "signal_thresholds.", "market_filters.max_resolution_hours"))
        for change in profile_override_diff["changed_fields"]
    )

    docs_drift = _build_docs_runtime_drift(root, local_counts)
    remote_probe_alignment = _build_remote_probe_alignment(
        effective_flags=effective_flags,
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
            "jj-live.service is running while launch posture remains blocked"
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
        "agent_run_mode": agent_run_mode,
        "execution_mode": execution_mode,
        "paper_trading": paper_trading,
        "allow_order_submission": allow_order_submission,
        "order_submit_enabled": order_submit_enabled,
        "effective_caps": _build_effective_caps(risk_limits),
        "effective_thresholds": _build_effective_thresholds(
            risk_limits=risk_limits,
            signal_thresholds=signal_thresholds,
            market_filters=market_filters,
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
            "service_running_while_launch_blocked": service_state == "running"
            and launch_posture == "blocked",
            "runtime_profile_effective_stale_before_refresh": bool(
                runtime_profile_refresh.get("stale_before_refresh")
            ),
            "wallet_balance_drift": wallet_balance_drift,
            "wallet_balance_delta_usd": wallet_balance_delta_usd,
            "drift_reasons": drift_reasons,
        },
        "launch_posture": launch_posture,
        "restart_recommended": restart_recommended,
        "mode_reconciliation": {
            "sources": {
                "local_env": _relative_path_text(root, root / DEFAULT_ENV_PATH),
                "env_example": _relative_path_text(root, root / DEFAULT_ENV_EXAMPLE_PATH),
                "runtime_operator_overrides": _relative_path_text(
                    root,
                    root / DEFAULT_RUNTIME_OPERATOR_OVERRIDES_PATH,
                ),
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
            "runtime_operator_overrides": _sanitize_env_subset(
                runtime_profile_refresh.get("operator_overrides") or {}
            ),
            "runtime_profile_effective_refreshed": bool(runtime_profile_refresh.get("refreshed")),
            "runtime_profile_effective_stale_before_refresh_fields": list(
                runtime_profile_refresh.get("stale_before_refresh_fields") or []
            ),
            "selected_profile": bundle.selected_profile,
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
            "agent_run_mode": runtime_mode_reconciliation["agent_run_mode"],
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
            "mode_reconciliation": runtime_mode_reconciliation["mode_reconciliation"],
        }
    )
    snapshot.setdefault("summary", {}).update(
        {
            "remote_runtime_profile": runtime_mode_reconciliation["remote_runtime_profile"],
            "agent_run_mode": runtime_mode_reconciliation["agent_run_mode"],
            "execution_mode": runtime_mode_reconciliation["execution_mode"],
            "paper_trading": runtime_mode_reconciliation["paper_trading"],
            "allow_order_submission": runtime_mode_reconciliation["allow_order_submission"],
            "order_submit_enabled": runtime_mode_reconciliation["order_submit_enabled"],
        }
    )
    snapshot.setdefault("artifacts", {})[
        "runtime_mode_reconciliation_markdown"
    ] = _relative_path_text(ROOT, runtime_mode_reconciliation_path)
    snapshot.setdefault("drift", {})["mode_contract"] = runtime_mode_reconciliation["drift_flags"]
    _attach_control_plane_consistency(snapshot, root=root)
    return snapshot


def _load_strategy_scale_comparison_summary(
    *,
    root: Path,
    generated_at: datetime | None,
) -> dict[str, Any]:
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
    path = root / "reports" / "signal_source_audit.json"
    payload = _load_json(path, default={})
    summary = {
        "exists": path.exists() and isinstance(payload, dict),
        "path": _relative_path_text(root, path) or str(path),
        "generated_at": None,
        "age_hours": None,
        "freshness": "unknown",
        "stage_upgrade_support_status": None,
        "wallet_flow_confirmation_ready": None,
        "supports_capital_allocation": None,
        "best_component_source": None,
        "best_source_combo": None,
        "stage_upgrade_blocking_checks": [],
        "confirmation_coverage_score": None,
        "confirmation_coverage_status": None,
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
    confirmation_coverage_score = _first_nonempty(
        capital_support.get("confirmation_coverage_score"),
        capital_support.get("confirmation_coverage_pct"),
        capital_support.get("resolved_window_coverage_score"),
        capital_support.get("resolved_window_coverage_pct"),
    )
    normalized_confirmation_score = _normalize_unit_score(confirmation_coverage_score)
    wallet_flow_confirmation_ready = _bool_or_none(
        capital_support.get("wallet_flow_confirmation_ready")
    )
    if normalized_confirmation_score is None:
        if wallet_flow_confirmation_ready is True:
            normalized_confirmation_score = 0.75
        elif wallet_flow_confirmation_ready is False:
            normalized_confirmation_score = 0.2
        elif _bool_or_none(capital_support.get("supports_capital_allocation")) is True:
            normalized_confirmation_score = 0.35
        else:
            normalized_confirmation_score = 0.1
    stage_upgrade_blocking_checks = list(capital_support.get("stage_upgrade_blocking_checks") or [])
    stage_upgrade_support_status = _first_nonempty(
        capital_support.get("stage_upgrade_support_status"),
        capital_support.get("combined_sources_vs_single_source_status"),
        capital_support.get("wallet_flow_vs_llm_status"),
    )
    confirmation_coverage_status = str(
        _first_nonempty(
            capital_support.get("confirmation_coverage_status"),
            stage_upgrade_support_status,
            ("ready" if wallet_flow_confirmation_ready else None),
        )
        or "unknown"
    ).strip().lower()
    if not stage_upgrade_blocking_checks and confirmation_coverage_status in {
        "limited",
        "insufficient_data",
        "collect_more_data",
        "not_ready",
        "unknown",
    }:
        stage_upgrade_blocking_checks.append("confirmation_coverage_insufficient")
    summary.update(
        {
            "generated_at": artifact_generated_at.isoformat() if artifact_generated_at is not None else None,
            "age_hours": round(age_hours, 4) if age_hours is not None else None,
            "freshness": _freshness_label_for_age_hours(age_hours),
            "stage_upgrade_support_status": stage_upgrade_support_status,
            "wallet_flow_confirmation_ready": wallet_flow_confirmation_ready,
            "supports_capital_allocation": _bool_or_none(capital_support.get("supports_capital_allocation")),
            "best_component_source": capital_support.get("best_component_source"),
            "best_source_combo": capital_support.get("best_source_combo"),
            "stage_upgrade_blocking_checks": _dedupe_preserve_order(stage_upgrade_blocking_checks),
            "confirmation_coverage_score": normalized_confirmation_score,
            "confirmation_coverage_status": confirmation_coverage_status,
            "confirmation_lift": _float_or_none(
                _first_nonempty(
                    capital_support.get("confirmation_lift"),
                    capital_support.get("confirmation_lift_pct"),
                )
            ),
            "contradiction_penalty_score": _normalize_unit_score(
                _first_nonempty(
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
            or lowered.startswith("insufficient_trailing_12")
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

    trade_now_ready = allowed_stage >= 1
    trade_now_blockers = [] if trade_now_ready else (
        list(stage_blockers["stage_1_blockers"]) or list(dict.fromkeys(blocking_checks))
    )
    trade_now_reasons = [] if trade_now_ready else (
        reasons or ["BTC5 does not currently have a stage-approved deployment package."]
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
        "trade_now_status": "ready" if trade_now_ready else "blocked",
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

    return {
        "rule": (
            "Use the freshest artifact per truth domain: wallet export for wallet reporting, BTC5 probe for BTC5 activity, "
            "remote wallet for position counts when the local ledger drifts, and stale service files remain advisory only."
        ),
        "fields": fields,
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

    confirmation_coverage_score = _normalize_unit_score(
        audit_summary.get("confirmation_coverage_score")
    )
    if confirmation_coverage_score is None:
        confirmation_coverage_score = 0.1

    contradiction_codes = [
        str(item.get("code"))
        for item in list(source_precedence.get("contradictions") or [])
        if isinstance(item, dict) and str(item.get("code") or "").strip()
    ]
    blocking_checks = _dedupe_preserve_order(
        [
            *list(btc5_stage_readiness.get("trade_now_blocking_checks") or []),
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
                if confirmation_coverage_score < 0.4
                else []
            ),
            *contradiction_codes,
        ]
    )

    next_required_artifact = None
    if not scale_summary.get("exists"):
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
            + 0.1 * confirmation_coverage_score
        ),
        4,
    )
    confidence_label = _confidence_label_for_score(overall_score)
    if accounting_coherence_score < 0.35 or freshness_score < 0.3:
        confidence_label = "low"

    return {
        "confidence_label": confidence_label,
        "overall_score": overall_score,
        "freshness_score": freshness_score,
        "accounting_coherence_score": accounting_coherence_score,
        "stage_readiness_score": stage_readiness_score,
        "confirmation_coverage_score": round(confirmation_coverage_score, 4),
        "can_btc5_trade_now": bool(btc5_stage_readiness.get("can_trade_now")),
        "allowed_stage": allowed_stage,
        "allowed_stage_label": btc5_stage_readiness.get("allowed_stage_label") or f"stage_{allowed_stage}",
        "stage_2_blockers": list(btc5_stage_readiness.get("stage_2_blockers") or []),
        "stage_3_blockers": list(btc5_stage_readiness.get("stage_3_blockers") or []),
        "blocking_checks": blocking_checks,
        "warning_checks": contradiction_codes,
        "next_required_artifact": next_required_artifact,
        "service_status_freshness": service_freshness.get("freshness") or "unknown",
        "wallet_reporting_precedence": wallet_reconciliation_summary.get("reporting_precedence"),
        "current_probe_freshness": current_probe_summary.get("freshness") or "unknown",
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
    drift_flags = payload["drift_flags"]
    mode_reconciliation = payload["mode_reconciliation"]
    docs = mode_reconciliation["docs"]
    remote_probe = mode_reconciliation["remote_probe"]
    lines = [
        "# Runtime Mode Reconciliation",
        "",
        f"- Generated: {payload.get('generated_at') or 'unknown'}",
        f"- Service state: {payload['service_state']}",
        f"- Process state: {payload['process_state']}",
        f"- Remote runtime profile: {payload.get('remote_runtime_profile') or 'unknown'}",
        f"- Agent run mode: {payload.get('agent_run_mode') or 'unknown'}",
        f"- Execution mode: {payload.get('execution_mode') or 'unknown'}",
        f"- Paper trading: {payload.get('paper_trading')}",
        f"- Allow order submission: {payload.get('allow_order_submission')}",
        f"- Order submit enabled: {'yes' if payload.get('order_submit_enabled') else 'no'}",
        f"- Launch posture: {payload['launch_posture']}",
        f"- Restart recommended: {'yes' if payload.get('restart_recommended') else 'no'}",
        "",
        "## Runtime Counts",
        "",
        f"- Cycles completed: {payload['cycles_completed']}",
        f"- Total trades: {payload['total_trades']}",
        f"- Open positions: {payload['open_positions']}",
        f"- Deployed capital: {_format_money(payload['deployed_capital_usd'])}",
        "",
        "## Effective Caps",
        "",
    ]
    for key, value in payload["effective_caps"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(
        [
            "",
            "## Effective Thresholds",
            "",
        ]
    )
    for key, value in payload["effective_thresholds"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(
        [
            "",
            "## Drift Flags",
            "",
            f"- Count drift: {'yes' if drift_flags['count_drift'] else 'no'}",
            f"- Profile override drift: {'yes' if drift_flags['profile_override_drift'] else 'no'}",
            f"- Caps/threshold drift: {'yes' if drift_flags['caps_threshold_drift'] else 'no'}",
            f"- Docs stale: {'yes' if drift_flags['docs_stale'] else 'no'}",
            f"- Local/remote truth mismatch: {'yes' if drift_flags['local_remote_truth_mismatch'] else 'no'}",
            f"- Mode field ambiguity: {'yes' if drift_flags['mode_field_ambiguity'] else 'no'}",
            f"- Mode field inconsistency: {'yes' if drift_flags['mode_field_inconsistency'] else 'no'}",
            f"- Service running while launch blocked: {'yes' if drift_flags['service_running_while_launch_blocked'] else 'no'}",
            f"- Wallet balance drift: {'yes' if drift_flags.get('wallet_balance_drift') else 'no'}",
            "",
            "### Drift Reasons",
            "",
        ]
    )
    drift_reasons = drift_flags.get("drift_reasons") or ["none"]
    lines.extend(f"- {reason}" for reason in drift_reasons)
    lines.extend(
        [
            "",
            "## Local / Remote / Docs",
            "",
            f"- Local selected profile: {mode_reconciliation['selected_profile']}",
            f"- Local `.env` selector: {(mode_reconciliation['local_env'] or {}).get('JJ_RUNTIME_PROFILE') or 'unset'}",
            f"- Remote selector: {(mode_reconciliation['remote_mode']['values'] or {}).get('JJ_RUNTIME_PROFILE') or 'unknown'}",
            f"- Remote agent run mode: {(mode_reconciliation['remote_mode']['values'] or {}).get('ELASTIFUND_AGENT_RUN_MODE') or 'unknown'}",
            f"- Remote paper trading: {(mode_reconciliation['remote_mode']['values'] or {}).get('PAPER_TRADING') or 'unknown'}",
            f"- Remote status probe open positions: {remote_probe.get('open_positions', 'unknown')}",
            f"- Remote status probe last trades: {remote_probe.get('last_trades', 'unknown')}",
            "",
            "### Remote Probe Mismatches",
            "",
        ]
    )
    mismatches = [
        *list(mode_reconciliation["remote_probe_alignment"].get("feature_mismatches") or []),
        *list(mode_reconciliation["remote_probe_alignment"].get("count_mismatches") or []),
    ]
    lines.extend(f"- {item}" for item in (mismatches or ["none"]))
    lines.extend(
        [
            "",
            "### Docs Drift",
            "",
        ]
    )
    stale_references = docs.get("stale_references") or ["none"]
    if stale_references == ["none"]:
        lines.append("- none")
    else:
        for reference in stale_references:
            if isinstance(reference, str):
                lines.append(f"- {reference}")
                continue
            lines.append(
                f"- {reference['path']}:{reference['line']} -> {reference['excerpt']}"
            )
    lines.append("")
    return "\n".join(lines)


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
            if "jj-live.service is running while launch posture remains blocked" in reason
        ),
        None,
    )
    launch_posture = "blocked" if launch["live_launch_blocked"] else "clear"
    latest_edge_scan = _summarize_edge_scan(repo_root, latest_edge_scan_path)
    latest_pipeline = _summarize_pipeline(repo_root, latest_pipeline_path)
    previous_snapshot = (
        previous_runtime_truth_snapshot if isinstance(previous_runtime_truth_snapshot, dict) else {}
    )
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
            "btc5_can_trade_now": bool(btc5_stage_readiness.get("can_trade_now")),
            "btc5_allowed_stage": btc5_stage_readiness.get("allowed_stage_label"),
            "deployment_confidence_label": deployment_confidence.get("confidence_label"),
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
    """Build a sanitized snapshot for docs and the website."""

    capital = runtime_truth_snapshot["capital"]
    runtime = runtime_truth_snapshot["runtime"]
    launch = runtime_truth_snapshot["launch"]
    wallet_flow = runtime_truth_snapshot["wallet_flow"]
    polymarket_wallet = runtime_truth_snapshot.get("polymarket_wallet") or {}
    btc5_maker = runtime_truth_snapshot.get("btc_5min_maker") or {}
    service = runtime_truth_snapshot["service"]
    verification = runtime_truth_snapshot["verification"]
    structural_gates = runtime_truth_snapshot["structural_gates"]
    latest_edge_scan = runtime_truth_snapshot["latest_edge_scan"]
    latest_pipeline = runtime_truth_snapshot["latest_pipeline"]
    state_improvement = runtime_truth_snapshot.get("state_improvement") or {}
    drift = runtime_truth_snapshot["drift"]
    btc5_stage_readiness = runtime_truth_snapshot.get("btc5_stage_readiness") or {}
    deployment_confidence = runtime_truth_snapshot.get("deployment_confidence") or {}
    source_precedence = runtime_truth_snapshot.get("source_precedence") or {}

    public_snapshot = {
        "artifact": "public_runtime_snapshot",
        "schema_version": 1,
        "generated_at": runtime_truth_snapshot["generated_at"],
        "snapshot_source": runtime_truth_snapshot["artifacts"]["runtime_truth_latest_json"],
        "capital": {
            "tracked_capital_usd": capital["tracked_capital_usd"],
            "deployed_capital_usd": capital["deployed_capital_usd"],
            "undeployed_capital_usd": capital["undeployed_capital_usd"],
            "bankroll_usd": runtime["bankroll_usd"],
            "polymarket_actual_deployable_usd": capital.get("polymarket_actual_deployable_usd"),
            "polymarket_observed_total_usd": capital.get("polymarket_observed_total_usd"),
            "polymarket_tracked_vs_observed_delta_usd": capital.get(
                "polymarket_tracked_vs_observed_delta_usd"
            ),
        },
        "runtime": {
            "cycles_completed": runtime["cycles_completed"],
            "total_trades": runtime["total_trades"],
            "closed_trades": runtime["closed_trades"],
            "open_positions": runtime["open_positions"],
            "daily_pnl_usd": runtime["daily_pnl_usd"],
            "total_pnl_usd": runtime["total_pnl_usd"],
            "polymarket_open_positions": runtime.get("polymarket_open_positions"),
            "polymarket_live_orders": runtime.get("polymarket_live_orders"),
            "polymarket_closed_positions_realized_pnl_usd": runtime.get(
                "polymarket_closed_positions_realized_pnl_usd"
            ),
            "btc5_source": runtime.get("btc5_source"),
            "btc5_db_path": runtime.get("btc5_db_path"),
            "btc5_live_filled_rows": runtime.get("btc5_live_filled_rows"),
            "btc5_live_filled_pnl_usd": runtime.get("btc5_live_filled_pnl_usd"),
            "btc5_latest_order_status": runtime.get("btc5_latest_order_status"),
            "btc5_intraday_live_summary": runtime.get("btc5_intraday_live_summary") or {},
        },
        "runtime_mode": {
            "remote_runtime_profile": runtime_truth_snapshot.get("remote_runtime_profile"),
            "agent_run_mode": runtime_truth_snapshot.get("agent_run_mode"),
            "execution_mode": runtime_truth_snapshot.get("execution_mode"),
            "paper_trading": runtime_truth_snapshot.get("paper_trading"),
            "allow_order_submission": runtime_truth_snapshot.get("allow_order_submission"),
            "order_submit_enabled": runtime_truth_snapshot.get("order_submit_enabled"),
        },
        "service": {
            "status": service["status"],
            "checked_at": service.get("checked_at"),
            "drift_detected": service.get("drift_detected", False),
            "drift_reason": service.get("drift_reason"),
        },
        "launch": {
            "posture": launch["posture"],
            "fast_flow_restart_ready": launch["fast_flow_restart_ready"],
            "live_launch_blocked": launch["live_launch_blocked"],
            "blocked_reasons": list(launch.get("blocked_reasons") or []),
            "next_operator_action": launch["next_operator_action"],
        },
        "btc5_stage_readiness": {
            "can_trade_now": btc5_stage_readiness.get("can_trade_now"),
            "allowed_stage": btc5_stage_readiness.get("allowed_stage"),
            "allowed_stage_label": btc5_stage_readiness.get("allowed_stage_label"),
            "stage_2_blockers": list(btc5_stage_readiness.get("stage_2_blockers") or []),
            "stage_3_blockers": list(btc5_stage_readiness.get("stage_3_blockers") or []),
            "freshness": btc5_stage_readiness.get("freshness"),
            "probe_freshness_hours": btc5_stage_readiness.get("probe_freshness_hours"),
        },
        "deployment_confidence": {
            "confidence_label": deployment_confidence.get("confidence_label"),
            "freshness_score": deployment_confidence.get("freshness_score"),
            "accounting_coherence_score": deployment_confidence.get("accounting_coherence_score"),
            "stage_readiness_score": deployment_confidence.get("stage_readiness_score"),
            "confirmation_coverage_score": deployment_confidence.get("confirmation_coverage_score"),
            "can_btc5_trade_now": deployment_confidence.get("can_btc5_trade_now"),
            "allowed_stage": deployment_confidence.get("allowed_stage"),
            "allowed_stage_label": deployment_confidence.get("allowed_stage_label"),
            "blocking_checks": list(deployment_confidence.get("blocking_checks") or []),
            "next_required_artifact": deployment_confidence.get("next_required_artifact"),
        },
        "source_precedence": {
            "rule": source_precedence.get("rule"),
            "fields": list(source_precedence.get("fields") or []),
            "contradictions": list(source_precedence.get("contradictions") or []),
        },
        "wallet_flow": {
            "status": wallet_flow["status"],
            "ready": wallet_flow["ready"],
            "wallet_count": wallet_flow["wallet_count"],
            "last_updated": wallet_flow.get("last_updated"),
        },
        "polymarket_wallet": {
            "status": polymarket_wallet.get("status"),
            "checked_at": polymarket_wallet.get("checked_at"),
            "free_collateral_usd": polymarket_wallet.get("free_collateral_usd"),
            "reserved_order_usd": polymarket_wallet.get("reserved_order_usd"),
            "live_orders_count": polymarket_wallet.get("live_orders_count"),
            "open_positions_count": polymarket_wallet.get("open_positions_count"),
            "positions_current_value_usd": polymarket_wallet.get("positions_current_value_usd"),
            "positions_unrealized_pnl_usd": polymarket_wallet.get(
                "positions_unrealized_pnl_usd"
            ),
            "closed_positions_realized_pnl_usd": polymarket_wallet.get(
                "closed_positions_realized_pnl_usd"
            ),
            "total_wallet_value_usd": polymarket_wallet.get("total_wallet_value_usd"),
            "warnings": list(polymarket_wallet.get("warnings") or []),
        },
        "btc_5min_maker": {
            "status": btc5_maker.get("status"),
            "checked_at": btc5_maker.get("checked_at"),
            "source": btc5_maker.get("source"),
            "db_path": btc5_maker.get("db_path"),
            "live_filled_rows": btc5_maker.get("live_filled_rows"),
            "live_filled_pnl_usd": btc5_maker.get("live_filled_pnl_usd"),
            "avg_live_filled_pnl_usd": btc5_maker.get("avg_live_filled_pnl_usd"),
            "latest_live_filled_at": btc5_maker.get("latest_live_filled_at"),
            "latest_trade": btc5_maker.get("latest_trade") or {},
            "recent_live_filled": list(btc5_maker.get("recent_live_filled") or []),
            "fill_attribution": btc5_maker.get("fill_attribution") or {},
            "intraday_live_summary": btc5_maker.get("intraday_live_summary") or {},
        },
        "structural_gates": {
            "a6": {
                "status": structural_gates["a6"]["status"],
                "summary": structural_gates["a6"]["summary"],
            },
            "b1": {
                "status": structural_gates["b1"]["status"],
                "summary": structural_gates["b1"]["summary"],
            },
        },
        "verification": {
            "status": verification["status"],
            "summary": verification["summary"],
            "checked_at": verification.get("checked_at"),
        },
        "latest_edge_scan": {
            "path": latest_edge_scan.get("path"),
            "generated_at": latest_edge_scan.get("generated_at"),
            "recommended_action": latest_edge_scan.get("recommended_action"),
            "action_reason": latest_edge_scan.get("action_reason"),
        },
        "latest_pipeline": {
            "path": latest_pipeline.get("path"),
            "report_generated_at": latest_pipeline.get("report_generated_at"),
            "recommendation": latest_pipeline.get("recommendation"),
            "reasoning": latest_pipeline.get("reasoning"),
        },
        "state_improvement": {
            "operator_digest": state_improvement.get("operator_digest"),
            "hourly_budget_progress": state_improvement.get("hourly_budget_progress"),
            "active_thresholds": state_improvement.get("active_thresholds"),
            "per_venue_candidate_counts": state_improvement.get("per_venue_candidate_counts"),
            "per_venue_executed_notional_usd": (
                state_improvement.get("per_venue_executed_notional_usd") or {}
            ),
            "reject_reasons": state_improvement.get("reject_reasons") or [],
            "improvement_velocity": state_improvement.get("improvement_velocity") or {},
            "strategy_recommendations": state_improvement.get("strategy_recommendations") or {},
        },
        "operator_headlines": _build_public_headlines(
            launch=launch,
            wallet_flow=wallet_flow,
            service=service,
            verification=verification,
            drift=drift,
        ),
    }
    return public_snapshot


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

    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
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
    return _load_service_status_with_fallback(path.parent.parent, path)


def _load_service_status_with_fallback(root: Path, path: Path) -> dict[str, Any]:
    raw = _load_json(path, default={})
    service = _normalize_service_status_payload(
        raw,
        default_service_name="jj-live.service",
        source=_relative_path_text(root, path) or str(path),
    )
    if service["status"] != "unknown":
        return service

    local_probe = _probe_local_systemctl_service_status(service["service_name"])
    if local_probe["status"] != "unknown":
        return local_probe

    fallback = _find_latest_artifact_payload(
        root,
        [
            Path("reports/runtime_truth_latest.json"),
            Path("reports/remote_cycle_status.json"),
            "reports/runtime_truth_*.json",
            "reports/deploy_*.json",
        ],
        extractor=_extract_service_status_candidate,
    )
    if fallback is not None:
        return fallback
    return service


def _load_root_test_status(path: Path) -> dict[str, Any]:
    return _load_root_test_status_with_fallback(path.parent.parent, path)


def _load_root_test_status_with_fallback(root: Path, path: Path) -> dict[str, Any]:
    raw = _load_json(path, default={})
    root_tests = _normalize_root_test_status_payload(
        raw,
        source=_relative_path_text(root, path) or str(path),
    )
    if root_tests["status"] != "unknown":
        return root_tests

    fallback = _find_latest_artifact_payload(
        root,
        [
            Path("reports/runtime_truth_latest.json"),
            Path("reports/remote_cycle_status.json"),
            "reports/runtime_truth_*.json",
            "reports/pipeline_*.json",
            "reports/pipeline_refresh_*.json",
        ],
        extractor=_extract_root_test_status_candidate,
    )
    if fallback is not None:
        return fallback
    return root_tests


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
            default_service_name="jj-live.service",
            source=None,
        )
    if any(
        key in payload
        for key in ("status", "systemctl_state", "active_state", "state", "service_state")
    ):
        return _normalize_service_status_payload(
            payload,
            default_service_name="jj-live.service",
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
            payload = json.loads(scores_path.read_text())
            wallet_count = _extract_wallet_count(payload)
            last_updated = _extract_wallet_last_updated(payload)
        except json.JSONDecodeError:
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


def _load_killed_structural_alpha_lanes() -> set[str]:
    """
    Read reports/research/structural_alpha/structural_alpha_decision.json and
    return the set of lane keys (e.g. {"a6", "b1"}) whose decision is "killed".
    Fail-safe: returns empty set if the file is missing or unreadable, which
    preserves the conservative default of keeping gates active.
    """
    decision_path = ROOT / "reports" / "research" / "structural_alpha" / "structural_alpha_decision.json"
    try:
        with open(decision_path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return set()
    killed: set[str] = set()
    for lane_key in ("a6", "b1"):
        lane = data.get(lane_key) or {}
        if (
            str(lane.get("status") or "").lower() == "killed"
            or str(lane.get("decision") or "").lower() == "killed"
            or str(lane.get("kill_decision") or "").lower() == "killed"
        ):
            killed.add(lane_key)
    return killed


def _build_launch_status(
    *,
    status: dict[str, Any],
    service: dict[str, Any],
    root_tests: dict[str, Any],
    wallet_flow: dict[str, Any],
    a6_gate: dict[str, Any],
    b1_gate: dict[str, Any],
    accounting_reconciliation: dict[str, Any],
) -> dict[str, Any]:
    runtime = status["runtime"]
    flywheel = status["flywheel"]

    blocked_checks: list[str] = []
    blocked_reasons: list[str] = []

    if root_tests["status"] != "passing":
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
    # Respect the formal kill decision for A-6 and B-1. If the kill decision
    # file marks a lane as "killed", that lane no longer blocks launch.
    # Fail-safe: if the file is missing or unreadable, gates remain active.
    _killed_lanes = _load_killed_structural_alpha_lanes()
    if a6_gate["status"] == "blocked" and "a6" not in _killed_lanes:
        blocked_checks.append("a6_gate_blocked")
        blocked_reasons.append(a6_gate["summary"])
    if b1_gate["status"] == "blocked" and "b1" not in _killed_lanes:
        blocked_checks.append("b1_gate_blocked")
        blocked_reasons.append(b1_gate["summary"])
    if flywheel.get("decision") != "deploy":
        blocked_checks.append("flywheel_not_green")
        blocked_reasons.append(
            f"Latest flywheel decision is {flywheel.get('decision') or 'n/a'}."
        )

    fast_flow_restart_ready = (
        root_tests["status"] == "passing"
        and wallet_flow["ready"]
    )

    if root_tests["status"] == "failing":
        next_operator_action = (
            "Merge the root regression repair and rerun `make test` before any restart or deploy."
        )
    elif root_tests["status"] != "passing":
        next_operator_action = (
            "Refresh the root regression status with `make test` before any restart or deploy."
        )
    elif not wallet_flow["ready"]:
        next_operator_action = (
            "Build wallet-flow bootstrap artifacts, confirm readiness, then restart `jj_live` in paper or shadow fast-flow mode."
        )
    elif service["status"] != "running":
        next_operator_action = (
            "Restart `jj_live` in paper or shadow with conservative caps and collect the first closed trades needed for calibration."
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
            "Resolve the remaining blocked checks and collect the first closed trades needed for calibration."
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
    if (
        bankroll_usd is not None
        and jj_state_bankroll_usd is not None
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
            "Service-state drift: jj-live.service is running while launch posture remains blocked; confirm the remote mode is paper or shadow."
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
        if blocker != "jj-live is intentionally stopped while structural alpha integration is completed."
    ]

    if service["status"] == "running" and launch["live_launch_blocked"]:
        blockers.insert(
            0,
            "jj-live.service is currently running on the VPS while launch posture remains blocked; treat this as operational drift until the remote mode is reconciled.",
        )
    elif service["status"] != "running":
        blockers.insert(
            0,
            f"jj-live.service is {service['status']} ({service.get('systemctl_state') or 'unknown'}).",
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

    return {
        "path": _relative_path_text(root, path),
        "exists": path.exists(),
        "generated_at": generated_at,
        "age_hours": age_hours,
        "fresh": fresh,
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
            _confidence_rank(item.get("confidence_label")),
            _deploy_rank(item.get("deploy_recommendation")),
            item["generated_at"].timestamp() if isinstance(item.get("generated_at"), datetime) else float("-inf"),
        ),
    )
    return {
        "selected": selected,
        "considered": candidates,
        "selection_reason": "fresh_ranked_selection" if fresh_candidates else "stale_fallback_selection",
    }


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
                "source_age_hours": _float_or_none(wallet_export_summary.get("source_age_hours")),
                "wallet_export_fresh": wallet_export_fresh,
                "wallet_export_freshness_label": str(
                    wallet_export_summary.get("wallet_export_freshness_label")
                    or _freshness_label_for_age_hours(_float_or_none(wallet_export_summary.get("source_age_hours")))
                ),
                "btc_closed_markets": int(_safe_float(wallet_export_summary.get("btc_closed_markets"), 0.0) or 0),
                "btc_closed_net_cashflow_usd": round(
                    _safe_float(wallet_export_summary.get("btc_closed_net_cashflow_usd"), 0.0),
                    4,
                ),
                "btc_open_markets": int(_safe_float(wallet_export_summary.get("btc_open_markets"), 0.0) or 0),
                "non_btc_open_buy_notional_usd": _float_or_none(
                    wallet_export_summary.get("non_btc_open_buy_notional_usd")
                ),
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
        "deploy_recommendation": str(selected.get("deploy_recommendation") or "hold"),
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
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


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

    fund_status = "hold" if fund_blocked else "ready_scale"
    fund_amount = 0 if fund_blocked else 1000
    fund_confidence = "low" if fund_blocked else "medium"

    kalshi_status = "hold" if kalshi_blocking_checks else "ready_test_tranche"
    kalshi_amount = 0 if kalshi_status == "hold" else 100

    next_1000_status = "ready_scale" if fund_status == "ready_scale" else "hold"
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
    execution_summary = _compute_execution_notional_summary(root=root, now=generated_at)
    per_venue_candidate_counts = dict(
        latest_edge_scan.get("per_venue_candidate_counts")
        or {"polymarket": 0, "kalshi": 0, "total": 0}
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
    trade_total = int(runtime.get("total_trades") or 0)
    conversion_rate = (trade_total / candidate_total) if candidate_total > 0 else None

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
    }

    report = {
        "artifact": "state_improvement_report",
        "schema_version": 1,
        "generated_at": generated_at.isoformat(),
        "hourly_budget_progress": hourly_budget_progress,
        "active_thresholds": active_thresholds,
        "per_venue_candidate_counts": per_venue_candidate_counts,
        "per_venue_executed_notional_usd": dict(execution_summary.get("per_venue_notional_usd") or {}),
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
            "public_performance_scoreboard": public_performance_scoreboard,
            "performance_split": public_performance_scoreboard.get("performance_split") or {},
            "wallet_reconciliation_summary": public_performance_scoreboard.get("wallet_reconciliation_summary") or {},
            "portfolio_equity_delta_1d": _float_or_none(public_performance_scoreboard.get("portfolio_equity_delta_1d")),
            "closed_cashflow_delta_1d": _float_or_none(public_performance_scoreboard.get("closed_cashflow_delta_1d")),
            "open_notional_delta_1d": _float_or_none(public_performance_scoreboard.get("open_notional_delta_1d")),
            "capital_addition_readiness": capital_addition_readiness,
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


def _compute_execution_notional_summary(*, root: Path, now: datetime) -> dict[str, Any]:
    db_path = root / DEFAULT_TRADES_DB_PATH
    if not db_path.exists():
        return {
            "hourly_notional_usd": 0.0,
            "per_venue_notional_usd": {
                "polymarket_hourly": 0.0,
                "kalshi_hourly": 0.0,
                "polymarket_total": 0.0,
                "kalshi_total": 0.0,
                "combined_hourly": 0.0,
                "combined_total": 0.0,
            },
            "source": "missing_data/jj_trades.db",
        }

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
                "per_venue_notional_usd": {
                    "polymarket_hourly": 0.0,
                    "kalshi_hourly": 0.0,
                    "polymarket_total": 0.0,
                    "kalshi_total": 0.0,
                    "combined_hourly": 0.0,
                    "combined_total": 0.0,
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
            "per_venue_notional_usd": {
                "polymarket_hourly": 0.0,
                "kalshi_hourly": 0.0,
                "polymarket_total": 0.0,
                "kalshi_total": 0.0,
                "combined_hourly": 0.0,
                "combined_total": 0.0,
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

        parsed_ts = _parse_trade_timestamp(timestamp_value)
        if parsed_ts is not None and parsed_ts >= one_hour_ago:
            totals[f"{venue}_hourly"] += size

    combined_hourly = totals["polymarket_hourly"] + totals["kalshi_hourly"]
    combined_total = totals["polymarket_total"] + totals["kalshi_total"]
    return {
        "hourly_notional_usd": round(combined_hourly, 6),
        "per_venue_notional_usd": {
            **{k: round(v, 6) for k, v in totals.items()},
            "combined_hourly": round(combined_hourly, 6),
            "combined_total": round(combined_total, 6),
        },
        "source": "data/jj_trades.db",
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
    candidate_counts = report.get("per_venue_candidate_counts") or {}
    notional = report.get("per_venue_executed_notional_usd") or {}
    thresholds = report.get("active_thresholds") or {}
    budget = report.get("hourly_budget_progress") or {}
    deltas = (report.get("improvement_velocity") or {}).get("deltas") or {}
    reconciliation = report.get("reconciliation_summary") or {}
    open_mismatch = reconciliation.get("unmatched_open_positions") or {}
    closed_mismatch = reconciliation.get("unmatched_closed_positions") or {}
    status_text = "blocked" if launch.get("live_launch_blocked") else "unblocked"
    return (
        "Cycle state: "
        f"launch is {status_text}; "
        f"active thresholds YES={thresholds.get('yes_threshold')} NO={thresholds.get('no_threshold')} "
        f"(max_resolution_hours={thresholds.get('max_resolution_hours')}). "
        f"Candidates PM={candidate_counts.get('polymarket', 0)}, Kalshi={candidate_counts.get('kalshi', 0)}, "
        f"total={candidate_counts.get('total', 0)}. "
        f"Executed notional (last 60m) PM=${float(notional.get('polymarket_hourly') or 0.0):.2f}, "
        f"Kalshi=${float(notional.get('kalshi_hourly') or 0.0):.2f}, "
        f"combined=${float(notional.get('combined_hourly') or 0.0):.2f}. "
        f"Hourly budget used=${float(budget.get('used_usd') or 0.0):.2f}"
        + (
            f" of ${float(budget.get('cap_usd')):.2f} ({float(budget.get('progress_pct')):.2f}%). "
            if budget.get("cap_usd") is not None and budget.get("progress_pct") is not None
            else ". "
        )
        + "Improvement deltas: "
        f"edge_reachability={_format_signed_number(deltas.get('edge_reachability_delta'))}, "
        f"candidate_to_trade_conversion={_format_signed_number(deltas.get('candidate_to_trade_conversion_delta'))}, "
        f"realized_expected_pnl_drift_usd={_format_signed_number(deltas.get('realized_expected_pnl_drift_delta_usd'))}. "
        + "Reconciliation: "
        + (
            "drift detected"
            if reconciliation.get("drift_detected")
            else "reconciled"
        )
        + (
            f" (open delta={int(open_mismatch.get('delta_remote_minus_local') or 0):+d}, "
            f"closed delta={int(closed_mismatch.get('delta_remote_minus_local') or 0):+d}, "
            f"capital delta={_format_money(_safe_float(reconciliation.get('capital_accounting_delta_usd'), 0.0))})."
        )
    )


def _format_signed_number(value: Any) -> str:
    if value in (None, ""):
        return "n/a"
    number = float(value)
    if number > 0:
        return f"+{number:.6f}"
    return f"{number:.6f}"


def _render_state_improvement_digest_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# State Improvement Digest",
        "",
        f"- Generated: {report.get('generated_at') or 'unknown'}",
        "",
        "## Operator Summary",
        "",
        str(report.get("operator_digest") or "No operator digest available."),
        "",
        "## Structured Fields",
        "",
        "```json",
        json.dumps(report, indent=2, sort_keys=True),
        "```",
        "",
    ]
    return "\n".join(lines)


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
        }

    latest_path = max(candidates, key=_artifact_sort_key)
    payload = _load_json(latest_path, default={})
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
    headlines: list[str] = []
    if drift.get("service_running_while_launch_blocked"):
        headlines.append(
            "jj-live.service is running while launch posture remains blocked; treat this as drift until the remote mode is reconciled."
        )
    if wallet_flow.get("ready"):
        headlines.append("Wallet-flow bootstrap is ready.")
    else:
        headlines.append(
            "Wallet-flow bootstrap is not ready: "
            + ", ".join(wallet_flow.get("reasons") or ["unknown"])
        )
    headlines.append(
        f"Latest root verification status is {verification['status']} ({verification['summary']})."
    )
    if launch.get("live_launch_blocked"):
        headlines.append("Launch posture remains blocked.")
    elif service.get("status") == "running":
        headlines.append("Runtime is unblocked and the service is running.")
    return headlines


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
    candidates = [path for path in reports_dir.glob(pattern) if path.is_file()]
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
    if not path.exists():
        return default
    return json.loads(path.read_text())


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


def _format_optional_float(value: Any) -> str:
    if value in (None, ""):
        return "n/a"
    return f"{float(value):.4f}"


def _format_optional_pct(value: Any) -> str:
    if value in (None, ""):
        return "n/a"
    return f"{float(value) * 100.0:.2f}%"


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
