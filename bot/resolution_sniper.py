#!/usr/bin/env python3
"""
Resolution Sniper — Stale Market & Known-Outcome Detection
===========================================================
Identifies prediction markets where the real-world outcome is already
known but the market hasn't formally resolved. Buy YES at $0.95 on
events that clearly happened; earn ~5 cents/share when it resolves.

Also detects stale quotes: market-maker orders left on the book at
pre-news prices after a major event.

Design decisions:
- High confidence threshold (0.90) — only trade near-certainties.
- Dispute risk estimation is critical: UMA oracle can be gamed.
- Stale quote detection operates on order-book snapshots.
- EV calculation includes time cost of locked capital.
- Price-based classification is the primary heuristic.
- No LLM needed — pure rule-based detection.

Author: JJ (autonomous)
Date: 2026-03-21
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

try:
    from bot import elastic_client  # noqa: F401
except ImportError:  # pragma: no cover
    pass

logger = logging.getLogger("JJ.resolution_sniper")

# Risk-free rate assumption for time-cost of locked capital.
_ANNUAL_RISK_FREE_RATE: float = 0.05  # 5% per annum

# Price band boundaries.
_BAND_EFFECTIVELY_RESOLVED_HIGH: float = 0.98
_BAND_NEAR_CERTAIN_HIGH: float = 0.94
_BAND_LEANING_HIGH: float = 0.80
_BAND_LEANING_LOW: float = 0.20
_BAND_NEAR_CERTAIN_LOW: float = 0.06
_BAND_EFFECTIVELY_RESOLVED_LOW: float = 0.02

# Keywords that indicate political charge.
_POLITICAL_KEYWORDS: frozenset[str] = frozenset(
    [
        "trump", "biden", "democrat", "republican", "abortion", "impeach",
        "election", "vote", "congress", "senate", "president", "party",
        "legislation", "ballot", "politician", "supreme court", "court",
        "roe", "liberal", "conservative", "gun", "climate", "immigration",
    ]
)

# Keywords that suggest subjective resolution criteria.
_SUBJECTIVE_KEYWORDS: frozenset[str] = frozenset(
    [
        "significant", "major", "substantial", "notable", "considerable",
        "largely", "primarily", "mainly", "mostly", "effectively",
        "generally", "roughly", "approximately", "about", "around",
        "likely", "appears", "seems", "widely regarded", "consensus",
    ]
)

# Minimum reasonable order size to flag as a stale quote.
_MIN_STALE_SIZE: float = 1.0

# Stale quote detection: how far from fair price is "stale"?
_STALE_DISTANCE_THRESHOLD: float = 0.10


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ResolutionTarget:
    """A market identified as a resolution-sniping opportunity."""

    market_id: str
    question: str
    current_yes_price: float
    current_no_price: float
    expected_outcome: str           # "YES" or "NO"
    confidence: float               # How certain we are the outcome is known (0–1)
    evidence: str                   # Why we think this is resolved
    expected_profit_per_share: float  # 1.0 − purchase_price (for YES outcome)
    resolution_eta_hours: float     # Estimated hours until formal resolution
    volume_24h: float
    risk_factors: list[str] = field(default_factory=list)


@dataclass
class StaleQuote:
    """An outdated order-book quote left behind after a market move."""

    market_id: str
    question: str
    side: str                 # "YES" or "NO"
    stale_price: float        # The outdated price
    fair_price: float         # What the price should be
    edge: float               # fair_price − stale_price
    size_available: float     # How many shares at the stale price
    likely_reason: str        # "pre_news_quote", "bot_malfunction", "thin_book"


# ---------------------------------------------------------------------------
# Timing utilities (module-level, not class methods)
# ---------------------------------------------------------------------------


def hours_until_resolution(resolution_date: str) -> float:
    """Parse a resolution date string and return hours from now (UTC).

    Supports ISO-8601 strings (with or without timezone), e.g.:
        "2026-03-22T14:00:00Z"
        "2026-03-22T14:00:00+00:00"
        "2026-03-22 14:00:00"
        "2026-03-22"
    Returns 0.0 if the date cannot be parsed or is already in the past.
    """
    if not resolution_date:
        return 0.0

    # Normalise: replace space separator with T, strip trailing Z for fromisoformat
    s = resolution_date.strip()
    s = s.replace(" ", "T")
    # Python's fromisoformat before 3.11 doesn't handle "Z" suffix
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"

    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # Try date-only
        try:
            dt = datetime.fromisoformat(s.split("T")[0])
        except ValueError:
            logger.warning("hours_until_resolution: unparseable date '%s'", resolution_date)
            return 0.0

    # Make timezone-aware if naive (assume UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    now = datetime.now(tz=timezone.utc)
    delta = dt - now
    hours = delta.total_seconds() / 3600.0
    return max(0.0, hours)


def is_market_hours(hour_utc: int) -> bool:
    """Return True during active trading hours (09–17 UTC Mon–Fri).

    Resolution proposals are submitted more often during business hours
    in the US/EU time zones.  This is a soft filter only.
    """
    return 9 <= hour_utc <= 17


# ---------------------------------------------------------------------------
# Core class
# ---------------------------------------------------------------------------


class ResolutionSniper:
    """Identify prediction-market resolution-sniping and stale-quote opportunities."""

    def __init__(
        self,
        min_confidence: float = 0.90,
        min_profit_per_share: float = 0.02,
        max_resolution_hours: float = 48.0,
        dispute_risk_threshold: float = 0.10,
        stale_edge_threshold: float = 0.05,
    ) -> None:
        self.min_confidence = min_confidence
        self.min_profit_per_share = min_profit_per_share
        self.max_resolution_hours = max_resolution_hours
        self.dispute_risk_threshold = dispute_risk_threshold
        self.stale_edge_threshold = stale_edge_threshold
        logger.info(
            "ResolutionSniper init: min_conf=%.2f min_profit=%.3f "
            "max_hours=%.1f dispute_thresh=%.2f stale_edge=%.2f",
            min_confidence,
            min_profit_per_share,
            max_resolution_hours,
            dispute_risk_threshold,
            stale_edge_threshold,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def classify_resolution_state(
        self,
        yes_price: float,
        no_price: float,
        volume_24h: float = 0.0,
        price_history: Optional[list[float]] = None,
    ) -> dict:
        """Classify the resolution state of a market.

        States:
        - "pre_event":           Price 0.20–0.80; no clear direction.
        - "leaning":             Price 0.80–0.94 or 0.06–0.20; probable but uncertain.
        - "near_certain":        Price >0.94 or <0.06; likely outcome known.
        - "effectively_resolved": Price >0.98 or <0.02; just awaiting formal resolution.

        Returns
        -------
        dict with keys: state, confidence, expected_outcome, profit_if_correct
        """
        # Clamp to valid range
        yes_price = max(0.0, min(1.0, yes_price))

        # Determine direction
        if yes_price >= 0.5:
            outcome = "YES"
            p = yes_price
        else:
            outcome = "NO"
            p = 1.0 - yes_price  # probability that NO wins

        purchase_price = yes_price if outcome == "YES" else no_price
        profit_if_correct = 1.0 - purchase_price

        if p >= _BAND_EFFECTIVELY_RESOLVED_HIGH:
            state = "effectively_resolved"
            confidence = 0.98 + (p - _BAND_EFFECTIVELY_RESOLVED_HIGH) / (1.0 - _BAND_EFFECTIVELY_RESOLVED_HIGH) * 0.01
        elif p >= _BAND_NEAR_CERTAIN_HIGH:
            state = "near_certain"
            # Linear interpolation from 0.90 at boundary to 0.97 just below effectively_resolved
            span = _BAND_EFFECTIVELY_RESOLVED_HIGH - _BAND_NEAR_CERTAIN_HIGH
            frac = (p - _BAND_NEAR_CERTAIN_HIGH) / span
            confidence = 0.90 + frac * 0.07
        elif p >= _BAND_LEANING_HIGH:
            state = "leaning"
            span = _BAND_NEAR_CERTAIN_HIGH - _BAND_LEANING_HIGH
            frac = (p - _BAND_LEANING_HIGH) / span
            confidence = 0.70 + frac * 0.19
        else:
            state = "pre_event"
            confidence = float(p)  # raw probability, no boosting

        confidence = min(confidence, 0.99)

        logger.debug(
            "classify_resolution_state yes=%.3f no=%.3f → %s (conf=%.3f outcome=%s)",
            yes_price, no_price, state, confidence, outcome,
        )

        return {
            "state": state,
            "confidence": confidence,
            "expected_outcome": outcome,
            "profit_if_correct": profit_if_correct,
        }

    def analyze_market(
        self,
        market_id: str,
        question: str,
        yes_price: float,
        no_price: float,
        resolution_source: str = "",
        market_metadata: Optional[dict] = None,
    ) -> Optional[ResolutionTarget]:
        """Analyze a single market for a resolution-sniping opportunity.

        Returns ResolutionTarget if opportunity found (passes all gates),
        None otherwise.
        """
        meta = market_metadata or {}
        volume_24h = float(meta.get("volume_24h", 0.0))
        resolution_eta_hours = float(meta.get("resolution_eta_hours", 24.0))

        classification = self.classify_resolution_state(yes_price, no_price, volume_24h)
        state = classification["state"]
        confidence = classification["confidence"]
        expected_outcome = classification["expected_outcome"]
        profit_if_correct = classification["profit_if_correct"]

        # Must be near_certain or effectively_resolved
        if state not in ("near_certain", "effectively_resolved"):
            logger.debug("analyze_market %s: rejected — state=%s", market_id, state)
            return None

        if confidence < self.min_confidence:
            logger.debug(
                "analyze_market %s: rejected — confidence=%.3f < min=%.3f",
                market_id, confidence, self.min_confidence,
            )
            return None

        if profit_if_correct < self.min_profit_per_share:
            logger.debug(
                "analyze_market %s: rejected — profit=%.4f < min=%.4f",
                market_id, profit_if_correct, self.min_profit_per_share,
            )
            return None

        if resolution_eta_hours > self.max_resolution_hours:
            logger.debug(
                "analyze_market %s: rejected — eta=%.1fh > max=%.1fh",
                market_id, resolution_eta_hours, self.max_resolution_hours,
            )
            return None

        dispute_risk = self.estimate_dispute_risk(question, yes_price, resolution_source)
        if dispute_risk > self.dispute_risk_threshold:
            logger.debug(
                "analyze_market %s: rejected — dispute_risk=%.3f > threshold=%.3f",
                market_id, dispute_risk, self.dispute_risk_threshold,
            )
            return None

        # Build risk factors list
        risk_factors: list[str] = []
        if dispute_risk > 0.05:
            risk_factors.append("dispute_possible")
        if not resolution_source:
            risk_factors.append("resolution_source_unknown")
        q_lower = question.lower()
        if any(kw in q_lower for kw in _SUBJECTIVE_KEYWORDS):
            risk_factors.append("resolution_criteria_ambiguous")
        if "uma" in q_lower or "uma oracle" in resolution_source.lower():
            risk_factors.append("uma_oracle")

        evidence = _build_evidence(state, yes_price, no_price, expected_outcome)

        target = ResolutionTarget(
            market_id=market_id,
            question=question,
            current_yes_price=yes_price,
            current_no_price=no_price,
            expected_outcome=expected_outcome,
            confidence=confidence,
            evidence=evidence,
            expected_profit_per_share=profit_if_correct,
            resolution_eta_hours=resolution_eta_hours,
            volume_24h=volume_24h,
            risk_factors=risk_factors,
        )
        logger.info(
            "analyze_market %s OPPORTUNITY: outcome=%s conf=%.3f profit=%.4f eta=%.1fh",
            market_id, expected_outcome, confidence, profit_if_correct, resolution_eta_hours,
        )
        return target

    def detect_stale_quotes(
        self,
        market_id: str,
        question: str,
        order_book: dict,
        fair_price_estimate: float,
    ) -> list[StaleQuote]:
        """Detect stale/outdated quotes in the order book.

        A quote is "stale" if it is more than ``stale_edge_threshold`` away
        from ``fair_price_estimate`` (in the profitable direction for a
        sniper — i.e. the order offers a better price than fair value).

        order_book format::

            {
                'bids': [{'price': float, 'size': float}, ...],
                'asks': [{'price': float, 'size': float}, ...],
            }

        Returns a list of StaleQuote objects, one per stale level.
        """
        stale: list[StaleQuote] = []
        bids = order_book.get("bids", [])
        asks = order_book.get("asks", [])

        fair = max(0.0, min(1.0, fair_price_estimate))

        # Stale BID: someone is willing to BUY YES at a price far BELOW fair
        # (i.e. we can sell YES to them at a premium — or if we hold YES, their
        # bid is cheap, not exploitable as a sniper).
        # More relevant for sniping: stale ASK — someone is SELLING YES
        # (or selling NO) at a price far BELOW fair value.
        #
        # From a sniper's perspective:
        #   - Stale ASK (someone selling YES cheap): we can buy YES below fair value.
        #   - Stale BID (someone buying YES at a high price after news turned NO):
        #     we could sell YES to them (above fair) — also exploitable.

        for ask in asks:
            price = float(ask.get("price", 0.0))
            size = float(ask.get("size", 0.0))
            if size < _MIN_STALE_SIZE:
                continue
            # Ask is stale if it is priced significantly BELOW fair value
            # (we can buy YES cheaper than fair — free money if outcome known)
            edge = fair - price
            if edge >= self.stale_edge_threshold:
                reason = _classify_stale_reason(price, fair)
                sq = StaleQuote(
                    market_id=market_id,
                    question=question,
                    side="YES",
                    stale_price=price,
                    fair_price=fair,
                    edge=edge,
                    size_available=size,
                    likely_reason=reason,
                )
                stale.append(sq)
                logger.debug(
                    "detect_stale_quotes %s: stale ASK YES price=%.3f fair=%.3f edge=%.3f",
                    market_id, price, fair, edge,
                )

        for bid in bids:
            price = float(bid.get("price", 0.0))
            size = float(bid.get("size", 0.0))
            if size < _MIN_STALE_SIZE:
                continue
            # Bid is stale if it is priced significantly ABOVE fair value
            # (someone is over-paying for YES — we could sell YES to them)
            edge = price - fair
            if edge >= self.stale_edge_threshold:
                reason = _classify_stale_reason(fair, price)
                sq = StaleQuote(
                    market_id=market_id,
                    question=question,
                    side="YES",
                    stale_price=price,
                    fair_price=fair,
                    edge=edge,
                    size_available=size,
                    likely_reason=reason,
                )
                stale.append(sq)
                logger.debug(
                    "detect_stale_quotes %s: stale BID YES price=%.3f fair=%.3f edge=%.3f",
                    market_id, price, fair, edge,
                )

        return stale

    def estimate_dispute_risk(
        self,
        question: str,
        yes_price: float,
        resolution_source: str = "",
    ) -> float:
        """Estimate probability that a resolution will be disputed.

        Base risk 0.02.  Increments:
        +0.05  politically charged language
        +0.10  subjective resolution criteria
        +0.05  large open interest on losing side (proxied by price distance from extremes)
        +0.10  no resolution source specified
        +0.05  UMA oracle mentioned

        Returns probability in [0, 1].
        """
        risk = 0.02
        q_lower = question.lower()
        src_lower = resolution_source.lower()

        # Political charge
        if any(kw in q_lower for kw in _POLITICAL_KEYWORDS):
            risk += 0.05

        # Subjective criteria
        if any(kw in q_lower for kw in _SUBJECTIVE_KEYWORDS):
            risk += 0.10

        # Large open interest on losing side: price in 0.80–0.95 means many
        # losing-side holders who might dispute.
        p = max(yes_price, 1.0 - yes_price)
        if 0.80 <= p < 0.95:
            risk += 0.05

        # No resolution source
        if not resolution_source.strip():
            risk += 0.10

        # UMA oracle
        if "uma" in q_lower or "uma" in src_lower:
            risk += 0.05

        risk = min(risk, 1.0)
        logger.debug("estimate_dispute_risk: %.3f for '%s'", risk, question[:60])
        return risk

    def calculate_expected_value(self, target: ResolutionTarget) -> float:
        """Compute expected value per share.

        EV = confidence × profit − (1 − confidence) × loss − time_cost

        loss = purchase_price (lose entire stake if wrong)
        time_cost = purchase_price × risk_free_rate × hours / 8760
        """
        if target.expected_outcome == "YES":
            purchase_price = target.current_yes_price
        else:
            purchase_price = target.current_no_price

        profit = target.expected_profit_per_share
        loss = purchase_price  # lose entire stake
        c = target.confidence

        # Opportunity cost of locked capital
        time_cost = (
            purchase_price
            * _ANNUAL_RISK_FREE_RATE
            * target.resolution_eta_hours
            / 8760.0
        )

        ev = c * profit - (1.0 - c) * loss - time_cost
        logger.debug(
            "calculate_expected_value %s: ev=%.5f (c=%.3f profit=%.4f loss=%.4f tc=%.5f)",
            target.market_id, ev, c, profit, loss, time_cost,
        )
        return ev

    def scan_markets(self, markets: list[dict]) -> list[ResolutionTarget]:
        """Scan a list of markets and return opportunities sorted by EV descending.

        Each market dict should contain at minimum:
            market_id, question, yes_price, no_price

        Optional keys: volume_24h, resolution_source, resolution_eta_hours,
        and any other metadata passed through to analyze_market.
        """
        opportunities: list[ResolutionTarget] = []

        for m in markets:
            mid = m.get("market_id", "unknown")
            question = m.get("question", "")
            yes_price = float(m.get("yes_price", 0.5))
            no_price = float(m.get("no_price", 0.5))
            resolution_source = m.get("resolution_source", "")

            # Build metadata dict from remaining fields
            metadata = {k: v for k, v in m.items()
                        if k not in ("market_id", "question", "yes_price",
                                     "no_price", "resolution_source")}

            target = self.analyze_market(
                market_id=mid,
                question=question,
                yes_price=yes_price,
                no_price=no_price,
                resolution_source=resolution_source,
                market_metadata=metadata,
            )
            if target is not None:
                opportunities.append(target)

        # Sort by EV descending
        opportunities.sort(key=self.calculate_expected_value, reverse=True)

        logger.info(
            "scan_markets: %d markets scanned, %d opportunities found",
            len(markets), len(opportunities),
        )
        return opportunities

    def format_alert(self, target: ResolutionTarget) -> str:
        """Format a ResolutionTarget as a Telegram-ready alert string."""
        outcome_emoji = "[YES]" if target.expected_outcome == "YES" else "[NO]"
        conf_pct = f"{target.confidence * 100:.1f}%"
        profit_cents = f"{target.expected_profit_per_share * 100:.1f}c"
        price = (
            target.current_yes_price
            if target.expected_outcome == "YES"
            else target.current_no_price
        )
        ev = self.calculate_expected_value(target)

        lines = [
            f"RESOLUTION SNIPER {outcome_emoji}",
            f"Market: {target.market_id}",
            f"Q: {target.question[:120]}",
            f"Outcome: {target.expected_outcome} @ ${price:.3f}",
            f"Confidence: {conf_pct}",
            f"Profit/share: {profit_cents}",
            f"EV: ${ev:.4f}",
            f"ETA: {target.resolution_eta_hours:.1f}h",
            f"Evidence: {target.evidence}",
        ]

        if target.risk_factors:
            lines.append(f"Risks: {', '.join(target.risk_factors)}")
        else:
            lines.append("Risks: none flagged")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _build_evidence(
    state: str,
    yes_price: float,
    no_price: float,
    expected_outcome: str,
) -> str:
    """Produce a concise evidence string based on price signal."""
    p = yes_price if expected_outcome == "YES" else no_price
    if state == "effectively_resolved":
        return (
            f"Price {p:.3f} > 0.98 — market effectively resolved; "
            "formal confirmation pending"
        )
    elif state == "near_certain":
        return (
            f"Price {p:.3f} in near-certain band (0.94–0.98); "
            "strong consensus on outcome"
        )
    else:
        return f"Price {p:.3f} — {state}"


def _classify_stale_reason(lower_price: float, higher_price: float) -> str:
    """Classify the likely reason a quote is stale based on price gap magnitude."""
    gap = abs(higher_price - lower_price)
    if gap >= 0.30:
        return "pre_news_quote"
    elif gap >= 0.15:
        return "bot_malfunction"
    else:
        return "thin_book"
