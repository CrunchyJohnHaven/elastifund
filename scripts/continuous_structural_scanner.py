#!/usr/bin/env python3
"""Continuous structural opportunity scanner for Polymarket.

Runs locally on John's Mac. Scans ALL active Polymarket markets for three
classes of structural alpha:

1. Resolution sniping — near-certain outcomes priced below $1.00
2. Negative-risk arbitrage — multi-outcome groups where YES prices sum < $0.97
3. Stale quote detection — wide spreads with depth on one side

Writes opportunity signals to JSON files for the VPS strike desk to consume.
Does NOT place trades directly.

Usage:
    python3 scripts/continuous_structural_scanner.py          # run continuously
    python3 scripts/continuous_structural_scanner.py --once   # single cycle
    python3 scripts/continuous_structural_scanner.py --interval 60  # 60s cycles

Author: JJ (autonomous)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiohttp

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GAMMA_URL = "https://gamma-api.polymarket.com/markets"
CLOB_BOOK_URL = "https://clob.polymarket.com/book"
DEFAULT_OUTPUT = Path("reports/structural_opportunities.json")
DEFAULT_SIGNAL_FEED = Path("reports/structural_signal_feed.json")
DEFAULT_INTERVAL = 30
MAX_CONCURRENT_BOOK_FETCHES = 20
REQUEST_TIMEOUT = 15
MAX_GAMMA_PAGES = 200
GAMMA_PAGE_SIZE = 100

# Scanner thresholds
RESOLUTION_SNIPER_THRESHOLD = 0.94
NEG_RISK_SUM_THRESHOLD = 0.97
STALE_SPREAD_THRESHOLD = 0.10
STALE_DEPTH_THRESHOLD = 50.0

# Filter thresholds
MIN_PROFIT_PER_SHARE = 0.02  # after 2% winner fee
MIN_VOLUME_24H = 100.0
MIN_HOURS_TO_RESOLUTION = 1.0
MIN_ASK_DEPTH = 10.0

# Winner fee on Polymarket
WINNER_FEE = 0.02

logger = logging.getLogger("JJ.structural_scanner")

# VPS push config
VPS_USER = "ubuntu"
VPS_HOST = "34.244.34.108"
VPS_KEY = str(Path.home() / ".ssh" / "lightsail_new.pem")
VPS_REMOTE_PATH = "/home/ubuntu/polymarket-trading-bot/reports/structural_signal_feed.json"


async def _push_to_vps(local_path: Path) -> None:
    """SCP the signal feed to VPS for strike desk consumption."""
    if not local_path.exists():
        return
    cmd = [
        "scp", "-i", VPS_KEY,
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=5",
        str(local_path),
        f"{VPS_USER}@{VPS_HOST}:{VPS_REMOTE_PATH}",
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
        if proc.returncode == 0:
            logger.debug("Signal feed pushed to VPS")
        else:
            logger.warning("VPS push failed (rc=%d): %s", proc.returncode, stderr.decode()[:100])
    except asyncio.TimeoutError:
        logger.warning("VPS push timed out")
    except Exception as exc:
        logger.warning("VPS push error: %s", exc)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class Opportunity:
    scanner: str  # "resolution_sniper" | "neg_risk" | "stale_quote"
    market_id: str
    question: str
    direction: str  # "YES" | "NO"
    token_id: str
    entry_price: float
    expected_profit_per_share: float
    confidence: float
    evidence: str
    detected_at: str
    ttl_seconds: int
    size_hint_usd: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ParsedMarket:
    market_id: str
    condition_id: str
    question: str
    yes_price: float
    no_price: float
    yes_token_id: str
    no_token_id: str
    volume_24h: float
    liquidity: float
    end_date: str
    hours_to_resolution: float


@dataclass
class BookSnapshot:
    bids: list[dict[str, float]]
    asks: list[dict[str, float]]
    best_bid: float
    best_ask: float
    spread: float
    bid_depth_usd: float
    ask_depth_usd: float


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_json_field(raw: Any) -> list[Any]:
    if isinstance(raw, list):
        return list(raw)
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass
    return []


def _parse_iso_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
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
    return dt


def _hours_until(dt: datetime | None) -> float:
    if dt is None:
        return 0.0
    now = datetime.now(tz=timezone.utc)
    delta = (dt - now).total_seconds() / 3600.0
    return max(0.0, delta)


def _extract_end_date(market: dict[str, Any]) -> datetime | None:
    for key in ("end_date_iso", "endDate", "resolution_date",
                "resolutionDate", "closedTime", "endTime"):
        dt = _parse_iso_datetime(market.get(key))
        if dt is not None:
            return dt
    return None


def _extract_yes_price(market: dict[str, Any]) -> float | None:
    """Extract YES price from various Gamma API field shapes."""
    # tokens array
    tokens = market.get("tokens")
    if isinstance(tokens, list):
        for token in tokens:
            if not isinstance(token, dict):
                continue
            outcome = str(token.get("outcome") or "").strip().lower()
            if outcome == "yes":
                price = token.get("price") or token.get("last_price") or token.get("lastPrice")
                p = _safe_float(price, -1.0)
                if 0.0 < p < 1.0:
                    return p

    # outcomePrices
    op = _parse_json_field(market.get("outcomePrices"))
    if len(op) >= 2:
        p = _safe_float(op[0], -1.0)
        if 0.0 <= p <= 1.0:
            return p

    # bestBid/bestAsk midpoint
    bid = market.get("bestBid")
    ask = market.get("bestAsk")
    if bid is not None and ask is not None:
        b, a = _safe_float(bid, -1.0), _safe_float(ask, -1.0)
        if 0.0 <= b <= 1.0 and 0.0 <= a <= 1.0 and a >= b:
            return (b + a) / 2.0

    return None


def _extract_token_ids(market: dict[str, Any]) -> tuple[str, str]:
    """Return (yes_token_id, no_token_id)."""
    yes_token = ""
    no_token = ""

    tokens = market.get("tokens")
    if isinstance(tokens, list):
        for token in tokens:
            if not isinstance(token, dict):
                continue
            outcome = str(token.get("outcome") or "").strip().upper()
            token_id = str(
                token.get("token_id") or token.get("tokenId") or token.get("id") or ""
            ).strip()
            if token_id and outcome == "YES":
                yes_token = token_id
            elif token_id and outcome == "NO":
                no_token = token_id

    if yes_token and no_token:
        return yes_token, no_token

    raw_clob = market.get("clobTokenIds") or market.get("clob_token_ids")
    ids = _parse_json_field(raw_clob)
    if not ids and isinstance(raw_clob, str) and raw_clob.strip():
        ids = [s.strip() for s in raw_clob.split(",") if s.strip()]

    if len(ids) >= 2:
        yes_token = yes_token or str(ids[0]).strip()
        no_token = no_token or str(ids[1]).strip()

    return yes_token, no_token


def parse_market(raw: dict[str, Any]) -> ParsedMarket | None:
    """Parse a raw Gamma API market dict into a ParsedMarket."""
    market_id = str(raw.get("id") or raw.get("conditionId") or "").strip()
    if not market_id:
        return None

    question = str(raw.get("question") or "").strip()
    if not question:
        return None

    yes_price = _extract_yes_price(raw)
    if yes_price is None:
        return None
    no_price = max(0.0, min(1.0, 1.0 - yes_price))

    yes_token, no_token = _extract_token_ids(raw)
    condition_id = str(raw.get("conditionId") or raw.get("condition_id") or "").strip()

    end_dt = _extract_end_date(raw)
    hours = _hours_until(end_dt) if end_dt else 0.0
    end_date_str = end_dt.isoformat() if end_dt else ""

    volume_24h = _safe_float(raw.get("volume24hr") or raw.get("volume_24h"), 0.0)
    liquidity = _safe_float(raw.get("liquidity"), 0.0)

    return ParsedMarket(
        market_id=market_id,
        condition_id=condition_id,
        question=question,
        yes_price=yes_price,
        no_price=no_price,
        yes_token_id=yes_token,
        no_token_id=no_token,
        volume_24h=volume_24h,
        liquidity=liquidity,
        end_date=end_date_str,
        hours_to_resolution=hours,
    )


def parse_book(payload: dict[str, Any]) -> BookSnapshot:
    """Parse a CLOB book response into a BookSnapshot."""
    raw_bids = payload.get("bids") or []
    raw_asks = payload.get("asks") or []

    bids = []
    for level in raw_bids:
        if isinstance(level, dict):
            bids.append({
                "price": _safe_float(level.get("price")),
                "size": _safe_float(level.get("size")),
            })

    asks = []
    for level in raw_asks:
        if isinstance(level, dict):
            asks.append({
                "price": _safe_float(level.get("price")),
                "size": _safe_float(level.get("size")),
            })

    best_bid = max((b["price"] for b in bids), default=0.0)
    ask_prices = [a["price"] for a in asks if a["price"] > 0]
    best_ask = min(ask_prices) if ask_prices else 0.0

    spread = max(0.0, best_ask - best_bid) if best_ask > 0 and best_bid > 0 else 0.0

    bid_depth = sum(b["price"] * b["size"] for b in bids)
    ask_depth = sum(a["price"] * a["size"] for a in asks)

    return BookSnapshot(
        bids=bids,
        asks=asks,
        best_bid=best_bid,
        best_ask=best_ask,
        spread=spread,
        bid_depth_usd=bid_depth,
        ask_depth_usd=ask_depth,
    )


# ---------------------------------------------------------------------------
# Market fetching
# ---------------------------------------------------------------------------


async def fetch_all_markets(session: aiohttp.ClientSession) -> list[dict[str, Any]]:
    """Fetch all active markets from Gamma API with pagination."""
    markets: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    offset = 0

    for _ in range(MAX_GAMMA_PAGES):
        params = {
            "active": "true",
            "closed": "false",
            "limit": str(GAMMA_PAGE_SIZE),
            "offset": str(offset),
        }
        try:
            async with session.get(
                GAMMA_URL, params=params, timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
            ) as resp:
                if resp.status == 429:
                    logger.warning("Gamma API rate limited at offset=%d, backing off", offset)
                    await asyncio.sleep(5)
                    continue
                resp.raise_for_status()
                payload = await resp.json()
        except Exception as exc:
            logger.error("fetch_all_markets error at offset=%d: %s", offset, exc)
            break

        if not isinstance(payload, list) or not payload:
            break

        page_new = 0
        for item in payload:
            if not isinstance(item, dict):
                continue
            mid = str(item.get("id") or item.get("conditionId") or "").strip()
            if mid and mid in seen_ids:
                continue
            if mid:
                seen_ids.add(mid)
            markets.append(item)
            page_new += 1

        if page_new == 0 or len(payload) < GAMMA_PAGE_SIZE:
            break
        offset += GAMMA_PAGE_SIZE

    return markets


async def fetch_book_async(
    session: aiohttp.ClientSession,
    token_id: str,
    semaphore: asyncio.Semaphore,
) -> tuple[str, BookSnapshot | None]:
    """Fetch a single order book with concurrency limiting."""
    if not token_id:
        return token_id, None

    async with semaphore:
        try:
            async with session.get(
                CLOB_BOOK_URL,
                params={"token_id": token_id},
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                if resp.status == 429:
                    logger.warning("CLOB rate limited for token %s", token_id[:12])
                    await asyncio.sleep(2)
                    return token_id, None
                if resp.status != 200:
                    return token_id, None
                payload = await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.debug("Book fetch failed for %s: %s", token_id[:12], exc)
            return token_id, None

    if not isinstance(payload, dict):
        return token_id, None
    return token_id, parse_book(payload)


# ---------------------------------------------------------------------------
# Scanner: Resolution Sniper
# ---------------------------------------------------------------------------


def scan_resolution_sniper(markets: list[ParsedMarket]) -> list[Opportunity]:
    """Find markets where one side is priced >= 0.94 (near-certain outcome)."""
    opportunities: list[Opportunity] = []
    now_iso = datetime.now(tz=timezone.utc).isoformat()

    for m in markets:
        # Volume filter
        if m.volume_24h < MIN_VOLUME_24H:
            continue
        # Resolution time filter
        if m.hours_to_resolution < MIN_HOURS_TO_RESOLUTION:
            continue

        # Check YES side
        if m.yes_price >= RESOLUTION_SNIPER_THRESHOLD:
            gross_profit = 1.0 - m.yes_price
            net_profit = gross_profit - WINNER_FEE
            if net_profit < MIN_PROFIT_PER_SHARE:
                continue
            if not m.yes_token_id:
                continue

            # Confidence scales with price
            confidence = min(0.99, 0.85 + (m.yes_price - 0.94) * 2.5)
            ttl = int(m.hours_to_resolution * 3600)

            opportunities.append(Opportunity(
                scanner="resolution_sniper",
                market_id=m.market_id,
                question=m.question,
                direction="YES",
                token_id=m.yes_token_id,
                entry_price=m.yes_price,
                expected_profit_per_share=round(net_profit, 4),
                confidence=round(confidence, 3),
                evidence=f"YES price {m.yes_price:.3f} >= {RESOLUTION_SNIPER_THRESHOLD} — near-certain outcome, profit {net_profit:.4f}/share after fee",
                detected_at=now_iso,
                ttl_seconds=ttl,
                size_hint_usd=round(min(20.0, 5.0 / max(0.01, net_profit)), 2),
            ))

        # Check NO side
        if m.no_price >= RESOLUTION_SNIPER_THRESHOLD:
            gross_profit = 1.0 - m.no_price
            net_profit = gross_profit - WINNER_FEE
            if net_profit < MIN_PROFIT_PER_SHARE:
                continue
            if not m.no_token_id:
                continue

            confidence = min(0.99, 0.85 + (m.no_price - 0.94) * 2.5)
            ttl = int(m.hours_to_resolution * 3600)

            opportunities.append(Opportunity(
                scanner="resolution_sniper",
                market_id=m.market_id,
                question=m.question,
                direction="NO",
                token_id=m.no_token_id,
                entry_price=m.no_price,
                expected_profit_per_share=round(net_profit, 4),
                confidence=round(confidence, 3),
                evidence=f"NO price {m.no_price:.3f} >= {RESOLUTION_SNIPER_THRESHOLD} — near-certain outcome, profit {net_profit:.4f}/share after fee",
                detected_at=now_iso,
                ttl_seconds=ttl,
                size_hint_usd=round(min(20.0, 5.0 / max(0.01, net_profit)), 2),
            ))

    return opportunities


# ---------------------------------------------------------------------------
# Scanner: Negative Risk
# ---------------------------------------------------------------------------


def scan_neg_risk(markets: list[ParsedMarket]) -> list[Opportunity]:
    """Find multi-outcome groups where buying all YES tokens costs < $0.97."""
    # Group by condition_id
    groups: dict[str, list[ParsedMarket]] = {}
    for m in markets:
        if m.condition_id:
            groups.setdefault(m.condition_id, []).append(m)

    opportunities: list[Opportunity] = []
    now_iso = datetime.now(tz=timezone.utc).isoformat()

    for condition_id, group in groups.items():
        if len(group) < 2:
            continue

        # All markets must have token IDs and reasonable volume
        if any(not m.yes_token_id for m in group):
            continue
        total_volume = sum(m.volume_24h for m in group)
        if total_volume < MIN_VOLUME_24H:
            continue
        # At least one market must resolve > 1h
        max_hours = max(m.hours_to_resolution for m in group)
        if max_hours < MIN_HOURS_TO_RESOLUTION:
            continue

        total_cost = sum(m.yes_price for m in group)
        if total_cost >= NEG_RISK_SUM_THRESHOLD:
            continue

        profit_per_share = 1.0 - total_cost
        # Account for taker fees on each leg (worst case)
        n_legs = len(group)
        fee_cost = n_legs * 0.015 * (total_cost / n_legs)
        net_profit = profit_per_share - fee_cost
        if net_profit < MIN_PROFIT_PER_SHARE:
            continue

        confidence = min(0.99, 0.90 + net_profit * 2.0)
        ttl = int(max_hours * 3600)

        # Report as one opportunity per group, using first market's ID
        questions = " | ".join(m.question[:50] for m in group[:4])
        token_ids = ",".join(m.yes_token_id for m in group)

        opportunities.append(Opportunity(
            scanner="neg_risk",
            market_id=condition_id,
            question=f"[{n_legs}-way neg-risk] {questions}",
            direction="YES",
            token_id=token_ids,
            entry_price=round(total_cost, 4),
            expected_profit_per_share=round(net_profit, 4),
            confidence=round(confidence, 3),
            evidence=f"YES prices sum to {total_cost:.4f} < {NEG_RISK_SUM_THRESHOLD} across {n_legs} outcomes — locked profit {net_profit:.4f}/share after fees",
            detected_at=now_iso,
            ttl_seconds=ttl,
            size_hint_usd=round(min(50.0, 10.0 / max(0.01, net_profit)), 2),
        ))

    return opportunities


# ---------------------------------------------------------------------------
# Scanner: Stale Quote
# ---------------------------------------------------------------------------


def scan_stale_quotes(
    markets: list[ParsedMarket],
    books: dict[str, BookSnapshot],
) -> list[Opportunity]:
    """Find markets with wide spreads and liquidity on one side."""
    opportunities: list[Opportunity] = []
    now_iso = datetime.now(tz=timezone.utc).isoformat()

    for m in markets:
        if m.volume_24h < MIN_VOLUME_24H:
            continue
        if m.hours_to_resolution < MIN_HOURS_TO_RESOLUTION:
            continue

        # Check YES book
        yes_book = books.get(m.yes_token_id)
        if yes_book is not None and yes_book.spread > STALE_SPREAD_THRESHOLD:
            if yes_book.ask_depth_usd > STALE_DEPTH_THRESHOLD or yes_book.bid_depth_usd > STALE_DEPTH_THRESHOLD:
                if yes_book.ask_depth_usd >= MIN_ASK_DEPTH:
                    # Potential stale ask — can buy YES cheap
                    fair_price = (yes_book.best_bid + yes_book.best_ask) / 2.0
                    edge = fair_price - yes_book.best_ask
                    if edge > MIN_PROFIT_PER_SHARE:
                        confidence = min(0.85, 0.5 + edge * 3.0)
                        ttl = min(300, int(m.hours_to_resolution * 3600))  # stale quotes are fleeting

                        opportunities.append(Opportunity(
                            scanner="stale_quote",
                            market_id=m.market_id,
                            question=m.question,
                            direction="YES",
                            token_id=m.yes_token_id,
                            entry_price=round(yes_book.best_ask, 4),
                            expected_profit_per_share=round(edge, 4),
                            confidence=round(confidence, 3),
                            evidence=f"YES spread {yes_book.spread:.3f} > {STALE_SPREAD_THRESHOLD}, bid={yes_book.best_bid:.3f} ask={yes_book.best_ask:.3f}, depth=${yes_book.ask_depth_usd:.0f}",
                            detected_at=now_iso,
                            ttl_seconds=ttl,
                            size_hint_usd=round(min(20.0, 5.0 / max(0.01, edge)), 2),
                        ))

        # Check NO book
        no_book = books.get(m.no_token_id)
        if no_book is not None and no_book.spread > STALE_SPREAD_THRESHOLD:
            if no_book.ask_depth_usd > STALE_DEPTH_THRESHOLD or no_book.bid_depth_usd > STALE_DEPTH_THRESHOLD:
                if no_book.ask_depth_usd >= MIN_ASK_DEPTH:
                    fair_price = (no_book.best_bid + no_book.best_ask) / 2.0
                    edge = fair_price - no_book.best_ask
                    if edge > MIN_PROFIT_PER_SHARE:
                        confidence = min(0.85, 0.5 + edge * 3.0)
                        ttl = min(300, int(m.hours_to_resolution * 3600))

                        opportunities.append(Opportunity(
                            scanner="stale_quote",
                            market_id=m.market_id,
                            question=m.question,
                            direction="NO",
                            token_id=m.no_token_id,
                            entry_price=round(no_book.best_ask, 4),
                            expected_profit_per_share=round(edge, 4),
                            confidence=round(confidence, 3),
                            evidence=f"NO spread {no_book.spread:.3f} > {STALE_SPREAD_THRESHOLD}, bid={no_book.best_bid:.3f} ask={no_book.best_ask:.3f}, depth=${no_book.ask_depth_usd:.0f}",
                            detected_at=now_iso,
                            ttl_seconds=ttl,
                            size_hint_usd=round(min(20.0, 5.0 / max(0.01, edge)), 2),
                        ))

    return opportunities


# ---------------------------------------------------------------------------
# Main scan cycle
# ---------------------------------------------------------------------------


async def run_scan_cycle(
    session: aiohttp.ClientSession,
) -> tuple[list[Opportunity], dict[str, int]]:
    """Execute one full scan cycle. Returns (opportunities, stats)."""
    cycle_start = time.monotonic()

    # 1. Fetch all markets
    raw_markets = await fetch_all_markets(session)
    parsed: list[ParsedMarket] = []
    for raw in raw_markets:
        m = parse_market(raw)
        if m is not None:
            parsed.append(m)

    # 2. Run resolution sniper and neg-risk (no book data needed)
    resolution_opps = scan_resolution_sniper(parsed)
    neg_risk_opps = scan_neg_risk(parsed)

    # 3. Identify markets needing book data for stale-quote scan
    # Only fetch books for markets passing volume + resolution filters
    book_candidates = [
        m for m in parsed
        if m.volume_24h >= MIN_VOLUME_24H
        and m.hours_to_resolution >= MIN_HOURS_TO_RESOLUTION
    ]

    # Collect unique token IDs
    tokens_needed: set[str] = set()
    for m in book_candidates:
        if m.yes_token_id:
            tokens_needed.add(m.yes_token_id)
        if m.no_token_id:
            tokens_needed.add(m.no_token_id)

    # 4. Fetch books concurrently
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_BOOK_FETCHES)
    tasks = [
        fetch_book_async(session, tid, semaphore)
        for tid in sorted(tokens_needed)
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    books: dict[str, BookSnapshot] = {}
    for result in results:
        if isinstance(result, tuple):
            tid, book = result
            if book is not None:
                books[tid] = book

    # 5. Run stale quote scanner
    stale_opps = scan_stale_quotes(book_candidates, books)

    all_opps = resolution_opps + neg_risk_opps + stale_opps
    # Sort by expected profit descending
    all_opps.sort(key=lambda o: o.expected_profit_per_share, reverse=True)

    cycle_duration = time.monotonic() - cycle_start

    stats = {
        "total_markets_fetched": len(raw_markets),
        "markets_parsed": len(parsed),
        "book_candidates": len(book_candidates),
        "books_fetched": len(books),
        "resolution_sniper_opps": len(resolution_opps),
        "neg_risk_opps": len(neg_risk_opps),
        "stale_quote_opps": len(stale_opps),
        "total_opps": len(all_opps),
        "cycle_duration_seconds": round(cycle_duration, 2),
    }

    return all_opps, stats


def write_opportunities(
    opportunities: list[Opportunity],
    output_path: Path,
    signal_feed_path: Path,
) -> None:
    """Write opportunity files atomically."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    signal_feed_path.parent.mkdir(parents=True, exist_ok=True)

    # Full opportunity file
    payload = {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "count": len(opportunities),
        "opportunities": [o.to_dict() for o in opportunities],
    }
    tmp = output_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(output_path)

    # High-confidence signal feed for strike desk
    high_conf = [o for o in opportunities if o.confidence > 0.8]
    signal_payload = {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "count": len(high_conf),
        "signals": [o.to_dict() for o in high_conf],
    }
    tmp_sig = signal_feed_path.with_suffix(".tmp")
    tmp_sig.write_text(json.dumps(signal_payload, indent=2) + "\n", encoding="utf-8")
    tmp_sig.replace(signal_feed_path)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def main_loop(
    interval: int,
    once: bool,
    output_path: Path,
    signal_feed_path: Path,
) -> None:
    """Run the scanner in a continuous loop."""
    connector = aiohttp.TCPConnector(limit=50)
    backoff = 1

    async with aiohttp.ClientSession(connector=connector) as session:
        cycle_num = 0
        while True:
            cycle_num += 1
            try:
                opportunities, stats = await run_scan_cycle(session)

                write_opportunities(opportunities, output_path, signal_feed_path)

                logger.info(
                    "Cycle %d complete: %d markets, %d opportunities "
                    "(res=%d neg=%d stale=%d) in %.1fs",
                    cycle_num,
                    stats["markets_parsed"],
                    stats["total_opps"],
                    stats["resolution_sniper_opps"],
                    stats["neg_risk_opps"],
                    stats["stale_quote_opps"],
                    stats["cycle_duration_seconds"],
                )

                for opp in opportunities:
                    logger.info(
                        "  [%s] %s %s @ %.3f — profit %.4f conf %.2f — %s",
                        opp.scanner,
                        opp.direction,
                        opp.market_id[:16],
                        opp.entry_price,
                        opp.expected_profit_per_share,
                        opp.confidence,
                        opp.question[:60],
                    )

                # Push signal feed to VPS for strike desk consumption
                await _push_to_vps(signal_feed_path)

                backoff = 1  # reset on success

            except aiohttp.ClientResponseError as exc:
                if exc.status == 429:
                    backoff = min(backoff * 2, 120)
                    logger.warning(
                        "Rate limited (429). Backing off %ds before next cycle.", backoff
                    )
                    await asyncio.sleep(backoff)
                    continue
                else:
                    logger.error("HTTP error in cycle %d: %s", cycle_num, exc)
            except Exception as exc:
                logger.error("Cycle %d failed: %s", cycle_num, exc, exc_info=True)

            if once:
                break

            await asyncio.sleep(interval)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Continuous structural opportunity scanner for Polymarket."
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single scan cycle and exit.",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_INTERVAL,
        help=f"Seconds between scan cycles (default: {DEFAULT_INTERVAL}).",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(DEFAULT_OUTPUT),
        help=f"Path for full opportunity JSON (default: {DEFAULT_OUTPUT}).",
    )
    parser.add_argument(
        "--signal-feed",
        type=str,
        default=str(DEFAULT_SIGNAL_FEED),
        help=f"Path for high-confidence signal feed (default: {DEFAULT_SIGNAL_FEED}).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO).",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    output_path = Path(args.output)
    signal_feed_path = Path(args.signal_feed)

    logger.info(
        "Starting structural scanner: interval=%ds once=%s output=%s signal=%s",
        args.interval, args.once, output_path, signal_feed_path,
    )

    # Graceful shutdown on SIGINT/SIGTERM
    loop = asyncio.new_event_loop()

    def _shutdown(sig: int, frame: Any) -> None:
        logger.info("Received signal %d, shutting down.", sig)
        for task in asyncio.all_tasks(loop):
            task.cancel()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        loop.run_until_complete(
            main_loop(args.interval, args.once, output_path, signal_feed_path)
        )
    except (asyncio.CancelledError, KeyboardInterrupt):
        logger.info("Scanner stopped.")
    finally:
        loop.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
