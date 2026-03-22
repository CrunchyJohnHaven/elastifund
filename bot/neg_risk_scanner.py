#!/usr/bin/env python3
"""Negative-risk and combinatorial arbitrage scanner for Polymarket multi-outcome markets.

Scans for two classes of guaranteed-profit opportunities:

1. NEGATIVE RISK: Multiple outcomes for the same event have YES prices summing
   to less than $1.00 — buying one YES share of every outcome guarantees $1.00
   payout regardless of which outcome resolves.

2. COMBINATORIAL CONSTRAINT VIOLATIONS: Logically-ordered markets violate
   monotonicity (e.g., P(BTC > $95k) > P(BTC > $90k) is impossible).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging
import re
import time
from typing import Any

try:
    import httpx as _httpx
    _HTTPX_AVAILABLE = True
except ImportError:  # pragma: no cover - optional at import time
    _HTTPX_AVAILABLE = False

try:
    from bot.elastic_client import ElasticClient
    _elastic_import_ok = True
except ImportError:  # pragma: no cover - direct script mode
    try:
        from elastic_client import ElasticClient  # type: ignore
        _elastic_import_ok = True
    except ImportError:
        _elastic_import_ok = False

logger = logging.getLogger("JJ.neg_risk_scanner")

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class MarketOutcome:
    """A single market in a multi-outcome event group."""
    market_id: str
    condition_id: str
    question: str
    yes_price: float
    no_price: float
    yes_token_id: str
    no_token_id: str
    volume_24h: float
    liquidity: float


@dataclass
class ArbitrageOpportunity:
    """A detected arbitrage opportunity, fully described."""
    opportunity_type: str          # "negative_risk" or "combinatorial"
    market_group_id: str           # Polymarket group/condition ID
    markets: list[dict]            # [{market_id, question, yes_price, no_price, token_id}]
    total_cost: float              # Sum of YES prices (or cost of arb portfolio)
    guaranteed_payout: float       # $1.00 for negative risk
    profit_per_share: float        # guaranteed_payout - total_cost
    profit_pct: float              # profit_per_share / total_cost
    required_capital: float        # total_cost * min_shares
    constraint_violated: str       # Description of the logical constraint violated
    timestamp: float = field(default_factory=time.time)

    @property
    def is_profitable_after_fees(self) -> bool:
        """True if profit exceeds taker fees across all legs.

        Taker fee is ~1.5% per leg. For N legs that is N * 0.015 * avg_price.
        We use total_cost / n_legs as the average price per leg.
        """
        n = len(self.markets)
        if n == 0:
            return False
        avg_price = self.total_cost / n
        fee_cost = n * 0.015 * avg_price
        return self.profit_per_share > fee_cost


# ---------------------------------------------------------------------------
# Threshold / pattern extraction helpers
# ---------------------------------------------------------------------------

# Matches dollar amounts with optional commas and k/K/M suffix.
# Captures: sign keywords, numeric value.
_THRESHOLD_RE = re.compile(
    r"""
    (?:above|below|over|under|exceed|reach|hit|cross|surpass|go\s+(?:above|below|over|under)|>|<|>=|<=|\bprice\b.*?(?:above|below|>|<))
    \s*
    \$?\s*
    ([\d,]+(?:\.\d+)?)\s*([kKmMbB])?
    """,
    re.VERBOSE | re.IGNORECASE,
)

# Simpler capture: bare "$85k", "$90,000", "85000"
_DOLLAR_VALUE_RE = re.compile(
    r"\$\s*([\d,]+(?:\.\d+)?)\s*([kKmMbB])?",
    re.IGNORECASE,
)

_SUFFIX_MAP = {
    "k": 1_000,
    "m": 1_000_000,
    "b": 1_000_000_000,
}

# Month → quarter mapping for time-subset detection
_MONTH_TO_QUARTER: dict[str, int] = {
    "january": 1, "jan": 1,
    "february": 1, "feb": 1,
    "march": 1, "mar": 1,
    "april": 2, "apr": 2,
    "may": 2,
    "june": 2, "jun": 2,
    "july": 3, "jul": 3,
    "august": 3, "aug": 3,
    "september": 3, "sep": 3, "sept": 3,
    "october": 4, "oct": 4,
    "november": 4, "nov": 4,
    "december": 4, "dec": 4,
}

_QUARTER_RE = re.compile(r"\bq([1-4])\b", re.IGNORECASE)
_MONTH_RE = re.compile(
    r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|"
    r"dec(?:ember)?)\b",
    re.IGNORECASE,
)


def _parse_suffix(num_str: str, suffix: str | None) -> float:
    value = float(num_str.replace(",", ""))
    if suffix:
        value *= _SUFFIX_MAP.get(suffix.lower(), 1)
    return value


def extract_threshold(question: str) -> float | None:
    """Extract a numeric price threshold from a market question string.

    Handles formats like:
    - "Bitcoin above $95,000"    → 95000.0
    - "BTC above $95k"           → 95000.0
    - "Bitcoin price > $95,000.00" → 95000.0
    - "BTC below 90000"          → 90000.0
    - "above $100K"              → 100000.0
    - "ETH above $3.5k"          → 3500.0

    Returns None if no threshold is detected.
    """
    # Try the directional-keyword + dollar regex first.
    m = _THRESHOLD_RE.search(question)
    if m:
        return _parse_suffix(m.group(1), m.group(2))

    # Fall back to bare dollar-sign extraction.
    m = _DOLLAR_VALUE_RE.search(question)
    if m:
        return _parse_suffix(m.group(1), m.group(2))

    return None


def _extract_direction(question: str) -> str:
    """Return 'above' or 'below' from a question string, defaulting to 'above'."""
    low = question.lower()
    if any(kw in low for kw in ("below", "under", "less than", "< $", "<$")):
        return "below"
    return "above"


def _extract_month_quarter(question: str) -> tuple[str | None, int | None]:
    """Return (month_name_lower, quarter_int) for any detected time reference."""
    q_match = _QUARTER_RE.search(question)
    quarter = int(q_match.group(1)) if q_match else None
    m_match = _MONTH_RE.search(question)
    month = m_match.group(1).lower() if m_match else None
    return month, quarter


# ---------------------------------------------------------------------------
# Core scanner
# ---------------------------------------------------------------------------

class NegativeRiskScanner:
    """Scan Polymarket for neg-risk and combinatorial arbitrage opportunities."""

    def __init__(
        self,
        min_profit_pct: float = 0.005,
        min_liquidity: float = 100.0,
        max_outcomes: int = 20,
        api_base: str = "https://gamma-api.polymarket.com",
        taker_fee: float = 0.015,
    ) -> None:
        self.min_profit_pct = min_profit_pct
        self.min_liquidity = min_liquidity
        self.max_outcomes = max_outcomes
        self.api_base = api_base.rstrip("/")
        self.taker_fee = taker_fee

    # ------------------------------------------------------------------
    # API fetch
    # ------------------------------------------------------------------

    async def fetch_grouped_markets(
        self,
        _override: dict[str, list[MarketOutcome]] | None = None,
    ) -> dict[str, list[MarketOutcome]]:
        """Fetch all active markets grouped by condition_id.

        Returns {condition_id: [MarketOutcome, ...]}.

        Pass _override for testing without live API calls.
        """
        if _override is not None:
            return _override

        if not _HTTPX_AVAILABLE:
            logger.warning("httpx not available; returning empty market dict")
            return {}

        groups: dict[str, list[MarketOutcome]] = {}
        offset = 0
        limit = 500

        async with _httpx.AsyncClient(timeout=30.0) as client:
            while True:
                url = (
                    f"{self.api_base}/markets"
                    f"?active=true&closed=false&limit={limit}&offset={offset}"
                )
                try:
                    resp = await client.get(url, headers={"Accept": "application/json"})
                    resp.raise_for_status()
                    data: list[dict] = resp.json()
                except Exception as exc:  # pragma: no cover
                    logger.error("fetch_grouped_markets error at offset=%d: %s", offset, exc)
                    break

                if not data:
                    break

                for raw in data:
                    mo = self._parse_market_outcome(raw)
                    if mo is None:
                        continue
                    groups.setdefault(mo.condition_id, []).append(mo)

                if len(data) < limit:
                    break
                offset += limit

        return groups

    def _parse_market_outcome(self, raw: dict[str, Any]) -> MarketOutcome | None:
        """Parse a Gamma API market dict into a MarketOutcome."""
        try:
            condition_id = raw.get("conditionId") or raw.get("condition_id") or ""
            if not condition_id:
                return None

            # Extract prices from outcomePrices JSON array or bestBid/bestAsk fields
            yes_price = self._extract_yes_price(raw)
            no_price = 1.0 - yes_price if 0.0 <= yes_price <= 1.0 else 0.5

            # Token IDs — outcomePrices array index 0=YES, 1=NO
            clob_tokens = raw.get("clobTokenIds") or "[]"
            if isinstance(clob_tokens, str):
                import json as _json
                try:
                    token_list = _json.loads(clob_tokens)
                except Exception:
                    token_list = clob_tokens.split(",")
            else:
                token_list = list(clob_tokens)

            yes_token = str(token_list[0]).strip() if len(token_list) > 0 else ""
            no_token = str(token_list[1]).strip() if len(token_list) > 1 else ""

            return MarketOutcome(
                market_id=str(raw.get("id") or raw.get("market_id") or ""),
                condition_id=condition_id,
                question=str(raw.get("question") or ""),
                yes_price=yes_price,
                no_price=no_price,
                yes_token_id=yes_token,
                no_token_id=no_token,
                volume_24h=float(raw.get("volume24hr") or raw.get("volume_24h") or 0.0),
                liquidity=float(raw.get("liquidity") or 0.0),
            )
        except Exception as exc:  # pragma: no cover
            logger.debug("_parse_market_outcome failed: %s", exc)
            return None

    def _extract_yes_price(self, raw: dict[str, Any]) -> float:
        """Extract the YES mid-price from various Gamma API field shapes."""
        # Direct yes_price field (from normalised input)
        for key in ("yes_price", "yesPrice"):
            v = raw.get(key)
            if v is not None:
                try:
                    f = float(v)
                    if 0.0 <= f <= 1.0:
                        return f
                except (TypeError, ValueError):
                    pass

        # bestBid/bestAsk → mid
        bid = raw.get("bestBid")
        ask = raw.get("bestAsk")
        if bid is not None and ask is not None:
            try:
                b, a = float(bid), float(ask)
                if 0.0 <= b <= 1.0 and 0.0 <= a <= 1.0 and a >= b:
                    return (b + a) / 2.0
            except (TypeError, ValueError):
                pass

        # outcomePrices JSON array: [yes_price, no_price]
        op = raw.get("outcomePrices")
        if isinstance(op, str):
            import json as _json
            try:
                op = _json.loads(op)
            except Exception:
                op = None
        if isinstance(op, (list, tuple)) and len(op) >= 1:
            try:
                f = float(op[0])
                if 0.0 <= f <= 1.0:
                    return f
            except (TypeError, ValueError):
                pass

        return 0.5  # sentinel

    # ------------------------------------------------------------------
    # Negative-risk scan
    # ------------------------------------------------------------------

    def scan_negative_risk(
        self, grouped_markets: dict[str, list[MarketOutcome]]
    ) -> list[ArbitrageOpportunity]:
        """Find groups where sum of YES prices < 1.0 — a guaranteed-profit basket."""
        opportunities: list[ArbitrageOpportunity] = []

        for condition_id, outcomes in grouped_markets.items():
            if len(outcomes) < 2 or len(outcomes) > self.max_outcomes:
                continue

            # Liquidity gate: every leg must be liquid enough.
            if any(o.liquidity < self.min_liquidity for o in outcomes):
                continue

            total_cost = sum(o.yes_price for o in outcomes)
            guaranteed_payout = 1.0
            profit_per_share = guaranteed_payout - total_cost

            if profit_per_share <= 0:
                continue

            profit_pct = profit_per_share / total_cost if total_cost > 0 else 0.0
            if profit_pct < self.min_profit_pct:
                continue

            # Fee check
            n = len(outcomes)
            avg_price = total_cost / n
            fee_cost = n * self.taker_fee * avg_price
            if profit_per_share <= fee_cost:
                continue

            required_capital = total_cost  # for one share of each outcome

            opp = ArbitrageOpportunity(
                opportunity_type="negative_risk",
                market_group_id=condition_id,
                markets=[
                    {
                        "market_id": o.market_id,
                        "question": o.question,
                        "yes_price": o.yes_price,
                        "no_price": o.no_price,
                        "token_id": o.yes_token_id,
                    }
                    for o in outcomes
                ],
                total_cost=round(total_cost, 6),
                guaranteed_payout=guaranteed_payout,
                profit_per_share=round(profit_per_share, 6),
                profit_pct=round(profit_pct, 6),
                required_capital=round(required_capital, 6),
                constraint_violated=(
                    f"YES prices sum to {total_cost:.4f} < 1.00 "
                    f"({n} outcomes, {condition_id})"
                ),
            )
            opportunities.append(opp)
            logger.info(
                "neg_risk opportunity: group=%s cost=%.4f profit_pct=%.2f%%",
                condition_id, total_cost, profit_pct * 100,
            )

        return sorted(opportunities, key=lambda x: x.profit_pct, reverse=True)

    # ------------------------------------------------------------------
    # Combinatorial scan
    # ------------------------------------------------------------------

    def scan_combinatorial(
        self, grouped_markets: dict[str, list[MarketOutcome]]
    ) -> list[ArbitrageOpportunity]:
        """Find logical constraint violations between related markets."""
        opportunities: list[ArbitrageOpportunity] = []

        # Flatten all markets for cross-group analysis
        all_markets: list[MarketOutcome] = [
            m for outcomes in grouped_markets.values() for m in outcomes
        ]

        # 1. Ordered thresholds (e.g., BTC price levels)
        threshold_groups = self._detect_ordered_threshold_groups(all_markets)
        for group in threshold_groups:
            opps = self._check_ordered_threshold_violations(group)
            opportunities.extend(opps)

        # 2. Time-subset relationships (e.g., "in March" vs "in Q1")
        subset_pairs = self._detect_time_subset_groups(all_markets)
        for narrow, wide in subset_pairs:
            # P(wide) >= P(narrow) always. If P(narrow) > P(wide), violation.
            if narrow.yes_price <= wide.yes_price + 1e-6:
                continue
            if narrow.liquidity < self.min_liquidity or wide.liquidity < self.min_liquidity:
                continue
            cost = narrow.yes_price  # we'd sell the narrow / buy the wide
            profit = narrow.yes_price - wide.yes_price
            profit_pct = profit / cost if cost > 0 else 0.0
            if profit_pct < self.min_profit_pct:
                continue
            opp = ArbitrageOpportunity(
                opportunity_type="combinatorial",
                market_group_id=f"{narrow.condition_id}|{wide.condition_id}",
                markets=[
                    {
                        "market_id": narrow.market_id,
                        "question": narrow.question,
                        "yes_price": narrow.yes_price,
                        "no_price": narrow.no_price,
                        "token_id": narrow.yes_token_id,
                        "role": "narrow_time_window",
                    },
                    {
                        "market_id": wide.market_id,
                        "question": wide.question,
                        "yes_price": wide.yes_price,
                        "no_price": wide.no_price,
                        "token_id": wide.yes_token_id,
                        "role": "wide_time_window",
                    },
                ],
                total_cost=round(cost, 6),
                guaranteed_payout=round(narrow.yes_price, 6),
                profit_per_share=round(profit, 6),
                profit_pct=round(profit_pct, 6),
                required_capital=round(cost, 6),
                constraint_violated=(
                    f"Time subset violation: narrow '{narrow.question}' "
                    f"({narrow.yes_price:.3f}) > wide '{wide.question}' "
                    f"({wide.yes_price:.3f})"
                ),
            )
            opportunities.append(opp)

        return sorted(opportunities, key=lambda x: x.profit_pct, reverse=True)

    def _detect_ordered_threshold_groups(
        self, markets: list[MarketOutcome]
    ) -> list[list[MarketOutcome]]:
        """Find groups of markets with ordered numeric thresholds on the same underlying.

        Markets are bucketed by their 'skeleton' (question with numbers stripped).
        Within each bucket, only markets with extractable thresholds are grouped.
        """
        skeleton_buckets: dict[str, list[tuple[float, MarketOutcome]]] = {}

        for m in markets:
            threshold = extract_threshold(m.question)
            if threshold is None:
                continue
            skeleton = _question_skeleton(m.question)
            skeleton_buckets.setdefault(skeleton, []).append((threshold, m))

        groups: list[list[MarketOutcome]] = []
        for bucket in skeleton_buckets.values():
            if len(bucket) < 2:
                continue
            # Sort by threshold ascending
            sorted_bucket = sorted(bucket, key=lambda x: x[0])
            groups.append([m for _, m in sorted_bucket])

        return groups

    def _check_ordered_threshold_violations(
        self, sorted_group: list[MarketOutcome]
    ) -> list[ArbitrageOpportunity]:
        """For a threshold-sorted group, check monotonicity violations.

        For 'above' markets: P(above A) >= P(above B) when A < B.
        Violation: P(above B) > P(above A) when B > A.
        """
        opportunities: list[ArbitrageOpportunity] = []

        direction = _extract_direction(sorted_group[0].question)

        for i in range(len(sorted_group) - 1):
            lower = sorted_group[i]    # lower threshold
            higher = sorted_group[i + 1]  # higher threshold

            if lower.liquidity < self.min_liquidity or higher.liquidity < self.min_liquidity:
                continue

            if direction == "above":
                # P(above lower_threshold) >= P(above higher_threshold)
                # Violation: higher.yes_price > lower.yes_price
                violation_magnitude = higher.yes_price - lower.yes_price
            else:
                # P(below lower_threshold) <= P(below higher_threshold)
                # Violation: lower.yes_price > higher.yes_price
                violation_magnitude = lower.yes_price - higher.yes_price

            if violation_magnitude <= 1e-6:
                continue

            # Arb: buy the cheap leg, short (or avoid) the expensive leg
            cost = min(lower.yes_price, higher.yes_price)
            profit_per_share = violation_magnitude
            profit_pct = profit_per_share / cost if cost > 0 else 0.0

            if profit_pct < self.min_profit_pct:
                continue

            opp = ArbitrageOpportunity(
                opportunity_type="combinatorial",
                market_group_id=f"{lower.condition_id}|{higher.condition_id}",
                markets=[
                    {
                        "market_id": lower.market_id,
                        "question": lower.question,
                        "yes_price": lower.yes_price,
                        "no_price": lower.no_price,
                        "token_id": lower.yes_token_id,
                        "role": "lower_threshold",
                    },
                    {
                        "market_id": higher.market_id,
                        "question": higher.question,
                        "yes_price": higher.yes_price,
                        "no_price": higher.no_price,
                        "token_id": higher.yes_token_id,
                        "role": "higher_threshold",
                    },
                ],
                total_cost=round(cost, 6),
                guaranteed_payout=round(cost + profit_per_share, 6),
                profit_per_share=round(profit_per_share, 6),
                profit_pct=round(profit_pct, 6),
                required_capital=round(cost, 6),
                constraint_violated=(
                    f"Monotonicity violation ({direction}): "
                    f"'{higher.question}' ({higher.yes_price:.3f}) > "
                    f"'{lower.question}' ({lower.yes_price:.3f}); "
                    f"diff={violation_magnitude:.4f}"
                ),
            )
            opportunities.append(opp)
            logger.info(
                "combinatorial opportunity: %s violation=%.4f profit_pct=%.2f%%",
                opp.constraint_violated[:60],
                violation_magnitude,
                profit_pct * 100,
            )

        return opportunities

    def _detect_time_subset_groups(
        self, markets: list[MarketOutcome]
    ) -> list[tuple[MarketOutcome, MarketOutcome]]:
        """Find pairs where one market's time window is a subset of the other.

        E.g., 'in March' ⊂ 'in Q1 2026'.
        Returns (narrow_market, wide_market) pairs.
        """
        pairs: list[tuple[MarketOutcome, MarketOutcome]] = []

        for i, m_i in enumerate(markets):
            month_i, quarter_i = _extract_month_quarter(m_i.question)
            if month_i is None and quarter_i is None:
                continue
            for j, m_j in enumerate(markets):
                if i == j:
                    continue
                month_j, quarter_j = _extract_month_quarter(m_j.question)
                if month_j is None and quarter_j is None:
                    continue

                # Check if m_i is a narrow (month) and m_j is the containing quarter
                if month_i is not None and quarter_j is not None:
                    month_q = _MONTH_TO_QUARTER.get(month_i)
                    if month_q == quarter_j:
                        # m_i is the narrow window, m_j is the wide window
                        pairs.append((m_i, m_j))

        return pairs

    # ------------------------------------------------------------------
    # Portfolio construction
    # ------------------------------------------------------------------

    def calculate_optimal_portfolio(
        self, opportunity: ArbitrageOpportunity
    ) -> dict[str, dict]:
        """Compute the exact orders to place for a given opportunity.

        Returns {market_id: {side, price, size, token_id}}.
        """
        orders: dict[str, dict] = {}

        if opportunity.opportunity_type == "negative_risk":
            # Buy one YES share on every outcome leg
            for leg in opportunity.markets:
                orders[leg["market_id"]] = {
                    "side": "YES",
                    "price": leg["yes_price"],
                    "size": 1,
                    "token_id": leg["token_id"],
                }

        elif opportunity.opportunity_type == "combinatorial":
            # Find the two legs
            if len(opportunity.markets) < 2:
                return orders

            legs = opportunity.markets
            # Identify cheap vs expensive leg
            cheap = min(legs, key=lambda x: x["yes_price"])
            expensive = max(legs, key=lambda x: x["yes_price"])

            role_cheap = cheap.get("role", "")
            role_expensive = expensive.get("role", "")

            if "lower_threshold" in (role_cheap, role_expensive):
                # Threshold monotonicity: buy the cheap leg (YES),
                # hedge by buying NO on the expensive leg
                orders[cheap["market_id"]] = {
                    "side": "YES",
                    "price": cheap["yes_price"],
                    "size": 1,
                    "token_id": cheap["token_id"],
                }
                orders[expensive["market_id"]] = {
                    "side": "NO",
                    "price": expensive["no_price"],
                    "size": 1,
                    "token_id": expensive.get("no_token_id", ""),
                }
            elif "narrow_time_window" in (role_cheap, role_expensive):
                # Time subset: sell narrow (overpriced), buy wide (underpriced)
                narrow_leg = next(
                    (x for x in legs if x.get("role") == "narrow_time_window"), legs[0]
                )
                wide_leg = next(
                    (x for x in legs if x.get("role") == "wide_time_window"), legs[1]
                )
                orders[narrow_leg["market_id"]] = {
                    "side": "NO",
                    "price": narrow_leg["no_price"],
                    "size": 1,
                    "token_id": narrow_leg.get("no_token_id", ""),
                }
                orders[wide_leg["market_id"]] = {
                    "side": "YES",
                    "price": wide_leg["yes_price"],
                    "size": 1,
                    "token_id": wide_leg["token_id"],
                }
            else:
                # Default: buy the cheap leg
                orders[cheap["market_id"]] = {
                    "side": "YES",
                    "price": cheap["yes_price"],
                    "size": 1,
                    "token_id": cheap["token_id"],
                }

        return orders

    # ------------------------------------------------------------------
    # Top-level orchestration
    # ------------------------------------------------------------------

    async def scan_all(
        self,
        market_data: dict[str, list[MarketOutcome]] | None = None,
    ) -> list[ArbitrageOpportunity]:
        """Run all scanners and return opportunities sorted by profit_pct descending.

        If market_data is None, fetch live data from API.
        """
        grouped = await self.fetch_grouped_markets(_override=market_data)
        neg_risk_opps = self.scan_negative_risk(grouped)
        combinatorial_opps = self.scan_combinatorial(grouped)
        all_opps = neg_risk_opps + combinatorial_opps
        all_opps.sort(key=lambda x: x.profit_pct, reverse=True)

        if all_opps:
            logger.info(
                "scan_all complete: %d neg_risk + %d combinatorial opportunities",
                len(neg_risk_opps), len(combinatorial_opps),
            )
        else:
            logger.debug("scan_all complete: no opportunities found")

        return all_opps

    # ------------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------------

    def format_alert(self, opp: ArbitrageOpportunity) -> str:
        """Format an opportunity as a human-readable Telegram alert string."""
        lines = [
            f"[ARB ALERT] {opp.opportunity_type.upper().replace('_', ' ')}",
            f"Group: {opp.market_group_id}",
            f"Profit: {opp.profit_pct * 100:.2f}% (${opp.profit_per_share:.4f}/share)",
            f"Cost:   ${opp.total_cost:.4f}  |  Payout: ${opp.guaranteed_payout:.4f}",
            f"Capital required: ${opp.required_capital:.4f}",
            f"Constraint: {opp.constraint_violated}",
            f"After-fee profitable: {opp.is_profitable_after_fees}",
            f"Legs ({len(opp.markets)}):",
        ]
        for leg in opp.markets:
            lines.append(
                f"  {leg['market_id']}: YES={leg['yes_price']:.3f}  "
                f"Q: {leg['question'][:60]}"
            )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _question_skeleton(question: str) -> str:
    """Strip numbers/dates from a question to produce a grouping skeleton."""
    text = question.lower()
    # Remove dollar amounts and numeric thresholds
    text = re.sub(r"\$[\d,]+(?:\.\d+)?\s*[kKmMbB]?", " <val> ", text)
    text = re.sub(r"\b\d[\d,]*(?:\.\d+)?\s*[kKmMbB]?\b", " <val> ", text)
    # Remove year references
    text = re.sub(r"\b20\d{2}\b", " <year> ", text)
    # Normalise whitespace and punctuation
    text = re.sub(r"[^a-z<>\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------

def btc_price_ladder_scanner() -> NegativeRiskScanner:
    """Pre-configured scanner for BTC price-level markets.

    Lower min_profit threshold (0.3%) because BTC ladders are high-frequency.
    """
    return NegativeRiskScanner(
        min_profit_pct=0.003,
        min_liquidity=50.0,
        max_outcomes=30,
    )
