#!/usr/bin/env python3
"""Audit the broad Gamma crypto-tagged universe against the repo fast-market lane."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.pipeline_refresh import (
    fetch_json,
    filter_basic_markets,
    flatten_open_markets,
    iso_to_dt,
    load_fast_markets,
    parse_yes_price,
)


REPORT_PATH = REPO_ROOT / "reports" / "crypto_category_audit.json"
GAMMA_EVENTS_URL = "https://gamma-api.polymarket.com/events"
EVENT_PAGE_SIZE = 500
DEFAULT_MAX_EVENT_PAGES = 10
AUDIT_CLASSES = ("btc_candle", "eth_candle", "altcoin_meme", "crypto_other")
LEGACY_CLASSES = ("btc_candle", "eth_candle", "altcoin", "meme_degenerate", "crypto_other")
SAMPLE_SIZE = 5

BTC_MARKERS = ("bitcoin", "btc")
ETH_MARKERS = ("ethereum", "eth")
ALTCOIN_MARKERS = (
    "solana",
    "sol",
    "xrp",
    "ripple",
    "dogecoin",
    "doge",
    "litecoin",
    "ltc",
    "cardano",
    "ada",
    "avalanche",
    "avax",
    "sui",
    "pepe",
    "bonk",
    "shib",
    "shiba",
    "tron",
    "trx",
    "aptos",
    "apt",
    "berachain",
    "bera",
    "hyperliquid",
    "hype",
)
MEME_MARKERS = (
    "airdrop",
    "airdrops",
    "pre-market",
    "premarket",
    "fdv",
    "launch",
    "token launch",
    "token sale",
    "token-sales",
    "token-launch",
    "pump.fun",
    "pumpfun",
    "memecoin",
    "meme coin",
    "meme",
    "tge",
)
CRYPTO_TAG_MARKERS = (
    "crypto",
    "crypto-prices",
    "bitcoin",
    "btc",
    "ethereum",
    "eth",
    "solana",
    "stablecoins",
    "exchange",
    "airdrops",
    "airdrop",
    "token-launch",
    "token-sales",
    "defi",
    "usdc",
    "usdt",
)
PRICE_TARGET_MARKERS = (
    "above $",
    "below $",
    "greater than $",
    "less than $",
    "hit $",
    "hits $",
)
TIME_WINDOW_MARKERS = (
    "up or down",
    "5m",
    "15m",
    "4h",
    "5-minute",
    "15-minute",
    "4-hour",
    "5 minute",
    "15 minute",
    "4 hour",
)
TIME_WINDOW_RE = re.compile(
    r"\b\d{1,2}(:\d{2})?(am|pm)\s*[-–]\s*\d{1,2}(:\d{2})?(am|pm)\b",
    re.IGNORECASE,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_tags(raw_tags: Any) -> list[str]:
    if not isinstance(raw_tags, list):
        return []
    normalized: list[str] = []
    for tag in raw_tags:
        if isinstance(tag, dict):
            value = str(tag.get("slug") or tag.get("label") or "").strip().lower()
        else:
            value = str(tag).strip().lower()
        if value:
            normalized.append(value)
    return normalized


def fetch_open_events(*, max_pages: int = DEFAULT_MAX_EVENT_PAGES, page_size: int = EVENT_PAGE_SIZE) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for page in range(max_pages):
        offset = page * page_size
        payload = fetch_json(f"{GAMMA_EVENTS_URL}?closed=false&limit={page_size}&offset={offset}")
        if not isinstance(payload, list):
            break
        events.extend(item for item in payload if isinstance(item, dict))
        if len(payload) < page_size:
            break
    return events


def market_id(market: dict[str, Any]) -> str:
    return str(market.get("conditionId") or market.get("id") or market.get("market_id") or "").strip()


def _contains_marker(text: str, marker: str) -> bool:
    marker = marker.strip().lower()
    if not marker:
        return False
    if any(character in marker for character in (" ", ".", "$", "-")):
        return marker in text
    return re.search(rf"(?<![a-z0-9]){re.escape(marker)}(?![a-z0-9])", text) is not None


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(_contains_marker(text, marker) for marker in markers)


def market_text(market: dict[str, Any]) -> str:
    parts = [
        str(market.get("question") or ""),
        str(market.get("title") or ""),
        str(market.get("event_title") or ""),
        str(market.get("slug") or ""),
        " ".join(normalize_tags(market.get("tags"))),
    ]
    return " ".join(part for part in parts if part).lower()


def has_crypto_tag(tags: list[str]) -> bool:
    return any(
        tag in CRYPTO_TAG_MARKERS
        or tag.startswith("crypto")
        or tag.startswith("token-")
        or tag.startswith("stablecoin")
        or tag.startswith("airdrop")
        for tag in tags
    )


def is_crypto_tagged_event(event: dict[str, Any]) -> bool:
    return has_crypto_tag(normalize_tags(event.get("tags")))


def extract_crypto_tagged_markets(events: list[dict[str, Any]], *, now: datetime) -> tuple[list[dict[str, Any]], int]:
    crypto_events = [event for event in events if is_crypto_tagged_event(event)]
    flattened = flatten_open_markets(crypto_events, now)
    deduped: dict[str, dict[str, Any]] = {}
    for market in flattened:
        identifier = market_id(market)
        if identifier:
            deduped[identifier] = market
    return list(deduped.values()), len(crypto_events)


def looks_like_fast_candle_contract(market: dict[str, Any]) -> bool:
    slug = str(market.get("slug") or "").strip().lower()
    text = market_text(market)
    if slug.startswith(("btc-updown-", "eth-updown-")):
        return True
    if _contains_any(text, TIME_WINDOW_MARKERS):
        return True
    return TIME_WINDOW_RE.search(text) is not None


def has_clear_resolution_mechanics(market: dict[str, Any]) -> bool:
    return looks_like_fast_candle_contract(market)


def classify_crypto_market(market: dict[str, Any]) -> str:
    """Legacy fine-grained classifier retained for compatibility with older tests."""
    text = market_text(market)
    has_candle_shape = looks_like_fast_candle_contract(market)
    has_price_target_shape = _contains_any(text, PRICE_TARGET_MARKERS)

    if _contains_any(text, MEME_MARKERS):
        return "meme_degenerate"
    if _contains_any(text, BTC_MARKERS) and (has_candle_shape or has_price_target_shape):
        return "btc_candle"
    if _contains_any(text, ETH_MARKERS) and (has_candle_shape or has_price_target_shape):
        return "eth_candle"
    if _contains_any(text, ALTCOIN_MARKERS):
        return "altcoin"
    return "crypto_other"


def classify_audit_category(market: dict[str, Any]) -> str:
    text = market_text(market)
    if has_clear_resolution_mechanics(market):
        if _contains_any(text, BTC_MARKERS):
            return "btc_candle"
        if _contains_any(text, ETH_MARKERS):
            return "eth_candle"
    if _contains_any(text, ALTCOIN_MARKERS) or _contains_any(text, MEME_MARKERS):
        return "altcoin_meme"
    return "crypto_other"


def market_resolution_hours(market: dict[str, Any], *, now: datetime) -> float | None:
    if isinstance(market.get("resolution_hours"), (int, float)):
        hours = float(market["resolution_hours"])
        return hours if hours > 0.0 else None
    end_dt = iso_to_dt(str(market.get("endDate") or market.get("endDateIso") or ""))
    if end_dt is None:
        return None
    hours = (end_dt - now).total_seconds() / 3600.0
    return hours if hours > 0.0 else None


def market_passes_thresholds(market: dict[str, Any], *, now: datetime) -> bool:
    yes_price = market.get("yes_price")
    if not isinstance(yes_price, (int, float)):
        yes_price = parse_yes_price(market)
    resolution_hours = market_resolution_hours(market, now=now)
    if yes_price is None or resolution_hours is None:
        return False
    if resolution_hours > 48.0:
        return False
    return 0.10 <= float(yes_price) <= 0.90


def serialize_market(market: dict[str, Any], *, now: datetime, classification: str) -> dict[str, Any]:
    yes_price = market.get("yes_price")
    if not isinstance(yes_price, (int, float)):
        yes_price = parse_yes_price(market)
    resolution_hours = market_resolution_hours(market, now=now)
    return {
        "market_id": market_id(market),
        "slug": str(market.get("slug") or ""),
        "question": str(market.get("question") or ""),
        "class": classification,
        "price": round(float(yes_price), 4) if isinstance(yes_price, (int, float)) else None,
        "resolution_hours": round(float(resolution_hours), 4) if resolution_hours is not None else None,
        "tags": normalize_tags(market.get("tags")),
        "source": str(market.get("source") or "gamma_events"),
        "clear_resolution_mechanics": has_clear_resolution_mechanics(market),
    }


def _sort_market_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda item: (item["class"], item["question"], item["market_id"]))


def _count_by_class(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {name: 0 for name in AUDIT_CLASSES}
    counter = Counter(str(row["class"]) for row in rows)
    for name in AUDIT_CLASSES:
        counts[name] = int(counter.get(name, 0))
    return counts


def _sample_by_class(rows: list[dict[str, Any]], *, sample_size: int = SAMPLE_SIZE) -> dict[str, list[dict[str, Any]]]:
    samples = {name: [] for name in AUDIT_CLASSES}
    for row in _sort_market_rows(rows):
        class_name = str(row["class"])
        if class_name not in samples or len(samples[class_name]) >= sample_size:
            continue
        samples[class_name].append(row)
    return samples


def _legacy_counts(markets: list[dict[str, Any]]) -> dict[str, int]:
    counts = {name: 0 for name in LEGACY_CLASSES}
    for market in markets:
        counts[classify_crypto_market(market)] += 1
    return counts


def _safe_load_fast_markets(now: datetime) -> list[dict[str, Any]]:
    try:
        return load_fast_markets(now)
    except Exception:
        return []


def _recommendation_basis(
    fast_tradeable_rows: list[dict[str, Any]],
    fast_discovered_rows: list[dict[str, Any]],
    broad_tradeable_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if fast_tradeable_rows:
        return fast_tradeable_rows
    if fast_discovered_rows:
        return fast_discovered_rows
    return broad_tradeable_rows


def derive_recommendation(
    fast_tradeable_rows: list[dict[str, Any]],
    fast_discovered_rows: list[dict[str, Any]],
    broad_tradeable_rows: list[dict[str, Any]],
) -> str:
    basis = _recommendation_basis(fast_tradeable_rows, fast_discovered_rows, broad_tradeable_rows)
    if not basis:
        return "APPROVE_BTC_CANDLES_ONLY"
    if any(
        row["class"] not in {"btc_candle", "eth_candle"} or not bool(row["clear_resolution_mechanics"])
        for row in basis
    ):
        return "ADD_SUBCATEGORY_FILTER"
    return "APPROVE_BTC_CANDLES_ONLY"


def build_conclusion(
    *,
    tagged_event_count: int,
    broad_counts: dict[str, int],
    fast_discovered_count: int,
    fast_tradeable_count: int,
    fast_tradeable_counts: dict[str, int],
    recommendation: str,
) -> str:
    broad_noise = broad_counts["altcoin_meme"] + broad_counts["crypto_other"]
    if fast_tradeable_count == 0:
        return (
            f"Gamma /events currently exposes {sum(broad_counts.values())} crypto-tagged markets across "
            f"{tagged_event_count} tagged events, with {broad_noise} of them outside the BTC/ETH candle lane. "
            f"The repo fast-market helper discovered {fast_discovered_count} candidate markets but 0 pass the "
            f"current basic tradeability screen, so this run shows category noise rather than a live fast-market "
            f"dispatch set. Recommendation: {recommendation}."
        )
    return (
        f"Gamma /events currently exposes {sum(broad_counts.values())} crypto-tagged markets across "
        f"{tagged_event_count} tagged events, with {broad_noise} classified as altcoin/meme or crypto_other. "
        f"The repo fast-market helper discovered {fast_discovered_count} candidate markets and {fast_tradeable_count} "
        f"of them remain tradeable after the current basic screen; that tradeable set breaks down as "
        f"{fast_tradeable_counts['btc_candle']} BTC candle, {fast_tradeable_counts['eth_candle']} ETH candle, "
        f"{fast_tradeable_counts['altcoin_meme']} altcoin/meme, and {fast_tradeable_counts['crypto_other']} crypto_other. "
        f"Recommendation: {recommendation}."
    )


def build_crypto_category_audit(
    broad_markets: list[dict[str, Any]],
    *,
    now: datetime | None = None,
    fast_overlay: list[dict[str, Any]] | None = None,
    tagged_event_count: int = 0,
) -> dict[str, Any]:
    current_time = now or utc_now()
    deduped_broad: dict[str, dict[str, Any]] = {}
    for market in broad_markets:
        identifier = market_id(market)
        if identifier:
            deduped_broad[identifier] = dict(market)

    fast_candidates = list(fast_overlay) if fast_overlay is not None else _safe_load_fast_markets(current_time)
    deduped_fast: dict[str, dict[str, Any]] = {}
    for market in fast_candidates:
        identifier = market_id(market)
        if not identifier:
            continue
        deduped_fast[identifier] = {
            **dict(market),
            "id": identifier,
            "conditionId": identifier,
            "source": "fast_market_discovery",
        }

    broad_rows = [
        serialize_market(market, now=current_time, classification=classify_audit_category(market))
        for market in deduped_broad.values()
    ]
    broad_rows = _sort_market_rows(broad_rows)
    broad_counts = _count_by_class(broad_rows)
    broad_samples = _sample_by_class(broad_rows)

    fast_discovered_rows = [
        serialize_market(market, now=current_time, classification=classify_audit_category(market))
        for market in deduped_fast.values()
    ]
    fast_discovered_rows = _sort_market_rows(fast_discovered_rows)

    fast_tradeable_markets = filter_basic_markets(list(deduped_fast.values()))
    fast_tradeable_rows = [
        serialize_market(market, now=current_time, classification=classify_audit_category(market))
        for market in fast_tradeable_markets
    ]
    fast_tradeable_rows = _sort_market_rows(fast_tradeable_rows)
    fast_tradeable_counts = _count_by_class(fast_tradeable_rows)
    fast_tradeable_samples = _sample_by_class(fast_tradeable_rows)

    broad_tradeable_rows = [
        serialize_market(market, now=current_time, classification=classify_audit_category(market))
        for market in deduped_broad.values()
        if market_passes_thresholds(market, now=current_time)
    ]
    broad_tradeable_rows = _sort_market_rows(broad_tradeable_rows)

    recommendation = derive_recommendation(fast_tradeable_rows, fast_discovered_rows, broad_tradeable_rows)
    conclusion = build_conclusion(
        tagged_event_count=tagged_event_count,
        broad_counts=broad_counts,
        fast_discovered_count=len(fast_discovered_rows),
        fast_tradeable_count=len(fast_tradeable_rows),
        fast_tradeable_counts=fast_tradeable_counts,
        recommendation=recommendation,
    )

    return {
        "generated_at": current_time.isoformat(),
        "sources": {
            "gamma_events": GAMMA_EVENTS_URL,
            "fast_market_discovery": "src.pipeline_refresh.load_fast_markets",
            "fast_market_tradeable_filter": "src.pipeline_refresh.filter_basic_markets",
        },
        "classification_schema": list(AUDIT_CLASSES),
        "broad_crypto_tagged_universe": {
            "tagged_event_count": tagged_event_count,
            "market_count": len(broad_rows),
            "counts_by_class": broad_counts,
            "sample_markets_by_class": broad_samples,
        },
        "fast_market_tradeable_set": {
            "discovered_market_count": len(fast_discovered_rows),
            "tradeable_market_count": len(fast_tradeable_rows),
            "counts_by_class": fast_tradeable_counts,
            "sample_markets_by_class": fast_tradeable_samples,
            "markets": fast_tradeable_rows,
        },
        "recommendation": recommendation,
        "conclusion": conclusion,
        "classification_counts": {
            **broad_counts,
            **_legacy_counts(list(deduped_broad.values())),
        },
        "tradeable_at_008": broad_tradeable_rows,
    }


def write_report(payload: dict[str, Any], *, output_path: Path = REPORT_PATH) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return output_path


def run_audit() -> dict[str, Any]:
    now = utc_now()
    events = fetch_open_events()
    broad_markets, tagged_event_count = extract_crypto_tagged_markets(events, now=now)
    payload = build_crypto_category_audit(
        broad_markets,
        now=now,
        tagged_event_count=tagged_event_count,
    )
    write_report(payload)
    return payload


def main() -> int:
    payload = run_audit()

    broad = payload["broad_crypto_tagged_universe"]
    fast = payload["fast_market_tradeable_set"]
    print(f"Wrote crypto category audit to {REPORT_PATH}")
    print(
        "Broad crypto-tagged universe: "
        f"{broad['market_count']} markets across {broad['tagged_event_count']} tagged events"
    )
    for class_name, count in broad["counts_by_class"].items():
        print(f"  broad {class_name}: {count}")
    print(
        "Fast-market tradeable set: "
        f"{fast['tradeable_market_count']} markets "
        f"({fast['discovered_market_count']} discovered before the basic tradeability filter)"
    )
    for class_name, count in fast["counts_by_class"].items():
        print(f"  fast {class_name}: {count}")
    print(f"Recommendation: {payload['recommendation']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
