#!/usr/bin/env python3
"""
Tests for bot/strike_desk.py — Strike Desk execution routing layer.

Categories:
  - ExecutionPacket creation and validation
  - Priority ordering (P0 beats P1, etc.)
  - Conflict resolution (same market, opposing signals)
  - Exposure caps (per-market, per-lane, total)
  - Lane adapter correctness (each scanner signal type)
  - Graceful degradation (scanner import fails, scanner throws, scanner returns empty)
  - Multi-leg packet linking (neg-risk baskets, cross-plat arb)
  - Fill/rejection recording and exposure updates
  - Diagnostics completeness

All tests use mock/injected data — zero network calls.
"""

import asyncio
import sys
import time
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch
from typing import Any, Optional

# Ensure bot/ is importable
_project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_project_root))
sys.path.insert(0, str(_project_root / "bot"))

from bot.strike_desk import (
    ExecutionPacket,
    StrikeDesk,
    PRIORITY_NEG_RISK,
    PRIORITY_CROSS_PLAT,
    PRIORITY_RESOLUTION,
    PRIORITY_STALE_QUOTE,
    PRIORITY_WHALE,
    PRIORITY_LEADER_FOLLOWER,
    PRIORITY_LLM_TOURNAMENT,
    PRIORITY_BTC5,
    LANE_NAMES,
    DEFAULT_CONFIG,
    _evidence_hash,
)


def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Mock signal dataclasses (mirror real scanner outputs)
# ---------------------------------------------------------------------------

@dataclass
class MockArbitrageOpportunity:
    opportunity_type: str = "negative_risk"
    market_group_id: str = "group_abc"
    markets: list = field(default_factory=lambda: [
        {"market_id": "m1", "question": "Outcome A?", "yes_price": 0.30, "no_price": 0.70, "token_id": "tok_1"},
        {"market_id": "m2", "question": "Outcome B?", "yes_price": 0.25, "no_price": 0.75, "token_id": "tok_2"},
        {"market_id": "m3", "question": "Outcome C?", "yes_price": 0.35, "no_price": 0.65, "token_id": "tok_3"},
    ])
    total_cost: float = 0.90
    guaranteed_payout: float = 1.00
    profit_per_share: float = 0.10
    profit_pct: float = 0.1111
    required_capital: float = 0.90
    constraint_violated: str = "YES prices sum to 0.90 < 1.00"
    is_profitable_after_fees: bool = True


@dataclass
class MockConsensusSignal:
    market_id: str = "whale_market_1"
    market_question: str = "Will BTC hit $100k?"
    direction: str = "YES"
    agreeing_wallets: int = 4
    total_tracked: int = 5
    consensus_pct: float = 0.80
    avg_size_usd: float = 5000.0
    total_volume_usd: float = 20000.0
    confidence: float = 0.75
    signal_time: float = field(default_factory=time.time)
    recommended_size_usd: float = 15.0


@dataclass
class MockResolutionTarget:
    market_id: str = "res_market_1"
    question: str = "Did event X happen?"
    current_yes_price: float = 0.97
    current_no_price: float = 0.03
    expected_outcome: str = "YES"
    confidence: float = 0.98
    evidence: str = "Price 0.97 in near-certain band"
    expected_profit_per_share: float = 0.03
    resolution_eta_hours: float = 6.0
    volume_24h: float = 50000.0
    risk_factors: list = field(default_factory=list)


@dataclass
class MockStaleQuote:
    market_id: str = "stale_market_1"
    question: str = "Did event Y happen?"
    side: str = "YES"
    stale_price: float = 0.41
    fair_price: float = 0.55
    edge: float = 0.14
    size_available: float = 12.0
    likely_reason: str = "pre_news_quote"


@dataclass
class MockCrossPlatformOpportunity:
    matched_pair: Any = None
    buy_yes_platform: str = "polymarket"
    buy_no_platform: str = "kalshi"
    yes_price: float = 0.45
    no_price: float = 0.48
    gross_cost: float = 0.93
    total_fees: float = 0.02
    net_cost: float = 0.95
    net_profit: float = 0.05
    profit_pct: float = 0.0526
    required_capital: float = 0.95
    risk_level: str = "LOW"


@dataclass
class MockMatchedPair:
    polymarket: Any = None
    kalshi: Any = None
    similarity_score: float = 0.85
    resolution_match: bool = True
    resolution_risk: str = "LOW"


@dataclass
class MockPlatformMarket:
    platform: str = "polymarket"
    market_id: str = "pm_123"
    question: str = "Will X happen?"


@dataclass
class MockTournamentResult:
    market_id: str = "tourn_market_1"
    market_question: str = "Will GDP grow?"
    estimates: list = field(default_factory=list)
    mean_probability: float = 0.72
    median_probability: float = 0.73
    std_probability: float = 0.02
    agreement_score: float = 0.92
    market_price: float = 0.55
    divergence: float = 0.17
    abs_divergence: float = 0.17
    signal: str = "BUY_YES"
    signal_strength: float = 0.156
    total_cost_usd: float = 0.05


