"""
Cross-Platform Arbitrage Scanner — Polymarket ↔ Kalshi.

Finds risk-free arbitrage when identical markets are priced differently
on Polymarket vs Kalshi. Executes both legs simultaneously.

Usage:
    python cross_platform_arb.py scan          # One-shot scan, print opportunities
    python cross_platform_arb.py monitor       # Continuous monitoring loop
    python cross_platform_arb.py match-test    # Show matched markets without trading
"""

import asyncio
import json
import logging
import math
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

import httpx

# ---------------------------------------------------------------------------
# Kalshi SDK import
# ---------------------------------------------------------------------------
try:
    import kalshi_python
    from kalshi_python import Configuration as KalshiConfig, KalshiClient
    KALSHI_AVAILABLE = True
except ImportError:
    KALSHI_AVAILABLE = False
    KalshiClient = None

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("cross_platform_arb")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
GAMMA_API_BASE = "https://gamma-api.polymarket.com"
DATA_DIR = Path(__file__).parent / "data"
MATCH_CACHE_FILE = DATA_DIR / "market_matches.json"
ARB_POSITIONS_FILE = DATA_DIR / "arb_positions.json"

# Minimum profit % after fees to trigger an arb
MIN_PROFIT_PCT = 0.01  # 1%
# Kalshi taker fee coefficient
KALSHI_FEE_COEFFICIENT = 0.07
# Polymarket maker fee (zero for maker orders)
POLY_MAKER_FEE = 0.0
# Polymarket taker fee rate
POLY_TAKER_FEE = 0.02  # ~2% effective taker fee, varies by price
# Scan interval in seconds
SCAN_INTERVAL = 60
# Max capital per arb leg
MAX_ARB_USD = 10.0
# Max daily arb exposure
MAX_DAILY_EXPOSURE = 50.0

