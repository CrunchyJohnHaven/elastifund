#!/usr/bin/env python3
"""Rank LLM-tradable Polymarket opportunities by resolution window.

This script is the operational companion for Instance 3:
  - applies the slow-market LLM lane gates (category + velocity + btc5 ownership)
  - compares eligibility at 24h / 72h / 168h windows
  - outputs top candidates with annualized velocity proxy
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

GAMMA_URL = "https://gamma-api.polymarket.com/markets"
DEFAULT_WINDOWS = (24.0, 72.0, 168.0)
DEFAULT_OUTPUT = Path("reports/llm_velocity_window_scan.json")

DEFAULT_CATEGORY_PRIORITY: dict[str, int] = {
    "politics": 3,
    "weather": 3,
    "economic": 2,
    "crypto": 0,
    "sports": 0,
    "financial_speculation": 0,
    "geopolitical": 1,
    "fed_rates": 0,
    "unknown": 0,
}
DEFAULT_MIN_CATEGORY_PRIORITY = 1

_WORD_KEYWORDS: dict[str, tuple[str, ...]] = {
    "crypto": ("bitcoin", "btc", "ethereum", "eth", "solana", "xrp", "crypto"),
    "sports": (
        "nba",
        "nfl",
        "mlb",
        "nhl",
        "mls",
        "soccer",
        "football",
        "basketball",
        "tennis",
        "golf",
        "fight",
        "ufc",
    ),
    "financial_speculation": ("stock", "nasdaq", "dow", "s&p", "market cap", "fdv", "price target"),
    "politics": ("election", "president", "prime minister", "senate", "congress"),
    "weather": ("rain", "snow", "temperature", "hurricane", "storm", "weather"),
    "economic": ("inflation", "cpi", "gdp", "jobs", "unemployment", "fomc"),
    "geopolitical": ("war", "ceasefire", "taiwan", "ukraine", "russia", "israel", "gaza"),
}

_BTC5_TITLES = (
    "btc up or down",
    "bitcoin up or down",
    "btc 5 minute",
    "btc 5-minute",
    "bitcoin 5 minute",
    "bitcoin 5-minute",
)


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_horizons(raw: str) -> list[float]:
    values: list[float] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        value = float(chunk)
        if value <= 0:
            raise ValueError("resolution windows must be > 0 hours")
        values.append(value)
    if not values:
        raise ValueError("no valid windows provided")
    return sorted(set(values))


def _parse_iso_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def estimate_resolution_hours(market: dict[str, Any], *, now: datetime) -> float | None:
    for key in (
        "endDate",
        "end_date_iso",
        "resolution_date",
        "resolutionDate",
        "closeTime",
        "closedTime",
        "endTime",
    ):
        parsed = _parse_iso_datetime(market.get(key))
        if parsed is None:
            continue
        hours = (parsed - now).total_seconds() / 3600.0
        if hours <= 0:
            return None
        return hours

    # Keep a small heuristic for short-horizon intraday wording.
    question = str(market.get("question", "")).lower()
    if "today" in question:
        return 12.0
    if "tomorrow" in question:
        return 24.0
    return None


def _keyword_match(text: str, keyword: str) -> bool:
    if " " in keyword:
        return keyword in text
    return re.search(rf"\b{re.escape(keyword)}\b", text) is not None


def classify_market_category(question: str, category_field: Any) -> str:
    normalized = str(category_field or "").strip().lower().replace(" ", "_")
    if normalized:
        return normalized

    question_lower = question.lower()
    scores: dict[str, int] = {}
    for category, keywords in _WORD_KEYWORDS.items():
        scores[category] = sum(1 for keyword in keywords if _keyword_match(question_lower, keyword))
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "unknown"


def is_dedicated_btc5_market(question: str, slug: str) -> bool:
    combined = f"{question} {slug}".lower()
    return any(marker in combined for marker in _BTC5_TITLES)


def extract_yes_price(market: dict[str, Any]) -> float | None:
    tokens = market.get("tokens")
    if isinstance(tokens, list):
        for token in tokens:
            if not isinstance(token, dict):
                continue
            outcome = str(token.get("outcome", "")).strip().lower()
            if outcome != "yes":
                continue
            candidate = _safe_float(
                token.get("price", token.get("last_price", token.get("lastPrice"))),
                None,
            )
            if candidate is not None and 0.0 < candidate < 1.0:
                return candidate

    outcome_prices = market.get("outcomePrices")
    if isinstance(outcome_prices, list) and outcome_prices:
        yes_price = _safe_float(outcome_prices[0], None)
        if yes_price is not None and 0.0 < yes_price < 1.0:
            return yes_price
    if isinstance(outcome_prices, str) and outcome_prices.strip():
        try:
            parsed = json.loads(outcome_prices)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list) and parsed:
            yes_price = _safe_float(parsed[0], None)
            if yes_price is not None and 0.0 < yes_price < 1.0:
                return yes_price

    fallback = _safe_float(market.get("price", market.get("yes_price")), None)
    if fallback is not None and 0.0 < fallback < 1.0:
        return fallback
    return None


def annualized_velocity_proxy(estimated_edge: float, resolution_hours: float) -> float:
    if resolution_hours <= 0:
        return 0.0
    resolution_days = resolution_hours / 24.0
    return abs(estimated_edge) / resolution_days * 365.0


def evaluate_market(
    market: dict[str, Any],
    *,
    now: datetime,
    max_resolution_hours: float,
    category_priority: dict[str, int],
    min_category_priority: int,
) -> tuple[dict[str, Any] | None, str]:
    question = str(market.get("question", "") or "").strip()
    slug = str(market.get("slug", "") or "").strip()
    if not question:
        return None, "missing_question"

    category = classify_market_category(question, market.get("category"))
    if is_dedicated_btc5_market(question, slug):
        return None, "btc5_dedicated"
    if category_priority.get(category, 0) < min_category_priority:
        return None, "category"

    resolution_hours = estimate_resolution_hours(market, now=now)
    if resolution_hours is None:
        return None, "unknown_resolution"
    if resolution_hours > max_resolution_hours:
        return None, "velocity"

    yes_price = extract_yes_price(market)
    if yes_price is None:
        return None, "missing_price"
    if not (0.10 <= yes_price <= 0.90):
        return None, "price_window"

    market_id = str(market.get("conditionId") or market.get("condition_id") or market.get("id") or "").strip()
    estimated_edge_proxy = abs(0.5 - yes_price)
    velocity = annualized_velocity_proxy(estimated_edge_proxy, resolution_hours)
    return (
        {
            "market_id": market_id,
            "slug": slug,
            "question": question,
            "category": category,
            "resolution_hours": round(resolution_hours, 4),
            "yes_price": round(yes_price, 4),
            "estimated_edge_proxy": round(estimated_edge_proxy, 6),
            "velocity_score": round(velocity, 4),
        },
        "ok",
    )


def evaluate_windows(
    markets: list[dict[str, Any]],
    *,
    now: datetime,
    horizons: list[float],
    top_n: int,
    category_priority: dict[str, int] | None = None,
    min_category_priority: int = DEFAULT_MIN_CATEGORY_PRIORITY,
) -> dict[str, Any]:
    category_priority = dict(category_priority or DEFAULT_CATEGORY_PRIORITY)
    windows: dict[str, Any] = {}

    for horizon in horizons:
        reason_counts: dict[str, int] = {}
        passing_rows: list[dict[str, Any]] = []
        for market in markets:
            row, reason = evaluate_market(
                market,
                now=now,
                max_resolution_hours=horizon,
                category_priority=category_priority,
                min_category_priority=min_category_priority,
            )
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
            if row is not None:
                passing_rows.append(row)

        passing_rows.sort(key=lambda item: item["velocity_score"], reverse=True)
        velocity_sum = sum(float(row["velocity_score"]) for row in passing_rows)
        windows[f"{horizon:.0f}h"] = {
            "max_resolution_hours": horizon,
            "passing_count": len(passing_rows),
            "sum_velocity_score": round(velocity_sum, 4),
            "reason_counts": reason_counts,
            "top_markets": passing_rows[: max(1, top_n)],
        }

    ranked_windows = sorted(
        windows.values(),
        key=lambda item: (item["sum_velocity_score"], item["passing_count"]),
        reverse=True,
    )
    recommended = ranked_windows[0] if ranked_windows else None
    recommended_window = (
        f"{int(recommended['max_resolution_hours'])}h"
        if isinstance(recommended, dict)
        else None
    )
    return {
        "evaluated_at": now.isoformat(),
        "total_markets_scanned": len(markets),
        "min_category_priority": min_category_priority,
        "category_priority": category_priority,
        "windows": windows,
        "recommended_window": recommended_window,
        "method_note": (
            "velocity_score uses annualized edge proxy abs(0.5-yes_price); "
            "replace with model-estimated edge for live sizing decisions."
        ),
    }


def fetch_active_markets(*, limit: int = 600, timeout_seconds: float = 20.0) -> list[dict[str, Any]]:
    markets: list[dict[str, Any]] = []
    offset = 0
    page_size = 100
    timeout = httpx.Timeout(timeout_seconds, connect=timeout_seconds)
    with httpx.Client(timeout=timeout) as client:
        while len(markets) < limit:
            params = {
                "active": "true",
                "closed": "false",
                "limit": str(min(page_size, limit - len(markets))),
                "offset": str(offset),
            }
            response = client.get(GAMMA_URL, params=params)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list) or not payload:
                break
            page_rows = [item for item in payload if isinstance(item, dict)]
            markets.extend(page_rows)
            if len(payload) < page_size:
                break
            offset += page_size
    return markets[:limit]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--horizons", default="24,72,168", help="Comma-separated max-resolution windows in hours.")
    parser.add_argument("--limit", type=int, default=600, help="Max active markets to fetch from Gamma.")
    parser.add_argument("--top", type=int, default=20, help="Top markets to keep per window.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Report output path.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    horizons = parse_horizons(args.horizons)
    now = datetime.now(timezone.utc)
    markets = fetch_active_markets(limit=max(1, args.limit))
    report = evaluate_windows(
        markets,
        now=now,
        horizons=horizons,
        top_n=max(1, args.top),
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(
        f"Scanned {report['total_markets_scanned']} markets | "
        f"recommended_window={report['recommended_window']} | "
        f"output={output_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