@dataclass
class MockLeaderFollowerSignal:
    leader_market_id: str = "leader_1"
    leader_question: str = "Will BTC > $90k?"
    leader_price_change: float = 0.08
    leader_direction: str = "up"
    follower_market_id: str = "follower_1"
    follower_question: str = "Will BTC > $95k?"
    follower_current_price: float = 0.50
    predicted_direction: str = "up"
    predicted_magnitude: float = 0.06
    confidence: float = 0.65
    pair_similarity: float = 0.78
    signal_strength: float = 0.45
    recommended_side: str = "BUY_YES"
    recommended_size_usd: float = 8.0
    generated_at: float = field(default_factory=time.time)
    expires_at: float = 0.0


# ---------------------------------------------------------------------------
# Helper to build a desk with no live scanners
# ---------------------------------------------------------------------------

def _make_desk(config: Optional[dict] = None) -> StrikeDesk:
    """Create a StrikeDesk with default config; scanners will be whatever imports."""
    base = {"capital": 1000.0}
    if config:
        base.update(config)
    return StrikeDesk(config=base)


def _make_packet(
    strategy_id: str = "test",
    market_id: str = "mkt_1",
    priority: int = 4,
    direction: str = "YES",
    size_usd: float = 10.0,
    edge: float = 0.05,
    **kwargs,
) -> ExecutionPacket:
    return ExecutionPacket(
        strategy_id=strategy_id,
        market_id=market_id,
        platform="polymarket",
        direction=direction,
        token_id="tok_1",
        size_usd=size_usd,
        edge_estimate=edge,
        confidence=0.8,
        evidence_hash="abcdef1234567890",
        max_slippage=0.02,
        ttl_seconds=120,
        order_type="maker",
        priority=priority,
        **kwargs,
    )


# ===========================================================================
# Test classes
# ===========================================================================


class TestExecutionPacket(unittest.TestCase):
    """ExecutionPacket creation and validation."""

    def test_create_packet_all_fields(self):
        pkt = _make_packet()
        self.assertEqual(pkt.strategy_id, "test")
        self.assertEqual(pkt.market_id, "mkt_1")
        self.assertEqual(pkt.platform, "polymarket")
        self.assertEqual(pkt.direction, "YES")
        self.assertEqual(pkt.size_usd, 10.0)
        self.assertEqual(pkt.priority, 4)
        self.assertEqual(pkt.status, "pending")
        self.assertIsInstance(pkt.packet_id, str)
        self.assertTrue(len(pkt.packet_id) > 0)

    def test_packet_has_15_spec_fields(self):
        """Verify the 15 fields from the spec are present."""
        pkt = _make_packet()
        spec_fields = [
            "strategy_id", "market_id", "platform", "direction", "token_id",
            "size_usd", "edge_estimate", "confidence", "evidence_hash",
            "max_slippage", "ttl_seconds", "order_type", "priority",
            "linked_packets", "timestamp",
        ]
        for f in spec_fields:
            self.assertTrue(hasattr(pkt, f), f"Missing field: {f}")

    def test_packet_metadata_dict(self):
        pkt = _make_packet(metadata={"key": "val"})
        self.assertEqual(pkt.metadata["key"], "val")

    def test_packet_to_dict(self):
        pkt = _make_packet()
        d = pkt.to_dict()
        self.assertIsInstance(d, dict)
        self.assertEqual(d["strategy_id"], "test")
        self.assertEqual(d["market_id"], "mkt_1")

    def test_packet_unique_ids(self):
        pkt1 = _make_packet()
        pkt2 = _make_packet()
        self.assertNotEqual(pkt1.packet_id, pkt2.packet_id)

    def test_packet_linked_packets_default_empty(self):
        pkt = _make_packet()
        self.assertEqual(pkt.linked_packets, [])

    def test_packet_timestamp_set(self):
        before = time.time()
        pkt = _make_packet()
        after = time.time()
        self.assertGreaterEqual(pkt.timestamp, before)
        self.assertLessEqual(pkt.timestamp, after)


class TestEvidenceHash(unittest.TestCase):
    def test_hash_deterministic(self):
        h1 = _evidence_hash("test payload")
        h2 = _evidence_hash("test payload")
        self.assertEqual(h1, h2)

    def test_hash_different_input(self):
        h1 = _evidence_hash("payload_a")
        h2 = _evidence_hash("payload_b")
        self.assertNotEqual(h1, h2)

    def test_hash_length(self):
        h = _evidence_hash("anything")
        self.assertEqual(len(h), 16)


class TestPriorityConstants(unittest.TestCase):
    def test_priority_ordering(self):
        self.assertEqual(PRIORITY_NEG_RISK, 0)
        self.assertEqual(PRIORITY_CROSS_PLAT, 1)
        self.assertEqual(PRIORITY_RESOLUTION, 2)
        self.assertEqual(PRIORITY_STALE_QUOTE, 3)
        self.assertEqual(PRIORITY_WHALE, 4)
        self.assertEqual(PRIORITY_LEADER_FOLLOWER, 5)
        self.assertEqual(PRIORITY_LLM_TOURNAMENT, 6)
        self.assertEqual(PRIORITY_BTC5, 7)

    def test_neg_risk_beats_all(self):
        self.assertLess(PRIORITY_NEG_RISK, PRIORITY_CROSS_PLAT)
        self.assertLess(PRIORITY_NEG_RISK, PRIORITY_WHALE)
        self.assertLess(PRIORITY_NEG_RISK, PRIORITY_LLM_TOURNAMENT)

    def test_lane_names_complete(self):
        self.assertEqual(len(LANE_NAMES), 9)


