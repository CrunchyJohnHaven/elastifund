#!/usr/bin/env python3
"""
Strike Desk — Execution Routing Layer for JJ
=============================================
Wires six money-making scanners into the execution layer. Each scanner
produces a different signal type; the Strike Desk normalises them into
uniform ``ExecutionPacket`` objects, applies priority ordering, conflict
resolution, and exposure caps, then emits packets ready for
``jj_live.place_order()``.

Scanners (priority order):
  P0  NegativeRiskScanner   — guaranteed-profit baskets
  P1  CrossPlatformArbScanner — near-guaranteed cross-platform arb
  P2  ResolutionSniper       — known-outcome resolution sniping
  P3  ResolutionSniper (stale quotes)
  P4  WhaleTracker           — consensus copy-trade signals
  P5  SemanticLeaderFollower — statistical lead-lag signals
  P6  LLMTournament          — LLM consensus-divergence signals

Design:
  - All scanner imports are try/except guarded (graceful degradation)
  - Zero external dependencies beyond what is already in the repo
  - Sub-millisecond conflict resolution and exposure checks
  - Multi-leg packet linking for basket trades (neg-risk, cross-plat)

Author: JJ (autonomous)
Date: 2026-03-22
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

logger = logging.getLogger("JJ.strike_desk")

# ---------------------------------------------------------------------------
# Scanner imports — all guarded for graceful degradation
# ---------------------------------------------------------------------------

try:
    from bot.neg_risk_scanner import NegativeRiskScanner, ArbitrageOpportunity
except ImportError:
    try:
        from neg_risk_scanner import NegativeRiskScanner, ArbitrageOpportunity  # type: ignore
    except ImportError:
        NegativeRiskScanner = None  # type: ignore[misc, assignment]
        ArbitrageOpportunity = None  # type: ignore[misc, assignment]

try:
    from bot.whale_tracker import WhaleTracker, ConsensusSignal
except ImportError:
    try:
        from whale_tracker import WhaleTracker, ConsensusSignal  # type: ignore
    except ImportError:
        WhaleTracker = None  # type: ignore[misc, assignment]
        ConsensusSignal = None  # type: ignore[misc, assignment]

try:
    from bot.resolution_sniper import ResolutionSniper, ResolutionTarget, StaleQuote
except ImportError:
    try:
        from resolution_sniper import ResolutionSniper, ResolutionTarget, StaleQuote  # type: ignore
    except ImportError:
        ResolutionSniper = None  # type: ignore[misc, assignment]
        ResolutionTarget = None  # type: ignore[misc, assignment]
        StaleQuote = None  # type: ignore[misc, assignment]

try:
    from bot.cross_platform_arb_scanner import CrossPlatformArbScanner, CrossPlatformOpportunity
except ImportError:
    try:
        from cross_platform_arb_scanner import CrossPlatformArbScanner, CrossPlatformOpportunity  # type: ignore
    except ImportError:
        CrossPlatformArbScanner = None  # type: ignore[misc, assignment]
        CrossPlatformOpportunity = None  # type: ignore[misc, assignment]

try:
    from bot.llm_tournament import LLMTournament, TournamentResult
except ImportError:
    try:
        from llm_tournament import LLMTournament, TournamentResult  # type: ignore
    except ImportError:
        LLMTournament = None  # type: ignore[misc, assignment]
        TournamentResult = None  # type: ignore[misc, assignment]

try:
    from bot.semantic_leader_follower import SemanticLeaderFollower, LeaderFollowerSignal
except ImportError:
    try:
        from semantic_leader_follower import SemanticLeaderFollower, LeaderFollowerSignal  # type: ignore
    except ImportError:
        SemanticLeaderFollower = None  # type: ignore[misc, assignment]
        LeaderFollowerSignal = None  # type: ignore[misc, assignment]

# ---------------------------------------------------------------------------
# Priority constants
# ---------------------------------------------------------------------------

PRIORITY_NEG_RISK: int = 0
PRIORITY_CROSS_PLAT: int = 1
PRIORITY_RESOLUTION: int = 2
PRIORITY_STALE_QUOTE: int = 3
PRIORITY_WHALE: int = 4
PRIORITY_LEADER_FOLLOWER: int = 5
PRIORITY_LLM_TOURNAMENT: int = 6
PRIORITY_BTC5: int = 7

LANE_NAMES: dict[int, str] = {
    PRIORITY_NEG_RISK: "neg_risk",
    PRIORITY_CROSS_PLAT: "cross_plat",
    PRIORITY_RESOLUTION: "resolution",
    PRIORITY_STALE_QUOTE: "stale_quote",
    PRIORITY_WHALE: "whale",
    PRIORITY_LEADER_FOLLOWER: "leader_follower",
    PRIORITY_LLM_TOURNAMENT: "llm_tournament",
    PRIORITY_BTC5: "btc5",
}

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ExecutionPacket:
    """Normalised trade signal ready for execution."""

    strategy_id: str
    market_id: str
    platform: str          # "polymarket" or "kalshi"
    direction: str         # "YES" or "NO"
    token_id: str
    size_usd: float
    edge_estimate: float
    confidence: float
    evidence_hash: str
    max_slippage: float
    ttl_seconds: int
    order_type: str        # "maker" or "taker"
    priority: int          # P0-P7
    linked_packets: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)

    # Runtime tracking (set after creation)
    packet_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: str = "pending"  # "pending", "filled", "rejected", "expired"

    def to_dict(self) -> dict:
        """Serialise for logging / persistence."""
        d = asdict(self)
        return d


def _evidence_hash(payload: str) -> str:
    """SHA-256 hex digest of an evidence payload string."""
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Default config
# ---------------------------------------------------------------------------

DEFAULT_CONFIG: dict[str, Any] = {
    "max_desk_exposure_pct": 0.60,
    "max_single_market_pct": 0.10,
    "max_single_lane_pct": 0.30,
    "btc5_reserve_pct": 0.25,
    "cash_buffer_pct": 0.15,
    "capital": 1178.0,
    "default_ttl_seconds": 120,
    "default_max_slippage": 0.02,
    "default_order_type": "maker",
    "neg_risk_max_per_leg": 50.0,
    "neg_risk_min_per_leg": 5.0,
    "whale_kelly_fraction": 0.25,
    "leader_follower_kelly_fraction": 0.125,
    "tournament_kelly_fraction": 0.25,
    "resolution_default_size": 10.0,
}


# ---------------------------------------------------------------------------
# Strike Desk
# ---------------------------------------------------------------------------


class StrikeDesk:
    """Aggregates signals from all money-making scanners into a
    priority-ordered execution queue with exposure management."""

    def __init__(self, config: Optional[dict[str, Any]] = None) -> None:
        self._config: dict[str, Any] = {**DEFAULT_CONFIG, **(config or {})}
        self._capital: float = float(self._config["capital"])

        # Exposure tracking: {market_id: usd_amount}
        self._market_exposure: dict[str, float] = {}
        # Lane exposure: {lane_name: usd_amount}
        self._lane_exposure: dict[str, float] = {}
        # Total desk exposure
        self._total_exposure: float = 0.0

        # Fill / rejection history
        self._fills: list[dict] = []
        self._rejections: list[dict] = []

        # Active packets (current cycle)
        self._active_packets: list[ExecutionPacket] = []

        # Scanner instances (lazy-init, can be injected)
        self._neg_risk: Any = None
        self._whale: Any = None
        self._sniper: Any = None
        self._cross_plat: Any = None
        self._tournament: Any = None
        self._leader_follower: Any = None

        self._init_scanners()
        logger.info(
            "StrikeDesk initialised: capital=$%.2f desk_budget=$%.2f",
            self._capital,
            self._desk_budget,
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def _desk_budget(self) -> float:
        return self._capital * self._config["max_desk_exposure_pct"]

    @property
    def _max_per_market(self) -> float:
        return self._capital * self._config["max_single_market_pct"]

    @property
    def _max_per_lane(self) -> float:
        return self._capital * self._config["max_single_lane_pct"]

    # ------------------------------------------------------------------
    # Scanner initialisation
    # ------------------------------------------------------------------

    def _init_scanners(self) -> None:
        """Initialise available scanners. Missing scanners are left as None."""
        if NegativeRiskScanner is not None:
            try:
                self._neg_risk = NegativeRiskScanner()
            except Exception as exc:
                logger.warning("NegativeRiskScanner init failed: %s", exc)

        if WhaleTracker is not None:
            try:
                self._whale = WhaleTracker()
            except Exception as exc:
                logger.warning("WhaleTracker init failed: %s", exc)

        if ResolutionSniper is not None:
            try:
                self._sniper = ResolutionSniper()
            except Exception as exc:
                logger.warning("ResolutionSniper init failed: %s", exc)

        if CrossPlatformArbScanner is not None:
            try:
                self._cross_plat = CrossPlatformArbScanner()
            except Exception as exc:
                logger.warning("CrossPlatformArbScanner init failed: %s", exc)

        if LLMTournament is not None:
            try:
                self._tournament = LLMTournament()
            except Exception as exc:
                logger.warning("LLMTournament init failed: %s", exc)

        if SemanticLeaderFollower is not None:
            try:
                self._leader_follower = SemanticLeaderFollower()
            except Exception as exc:
                logger.warning("SemanticLeaderFollower init failed: %s", exc)

    # ------------------------------------------------------------------
    # Scanner injection (for testing)
    # ------------------------------------------------------------------

    def set_scanner(self, name: str, instance: Any) -> None:
        """Inject a scanner instance (primarily for testing)."""
        attr = f"_{name}"
        if hasattr(self, attr):
            setattr(self, attr, instance)
        else:
            raise ValueError(f"Unknown scanner name: {name!r}")

    # ------------------------------------------------------------------
    # scan_all_lanes — runs all scanners concurrently
    # ------------------------------------------------------------------

    async def scan_all_lanes(
        self,
        *,
        neg_risk_data: Any = None,
        whale_signals: Optional[list] = None,
        sniper_markets: Optional[list[dict]] = None,
        cross_plat_poly: Optional[list] = None,
        cross_plat_kalshi: Optional[list] = None,
        tournament_questions: Optional[list[dict]] = None,
        leader_follower_data: Optional[dict] = None,
    ) -> list[ExecutionPacket]:
        """Run all available scanners via asyncio.gather.

        Each scanner is wrapped so that a failure in one does not block
        the others.  Returns a flat list of ExecutionPackets from all
        lanes, unsorted.

        Keyword arguments allow injecting data for each lane (for tests
        or when live data is pre-fetched).
        """
        tasks = []

        async def _safe_scan(name: str, coro: Any) -> list[ExecutionPacket]:
            try:
                return await coro
            except Exception as exc:
                logger.error("Lane %s scan failed: %s", name, exc)
                return []

        # Neg-risk
        tasks.append(_safe_scan("neg_risk", self._scan_neg_risk(neg_risk_data)))
        # Whale
        tasks.append(_safe_scan("whale", self._scan_whale(whale_signals)))
        # Resolution sniper
        tasks.append(_safe_scan("resolution", self._scan_resolution(sniper_markets)))
        # Cross-platform arb
        tasks.append(_safe_scan("cross_plat", self._scan_cross_plat(cross_plat_poly, cross_plat_kalshi)))
        # LLM tournament
        tasks.append(_safe_scan("tournament", self._scan_tournament(tournament_questions)))
        # Semantic leader-follower
        tasks.append(_safe_scan("leader_follower", self._scan_leader_follower(leader_follower_data)))

        results = await asyncio.gather(*tasks)
        all_packets: list[ExecutionPacket] = []
        for batch in results:
            all_packets.extend(batch)

        logger.info("scan_all_lanes: %d raw packets from %d lanes", len(all_packets), len(results))
        return all_packets

    # ------------------------------------------------------------------
    # Individual lane scanners
    # ------------------------------------------------------------------

    async def _scan_neg_risk(self, data: Any = None) -> list[ExecutionPacket]:
        if self._neg_risk is None:
            return []
        opps = await self._neg_risk.scan_all(market_data=data)
        packets: list[ExecutionPacket] = []
        for opp in opps:
            packets.extend(self._adapt_neg_risk(opp))
        return packets

    async def _scan_whale(self, signals: Optional[list] = None) -> list[ExecutionPacket]:
        if self._whale is None:
            return []
        if signals is not None:
            consensus = signals
        else:
            consensus = self._whale.get_consensus_signals()
        packets: list[ExecutionPacket] = []
        for sig in consensus:
            pkt = self._adapt_whale(sig)
            if pkt is not None:
                packets.append(pkt)
        return packets

    async def _scan_resolution(self, markets: Optional[list[dict]] = None) -> list[ExecutionPacket]:
        if self._sniper is None:
            return []
        if markets is None:
            return []
        targets = self._sniper.scan_markets(markets)
        packets: list[ExecutionPacket] = []
        for target in targets:
            pkt = self._adapt_resolution(target)
            if pkt is not None:
                packets.append(pkt)
        return packets

    async def _scan_cross_plat(
        self,
        poly_data: Optional[list] = None,
        kalshi_data: Optional[list] = None,
    ) -> list[ExecutionPacket]:
        if self._cross_plat is None:
            return []
        opps = await self._cross_plat.scan_all(
            polymarket_data=poly_data,
            kalshi_data=kalshi_data,
        )
        packets: list[ExecutionPacket] = []
        for opp in opps:
            packets.extend(self._adapt_cross_plat(opp))
        return packets

    async def _scan_tournament(
        self, questions: Optional[list[dict]] = None,
    ) -> list[ExecutionPacket]:
        if self._tournament is None:
            return []
        if not questions:
            return []
        packets: list[ExecutionPacket] = []
        for q in questions:
            try:
                result = await self._tournament.run_tournament(
                    market_id=q["market_id"],
                    question=q["question"],
                    market_price=q["market_price"],
                    model_responses=q.get("model_responses"),
                )
                pkt = self._adapt_llm_tournament(result)
                if pkt is not None:
                    packets.append(pkt)
            except Exception as exc:
                logger.warning("Tournament failed for %s: %s", q.get("market_id", "?"), exc)
        return packets

    async def _scan_leader_follower(
        self, data: Optional[dict] = None,
    ) -> list[ExecutionPacket]:
        if self._leader_follower is None:
            return []
        if data is None:
            return []
        signals = data.get("signals", [])
        packets: list[ExecutionPacket] = []
        for sig in signals:
            pkt = self._adapt_leader_follower(sig)
            if pkt is not None:
                packets.append(pkt)
        return packets

    # ------------------------------------------------------------------
    # Lane adapters
    # ------------------------------------------------------------------

    def _adapt_neg_risk(self, opportunity: Any) -> list[ExecutionPacket]:
        """Convert ArbitrageOpportunity to a list of linked ExecutionPackets (one per leg)."""
        if not hasattr(opportunity, "markets") or not opportunity.markets:
            return []

        group_id = uuid.uuid4().hex[:12]
        packet_ids: list[str] = []
        packets: list[ExecutionPacket] = []

        max_per_leg = float(self._config.get("neg_risk_max_per_leg", 50.0))
        min_per_leg = float(self._config.get("neg_risk_min_per_leg", 5.0))

        n_legs = len(opportunity.markets)
        budget = min(max_per_leg * n_legs, self._max_per_lane)
        per_leg = max(min_per_leg, min(max_per_leg, budget / n_legs))

        evidence = f"neg_risk|group={opportunity.market_group_id}|cost={opportunity.total_cost}|profit_pct={opportunity.profit_pct}"

        for leg in opportunity.markets:
            pkt = ExecutionPacket(
                strategy_id="neg_risk",
                market_id=leg.get("market_id", ""),
                platform="polymarket",
                direction="YES",
                token_id=leg.get("token_id", ""),
                size_usd=round(per_leg, 2),
                edge_estimate=opportunity.profit_pct,
                confidence=0.99,  # Guaranteed profit
                evidence_hash=_evidence_hash(evidence),
                max_slippage=float(self._config.get("default_max_slippage", 0.02)),
                ttl_seconds=30,
                order_type="taker",  # Neg-risk needs simultaneous fill
                priority=PRIORITY_NEG_RISK,
                metadata={
                    "group_id": group_id,
                    "opportunity_type": opportunity.opportunity_type,
                    "total_cost": opportunity.total_cost,
                    "guaranteed_payout": opportunity.guaranteed_payout,
                    "leg_price": leg.get("yes_price", 0.0),
                },
            )
            packet_ids.append(pkt.packet_id)
            packets.append(pkt)

        # Link all packets in the basket
        for pkt in packets:
            pkt.linked_packets = [pid for pid in packet_ids if pid != pkt.packet_id]

        logger.debug(
            "adapt_neg_risk: %d legs, $%.2f/leg, profit_pct=%.4f",
            n_legs, per_leg, opportunity.profit_pct,
        )
        return packets

    def _adapt_whale(self, signal: Any) -> Optional[ExecutionPacket]:
        """Convert ConsensusSignal to a single ExecutionPacket."""
        if signal is None:
            return None

        market_id = getattr(signal, "market_id", "")
        direction = getattr(signal, "direction", "YES")
        confidence = getattr(signal, "confidence", 0.5)
        recommended_size = getattr(signal, "recommended_size_usd", 10.0)

        edge = max(0.0, getattr(signal, "consensus_pct", 0.5) - 0.5)
        evidence = f"whale|market={market_id}|dir={direction}|wallets={getattr(signal, 'agreeing_wallets', 0)}"

        size = min(recommended_size, self._max_per_market)

        return ExecutionPacket(
            strategy_id="whale",
            market_id=market_id,
            platform="polymarket",
            direction=direction,
            token_id="",  # Resolved at execution time
            size_usd=round(size, 2),
            edge_estimate=round(edge, 4),
            confidence=round(confidence, 4),
            evidence_hash=_evidence_hash(evidence),
            max_slippage=float(self._config.get("default_max_slippage", 0.02)),
            ttl_seconds=int(self._config.get("default_ttl_seconds", 120)),
            order_type=str(self._config.get("default_order_type", "maker")),
            priority=PRIORITY_WHALE,
            metadata={
                "agreeing_wallets": getattr(signal, "agreeing_wallets", 0),
                "total_tracked": getattr(signal, "total_tracked", 0),
                "consensus_pct": getattr(signal, "consensus_pct", 0.0),
                "question": getattr(signal, "market_question", ""),
            },
        )

    def _adapt_resolution(self, target: Any) -> Optional[ExecutionPacket]:
        """Convert ResolutionTarget to a single ExecutionPacket."""
        if target is None:
            return None

        market_id = getattr(target, "market_id", "")
        direction = getattr(target, "expected_outcome", "YES")
        confidence = getattr(target, "confidence", 0.9)
        profit = getattr(target, "expected_profit_per_share", 0.03)

        default_size = float(self._config.get("resolution_default_size", 10.0))
        size = min(default_size, self._max_per_market)

        evidence = (
            f"resolution|market={market_id}|outcome={direction}"
            f"|conf={confidence:.3f}|profit={profit:.4f}"
        )

        return ExecutionPacket(
            strategy_id="resolution",
            market_id=market_id,
            platform="polymarket",
            direction=direction,
            token_id="",
            size_usd=round(size, 2),
            edge_estimate=round(profit, 4),
            confidence=round(confidence, 4),
            evidence_hash=_evidence_hash(evidence),
            max_slippage=float(self._config.get("default_max_slippage", 0.02)),
            ttl_seconds=int(self._config.get("default_ttl_seconds", 120)),
            order_type="maker",
            priority=PRIORITY_RESOLUTION,
            metadata={
                "question": getattr(target, "question", ""),
                "yes_price": getattr(target, "current_yes_price", 0.0),
                "no_price": getattr(target, "current_no_price", 0.0),
                "resolution_eta_hours": getattr(target, "resolution_eta_hours", 0.0),
                "risk_factors": getattr(target, "risk_factors", []),
            },
        )

    def _adapt_cross_plat(self, opp: Any) -> list[ExecutionPacket]:
        """Convert CrossPlatformOpportunity to two linked ExecutionPackets."""
        if opp is None:
            return []

        pair = getattr(opp, "matched_pair", None)
        if pair is None:
            return []

        group_id = uuid.uuid4().hex[:12]
        profit_pct = getattr(opp, "profit_pct", 0.0)
        net_cost = getattr(opp, "net_cost", 1.0)

        buy_yes_platform = getattr(opp, "buy_yes_platform", "polymarket")
        buy_no_platform = getattr(opp, "buy_no_platform", "kalshi")
        yes_price = getattr(opp, "yes_price", 0.5)
        no_price = getattr(opp, "no_price", 0.5)

        pm = getattr(pair, "polymarket", None)
        km = getattr(pair, "kalshi", None)

        size = min(self._max_per_market, 50.0)  # Conservative initial size

        evidence = f"cross_plat|profit_pct={profit_pct:.4f}|net_cost={net_cost:.4f}"

        pkt_yes = ExecutionPacket(
            strategy_id="cross_plat",
            market_id=getattr(pm, "market_id", "") if buy_yes_platform == "polymarket" else getattr(km, "market_id", ""),
            platform=buy_yes_platform,
            direction="YES",
            token_id="",
            size_usd=round(size, 2),
            edge_estimate=round(profit_pct, 4),
            confidence=0.95 if getattr(opp, "risk_level", "HIGH") == "LOW" else 0.80,
            evidence_hash=_evidence_hash(evidence),
            max_slippage=float(self._config.get("default_max_slippage", 0.02)),
            ttl_seconds=15,
            order_type="taker",  # Cross-plat needs simultaneous fill
            priority=PRIORITY_CROSS_PLAT,
            metadata={
                "group_id": group_id,
                "leg": "yes",
                "platform": buy_yes_platform,
                "price": yes_price,
                "risk_level": getattr(opp, "risk_level", "MEDIUM"),
            },
        )

        pkt_no = ExecutionPacket(
            strategy_id="cross_plat",
            market_id=getattr(km, "market_id", "") if buy_no_platform == "kalshi" else getattr(pm, "market_id", ""),
            platform=buy_no_platform,
            direction="NO",
            token_id="",
            size_usd=round(size, 2),
            edge_estimate=round(profit_pct, 4),
            confidence=pkt_yes.confidence,
            evidence_hash=_evidence_hash(evidence),
            max_slippage=float(self._config.get("default_max_slippage", 0.02)),
            ttl_seconds=15,
            order_type="taker",
            priority=PRIORITY_CROSS_PLAT,
            metadata={
                "group_id": group_id,
                "leg": "no",
                "platform": buy_no_platform,
                "price": no_price,
                "risk_level": getattr(opp, "risk_level", "MEDIUM"),
            },
        )

        # Link the two legs
        pkt_yes.linked_packets = [pkt_no.packet_id]
        pkt_no.linked_packets = [pkt_yes.packet_id]

        return [pkt_yes, pkt_no]

    def _adapt_llm_tournament(self, result: Any) -> Optional[ExecutionPacket]:
        """Convert TournamentResult to an ExecutionPacket (or None if no signal)."""
        if result is None:
            return None

        signal = getattr(result, "signal", "NO_SIGNAL")
        if signal == "NO_SIGNAL":
            return None

        market_id = getattr(result, "market_id", "")
        direction = "YES" if signal == "BUY_YES" else "NO"
        agreement = getattr(result, "agreement_score", 0.0)
        abs_div = getattr(result, "abs_divergence", 0.0)
        strength = getattr(result, "signal_strength", 0.0)

        edge = abs_div * agreement
        kelly_frac = float(self._config.get("tournament_kelly_fraction", 0.25))
        size = min(self._capital * kelly_frac * edge, self._max_per_market)
        size = max(1.0, size)

        evidence = (
            f"tournament|market={market_id}|signal={signal}"
            f"|agreement={agreement:.3f}|divergence={abs_div:.3f}"
        )

        return ExecutionPacket(
            strategy_id="llm_tournament",
            market_id=market_id,
            platform="polymarket",
            direction=direction,
            token_id="",
            size_usd=round(size, 2),
            edge_estimate=round(edge, 4),
            confidence=round(agreement, 4),
            evidence_hash=_evidence_hash(evidence),
            max_slippage=float(self._config.get("default_max_slippage", 0.02)),
            ttl_seconds=int(self._config.get("default_ttl_seconds", 120)),
            order_type="maker",
            priority=PRIORITY_LLM_TOURNAMENT,
            metadata={
                "question": getattr(result, "market_question", ""),
                "mean_probability": getattr(result, "mean_probability", 0.0),
                "market_price": getattr(result, "market_price", 0.0),
                "signal_strength": strength,
                "total_cost_usd": getattr(result, "total_cost_usd", 0.0),
            },
        )

    def _adapt_leader_follower(self, signal: Any) -> Optional[ExecutionPacket]:
        """Convert LeaderFollowerSignal to an ExecutionPacket."""
        if signal is None:
            return None

        follower_id = getattr(signal, "follower_market_id", "")
        recommended_side = getattr(signal, "recommended_side", "BUY_YES")
        direction = "YES" if recommended_side == "BUY_YES" else "NO"
        confidence = getattr(signal, "confidence", 0.5)
        strength = getattr(signal, "signal_strength", 0.0)
        recommended_size = getattr(signal, "recommended_size_usd", 5.0)

        size = min(recommended_size, self._max_per_market)

        evidence = (
            f"leader_follower|follower={follower_id}"
            f"|strength={strength:.3f}|side={recommended_side}"
        )

        return ExecutionPacket(
            strategy_id="leader_follower",
            market_id=follower_id,
            platform="polymarket",
            direction=direction,
            token_id="",
            size_usd=round(size, 2),
            edge_estimate=round(strength, 4),
            confidence=round(confidence, 4),
            evidence_hash=_evidence_hash(evidence),
            max_slippage=float(self._config.get("default_max_slippage", 0.02)),
            ttl_seconds=int(self._config.get("default_ttl_seconds", 120)),
            order_type="maker",
            priority=PRIORITY_LEADER_FOLLOWER,
            metadata={
                "leader_market_id": getattr(signal, "leader_market_id", ""),
                "leader_question": getattr(signal, "leader_question", ""),
                "follower_question": getattr(signal, "follower_question", ""),
                "pair_similarity": getattr(signal, "pair_similarity", 0.0),
                "predicted_direction": getattr(signal, "predicted_direction", ""),
                "predicted_magnitude": getattr(signal, "predicted_magnitude", 0.0),
            },
        )

    # ------------------------------------------------------------------
    # Priority and conflict resolution
    # ------------------------------------------------------------------

    def prioritize_signals(self, packets: list[ExecutionPacket]) -> list[ExecutionPacket]:
        """Sort packets by priority (P0 first) and apply conflict resolution.

        Conflict rules:
        1. Higher-priority lane wins on same market.
        2. Same-priority opposing signals on same market: both dropped.
        3. Dedup: only one packet per (market_id, direction) unless linked.
        """
        # Sort by priority ascending (P0 = highest priority = lowest number)
        sorted_packets = sorted(packets, key=lambda p: (p.priority, -p.edge_estimate))

        # Track claimed markets: {market_id: (direction, priority, packet_id)}
        claimed: dict[str, tuple[str, int, str]] = {}
        accepted: list[ExecutionPacket] = []
        dropped_ids: set[str] = set()

        for pkt in sorted_packets:
            mid = pkt.market_id
            if mid in claimed:
                prev_dir, prev_pri, prev_id = claimed[mid]

                # Same-priority conflict with opposing direction: drop both
                if prev_pri == pkt.priority and prev_dir != pkt.direction:
                    logger.info(
                        "Conflict: dropping both %s and %s on market %s (same priority, opposing)",
                        prev_id, pkt.packet_id, mid,
                    )
                    dropped_ids.add(prev_id)
                    dropped_ids.add(pkt.packet_id)
                    continue

                # Higher-priority already claimed this market
                if prev_pri < pkt.priority:
                    logger.debug(
                        "Suppressed %s (P%d) on market %s — already claimed by P%d",
                        pkt.packet_id, pkt.priority, mid, prev_pri,
                    )
                    dropped_ids.add(pkt.packet_id)
                    continue

                # Same priority, same direction — keep first (higher edge)
                if prev_pri == pkt.priority and prev_dir == pkt.direction:
                    dropped_ids.add(pkt.packet_id)
                    continue

            claimed[mid] = (pkt.direction, pkt.priority, pkt.packet_id)
            accepted.append(pkt)

        # Remove any packets that were retroactively dropped
        result = [p for p in accepted if p.packet_id not in dropped_ids]

        logger.info(
            "prioritize_signals: %d input -> %d accepted, %d dropped",
            len(packets), len(result), len(dropped_ids),
        )
        return result

    # ------------------------------------------------------------------
    # Exposure checks
    # ------------------------------------------------------------------

    def check_exposure(self, packet: ExecutionPacket) -> tuple[bool, str]:
        """Check whether a packet would breach exposure caps.

        Returns (allowed, reason). reason is empty string if allowed.
        """
        mid = packet.market_id
        lane = packet.strategy_id

        # Per-market cap
        current_market = self._market_exposure.get(mid, 0.0)
        if current_market + packet.size_usd > self._max_per_market:
            return False, f"market_cap_breach: {mid} would be ${current_market + packet.size_usd:.2f} > ${self._max_per_market:.2f}"

        # Per-lane cap
        current_lane = self._lane_exposure.get(lane, 0.0)
        if current_lane + packet.size_usd > self._max_per_lane:
            return False, f"lane_cap_breach: {lane} would be ${current_lane + packet.size_usd:.2f} > ${self._max_per_lane:.2f}"

        # Total desk cap
        if self._total_exposure + packet.size_usd > self._desk_budget:
            return False, f"desk_cap_breach: total would be ${self._total_exposure + packet.size_usd:.2f} > ${self._desk_budget:.2f}"

        return True, ""

    def _update_exposure(self, packet: ExecutionPacket, delta: float) -> None:
        """Add or subtract exposure for a packet."""
        mid = packet.market_id
        lane = packet.strategy_id
        self._market_exposure[mid] = self._market_exposure.get(mid, 0.0) + delta
        self._lane_exposure[lane] = self._lane_exposure.get(lane, 0.0) + delta
        self._total_exposure += delta

        # Clean up zero entries
        if self._market_exposure.get(mid, 0.0) <= 0:
            self._market_exposure.pop(mid, None)
        if self._lane_exposure.get(lane, 0.0) <= 0:
            self._lane_exposure.pop(lane, None)

    # ------------------------------------------------------------------
    # Packet generation pipeline
    # ------------------------------------------------------------------

    def generate_packets(self, raw_packets: list[ExecutionPacket]) -> list[ExecutionPacket]:
        """Full pipeline: prioritize, resolve conflicts, check exposure.

        Returns the final list of packets ready for execution.
        """
        prioritized = self.prioritize_signals(raw_packets)
        approved: list[ExecutionPacket] = []

        for pkt in prioritized:
            allowed, reason = self.check_exposure(pkt)
            if allowed:
                approved.append(pkt)
            else:
                logger.info(
                    "Exposure blocked %s (%s) on %s: %s",
                    pkt.packet_id, pkt.strategy_id, pkt.market_id, reason,
                )
                pkt.status = "rejected"
                self._rejections.append({
                    "packet_id": pkt.packet_id,
                    "reason": reason,
                    "timestamp": time.time(),
                })

        self._active_packets = approved
        return approved

    def get_active_packets(self) -> list[ExecutionPacket]:
        """Return the current list of approved packets."""
        return list(self._active_packets)

    # ------------------------------------------------------------------
    # Fill / rejection recording
    # ------------------------------------------------------------------

    def record_fill(self, packet: ExecutionPacket, fill_price: float = 0.0) -> None:
        """Record a filled order — updates exposure tracking."""
        packet.status = "filled"
        self._update_exposure(packet, packet.size_usd)
        self._fills.append({
            "packet_id": packet.packet_id,
            "strategy_id": packet.strategy_id,
            "market_id": packet.market_id,
            "direction": packet.direction,
            "size_usd": packet.size_usd,
            "fill_price": fill_price,
            "timestamp": time.time(),
        })
        logger.info(
            "FILL: %s %s %s $%.2f @ %.4f",
            packet.strategy_id, packet.market_id, packet.direction,
            packet.size_usd, fill_price,
        )

    def record_rejection(self, packet: ExecutionPacket, reason: str = "") -> None:
        """Record a rejected/failed order."""
        packet.status = "rejected"
        self._rejections.append({
            "packet_id": packet.packet_id,
            "strategy_id": packet.strategy_id,
            "market_id": packet.market_id,
            "reason": reason,
            "timestamp": time.time(),
        })
        logger.info(
            "REJECT: %s %s %s — %s",
            packet.strategy_id, packet.market_id, packet.direction, reason,
        )

    def release_exposure(self, packet: ExecutionPacket) -> None:
        """Release exposure for a position that has been closed or expired."""
        self._update_exposure(packet, -packet.size_usd)

    # ------------------------------------------------------------------
    # Capital management
    # ------------------------------------------------------------------

    def update_capital(self, new_capital: float) -> None:
        """Update the capital base (e.g. after reconciliation)."""
        self._capital = new_capital
        self._config["capital"] = new_capital
        logger.info("Capital updated to $%.2f", new_capital)

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def get_diagnostics(self) -> dict:
        """Return full desk state for monitoring."""
        lane_stats: dict[str, dict] = {}
        for lane_name in set(LANE_NAMES.values()):
            lane_stats[lane_name] = {
                "exposure": self._lane_exposure.get(lane_name, 0.0),
                "fills": sum(1 for f in self._fills if f["strategy_id"] == lane_name),
                "rejections": sum(1 for r in self._rejections if r.get("strategy_id") == lane_name),
            }

        scanner_status = {
            "neg_risk": self._neg_risk is not None,
            "whale": self._whale is not None,
            "sniper": self._sniper is not None,
            "cross_plat": self._cross_plat is not None,
            "tournament": self._tournament is not None,
            "leader_follower": self._leader_follower is not None,
        }

        return {
            "capital": self._capital,
            "desk_budget": self._desk_budget,
            "max_per_market": self._max_per_market,
            "max_per_lane": self._max_per_lane,
            "total_exposure": self._total_exposure,
            "market_exposure": dict(self._market_exposure),
            "lane_exposure": dict(self._lane_exposure),
            "active_packets": len(self._active_packets),
            "total_fills": len(self._fills),
            "total_rejections": len(self._rejections),
            "lane_stats": lane_stats,
            "scanner_status": scanner_status,
        }
