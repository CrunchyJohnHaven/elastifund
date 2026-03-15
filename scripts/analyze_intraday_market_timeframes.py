#!/usr/bin/env python3
"""Instance H: Analyze 15m/1h crypto candle market expansion viability.

Outputs a JSON report with:
  - market availability by asset/timeframe (BTC/ETH/SOL, 15m and 1h)
  - liquidity proxies (volume24hr, market spread, live book spread)
  - price-band dynamics checks for 0.90-0.95 entries from trade prints
  - per-lane liquidity verdicts to drive service rollout
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp

GAMMA_URL = "https://gamma-api.polymarket.com/markets"
CLOB_BOOK_URL = "https://clob.polymarket.com/book"
DATA_TRADES_URL = "https://data-api.polymarket.com/trades"
ET_ZONE = ZoneInfo("America/New_York")
UA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; Elastifund-Instance-H/1.0)",
    "Accept": "application/json",
}
DEFAULT_OUTPUT = Path("reports/instance_h_market_expansion.json")

ASSETS_15M = ("btc", "eth", "sol")
ASSETS_1H = ("bitcoin", "ethereum", "solana")
ASSET_ALIAS = {
    "btc": "BTC",
    "eth": "ETH",
    "sol": "SOL",
    "bitcoin": "BTC",
    "ethereum": "ETH",
    "solana": "SOL",
}


@dataclass(frozen=True)
class MarketLane:
    asset: str
    timeframe: str
    slug: str
    condition_id: str
    active: bool
    closed: bool
    event_start_ts: int | None
    best_bid: float | None
    best_ask: float | None
    volume24hr: float
    yes_token_id: str | None
    no_token_id: str | None


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_iso_ts(value: Any) -> int | None:
    text = str(value or "").strip()
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
    return int(dt.timestamp())


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    return float(statistics.median(values))


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return float(sum(values) / len(values))


def _to_json_num(value: float | None, digits: int = 6) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _parse_clob_token_ids(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    text = str(raw or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if str(item).strip()]
    return []


def _slug_for_hourly(asset_word: str, dt_et: datetime) -> str:
    hour12 = dt_et.hour % 12 or 12
    ampm = "am" if dt_et.hour < 12 else "pm"
    month = dt_et.strftime("%B").lower()
    return f"{asset_word}-up-or-down-{month}-{dt_et.day}-{dt_et.year}-{hour12}{ampm}-et"


def build_15m_slugs(now_utc: datetime, sample_hours: int) -> list[str]:
    floor = int(now_utc.timestamp()) // 900 * 900
    start = floor - sample_hours * 3600
    end = floor + 2 * 900
    slugs: list[str] = []
    for ts in range(start, end + 1, 900):
        for asset in ASSETS_15M:
            slugs.append(f"{asset}-updown-15m-{ts}")
    return slugs


def build_1h_slugs(now_utc: datetime, sample_hours: int) -> list[str]:
    now_et = now_utc.astimezone(ET_ZONE)
    floor_et = now_et.replace(minute=0, second=0, microsecond=0)
    slugs: list[str] = []
    for offset in range(-sample_hours, 3):
        slot = floor_et + timedelta(hours=offset)
        for asset in ASSETS_1H:
            slugs.append(_slug_for_hourly(asset, slot))
    return slugs


async def fetch_json(
    session: aiohttp.ClientSession,
    *,
    url: str,
    params: dict[str, Any],
    semaphore: asyncio.Semaphore,
) -> Any:
    async with semaphore:
        try:
            async with session.get(url, params=params, headers=UA_HEADERS, timeout=20) as resp:
                if resp.status != 200:
                    return None
                return await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return None


async def fetch_market_by_slug(
    session: aiohttp.ClientSession, slug: str, semaphore: asyncio.Semaphore
) -> dict[str, Any] | None:
    payload = await fetch_json(
        session,
        url=GAMMA_URL,
        params={"slug": slug, "limit": 1},
        semaphore=semaphore,
    )
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        return payload[0]
    return None


async def fetch_trades(
    session: aiohttp.ClientSession, condition_id: str, semaphore: asyncio.Semaphore
) -> list[dict[str, Any]]:
    payload = await fetch_json(
        session,
        url=DATA_TRADES_URL,
        params={"conditionId": condition_id, "limit": 500},
        semaphore=semaphore,
    )
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    return []


async def fetch_book(
    session: aiohttp.ClientSession, token_id: str, semaphore: asyncio.Semaphore
) -> dict[str, Any] | None:
    payload = await fetch_json(
        session,
        url=CLOB_BOOK_URL,
        params={"token_id": token_id},
        semaphore=semaphore,
    )
    return payload if isinstance(payload, dict) else None


def _book_best(book: dict[str, Any] | None) -> tuple[float | None, float | None]:
    if not isinstance(book, dict):
        return None, None
    bids = book.get("bids") if isinstance(book.get("bids"), list) else []
    asks = book.get("asks") if isinstance(book.get("asks"), list) else []
    bid_prices = [
        _safe_float(level.get("price"), None)
        for level in bids
        if isinstance(level, dict) and _safe_float(level.get("price"), None) is not None
    ]
    ask_prices = [
        _safe_float(level.get("price"), None)
        for level in asks
        if isinstance(level, dict) and _safe_float(level.get("price"), None) is not None
    ]
    best_bid = max((float(v) for v in bid_prices), default=None)
    best_ask = min((float(v) for v in ask_prices if float(v) > 0), default=None)
    return best_bid, best_ask


def _market_from_payload(payload: dict[str, Any], timeframe: str) -> MarketLane:
    slug = str(payload.get("slug") or "").strip()
    cond = str(payload.get("conditionId") or payload.get("id") or "").strip()
    if timeframe == "15m":
        asset_key = slug.split("-", 1)[0]
    else:
        asset_key = slug.split("-", 1)[0]
    event_start_ts = _parse_iso_ts(payload.get("eventStartTime"))
    token_ids = _parse_clob_token_ids(payload.get("clobTokenIds"))
    yes_token = token_ids[0] if len(token_ids) >= 1 else None
    no_token = token_ids[1] if len(token_ids) >= 2 else None
    volume24hr = _safe_float(payload.get("volume24hr"), None)
    if volume24hr is None:
        volume24hr = _safe_float(payload.get("volume24hrClob"), None)
    if volume24hr is None:
        volume24hr = _safe_float(payload.get("volume"), 0.0)
    return MarketLane(
        asset=ASSET_ALIAS.get(asset_key.lower(), asset_key.upper()),
        timeframe=timeframe,
        slug=slug,
        condition_id=cond,
        active=bool(payload.get("active")),
        closed=bool(payload.get("closed")),
        event_start_ts=event_start_ts,
        best_bid=_safe_float(payload.get("bestBid"), None),
        best_ask=_safe_float(payload.get("bestAsk"), None),
        volume24hr=float(volume24hr or 0.0),
        yes_token_id=yes_token,
        no_token_id=no_token,
    )


def _trade_band_metrics(trades: list[dict[str, Any]], event_start_ts: int | None) -> dict[str, Any]:
    if not trades:
        return {
            "trade_count": 0,
            "has_price_ge_0_90": False,
            "has_price_band_0_90_0_95": False,
            "first_band_offset_sec": None,
        }
    prices: list[float] = []
    band_offsets: list[int] = []
    for trade in trades:
        price = _safe_float(trade.get("price"), None)
        ts_raw = trade.get("timestamp")
        try:
            ts = int(ts_raw) if ts_raw is not None else None
        except (TypeError, ValueError):
            ts = None
        if price is None:
            continue
        prices.append(float(price))
        if 0.90 <= float(price) <= 0.95 and ts is not None and event_start_ts is not None:
            band_offsets.append(int(ts - event_start_ts))
    return {
        "trade_count": len(trades),
        "has_price_ge_0_90": any(price >= 0.90 for price in prices),
        "has_price_band_0_90_0_95": any(0.90 <= price <= 0.95 for price in prices),
        "first_band_offset_sec": min(band_offsets) if band_offsets else None,
    }


def _liquidity_verdict(
    *,
    median_volume24hr: float | None,
    median_market_spread: float | None,
    pct_markets_with_trades: float,
) -> dict[str, Any]:
    checks = {
        "median_volume24hr_ge_2000": bool((median_volume24hr or 0.0) >= 2000.0),
        "median_market_spread_le_0_03": bool(
            median_market_spread is not None and median_market_spread <= 0.03
        ),
        "pct_markets_with_trades_ge_0_70": bool(pct_markets_with_trades >= 0.70),
    }
    is_liquid = all(checks.values())
    return {"is_liquid": is_liquid, "checks": checks}


def summarize_lane(
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    volumes = [float(row["market"].volume24hr) for row in rows]
    market_spreads = []
    trades_with_data = 0
    trades_total = 0
    markets_ge_090 = 0
    markets_band_090_095 = 0
    band_offsets: list[float] = []

    live_yes_spreads: list[float] = []
    live_no_spreads: list[float] = []
    conviction_asks: list[float] = []
    conviction_in_band = 0
    live_book_count = 0

    active_count = 0
    closed_count = 0

    for row in rows:
        market: MarketLane = row["market"]
        if market.active:
            active_count += 1
        if market.closed:
            closed_count += 1
        if market.best_bid is not None and market.best_ask is not None and market.best_ask > market.best_bid:
            market_spreads.append(float(market.best_ask - market.best_bid))

        trade_metrics = row["trade_metrics"]
        if trade_metrics["trade_count"] > 0:
            trades_with_data += 1
            trades_total += int(trade_metrics["trade_count"])
            if trade_metrics["has_price_ge_0_90"]:
                markets_ge_090 += 1
            if trade_metrics["has_price_band_0_90_0_95"]:
                markets_band_090_095 += 1
            if trade_metrics["first_band_offset_sec"] is not None:
                band_offsets.append(float(trade_metrics["first_band_offset_sec"]))

        live_book = row["live_book"]
        if live_book is None:
            continue
        live_book_count += 1
        yes_spread = live_book.get("yes_spread")
        no_spread = live_book.get("no_spread")
        if yes_spread is not None:
            live_yes_spreads.append(float(yes_spread))
        if no_spread is not None:
            live_no_spreads.append(float(no_spread))
        conviction_ask = live_book.get("conviction_ask")
        if conviction_ask is not None:
            conviction_asks.append(float(conviction_ask))
            if 0.90 <= float(conviction_ask) <= 0.95:
                conviction_in_band += 1

    sample_size = len(rows)
    pct_with_trades = (trades_with_data / sample_size) if sample_size else 0.0
    verdict = _liquidity_verdict(
        median_volume24hr=_median(volumes),
        median_market_spread=_median(market_spreads),
        pct_markets_with_trades=pct_with_trades,
    )
    return {
        "sample_size": sample_size,
        "active_markets": active_count,
        "closed_markets": closed_count,
        "volume24hr": {
            "avg": _to_json_num(_mean(volumes)),
            "median": _to_json_num(_median(volumes)),
            "max": _to_json_num(max(volumes) if volumes else None),
        },
        "market_spread": {
            "avg": _to_json_num(_mean(market_spreads)),
            "median": _to_json_num(_median(market_spreads)),
        },
        "trade_dynamics": {
            "markets_with_trade_data": trades_with_data,
            "avg_trades_per_market_with_data": _to_json_num(
                (trades_total / trades_with_data) if trades_with_data else None
            ),
            "pct_markets_with_price_ge_0_90": _to_json_num(
                (markets_ge_090 / trades_with_data) if trades_with_data else None
            ),
            "pct_markets_with_price_band_0_90_0_95": _to_json_num(
                (markets_band_090_095 / trades_with_data) if trades_with_data else None
            ),
            "median_first_band_offset_sec": _to_json_num(_median(band_offsets), digits=2),
        },
        "live_book": {
            "markets_with_live_book": live_book_count,
            "yes_spread_median": _to_json_num(_median(live_yes_spreads)),
            "no_spread_median": _to_json_num(_median(live_no_spreads)),
            "conviction_ask_median": _to_json_num(_median(conviction_asks)),
            "pct_conviction_asks_in_0_90_0_95": _to_json_num(
                (conviction_in_band / live_book_count) if live_book_count else None
            ),
        },
        "liquidity_verdict": verdict,
    }


async def run(sample_hours: int) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    slugs_15m = build_15m_slugs(now, sample_hours)
    slugs_1h = build_1h_slugs(now, sample_hours)

    connector = aiohttp.TCPConnector(limit=60)
    semaphore = asyncio.Semaphore(30)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks_15m = [fetch_market_by_slug(session, slug, semaphore) for slug in slugs_15m]
        tasks_1h = [fetch_market_by_slug(session, slug, semaphore) for slug in slugs_1h]
        payloads_15m = await asyncio.gather(*tasks_15m)
        payloads_1h = await asyncio.gather(*tasks_1h)

        markets: list[MarketLane] = []
        seen: set[str] = set()
        for payload in payloads_15m:
            if not isinstance(payload, dict):
                continue
            lane = _market_from_payload(payload, "15m")
            if lane.slug in seen:
                continue
            seen.add(lane.slug)
            markets.append(lane)
        for payload in payloads_1h:
            if not isinstance(payload, dict):
                continue
            lane = _market_from_payload(payload, "1h")
            if lane.slug in seen:
                continue
            seen.add(lane.slug)
            markets.append(lane)

        trade_tasks = [
            fetch_trades(session, market.condition_id, semaphore)
            if market.condition_id
            else asyncio.sleep(0, result=[])
            for market in markets
        ]
        trade_results = await asyncio.gather(*trade_tasks)

        book_jobs: list[tuple[int, str, str]] = []
        for idx, market in enumerate(markets):
            if not market.active:
                continue
            if market.yes_token_id:
                book_jobs.append((idx, "yes", market.yes_token_id))
            if market.no_token_id:
                book_jobs.append((idx, "no", market.no_token_id))

        book_tasks = [fetch_book(session, token_id, semaphore) for _, _, token_id in book_jobs]
        book_results = await asyncio.gather(*book_tasks) if book_tasks else []

    token_books: dict[tuple[int, str], dict[str, Any] | None] = {}
    for (idx, side, _), book in zip(book_jobs, book_results):
        token_books[(idx, side)] = book

    rows: list[dict[str, Any]] = []
    for idx, market in enumerate(markets):
        trades = trade_results[idx] if idx < len(trade_results) else []
        trade_metrics = _trade_band_metrics(trades, market.event_start_ts)
        live_book = None
        if market.active:
            yes_book = token_books.get((idx, "yes"))
            no_book = token_books.get((idx, "no"))
            yes_bid, yes_ask = _book_best(yes_book)
            no_bid, no_ask = _book_best(no_book)
            yes_spread = (yes_ask - yes_bid) if yes_ask is not None and yes_bid is not None else None
            no_spread = (no_ask - no_bid) if no_ask is not None and no_bid is not None else None
            conviction_ask = None
            if yes_ask is not None or no_ask is not None:
                conviction_ask = max(
                    [value for value in (yes_ask, no_ask) if value is not None],
                    default=None,
                )
            live_book = {
                "yes_spread": yes_spread,
                "no_spread": no_spread,
                "conviction_ask": conviction_ask,
            }
        rows.append({"market": market, "trade_metrics": trade_metrics, "live_book": live_book})

    lanes: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        market: MarketLane = row["market"]
        key = (market.timeframe, market.asset)
        lanes.setdefault(key, []).append(row)

    summary: dict[str, Any] = {}
    liquid_assets_15m: list[str] = []
    for timeframe in ("15m", "1h"):
        summary[timeframe] = {}
        for asset in ("BTC", "ETH", "SOL"):
            lane_rows = lanes.get((timeframe, asset), [])
            lane_summary = summarize_lane(lane_rows)
            summary[timeframe][asset] = lane_summary
            if timeframe == "15m" and lane_summary["liquidity_verdict"]["is_liquid"]:
                liquid_assets_15m.append(asset)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sample_hours": sample_hours,
        "sample_counts": {
            "candidate_slugs_15m": len(slugs_15m),
            "candidate_slugs_1h": len(slugs_1h),
            "markets_found": len(markets),
        },
        "timeframe_summary": summary,
        "instance_h_rollout_recommendation": {
            "liquid_15m_assets": liquid_assets_15m,
            "should_create_15m_services": len(liquid_assets_15m) > 0,
            "note": (
                "Create 15m maker services only for assets flagged liquid. "
                "Keep 1h in analysis-only mode until spread and fill behavior stabilize."
            ),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-hours", type=int, default=24, help="Historical lookback window in hours.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="JSON report path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = asyncio.run(run(sample_hours=max(1, int(args.sample_hours))))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    recommendation = payload["instance_h_rollout_recommendation"]
    print(
        "Instance H scan complete | markets_found="
        f"{payload['sample_counts']['markets_found']} | "
        f"liquid_15m_assets={recommendation['liquid_15m_assets']} | output={output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
