"""Refresh live Polymarket market-universe metrics for the fast-trade report."""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sqlite3
from typing import Any
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = REPO_ROOT / "reports"
DATA_PULLS_DIR = REPO_ROOT / "data" / "pulls"
CURRENT_PROFILE_PATH = REPO_ROOT / "config" / "runtime_profiles" / "blocked_safe.json"
PUBLIC_RUNTIME_PATH = REPORTS_DIR / "public_runtime_snapshot.json"
RUNTIME_TRUTH_PATH = REPORTS_DIR / "runtime_truth_latest.json"
ARB_SNAPSHOT_PATH = REPORTS_DIR / "arb_empirical_snapshot.json"

INSTANCE_VERSION = "2.8.0"
DEFAULT_PLATT_A = 0.5914
DEFAULT_PLATT_B = -0.3977
DEFAULT_CATEGORY_PRIORITIES = {
    "politics": 3,
    "weather": 3,
    "economic": 2,
    "crypto": 0,
    "sports": 0,
    "other": 0,
}
AGGRESSIVE_THRESHOLDS = {"yes": 0.08, "no": 0.03, "min_category_priority": 0}
WIDE_OPEN_THRESHOLDS = {"yes": 0.05, "no": 0.02, "min_category_priority": 0}
CATEGORY_DISPLAY_ORDER = ["politics", "weather", "economic", "crypto", "sports", "other"]
TAG_CATEGORY_MAP = {
    "politics": "politics",
    "political": "politics",
    "election": "politics",
    "elections": "politics",
    "government": "politics",
    "congress": "politics",
    "senate": "politics",
    "house": "politics",
    "president": "politics",
    "white-house": "politics",
    "geopolitics": "politics",
    "geopolitical": "politics",
    "world": "politics",
    "ukraine": "politics",
    "middle-east": "politics",
    "weather": "weather",
    "climate": "weather",
    "storm": "weather",
    "hurricane": "weather",
    "snow": "weather",
    "temperature": "weather",
    "economy": "economic",
    "economic": "economic",
    "finance": "economic",
    "business": "economic",
    "fed": "economic",
    "stocks": "economic",
    "stock-market": "economic",
    "tech": "economic",
    "earnings": "economic",
    "crypto": "crypto",
    "bitcoin": "crypto",
    "ethereum": "crypto",
    "solana": "crypto",
    "exchange": "crypto",
    "sports": "sports",
    "nba": "sports",
    "nfl": "sports",
    "mlb": "sports",
    "nhl": "sports",
    "soccer": "sports",
    "tennis": "sports",
    "golf": "sports",
}
QUESTION_KEYWORDS = {
    "weather": ("temperature", "snow", "rain", "storm", "hurricane", "weather"),
    "politics": (
        "election",
        "president",
        "senate",
        "congress",
        "parliament",
        "prime minister",
        "government",
        "cabinet",
        "ceasefire",
        "tariff",
    ),
    "crypto": ("bitcoin", "btc", "ethereum", "eth", "solana", "crypto", "coin", "token"),
    "sports": (
        "super bowl",
        "world series",
        "nba",
        "nfl",
        "mlb",
        "nhl",
        "match",
        "tournament",
        "goal",
        "touchdown",
    ),
    "economic": ("cpi", "inflation", "fed", "gdp", "ipo", "earnings", "stock", "economy", "rates"),
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_to_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def fetch_json(url: str) -> Any:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_yes_price(market: dict[str, Any]) -> float | None:
    raw = market.get("outcomePrices")
    values: list[Any]
    if isinstance(raw, str):
        try:
            values = json.loads(raw)
        except json.JSONDecodeError:
            values = []
    elif isinstance(raw, list):
        values = raw
    else:
        values = []
    if len(values) >= 1:
        try:
            price = float(values[0])
            return max(0.0, min(1.0, price))
        except (TypeError, ValueError):
            return None
    try:
        return max(0.0, min(1.0, float(market.get("bestAsk"))))
    except (TypeError, ValueError):
        return None


def round_or_none(value: float | None, digits: int = 4) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def inverse_platt_probability(calibrated_prob: float, a: float, b: float) -> float:
    calibrated = max(0.01, min(0.99, float(calibrated_prob)))
    if abs(calibrated - 0.5) < 1e-9:
        return 0.5
    if calibrated < 0.5:
        return 1.0 - inverse_platt_probability(1.0 - calibrated, a, b)
    if abs(a) < 1e-9:
        return calibrated
    logit_output = math.log(calibrated / (1.0 - calibrated))
    logit_input = (logit_output - b) / a
    raw = 1.0 / (1.0 + math.exp(-logit_input))
    return max(0.001, min(0.999, raw))


def required_probability_window(
    *,
    yes_price: float,
    yes_threshold: float,
    no_threshold: float,
    platt_a: float,
    platt_b: float,
) -> dict[str, float | bool | None]:
    yes_target = yes_price + yes_threshold
    no_target = yes_price - no_threshold
    yes_reachable = yes_target <= 0.99
    no_reachable = no_target >= 0.01
    return {
        "required_calibrated_prob_yes": round_or_none(yes_target if yes_reachable else None),
        "required_raw_prob_yes": (
            round_or_none(inverse_platt_probability(yes_target, platt_a, platt_b))
            if yes_reachable
            else None
        ),
        "max_calibrated_prob_no": round_or_none(no_target if no_reachable else None),
        "max_raw_prob_no": (
            round_or_none(inverse_platt_probability(no_target, platt_a, platt_b))
            if no_reachable
            else None
        ),
        "yes_reachable": yes_reachable,
        "no_reachable": no_reachable,
        "tradeable": yes_reachable or no_reachable,
    }


def classify_category(tags: list[dict[str, Any]], question: str) -> str:
    tag_slugs = []
    for tag in tags:
        slug = str(tag.get("slug") or tag.get("label") or "").strip().lower()
        if slug:
            tag_slugs.append(slug)

    for preferred in ("weather", "politics", "crypto", "sports", "economic"):
        if any(TAG_CATEGORY_MAP.get(slug) == preferred for slug in tag_slugs):
            return preferred

    lowered = question.lower()
    for category, keywords in QUESTION_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return category
    return "other"


def load_current_profile() -> dict[str, Any]:
    payload = load_json(CURRENT_PROFILE_PATH)
    market_filters = payload.get("market_filters", {})
    signal_thresholds = payload.get("signal_thresholds", {})
    category_priorities = {
        "other": 0,
        **DEFAULT_CATEGORY_PRIORITIES,
        **{
            str(key): int(value)
            for key, value in dict(market_filters.get("category_priorities", {})).items()
        },
    }
    return {
        "yes": float(signal_thresholds.get("yes_threshold", 0.15)),
        "no": float(signal_thresholds.get("no_threshold", 0.05)),
        "min_category_priority": int(market_filters.get("min_category_priority", 1)),
        "category_priorities": category_priorities,
    }


def flatten_open_markets(events: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for event in events:
        tags = list(event.get("tags") or [])
        for market in event.get("markets") or []:
            if bool(market.get("closed")):
                continue
            end_dt = iso_to_dt(str(market.get("endDate") or market.get("endDateIso") or ""))
            yes_price = parse_yes_price(market)
            category = classify_category(tags, str(market.get("question") or event.get("title") or ""))
            category_priority = DEFAULT_CATEGORY_PRIORITIES.get(category, 0)
            if category in {"politics", "weather", "economic", "crypto", "sports"}:
                category_priority = DEFAULT_CATEGORY_PRIORITIES[category]
            flattened.append(
                {
                    "id": str(market.get("conditionId") or market.get("id") or ""),
                    "question": str(market.get("question") or event.get("title") or ""),
                    "event_title": str(event.get("title") or ""),
                    "slug": str(market.get("slug") or ""),
                    "category": category,
                    "tags": [str(tag.get("slug") or tag.get("label") or "") for tag in tags],
                    "yes_price": yes_price,
                    "resolution_time": end_dt.isoformat() if end_dt else None,
                    "resolution_hours": (
                        round((end_dt - now).total_seconds() / 3600.0, 4)
                        if end_dt is not None
                        else None
                    ),
                    "accepting_orders": bool(market.get("acceptingOrders", True)),
                    "active": bool(market.get("active", True)),
                    "liquidity": round_or_none(_safe_float(market.get("liquidity") or market.get("liquidityClob"))),
                    "volume": round_or_none(_safe_float(market.get("volume") or market.get("volumeClob"))),
                    "category_priority": category_priority,
                }
            )
    return flattened


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_category_snapshot(markets: list[dict[str, Any]]) -> dict[str, dict[str, float | int | None]]:
    counts = defaultdict(int)
    under_24h = defaultdict(int)
    price_sums = defaultdict(float)
    priced_counts = defaultdict(int)

    for market in markets:
        category = str(market.get("category") or "other")
        counts[category] += 1
        resolution_hours = market.get("resolution_hours")
        if isinstance(resolution_hours, (int, float)) and 0 < float(resolution_hours) <= 24.0:
            under_24h[category] += 1
        yes_price = market.get("yes_price")
        if isinstance(yes_price, (int, float)):
            price_sums[category] += float(yes_price)
            priced_counts[category] += 1

    snapshot: dict[str, dict[str, float | int | None]] = {}
    for category in CATEGORY_DISPLAY_ORDER:
        avg_price = None
        if priced_counts[category] > 0:
            avg_price = round(price_sums[category] / priced_counts[category], 4)
        snapshot[category] = {
            "count": counts[category],
            "avg_yes_price": avg_price,
            "under_24h": under_24h[category],
        }
    return snapshot


def filter_basic_markets(
    markets: list[dict[str, Any]],
    *,
    max_resolution_hours: float = 48.0,
    min_yes_price: float = 0.10,
    max_yes_price: float = 0.90,
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for market in markets:
        resolution_hours = market.get("resolution_hours")
        yes_price = market.get("yes_price")
        if not isinstance(resolution_hours, (int, float)):
            continue
        if float(resolution_hours) <= 0.0 or float(resolution_hours) > max_resolution_hours:
            continue
        if not isinstance(yes_price, (int, float)):
            continue
        if not (min_yes_price <= float(yes_price) <= max_yes_price):
            continue
        filtered.append(market)
    return filtered


def select_threshold_markets(
    markets: list[dict[str, Any]],
    fast_markets: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str]:
    """Prefer the discovered BTC fast-market lane for threshold sensitivity."""
    if fast_markets:
        return fast_markets, "fast_market_discovery"
    return markets, "gamma_events_flattened"


def load_fast_markets(now: datetime) -> list[dict[str, Any]]:
    from .config import load_config
    from .data_pipeline import DataPipeline

    config = load_config()
    pipeline = DataPipeline(config)
    candidate_slugs = pipeline.discover_candidate_slugs(int(now.timestamp()))
    fetched = pipeline.fetch_markets_by_slugs(candidate_slugs)
    normalized: list[dict[str, Any]] = []
    for market in fetched:
        if not pipeline._is_target_market(market):
            continue
        end_dt = iso_to_dt(str(market.get("endDate") or market.get("endDateIso") or ""))
        yes_price = parse_yes_price(market)
        normalized.append(
            {
                "id": str(market.get("conditionId") or market.get("id") or ""),
                "question": str(market.get("question") or ""),
                "slug": str(market.get("slug") or ""),
                "category": "crypto",
                "yes_price": yes_price,
                "resolution_time": end_dt.isoformat() if end_dt else None,
                "resolution_hours": (
                    round((end_dt - now).total_seconds() / 3600.0, 4)
                    if end_dt is not None
                    else None
                ),
                "accepting_orders": bool(market.get("acceptingOrders", True)),
                "active": bool(market.get("active", True)),
                "liquidity": round_or_none(_safe_float(market.get("liquidity") or market.get("liquidityClob"))),
                "volume": round_or_none(_safe_float(market.get("volume") or market.get("volumeClob"))),
            }
        )
    return normalized


def build_threshold_summary(
    *,
    markets: list[dict[str, Any]],
    profile_name: str,
    yes_threshold: float,
    no_threshold: float,
    min_category_priority: int,
    category_priorities: dict[str, int],
    platt_a: float,
    platt_b: float,
) -> dict[str, Any]:
    eligible_markets: list[dict[str, Any]] = []
    yes_reachable_markets = 0
    no_reachable_markets = 0
    sample_windows: list[dict[str, Any]] = []

    for market in filter_basic_markets(markets):
        resolution_hours = market.get("resolution_hours")
        yes_price = market.get("yes_price")
        category = str(market.get("category") or "other")
        priority = int(category_priorities.get(category, category_priorities.get("other", 0)))
        if priority < min_category_priority:
            continue

        thresholds = required_probability_window(
            yes_price=float(yes_price),
            yes_threshold=yes_threshold,
            no_threshold=no_threshold,
            platt_a=platt_a,
            platt_b=platt_b,
        )
        if thresholds["yes_reachable"]:
            yes_reachable_markets += 1
        if thresholds["no_reachable"]:
            no_reachable_markets += 1
        eligible_markets.append(market)
        if len(sample_windows) < 20:
            sample_windows.append(
                {
                    "question": market["question"],
                    "category": category,
                    "yes_price": round_or_none(float(yes_price)),
                    "resolution_hours": round_or_none(float(resolution_hours)),
                    "required_calibrated_prob_yes": thresholds["required_calibrated_prob_yes"],
                    "required_raw_prob_yes": thresholds["required_raw_prob_yes"],
                    "max_calibrated_prob_no": thresholds["max_calibrated_prob_no"],
                    "max_raw_prob_no": thresholds["max_raw_prob_no"],
                }
            )

    return {
        "profile": profile_name,
        "yes": yes_threshold,
        "no": no_threshold,
        "min_category_priority": min_category_priority,
        "tradeable": len(eligible_markets),
        "yes_reachable_markets": yes_reachable_markets,
        "no_reachable_markets": no_reachable_markets,
        "sample_windows": sample_windows,
    }


def load_wallet_flow_status() -> dict[str, Any]:
    public_snapshot = load_json(PUBLIC_RUNTIME_PATH)
    runtime_truth = load_json(RUNTIME_TRUTH_PATH)

    wallet_flow = public_snapshot.get("wallet_flow")
    if isinstance(wallet_flow, dict) and wallet_flow:
        return {
            "ready": bool(wallet_flow.get("ready")),
            "status": wallet_flow.get("status"),
            "scored_wallets": int(wallet_flow.get("wallet_count", 0)),
            "source": str(PUBLIC_RUNTIME_PATH),
        }

    wallet_flow = runtime_truth.get("wallet_flow")
    if isinstance(wallet_flow, dict) and wallet_flow:
        return {
            "ready": bool(wallet_flow.get("ready")),
            "status": wallet_flow.get("status"),
            "scored_wallets": int(wallet_flow.get("wallet_count", 0)),
            "source": str(RUNTIME_TRUTH_PATH),
        }

    scores_path = REPO_ROOT / "data" / "smart_wallets.json"
    db_path = REPO_ROOT / "data" / "wallet_scores.db"
    scored_wallets = 0
    if scores_path.exists():
        try:
            payload = json.loads(scores_path.read_text())
            if isinstance(payload, list):
                scored_wallets = len(payload)
        except json.JSONDecodeError:
            scored_wallets = 0
    elif db_path.exists():
        try:
            with sqlite3.connect(db_path) as conn:
                row = conn.execute("SELECT COUNT(*) FROM wallet_scores").fetchone()
            scored_wallets = int(row[0]) if row else 0
        except sqlite3.DatabaseError:
            scored_wallets = 0
    return {
        "ready": bool(scores_path.exists() and db_path.exists() and scored_wallets > 0),
        "status": "ready" if scores_path.exists() and db_path.exists() and scored_wallets > 0 else "unknown",
        "scored_wallets": scored_wallets,
        "source": "data/smart_wallets.json + data/wallet_scores.db",
    }


def load_system_status() -> str:
    public_snapshot = load_json(PUBLIC_RUNTIME_PATH)
    service = public_snapshot.get("service")
    if isinstance(service, dict) and service.get("status"):
        return str(service["status"])

    runtime_truth = load_json(RUNTIME_TRUTH_PATH)
    service = runtime_truth.get("service")
    if isinstance(service, dict) and service.get("status"):
        return str(service["status"])
    return "unknown"


def load_latest_pipeline_verdict() -> tuple[str, str, list[dict[str, Any]]]:
    pipeline_paths = sorted(
        path for path in REPORTS_DIR.glob("pipeline_*.json") if not path.name.startswith("pipeline_refresh_")
    )
    if not pipeline_paths:
        return "REJECT ALL", "No pipeline artifact was present for reconciliation.", []

    latest = pipeline_paths[-1]
    payload = load_json(latest)
    verdict = payload.get("pipeline_verdict", {}) if isinstance(payload, dict) else {}
    new_viable = payload.get("new_viable_strategies", []) if isinstance(payload, dict) else []
    return (
        str(verdict.get("recommendation", "REJECT ALL")),
        str(verdict.get("reasoning", "No reasoning was available.")),
        new_viable if isinstance(new_viable, list) else [],
    )


def load_a6_scan_summary() -> dict[str, Any]:
    payload = load_json(ARB_SNAPSHOT_PATH)
    repo_truth = payload.get("repo_truth", {}) if isinstance(payload, dict) else {}
    lane_status = payload.get("lane_status", {}) if isinstance(payload, dict) else {}
    public_a6 = repo_truth.get("public_a6_audit", {}) if isinstance(repo_truth, dict) else {}
    a6_lane = lane_status.get("a6", {}) if isinstance(lane_status, dict) else {}
    live_surface = payload.get("live_surface", {}) if isinstance(payload, dict) else {}
    return {
        "generated_at": payload.get("generated_at"),
        "allowed_events": int(public_a6.get("allowed_neg_risk_event_count", 0) or 0),
        "qualified": int(live_surface.get("qualified_a6_count", 0) or 0),
        "executable": int(public_a6.get("executable_constructions_below_threshold", 0) or 0),
        "execute_threshold": public_a6.get("execute_threshold"),
        "status": a6_lane.get("status"),
        "blocked_reasons": list(a6_lane.get("blocked_reasons", [])),
        "source": str(ARB_SNAPSHOT_PATH),
    }


def run_a6_live_scan() -> dict[str, Any]:
    try:
        from bot.a6_sum_scanner import scan_neg_risk_events

        result = scan_neg_risk_events()
    except Exception as exc:  # pragma: no cover - defensive fallback around live scanner
        return {
            "status": "error",
            "error": str(exc),
            "executable": 0,
            "candidates": 0,
            "opportunities": [],
            "stats": {},
        }

    if not isinstance(result, dict):
        return {
            "status": "unexpected_payload",
            "executable": 0,
            "candidates": 0,
            "opportunities": [],
            "stats": {},
        }

    return {
        "status": str(result.get("status") or "unknown"),
        "executable": int(result.get("executable", 0) or 0),
        "candidates": int(result.get("candidates", 0) or 0),
        "opportunities": list(result.get("opportunities", [])),
        "stats": dict(result.get("stats") or {}),
    }


def build_refresh_payload(now: datetime, pull_dir: Path, gamma_events: list[dict[str, Any]]) -> dict[str, Any]:
    profile = load_current_profile()
    platt_a = DEFAULT_PLATT_A
    platt_b = DEFAULT_PLATT_B
    markets = flatten_open_markets(gamma_events, now)
    fast_markets = load_fast_markets(now)
    threshold_markets, threshold_market_source = select_threshold_markets(markets, fast_markets)
    category_snapshot = build_category_snapshot(markets)

    markets_with_resolution = [
        market
        for market in markets
        if isinstance(market.get("resolution_hours"), (int, float))
        and float(market["resolution_hours"]) > 0.0
    ]
    markets_in_price_window = [
        market
        for market in markets_with_resolution
        if isinstance(market.get("yes_price"), (int, float)) and 0.10 <= float(market["yes_price"]) <= 0.90
    ]
    threshold_markets_in_price_window = [
        market
        for market in threshold_markets
        if isinstance(market.get("yes_price"), (int, float)) and 0.10 <= float(market["yes_price"]) <= 0.90
    ]
    basic_filter_markets = filter_basic_markets(threshold_markets)
    current_allowed = [
        market
        for market in basic_filter_markets
        if int(profile["category_priorities"].get(str(market["category"]), 0)) >= int(profile["min_category_priority"])
    ]

    current_summary = build_threshold_summary(
        markets=threshold_markets,
        profile_name="current",
        yes_threshold=float(profile["yes"]),
        no_threshold=float(profile["no"]),
        min_category_priority=int(profile["min_category_priority"]),
        category_priorities=dict(profile["category_priorities"]),
        platt_a=platt_a,
        platt_b=platt_b,
    )
    aggressive_summary = build_threshold_summary(
        markets=threshold_markets,
        profile_name="aggressive",
        yes_threshold=AGGRESSIVE_THRESHOLDS["yes"],
        no_threshold=AGGRESSIVE_THRESHOLDS["no"],
        min_category_priority=AGGRESSIVE_THRESHOLDS["min_category_priority"],
        category_priorities=dict(profile["category_priorities"]),
        platt_a=platt_a,
        platt_b=platt_b,
    )
    wide_open_summary = build_threshold_summary(
        markets=threshold_markets,
        profile_name="wide_open",
        yes_threshold=WIDE_OPEN_THRESHOLDS["yes"],
        no_threshold=WIDE_OPEN_THRESHOLDS["no"],
        min_category_priority=WIDE_OPEN_THRESHOLDS["min_category_priority"],
        category_priorities=dict(profile["category_priorities"]),
        platt_a=platt_a,
        platt_b=platt_b,
    )

    recommendation, pipeline_reasoning, new_viable_strategies = load_latest_pipeline_verdict()
    if threshold_market_source == "fast_market_discovery":
        reason_lines = [
            f"Fast-market discovery surfaced {len(fast_markets)} BTC markets; {len(basic_filter_markets)} pass the basic <48h and 0.10-0.90 filters. The current profile leaves {current_summary['tradeable']} after the category gate, while aggressive and wide-open expand that to {aggressive_summary['tradeable']} and {wide_open_summary['tradeable']}.",
            f"YES-side trigger reachability within the BTC fast-market universe moves {current_summary['yes_reachable_markets']} to {aggressive_summary['yes_reachable_markets']} to {wide_open_summary['yes_reachable_markets']}, but the latest strategy pipeline still reports {recommendation}.",
        ]
        if markets:
            reason_lines.append(
                f"The broad flattened Gamma pull still surfaced {len(markets)} open markets across {len(gamma_events)} events, but that feed is not the threshold universe for the BTC fast-market lane."
            )
    else:
        reason_lines = [
            f"Flattened Gamma pull surfaced {len(markets)} open markets across {len(gamma_events)} events; {len(basic_filter_markets)} pass the basic <48h and 0.10-0.90 filters. The current profile leaves {current_summary['tradeable']} after the category gate, while aggressive and wide-open expand that to {aggressive_summary['tradeable']} and {wide_open_summary['tradeable']}.",
            f"YES-side trigger reachability widens from {current_summary['yes_reachable_markets']} to {aggressive_summary['yes_reachable_markets']} to {wide_open_summary['yes_reachable_markets']}, but the latest strategy pipeline still reports {recommendation}.",
        ]
    if not new_viable_strategies:
        reason_lines.append("No validated or candidate edges were promoted by the latest research cycle, so lower thresholds do not unlock a real dispatchable trade set.")
    reason_lines.append(pipeline_reasoning)

    a6_summary = load_a6_scan_summary()
    a6_live_scan = run_a6_live_scan()
    wallet_flow = load_wallet_flow_status()

    return {
        "timestamp": now.isoformat(),
        "instance_version": INSTANCE_VERSION,
        "system_status": load_system_status(),
        "data_pull_dir": str(pull_dir),
        "markets_pulled": len(markets),
        "events_pulled": len(gamma_events),
        "fast_markets_pulled": len(fast_markets),
        "threshold_market_source": threshold_market_source,
        "threshold_markets_pulled": len(threshold_markets),
        "basic_filter_markets": len(basic_filter_markets),
        "markets_under_24h": sum(
            1 for market in basic_filter_markets if float(market["resolution_hours"]) <= 24.0
        ),
        "markets_under_48h": len(basic_filter_markets),
        "markets_in_price_window": len(threshold_markets_in_price_window),
        "markets_in_allowed_categories": len(current_allowed),
        "threshold_sensitivity": {
            "current": current_summary,
            "aggressive": aggressive_summary,
            "wide_open": wide_open_summary,
        },
        "category_breakdown": {
            category: details["count"] for category, details in category_snapshot.items()
        },
        "category_snapshot": category_snapshot,
        "a6_scan": a6_summary,
        "a6_live_scan": a6_live_scan,
        "wallet_flow": wallet_flow,
        "calibration_params": {"A": platt_a, "B": platt_b},
        "recommendation": recommendation,
        "reasoning": " ".join(reason_lines),
        "new_viable_strategies": new_viable_strategies,
    }


def write_refresh_artifact(payload: dict[str, Any], report_root: Path) -> Path:
    stamp = datetime.fromisoformat(payload["timestamp"]).strftime("%Y%m%dT%H%M%SZ")
    path = report_root / f"pipeline_refresh_{stamp}.json"
    path.write_text(json.dumps(payload, indent=2))
    return path


def run_refresh() -> Path:
    now = utc_now()
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    pull_dir = DATA_PULLS_DIR / stamp
    pull_dir.mkdir(parents=True, exist_ok=True)

    gamma_events = fetch_json("https://gamma-api.polymarket.com/events?closed=false&limit=500")
    gamma_events_path = pull_dir / "gamma_events.json"
    gamma_events_path.write_text(json.dumps(gamma_events, indent=2))

    payload = build_refresh_payload(now, pull_dir, gamma_events if isinstance(gamma_events, list) else [])
    payload["gamma_events_path"] = str(gamma_events_path)
    artifact_path = write_refresh_artifact(payload, REPORTS_DIR)
    return artifact_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh live Polymarket market-universe metrics.")
    return parser.parse_args()


def main() -> None:
    parse_args()
    artifact_path = run_refresh()
    print(artifact_path)


if __name__ == "__main__":
    main()
