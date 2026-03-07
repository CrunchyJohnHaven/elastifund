"""
Scanner - Gamma API Market Scanner (Velocity Maker v2)

Fetches active markets from the Gamma API, filters for fast-resolving
markets, and prioritizes by capital velocity score.

v2 changes:
- Multi-page fetching (up to 500 markets)
- Sort by volume to find high-activity markets first
- Fixed resolution filter: past endDates no longer get speed bonus
- Better category detection from market question text
- Separate fast-market discovery for crypto 5m/15m and sports

Based on jbecker.dev microstructure research (72.1M trades):
- Makers earn +1.12% excess return vs takers' -1.12%
- Category gaps: World Events 7.32pp, Media 7.28pp, Entertainment 4.79pp
- NO outperforms YES at 69/99 price levels (optimism tax)
"""

import json
import logging
import re
import time
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from .http import ThreadLocalSessionMixin

logger = logging.getLogger(__name__)

GAMMA_API = "https://gamma-api.polymarket.com"

# Categories with highest maker-taker edge gaps (jbecker.dev research)
CATEGORY_EDGE_MULTIPLIER = {
    "world_events": 1.5,   # 7.32pp gap
    "media": 1.5,          # 7.28pp gap
    "entertainment": 1.3,  # 4.79pp gap
    "weather": 1.2,        # 2.57pp gap, 0% fees
    "crypto": 1.1,         # 2.69pp gap
    "sports": 1.1,         # 2.23pp gap
    "politics": 1.0,       # 1.02pp gap
    "finance": 0.8,        # 0.17pp gap (too efficient)
}


def estimate_resolution_hours(market: dict) -> Optional[float]:
    """Estimate hours until market resolves.

    Uses endDate from API if available, otherwise keyword matching.
    Returns None if cannot estimate.
    IMPORTANT: Returns None for past endDates (market already expired).
    """
    end_date_str = market.get("endDate") or market.get("end_date_iso")
    if end_date_str:
        try:
            for fmt in ["%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"]:
                try:
                    end_dt = datetime.strptime(end_date_str, fmt).replace(tzinfo=timezone.utc)
                    hours = (end_dt - datetime.now(timezone.utc)).total_seconds() / 3600
                    if hours <= 0:
                        # Market endDate is in the past — could be awaiting resolution
                        # Don't treat as "fast resolving", treat as unknown
                        return None
                    return hours
                except ValueError:
                    continue
        except Exception:
            pass

    # Keyword-based estimation from question text
    question = (market.get("question") or "").lower()

    # Crypto 5m/15m/1h markets
    if re.search(r'up or down.*\d{1,2}:\d{2}', question):
        return 0.25  # 15 minutes
    if "5m" in question or "5-minute" in question or "5 minute" in question:
        return 0.083  # 5 minutes
    if "15m" in question or "15-minute" in question or "15 minute" in question:
        return 0.25

    # Time-based keywords
    if any(kw in question for kw in ["today", "tonight"]):
        return 12.0
    if "tomorrow" in question:
        return 36.0
    if any(kw in question for kw in ["this week", "this weekend"]):
        return 120.0

    # Date patterns like "March 7", "March 8", etc.
    now = datetime.now(timezone.utc)
    date_match = re.search(r'(?:march|mar)\s+(\d{1,2})', question)
    if date_match:
        day = int(date_match.group(1))
        try:
            target = datetime(now.year, 3, day, 23, 59, tzinfo=timezone.utc)
            hours = (target - now).total_seconds() / 3600
            if 0 < hours < 720:  # Within 30 days
                return hours
        except ValueError:
            pass

    # Sports game markets often have dates in the question
    if re.search(r'2026-03-0[7-9]|2026-03-1[0-4]', question):
        return 24.0  # Resolves within a day or so

    return None


def get_category(market: dict) -> str:
    """Extract category from market tags or question keywords."""
    # Check tags first
    tags = market.get("tags") or []
    if isinstance(tags, list):
        for tag in tags:
            tag_lower = str(tag).lower() if tag else ""
            for cat in CATEGORY_EDGE_MULTIPLIER:
                if cat in tag_lower:
                    return cat

    # Keyword-based category detection
    question = (market.get("question") or "").lower()

    # Weather
    if any(w in question for w in ["temperature", "highest temp", "lowest temp", "weather",
                                    "degrees", "fahrenheit", "celsius", "precipitation"]):
        return "weather"

    # Crypto
    if any(w in question for w in ["bitcoin", "btc", "eth", "ethereum", "crypto", "token",
                                    "solana", "sol", "xrp", "megaeth", "airdrop"]):
        return "crypto"

    # Sports
    if any(w in question for w in ["nba", "nfl", "nhl", "mlb", "fifa", "ufc",
                                    "game", "match", "spread", "o/u", "over/under",
                                    "vs.", "vs ", "win on 2026", "playoffs",
                                    "capitals", "bruins", "lakers", "celtics",
                                    "huskies", "eagles", "fc", "sc",
                                    "ncaa", "serie a", "lpl", "lol:"]):
        return "sports"

    # Entertainment
    if any(w in question for w in ["movie", "album", "oscar", "grammy", "rotten",
                                    "box office", "rihanna", "carti", "gta"]):
        return "entertainment"

    # Politics
    if any(w in question for w in ["trump", "biden", "election", "president",
                                    "congress", "senate", "governor", "political"]):
        return "politics"

    # Media
    if any(w in question for w in ["cnn", "fox news", "twitter", "x.com",
                                    "youtube", "tiktok", "podcast"]):
        return "media"

    return "world_events"  # Default to highest-edge category