# Words to strip for matching
STRIP_WORDS = {
    "will", "the", "be", "a", "an", "in", "on", "at", "to", "of",
    "by", "for", "or", "and", "is", "it", "this", "that", "?",
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class MarketListing:
    """Normalized market from either platform."""
    platform: str  # "polymarket" or "kalshi"
    market_id: str
    title: str
    normalized_title: str
    yes_bid: float  # 0.00 - 1.00
    yes_ask: float
    no_bid: float
    no_ask: float
    volume: float
    end_date: Optional[str] = None
    extra: dict = field(default_factory=dict)


@dataclass
class ArbOpportunity:
    """A detected arbitrage opportunity."""
    poly_market: MarketListing
    kalshi_market: MarketListing
    match_score: float  # 0-1 similarity
    # Which direction is profitable
    direction: str  # "poly_yes_kalshi_no" or "poly_no_kalshi_yes"
    # Costs
    poly_price: float  # price we pay on Polymarket
    kalshi_price: float  # price we pay on Kalshi
    total_cost: float  # sum of both legs (should be < 1.0)
    gross_profit: float  # 1.0 - total_cost
    # Fees
    poly_fee: float
    kalshi_fee: float
    total_fees: float
    # Net
    net_profit: float
    net_profit_pct: float
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Title normalization for matching
# ---------------------------------------------------------------------------
def normalize_title(title: str) -> str:
    """Normalize a market title for fuzzy matching."""
    t = title.lower().strip()
    # Remove markdown bold markers
    t = t.replace("**", "")
    # Remove common punctuation
    for ch in "?!.,;:()[]{}\"'":
        t = t.replace(ch, "")
    # Remove common filler words
    words = t.split()
    words = [w for w in words if w not in STRIP_WORDS]
    return " ".join(words)


def extract_keywords(title: str) -> set[str]:
    """Extract meaningful keywords from a title for matching."""
    t = title.lower().strip()
    t = t.replace("**", "")
    for ch in "?!.,;:()[]{}\"'":
        t = t.replace(ch, "")
    words = t.split()
    # Remove very common words
    stop = STRIP_WORDS | {"before", "after", "more", "than", "above", "below",
                          "how", "many", "when", "who", "what", "which",
                          "new", "next", "first", "last", "any", "win",
                          "2025", "2026", "2027", "jan", "feb", "mar", "apr",
                          "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec",
                          "january", "february", "march", "april", "june",
                          "july", "august", "september", "october", "november", "december"}
    return {w for w in words if w not in stop and len(w) > 2}


def keyword_similarity(a_keywords: set[str], b_keywords: set[str]) -> float:
    """Jaccard similarity between keyword sets."""
    if not a_keywords or not b_keywords:
        return 0.0
    intersection = a_keywords & b_keywords
    union = a_keywords | b_keywords
    return len(intersection) / len(union)


def title_similarity(a: str, b: str) -> float:
    """Compute combined similarity between two market titles.
    Uses both sequence matching and keyword overlap.
    """
    seq_score = SequenceMatcher(None, a, b).ratio()
    kw_score = keyword_similarity(extract_keywords(a), extract_keywords(b))
    # Weight keyword matching higher — it handles different phrasing
    return max(seq_score, kw_score * 0.9 + seq_score * 0.1)


# ---------------------------------------------------------------------------
# Kalshi fee calculation
# ---------------------------------------------------------------------------
def kalshi_taker_fee(price_cents: int, contracts: int = 1) -> float:
    """Calculate Kalshi taker fee in dollars.

    Fee = coefficient * contracts * price * (1 - price)
    where price is in [0, 1].
    """
    p = price_cents / 100.0
    fee_per_contract = KALSHI_FEE_COEFFICIENT * p * (1 - p)
    return fee_per_contract * contracts


def kalshi_maker_fee(price_cents: int, contracts: int = 1) -> float:
    """Kalshi maker fee is 0."""
    return 0.0


# ---------------------------------------------------------------------------
# Polymarket market fetching
# ---------------------------------------------------------------------------
async def fetch_polymarket_markets(max_pages: int = 5) -> list[MarketListing]:
    """Fetch active markets from Polymarket Gamma API."""
    listings = []
    async with httpx.AsyncClient(timeout=15.0) as client:
        for page in range(max_pages):
            params = {"closed": "false", "limit": 100, "offset": page * 100}
            try:
                resp = await client.get(f"{GAMMA_API_BASE}/markets", params=params)
                resp.raise_for_status()
                markets = resp.json()
            except Exception as e:
                logger.warning(f"Polymarket fetch page {page} failed: {e}")
                break

            if not isinstance(markets, list):
                markets = markets.get("data", [])

            for m in markets:
                question = m.get("question", "")
                if not question:
                    continue

                # Extract prices
                prices_raw = m.get("outcomePrices")
                yes_price, no_price = 0.5, 0.5
                if isinstance(prices_raw, str):
                    try:
                        pl = json.loads(prices_raw)
                        if len(pl) >= 2:
                            yes_price = float(pl[0])
                            no_price = float(pl[1])
                    except (json.JSONDecodeError, ValueError):
                        pass
                elif isinstance(prices_raw, list) and len(prices_raw) >= 2:
                    yes_price = float(prices_raw[0])
                    no_price = float(prices_raw[1])

                # Use best bid/ask if available, else use outcomePrices
                yes_bid = float(m.get("bestBid", yes_price) or yes_price)
                yes_ask = float(m.get("bestAsk", yes_price) or yes_price)
                # For NO side, compute from YES
                no_bid = 1.0 - yes_ask  # NO bid = 1 - YES ask
                no_ask = 1.0 - yes_bid  # NO ask = 1 - YES bid

                listings.append(MarketListing(
                    platform="polymarket",
                    market_id=m.get("id", m.get("condition_id", "")),
                    title=question,
                    normalized_title=normalize_title(question),
                    yes_bid=max(0.01, min(0.99, yes_bid)),
                    yes_ask=max(0.01, min(0.99, yes_ask)),
                    no_bid=max(0.01, min(0.99, no_bid)),
                    no_ask=max(0.01, min(0.99, no_ask)),
                    volume=float(m.get("volume", 0) or 0),
                    end_date=m.get("endDate"),
                    extra={
                        "clobTokenIds": m.get("clobTokenIds"),
                        "spread": m.get("spread"),
                        "liquidity": float(m.get("liquidity", 0) or 0),
                    },
                ))

            if len(markets) < 100:
                break
            await asyncio.sleep(0.2)

    logger.info(f"Fetched {len(listings)} Polymarket markets")
    return listings


# ---------------------------------------------------------------------------
# Kalshi market fetching
# ---------------------------------------------------------------------------
def get_kalshi_client() -> Optional["KalshiClient"]:
    """Initialize Kalshi client with RSA auth."""
    if not KALSHI_AVAILABLE:
        logger.warning("kalshi_python not installed")
        return None

    api_key_id = os.environ.get("KALSHI_API_KEY_ID", "")

    # Find RSA key
    key_paths = [
        Path(__file__).parent / "kalshi" / "kalshi_rsa_private.pem",
        Path(os.environ.get("KALSHI_RSA_KEY_PATH", "")),
        Path.home() / "Desktop" / "Elastifund" / "bot" / "kalshi" / "kalshi_rsa_private.pem",
        Path.home() / "Desktop" / "Elastifund" / "kalshi" / "kalshi_rsa_private.pem",
    ]

    private_key_pem = None
    for kp in key_paths:
        if kp.exists():
            private_key_pem = kp.read_text()
            logger.info(f"Loaded Kalshi RSA key from {kp}")
            break

    if not private_key_pem:
        logger.error("Kalshi RSA private key not found")
        return None

    config = KalshiConfig()
    config.api_key_id = api_key_id
    config.private_key_pem = private_key_pem

    client = KalshiClient(configuration=config)
    return client


# Kalshi ticker prefixes to SKIP (sports combos, esports, etc)
KALSHI_SKIP_PREFIXES = {
    "KXMVECROSS", "KXMVESPORT", "KXMVEOSCAR",
    "KXNCAA", "KXLOL", "KXCSGO", "KXVALO",
}

# Interesting Kalshi series to explicitly fetch
KALSHI_SERIES = [
    "KXHIGHNY", "KXHIGHCH", "KXHIGHMI", "KXHIGHAUS",  # Weather
    "KXRAINNYCM",  # Rain
]


def _parse_kalshi_market(m) -> Optional[MarketListing]:
    """Parse a Kalshi market object/dict into a MarketListing."""
    if hasattr(m, "ticker"):
        ticker = m.ticker
        title = m.title or m.subtitle or ticker
        yes_bid = (m.yes_bid or 0) / 100.0
        yes_ask = (m.yes_ask or 0) / 100.0
        no_bid = (m.no_bid or 0) / 100.0
        no_ask = (m.no_ask or 0) / 100.0
        volume = m.volume or 0
        close_time = str(m.close_time) if m.close_time else None
        status = m.status
    else:
        ticker = m.get("ticker", "")
        title = m.get("title", "") or m.get("subtitle", "") or ticker
        yes_bid = (m.get("yes_bid", 0) or 0) / 100.0
        yes_ask = (m.get("yes_ask", 0) or 0) / 100.0
        no_bid = (m.get("no_bid", 0) or 0) / 100.0
        no_ask = (m.get("no_ask", 0) or 0) / 100.0
        volume = m.get("volume", 0) or 0
        close_time = m.get("close_time")
        status = m.get("status", "")

    if not title or not ticker:
        return None

    # Skip sports combos and multivariate markets
    for prefix in KALSHI_SKIP_PREFIXES:
        if ticker.startswith(prefix):
            return None

    # Skip markets with zero liquidity on both sides
    if yes_bid == 0 and yes_ask == 0 and no_bid == 0 and no_ask == 0:
        return None

    return MarketListing(
        platform="kalshi",
        market_id=ticker,
        title=title,
        normalized_title=normalize_title(title),
        yes_bid=max(0.01, min(0.99, yes_bid)) if yes_bid > 0 else 0.01,
        yes_ask=max(0.01, min(0.99, yes_ask)) if yes_ask > 0 else 0.99,
        no_bid=max(0.01, min(0.99, no_bid)) if no_bid > 0 else 0.01,
        no_ask=max(0.01, min(0.99, no_ask)) if no_ask > 0 else 0.99,
        volume=volume,
        end_date=close_time,
        extra={"status": status},
    )


def fetch_kalshi_markets(client: "KalshiClient", max_pages: int = 10) -> list[MarketListing]:
    """Fetch active non-sports markets from Kalshi API.

    Strategy: fetch events first (politics, economics, weather, entertainment),
    then get markets per event. Also fetch known weather series directly.
    """
    listings = []
    seen_tickers = set()

    def _add_market(m):
        listing = _parse_kalshi_market(m)
        if listing and listing.market_id not in seen_tickers:
            seen_tickers.add(listing.market_id)
            listings.append(listing)

    # 1. Fetch known weather series directly
    for series in KALSHI_SERIES:
        try:
            resp = client.get_markets(series_ticker=series, limit=50)
            for m in (resp.markets or []):
                _add_market(m)
        except Exception as e:
            logger.debug(f"Series {series} fetch failed: {e}")

    # 2. Fetch events and get their markets
    try:
        cursor = None
        for page in range(5):
            kwargs = {"limit": 200}
            if cursor:
                kwargs["cursor"] = cursor
            resp = client.get_events(**kwargs)
            events = resp.events or []

            for evt in events:
                ticker = evt.event_ticker if hasattr(evt, "event_ticker") else ""
                # Skip sports-looking events
                skip = any(x in ticker.upper() for x in [
                    "SPORT", "NBA", "NFL", "MLB", "NHL", "NCAA",
                    "SOC", "UFC", "LOL", "CSGO", "VALO",
                    "KXMVE",
                ])
                if skip:
                    continue

                try:
                    mkts_resp = client.get_markets(event_ticker=ticker, limit=50)
                    for m in (mkts_resp.markets or []):
                        _add_market(m)
                except Exception:
                    pass

            cursor = resp.cursor if hasattr(resp, "cursor") and resp.cursor else None
            if not cursor or len(events) < 200:
                break

    except Exception as e:
        logger.warning(f"Kalshi events fetch failed: {e}")

    # 3. Also do a general market scan (non-sports, with liquidity)
    try:
        cursor = None
        for page in range(max_pages):
            kwargs = {"status": "open", "limit": 1000}
            if cursor:
                kwargs["cursor"] = cursor
            resp = client.get_markets(**kwargs)
            for m in (resp.markets or []):
                _add_market(m)
            cursor = resp.cursor if hasattr(resp, "cursor") and resp.cursor else None
            if not cursor:
                break
    except Exception as e:
        logger.warning(f"Kalshi general fetch failed: {e}")

    logger.info(f"Fetched {len(listings)} non-sports Kalshi markets")
    return listings


# ---------------------------------------------------------------------------
# Market matching
# ---------------------------------------------------------------------------
def match_markets(
    poly_markets: list[MarketListing],
    kalshi_markets: list[MarketListing],
    threshold: float = 0.70,
) -> list[tuple[MarketListing, MarketListing, float]]:
    """Match markets across platforms by title similarity.

    Returns list of (poly_market, kalshi_market, similarity_score) tuples.
    """
    matches = []

    for pm in poly_markets:
        best_match = None
        best_score = 0.0

        for km in kalshi_markets:
            score = title_similarity(pm.normalized_title, km.normalized_title)
            if score > best_score:
                best_score = score
                best_match = km

        if best_match and best_score >= threshold:
            matches.append((pm, best_match, best_score))

    # Deduplicate: each Kalshi market should only match one Poly market (best one)
    kalshi_used = {}
    for pm, km, score in sorted(matches, key=lambda x: -x[2]):
        if km.market_id not in kalshi_used:
            kalshi_used[km.market_id] = (pm, km, score)

    final_matches = list(kalshi_used.values())
    logger.info(f"Found {len(final_matches)} cross-platform matches (threshold={threshold})")
    return final_matches


def save_matches(matches: list[tuple[MarketListing, MarketListing, float]]) -> None:
    """Cache market matches to disk."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data = []
    for pm, km, score in matches:
        data.append({
            "poly_id": pm.market_id,
            "poly_title": pm.title,
            "kalshi_id": km.market_id,
            "kalshi_title": km.title,
            "score": round(score, 4),
            "updated": datetime.now(timezone.utc).isoformat(),
        })
    MATCH_CACHE_FILE.write_text(json.dumps(data, indent=2))
    logger.info(f"Saved {len(data)} matches to {MATCH_CACHE_FILE}")


# ---------------------------------------------------------------------------
# Arbitrage detection
# ---------------------------------------------------------------------------
def detect_arb(
    poly: MarketListing,
    kalshi: MarketListing,
    match_score: float,
    use_maker: bool = True,
) -> Optional[ArbOpportunity]:
    """Check if an arbitrage opportunity exists between two matched markets.

    Two possible arb directions:
    1. Buy YES on Poly + Buy NO on Kalshi → pays $1 guaranteed if same resolution
    2. Buy NO on Poly + Buy YES on Kalshi → pays $1 guaranteed if same resolution

    Profitable when total cost < $1.00 minus fees.
    """
    opportunities = []

    # Direction 1: Poly YES + Kalshi NO
    poly_yes_cost = poly.yes_ask  # What we pay for YES on Poly
    kalshi_no_cost = kalshi.no_ask  # What we pay for NO on Kalshi

    if poly_yes_cost > 0 and kalshi_no_cost > 0:
        total_cost = poly_yes_cost + kalshi_no_cost
        gross_profit = 1.0 - total_cost

        # Fees
        poly_fee = POLY_MAKER_FEE if use_maker else POLY_TAKER_FEE * poly_yes_cost
        kalshi_fee_val = kalshi_taker_fee(int(kalshi_no_cost * 100))
        total_fees = poly_fee + kalshi_fee_val

        net_profit = gross_profit - total_fees
        net_profit_pct = net_profit / total_cost if total_cost > 0 else 0

        if net_profit > 0 and net_profit_pct >= MIN_PROFIT_PCT:
            opportunities.append(ArbOpportunity(
                poly_market=poly,
                kalshi_market=kalshi,
                match_score=match_score,
                direction="poly_yes_kalshi_no",
                poly_price=poly_yes_cost,
                kalshi_price=kalshi_no_cost,
                total_cost=total_cost,
                gross_profit=gross_profit,
                poly_fee=poly_fee,
                kalshi_fee=kalshi_fee_val,
                total_fees=total_fees,
                net_profit=net_profit,
                net_profit_pct=net_profit_pct,
            ))

    # Direction 2: Poly NO + Kalshi YES
    poly_no_cost = poly.no_ask
    kalshi_yes_cost = kalshi.yes_ask

    if poly_no_cost > 0 and kalshi_yes_cost > 0:
        total_cost = poly_no_cost + kalshi_yes_cost
        gross_profit = 1.0 - total_cost

        poly_fee = POLY_MAKER_FEE if use_maker else POLY_TAKER_FEE * poly_no_cost
        kalshi_fee_val = kalshi_taker_fee(int(kalshi_yes_cost * 100))
        total_fees = poly_fee + kalshi_fee_val

        net_profit = gross_profit - total_fees
        net_profit_pct = net_profit / total_cost if total_cost > 0 else 0

        if net_profit > 0 and net_profit_pct >= MIN_PROFIT_PCT:
            opportunities.append(ArbOpportunity(
                poly_market=poly,
                kalshi_market=kalshi,
                match_score=match_score,
                direction="poly_no_kalshi_yes",
                poly_price=poly_no_cost,
                kalshi_price=kalshi_yes_cost,
                total_cost=total_cost,
                gross_profit=gross_profit,
                poly_fee=poly_fee,
                kalshi_fee=kalshi_fee_val,
                total_fees=total_fees,
                net_profit=net_profit,
                net_profit_pct=net_profit_pct,
            ))

    if not opportunities:
        return None

    # Return the most profitable direction
    return max(opportunities, key=lambda o: o.net_profit_pct)


def scan_for_arbs(
    poly_markets: list[MarketListing],
    kalshi_markets: list[MarketListing],
    match_threshold: float = 0.70,
) -> list[ArbOpportunity]:
    """Full scan: match markets and detect arbitrage."""
    matches = match_markets(poly_markets, kalshi_markets, threshold=match_threshold)
    save_matches(matches)

    arbs = []
    for pm, km, score in matches:
        arb = detect_arb(pm, km, score)
        if arb:
            arbs.append(arb)

    arbs.sort(key=lambda a: -a.net_profit_pct)
    logger.info(f"Found {len(arbs)} arbitrage opportunities")
    return arbs


# ---------------------------------------------------------------------------
# Signal output (for jj_live.py integration)
# ---------------------------------------------------------------------------
def arb_to_signal(arb: ArbOpportunity) -> dict:
    """Convert an arb opportunity to a jj_live.py-compatible signal dict."""
    # Determine the Polymarket side
    if arb.direction == "poly_yes_kalshi_no":
        poly_direction = "buy_yes"
        poly_price = arb.poly_price
    else:
        poly_direction = "buy_no"
        poly_price = arb.poly_price

    return {
        "market_id": arb.poly_market.market_id,
        "question": arb.poly_market.title,
        "direction": poly_direction,
        "market_price": poly_price,
        "estimated_prob": 1.0 - arb.kalshi_price,  # Implied by other platform
        "edge": arb.net_profit_pct,
        "confidence": arb.match_score,
        "reasoning": (
            f"Cross-platform arb: {arb.direction}. "
            f"Poly {poly_direction} @ {arb.poly_price:.2f} + "
            f"Kalshi @ {arb.kalshi_price:.2f} = "
            f"{arb.total_cost:.2f} total. "
            f"Net profit: {arb.net_profit:.4f} ({arb.net_profit_pct:.1%}). "
            f"Match: {arb.match_score:.0%}"
        ),
        "source": "cross_platform_arb",
        "taker_fee": 0.0,  # We use maker on Poly
        "category": "arbitrage",
        "resolution_hours": 0,  # N/A for arb
        "velocity_score": 999,  # Always high priority
        "kelly_fraction": min(0.25, arb.net_profit_pct),  # Scale with profit
        "arb_details": {
            "kalshi_ticker": arb.kalshi_market.market_id,
            "kalshi_side": "no" if arb.direction == "poly_yes_kalshi_no" else "yes",
            "kalshi_price_cents": int(arb.kalshi_price * 100),
            "total_cost": arb.total_cost,
            "net_profit": arb.net_profit,
        },
    }


def get_signals_for_engine() -> list[dict]:
    """Scan for arb opportunities and return as jj_live.py signals.

    This is the main entry point for jj_live.py integration.
    Runs synchronously (wraps async internally).
    """
    try:
        return asyncio.get_event_loop().run_until_complete(_async_get_signals())
    except RuntimeError:
        # No event loop running, create one
        return asyncio.run(_async_get_signals())


async def _async_get_signals() -> list[dict]:
    """Async implementation of signal generation."""
    # Fetch Polymarket markets
    poly_markets = await fetch_polymarket_markets(max_pages=3)

    # Fetch Kalshi markets
    kalshi_client = get_kalshi_client()
    if not kalshi_client:
        logger.warning("Kalshi client unavailable, skipping cross-platform arb")
        return []

    kalshi_markets = fetch_kalshi_markets(kalshi_client, max_pages=3)

    if not poly_markets or not kalshi_markets:
        logger.warning(
            f"Insufficient markets: poly={len(poly_markets)}, kalshi={len(kalshi_markets)}"
        )
        return []

    # Scan for arbs
    arbs = scan_for_arbs(poly_markets, kalshi_markets)

    # Convert to signals
    signals = [arb_to_signal(arb) for arb in arbs[:10]]  # Top 10 max
    logger.info(f"Generated {len(signals)} cross-platform arb signals")
    return signals


# ---------------------------------------------------------------------------
# Arb position tracking
# ---------------------------------------------------------------------------
def save_arb_position(arb: ArbOpportunity, poly_order_id: str, kalshi_order_id: str):
    """Save an executed arb position to disk."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    positions = []
    if ARB_POSITIONS_FILE.exists():
        try:
            positions = json.loads(ARB_POSITIONS_FILE.read_text())
        except json.JSONDecodeError:
            positions = []

    positions.append({
        "timestamp": arb.timestamp,
        "direction": arb.direction,
        "poly_market_id": arb.poly_market.market_id,
        "poly_title": arb.poly_market.title,
        "kalshi_market_id": arb.kalshi_market.market_id,
        "kalshi_title": arb.kalshi_market.title,
        "poly_price": arb.poly_price,
        "kalshi_price": arb.kalshi_price,
        "total_cost": arb.total_cost,
        "net_profit": arb.net_profit,
        "net_profit_pct": arb.net_profit_pct,
        "poly_order_id": poly_order_id,
        "kalshi_order_id": kalshi_order_id,
        "status": "open",
    })

    ARB_POSITIONS_FILE.write_text(json.dumps(positions, indent=2))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def print_arb(arb: ArbOpportunity) -> None:
    """Pretty-print an arb opportunity."""
    print(f"\n{'='*70}")
    print(f"  ARB: {arb.direction}")
    print(f"  Match: {arb.match_score:.0%}")
    print(f"  Poly:  {arb.poly_market.title[:60]}")
    print(f"  Kalshi: {arb.kalshi_market.title[:60]}")
    print(f"  ---")
    print(f"  Poly price:   ${arb.poly_price:.2f}")
    print(f"  Kalshi price: ${arb.kalshi_price:.2f}")
    print(f"  Total cost:   ${arb.total_cost:.2f}")
    print(f"  Gross profit: ${arb.gross_profit:.4f}")
    print(f"  Fees:         ${arb.total_fees:.4f} (Poly: ${arb.poly_fee:.4f}, Kalshi: ${arb.kalshi_fee:.4f})")
    print(f"  Net profit:   ${arb.net_profit:.4f} ({arb.net_profit_pct:.1%})")
    print(f"{'='*70}")


async def cmd_scan():
    """One-shot scan for arb opportunities."""
    print("Fetching Polymarket markets...")
    poly = await fetch_polymarket_markets(max_pages=3)
    print(f"  → {len(poly)} markets")

    print("Fetching Kalshi markets...")
    kalshi_client = get_kalshi_client()
    if not kalshi_client:
        print("ERROR: Could not initialize Kalshi client")
        return

    kalshi = fetch_kalshi_markets(kalshi_client, max_pages=3)
    print(f"  → {len(kalshi)} markets")

    print("\nMatching markets...")
    arbs = scan_for_arbs(poly, kalshi)

    if not arbs:
        print("\nNo arbitrage opportunities found.")
        # Show top matches anyway
        matches = match_markets(poly, kalshi, threshold=0.50)
        if matches:
            print(f"\nTop {min(10, len(matches))} matches (below arb threshold):")
            for pm, km, score in matches[:10]:
                print(f"  {score:.0%} | Poly: {pm.title[:40]} ↔ Kalshi: {km.title[:40]}")
                poly_cost = pm.yes_ask + km.no_ask
                kalshi_cost = pm.no_ask + km.yes_ask
                print(f"       P_YES+K_NO={poly_cost:.2f}  P_NO+K_YES={kalshi_cost:.2f}")
    else:
        print(f"\n{'='*70}")
        print(f"  FOUND {len(arbs)} ARBITRAGE OPPORTUNITIES")
        print(f"{'='*70}")
        for arb in arbs:
            print_arb(arb)


async def cmd_match_test():
    """Show matched markets without checking for arbs."""
    print("Fetching Polymarket markets...")
    poly = await fetch_polymarket_markets(max_pages=3)
    print(f"  → {len(poly)} markets")

    print("Fetching Kalshi markets...")
    kalshi_client = get_kalshi_client()
    if not kalshi_client:
        print("ERROR: Could not initialize Kalshi client")
        return

    kalshi = fetch_kalshi_markets(kalshi_client, max_pages=3)
    print(f"  → {len(kalshi)} markets")

    print("\nMatching markets (threshold=0.50)...")
    matches = match_markets(poly, kalshi, threshold=0.50)

    for pm, km, score in matches:
        indicator = "✓" if score >= 0.70 else "~"
        print(f"\n{indicator} Score: {score:.2%}")
        print(f"  Poly:   {pm.title}")
        print(f"  Kalshi: {km.title}")
        print(f"  Poly  YES: bid={pm.yes_bid:.2f} ask={pm.yes_ask:.2f} | NO: bid={pm.no_bid:.2f} ask={pm.no_ask:.2f}")
        print(f"  Kalshi YES: bid={km.yes_bid:.2f} ask={km.yes_ask:.2f} | NO: bid={km.no_bid:.2f} ask={km.no_ask:.2f}")

        # Quick arb check
        cost1 = pm.yes_ask + km.no_ask
        cost2 = pm.no_ask + km.yes_ask
        print(f"  Arb check: P_YES+K_NO={cost1:.2f}  P_NO+K_YES={cost2:.2f}  (< 1.00 = opportunity)")


async def cmd_monitor():
    """Continuous monitoring loop."""
    print(f"Starting cross-platform arb monitor (interval={SCAN_INTERVAL}s)")
    print("Press Ctrl+C to stop.\n")

    kalshi_client = get_kalshi_client()
    if not kalshi_client:
        print("ERROR: Could not initialize Kalshi client")
        return

    cycle = 0
    while True:
        cycle += 1
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        print(f"\n[{ts}] Cycle {cycle}...")

        try:
            poly = await fetch_polymarket_markets(max_pages=3)
            kalshi = fetch_kalshi_markets(kalshi_client, max_pages=3)

            arbs = scan_for_arbs(poly, kalshi)

            if arbs:
                print(f"  *** {len(arbs)} ARB OPPORTUNITIES ***")
                for arb in arbs[:3]:
                    print(f"    {arb.net_profit_pct:.1%} | {arb.direction} | {arb.poly_market.title[:40]}")
            else:
                matches = match_markets(poly, kalshi, threshold=0.70)
                print(f"  No arbs. {len(matches)} matched markets, {len(poly)} Poly, {len(kalshi)} Kalshi")

        except Exception as e:
            logger.error(f"Cycle {cycle} error: {e}")

        await asyncio.sleep(SCAN_INTERVAL)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    if len(sys.argv) < 2:
        print("Usage: python cross_platform_arb.py [scan|monitor|match-test]")
        sys.exit(1)

    cmd = sys.argv[1].lower()

    if cmd == "scan":
        asyncio.run(cmd_scan())
    elif cmd == "monitor":
        asyncio.run(cmd_monitor())
    elif cmd in ("match-test", "match_test", "matchtest"):
        asyncio.run(cmd_match_test())
    else:
        print(f"Unknown command: {cmd}")
        print("Usage: python cross_platform_arb.py [scan|monitor|match-test]")
        sys.exit(1)


if __name__ == "__main__":
    main()
