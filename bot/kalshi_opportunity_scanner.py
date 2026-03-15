"""Kalshi fast-resolving LLM-edge opportunity scanner (Instance 5)."""

from __future__ import annotations

import json
import logging
import math
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import requests

KALSHI_API_BASE = os.environ.get(
    "KALSHI_API_BASE",
    "https://api.elections.kalshi.com/trade-api/v2",
)
OUTPUT_PATH = Path("data/kalshi_opportunities.json")

LOGGER = logging.getLogger("kalshi.opportunity_scanner")

LLM_EDGE_CATEGORY_MAP = {
    "politics": "politics",
    "elections": "politics",
    "climate and weather": "weather",
    "weather": "weather",
    "economics": "economic",
    "world": "geopolitical",
}

WEATHER_KEYWORDS = {
    "weather",
    "rain",
    "snow",
    "hurricane",
    "temperature",
    "wind",
    "storm",
    "precipitation",
}
POLITICS_KEYWORDS = {
    "election",
    "senate",
    "house",
    "governor",
    "president",
    "approval",
    "primary",
    "candidate",
    "cabinet",
    "minister",
}
ECONOMIC_KEYWORDS = {
    "inflation",
    "cpi",
    "ppi",
    "federal reserve",
    "fed",
    "jobs report",
    "payroll",
    "gdp",
    "unemployment",
    "interest rate",
    "treasury",
    "recession",
}
GEOPOLITICAL_KEYWORDS = {
    "ukraine",
    "russia",
    "china",
    "taiwan",
    "israel",
    "gaza",
    "iran",
    "ceasefire",
    "sanctions",
    "nato",
    "missile",
    "airstrike",
    "border",
    "diplomatic",
}


@dataclass(frozen=True)
class ScanConfig:
    max_event_pages: int = 8
    events_page_limit: int = 200
    market_limit_per_event: int = 200
    max_hours_to_resolution: float = 72.0
    top_n: int = 20
    per_request_sleep_seconds: float = 0.06


def _json_get(url: str, *, params: Optional[dict[str, Any]] = None, timeout: float = 25.0) -> dict[str, Any]:
    response = requests.get(
        url,
        params=params,
        timeout=timeout,
        headers={"User-Agent": "Elastifund/1.0 (kalshi-opportunity-scanner)"},
    )
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_prob(value: Any) -> Optional[float]:
    raw = _safe_float(value)
    if raw is None:
        return None
    if raw > 1.0:
        raw = raw / 100.0
    return max(0.0, min(1.0, raw))