def velocity_score(edge: float, resolution_hours: float) -> float:
    """Capital velocity score: annualized edge per unit of capital lockup."""
    if resolution_hours <= 0:
        resolution_hours = 1.0
    resolution_days = resolution_hours / 24.0
    return abs(edge) / max(resolution_days, 0.01) * 365


class MarketScanner(ThreadLocalSessionMixin):
    """
    Scans Polymarket for fast-resolving, high-velocity trading opportunities.
    Prioritizes markets by capital velocity and category edge.
    """

    def __init__(self, timeout: int = 15):
        super().__init__()
        self.timeout = timeout

    def fetch_active_markets(
        self,
        limit: int = 100,
        min_liquidity: float = 50.0,
        category: Optional[str] = None,
        order: str = "volume",
        ascending: bool = False,
    ) -> List[Dict[str, Any]]:
        """Fetch active markets from Gamma API.

        Args:
            order: Sort field (volume, endDate, liquidity, etc.)
            ascending: Sort direction
        """
        params: Dict[str, Any] = {
            "closed": "false",
            "limit": min(limit, 100),
            "active": "true",
            "order": order,
            "ascending": str(ascending).lower(),
        }
        if category:
            params["category"] = category

        try:
            resp = self.session.get(
                f"{GAMMA_API}/markets",
                params=params,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            markets = resp.json()
        except Exception as e:
            logger.error(f"Failed to fetch markets: {e}")
            return []

        if isinstance(markets, dict) and "data" in markets:
            markets = markets["data"]

        filtered = []
        for m in markets:
            liquidity = float(m.get("liquidity") or 0)
            if liquidity < min_liquidity:
                continue
            if not m.get("acceptingOrders", False):
                continue
            filtered.append(m)

        logger.info(f"Found {len(filtered)} active markets (min liquidity ${min_liquidity})")
        return filtered

    def fetch_multi_page(
        self,
        pages: int = 3,
        min_liquidity: float = 50.0,
    ) -> List[Dict[str, Any]]:
        """Fetch markets across multiple pages sorted by volume.

        Returns deduplicated list of markets.
        """
        all_markets = []
        seen_ids = set()

        for page in range(pages):
            offset = page * 100
            params = {
                "closed": "false",
                "limit": 100,
                "active": "true",
                "order": "volume",
                "ascending": "false",
                "offset": offset,
            }

            try:
                resp = self.session.get(
                    f"{GAMMA_API}/markets",
                    params=params,
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                markets = resp.json()
            except Exception as e:
                logger.error(f"Failed to fetch page {page}: {e}")
                break

            if isinstance(markets, dict) and "data" in markets:
                markets = markets["data"]

            for m in markets:
                mid = m.get("id") or m.get("condition_id") or m.get("question", "")
                if mid in seen_ids:
                    continue
                seen_ids.add(mid)

                liquidity = float(m.get("liquidity") or 0)
                if liquidity < min_liquidity:
                    continue
                if not m.get("acceptingOrders", False):
                    continue
                all_markets.append(m)

            if len(markets) < 100:
                break

            time.sleep(0.2)  # Rate limit courtesy

        logger.info(f"Multi-page fetch: {len(all_markets)} markets across {min(page+1, pages)} pages")
        return all_markets

    def fetch_market(self, condition_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single market by condition ID."""
        try:
            resp = self.session.get(
                f"{GAMMA_API}/markets/{condition_id}",
                timeout=self.timeout,
            )
            if resp.status_code == 200:
                return resp.json()
            return None
        except Exception as e:
            logger.error(f"Failed to fetch market {condition_id}: {e}")
            return None

    def get_mispriced_markets(
        self,
        markets: List[Dict[str, Any]],
        threshold: float = 0.10,
    ) -> List[Dict[str, Any]]:
        """Identify markets with potential mispricing."""
        candidates = []
        for m in markets:
            try:
                best_bid = float(m.get("bestBid") or 0)
                best_ask = float(m.get("bestAsk") or 1)
                prices_raw = m.get("outcomePrices", "[]")

                if isinstance(prices_raw, str):
                    prices = [float(p) for p in json.loads(prices_raw)]
                else:
                    prices = [float(p) for p in prices_raw]

                if len(prices) < 2:
                    continue

                price_sum = sum(prices)
                if abs(price_sum - 1.0) > threshold:
                    m["edge"] = abs(price_sum - 1.0)
                    m["edge_type"] = "sum_deviation"
                    candidates.append(m)
                    continue

                mid = (best_bid + best_ask) / 2
                spread = best_ask - best_bid
                if mid > 0 and spread / mid > threshold:
                    m["edge"] = spread / mid
                    m["edge_type"] = "wide_spread"
                    candidates.append(m)

            except (ValueError, TypeError):
                continue

        candidates.sort(key=lambda x: x.get("edge", 0), reverse=True)
        return candidates

    def get_actionable_candidates(
        self,
        markets: list,
        min_price: float = 0.10,
        max_price: float = 0.90,
        limit: int = 20,
        max_resolution_days: float = 7.0,
        prefer_fast: bool = True,
    ) -> list:
        """
        Select markets optimized for velocity trading.

        Prioritizes:
        1. Fast resolution time (< max_resolution_days)
        2. High category edge multiplier (Entertainment > Politics)
        3. NO-side opportunities (optimism tax)
        4. Good liquidity and volume
        """
        candidates = []
        skipped_no_resolution = 0
        skipped_too_slow = 0

        for m in markets:
            prices_raw = m.get("outcomePrices", "[]")
            try:
                if isinstance(prices_raw, str):
                    prices = [float(p) for p in json.loads(prices_raw)]
                else:
                    prices = [float(p) for p in prices_raw]
                if len(prices) < 2:
                    continue
                yes_price = prices[0]
            except (ValueError, json.JSONDecodeError):
                continue

            if not (min_price <= yes_price <= max_price):
                continue

            # Resolution time estimation
            res_hours = estimate_resolution_hours(m)

            # Filter: skip markets with unknown resolution OR too slow
            if res_hours is None:
                skipped_no_resolution += 1
                continue
            if res_hours > max_resolution_days * 24:
                skipped_too_slow += 1
                continue

            # Category and velocity scoring
            category = get_category(m)
            cat_multiplier = CATEGORY_EDGE_MULTIPLIER.get(category, 1.0)

            liquidity = float(m.get("liquidity") or 0)
            volume = float(m.get("volume") or 0)

            # Composite score
            price_score = 1.0 - abs(yes_price - 0.5) * 2
            liq_score = min(liquidity / 5000, 1.0)
            vol_score = min(volume / 50000, 1.0)

            # Speed bonus: faster resolution = higher score
            if res_hours < 1:
                speed_score = 3.0    # Huge bonus for <1h (crypto 5m/15m)
            elif res_hours < 12:
                speed_score = 2.5    # Big bonus for same-day
            elif res_hours < 24:
                speed_score = 2.0    # Bonus for <24h
            elif res_hours < 72:
                speed_score = 1.5    # Moderate for <3d
            elif res_hours < 168:
                speed_score = 1.0    # Neutral for <1w
            else:
                speed_score = 0.5    # Penalty for >1w

            # NO-side preference (optimism tax)
            no_preference = 1.0
            if yes_price > 0.7:
                no_preference = 1.2  # YES is expensive -> NO is good value

            m["_score"] = (
                price_score * 0.15 +
                liq_score * 0.10 +
                vol_score * 0.10 +
                speed_score * 0.40 +   # Speed is king
                cat_multiplier * 0.15 +
                no_preference * 0.10
            )
            m["_yes_price"] = yes_price
            m["_category"] = category
            m["_resolution_hours"] = res_hours
            m["_speed_score"] = speed_score
            candidates.append(m)

        candidates.sort(key=lambda x: x["_score"], reverse=True)

        logger.info(
            f"Velocity filter: {len(candidates)} pass, "
            f"{skipped_no_resolution} no resolution estimate, "
            f"{skipped_too_slow} too slow (>{max_resolution_days}d)"
        )

        # Log top 5 for visibility
        for c in candidates[:5]:
            q = c.get("question", "")[:50]
            cat = c.get("_category", "?")
            res = c.get("_resolution_hours")
            res_str = f"{res:.1f}h" if res else "?"
            logger.info(f"  TOP: {q} | cat={cat} | res={res_str} | score={c['_score']:.2f}")

        return candidates[:limit]

    def summarize_market(self, m: Dict[str, Any]) -> str:
        """Return a one-line summary of a market."""
        question = m.get("question", "Unknown")[:60]
        liquidity = float(m.get("liquidity") or 0)
        edge = m.get("edge", 0)
        return f"{question} | liq=${liquidity:.0f} | edge={edge:.1%}"