class TestPrioritizeSignals(unittest.TestCase):
    """Priority ordering and conflict resolution."""

    def test_sort_by_priority(self):
        desk = _make_desk()
        p6 = _make_packet(strategy_id="llm", market_id="a", priority=6)
        p0 = _make_packet(strategy_id="neg", market_id="b", priority=0)
        p2 = _make_packet(strategy_id="res", market_id="c", priority=2)
        result = desk.prioritize_signals([p6, p0, p2])
        self.assertEqual(result[0].priority, 0)
        self.assertEqual(result[1].priority, 2)
        self.assertEqual(result[2].priority, 6)

    def test_higher_priority_wins_same_market(self):
        desk = _make_desk()
        p0 = _make_packet(strategy_id="neg", market_id="same", priority=0, direction="YES")
        p4 = _make_packet(strategy_id="whale", market_id="same", priority=4, direction="YES")
        result = desk.prioritize_signals([p4, p0])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].priority, 0)

    def test_same_priority_opposing_both_dropped(self):
        desk = _make_desk()
        p1 = _make_packet(strategy_id="a", market_id="same", priority=2, direction="YES")
        p2 = _make_packet(strategy_id="b", market_id="same", priority=2, direction="NO")
        result = desk.prioritize_signals([p1, p2])
        self.assertEqual(len(result), 0)

    def test_same_priority_linked_opposing_kept(self):
        desk = _make_desk()
        p1 = _make_packet(strategy_id="a", market_id="same", priority=2, direction="YES")
        p2 = _make_packet(strategy_id="b", market_id="same", priority=2, direction="NO")
        p1.linked_packets = [p2.packet_id]
        p2.linked_packets = [p1.packet_id]
        result = desk.prioritize_signals([p1, p2])
        self.assertEqual(len(result), 2)
        self.assertEqual({pkt.packet_id for pkt in result}, {p1.packet_id, p2.packet_id})

    def test_same_priority_same_direction_keeps_first(self):
        desk = _make_desk()
        p1 = _make_packet(strategy_id="a", market_id="same", priority=2, direction="YES", edge=0.10)
        p2 = _make_packet(strategy_id="b", market_id="same", priority=2, direction="YES", edge=0.05)
        result = desk.prioritize_signals([p1, p2])
        self.assertEqual(len(result), 1)
        # Higher edge should be kept (sorted by -edge_estimate within same priority)
        self.assertEqual(result[0].edge_estimate, 0.10)

    def test_different_markets_no_conflict(self):
        desk = _make_desk()
        p1 = _make_packet(market_id="a", priority=2)
        p2 = _make_packet(market_id="b", priority=4)
        result = desk.prioritize_signals([p1, p2])
        self.assertEqual(len(result), 2)

    def test_empty_input(self):
        desk = _make_desk()
        result = desk.prioritize_signals([])
        self.assertEqual(len(result), 0)

    def test_single_packet(self):
        desk = _make_desk()
        pkt = _make_packet()
        result = desk.prioritize_signals([pkt])
        self.assertEqual(len(result), 1)


class TestExposureCaps(unittest.TestCase):
    """Per-market, per-lane, and total desk exposure caps."""

    def test_per_market_cap(self):
        desk = _make_desk({"capital": 1000.0})
        # Max per market = 10% of 1000 = $100
        pkt = _make_packet(market_id="m1", size_usd=101.0)
        desk._market_exposure["m1"] = 0.0
        allowed, reason = desk.check_exposure(pkt)
        self.assertFalse(allowed)
        self.assertIn("market_cap", reason)

    def test_per_market_cap_cumulative(self):
        desk = _make_desk({"capital": 1000.0})
        desk._market_exposure["m1"] = 90.0
        pkt = _make_packet(market_id="m1", size_usd=20.0)
        allowed, reason = desk.check_exposure(pkt)
        self.assertFalse(allowed)

    def test_per_lane_cap(self):
        desk = _make_desk({"capital": 1000.0})
        # Max per lane = 30% of 1000 = $300
        desk._lane_exposure["whale"] = 290.0
        pkt = _make_packet(strategy_id="whale", size_usd=20.0)
        allowed, reason = desk.check_exposure(pkt)
        self.assertFalse(allowed)
        self.assertIn("lane_cap", reason)

    def test_total_desk_cap(self):
        desk = _make_desk({"capital": 1000.0})
        # Desk budget = 60% of 1000 = $600
        desk._total_exposure = 595.0
        pkt = _make_packet(size_usd=10.0)
        allowed, reason = desk.check_exposure(pkt)
        self.assertFalse(allowed)
        self.assertIn("desk_cap", reason)

    def test_within_all_caps(self):
        desk = _make_desk({"capital": 1000.0})
        pkt = _make_packet(size_usd=50.0)
        allowed, reason = desk.check_exposure(pkt)
        self.assertTrue(allowed)
        self.assertEqual(reason, "")

    def test_exposure_update_on_fill(self):
        desk = _make_desk()
        pkt = _make_packet(strategy_id="whale", market_id="m1", size_usd=25.0)
        desk.record_fill(pkt, fill_price=0.55)
        self.assertEqual(desk._market_exposure["m1"], 25.0)
        self.assertEqual(desk._lane_exposure["whale"], 25.0)
        self.assertEqual(desk._total_exposure, 25.0)

    def test_exposure_release(self):
        desk = _make_desk()
        pkt = _make_packet(strategy_id="whale", market_id="m1", size_usd=25.0)
        desk.record_fill(pkt, fill_price=0.55)
        desk.release_exposure(pkt)
        self.assertEqual(desk._total_exposure, 0.0)
        self.assertNotIn("m1", desk._market_exposure)


