"""
Semantic Alignment — Cross-Platform Event Matching and Convergence
==================================================================
Dispatch: DISPATCH_107 (Deep Research Integration)

Detects when Polymarket and Kalshi list "the same" event at different
prices. Prices can diverge due to: different resolution wording, timing
differences, tie-break rules, or pure liquidity friction.

When divergence exceeds threshold and contracts are confirmed aligned
(same resolution semantics), generates a SemanticArbSignal for hedged
convergence trades.

Academic source: 2026 paper on cross-platform aligned prediction markets
and semantic non-fungibility.

Signal Source: #9 in jj_live.py

Author: JJ (autonomous)
Date: 2026-03-23
"""

import asyncio
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from enum import Enum
from typing import Optional

logger = logging.getLogger("JJ.semantic_alignment")

try:
    from bot.net_edge_accounting import (
        FeeSchedule,
        evaluate_edge,
        net_edge,
    )
except ImportError:
    from net_edge_accounting import (  # type: ignore
        FeeSchedule,
        evaluate_edge,
        net_edge,
    )


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class AlignmentConfig:
    """Configuration for semantic alignment detector."""
    # Minimum text similarity (0-1) for initial match
    min_similarity: float = 0.60
    # Minimum price divergence (fraction) to flag
    min_divergence: float = 0.03
    # Maximum acceptable "false parity" rate (fraction)
    max_false_parity_rate: float = 0.20
    # Maximum days to convergence (capital lockup constraint)
    max_convergence_days: int = 14
    # Minimum net edge (bps) after both venue fees
    min_net_edge_bps: float = 30.0
    # LLM semantic verification: require LLM confirmation of alignment
    require_llm_verification: bool = True
    # Maximum simultaneous arb positions
    max_positions: int = 10
    # Maximum capital per arb (fraction of bankroll)
    max_position_frac: float = 0.10


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

class AlignmentStatus(Enum):
    CANDIDATE = "candidate"        # initial text match
    VERIFIED = "verified"          # LLM confirmed same event
    FALSE_PARITY = "false_parity"  # LLM confirmed different resolution rules
    EXPIRED = "expired"            # convergence window passed


@dataclass
class ContractInfo:
    """Contract information from either venue."""
    venue: str              # "polymarket" or "kalshi"
    market_id: str
    token_id: str
    question: str
    category: str
    resolution_source: str   # who/what resolves it
    resolution_rules: str    # exact resolution criteria
    end_date_iso: str
    yes_price: float
    no_price: float
    bid: float
    ask: float
    volume_24h: float = 0.0

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0 if self.bid > 0 and self.ask > 0 else self.yes_price

    @property
    def spread(self) -> float:
        return self.ask - self.bid if self.bid > 0 and self.ask > 0 else 0.05


@dataclass
class AlignedPair:
    """A pair of contracts believed to represent the same event."""
    pair_id: str
    poly_contract: ContractInfo
    kalshi_contract: ContractInfo
    text_similarity: float
    status: AlignmentStatus = AlignmentStatus.CANDIDATE
    llm_verification: Optional[str] = None
    divergence: float = 0.0      # |poly_mid - kalshi_mid|
    created_at: float = 0.0
    last_updated: float = 0.0

    @property
    def poly_mid(self) -> float:
        return self.poly_contract.mid

    @property
    def kalshi_mid(self) -> float:
        return self.kalshi_contract.mid

    def update_divergence(self) -> float:
        self.divergence = abs(self.poly_mid - self.kalshi_mid)
        self.last_updated = time.time()
        return self.divergence


@dataclass
class SemanticArbSignal:
    """Generated when aligned pair has exploitable price divergence."""
    pair_id: str
    # Long leg (buy on cheaper venue)
    long_venue: str
    long_market_id: str
    long_token_id: str
    long_side: str      # "BUY_YES" or "BUY_NO"
    long_price: float
    # Short leg (sell on expensive venue)
    short_venue: str
    short_market_id: str
    short_token_id: str
    short_side: str
    short_price: float
    # Edge metrics
    divergence: float
    gross_edge_bps: float
    net_edge_bps: float
    position_usd_per_leg: float
    confidence: float
    ts: float


# ---------------------------------------------------------------------------
# Text Processing for Event Matching
# ---------------------------------------------------------------------------

