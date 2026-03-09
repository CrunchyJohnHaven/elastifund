#!/usr/bin/env python3
"""Scan live Polymarket markets and rank maker-velocity opportunities."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import aiohttp

GAMMA_URL = "https://gamma-api.polymarket.com/markets"
CLOB_BOOK_URL = "https://clob.polymarket.com/book"
REPORT_PATH = Path("reports/live_market_scan.json")
MAX_RESOLUTION_HOURS = 24.0
PRICE_MIN = 0.05
PRICE_MAX = 0.95
MIN_NOTIONAL_USD = 5.0
TOP_N = 30
ORDERBOOK_CANDIDATE_LIMIT = 200
TICK_SIZE = 0.01
REQUEST_TIMEOUT_SECONDS = 15
MAX_GAMMA_PAGES = 120

ALLOWED_CATEGORIES: dict[str, int] = {
    "politics": 3,
    "weather": 3,
    "economic": 2,
    "crypto": 3,
    "financial_speculation": 1,
    "geopolitical": 1,
}
REJECT_CATEGORIES = {"sports", "fed_rates", "unknown"}
KEYWORDS: dict[str, tuple[str, ...]] = {
    "crypto": ("bitcoin", "btc", "ethereum", "eth", "solana", "xrp", "crypto", "up or down"),
    "politics": ("election", "president", "prime minister", "senate", "congress", "campaign", "trump", "biden"),
    "weather": ("temperature", "rain", "snow", "hurricane", "storm", "flood", "weather"),
    "economic": ("inflation", "cpi", "gdp", "jobs", "unemployment", "retail sales", "fomc"),
    "financial_speculation": ("stock", "nasdaq", "s&p", "dow", "ipo", "market cap", "fdv"),
    "geopolitical": ("war", "ceasefire", "invade", "taiwan", "russia", "ukraine", "nato", "sanctions"),
    "sports": ("nba", "nfl", "mlb", "soccer", "fifa", "super bowl", "playoffs", "championship", " vs ", "o/u "),
}


@dataclass
class Candidate:
    question: str
    slug: str
    condition_id: str
    category: str
    resolution_date: str
    hours_to_resolution: float
    yes_price: float
    no_price: float
    velocity_score: float
    recommended_side: str
    yes_token_id: str
    no_token_id: str
    tokens: list[dict[str, str]]


@dataclass
class BookMetrics:
    best_bid: float
    best_ask: float
    bid_depth_usd: float
    ask_depth_usd: float


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def normalize_category(value: Any) -> str:
    raw = _safe_str(value).strip().lower().replace(" ", "_")
    return raw or "unknown"


def infer_category(question: str, fallback: str) -> str:
    text = _safe_str(question).lower()
    for category, keys in KEYWORDS.items():
        if any(keyword_matches(text, key) for key in keys):
            return category
    return fallback


def looks_like_sports_question(question: str) -> bool:
    text = _safe_str(question).lower()
    return any(keyword_matches(text, marker) for marker in (" vs ", " vs. ", "o/u ", "over/under", "mlb", "nba", "nfl", "nhl", "fifa", "world cup"))


def keyword_matches(text: str, keyword: str) -> bool:
    if not keyword:
        return False
    if " " in keyword or "/" in keyword or "." in keyword:
        return keyword in text
    return re.search(rf"\\b{re.escape(keyword)}\\b", text) is not None


def parse_iso_datetime(value: Any) -> datetime | None:
    text = _safe_str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def market_resolution_dt(market: dict[str, Any]) -> datetime | None:
    for key in (
        "end_date_iso",
        "endDate",
        "resolution_date",
        "resolutionDate",
        "closedTime",
        "endTime",
    ):
        dt = parse_iso_datetime(market.get(key))
        if dt is not None:
            return dt
    return None


def hours_to_resolution(market: dict[str, Any], now: datetime) -> float | None:
    dt = market_resolution_dt(market)
    if dt is not None:
        hours = (dt - now).total_seconds() / 3600.0
        if hours <= 0:
            return None
        return hours

    question = _safe_str(market.get("question")).lower()
    if any(key in question for key in ("5-minute", "5 minute", " 5m", " 5 m")):
        return 5.0 / 60.0
    if any(key in question for key in ("15-minute", "15 minute", " 15m", " 15 m", "up or down")):
        return 15.0 / 60.0
    if "today" in question or "tonight" in question:
        return 12.0
    if "tomorrow" in question:
        return 24.0

    match = re.search(r"\\b(\\d{1,2}):(\\d{2})\\b", question)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2))
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate = candidate + timedelta(days=1)
        return max(0.01, (candidate - now).total_seconds() / 3600.0)

    return None


def parse_outcome_prices(raw: Any) -> list[float]:
    if isinstance(raw, list):
        return [_safe_float(item) for item in raw]
    text = _safe_str(raw).strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parts = [part.strip() for part in text.split(",") if part.strip()]
        return [_safe_float(part) for part in parts]
    if isinstance(parsed, list):
        return [_safe_float(item) for item in parsed]
    return []


def extract_yes_no_prices(market: dict[str, Any]) -> tuple[float | None, float | None]:
    tokens = market.get("tokens")
    if isinstance(tokens, list) and tokens:
        yes_price = None
        no_price = None
        for token in tokens:
            if not isinstance(token, dict):
                continue
            outcome = _safe_str(token.get("outcome")).strip().lower()
            price = token.get("price")
            if price is None:
                price = token.get("last_price")
            if price is None:
                price = token.get("lastPrice")
            parsed = _safe_float(price, default=-1.0)
            if not (0.0 < parsed < 1.0):
                continue
            if outcome == "yes":
                yes_price = parsed
            elif outcome == "no":
                no_price = parsed
        if yes_price is not None:
            if no_price is None:
                no_price = max(0.0, min(1.0, 1.0 - yes_price))
            return yes_price, no_price

    parsed_prices = parse_outcome_prices(market.get("outcomePrices"))
    if len(parsed_prices) >= 2:
        return parsed_prices[0], parsed_prices[1]

    yes = _safe_float(market.get("yes_price"), default=-1.0)
    no = _safe_float(market.get("no_price"), default=-1.0)
    if 0.0 < yes < 1.0 and 0.0 < no < 1.0:
        return yes, no
    return None, None


def extract_token_id_map(market: dict[str, Any]) -> tuple[str, str, list[dict[str, str]]]:
    yes_token = ""
    no_token = ""
    token_rows: list[dict[str, str]] = []

    tokens = market.get("tokens")
    if isinstance(tokens, list):
        for token in tokens:
            if not isinstance(token, dict):
                continue
            outcome = _safe_str(token.get("outcome")).strip().upper()
            token_id = _safe_str(token.get("token_id") or token.get("tokenId") or token.get("id")).strip()
            if not token_id or outcome not in {"YES", "NO"}:
                continue
            token_rows.append({"token_id": token_id, "outcome": outcome})
            if outcome == "YES":
                yes_token = token_id
            elif outcome == "NO":
                no_token = token_id

    if yes_token and no_token:
        return yes_token, no_token, token_rows

    raw_clob = market.get("clobTokenIds") or market.get("clob_token_ids")
    ids: list[str] = []
    if isinstance(raw_clob, list):
        ids = [_safe_str(item).strip() for item in raw_clob if _safe_str(item).strip()]
    else:
        text = _safe_str(raw_clob).strip()
        if text:
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                ids = [_safe_str(item).strip() for item in parsed if _safe_str(item).strip()]

    if len(ids) >= 2:
        yes_token = yes_token or ids[0]
        no_token = no_token or ids[1]
        if not token_rows:
            token_rows = [
                {"token_id": yes_token, "outcome": "YES"},
                {"token_id": no_token, "outcome": "NO"},
            ]

    return yes_token, no_token, token_rows


def compute_velocity_score(yes_price: float, resolution_hours: float) -> float:
    if resolution_hours <= 0:
        return 0.0
    estimated_edge = abs(0.5 - yes_price)
    return estimated_edge / resolution_hours


def to_candidate(market: dict[str, Any], now: datetime) -> Candidate | None:
    question = _safe_str(market.get("question"))
    if looks_like_sports_question(question):
        return None

    category = infer_category(_safe_str(market.get("question")), normalize_category(market.get("category")))
    if category in REJECT_CATEGORIES or category not in ALLOWED_CATEGORIES:
        return None

    hrs = hours_to_resolution(market, now)
    if hrs is None or hrs > MAX_RESOLUTION_HOURS:
        return None

    yes_price, no_price = extract_yes_no_prices(market)
    if yes_price is None or no_price is None:
        return None
    if not (PRICE_MIN <= yes_price <= PRICE_MAX):
        return None

    yes_token_id, no_token_id, token_rows = extract_token_id_map(market)
    if not yes_token_id and not no_token_id:
        return None

    side = "YES" if yes_price < 0.50 else "NO"
    velocity = compute_velocity_score(yes_price, hrs)

    resolution_dt = market_resolution_dt(market)
    resolution_iso = resolution_dt.isoformat() if resolution_dt is not None else ""

    return Candidate(
        question=_safe_str(market.get("question")),
        slug=_safe_str(market.get("slug")),
        condition_id=_safe_str(market.get("conditionId") or market.get("condition_id") or market.get("id")),
        category=category,
        resolution_date=resolution_iso,
        hours_to_resolution=hrs,
        yes_price=yes_price,
        no_price=no_price,
        velocity_score=velocity,
        recommended_side=side,
        yes_token_id=yes_token_id,
        no_token_id=no_token_id,
        tokens=token_rows,
    )


def parse_book_metrics(book_payload: dict[str, Any]) -> BookMetrics:
    bids = book_payload.get("bids") if isinstance(book_payload.get("bids"), list) else []
    asks = book_payload.get("asks") if isinstance(book_payload.get("asks"), list) else []

    best_bid = 0.0
    best_ask = 0.0
    if bids:
        best_bid = max(_safe_float(level.get("price")) for level in bids if isinstance(level, dict))
    if asks:
        prices = [_safe_float(level.get("price")) for level in asks if isinstance(level, dict)]
        prices = [p for p in prices if p > 0]
        if prices:
            best_ask = min(prices)

    bid_depth = 0.0
    ask_depth = 0.0
    for level in bids[:3]:
        if isinstance(level, dict):
            bid_depth += _safe_float(level.get("price")) * _safe_float(level.get("size"))
    for level in asks[:3]:
        if isinstance(level, dict):
            ask_depth += _safe_float(level.get("price")) * _safe_float(level.get("size"))

    return BookMetrics(best_bid=best_bid, best_ask=best_ask, bid_depth_usd=bid_depth, ask_depth_usd=ask_depth)


async def fetch_markets(session: aiohttp.ClientSession) -> list[dict[str, Any]]:
    markets: list[dict[str, Any]] = []
    offset = 0
    limit = 100
    seen_ids: set[str] = set()

    for _ in range(MAX_GAMMA_PAGES):
        params = {"active": "true", "closed": "false", "limit": str(limit), "offset": str(offset)}
        async with session.get(GAMMA_URL, params=params, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            resp.raise_for_status()
            payload = await resp.json()

        if not isinstance(payload, list) or not payload:
            break

        page_new = 0
        for item in payload:
            if not isinstance(item, dict):
                continue
            market_id = _safe_str(item.get("id") or item.get("conditionId") or item.get("slug")).strip()
            if market_id and market_id in seen_ids:
                continue
            if market_id:
                seen_ids.add(market_id)
            markets.append(item)
            page_new += 1

        if page_new == 0:
            break

        if len(payload) < limit:
            break
        offset += limit

    return markets


async def fetch_book(session: aiohttp.ClientSession, token_id: str, semaphore: asyncio.Semaphore) -> BookMetrics | None:
    token = _safe_str(token_id).strip()
    if not token:
        return None
    async with semaphore:
        try:
            async with session.get(CLOB_BOOK_URL, params={"token_id": token}, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
                if resp.status != 200:
                    return None
                payload = await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return None
    if not isinstance(payload, dict):
        return None
    return parse_book_metrics(payload)


def recommended_price(best_bid: float) -> float:
    price = best_bid + TICK_SIZE
    if price < TICK_SIZE:
        price = TICK_SIZE
    if price > 0.99:
        price = 0.99
    return round(price, 4)


def ranked_market_rows(candidates: list[Candidate], book_lookup: dict[str, BookMetrics]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for item in candidates:
        selected_token = item.yes_token_id if item.recommended_side == "YES" else item.no_token_id
        selected_book = book_lookup.get(selected_token)
        if selected_book is None:
            continue

        spread = 0.0
        if selected_book.best_ask > 0 and selected_book.best_bid > 0:
            spread = max(0.0, selected_book.best_ask - selected_book.best_bid)

        rec_price = recommended_price(selected_book.best_bid)
        shares = round(MIN_NOTIONAL_USD / rec_price, 4) if rec_price > 0 else 0.0

        rows.append(
            {
                "question": item.question,
                "slug": item.slug,
                "condition_id": item.condition_id,
                "tokens": item.tokens,
                "category": item.category,
                "yes_price": round(item.yes_price, 4),
                "no_price": round(item.no_price, 4),
                "spread": round(spread, 4),
                "bid_depth_usd": round(selected_book.bid_depth_usd, 4),
                "ask_depth_usd": round(selected_book.ask_depth_usd, 4),
                "liquidity_depth_usd": round(selected_book.bid_depth_usd + selected_book.ask_depth_usd, 4),
                "resolution_date": item.resolution_date,
                "hours_to_resolution": round(item.hours_to_resolution, 4),
                "velocity_score": round(item.velocity_score, 8),
                "recommended_side": item.recommended_side,
                "recommended_price": rec_price,
                "recommended_shares": shares,
                "recommended_notional_usd": MIN_NOTIONAL_USD,
            }
        )

    rows.sort(key=lambda row: row["velocity_score"], reverse=True)
    return rows[:TOP_N]


async def run_scan() -> dict[str, Any]:
    now = datetime.now(timezone.utc)

    connector = aiohttp.TCPConnector(limit=40)
    async with aiohttp.ClientSession(connector=connector) as session:
        markets = await fetch_markets(session)
        candidates = [candidate for market in markets if (candidate := to_candidate(market, now)) is not None]
        candidates.sort(key=lambda row: row.velocity_score, reverse=True)
        orderbook_candidates = candidates[:ORDERBOOK_CANDIDATE_LIMIT]

        semaphore = asyncio.Semaphore(20)
        unique_tokens = set()
        for item in orderbook_candidates:
            if item.yes_token_id:
                unique_tokens.add(item.yes_token_id)
            if item.no_token_id:
                unique_tokens.add(item.no_token_id)

        token_list = sorted(unique_tokens)
        tasks = [fetch_book(session, token, semaphore) for token in token_list]
        metrics = await asyncio.gather(*tasks)

    book_lookup: dict[str, BookMetrics] = {}
    for token, book in zip(token_list, metrics):
        if book is not None:
            book_lookup[token] = book

    top_rows = ranked_market_rows(orderbook_candidates, book_lookup)
    return {
        "scan_timestamp": datetime.now(timezone.utc).isoformat(),
        "total_markets_scanned": len(markets),
        "markets_passing_filters": len(candidates),
        "markets_with_orderbook": len(top_rows),
        "top_markets": top_rows,
    }


def main() -> int:
    report = asyncio.run(run_scan())
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(f"Scan complete: {report['total_markets_scanned']} markets scanned")
    print(f"Passing filters: {report['markets_passing_filters']}")
    print(f"Top ranked output: {len(report['top_markets'])} markets")
    print(f"Report written: {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