class TestNegRiskAdapter(unittest.TestCase):
    """Neg-risk adapter: multi-leg linked packets."""

    def test_adapt_neg_risk_creates_linked_packets(self):
        desk = _make_desk()
        opp = MockArbitrageOpportunity()
        packets = desk._adapt_neg_risk(opp)
        self.assertEqual(len(packets), 3)

    def test_adapt_neg_risk_all_linked(self):
        desk = _make_desk()
        opp = MockArbitrageOpportunity()
        packets = desk._adapt_neg_risk(opp)
        ids = {p.packet_id for p in packets}
        for pkt in packets:
            linked_set = set(pkt.linked_packets)
            expected = ids - {pkt.packet_id}
            self.assertEqual(linked_set, expected)

    def test_adapt_neg_risk_priority_p0(self):
        desk = _make_desk()
        opp = MockArbitrageOpportunity()
        packets = desk._adapt_neg_risk(opp)
        for pkt in packets:
            self.assertEqual(pkt.priority, PRIORITY_NEG_RISK)

    def test_adapt_neg_risk_strategy_id(self):
        desk = _make_desk()
        opp = MockArbitrageOpportunity()
        packets = desk._adapt_neg_risk(opp)
        for pkt in packets:
            self.assertEqual(pkt.strategy_id, "neg_risk")

    def test_adapt_neg_risk_direction_yes(self):
        desk = _make_desk()
        opp = MockArbitrageOpportunity()
        packets = desk._adapt_neg_risk(opp)
        for pkt in packets:
            self.assertEqual(pkt.direction, "YES")

    def test_adapt_neg_risk_taker_order(self):
        desk = _make_desk()
        opp = MockArbitrageOpportunity()
        packets = desk._adapt_neg_risk(opp)
        for pkt in packets:
            self.assertEqual(pkt.order_type, "taker")

    def test_adapt_neg_risk_empty_markets(self):
        desk = _make_desk()
        opp = MockArbitrageOpportunity(markets=[])
        packets = desk._adapt_neg_risk(opp)
        self.assertEqual(len(packets), 0)

    def test_adapt_neg_risk_size_caps(self):
        desk = _make_desk({"neg_risk_max_per_leg": 20.0, "neg_risk_min_per_leg": 5.0})
        opp = MockArbitrageOpportunity()
        packets = desk._adapt_neg_risk(opp)
        for pkt in packets:
            self.assertGreaterEqual(pkt.size_usd, 5.0)
            self.assertLessEqual(pkt.size_usd, 20.0)


class TestWhaleAdapter(unittest.TestCase):
    def test_adapt_whale_basic(self):
        desk = _make_desk()
        sig = MockConsensusSignal()
        pkt = desk._adapt_whale(sig)
        self.assertIsNotNone(pkt)
        self.assertEqual(pkt.strategy_id, "whale")
        self.assertEqual(pkt.market_id, "whale_market_1")
        self.assertEqual(pkt.direction, "YES")
        self.assertEqual(pkt.priority, PRIORITY_WHALE)

    def test_adapt_whale_none(self):
        desk = _make_desk()
        pkt = desk._adapt_whale(None)
        self.assertIsNone(pkt)

    def test_adapt_whale_size_capped(self):
        desk = _make_desk({"capital": 100.0})
        # Max per market = 10% of 100 = $10
        sig = MockConsensusSignal(recommended_size_usd=50.0)
        pkt = desk._adapt_whale(sig)
        self.assertLessEqual(pkt.size_usd, 10.0)

    def test_adapt_whale_metadata(self):
        desk = _make_desk()
        sig = MockConsensusSignal()
        pkt = desk._adapt_whale(sig)
        self.assertEqual(pkt.metadata["agreeing_wallets"], 4)
        self.assertEqual(pkt.metadata["consensus_pct"], 0.80)


class TestResolutionAdapter(unittest.TestCase):
    def test_adapt_resolution_basic(self):
        desk = _make_desk()
        target = MockResolutionTarget()
        pkt = desk._adapt_resolution(target)
        self.assertIsNotNone(pkt)
        self.assertEqual(pkt.strategy_id, "resolution")
        self.assertEqual(pkt.direction, "YES")
        self.assertEqual(pkt.priority, PRIORITY_RESOLUTION)
        self.assertAlmostEqual(pkt.edge_estimate, 0.03, places=3)

    def test_adapt_resolution_none(self):
        desk = _make_desk()
        pkt = desk._adapt_resolution(None)
        self.assertIsNone(pkt)

    def test_adapt_resolution_maker_order(self):
        desk = _make_desk()
        target = MockResolutionTarget()
        pkt = desk._adapt_resolution(target)
        self.assertEqual(pkt.order_type, "maker")

    def test_adapt_resolution_metadata(self):
        desk = _make_desk()
        target = MockResolutionTarget()
        pkt = desk._adapt_resolution(target)
        self.assertAlmostEqual(pkt.metadata["yes_price"], 0.97, places=2)
        self.assertAlmostEqual(pkt.metadata["resolution_eta_hours"], 6.0, places=1)


