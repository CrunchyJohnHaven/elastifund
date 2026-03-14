"""Cross-asset history coverage, vendor flags, and vendor ranking helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
import sqlite3
from pathlib import Path
from typing import Any


ASSET_ORDER = ("BTC", "ETH", "SOL", "XRP", "DOGE")
INTERVAL_ORDER = ("1s", "1m")

ASSET_CONFIG: dict[str, dict[str, str]] = {
    "BTC": {
        "binance_symbol": "BTCUSDT",
        "coinbase_product": "BTC-USD",
        "coingecko_id": "bitcoin",
        "coinapi_symbol": "BINANCE_SPOT_BTC_USDT",
        "glassnode_asset": "BTC",
    },
    "ETH": {
        "binance_symbol": "ETHUSDT",
        "coinbase_product": "ETH-USD",
        "coingecko_id": "ethereum",
        "coinapi_symbol": "BINANCE_SPOT_ETH_USDT",
        "glassnode_asset": "ETH",
    },
    "SOL": {
        "binance_symbol": "SOLUSDT",
        "coinbase_product": "SOL-USD",
        "coingecko_id": "solana",
        "coinapi_symbol": "BINANCE_SPOT_SOL_USDT",
        "glassnode_asset": "SOL",
    },
    "XRP": {
        "binance_symbol": "XRPUSDT",
        "coinbase_product": "XRP-USD",
        "coingecko_id": "ripple",
        "coinapi_symbol": "BINANCE_SPOT_XRP_USDT",
        "glassnode_asset": "XRP",
    },
    "DOGE": {
        "binance_symbol": "DOGEUSDT",
        "coinbase_product": "DOGE-USD",
        "coingecko_id": "dogecoin",
        "coinapi_symbol": "BINANCE_SPOT_DOGE_USDT",
        "glassnode_asset": "DOGE",
    },
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return int(raw)


def env_text(name: str, default: str = "") -> str:
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = raw.strip()
    return value if value else default


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def env_flag_state(flags: "FeatureFlags", feature_flag_env: str) -> bool:
    mapping = {
        "ELASTIFUND_COINGECKO_ENABLED": flags.coingecko_enabled,
        "ELASTIFUND_COINAPI_ENABLED": flags.coinapi_enabled,
        "ELASTIFUND_GLASSNODE_ENABLED": flags.glassnode_enabled,
        "ELASTIFUND_NANSEN_ENABLED": flags.nansen_enabled,
    }
    return bool(mapping.get(feature_flag_env, False))


@dataclass(frozen=True)
class FeatureFlags:
    coingecko_enabled: bool
    coinapi_enabled: bool
    glassnode_enabled: bool
    nansen_enabled: bool
    auto_buy_coinapi: bool
    backfill_days: int

    @classmethod
    def from_env(cls) -> "FeatureFlags":
        return cls(
            coingecko_enabled=env_bool("ELASTIFUND_COINGECKO_ENABLED", True),
            coinapi_enabled=env_bool("ELASTIFUND_COINAPI_ENABLED", False),
            glassnode_enabled=env_bool("ELASTIFUND_GLASSNODE_ENABLED", False),
            nansen_enabled=env_bool("ELASTIFUND_NANSEN_ENABLED", False),
            auto_buy_coinapi=env_bool("ELASTIFUND_AUTO_BUY_COINAPI_STARTUP", True),
            backfill_days=max(30, min(90, env_int("ELASTIFUND_CROSS_ASSET_BACKFILL_DAYS", 30))),
        )


class VendorAdapter:
    vendor = ""
    implementation_status = "implemented"
    feature_flag_env = ""
    api_key_env = ""

    def __init__(self, flags: FeatureFlags):
        self.flags = flags

    @property
    def enabled(self) -> bool:
        return bool(self.feature_flag_env) and env_flag_state(self.flags, self.feature_flag_env)

    @property
    def configured(self) -> bool:
        if not self.api_key_env:
            return True
        return bool(env_text(self.api_key_env))

    def describe(self) -> dict[str, Any]:
        return {
            "vendor": self.vendor,
            "feature_flag_env": self.feature_flag_env or None,
            "enabled": self.enabled,
            "api_key_env": self.api_key_env or None,
            "configured": self.configured,
            "implementation_status": self.implementation_status,
        }


class CoinGeckoAdapter(VendorAdapter):
    vendor = "coingecko"
    feature_flag_env = "ELASTIFUND_COINGECKO_ENABLED"
    api_key_env = "COINGECKO_API_KEY"

    def build_history_request(self, *, asset: str, days: int) -> dict[str, Any]:
        asset_id = ASSET_CONFIG[asset]["coingecko_id"]
        return {
            "method": "GET",
            "url": f"https://api.coingecko.com/api/v3/coins/{asset_id}/market_chart/range",
            "query": {
                "vs_currency": "usd",
                "days": days,
            },
            "headers": {"x-cg-demo-api-key": env_text(self.api_key_env)},
        }


class CoinAPIAdapter(VendorAdapter):
    vendor = "coinapi"
    feature_flag_env = "ELASTIFUND_COINAPI_ENABLED"
    api_key_env = "COINAPI_KEY"

    def build_history_request(self, *, asset: str, interval: str, time_start: str, time_end: str) -> dict[str, Any]:
        symbol_id = ASSET_CONFIG[asset]["coinapi_symbol"]
        period_id = "1SEC" if interval == "1s" else "1MIN"
        return {
            "method": "GET",
            "url": f"https://rest.coinapi.io/v1/ohlcv/{symbol_id}/history",
            "query": {
                "period_id": period_id,
                "time_start": time_start,
                "time_end": time_end,
                "limit": 100000,
            },
            "headers": {"X-CoinAPI-Key": env_text(self.api_key_env)},
        }


class GlassnodeStubAdapter(VendorAdapter):
    vendor = "glassnode"
    feature_flag_env = "ELASTIFUND_GLASSNODE_ENABLED"
    api_key_env = "GLASSNODE_API_KEY"
    implementation_status = "stub"


class NansenStubAdapter(VendorAdapter):
    vendor = "nansen"
    feature_flag_env = "ELASTIFUND_NANSEN_ENABLED"
    api_key_env = "NANSEN_API_KEY"
    implementation_status = "stub"


def adapter_matrix(flags: FeatureFlags) -> list[dict[str, Any]]:
    adapters: list[VendorAdapter] = [
        CoinGeckoAdapter(flags),
        CoinAPIAdapter(flags),
        GlassnodeStubAdapter(flags),
        NansenStubAdapter(flags),
    ]
    return [adapter.describe() for adapter in adapters]


def ensure_history_store(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reference_bars (
                venue TEXT NOT NULL,
                asset TEXT NOT NULL,
                interval TEXT NOT NULL,
                open_time_ms INTEGER NOT NULL,
                close_time_ms INTEGER NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL NOT NULL,
                source TEXT NOT NULL,
                inserted_at TEXT NOT NULL,
                PRIMARY KEY (venue, asset, interval, open_time_ms)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS backfill_runs (
                run_id TEXT PRIMARY KEY,
                generated_at TEXT NOT NULL,
                requested_days INTEGER NOT NULL,
                notes_json TEXT NOT NULL
            )
            """
        )