def normalize_event_text(text: str) -> str:
    """Normalize contract text for fuzzy matching."""
    text = text.lower().strip()
    # Remove common prediction market phrasing
    for phrase in ["will the ", "will ", "is the ", "is ", "does the ",
                   "does ", "do ", "by ", "before ", "on or before "]:
        if text.startswith(phrase):
            text = text[len(phrase):]
            break
    # Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()
    # Remove trailing question mark
    text = text.rstrip("?")
    return text


def extract_entities(text: str) -> dict:
    """Extract structured fields from contract text."""
    entities = {
        "numbers": re.findall(r"\b\d+(?:\.\d+)?%?\b", text),
        "dates": re.findall(
            r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+\d{1,2}(?:,?\s+\d{4})?\b",
            text.lower(),
        ),
        "thresholds": [],
        "direction": None,
    }

    # Detect threshold direction
    if any(w in text.lower() for w in ["above", "over", "more than", "exceed", "higher"]):
        entities["direction"] = "above"
    elif any(w in text.lower() for w in ["below", "under", "less than", "lower"]):
        entities["direction"] = "below"

    # Extract thresholds (numbers near direction words)
    for num in entities["numbers"]:
        entities["thresholds"].append(num)

    return entities


def compute_similarity(text_a: str, text_b: str) -> float:
    """
    Compute semantic similarity between two contract texts.
    Uses SequenceMatcher as baseline; production uses LLM verification.
    """
    norm_a = normalize_event_text(text_a)
    norm_b = normalize_event_text(text_b)

    # Sequence similarity
    seq_sim = SequenceMatcher(None, norm_a, norm_b).ratio()

    # Entity overlap bonus
    ent_a = extract_entities(text_a)
    ent_b = extract_entities(text_b)

    # Numbers match → strong signal
    nums_a = set(ent_a["numbers"])
    nums_b = set(ent_b["numbers"])
    if nums_a and nums_b:
        num_overlap = len(nums_a & nums_b) / max(len(nums_a | nums_b), 1)
        seq_sim = 0.6 * seq_sim + 0.4 * num_overlap

    # Direction match → bonus
    if ent_a["direction"] and ent_b["direction"]:
        if ent_a["direction"] == ent_b["direction"]:
            seq_sim = min(1.0, seq_sim + 0.05)
        else:
            seq_sim = max(0.0, seq_sim - 0.20)

    return seq_sim


def generate_pair_id(contract_a: ContractInfo,
                     contract_b: ContractInfo) -> str:
    """Generate stable pair ID from two contracts."""
    raw = f"{contract_a.market_id}:{contract_b.market_id}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Resolution Rule Comparison
# ---------------------------------------------------------------------------

@dataclass
class RuleComparison:
    """Result of comparing resolution rules between two contracts."""
    same_source: bool
    same_threshold: bool
    same_direction: bool
    same_timeframe: bool
    compatibility_score: float  # 0-1
    notes: str = ""


def compare_resolution_rules(contract_a: ContractInfo,
                              contract_b: ContractInfo) -> RuleComparison:
    """
    Compare resolution rules between two contracts.
    Detects semantic non-fungibility (different rules that look the same).
    """
    ent_a = extract_entities(contract_a.resolution_rules or contract_a.question)
    ent_b = extract_entities(contract_b.resolution_rules or contract_b.question)

    same_source = False
    if contract_a.resolution_source and contract_b.resolution_source:
        same_source = (
            normalize_event_text(contract_a.resolution_source)
            == normalize_event_text(contract_b.resolution_source)
        )

    same_threshold = bool(
        set(ent_a.get("thresholds", [])) & set(ent_b.get("thresholds", []))
    )

    same_direction = (ent_a.get("direction") == ent_b.get("direction"))

    # Timeframe comparison (rough)
    same_timeframe = bool(set(ent_a.get("dates", [])) & set(ent_b.get("dates", [])))

    # Compatibility score
    score = 0.0
    weights = [("source", same_source, 0.35),
               ("threshold", same_threshold, 0.30),
               ("direction", same_direction, 0.20),
               ("timeframe", same_timeframe, 0.15)]

    notes_parts = []
    for name, matches, weight in weights:
        if matches:
            score += weight
        else:
            notes_parts.append(f"{name}_mismatch")

    return RuleComparison(
        same_source=same_source,
        same_threshold=same_threshold,
        same_direction=same_direction,
        same_timeframe=same_timeframe,
        compatibility_score=score,
        notes="; ".join(notes_parts) if notes_parts else "all_match",
    )