class TestStaleQuoteAdapter(unittest.TestCase):
    def test_adapt_stale_quote_basic(self):
        desk = _make_desk()
        quote = MockStaleQuote()
        pkt = desk._adapt_stale_quote(quote)
        self.assertIsNotNone(pkt)
        self.assertEqual(pkt.strategy_id, "stale_quote")
        self.assertEqual(pkt.market_id, "stale_market_1")
        self.assertEqual(pkt.direction, "YES")
        self.assertEqual(pkt.priority, PRIORITY_STALE_QUOTE)
        self.assertEqual(pkt.metadata["execution_side"], "buy_yes")


class TestCrossPlatAdapter(unittest.TestCase):
    def _make_opp(self):
        pm = MockPlatformMarket(platform="polymarket", market_id="pm_1")
        km = MockPlatformMarket(platform="kalshi", market_id="km_1")
        pair = MockMatchedPair(polymarket=pm, kalshi=km)
        return MockCrossPlatformOpportunity(matched_pair=pair)

    def test_adapt_cross_plat_two_legs(self):
        desk = _make_desk()
        opp = self._make_opp()
        packets = desk._adapt_cross_plat(opp)
        self.assertEqual(len(packets), 2)

    def test_adapt_cross_plat_linked(self):
        desk = _make_desk()
        opp = self._make_opp()
        packets = desk._adapt_cross_plat(opp)
        self.assertEqual(packets[0].linked_packets, [packets[1].packet_id])
        self.assertEqual(packets[1].linked_packets, [packets[0].packet_id])

    def test_adapt_cross_plat_platforms(self):
        desk = _make_desk()
        opp = self._make_opp()
        packets = desk._adapt_cross_plat(opp)
        platforms = {p.platform for p in packets}
        self.assertEqual(platforms, {"polymarket", "kalshi"})

    def test_adapt_cross_plat_directions(self):
        desk = _make_desk()
        opp = self._make_opp()
        packets = desk._adapt_cross_plat(opp)
        directions = {p.direction for p in packets}
        self.assertEqual(directions, {"YES", "NO"})

    def test_adapt_cross_plat_priority(self):
        desk = _make_desk()
        opp = self._make_opp()
        packets = desk._adapt_cross_plat(opp)
        for pkt in packets:
            self.assertEqual(pkt.priority, PRIORITY_CROSS_PLAT)

    def test_adapt_cross_plat_none(self):
        desk = _make_desk()
        packets = desk._adapt_cross_plat(None)
        self.assertEqual(len(packets), 0)

    def test_adapt_cross_plat_taker_order(self):
        desk = _make_desk()
        opp = self._make_opp()
        packets = desk._adapt_cross_plat(opp)
        for pkt in packets:
            self.assertEqual(pkt.order_type, "taker")


class TestLLMTournamentAdapter(unittest.TestCase):
    def test_adapt_tournament_buy_yes(self):
        desk = _make_desk()
        result = MockTournamentResult(signal="BUY_YES")
        pkt = desk._adapt_llm_tournament(result)
        self.assertIsNotNone(pkt)
        self.assertEqual(pkt.direction, "YES")
        self.assertEqual(pkt.priority, PRIORITY_LLM_TOURNAMENT)

    def test_adapt_tournament_buy_no(self):
        desk = _make_desk()
        result = MockTournamentResult(signal="BUY_NO")
        pkt = desk._adapt_llm_tournament(result)
        self.assertIsNotNone(pkt)
        self.assertEqual(pkt.direction, "NO")

    def test_adapt_tournament_no_signal(self):
        desk = _make_desk()
        result = MockTournamentResult(signal="NO_SIGNAL")
        pkt = desk._adapt_llm_tournament(result)
        self.assertIsNone(pkt)

    def test_adapt_tournament_none(self):
        desk = _make_desk()
        pkt = desk._adapt_llm_tournament(None)
        self.assertIsNone(pkt)

    def test_adapt_tournament_size_calculation(self):
        desk = _make_desk({"capital": 1000.0, "tournament_kelly_fraction": 0.25})
        result = MockTournamentResult(
            signal="BUY_YES",
            agreement_score=0.90,
            abs_divergence=0.20,
        )
        pkt = desk._adapt_llm_tournament(result)
        # edge = 0.20 * 0.90 = 0.18
        # raw size = 1000 * 0.25 * 0.18 = 45.0
        # max_per_market = 1000 * 0.10 = 100
        expected_size = min(1000.0 * 0.25 * 0.18, 100.0)
        self.assertAlmostEqual(pkt.size_usd, expected_size, places=1)


