"""
Cross-Platform Arbitrage Scanner — Polymarket vs Kalshi.

Monitors the same events across both platforms to detect guaranteed-profit
opportunities: when YES on one platform + NO on the other costs less than
$1.00 after fees.

Architecture:
  PlatformMarket   — normalized market from either platform
  MatchedPair      — same event identified on both platforms
  CrossPlatformOpportunity — executable arb with full cost breakdown
  CrossPlatformArbScanner  — main scanning class

Usage:
    scanner = CrossPlatformArbScanner()
    opportunities = await scanner.scan_all()
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger("JJ.cross_platform_arb")

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PlatformMarket:
    platform: str              # "polymarket" or "kalshi"
    market_id: str
    question: str
    yes_price: float
    no_price: float
    volume_24h: float
    resolution_source: str     # Where does it resolve from?
    resolution_date: str       # Expected resolution (ISO string or raw)
    fees: dict = field(default_factory=dict)  # {taker_fee: float, maker_fee: float}


@dataclass
class MatchedPair:
    polymarket: PlatformMarket
    kalshi: PlatformMarket
    similarity_score: float    # How similar the questions are (0-1)
    resolution_match: bool     # Do resolution criteria match?
    resolution_risk: str       # Description of resolution differences


@dataclass
class CrossPlatformOpportunity:
    matched_pair: MatchedPair
    buy_yes_platform: str      # Which platform to buy YES on
    buy_no_platform: str       # Which platform to buy NO on
    yes_price: float           # Price of YES on the cheaper platform
    no_price: float            # Price of NO on the other platform
    gross_cost: float          # yes_price + no_price
    total_fees: float          # Combined fees on both platforms
    net_cost: float            # gross_cost + total_fees
    net_profit: float          # 1.0 - net_cost
    profit_pct: float          # net_profit / net_cost
    required_capital: float    # Must fund BOTH platforms
    risk_level: str            # "LOW", "MEDIUM", or "HIGH"
    timestamp: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Date / currency normalisation helpers
# ---------------------------------------------------------------------------

_MONTH_MAP = {
    "jan": "01", "january": "01",
    "feb": "02", "february": "02",
    "mar": "03", "march": "03",
    "apr": "04", "april": "04",
    "may": "05",
    "jun": "06", "june": "06",
    "jul": "07", "july": "07",
    "aug": "08", "august": "08",
    "sep": "09", "sept": "09", "september": "09",
    "oct": "10", "october": "10",
    "nov": "11", "november": "11",
    "dec": "12", "december": "12",
}

_CURRENT_YEAR = "2026"


def _expand_currency(text: str) -> str:
    """Expand shorthand currency amounts: $95k → $95000, $1.2m → $1200000."""
    # $NNk / $NN.NNk
    text = re.sub(
        r"\$(\d+(?:\.\d+)?)\s*k\b",
        lambda m: f"${int(float(m.group(1)) * 1_000)}",
        text,
        flags=re.IGNORECASE,
    )
    # $NNm / $NN.NNm
    text = re.sub(
        r"\$(\d+(?:\.\d+)?)\s*m\b",
        lambda m: f"${int(float(m.group(1)) * 1_000_000)}",
        text,
        flags=re.IGNORECASE,
    )
    return text


def _normalise_dates(text: str) -> str:
    """Convert textual dates to YYYY-MM-DD.
    Handles: 'March 31', 'Mar 31, 2026', 'March 31 2026', '3/31/2026'.
    """
    # Written month: 'March 31, 2026' / 'Mar 31 2026' / 'March 31'
    pattern_written = re.compile(
        r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
        r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|"
        r"nov(?:ember)?|dec(?:ember)?)\s+(\d{1,2})(?:,?\s*(\d{4}))?\b",
        re.IGNORECASE,
    )
    def _replace_written(m: re.Match) -> str:
        month_str = m.group(1).lower()
        day = int(m.group(2))
        year = m.group(3) or _CURRENT_YEAR
        month = _MONTH_MAP.get(month_str, "00")
        return f"{year}-{month}-{day:02d}"

    text = pattern_written.sub(_replace_written, text)

    # Numeric: 3/31/2026 or 03/31/2026
    pattern_numeric = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
    def _replace_numeric(m: re.Match) -> str:
        return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"

    text = pattern_numeric.sub(_replace_numeric, text)
    return text


# ---------------------------------------------------------------------------
# Stop-words for Jaccard similarity
# ---------------------------------------------------------------------------
_STOP_WORDS = frozenset({
    "will", "the", "be", "a", "an", "in", "on", "at", "to", "of",
    "by", "for", "or", "and", "is", "it", "this", "that",
    "before", "after", "than", "above", "below",
    "how", "many", "when", "who", "what", "which",
    "new", "next", "first", "last", "any",
})


# ---------------------------------------------------------------------------
# Main scanner class
# ---------------------------------------------------------------------------

class CrossPlatformArbScanner:
    """Cross-platform arbitrage scanner for Polymarket vs Kalshi.

    Detects risk-free (or near-risk-free) arbitrage by:
    1. Fetching active markets from both platforms.
    2. Matching markets on text similarity + resolution proximity.
    3. Checking whether the combined YES+NO cost leaves positive profit.
    """

    def __init__(
        self,
        min_profit_pct: float = 0.02,
        min_similarity: float = 0.7,
        polymarket_taker_fee: float = 0.015,
        kalshi_taker_fee: float = 0.012,
        polymarket_api: str = "https://gamma-api.polymarket.com",
        kalshi_api: str = "https://trading-api.kalshi.com/trade-api/v2",
    ) -> None:
        self.min_profit_pct = min_profit_pct
        self.min_similarity = min_similarity
        self.polymarket_taker_fee = polymarket_taker_fee
        self.kalshi_taker_fee = kalshi_taker_fee
        self.polymarket_api = polymarket_api
        self.kalshi_api = kalshi_api

    # ------------------------------------------------------------------
    # Text normalisation
    # ------------------------------------------------------------------

    def _normalize_question(self, question: str) -> str:
        """Normalize a market question for comparison.

        Steps:
        - Lowercase and strip surrounding whitespace
        - Remove platform-specific prefixes (e.g., 'Kalshi: ')
        - Remove thousands-separator commas inside numbers (100,000 → 100000)
        - Expand currency shorthand ($95k → $95000)
        - Normalize dates to YYYY-MM-DD
        - Remove remaining punctuation
        - Collapse whitespace
        """
        text = question.lower().strip()
        # Strip platform prefixes like "Kalshi: " or "Polymarket | "
        text = re.sub(r"^(?:kalshi|polymarket)\s*[:\|]\s*", "", text)
        # Remove thousands-separator commas inside numbers BEFORE general punct removal
        # e.g. "$100,000" → "$100000", "1,500,000" → "1500000"
        text = re.sub(r"(\d),(\d)", r"\1\2", text)
        # Apply again in case of multiple commas (e.g. 1,000,000)
        text = re.sub(r"(\d),(\d)", r"\1\2", text)
        # Expand currency
        text = _expand_currency(text)
        # Normalise dates
        text = _normalise_dates(text)
        # Remove punctuation except hyphens and underscores
        text = re.sub(r"[^\w\s\-]", " ", text)
        # Collapse whitespace
        text = re.sub(r"\s+", " ", text).strip()
        return text

    # ------------------------------------------------------------------
    # Similarity
    # ------------------------------------------------------------------

    def _tokenize(self, normalized: str) -> set[str]:
        """Split into meaningful tokens, removing stop-words."""
        tokens = normalized.split()
        return {t for t in tokens if t not in _STOP_WORDS and len(t) >= 2}

    def _compute_similarity(self, q1: str, q2: str) -> float:
        """Compute text similarity between two normalized questions.

        Uses Jaccard similarity on token sets plus an entity-overlap bonus
        for numbers and capitalized entities (already lowercased here, so
        numbers and specific strings like 'bitcoin', 'btc', price levels).

        Returns 0.0 – 1.0.
        """
        tokens1 = self._tokenize(q1)
        tokens2 = self._tokenize(q2)

        if not tokens1 or not tokens2:
            return 0.0

        # Base Jaccard
        intersection = tokens1 & tokens2
        union = tokens1 | tokens2
        jaccard = len(intersection) / len(union)

        # Entity bonus: numeric tokens and short alphabetic tokens that look
        # like tickers / named-entities (≤6 chars, no common stopword).
        def _entity_tokens(tset: set[str]) -> set[str]:
            result = set()
            for t in tset:
                if re.match(r"^\d[\d,.]*$", t):   # numeric
                    result.add(t)
                elif len(t) <= 6 and t.isalpha():  # ticker-length word
                    result.add(t)
            return result

        ent1 = _entity_tokens(tokens1)
        ent2 = _entity_tokens(tokens2)
        if ent1 and ent2:
            ent_intersection = ent1 & ent2
            ent_union = ent1 | ent2
            entity_score = len(ent_intersection) / len(ent_union)
            # Blend: 70% Jaccard, 30% entity
            score = 0.70 * jaccard + 0.30 * entity_score
        else:
            score = jaccard

        return min(score, 1.0)

    # ------------------------------------------------------------------
    # Market matching
    # ------------------------------------------------------------------

    def match_markets(
        self,
        polymarket_markets: list[PlatformMarket],
        kalshi_markets: list[PlatformMarket],
    ) -> list[MatchedPair]:
        """Match markets across platforms using text similarity.

        Steps:
        1. Normalize all question texts.
        2. Compute pairwise similarity between every Polymarket and Kalshi market.
        3. For pairs above min_similarity:
           a. Check resolution source alignment.
           b. Check resolution dates are within 24 h of each other.
           c. Assess resolution risk.
        4. Return list sorted by similarity descending.
           Each Polymarket market is matched to at most one Kalshi market
           (and vice versa) — highest score wins.
        """
        # Normalize
        poly_norm = {m.market_id: self._normalize_question(m.question) for m in polymarket_markets}
        kal_norm  = {m.market_id: self._normalize_question(m.question) for m in kalshi_markets}

        # Score all pairs
        scored: list[tuple[float, PlatformMarket, PlatformMarket]] = []
        for pm in polymarket_markets:
            for km in kalshi_markets:
                score = self._compute_similarity(poly_norm[pm.market_id], kal_norm[km.market_id])
                if score >= self.min_similarity:
                    scored.append((score, pm, km))

        # Greedy assignment: highest-score pairs first, each market used once
        scored.sort(key=lambda x: x[0], reverse=True)
        used_poly: set[str] = set()
        used_kal: set[str] = set()
        pairs: list[MatchedPair] = []

        for score, pm, km in scored:
            if pm.market_id in used_poly or km.market_id in used_kal:
                continue
            used_poly.add(pm.market_id)
            used_kal.add(km.market_id)

            resolution_match = self._dates_close(pm.resolution_date, km.resolution_date)
            resolution_risk = self.assess_resolution_risk(
                MatchedPair(
                    polymarket=pm,
                    kalshi=km,
                    similarity_score=score,
                    resolution_match=resolution_match,
                    resolution_risk="",  # filled in below
                )
            )
            pairs.append(
                MatchedPair(
                    polymarket=pm,
                    kalshi=km,
                    similarity_score=score,
                    resolution_match=resolution_match,
                    resolution_risk=resolution_risk,
                )
            )

        pairs.sort(key=lambda p: p.similarity_score, reverse=True)
        return pairs

    def _dates_close(self, d1: str, d2: str, max_delta_hours: float = 24.0) -> bool:
        """Return True if two date strings represent times within max_delta_hours."""
        if not d1 or not d2:
            return False
        # Try to extract YYYY-MM-DD prefix
        iso1 = re.search(r"(\d{4}-\d{2}-\d{2})", d1)
        iso2 = re.search(r"(\d{4}-\d{2}-\d{2})", d2)
        if not iso1 or not iso2:
            # Fallback: exact string match
            return d1.strip() == d2.strip()
        from datetime import datetime as _dt
        try:
            t1 = _dt.strptime(iso1.group(1), "%Y-%m-%d")
            t2 = _dt.strptime(iso2.group(1), "%Y-%m-%d")
            delta_hours = abs((t1 - t2).total_seconds()) / 3600.0
            return delta_hours <= max_delta_hours
        except ValueError:
            return False

    # ------------------------------------------------------------------
    # Resolution risk
    # ------------------------------------------------------------------

    def assess_resolution_risk(self, pair: MatchedPair) -> str:
        """Assess the risk that the two platforms resolve differently.

        LOW:    Exact same event, same resolution source.
        MEDIUM: Same event, different wording but likely same resolution.
        HIGH:   Similar event but different resolution criteria
                (different deadline, different source, threshold mismatch).
        """
        pm = pair.polymarket
        km = pair.kalshi

        risk_factors: list[str] = []

        # Check resolution sources
        src_pm = (pm.resolution_source or "").lower().strip()
        src_km = (km.resolution_source or "").lower().strip()
        sources_match = (
            bool(src_pm) and bool(src_km) and src_pm == src_km
        )
        if not sources_match and src_pm and src_km:
            risk_factors.append(f"different resolution sources ({pm.resolution_source!r} vs {km.resolution_source!r})")

        # Check resolution dates
        dates_match = self._dates_close(pm.resolution_date, km.resolution_date)
        if not dates_match:
            risk_factors.append(
                f"different resolution dates ({pm.resolution_date!r} vs {km.resolution_date!r})"
            )

        # Check for by/before wording risk (can cause off-by-one day)
        q_pm = pm.question.lower()
        q_km = km.question.lower()
        by_before_mismatch = (
            ("by " in q_pm and "before " in q_km)
            or ("before " in q_pm and "by " in q_km)
        )
        if by_before_mismatch:
            risk_factors.append("'by' vs 'before' wording mismatch (off-by-one-day risk)")

        # Determine level
        if not risk_factors and sources_match and dates_match:
            return "LOW"
        if len(risk_factors) >= 2 or not dates_match:
            return "HIGH"
        return "MEDIUM"

    # ------------------------------------------------------------------
    # Opportunity scanning
    # ------------------------------------------------------------------

    def _calc_fee(self, platform: str, price: float) -> float:
        """Return the taker fee in dollar terms for a single leg."""
        if platform == "polymarket":
            return self.polymarket_taker_fee * price
        return self.kalshi_taker_fee * price

    def scan_opportunities(
        self, matched_pairs: list[MatchedPair]
    ) -> list[CrossPlatformOpportunity]:
        """For each matched pair, check if cross-platform arb exists.

        For pair (P=Polymarket, K=Kalshi):
          Option A: Buy YES on P + Buy NO on K
            gross_cost_A = P.yes_price + K.no_price
            fees_A = P.yes_price * poly_fee + K.no_price * kalshi_fee
            net_cost_A = gross_cost_A + fees_A
          Option B: Buy YES on K + Buy NO on P
            gross_cost_B = K.yes_price + P.no_price
            fees_B = K.yes_price * kalshi_fee + P.no_price * poly_fee
            net_cost_B = gross_cost_B + fees_B

        Best option = whichever net_cost is smaller.
        If net_cost < 1.0 and net_profit / net_cost >= min_profit_pct → opportunity.
        """
        opportunities: list[CrossPlatformOpportunity] = []

        for pair in matched_pairs:
            pm = pair.polymarket
            km = pair.kalshi

            # Option A: YES on Polymarket, NO on Kalshi
            gross_A = pm.yes_price + km.no_price
            fees_A = self._calc_fee("polymarket", pm.yes_price) + self._calc_fee("kalshi", km.no_price)
            net_A = gross_A + fees_A

            # Option B: YES on Kalshi, NO on Polymarket
            gross_B = km.yes_price + pm.no_price
            fees_B = self._calc_fee("kalshi", km.yes_price) + self._calc_fee("polymarket", pm.no_price)
            net_B = gross_B + fees_B

            # Pick best
            if net_A <= net_B:
                buy_yes_platform = "polymarket"
                buy_no_platform  = "kalshi"
                yes_price  = pm.yes_price
                no_price   = km.no_price
                gross_cost = gross_A
                total_fees = fees_A
                net_cost   = net_A
            else:
                buy_yes_platform = "kalshi"
                buy_no_platform  = "polymarket"
                yes_price  = km.yes_price
                no_price   = pm.no_price
                gross_cost = gross_B
                total_fees = fees_B
                net_cost   = net_B

            if net_cost >= 1.0:
                logger.debug(
                    "Pair %r/%r: net_cost=%.4f ≥ 1.0, skipping",
                    pm.market_id, km.market_id, net_cost,
                )
                continue

            net_profit = 1.0 - net_cost
            profit_pct = net_profit / net_cost if net_cost > 0 else 0.0

            if profit_pct < self.min_profit_pct:
                logger.debug(
                    "Pair %r/%r: profit_pct=%.4f below threshold %.4f, skipping",
                    pm.market_id, km.market_id, profit_pct, self.min_profit_pct,
                )
                continue

            risk_level = self.assess_resolution_risk(pair)

            opp = CrossPlatformOpportunity(
                matched_pair=pair,
                buy_yes_platform=buy_yes_platform,
                buy_no_platform=buy_no_platform,
                yes_price=yes_price,
                no_price=no_price,
                gross_cost=gross_cost,
                total_fees=total_fees,
                net_cost=net_cost,
                net_profit=net_profit,
                profit_pct=profit_pct,
                required_capital=net_cost,  # must fund both legs
                risk_level=risk_level,
                timestamp=time.time(),
            )
            opportunities.append(opp)
            logger.info(
                "ARB FOUND: %.2f%% profit | %s YES@%.3f + %s NO@%.3f | risk=%s",
                profit_pct * 100,
                buy_yes_platform, yes_price,
                buy_no_platform, no_price,
                risk_level,
            )

        opportunities.sort(key=lambda o: o.profit_pct, reverse=True)
        return opportunities

    # ------------------------------------------------------------------
    # API fetching
    # ------------------------------------------------------------------

    async def fetch_polymarket_markets(
        self,
        category: Optional[str] = None,
        _injected: Optional[list] = None,
    ) -> list[PlatformMarket]:
        """Fetch active markets from Polymarket Gamma API.

        Pass _injected to bypass network (for tests / offline use).
        """
        if _injected is not None:
            return _injected

        params: dict = {"active": "true", "closed": "false", "limit": 100}
        if category:
            params["category"] = category

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.get(f"{self.polymarket_api}/markets", params=params)
                resp.raise_for_status()
                raw: list[dict] = resp.json()
            except Exception as exc:
                logger.error("Polymarket fetch failed: %s", exc)
                return []

        markets: list[PlatformMarket] = []
        for item in raw:
            try:
                market = PlatformMarket(
                    platform="polymarket",
                    market_id=item.get("id") or item.get("conditionId", ""),
                    question=item.get("question") or item.get("title", ""),
                    yes_price=float(item.get("bestAsk", item.get("lastTradedPrice", 0.5))),
                    no_price=1.0 - float(item.get("bestAsk", item.get("lastTradedPrice", 0.5))),
                    volume_24h=float(item.get("volume24hr", 0.0)),
                    resolution_source=item.get("resolutionSource", ""),
                    resolution_date=item.get("endDate", ""),
                    fees={"taker_fee": self.polymarket_taker_fee, "maker_fee": 0.0},
                )
                markets.append(market)
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning("Skipping malformed Polymarket market: %s", exc)

        logger.info("Fetched %d Polymarket markets", len(markets))
        return markets

    async def fetch_kalshi_markets(
        self,
        category: Optional[str] = None,
        _injected: Optional[list] = None,
    ) -> list[PlatformMarket]:
        """Fetch active markets from Kalshi API.

        Pass _injected to bypass network (for tests / offline use).
        """
        if _injected is not None:
            return _injected

        params: dict = {"status": "open", "limit": 100}
        if category:
            params["event_category"] = category

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.get(f"{self.kalshi_api}/markets", params=params)
                resp.raise_for_status()
                raw: dict = resp.json()
                items: list[dict] = raw.get("markets", [])
            except Exception as exc:
                logger.error("Kalshi fetch failed: %s", exc)
                return []

        markets: list[PlatformMarket] = []
        for item in items:
            try:
                yes_ask = float(item.get("yes_ask", 50)) / 100.0
                no_ask  = float(item.get("no_ask",  50)) / 100.0
                market = PlatformMarket(
                    platform="kalshi",
                    market_id=item.get("ticker", item.get("id", "")),
                    question=item.get("title", ""),
                    yes_price=yes_ask,
                    no_price=no_ask,
                    volume_24h=float(item.get("volume", 0.0)),
                    resolution_source=item.get("resolution_source", ""),
                    resolution_date=item.get("close_time", item.get("expiration_time", "")),
                    fees={"taker_fee": self.kalshi_taker_fee, "maker_fee": 0.0},
                )
                markets.append(market)
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning("Skipping malformed Kalshi market: %s", exc)

        logger.info("Fetched %d Kalshi markets", len(markets))
        return markets

    # ------------------------------------------------------------------
    # Full scan
    # ------------------------------------------------------------------

    async def scan_all(
        self,
        polymarket_data: Optional[list] = None,
        kalshi_data: Optional[list] = None,
    ) -> list[CrossPlatformOpportunity]:
        """Full scan: fetch both platforms, match, find opportunities.

        If polymarket_data / kalshi_data are provided (list[PlatformMarket]
        or raw dicts), use them instead of fetching from the network.
        """
        poly_markets = await self.fetch_polymarket_markets(_injected=polymarket_data)
        kal_markets  = await self.fetch_kalshi_markets(_injected=kalshi_data)

        if not poly_markets or not kal_markets:
            logger.warning("One or both platform market lists are empty — no pairs to match")
            return []

        pairs = self.match_markets(poly_markets, kal_markets)
        logger.info("Matched %d cross-platform pairs", len(pairs))

        opportunities = self.scan_opportunities(pairs)
        logger.info("Found %d actionable arb opportunities", len(opportunities))
        return opportunities

    # ------------------------------------------------------------------
    # Alert formatting
    # ------------------------------------------------------------------

    def format_alert(self, opp: CrossPlatformOpportunity) -> str:
        """Format opportunity as a Telegram alert string."""
        pm = opp.matched_pair.polymarket
        km = opp.matched_pair.kalshi
        # Use whichever question is longer as the canonical description
        question = pm.question if len(pm.question) >= len(km.question) else km.question

        yes_plat = opp.buy_yes_platform.capitalize()
        no_plat  = opp.buy_no_platform.capitalize()

        lines = [
            f"CROSS-PLATFORM ARB: {opp.profit_pct * 100:.1f}% guaranteed",
            f"Event: {question}",
            f"BUY YES on {yes_plat} @ ${opp.yes_price:.2f}",
            f"BUY NO on {no_plat} @ ${opp.no_price:.2f}",
            f"Cost: ${opp.gross_cost:.2f} + ${opp.total_fees:.4f} fees = ${opp.net_cost:.4f}",
            f"Profit: ${opp.net_profit:.4f} per share ({opp.profit_pct * 100:.1f}%)",
            f"Risk: {opp.risk_level} ({opp.matched_pair.resolution_risk})",
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Historical spread analysis
    # ------------------------------------------------------------------

    def historical_spread_analysis(self, pair_history: list[dict]) -> dict:
        """Analyse historical spread data for a matched pair.

        Each entry in pair_history should have:
          {
            "timestamp": float,
            "poly_yes": float,
            "poly_no": float,
            "kalshi_yes": float,
            "kalshi_no": float,
          }

        Returns:
          avg_spread, max_spread, min_spread, volatility (std),
          mean_reversion_time (seconds, estimated from zero-crossings),
          profitable_windows_per_day (count of periods where spread > fee threshold).
        """
        if not pair_history:
            return {
                "avg_spread": 0.0,
                "max_spread": 0.0,
                "min_spread": 0.0,
                "volatility": 0.0,
                "mean_reversion_time": 0.0,
                "profitable_windows_per_day": 0,
            }

        spreads: list[float] = []
        for entry in pair_history:
            # Best cross-platform spread in either direction
            spread_a = 1.0 - (entry["poly_yes"] + entry["kalshi_no"])
            spread_b = 1.0 - (entry["kalshi_yes"] + entry["poly_no"])
            spreads.append(max(spread_a, spread_b))

        n = len(spreads)
        avg_spread = sum(spreads) / n
        max_spread = max(spreads)
        min_spread = min(spreads)

        # Variance / std
        variance = sum((s - avg_spread) ** 2 for s in spreads) / n
        volatility = variance ** 0.5

        # Mean reversion time: estimate from zero-crossings of (spread - avg)
        demeaned = [s - avg_spread for s in spreads]
        crossings = 0
        for i in range(1, len(demeaned)):
            if demeaned[i - 1] * demeaned[i] < 0:
                crossings += 1

        if crossings > 0 and n > 1:
            # Time span
            if "timestamp" in pair_history[0] and "timestamp" in pair_history[-1]:
                span_seconds = pair_history[-1]["timestamp"] - pair_history[0]["timestamp"]
            else:
                span_seconds = float(n - 1)  # assume 1s per entry
            mean_reversion_time = span_seconds / crossings
        else:
            mean_reversion_time = 0.0

        # Profitable windows: windows where spread > combined fee threshold
        fee_threshold = self.polymarket_taker_fee + self.kalshi_taker_fee
        profitable_windows = sum(1 for s in spreads if s > fee_threshold)

        # Normalise to per-day if we have timestamps
        if (
            "timestamp" in pair_history[0]
            and "timestamp" in pair_history[-1]
            and pair_history[-1]["timestamp"] > pair_history[0]["timestamp"]
        ):
            span_days = (
                pair_history[-1]["timestamp"] - pair_history[0]["timestamp"]
            ) / 86400.0
            profitable_windows_per_day = profitable_windows / span_days if span_days > 0 else profitable_windows
        else:
            profitable_windows_per_day = profitable_windows

        return {
            "avg_spread": avg_spread,
            "max_spread": max_spread,
            "min_spread": min_spread,
            "volatility": volatility,
            "mean_reversion_time": mean_reversion_time,
            "profitable_windows_per_day": profitable_windows_per_day,
        }