def insert_reference_bars(path: Path, bars: list[dict[str, Any]]) -> int:
    if not bars:
        return 0
    with sqlite3.connect(path) as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO reference_bars (
                venue,
                asset,
                interval,
                open_time_ms,
                close_time_ms,
                open,
                high,
                low,
                close,
                volume,
                source,
                inserted_at
            ) VALUES (
                :venue,
                :asset,
                :interval,
                :open_time_ms,
                :close_time_ms,
                :open,
                :high,
                :low,
                :close,
                :volume,
                :source,
                :inserted_at
            )
            """,
            bars,
        )
    return len(bars)


def record_backfill_run(path: Path, *, run_id: str, requested_days: int, notes: dict[str, Any]) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO backfill_runs (run_id, generated_at, requested_days, notes_json)
            VALUES (?, ?, ?, ?)
            """,
            (run_id, utc_now(), requested_days, json.dumps(notes, sort_keys=True)),
        )


def summarize_history_store(path: Path, *, assets: tuple[str, ...] = ASSET_ORDER) -> dict[str, Any]:
    coverage_rows: list[dict[str, Any]] = []
    if not path.exists():
        for asset in assets:
            coverage_rows.append(
                {
                    "asset": asset,
                    "intervals": {
                        "1m": {
                            "status": "missing",
                            "row_count": 0,
                            "first_open_time_ms": None,
                            "last_open_time_ms": None,
                            "venues": [],
                        },
                        "1s": {
                            "status": "missing",
                            "row_count": 0,
                            "first_open_time_ms": None,
                            "last_open_time_ms": None,
                            "venues": [],
                        },
                    },
                }
            )
        return {
            "assets": coverage_rows,
            "complete_assets_1m": 0,
            "complete_assets_1s": 0,
            "missing_assets_1m": list(assets),
            "missing_assets_1s": list(assets),
        }

    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT
                asset,
                interval,
                COUNT(*) AS row_count,
                MIN(open_time_ms) AS first_open_time_ms,
                MAX(open_time_ms) AS last_open_time_ms,
                GROUP_CONCAT(DISTINCT venue) AS venues
            FROM reference_bars
            GROUP BY asset, interval
            """
        ).fetchall()

    by_asset_interval: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        asset = str(row["asset"])
        interval = str(row["interval"])
        by_asset_interval[(asset, interval)] = {
            "status": "ready" if int(row["row_count"]) > 0 else "missing",
            "row_count": int(row["row_count"]),
            "first_open_time_ms": row["first_open_time_ms"],
            "last_open_time_ms": row["last_open_time_ms"],
            "venues": sorted(
                value.strip()
                for value in str(row["venues"] or "").split(",")
                if value and value.strip()
            ),
        }

    complete_assets_1m = 0
    complete_assets_1s = 0
    missing_assets_1m: list[str] = []
    missing_assets_1s: list[str] = []
    for asset in assets:
        intervals: dict[str, dict[str, Any]] = {}
        for interval in INTERVAL_ORDER:
            item = by_asset_interval.get(
                (asset, interval),
                {
                    "status": "missing",
                    "row_count": 0,
                    "first_open_time_ms": None,
                    "last_open_time_ms": None,
                    "venues": [],
                },
            )
            intervals[interval] = item
        if intervals["1m"]["status"] == "ready":
            complete_assets_1m += 1
        else:
            missing_assets_1m.append(asset)
        if intervals["1s"]["status"] == "ready":
            complete_assets_1s += 1
        else:
            missing_assets_1s.append(asset)
        coverage_rows.append({"asset": asset, "intervals": intervals})

    return {
        "assets": coverage_rows,
        "complete_assets_1m": complete_assets_1m,
        "complete_assets_1s": complete_assets_1s,
        "missing_assets_1m": missing_assets_1m,
        "missing_assets_1s": missing_assets_1s,
    }


def queued_monthly_commitments(action_queue: dict[str, Any]) -> float:
    total = 0.0
    for action in action_queue.get("actions") or []:
        if not isinstance(action, dict):
            continue
        status = str(action.get("status") or "").lower()
        if status not in {"queued", "executed"}:
            continue
        total += safe_float(action.get("monthly_commitment_usd"))
    return total


def build_vendor_stack(
    *,
    coverage: dict[str, Any],
    finance_latest: dict[str, Any],
    action_queue: dict[str, Any],
    flags: FeatureFlags,
) -> dict[str, Any]:
    finance_gate_pass = bool(finance_latest.get("finance_gate_pass"))
    finance_gate = finance_latest.get("finance_gate") if isinstance(finance_latest.get("finance_gate"), dict) else {}
    single_action_cap_usd = safe_float(
        (((finance_latest.get("cycle_budget_ledger") or {}).get("dollars") or {}).get("single_action_cap_usd")),
        250.0,
    )
    monthly_cap_usd = safe_float(os.environ.get("JJ_FINANCE_MONTHLY_NEW_COMMITMENT_CAP_USD"), 1000.0)
    current_monthly_commitment_usd = queued_monthly_commitments(action_queue)
    remaining_monthly_capacity_usd = max(0.0, monthly_cap_usd - current_monthly_commitment_usd)
    missing_1s_assets = list(coverage.get("missing_assets_1s") or [])
    missing_1m_assets = list(coverage.get("missing_assets_1m") or [])
    all_1m_ready = not missing_1m_assets
    all_1s_ready = not missing_1s_assets

    vendors: list[dict[str, Any]] = []

    def add_vendor(
        *,
        vendor: str,
        tier: str,
        monthly_commitment_impact_usd: float | None,
        expected_info_gain_score: float,
        expected_arr_lift_bps: int,
        implementation_status: str,
        reason: str,
        buy_eligible: bool,
        transparency: str = "transparent",
    ) -> None:
        monthly = monthly_commitment_impact_usd if monthly_commitment_impact_usd is not None else 0.0
        single_action_cap_hit = monthly_commitment_impact_usd is not None and monthly > single_action_cap_usd
        monthly_cap_hit = monthly_commitment_impact_usd is not None and monthly > remaining_monthly_capacity_usd
        finance_blocked = not finance_gate_pass
        cost_penalty = monthly / max(monthly_cap_usd, 1.0)
        score = round(
            expected_info_gain_score * 0.55
            + (expected_arr_lift_bps / 250.0) * 0.35
            - cost_penalty * 0.15
            - (0.10 if transparency == "opaque" else 0.0),
            4,
        )
        vendors.append(
            {
                "vendor": vendor,
                "tier": tier,
                "monthly_commitment_impact_usd": monthly_commitment_impact_usd,
                "expected_info_gain_score": expected_info_gain_score,
                "expected_arr_lift_bps": expected_arr_lift_bps,
                "score": score,
                "implementation_status": implementation_status,
                "buy_eligible": buy_eligible,
                "single_action_cap_hit": bool(single_action_cap_hit),
                "monthly_cap_hit": bool(monthly_cap_hit),
                "finance_gate_blocked": finance_blocked,
                "transparency": transparency,
                "reason": reason,
            }
        )

    add_vendor(
        vendor="free_stack",
        tier="public_binance_plus_optional_coingecko",
        monthly_commitment_impact_usd=0.0,
        expected_info_gain_score=0.58 if all_1m_ready else 0.45,
        expected_arr_lift_bps=45 if all_1m_ready else 20,
        implementation_status="implemented",
        reason=(
            "Keeps zero recurring spend while covering 1m replay for BTC/ETH/SOL/XRP/DOGE; does not close the 1s gap."
            if all_1m_ready
            else "Still missing 1m coverage on the free stack."
        ),
        buy_eligible=True,
    )
    add_vendor(
        vendor="coinapi",
        tier="startup",
        monthly_commitment_impact_usd=79.0,
        expected_info_gain_score=0.92 if missing_1s_assets else 0.40,
        expected_arr_lift_bps=180 if missing_1s_assets else 35,
        implementation_status="implemented",
        reason=(
            "First paid step because 1s history is missing for "
            + ", ".join(missing_1s_assets)
            + "."
            if missing_1s_assets
            else "1s history gap is already closed; no paid upgrade needed."
        ),
        buy_eligible=flags.auto_buy_coinapi,
    )
    add_vendor(
        vendor="nansen",
        tier="pro_api",
        monthly_commitment_impact_usd=69.0,
        expected_info_gain_score=0.44,
        expected_arr_lift_bps=55,
        implementation_status="stub",
        reason="Useful after the price history lane is stable, but not the first spend for replay-grade 1s data.",
        buy_eligible=False,
    )
    add_vendor(
        vendor="glassnode",
        tier="professional_plus_api_add_on",
        monthly_commitment_impact_usd=999.0,
        expected_info_gain_score=0.52,
        expected_arr_lift_bps=65,
        implementation_status="stub",
        reason="Institutional-grade on-chain and market metrics, but API access requires Professional plus add-on and breaches the default spend cap.",
        buy_eligible=False,
        transparency="partial",
    )
    add_vendor(
        vendor="kaiko",
        tier="contact_sales",
        monthly_commitment_impact_usd=None,
        expected_info_gain_score=0.61,
        expected_arr_lift_bps=90,
        implementation_status="deferred",
        reason="Deferred by policy until the free stack and CoinAPI prove an information gap.",
        buy_eligible=False,
        transparency="opaque",
    )
    add_vendor(
        vendor="amberdata",
        tier="contact_sales",
        monthly_commitment_impact_usd=None,
        expected_info_gain_score=0.60,
        expected_arr_lift_bps=85,
        implementation_status="deferred",
        reason="Deferred by policy until the cheaper stack proves insufficient.",
        buy_eligible=False,
        transparency="opaque",
    )

    vendors.sort(key=lambda item: float(item["score"]), reverse=True)

    recommendation = "hold_free_stack"
    recommendation_reason = "1m history is not ready yet; fix the free stack first."
    monthly_commitment_impact_usd = 0.0
    block_reasons: list[str] = []
    chosen_vendor = "free_stack"

    if missing_1m_assets:
        block_reasons.append("1m_history_incomplete")
    if missing_1s_assets:
        block_reasons.append("1s_history_missing_on_free_stack")

    coinapi = next((item for item in vendors if item["vendor"] == "coinapi"), None)
    if coinapi is not None and missing_1s_assets:
        if not finance_gate_pass:
            block_reasons.append(f"finance_gate_blocked:{finance_gate.get('reason') or 'unknown'}")
        elif bool(coinapi["single_action_cap_hit"]):
            block_reasons.append("coinapi_exceeds_single_action_cap")
        elif bool(coinapi["monthly_cap_hit"]):
            block_reasons.append("coinapi_exceeds_monthly_commitment_cap")
        elif flags.auto_buy_coinapi and all_1m_ready:
            recommendation = "buy_coinapi_startup"
            recommendation_reason = (
                "Buy CoinAPI Startup because 1m replay is already covered and the only critical remaining gap is 1s history."
            )
            monthly_commitment_impact_usd = safe_float(coinapi["monthly_commitment_impact_usd"])
            chosen_vendor = "coinapi"
        else:
            recommendation = "hold_free_stack"
            recommendation_reason = (
                "Keep the free stack until 1m replay is complete or automatic spend is disabled."
            )

    recommended_row = next(item for item in vendors if item["vendor"] == chosen_vendor)
    recommended_row = dict(recommended_row)
    recommended_row["decision"] = recommendation
    recommended_row["decision_reason"] = recommendation_reason

    return {
        "schema_version": "vendor_stack.v1",
        "generated_at": utc_now(),
        "finance_gate_pass": finance_gate_pass,
        "finance_gate_reason": finance_gate.get("reason") or ("pass" if finance_gate_pass else "unknown"),
        "missing_1m_assets": missing_1m_assets,
        "missing_1s_assets": missing_1s_assets,
        "current_monthly_commitment_usd": current_monthly_commitment_usd,
        "monthly_cap_usd": monthly_cap_usd,
        "remaining_monthly_capacity_usd": remaining_monthly_capacity_usd,
        "single_action_cap_usd": single_action_cap_usd,
        "vendors": vendors,
        "recommendation": recommendation,
        "recommendation_reason": recommendation_reason,
        "recommended_vendor": recommended_row,
        "monthly_commitment_impact_usd": monthly_commitment_impact_usd,
        "block_reasons": block_reasons,
    }


def one_second_coverage_by_asset(coverage: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = coverage.get("assets") if isinstance(coverage.get("assets"), list) else []
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        asset = str(row.get("asset") or "").upper()
        if not asset:
            continue
        intervals = row.get("intervals") if isinstance(row.get("intervals"), dict) else {}
        one_second = intervals.get("1s") if isinstance(intervals.get("1s"), dict) else {}
        result[asset] = {
            "status": str(one_second.get("status") or "missing"),
            "row_count": int(one_second.get("row_count") or 0),
            "first_open_time_ms": one_second.get("first_open_time_ms"),
            "last_open_time_ms": one_second.get("last_open_time_ms"),
            "venues": list(one_second.get("venues") or []),
        }
    for asset in ASSET_ORDER:
        result.setdefault(
            asset,
            {
                "status": "missing",
                "row_count": 0,
                "first_open_time_ms": None,
                "last_open_time_ms": None,
                "venues": [],
            },
        )
    return result


def coinapi_ready(flags: FeatureFlags) -> bool:
    return flags.coinapi_enabled and bool(env_text("COINAPI_KEY"))


def coinapi_subscription_present(finance_latest: dict[str, Any], action_queue: dict[str, Any]) -> bool:
    target_key = "subscribe::coinapi_startup"
    for action in action_queue.get("actions") or []:
        if not isinstance(action, dict):
            continue
        action_key = str(action.get("action_key") or "")
        vendor = str(action.get("vendor") or "").strip().lower()
        status = str(action.get("status") or "").strip().lower()
        if action_key == target_key and status in {"queued", "shadowed", "executed"}:
            return True
        if "coinapi" in vendor and status in {"active", "queued", "shadowed", "executed"}:
            return True

    def _contains_coinapi(node: Any) -> bool:
        if isinstance(node, dict):
            for key, value in node.items():
                if "coinapi" in str(key).lower():
                    return True
                if _contains_coinapi(value):
                    return True
            return False
        if isinstance(node, list):
            return any(_contains_coinapi(item) for item in node)
        return "coinapi" in str(node).lower() if isinstance(node, str) else False

    return _contains_coinapi(finance_latest)


def build_coinapi_subscription_action(vendor_stack: dict[str, Any]) -> dict[str, Any]:
    monthly_commitment_usd = safe_float(vendor_stack.get("monthly_commitment_impact_usd"), 79.0)
    recommendation_reason = str(vendor_stack.get("recommendation_reason") or "")
    return {
        "action_key": "subscribe::coinapi_startup",
        "action_type": "buy_tool_or_data",
        "amount_usd": monthly_commitment_usd,
        "bucket": "buy_tool_or_data",
        "cooldown_until": None,
        "destination": "coinapi_startup",
        "executed_at": None,
        "idempotency_key": "subscribe::coinapi_startup",
        "metadata": {
            "expected_arr_lift_bps": 180,
            "source": "reports/instance3_vendor_backfill/latest.json",
            "vendor_dispatch_recommendation": str(vendor_stack.get("recommendation") or ""),
        },
        "mode_requested": "live_spend",
        "monthly_commitment_usd": monthly_commitment_usd,
        "priority_score": 180.0,
        "reason": recommendation_reason or "Queue CoinAPI Startup because 1-second replay coverage is missing.",
        "requires_whitelist": False,
        "rollback": "Cancel the subscription if 1-second replay coverage stays unused or finance gating turns red.",
        "status": "queued",
        "title": "Subscribe to CoinAPI Startup",
        "updated_at": utc_now(),
        "vendor": "CoinAPI",
    }


def emit_finance_action_queue(
    *,
    action_queue: dict[str, Any],
    finance_latest: dict[str, Any],
    vendor_stack: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    actions = [item for item in (action_queue.get("actions") or []) if isinstance(item, dict)]
    emitted = False
    action_key = "subscribe::coinapi_startup"
    finance_gate_pass = bool(finance_latest.get("finance_gate_pass"))
    subscription_present = coinapi_subscription_present(finance_latest, action_queue)
    should_emit = (
        vendor_stack.get("recommendation") == "buy_coinapi_startup"
        and finance_gate_pass
        and not subscription_present
    )

    if should_emit:
        action = build_coinapi_subscription_action(vendor_stack)
        actions = [item for item in actions if str(item.get("action_key") or "") != action_key]
        actions.append(action)
        emitted = True

    summary = {
        "queued": sum(1 for action in actions if str(action.get("status") or "").lower() == "queued"),
        "shadowed": sum(1 for action in actions if str(action.get("status") or "").lower() == "shadowed"),
        "executed": sum(1 for action in actions if str(action.get("status") or "").lower() == "executed"),
        "rejected": sum(1 for action in actions if str(action.get("status") or "").lower() == "rejected"),
    }
    updated_queue = {
        "schema_version": "finance_action_queue.v1",
        "generated_at": utc_now(),
        "summary": summary,
        "actions": actions,
    }
    return updated_queue, {
        "emitted": emitted,
        "action_key": action_key if should_emit else None,
        "subscription_present": subscription_present,
        "finance_gate_pass": finance_gate_pass,
    }


def build_instance_artifact(
    *,
    coverage: dict[str, Any],
    vendor_stack: dict[str, Any],
    finance_latest: dict[str, Any],
    state_improvement: dict[str, Any],
) -> dict[str, Any]:
    recommended = vendor_stack.get("recommended_vendor") if isinstance(vendor_stack.get("recommended_vendor"), dict) else {}
    coverage_1s = one_second_coverage_by_asset(coverage)
    one_second_complete = all(int(item.get("row_count") or 0) > 0 for item in coverage_1s.values())
    block_reasons = [] if one_second_complete else ["coinapi_not_enabled_or_not_configured"]

    return {
        "schema_version": "instance3_vendor_backfill.v1",
        "generated_at": utc_now(),
        "candidate_delta_arr_bps": int(recommended.get("expected_arr_lift_bps") or 180),
        "expected_improvement_velocity_delta": 0.20,
        "arr_confidence_score": 0.76,
        "block_reasons": block_reasons,
        "finance_gate_pass": bool(finance_latest.get("finance_gate_pass")),
        "one_next_cycle_action": "Enable 1-second replay mode for Instance 5 when coverage is complete.",
        "details": {
            "recommendation": vendor_stack.get("recommendation"),
            "recommendation_reason": vendor_stack.get("recommendation_reason"),
            "recommended_vendor": recommended,
            "history_coverage": {
                "complete_assets_1m": coverage.get("complete_assets_1m"),
                "complete_assets_1s": coverage.get("complete_assets_1s"),
                "missing_assets_1m": coverage.get("missing_assets_1m"),
                "missing_assets_1s": coverage.get("missing_assets_1s"),
            },
            "one_second_coverage_by_asset": coverage_1s,
            "coinapi_enabled": bool(state_improvement.get("coinapi_enabled")),
            "coinapi_configured": bool(state_improvement.get("coinapi_configured")),
        },
    }
