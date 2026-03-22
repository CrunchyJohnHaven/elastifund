"""Constants used by scripts/write_remote_cycle_status.py."""

from __future__ import annotations

import re
from pathlib import Path

DEFAULT_CONFIG_PATH = Path("config/remote_cycle_status.json")
DEFAULT_MARKDOWN_PATH = Path("reports/remote_cycle_status.md")
DEFAULT_JSON_PATH = Path("reports/remote_cycle_status.json")
DEFAULT_RUNTIME_TRUTH_LATEST_PATH = Path("reports/runtime_truth_latest.json")
DEFAULT_RUNTIME_TRUTH_HISTORY_DIR = Path("reports/runtime/runtime_truth")
DEFAULT_PUBLIC_RUNTIME_SNAPSHOT_PATH = Path("reports/public_runtime_snapshot.json")
DEFAULT_TRADE_PROOF_LATEST_PATH = Path("reports/trade_proof/latest.json")
DEFAULT_LAUNCH_PACKET_LATEST_PATH = Path("reports/launch_packet_latest.json")
DEFAULT_LAUNCH_PACKET_HISTORY_DIR = Path("reports/runtime/launch_packets")
DEFAULT_STATE_IMPROVEMENT_LATEST_PATH = Path("reports/state_improvement_latest.json")
DEFAULT_STATE_IMPROVEMENT_DIGEST_PATH = Path("reports/state_improvement_digest.md")
DEFAULT_STATE_IMPROVEMENT_HISTORY_DIR = Path("reports/runtime/state_improvement")
DEFAULT_RUNTIME_MODE_RECONCILIATION_HISTORY_DIR = Path("reports/runtime/reconciliation")
DEFAULT_SERVICE_STATUS_PATH = Path("reports/remote_service_status.json")
DEFAULT_ROOT_TEST_STATUS_PATH = Path("reports/root_test_status.json")
DEFAULT_ARB_STATUS_PATH = Path("reports/arb_empirical_snapshot.json")
DEFAULT_FINANCE_LATEST_PATH = Path("reports/finance/latest.json")
DEFAULT_ENV_PATH = Path(".env")
DEFAULT_ENV_EXAMPLE_PATH = Path(".env.example")
DEFAULT_RUNTIME_OPERATOR_OVERRIDES_PATH = Path("reports/runtime_operator_overrides.env")
DEFAULT_RUNTIME_PROFILE_EFFECTIVE_PATH = Path("reports/runtime_profile_effective.json")
DEFAULT_WALLET_SCORES_PATH = Path("data/smart_wallets.json")
DEFAULT_WALLET_DB_PATH = Path("data/wallet_scores.db")
DEFAULT_TRADES_DB_PATH = Path("data/jj_trades.db")
DEFAULT_BTC5_DB_PATH = Path("data/btc_5min_maker.db")
DEFAULT_BTC5_WINDOW_ROWS_PATH = Path("reports/tmp_remote_btc5_window_rows.json")
DEFAULT_FAST_MARKET_SEARCH_LATEST_PATH = Path("reports/fast_market_search/latest.json")
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
    "JJ_FORCE_LIVE_ATTEMPT",
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
PRIMARY_RUNTIME_SERVICE_NAME = "btc-5min-maker.service"
WALLET_PROBE_SCRIPT = """import json
import logging
import os

from py_clob_client.clob_types import AssetType, BalanceAllowanceParams

from bot.polymarket_clob import build_authenticated_clob_client, parse_signature_type


def _clean(value):
    return str(value or "").strip().strip('"').strip("'").strip()


pk = _clean(os.environ.get("POLY_PRIVATE_KEY") or os.environ.get("PRIVATE_KEY") or os.environ.get("POLYMARKET_PK") or "")
maker = _clean(os.environ.get("POLY_SAFE_ADDRESS") or os.environ.get("POLYMARKET_FUNDER") or "")
sig = parse_signature_type(os.environ.get("JJ_CLOB_SIGNATURE_TYPE", "1"), default=1)

logger = logging.getLogger("wallet_probe")
logger.setLevel(logging.ERROR)
client, selected_signature_type, signature_probes = build_authenticated_clob_client(
    private_key=pk,
    safe_address=maker,
    configured_signature_type=sig,
    logger=logger,
    log_prefix="wallet_probe",
)
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
    BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=selected_signature_type)
)
print(
    json.dumps(
        {
            "maker_address": maker,
            "signature_type": selected_signature_type,
            "signature_probes": signature_probes,
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
recent_window_rows = conn.execute(
    \"\"\"
    SELECT
        id,
        window_start_ts,
        slug,
        direction,
        delta,
        ABS(delta) AS abs_delta,
        order_price,
        trade_size_usd,
        shares,
        filled,
        order_status,
        pnl_usd,
        created_at,
        updated_at
    FROM window_trades
    ORDER BY id DESC
    LIMIT 200
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
    "recent_window_rows": [dict(row) for row in recent_window_rows],
    "guardrail_recommendation": recommend_guardrails(all_live_filled),
    "fill_attribution": summarize_fill_attribution(all_live_filled),
}, sort_keys=True))
"""