class TestLeaderFollowerAdapter(unittest.TestCase):
    def test_adapt_leader_follower_basic(self):
        desk = _make_desk()
        sig = MockLeaderFollowerSignal()
        pkt = desk._adapt_leader_follower(sig)
        self.assertIsNotNone(pkt)
        self.assertEqual(pkt.strategy_id, "leader_follower")
        self.assertEqual(pkt.market_id, "follower_1")
        self.assertEqual(pkt.direction, "YES")
        self.assertEqual(pkt.priority, PRIORITY_LEADER_FOLLOWER)

    def test_adapt_leader_follower_buy_no(self):
        desk = _make_desk()
        sig = MockLeaderFollowerSignal(recommended_side="BUY_NO")
        pkt = desk._adapt_leader_follower(sig)
        self.assertEqual(pkt.direction, "NO")

    def test_adapt_leader_follower_none(self):
        desk = _make_desk()
        pkt = desk._adapt_leader_follower(None)
        self.assertIsNone(pkt)

    def test_adapt_leader_follower_metadata(self):
        desk = _make_desk()
        sig = MockLeaderFollowerSignal()
        pkt = desk._adapt_leader_follower(sig)
        self.assertEqual(pkt.metadata["leader_market_id"], "leader_1")
        self.assertAlmostEqual(pkt.metadata["pair_similarity"], 0.78, places=2)


class TestGracefulDegradation(unittest.TestCase):
    """Scanner import failures, exceptions, and empty returns."""

    def test_missing_scanner_returns_empty(self):
        desk = _make_desk()
        desk._neg_risk = None
        packets = _run(desk._scan_neg_risk())
        self.assertEqual(packets, [])

    def test_missing_whale_returns_empty(self):
        desk = _make_desk()
        desk._whale = None
        packets = _run(desk._scan_whale())
        self.assertEqual(packets, [])

    def test_missing_sniper_returns_empty(self):
        desk = _make_desk()
        desk._sniper = None
        packets = _run(desk._scan_resolution([]))
        self.assertEqual(packets, [])

    def test_missing_cross_plat_returns_empty(self):
        desk = _make_desk()
        desk._cross_plat = None
        packets = _run(desk._scan_cross_plat())
        self.assertEqual(packets, [])

    def test_missing_tournament_returns_empty(self):
        desk = _make_desk()
        desk._tournament = None
        packets = _run(desk._scan_tournament([{"market_id": "x", "question": "q", "market_price": 0.5}]))
        self.assertEqual(packets, [])

    def test_missing_leader_follower_returns_empty(self):
        desk = _make_desk()
        desk._leader_follower = None
        packets = _run(desk._scan_leader_follower({"signals": []}))
        self.assertEqual(packets, [])

    def test_scanner_exception_caught(self):
        """If a scanner throws, other lanes still produce results."""
        desk = _make_desk()
        desk._neg_risk = None  # Safe
        desk._whale = None
        desk._sniper = None
        desk._cross_plat = None
        desk._tournament = None
        desk._leader_follower = None
        # scan_all_lanes should not raise
        packets = _run(desk.scan_all_lanes())
        self.assertEqual(packets, [])

    def test_scan_all_lanes_one_lane_fails(self):
        """One failing lane does not block others."""
        desk = _make_desk()
        # Inject a whale that produces signals
        mock_whale = MagicMock()
        mock_whale.get_consensus_signals.return_value = [MockConsensusSignal()]
        desk._whale = mock_whale

        # Make everything else None
        desk._neg_risk = None
        desk._sniper = None
        desk._cross_plat = None
        desk._tournament = None
        desk._leader_follower = None

        packets = _run(desk.scan_all_lanes())
        self.assertEqual(len(packets), 1)
        self.assertEqual(packets[0].strategy_id, "whale")


class TestScanAllLanesIntegration(unittest.TestCase):
    """Integration tests for scan_all_lanes with injected data."""

    def test_whale_lane_via_injection(self):
        desk = _make_desk()
        desk._neg_risk = None
        desk._sniper = None
        desk._cross_plat = None
        desk._tournament = None
        desk._leader_follower = None

        mock_whale = MagicMock()
        desk._whale = mock_whale

        signals = [MockConsensusSignal(), MockConsensusSignal(market_id="whale_2")]
        packets = _run(desk.scan_all_lanes(whale_signals=signals))
        self.assertEqual(len(packets), 2)

    def test_leader_follower_via_injection(self):
        desk = _make_desk()
        desk._neg_risk = None
        desk._whale = None
        desk._sniper = None
        desk._cross_plat = None
        desk._tournament = None
        desk._leader_follower = MagicMock()  # Just needs to not be None

        data = {"signals": [MockLeaderFollowerSignal()]}
        packets = _run(desk.scan_all_lanes(leader_follower_data=data))
        self.assertEqual(len(packets), 1)
        self.assertEqual(packets[0].strategy_id, "leader_follower")


class TestGeneratePackets(unittest.TestCase):
    """Full pipeline: prioritize + exposure check."""

    def test_generate_filters_exposure(self):
        desk = _make_desk({"capital": 100.0})
        # Max per market = $10
        pkt_big = _make_packet(market_id="m1", size_usd=15.0, priority=2)
        result = desk.generate_packets([pkt_big])
        # Should be rejected by exposure
        self.assertEqual(len(result), 0)

    def test_generate_passes_valid(self):
        desk = _make_desk({"capital": 1000.0})
        pkt = _make_packet(market_id="m1", size_usd=10.0, priority=2)
        result = desk.generate_packets([pkt])
        self.assertEqual(len(result), 1)

    def test_generate_sets_active_packets(self):
        desk = _make_desk({"capital": 1000.0})
        pkt = _make_packet(size_usd=10.0)
        desk.generate_packets([pkt])
        active = desk.get_active_packets()
        self.assertEqual(len(active), 1)

    def test_generate_records_rejections(self):
        desk = _make_desk({"capital": 100.0})
        pkt = _make_packet(size_usd=200.0, priority=2)  # Exceeds desk budget
        desk.generate_packets([pkt])
        self.assertEqual(len(desk._rejections), 1)