def _parse_dt(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def infer_llm_edge_category(title: str, event_category: str) -> Optional[str]:
    category_key = str(event_category or "").strip().lower()
    mapped = LLM_EDGE_CATEGORY_MAP.get(category_key)
    if mapped:
        return mapped

    text = str(title or "").lower()
    if any(keyword in text for keyword in WEATHER_KEYWORDS):
        return "weather"
    if any(keyword in text for keyword in ECONOMIC_KEYWORDS):
        return "economic"
    if any(keyword in text for keyword in GEOPOLITICAL_KEYWORDS):
        return "geopolitical"
    if any(keyword in text for keyword in POLITICS_KEYWORDS):
        return "politics"
    return None


def _extract_yes_no_quotes(market: dict[str, Any]) -> tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    yes_bid = _to_prob(market.get("yes_bid"))
    yes_ask = _to_prob(market.get("yes_ask"))
    no_bid = _to_prob(market.get("no_bid"))
    no_ask = _to_prob(market.get("no_ask"))

    # Kalshi increasingly returns dollar quotes (e.g. "0.5600") instead of cent ints.
    if yes_bid is None:
        yes_bid = _to_prob(market.get("yes_bid_dollars"))
    if yes_ask is None:
        yes_ask = _to_prob(market.get("yes_ask_dollars"))
    if no_bid is None:
        no_bid = _to_prob(market.get("no_bid_dollars"))
    if no_ask is None:
        no_ask = _to_prob(market.get("no_ask_dollars"))

    if yes_ask is None and no_bid is not None:
        yes_ask = max(0.01, min(0.99, 1.0 - no_bid))
    if no_ask is None and yes_bid is not None:
        no_ask = max(0.01, min(0.99, 1.0 - yes_bid))
    if yes_bid is None and yes_ask is not None:
        yes_bid = max(0.0, min(yes_ask, yes_ask - 0.01))
    if no_bid is None and no_ask is not None:
        no_bid = max(0.0, min(no_ask, no_ask - 0.01))

    return yes_bid, yes_ask, no_bid, no_ask


def _estimate_edge_and_confidence(
    *,
    llm_edge_category: str,
    spread: float,
    hours_to_resolution: float,
    volume: float,
    open_interest: float,
) -> tuple[float, float]:
    base_edge = {
        "weather": 0.060,
        "politics": 0.055,
        "economic": 0.050,
        "geopolitical": 0.062,
    }.get(llm_edge_category, 0.045)

    spread_quality = max(0.10, min(1.0, 1.0 - (spread / 0.25)))
    liquidity_anchor = max(volume, open_interest)
    liquidity_quality = max(0.20, min(1.0, math.log10(liquidity_anchor + 10.0) / 4.0))
    horizon_quality = max(0.35, min(1.5, 72.0 / max(6.0, hours_to_resolution)))

    estimated_edge = base_edge * spread_quality * (0.70 + 0.30 * liquidity_quality) * (0.80 + 0.20 * horizon_quality)
    estimated_edge = max(0.01, min(0.18, estimated_edge))

    confidence = 0.20 + 0.35 * spread_quality + 0.30 * liquidity_quality + 0.15 * min(1.0, 72.0 / max(1.0, hours_to_resolution))
    confidence = max(0.10, min(0.95, confidence))
    return round(estimated_edge, 6), round(confidence, 6)


def _category_note(llm_edge_category: str, hours_to_resolution: float) -> str:
    if llm_edge_category == "weather":
        return "Short-horizon weather contracts are often forecastable from public data."
    if llm_edge_category == "economic":
        return "Macro release and rate-path contracts can offer modelable pre-release drift."
    if llm_edge_category == "geopolitical":
        return "Event-driven geopolitical contracts can move sharply on public headlines."
    if hours_to_resolution <= 24.0:
        return "Sub-24h political resolution supports fast feedback for LLM-edge validation."
    return "Political contract fits LLM-analysis lane; verify spread before execution."


def build_opportunity_record(
    *,
    market: dict[str, Any],
    event: dict[str, Any],
    now: datetime,
    max_hours_to_resolution: float,
) -> Optional[dict[str, Any]]:
    ticker = str(market.get("ticker") or "").strip()
    if not ticker:
        return None

    title = str(market.get("title") or market.get("subtitle") or event.get("title") or ticker).strip()
    event_title = str(event.get("title") or "").strip()
    llm_edge_category = infer_llm_edge_category(f"{event_title} {title}", str(event.get("category") or ""))
    if llm_edge_category is None:
        return None

    close_time = (
        _parse_dt(market.get("close_time"))
        or _parse_dt(market.get("expiration_time"))
        or _parse_dt(market.get("latest_expiration_time"))
        or _parse_dt(market.get("expected_expiration_time"))
    )
    if close_time is None:
        return None

    hours_to_resolution = (close_time - now).total_seconds() / 3600.0
    if hours_to_resolution <= 0.0 or hours_to_resolution > max_hours_to_resolution:
        return None

    yes_bid, yes_ask, no_bid, no_ask = _extract_yes_no_quotes(market)
    if yes_ask is None or no_ask is None:
        return None
    if yes_bid is None:
        yes_bid = max(0.0, yes_ask - 0.01)
    if no_bid is None:
        no_bid = max(0.0, no_ask - 0.01)

    spread = max(0.0, yes_ask - yes_bid, no_ask - no_bid)
    volume = _safe_float(market.get("volume")) or _safe_float(market.get("volume_fp")) or 0.0
    if volume <= 0.0:
        volume = _safe_float(market.get("volume_dollars")) or 0.0
    open_interest = _safe_float(market.get("open_interest")) or _safe_float(market.get("open_interest_fp")) or 0.0

    estimated_edge, confidence = _estimate_edge_and_confidence(
        llm_edge_category=llm_edge_category,
        spread=spread,
        hours_to_resolution=hours_to_resolution,
        volume=volume,
        open_interest=open_interest,
    )
    resolution_days = max(1.0 / 24.0, hours_to_resolution / 24.0)
    velocity_score = round((estimated_edge / resolution_days) * 365.0, 6)

    return {
        "ticker": ticker,
        "title": title,
        "event_ticker": str(event.get("event_ticker") or ""),
        "event_title": event_title,
        "category": llm_edge_category,
        "close_time": close_time.isoformat(),
        "hours_to_resolution": round(hours_to_resolution, 3),
        "yes_bid": round(yes_bid, 6),
        "yes_ask": round(yes_ask, 6),
        "no_bid": round(no_bid, 6),
        "no_ask": round(no_ask, 6),
        "spread": round(spread, 6),
        "volume": round(volume, 3),
        "open_interest": round(open_interest, 3),
        "estimated_edge": estimated_edge,
        "velocity_score": velocity_score,
        "confidence": confidence,
        "resolution_source": (
            str(market.get("rules_primary") or market.get("rules_secondary") or "").strip()[:280] or None
        ),
        "notes": _category_note(llm_edge_category, hours_to_resolution),
    }


def fetch_open_events(config: ScanConfig) -> tuple[list[dict[str, Any]], bool]:
    events: list[dict[str, Any]] = []
    cursor: Optional[str] = None
    for _ in range(max(1, int(config.max_event_pages))):
        params: dict[str, Any] = {
            "status": "open",
            "limit": int(config.events_page_limit),
        }
        if cursor:
            params["cursor"] = cursor
        payload = _json_get(f"{KALSHI_API_BASE}/events", params=params)
        page_events = payload.get("events") or []
        if not isinstance(page_events, list):
            break
        events.extend([event for event in page_events if isinstance(event, dict)])
        cursor = str(payload.get("cursor") or "").strip() or None
        if not cursor:
            break
        if config.per_request_sleep_seconds > 0:
            time.sleep(config.per_request_sleep_seconds)
    return events, bool(events)


def fetch_event_markets(event_ticker: str, config: ScanConfig) -> list[dict[str, Any]]:
    payload = _json_get(
        f"{KALSHI_API_BASE}/markets",
        params={
            "event_ticker": event_ticker,
            "status": "open",
            "limit": int(config.market_limit_per_event),
        },
    )
    markets = payload.get("markets") or []
    if not isinstance(markets, list):
        return []
    return [market for market in markets if isinstance(market, dict)]


def _build_balance_probe() -> dict[str, Any]:
    api_key = str(os.environ.get("KALSHI_API_KEY_ID") or "").strip()
    key_path = str(os.environ.get("KALSHI_RSA_KEY_PATH") or "").strip()
    if not api_key or not key_path:
        return {
            "status": "skipped_no_credentials",
            "details": "KALSHI_API_KEY_ID/KALSHI_RSA_KEY_PATH not configured in this environment.",
            "balance_usd": None,
        }
    return {
        "status": "credentials_detected_no_probe",
        "details": "Credentials exist but scanner runs read-only; execute authenticated balance probe on VPS.",
        "balance_usd": None,
    }


def scan_kalshi_opportunities(
    *,
    config: Optional[ScanConfig] = None,
    now: Optional[datetime] = None,
    events: Optional[list[dict[str, Any]]] = None,
    event_markets_loader: Optional[Callable[[str], list[dict[str, Any]]]] = None,
) -> dict[str, Any]:
    scan_config = config or ScanConfig()
    scan_now = now or datetime.now(timezone.utc)

    if events is None:
        events, api_ok = fetch_open_events(scan_config)
    else:
        api_ok = True

    loader = event_markets_loader
    if loader is None:
        loader = lambda event_ticker: fetch_event_markets(event_ticker, scan_config)

    total_events_scanned = 0
    llm_edge_events = 0
    total_markets_scanned = 0
    raw_candidates = 0
    opportunities_by_ticker: dict[str, dict[str, Any]] = {}
    category_counts = {"politics": 0, "weather": 0, "economic": 0, "geopolitical": 0}

    for event in events:
        total_events_scanned += 1
        event_ticker = str(event.get("event_ticker") or "").strip()
        if not event_ticker:
            continue
        event_title = str(event.get("title") or "")
        event_category = str(event.get("category") or "")
        llm_category = infer_llm_edge_category(event_title, event_category)
        if llm_category is None:
            continue
        llm_edge_events += 1
        category_counts[llm_category] = category_counts.get(llm_category, 0) + 1

        try:
            markets = loader(event_ticker)
        except requests.HTTPError as exc:
            LOGGER.warning("Event %s market fetch failed: %s", event_ticker, exc)
            continue
        except requests.RequestException as exc:
            LOGGER.warning("Event %s request failure: %s", event_ticker, exc)
            continue
        total_markets_scanned += len(markets)

        for market in markets:
            record = build_opportunity_record(
                market=market,
                event=event,
                now=scan_now,
                max_hours_to_resolution=float(scan_config.max_hours_to_resolution),
            )
            if record is None:
                continue
            raw_candidates += 1
            ticker = str(record.get("ticker") or "")
            existing = opportunities_by_ticker.get(ticker)
            if existing is None or float(record["velocity_score"]) > float(existing["velocity_score"]):
                opportunities_by_ticker[ticker] = record

        if scan_config.per_request_sleep_seconds > 0:
            time.sleep(scan_config.per_request_sleep_seconds)

    opportunities = sorted(
        opportunities_by_ticker.values(),
        key=lambda item: (float(item["velocity_score"]), float(item["confidence"]), float(item["volume"])),
        reverse=True,
    )
    top_opportunities = opportunities[: max(1, int(scan_config.top_n))]

    recommendations: list[str] = []
    if len(top_opportunities) < 5:
        recommendations.append(
            "Eligible opportunities under 5 at <=72h. Relax max_hours_to_resolution to 168h for broader throughput."
        )
    if not top_opportunities:
        recommendations.append(
            "No LLM-edge Kalshi opportunities passed current filters. Keep scan running hourly and widen category keywords."
        )
    if any(float(item["spread"]) > 0.12 for item in top_opportunities):
        recommendations.append(
            "Several top opportunities have spread > 12%; maker-only execution discipline is mandatory."
        )
    if api_ok and total_markets_scanned < 100:
        recommendations.append(
            "Scanned under 100 markets; increase max_event_pages for fuller venue coverage."
        )

    payload = {
        "scanned_at": scan_now.isoformat(),
        "api_base": KALSHI_API_BASE,
        "api_connection": {"status": "ok" if api_ok else "failed"},
        "balance_check": _build_balance_probe(),
        "filters": {
            "llm_edge_categories": ["politics", "weather", "economic", "geopolitical"],
            "max_hours_to_resolution": float(scan_config.max_hours_to_resolution),
            "top_n": int(scan_config.top_n),
        },
        "total_events_scanned": total_events_scanned,
        "llm_edge_events": llm_edge_events,
        "total_markets": total_markets_scanned,
        "raw_candidates": raw_candidates,
        "passing_filters": len(opportunities),
        "passing_filters_top_n": len(top_opportunities),
        "category_event_counts": category_counts,
        "opportunities": top_opportunities,
        "next_cycle_actions": recommendations,
    }
    return payload


def write_opportunity_report(
    payload: dict[str, Any],
    *,
    output_path: Path = OUTPUT_PATH,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output_path


def run_and_write_report(
    *,
    config: Optional[ScanConfig] = None,
    output_path: Path = OUTPUT_PATH,
) -> tuple[dict[str, Any], Path]:
    payload = scan_kalshi_opportunities(config=config)
    written_path = write_opportunity_report(payload, output_path=output_path)
    return payload, written_path