# ---------------------------------------------------------------------------
# Semantic Alignment Engine
# ---------------------------------------------------------------------------

class SemanticAlignmentEngine:
    """
    Detects and manages cross-platform aligned event contracts.

    Workflow:
        1. Feed contracts from both venues
        2. Engine finds fuzzy text matches
        3. Compares resolution rules (detects false parity)
        4. Tracks price divergence over time
        5. Generates SemanticArbSignal when exploitable

    Usage:
        engine = SemanticAlignmentEngine()
        engine.add_contracts(poly_contracts, kalshi_contracts)
        pairs = engine.find_aligned_pairs()
        signals = engine.evaluate_divergences()
    """

    def __init__(self, config: Optional[AlignmentConfig] = None):
        self.config = config or AlignmentConfig()
        self._poly_contracts: dict[str, ContractInfo] = {}
        self._kalshi_contracts: dict[str, ContractInfo] = {}
        self._aligned_pairs: dict[str, AlignedPair] = {}
        self._pending_signals: list[SemanticArbSignal] = []
        self._false_parity_log: list[dict] = []

    def add_poly_contract(self, contract: ContractInfo) -> None:
        self._poly_contracts[contract.market_id] = contract

    def add_kalshi_contract(self, contract: ContractInfo) -> None:
        self._kalshi_contracts[contract.market_id] = contract

    def add_contracts(self, poly_list: list[ContractInfo],
                      kalshi_list: list[ContractInfo]) -> None:
        for c in poly_list:
            self.add_poly_contract(c)
        for c in kalshi_list:
            self.add_kalshi_contract(c)

    def find_aligned_pairs(self) -> list[AlignedPair]:
        """
        Find pairs of contracts across venues that appear to be
        about the same event. Uses text similarity + entity matching.
        """
        new_pairs = []

        for poly_id, poly in self._poly_contracts.items():
            for kalshi_id, kalshi in self._kalshi_contracts.items():
                pair_id = generate_pair_id(poly, kalshi)
                if pair_id in self._aligned_pairs:
                    continue

                similarity = compute_similarity(poly.question, kalshi.question)
                if similarity < self.config.min_similarity:
                    continue

                # Check resolution rule compatibility
                rule_cmp = compare_resolution_rules(poly, kalshi)
                if rule_cmp.compatibility_score < 0.5:
                    # Log as false parity
                    self._false_parity_log.append({
                        "pair_id": pair_id,
                        "poly_question": poly.question,
                        "kalshi_question": kalshi.question,
                        "similarity": similarity,
                        "rule_notes": rule_cmp.notes,
                        "ts": time.time(),
                    })
                    continue

                pair = AlignedPair(
                    pair_id=pair_id,
                    poly_contract=poly,
                    kalshi_contract=kalshi,
                    text_similarity=similarity,
                    status=AlignmentStatus.CANDIDATE,
                    created_at=time.time(),
                    last_updated=time.time(),
                )
                pair.update_divergence()

                self._aligned_pairs[pair_id] = pair
                new_pairs.append(pair)

                logger.info(
                    "ALIGNED_PAIR: %s sim=%.2f div=%.4f | PM: %s | K: %s",
                    pair_id, similarity, pair.divergence,
                    poly.question[:50], kalshi.question[:50],
                )

        return new_pairs

    def verify_pair(self, pair_id: str,
                    is_aligned: bool, notes: str = "") -> None:
        """Record LLM or manual verification of a pair."""
        pair = self._aligned_pairs.get(pair_id)
        if pair is None:
            return

        if is_aligned:
            pair.status = AlignmentStatus.VERIFIED
            pair.llm_verification = f"VERIFIED: {notes}"
        else:
            pair.status = AlignmentStatus.FALSE_PARITY
            pair.llm_verification = f"FALSE_PARITY: {notes}"
            self._false_parity_log.append({
                "pair_id": pair_id,
                "reason": notes,
                "ts": time.time(),
            })

    def evaluate_divergences(self) -> list[SemanticArbSignal]:
        """
        Check all aligned pairs for exploitable divergences.
        Generates signals for verified pairs with sufficient spread.
        """
        signals = []

        for pair_id, pair in self._aligned_pairs.items():
            # Only trade verified pairs (or candidates if LLM not required)
            if self.config.require_llm_verification:
                if pair.status != AlignmentStatus.VERIFIED:
                    continue
            else:
                if pair.status == AlignmentStatus.FALSE_PARITY:
                    continue

            # Update divergence
            pair.update_divergence()
            if pair.divergence < self.config.min_divergence:
                continue

            # Determine long/short legs
            poly_mid = pair.poly_mid
            kalshi_mid = pair.kalshi_mid

            if poly_mid < kalshi_mid:
                # Polymarket is cheaper → buy YES on Poly, buy NO on Kalshi
                long_venue = "polymarket"
                long_contract = pair.poly_contract
                long_side = "BUY_YES"
                long_price = poly_mid
                short_venue = "kalshi"
                short_contract = pair.kalshi_contract
                short_side = "BUY_NO"
                short_price = 1 - kalshi_mid
            else:
                long_venue = "kalshi"
                long_contract = pair.kalshi_contract
                long_side = "BUY_YES"
                long_price = kalshi_mid
                short_venue = "polymarket"
                short_contract = pair.poly_contract
                short_side = "BUY_NO"
                short_price = 1 - poly_mid

            # Compute edge after both venue fees
            gross_edge = pair.divergence
            gross_edge_bps = gross_edge * 10_000

            # Both legs have costs
            poly_fee = FeeSchedule.polymarket()
            kalshi_fee = FeeSchedule.kalshi()
            total_spread_cost = (pair.poly_contract.spread + pair.kalshi_contract.spread) / 2
            total_fee_cost = poly_fee.taker_fee * 0.5 + kalshi_fee.taker_fee * 0.5  # approximate

            net_bps = gross_edge_bps - (total_spread_cost + total_fee_cost) * 10_000
            if net_bps < self.config.min_net_edge_bps:
                continue

            # Position sizing (per leg)
            position_per_leg = min(10.0, gross_edge * 100)  # scale with edge

            signal = SemanticArbSignal(
                pair_id=pair_id,
                long_venue=long_venue,
                long_market_id=long_contract.market_id,
                long_token_id=long_contract.token_id,
                long_side=long_side,
                long_price=long_price,
                short_venue=short_venue,
                short_market_id=short_contract.market_id,
                short_token_id=short_contract.token_id,
                short_side=short_side,
                short_price=short_price,
                divergence=pair.divergence,
                gross_edge_bps=gross_edge_bps,
                net_edge_bps=net_bps,
                position_usd_per_leg=position_per_leg,
                confidence=min(1.0, pair.text_similarity * (net_bps / 100)),
                ts=time.time(),
            )

            signals.append(signal)
            logger.info(
                "SEMANTIC_ARB: %s long=%s@%.2f short=%s@%.2f div=%.4f net=%.0fbps",
                pair_id, long_venue, long_price,
                short_venue, short_price, pair.divergence, net_bps,
            )

        self._pending_signals.extend(signals)
        return signals

    def get_pending_signals(self) -> list[SemanticArbSignal]:
        """Drain and return pending signals."""
        signals = self._pending_signals.copy()
        self._pending_signals.clear()
        return signals

    def get_pair_stats(self) -> dict:
        """Get summary statistics of aligned pairs."""
        statuses = {}
        for pair in self._aligned_pairs.values():
            s = pair.status.value
            statuses[s] = statuses.get(s, 0) + 1

        divergences = [p.divergence for p in self._aligned_pairs.values()
                       if p.status in (AlignmentStatus.VERIFIED, AlignmentStatus.CANDIDATE)]

        return {
            "total_pairs": len(self._aligned_pairs),
            "status_counts": statuses,
            "false_parity_count": len(self._false_parity_log),
            "avg_divergence": sum(divergences) / len(divergences) if divergences else 0.0,
            "max_divergence": max(divergences) if divergences else 0.0,
            "poly_contracts": len(self._poly_contracts),
            "kalshi_contracts": len(self._kalshi_contracts),
        }