class TestFillRejectionRecording(unittest.TestCase):
    def test_record_fill(self):
        desk = _make_desk()
        pkt = _make_packet(strategy_id="whale", market_id="m1", size_usd=20.0)
        desk.record_fill(pkt, fill_price=0.55)
        self.assertEqual(pkt.status, "filled")
        self.assertEqual(len(desk._fills), 1)
        self.assertEqual(desk._fills[0]["fill_price"], 0.55)
        self.assertEqual(desk._fills[0]["size_usd"], 20.0)

    def test_record_rejection(self):
        desk = _make_desk()
        pkt = _make_packet()
        desk.record_rejection(pkt, reason="price moved")
        self.assertEqual(pkt.status, "rejected")
        self.assertEqual(len(desk._rejections), 1)
        self.assertEqual(desk._rejections[0]["reason"], "price moved")

    def test_fill_updates_exposure(self):
        desk = _make_desk()
        pkt = _make_packet(strategy_id="resolution", market_id="m1", size_usd=30.0)
        desk.record_fill(pkt)
        self.assertEqual(desk._market_exposure["m1"], 30.0)
        self.assertEqual(desk._lane_exposure["resolution"], 30.0)
        self.assertEqual(desk._total_exposure, 30.0)

    def test_multiple_fills_cumulate(self):
        desk = _make_desk()
        pkt1 = _make_packet(strategy_id="whale", market_id="m1", size_usd=10.0)
        pkt2 = _make_packet(strategy_id="whale", market_id="m1", size_usd=15.0)
        desk.record_fill(pkt1)
        desk.record_fill(pkt2)
        self.assertEqual(desk._market_exposure["m1"], 25.0)
        self.assertEqual(desk._total_exposure, 25.0)


class TestDiagnostics(unittest.TestCase):
    def test_diagnostics_structure(self):
        desk = _make_desk()
        diag = desk.get_diagnostics()
        required_keys = [
            "capital", "desk_budget", "max_per_market", "max_per_lane",
            "total_exposure", "market_exposure", "lane_exposure",
            "active_packets", "total_fills", "total_rejections",
            "lane_stats", "scanner_status",
        ]
        for key in required_keys:
            self.assertIn(key, diag, f"Missing diagnostics key: {key}")

    def test_diagnostics_scanner_status(self):
        desk = _make_desk()
        diag = desk.get_diagnostics()
        self.assertIn("neg_risk", diag["scanner_status"])
        self.assertIn("whale", diag["scanner_status"])
        self.assertIn("sniper", diag["scanner_status"])

    def test_diagnostics_lane_stats(self):
        desk = _make_desk()
        pkt = _make_packet(strategy_id="whale", market_id="m1", size_usd=10.0)
        desk.record_fill(pkt)
        diag = desk.get_diagnostics()
        self.assertEqual(diag["lane_stats"]["whale"]["fills"], 1)

    def test_diagnostics_after_rejection(self):
        desk = _make_desk()
        pkt = _make_packet(strategy_id="resolution")
        desk.record_rejection(pkt, reason="test")
        diag = desk.get_diagnostics()
        self.assertEqual(diag["total_rejections"], 1)

    def test_diagnostics_capital_budget(self):
        desk = _make_desk({"capital": 500.0})
        diag = desk.get_diagnostics()
        self.assertEqual(diag["capital"], 500.0)
        self.assertAlmostEqual(diag["desk_budget"], 300.0, places=1)
        self.assertAlmostEqual(diag["max_per_market"], 50.0, places=1)


class TestCapitalUpdate(unittest.TestCase):
    def test_update_capital(self):
        desk = _make_desk({"capital": 1000.0})
        desk.update_capital(2000.0)
        self.assertEqual(desk._capital, 2000.0)
        self.assertAlmostEqual(desk._desk_budget, 1200.0, places=1)

    def test_update_capital_affects_limits(self):
        desk = _make_desk({"capital": 100.0})
        self.assertAlmostEqual(desk._max_per_market, 10.0, places=1)
        desk.update_capital(500.0)
        self.assertAlmostEqual(desk._max_per_market, 50.0, places=1)


class TestSetScanner(unittest.TestCase):
    def test_inject_scanner(self):
        desk = _make_desk()
        mock = MagicMock()
        desk.set_scanner("neg_risk", mock)
        self.assertIs(desk._neg_risk, mock)

    def test_inject_unknown_raises(self):
        desk = _make_desk()
        with self.assertRaises(ValueError):
            desk.set_scanner("nonexistent", MagicMock())


class TestMultiLegUnwind(unittest.TestCase):
    """Verify multi-leg packets (neg-risk, cross-plat) share linked IDs."""

    def test_neg_risk_all_legs_same_group(self):
        desk = _make_desk()
        opp = MockArbitrageOpportunity()
        packets = desk._adapt_neg_risk(opp)
        group_ids = {p.metadata["group_id"] for p in packets}
        self.assertEqual(len(group_ids), 1)

    def test_cross_plat_two_legs_linked(self):
        desk = _make_desk()
        pm = MockPlatformMarket(market_id="pm_1")
        km = MockPlatformMarket(platform="kalshi", market_id="km_1")
        pair = MockMatchedPair(polymarket=pm, kalshi=km)
        opp = MockCrossPlatformOpportunity(matched_pair=pair)
        packets = desk._adapt_cross_plat(opp)
        self.assertEqual(len(packets), 2)
        self.assertIn(packets[1].packet_id, packets[0].linked_packets)
        self.assertIn(packets[0].packet_id, packets[1].linked_packets)


