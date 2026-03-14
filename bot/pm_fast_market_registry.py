#!/usr/bin/env python3
"""Dynamic Polymarket fast-market registry (pm_fast_market_registry.v1).

Discovers ALL eligible Polymarket crypto candle markets every cycle.
Never hard-codes market counts — count is always derived from live API results.

Schema: pm_fast_market_registry.v1
Output: reports/market_registry/latest.json (refreshed each cycle)
Join key: condition_id -> joinable to market_envelope.v1 on condition_id

Architecture:
    1. Fetch all active Gamma markets with crypto keywords (paginated)
    2. Classify each market: asset, timeframe, token IDs, window, fee_flag
    3. Mark eligible/ineligible with explicit reasons
    4. Fetch CLOB top-of-book for every eligible market's YES token
    5. Compute quote staleness; disable cascade execution if >60s stale
    6. Write canonical registry JSON + latest.json symlink/copy
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import sys

CURRENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = CURRENT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

logger = logging.getLogger("JJ.pm_registry")

# ---------------------------------------------------------------------------
# Schema version and API endpoints
# ---------------------------------------------------------------------------
SCHEMA_VERSION = "pm_fast_market_registry.v1"
GAMMA_API_BASE = "https://gamma-api.polymarket.com"
CLOB_API_BASE = "https://clob.polymarket.com"
DATA_API_BASE = "https://data-api.polymarket.com"

HTTP_TIMEOUT_SECONDS = 20
GAMMA_PAGE_SIZE = 200
GAMMA_MAX_PAGES = 20
QUOTE_STALENESS_LIMIT_SECONDS = 60
FAST_MARKET_MAX_HOURS_TO_CLOSE = 24.0

# Cascade execution halts when freshness of this registry exceeds this threshold
REGISTRY_FRESHNESS_LIMIT_SECONDS = 60

# Asset regex patterns (order matters — check BTC before ETH)
_ASSET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("btc", re.compile(r"\b(?:bitcoin|btc)\b", re.IGNORECASE)),
    ("eth", re.compile(r"\b(?:ethereum|eth)\b", re.IGNORECASE)),
    ("sol", re.compile(r"\b(?:solana|sol)\b", re.IGNORECASE)),
    ("xrp", re.compile(r"\b(?:xrp|ripple)\b", re.IGNORECASE)),
    ("doge", re.compile(r"\b(?:dogecoin|doge)\b", re.IGNORECASE)),
    ("bnb", re.compile(r"\b(?:binance\s*coin|bnb)\b", re.IGNORECASE)),
    ("avax", re.compile(r"\b(?:avalanche|avax)\b", re.IGNORECASE)),
    ("ada", re.compile(r"\b(?:cardano|ada)\b", re.IGNORECASE)),
    ("matic", re.compile(r"\b(?:polygon|matic)\b", re.IGNORECASE)),
    ("link", re.compile(r"\b(?:chainlink|link)\b", re.IGNORECASE)),
)

# Timeframe explicit token patterns (applied to question text)
_TIMEFRAME_TOKENS: tuple[tuple[str, int, re.Pattern[str]], ...] = (
    ("1m", 1, re.compile(r"(?<!\$)\b(?:1m|1-?minute)\b", re.IGNORECASE)),
    ("5m", 5, re.compile(r"(?<!\$)\b(?:5m|5-?minute)\b", re.IGNORECASE)),
    ("10m", 10, re.compile(r"(?<!\$)\b(?:10m|10-?minute)\b", re.IGNORECASE)),
    ("15m", 15, re.compile(r"(?<!\$)\b(?:15m|15-?minute)\b", re.IGNORECASE)),
    ("30m", 30, re.compile(r"(?<!\$)\b(?:30m|30-?minute)\b", re.IGNORECASE)),
    ("1h", 60, re.compile(r"(?<!\$)\b(?:1h|1-?hour)\b", re.IGNORECASE)),
    ("2h", 120, re.compile(r"(?<!\$)\b(?:2h|2-?hour)\b", re.IGNORECASE)),
    ("3h", 180, re.compile(r"(?<!\$)\b(?:3h|3-?hour)\b", re.IGNORECASE)),
    ("4h", 240, re.compile(r"(?<!\$)\b(?:4h|4-?hour)\b", re.IGNORECASE)),
)

# Time range pattern for inferred window: "12:00 pm - 12:05 pm" style
_TIME_RANGE_RE = re.compile(
    r"(\d{1,2}):(\d{2})\s*(am|pm)\s*[-–—]\s*(\d{1,2}):(\d{2})\s*(am|pm)",
    re.IGNORECASE,
)

# Crypto detection gate: at least one of these must match for a Gamma market
# to be considered as a crypto candle candidate
_CRYPTO_GATE_RE = re.compile(
    r"\b(?:bitcoin|btc|ethereum|eth|solana|sol|xrp|ripple|dogecoin|doge|"
    r"binance\s*coin|bnb|avalanche|avax|cardano|ada|polygon|matic|chainlink|link|"
    r"crypto|altcoin)\b",
    re.IGNORECASE,
)

# "Up or down" style phrasing — strong signal this is a candle binary market
_CANDLE_PHRASING_RE = re.compile(
    r"\b(?:up\s+or\s+down|will\s+.*\s+(?:be\s+)?(?:above|below|higher|lower))\b",
    re.IGNORECASE,
)
_THRESHOLD_PHRASING_RE = re.compile(
    r"\b(?:will\s+the\s+price\s+of\s+.+?\s+be\s+(?:above|below)|"
    r"(?:above|below|over|under)\s+\$?\d[\d,]*(?:\.\d+)?)\b",
    re.IGNORECASE,
)
_RANGE_PHRASING_RE = re.compile(
    r"\b(?:between\s+\$?\d[\d,]*(?:\.\d+)?\s+and\s+\$?\d[\d,]*(?:\.\d+)?|range)\b",
    re.IGNORECASE,
)
_LONG_HORIZON_RE = re.compile(
    r"\b(?:this\s+year|next\s+year|before\s+\w+|in\s+20\d{2}|by\s+(?:dec|january|february|march|april|may|june|july|august|september|october|november))\b",
    re.IGNORECASE,
)

GAMMA_QUERY_PLANS: tuple[dict[str, Any], ...] = (
    {"order": "createdAt", "ascending": False},
    {"order": "endDate", "ascending": True},
    {"order": "volume24hr", "ascending": False},
)

# Priority lane definitions: (asset, timeframe_minutes_max) -> (rank, label)
def _classify_priority(asset: str, timeframe_minutes: int | None) -> tuple[int, str]:
    if asset == "btc":
        if timeframe_minutes is not None and timeframe_minutes <= 5:
            return 0, "btc_5m"
        if timeframe_minutes is not None and timeframe_minutes <= 15:
            return 1, "btc_15m"
        if timeframe_minutes is not None and timeframe_minutes <= 240:
            return 2, "btc_4h"
        return 2, "btc_intraday"
    if asset == "eth":
        return 3, "eth_intraday"
    if asset == "sol":
        return 4, "sol_intraday"
    if asset == "xrp":
        return 5, "xrp_intraday"
    if asset == "doge":
        return 6, "doge_intraday"
    return 7, "other_crypto"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class RegistryRow:
    """One canonical row in pm_fast_market_registry.v1."""
    condition_id: str
    market_id: str
    event_slug: str
    event_title: str
    question: str
    asset: str                          # btc/eth/sol/xrp/doge/bnb/other_crypto
    timeframe: str                      # 5m/15m/4h/intraday/unknown
    timeframe_minutes: int | None       # integer minutes; None if unknown
    yes_token_id: str
    no_token_id: str
    window_start_utc: str | None        # ISO or None
    window_end_utc: str | None          # ISO or None (=endDate on Gamma)
    fee_flag: str                       # maker_0pct | taker_fee | unknown
    enable_order_book: bool
    eligible: bool
    ineligible_reasons: list[str]
    priority_lane: str                  # btc_5m / btc_15m / btc_4h / eth_intraday / ...
    priority_rank: int                  # lower = higher priority
    # Live quote fields (populated by CLOB fetch, None until fetched)
    best_bid: float | None = None
    best_ask: float | None = None
    mid: float | None = None
    spread: float | None = None
    quote_staleness_seconds: float | None = None
    quote_fetched_at: str | None = None  # ISO
    # join key for market_envelope.v1
    envelope_join_key: str = ""         # same as condition_id

    def __post_init__(self) -> None:
        self.envelope_join_key = self.condition_id


@dataclass
class RegistryHealth:
    gamma_ok: bool = False
    clob_ok: bool = False
    gamma_pages_fetched: int = 0
    gamma_markets_raw: int = 0
    discovery_duration_seconds: float = 0.0
    quote_fetch_duration_seconds: float = 0.0
    quote_age_max_seconds: float | None = None
    staleness_breach_count: int = 0
    cascade_execution_enabled: bool = False
    last_error: str | None = None


@dataclass
class RegistrySummary:
    total_discovered: int = 0
    eligible_count: int = 0
    ineligible_count: int = 0
    asset_breakdown: dict[str, int] = field(default_factory=dict)
    timeframe_breakdown: dict[str, int] = field(default_factory=dict)
    priority_lane_breakdown: dict[str, int] = field(default_factory=dict)
    quote_fetched_count: int = 0
    quote_freshness_ok: bool = False


@dataclass
class MarketRegistry:
    schema_version: str
    generated_at: str
    freshness_seconds: float
    registry: list[RegistryRow]
    summary: RegistrySummary
    health: RegistryHealth


# ---------------------------------------------------------------------------
# Pure utility functions
# ---------------------------------------------------------------------------

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False


def _parse_iso_datetime(value: Any) -> datetime | None:
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
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_json_list(raw: Any) -> list[str]:
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError:
            decoded = [p.strip() for p in text.split(",") if p.strip()]
        raw = decoded
    out: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
    return out


def detect_asset(text: str) -> str:
    """Return the primary crypto asset from question/title text."""
    for asset, pattern in _ASSET_PATTERNS:
        if pattern.search(text):
            return asset
    return "other_crypto"


def detect_timeframe(text: str) -> tuple[str, int | None]:
    """Return (timeframe_label, timeframe_minutes) from question text.

    First checks explicit token patterns, then infers from a time-range.
    Returns ("unknown", None) if no timeframe can be determined.
    """
    for label, minutes, pattern in _TIMEFRAME_TOKENS:
        if pattern.search(text):
            return label, minutes

    # Try inferring from a time range like "12:00 pm - 12:05 pm"
    match = _TIME_RANGE_RE.search(text)
    if match:
        inferred = _minutes_from_time_range_match(match)
        if inferred is not None and inferred > 0:
            label = _minutes_to_label(inferred)
            return label, inferred

    # Fallback: if the text says "intraday" treat as intraday/unknown minutes
    if re.search(r"\bintraday\b", text, re.IGNORECASE):
        return "intraday", None

    return "unknown", None


def _minutes_from_time_range_match(match: re.Match[str]) -> int | None:
    try:
        def to_minutes(h: str, m: str, ampm: str) -> int:
            hour = int(h) % 12
            if ampm.lower() == "pm":
                hour += 12
            return hour * 60 + int(m)

        start = to_minutes(match.group(1), match.group(2), match.group(3))
        end = to_minutes(match.group(4), match.group(5), match.group(6))
        if end < start:
            end += 24 * 60
        return end - start
    except (IndexError, ValueError):
        return None


def _minutes_to_label(minutes: int) -> str:
    if minutes == 1:
        return "1m"
    if minutes == 5:
        return "5m"
    if minutes == 10:
        return "10m"
    if minutes == 15:
        return "15m"
    if minutes == 30:
        return "30m"
    if minutes == 60:
        return "1h"
    if minutes == 120:
        return "2h"
    if minutes == 180:
        return "3h"
    if minutes == 240:
        return "4h"
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    return f"{hours}h"


def classify_fee_flag(enable_order_book: bool) -> str:
    """Classify fee structure.

    Polymarket candle markets with an active order book use 0% maker fee.
    Markets without order books fall back to taker pricing.
    """
    if enable_order_book:
        return "maker_0pct"
    return "unknown"


def is_crypto_candle_candidate(
    question: str,
    event_title: str,
    *,
    end_date: str | None = None,
) -> bool:
    """True if this Gamma market looks like a fast crypto candle/range/threshold market."""
    combined = f"{question} {event_title}"
    if not _CRYPTO_GATE_RE.search(combined):
        return False
    if _LONG_HORIZON_RE.search(combined):
        return False
    timeframe_label, timeframe_minutes = detect_timeframe(combined)
    if timeframe_minutes is not None:
        return True
    if _CANDLE_PHRASING_RE.search(combined):
        return True
    if _THRESHOLD_PHRASING_RE.search(combined):
        return True
    if _RANGE_PHRASING_RE.search(combined):
        return True
    if end_date:
        end_dt = _parse_iso_datetime(end_date)
        if end_dt is not None:
            hours_to_close = (end_dt - _now_utc()).total_seconds() / 3600.0
            if 0.0 < hours_to_close <= FAST_MARKET_MAX_HOURS_TO_CLOSE:
                return True
    return False


def build_ineligible_reasons(
    *,
    yes_token_id: str,
    no_token_id: str,
    enable_order_book: bool,
    asset: str,
    window_end_utc: str | None,
    now: datetime,
) -> list[str]:
    reasons: list[str] = []
    if not yes_token_id:
        reasons.append("missing_yes_token")
    if not no_token_id:
        reasons.append("missing_no_token")
    if not enable_order_book:
        reasons.append("orderbook_disabled")
    if asset == "other_crypto":
        reasons.append("unrecognised_asset")
    if window_end_utc:
        try:
            end_dt = datetime.fromisoformat(window_end_utc.replace("Z", "+00:00"))
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
            hours_to_close = (end_dt - now).total_seconds() / 3600.0
            if hours_to_close <= 0.0:
                reasons.append("already_expired")
            elif hours_to_close > FAST_MARKET_MAX_HOURS_TO_CLOSE:
                reasons.append("outside_fast_window")
        except ValueError:
            pass
    return reasons


def parse_window_end(end_date_str: str | None) -> str | None:
    if not end_date_str:
        return None
    # Return as-is if already ISO
    try:
        dt = datetime.fromisoformat(str(end_date_str).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except ValueError:
        return end_date_str


# ---------------------------------------------------------------------------
# Gamma market discovery (HTTP, no aiohttp dependency in this module)
# ---------------------------------------------------------------------------

DEFAULT_HEADERS = {
    "User-Agent": "pm-fast-market-registry/1.0",
    "Accept": "application/json",
}


def _http_json(url: str, timeout: float = HTTP_TIMEOUT_SECONDS) -> Any:
    request = Request(url, headers=DEFAULT_HEADERS)
    with urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    return json.loads(body)


def _fetch_gamma_markets_page(
    *,
    offset: int,
    limit: int,
    active: bool = True,
    closed: bool = False,
    order: str | None = None,
    ascending: bool | None = None,
) -> list[dict[str, Any]]:
    """Fetch one page of Gamma /markets with crypto-friendly filters."""
    params: dict[str, str] = {
        "active": "true" if active else "false",
        "closed": "true" if closed else "false",
        "limit": str(max(1, limit)),
        "offset": str(max(0, offset)),
    }
    if order:
        params["order"] = order
    if ascending is not None:
        params["ascending"] = "true" if ascending else "false"
    url = f"{GAMMA_API_BASE}/markets?{urlencode(params)}"
    payload = _http_json(url)
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        data = payload.get("data", [])
        return [dict(row) for row in data if isinstance(row, dict)] if isinstance(data, list) else []
    return []


def discover_crypto_candle_markets(
    *,
    max_pages: int = GAMMA_MAX_PAGES,
    page_size: int = GAMMA_PAGE_SIZE,
) -> tuple[list[dict[str, Any]], int, bool]:
    """Discover all active crypto candle markets from Gamma.

    Returns:
        (markets, pages_fetched, gamma_ok)
        Markets are raw Gamma dicts. Count is NEVER hard-coded — always derived
        from live API results.
    """
    all_markets: list[dict[str, Any]] = []
    pages_fetched = 0
    seen_ids: set[str] = set()
    try:
        pages_per_plan = max(1, max_pages // max(1, len(GAMMA_QUERY_PLANS)))
        for plan in GAMMA_QUERY_PLANS:
            for page in range(pages_per_plan):
                offset = page * page_size
                batch = _fetch_gamma_markets_page(
                    offset=offset,
                    limit=page_size,
                    order=plan.get("order"),
                    ascending=plan.get("ascending"),
                )
                pages_fetched += 1
                if not batch:
                    break
                for market in batch:
                    market_id = str(
                        market.get("conditionId")
                        or market.get("condition_id")
                        or market.get("id")
                        or ""
                    ).strip()
                    if market_id and market_id in seen_ids:
                        continue
                    if market_id:
                        seen_ids.add(market_id)
                    all_markets.append(market)
                if len(batch) < page_size:
                    break
    except Exception as exc:
        logger.warning("gamma_discovery_failed err=%s", exc)
        return all_markets, pages_fetched, False

    # Filter to crypto candle candidates only
    candidates = [
        m for m in all_markets
        if is_crypto_candle_candidate(
            str(m.get("question") or ""),
            str(m.get("groupItemTitle") or m.get("title") or ""),
            end_date=str(m.get("endDate") or ""),
        )
    ]
    return candidates, pages_fetched, True


# ---------------------------------------------------------------------------
# CLOB quote fetch
# ---------------------------------------------------------------------------

def _fetch_clob_book(token_id: str) -> dict[str, Any] | None:
    """Fetch top-of-book for a single token from Polymarket CLOB REST API."""
    url = f"{CLOB_API_BASE}/book?token_id={token_id}"
    try:
        payload = _http_json(url)
        if isinstance(payload, dict):
            return payload
    except Exception as exc:
        logger.debug("clob_book_fetch_failed token=%s err=%s", token_id[:12], exc)
    return None


def _extract_quote_from_book(book: dict[str, Any] | None) -> tuple[float | None, float | None]:
    """Return (best_bid, best_ask) from a CLOB book response."""
    if not book:
        return None, None

    bids = book.get("bids") or []
    asks = book.get("asks") or []

    best_bid: float | None = None
    best_ask: float | None = None

    if isinstance(bids, list) and bids:
        prices = [_safe_float(b.get("price") if isinstance(b, dict) else b) for b in bids]
        valid_prices = [p for p in prices if p is not None]
        if valid_prices:
            best_bid = max(valid_prices)

    if isinstance(asks, list) and asks:
        prices = [_safe_float(a.get("price") if isinstance(a, dict) else a) for a in asks]
        valid_prices = [p for p in prices if p is not None]
        if valid_prices:
            best_ask = min(valid_prices)

    return best_bid, best_ask


def fetch_quotes_for_registry(
    rows: list[RegistryRow],
    *,
    now: datetime | None = None,
) -> tuple[bool, int]:
    """Fetch CLOB quotes for all eligible registry rows in-place.

    Returns (clob_ok, staleness_breach_count).
    Modifies rows in-place with bid/ask/mid/staleness fields.
    """
    if now is None:
        now = _now_utc()

    eligible_rows = [r for r in rows if r.eligible and r.yes_token_id]
    if not eligible_rows:
        return True, 0

    clob_ok = True
    staleness_breach_count = 0

    for row in eligible_rows:
        try:
            book = _fetch_clob_book(row.yes_token_id)
            fetch_time = _now_utc()
            best_bid, best_ask = _extract_quote_from_book(book)

            row.best_bid = best_bid
            row.best_ask = best_ask
            row.quote_fetched_at = fetch_time.isoformat()

            if best_bid is not None and best_ask is not None:
                row.mid = round((best_bid + best_ask) / 2.0, 6)
                row.spread = round(best_ask - best_bid, 6)

            # Final quote staleness is computed against the registry completion time.
            row.quote_staleness_seconds = None

        except Exception as exc:
            logger.warning("quote_fetch_failed market=%s err=%s", row.condition_id[:12], exc)
            clob_ok = False

    return clob_ok, staleness_breach_count


# ---------------------------------------------------------------------------
# Registry builder
# ---------------------------------------------------------------------------

def build_registry_row(raw: dict[str, Any], now: datetime) -> RegistryRow | None:
    """Build one RegistryRow from a raw Gamma market dict.

    Returns None if the market lacks a condition_id.
    """
    # Extract IDs
    condition_id = str(
        raw.get("conditionId") or raw.get("condition_id") or
        raw.get("market_id") or raw.get("id") or ""
    ).strip()
    if not condition_id:
        return None

    market_id = str(raw.get("id") or raw.get("market_id") or condition_id).strip()
    event_slug = str(raw.get("eventSlug") or raw.get("slug") or "").strip()
    event_title = str(raw.get("groupItemTitle") or raw.get("title") or raw.get("eventTitle") or "").strip()
    question = str(raw.get("question") or raw.get("title") or "").strip()

    # Token IDs
    clob_token_ids = _parse_json_list(raw.get("clobTokenIds"))
    yes_token_id = clob_token_ids[0] if clob_token_ids else ""
    no_token_id = clob_token_ids[1] if len(clob_token_ids) > 1 else ""

    # Asset and timeframe
    search_text = f"{question} {event_title}"
    asset = detect_asset(search_text)
    timeframe, timeframe_minutes = detect_timeframe(search_text)

    # Window
    window_end_utc = parse_window_end(str(raw.get("endDate") or ""))

    # Fee flag
    enable_order_book = _safe_bool(raw.get("enableOrderBook"))
    fee_flag = classify_fee_flag(enable_order_book)

    # Eligibility
    ineligible_reasons = build_ineligible_reasons(
        yes_token_id=yes_token_id,
        no_token_id=no_token_id,
        enable_order_book=enable_order_book,
        asset=asset,
        window_end_utc=window_end_utc,
        now=now,
    )
    eligible = len(ineligible_reasons) == 0

    # Priority
    priority_rank, priority_lane = _classify_priority(asset, timeframe_minutes)

    return RegistryRow(
        condition_id=condition_id,
        market_id=market_id,
        event_slug=event_slug,
        event_title=event_title,
        question=question,
        asset=asset,
        timeframe=timeframe,
        timeframe_minutes=timeframe_minutes,
        yes_token_id=yes_token_id,
        no_token_id=no_token_id,
        window_start_utc=None,  # parsed from question — not available in Gamma directly
        window_end_utc=window_end_utc,
        fee_flag=fee_flag,
        enable_order_book=enable_order_book,
        eligible=eligible,
        ineligible_reasons=ineligible_reasons,
        priority_lane=priority_lane,
        priority_rank=priority_rank,
    )


def build_registry(
    *,
    fetch_quotes: bool = True,
    max_pages: int = GAMMA_MAX_PAGES,
    page_size: int = GAMMA_PAGE_SIZE,
) -> MarketRegistry:
    """Discover and build the full dynamic fast-market registry.

    This is the main entry point. Never assumes a fixed count of markets.
    """
    discovery_start = time.monotonic()
    now = _now_utc()

    # 1. Discover
    raw_markets, pages_fetched, gamma_ok = discover_crypto_candle_markets(
        max_pages=max_pages,
        page_size=page_size,
    )
    discovery_duration = time.monotonic() - discovery_start

    # 2. Build rows
    rows: list[RegistryRow] = []
    for raw in raw_markets:
        row = build_registry_row(raw, now)
        if row is not None:
            rows.append(row)

    # Deduplicate by condition_id (keep first)
    seen: set[str] = set()
    deduped: list[RegistryRow] = []
    for row in rows:
        if row.condition_id not in seen:
            seen.add(row.condition_id)
            deduped.append(row)
    rows = deduped

    # Sort: eligible first, then by priority_rank, then by priority_lane
    rows.sort(key=lambda r: (0 if r.eligible else 1, r.priority_rank, r.priority_lane))

    # 3. Fetch CLOB quotes
    quote_start = time.monotonic()
    clob_ok = True
    staleness_breach_count = 0
    if fetch_quotes:
        clob_ok, staleness_breach_count = fetch_quotes_for_registry(rows, now=now)
    quote_duration = time.monotonic() - quote_start
    generated_at_dt = _now_utc()
    generated_at = generated_at_dt.isoformat()

    computed_staleness_breach_count = 0
    for row in rows:
        fetched_at = _parse_iso_datetime(row.quote_fetched_at)
        if fetched_at is None:
            row.quote_staleness_seconds = None
            continue
        row.quote_staleness_seconds = max(0.0, (generated_at_dt - fetched_at).total_seconds())
        if row.quote_staleness_seconds > QUOTE_STALENESS_LIMIT_SECONDS:
            computed_staleness_breach_count += 1
    staleness_breach_count = max(staleness_breach_count, computed_staleness_breach_count)

    # 4. Build summary (never hard-codes counts)
    eligible_rows = [r for r in rows if r.eligible]
    asset_breakdown: dict[str, int] = {}
    timeframe_breakdown: dict[str, int] = {}
    priority_lane_breakdown: dict[str, int] = {}
    for row in eligible_rows:
        asset_breakdown[row.asset] = asset_breakdown.get(row.asset, 0) + 1
        timeframe_breakdown[row.timeframe] = timeframe_breakdown.get(row.timeframe, 0) + 1
        priority_lane_breakdown[row.priority_lane] = priority_lane_breakdown.get(row.priority_lane, 0) + 1

    quote_fetched_count = sum(1 for r in rows if r.quote_fetched_at is not None)
    quote_ages = [
        r.quote_staleness_seconds for r in rows if r.quote_staleness_seconds is not None
    ]
    quote_freshness_ok = (
        staleness_breach_count == 0
        and len(eligible_rows) > 0
        and quote_fetched_count > 0
    ) if fetch_quotes else True

    max_quote_age: float | None = max(quote_ages) if quote_ages else None

    summary = RegistrySummary(
        total_discovered=len(rows),
        eligible_count=len(eligible_rows),
        ineligible_count=len(rows) - len(eligible_rows),
        asset_breakdown=asset_breakdown,
        timeframe_breakdown=timeframe_breakdown,
        priority_lane_breakdown=priority_lane_breakdown,
        quote_fetched_count=quote_fetched_count,
        quote_freshness_ok=quote_freshness_ok,
    )

    # 5. Cascade execution gate:
    # Disable cascade if registry is stale, quote staleness breaches, or gamma failed
    cascade_execution_enabled = (
        gamma_ok
        and len(eligible_rows) > 0
        and staleness_breach_count == 0
    )

    health = RegistryHealth(
        gamma_ok=gamma_ok,
        clob_ok=clob_ok,
        gamma_pages_fetched=pages_fetched,
        gamma_markets_raw=len(raw_markets),
        discovery_duration_seconds=round(discovery_duration, 3),
        quote_fetch_duration_seconds=round(quote_duration, 3),
        quote_age_max_seconds=max_quote_age,
        staleness_breach_count=staleness_breach_count,
        cascade_execution_enabled=cascade_execution_enabled,
    )

    freshness_seconds = (time.monotonic() - discovery_start)

    return MarketRegistry(
        schema_version=SCHEMA_VERSION,
        generated_at=generated_at,
        freshness_seconds=round(freshness_seconds, 3),
        registry=rows,
        summary=summary,
        health=health,
    )


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def registry_to_dict(registry: MarketRegistry) -> dict[str, Any]:
    """Convert MarketRegistry to a JSON-serializable dict.

    Top-level live summary fields (eligible_count, eligible_assets,
    quote_coverage_ratio, staleness_breach_count, cascade_execution_enabled)
    are promoted for direct downstream consumption by Instance 5 and 6
    without nested path parsing.
    """
    eligible_rows = [r for r in registry.registry if r.eligible]
    eligible_assets = sorted({r.asset for r in eligible_rows})

    # Quote coverage: eligible rows with both bid and ask populated
    quotes_populated = sum(
        1 for r in eligible_rows
        if r.best_bid is not None and r.best_ask is not None
    )
    quote_coverage_ratio = (
        round(quotes_populated / len(eligible_rows), 4)
        if len(eligible_rows) > 0 else 0.0
    )

    return {
        "schema_version": registry.schema_version,
        "generated_at": registry.generated_at,
        "freshness_seconds": registry.freshness_seconds,
        # Top-level live summary fields for direct downstream consumption
        "eligible_count": registry.summary.eligible_count,
        "eligible_assets": eligible_assets,
        "quote_coverage_ratio": quote_coverage_ratio,
        "staleness_breach_count": registry.health.staleness_breach_count,
        "cascade_execution_enabled": registry.health.cascade_execution_enabled,
        "registry": [asdict(row) for row in registry.registry],
        "summary": asdict(registry.summary),
        "health": asdict(registry.health),
    }


def write_registry(
    registry: MarketRegistry,
    *,
    output_dir: Path,
) -> tuple[Path, Path]:
    """Write registry JSON and update latest.json.

    Returns (timestamped_path, latest_path).
    The latest.json is always a plain copy (no symlinks for Windows compat).
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    timestamped_path = output_dir / f"market_registry_{stamp}.json"
    latest_path = output_dir / "latest.json"

    payload = registry_to_dict(registry)
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"

    timestamped_path.write_text(text)
    latest_path.write_text(text)

    return timestamped_path, latest_path


def get_registry_freshness_seconds(latest_path: Path) -> float | None:
    """Return age of the latest registry in seconds, or None if missing."""
    if not latest_path.exists():
        return None
    try:
        payload = json.loads(latest_path.read_text())
        generated_at = payload.get("generated_at")
        if not generated_at:
            return None
        dt = datetime.fromisoformat(str(generated_at).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (_now_utc() - dt).total_seconds()
    except Exception:
        return None


def is_registry_stale(latest_path: Path, limit_seconds: float = REGISTRY_FRESHNESS_LIMIT_SECONDS) -> bool:
    """True if latest.json is missing or older than limit_seconds."""
    age = get_registry_freshness_seconds(latest_path)
    if age is None:
        return True
    return age > limit_seconds