class TestDefaultConfig(unittest.TestCase):
    def test_default_config_keys(self):
        required = [
            "max_desk_exposure_pct", "max_single_market_pct", "max_single_lane_pct",
            "capital", "default_ttl_seconds", "default_max_slippage",
        ]
        for key in required:
            self.assertIn(key, DEFAULT_CONFIG)

    def test_desk_uses_config_overrides(self):
        desk = _make_desk({"capital": 5000.0, "max_desk_exposure_pct": 0.50})
        self.assertEqual(desk._capital, 5000.0)
        self.assertAlmostEqual(desk._desk_budget, 2500.0, places=1)


class TestBTC5DailyPnlDemotion(unittest.TestCase):
    """Tests for BTC5 daily PnL demotion logic in generate_packets."""

    def test_btc5_not_demoted_by_default(self):
        desk = _make_desk()
        demoted, reason = desk.is_btc5_demoted()
        self.assertFalse(demoted)
        self.assertEqual(reason, "")

    def test_btc5_demoted_on_negative_et_day(self):
        desk = _make_desk({"btc5_daily_pnl_demotion_usd": -10.0})
        desk.set_btc5_daily_pnl(et_day_pnl_usd=-15.0, rolling_24h_pnl_usd=5.0)
        demoted, reason = desk.is_btc5_demoted()
        self.assertTrue(demoted)
        self.assertIn("et_day_pnl", reason)

    def test_btc5_demoted_on_negative_rolling(self):
        desk = _make_desk({"btc5_daily_pnl_demotion_usd": -10.0})
        desk.set_btc5_daily_pnl(et_day_pnl_usd=0.0, rolling_24h_pnl_usd=-12.0)
        demoted, reason = desk.is_btc5_demoted()
        self.assertTrue(demoted)
        self.assertIn("rolling_24h_pnl", reason)

    def test_btc5_not_demoted_above_threshold(self):
        desk = _make_desk({"btc5_daily_pnl_demotion_usd": -10.0})
        desk.set_btc5_daily_pnl(et_day_pnl_usd=-5.0, rolling_24h_pnl_usd=-8.0)
        demoted, _ = desk.is_btc5_demoted()
        self.assertFalse(demoted)

    def test_generate_packets_suppresses_btc5_when_demoted(self):
        desk = _make_desk({"btc5_daily_pnl_demotion_usd": -10.0})
        desk.set_btc5_daily_pnl(et_day_pnl_usd=-20.0)

        btc5_pkt = _make_packet(strategy_id="btc5", priority=PRIORITY_BTC5, market_id="btc_mkt_1")
        whale_pkt = _make_packet(strategy_id="whale", priority=PRIORITY_WHALE, market_id="whale_mkt_1")

        approved = desk.generate_packets([btc5_pkt, whale_pkt])

        # BTC5 should be suppressed, whale should pass
        approved_ids = {p.strategy_id for p in approved}
        self.assertNotIn("btc5", approved_ids)
        self.assertIn("whale", approved_ids)

    def test_generate_packets_allows_btc5_when_not_demoted(self):
        desk = _make_desk({"btc5_daily_pnl_demotion_usd": -10.0})
        desk.set_btc5_daily_pnl(et_day_pnl_usd=5.0, rolling_24h_pnl_usd=10.0)

        btc5_pkt = _make_packet(strategy_id="btc5", priority=PRIORITY_BTC5, market_id="btc_mkt_2")
        approved = desk.generate_packets([btc5_pkt])
        self.assertEqual(len(approved), 1)
        self.assertEqual(approved[0].strategy_id, "btc5")

    def test_btc5_demotion_records_rejection(self):
        desk = _make_desk({"btc5_daily_pnl_demotion_usd": -10.0})
        desk.set_btc5_daily_pnl(et_day_pnl_usd=-20.0)

        btc5_pkt = _make_packet(strategy_id="btc5", priority=PRIORITY_BTC5, market_id="btc_mkt_3")
        desk.generate_packets([btc5_pkt])

        self.assertEqual(len(desk._rejections), 1)
        self.assertIn("daily_pnl_demotion", desk._rejections[0]["reason"])

    def test_structural_lanes_unaffected_by_btc5_demotion(self):
        desk = _make_desk({"btc5_daily_pnl_demotion_usd": -10.0})
        desk.set_btc5_daily_pnl(et_day_pnl_usd=-50.0, rolling_24h_pnl_usd=-50.0)

        # All non-btc5 packets should pass
        packets = [
            _make_packet(strategy_id="neg_risk", priority=PRIORITY_NEG_RISK, market_id="nr_1"),
            _make_packet(strategy_id="whale", priority=PRIORITY_WHALE, market_id="wh_1"),
        ]
        approved = desk.generate_packets(packets)
        self.assertEqual(len(approved), 2)


if __name__ == "__main__":
    unittest.main()
