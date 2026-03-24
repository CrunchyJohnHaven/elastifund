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
  P7  BTC5                   — BTC 5-minute maker signals
  P8  DualSidedSpread        — pair-completion spread capture

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
import inspect
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

try:
    from bot.event_tape import EventTapeWriter
except ImportError:
    try:
        from event_tape import EventTapeWriter  # type: ignore
    except ImportError:
        EventTapeWriter = None  # type: ignore[misc, assignment]

try:
    from bot.spread_capture import SpreadCaptureScanner, SpreadWindowScan
except ImportError:
    try:
        from spread_capture import SpreadCaptureScanner, SpreadWindowScan  # type: ignore
    except ImportError:
        SpreadCaptureScanner = None  # type: ignore[misc, assignment]
        SpreadWindowScan = None  # type: ignore[misc, assignment]

try:
    from bot.maker_velocity_blitz import (
        MarketSnapshot,
        DualSidedSpreadIntent,
        rank_dual_sided_spread_markets,
        allocate_dual_sided_spread_notional,
        build_dual_sided_spread_intents,
    )
except ImportError:
    try:
        from maker_velocity_blitz import (  # type: ignore
            MarketSnapshot,
            DualSidedSpreadIntent,
            rank_dual_sided_spread_markets,
            allocate_dual_sided_spread_notional,
            build_dual_sided_spread_intents,
        )
    except ImportError:
        MarketSnapshot = None  # type: ignore[misc, assignment]
        DualSidedSpreadIntent = None  # type: ignore[misc, assignment]
        rank_dual_sided_spread_markets = None  # type: ignore[misc, assignment]
        allocate_dual_sided_spread_notional = None  # type: ignore[misc, assignment]
        build_dual_sided_spread_intents = None  # type: ignore[misc, assignment]

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
PRIORITY_DUAL_SIDED: int = 8

LANE_NAMES: dict[int, str] = {
    PRIORITY_NEG_RISK: "neg_risk",
    PRIORITY_CROSS_PLAT: "cross_plat",
    PRIORITY_RESOLUTION: "resolution",
    PRIORITY_STALE_QUOTE: "stale_quote",
    PRIORITY_WHALE: "whale",
    PRIORITY_LEADER_FOLLOWER: "leader_follower",
    PRIORITY_LLM_TOURNAMENT: "llm_tournament",
    PRIORITY_BTC5: "btc5",
    PRIORITY_DUAL_SIDED: "dual_sided",
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

    # Proof-carrying fields (required for structural execution)
    post_only: bool = True
    edge_after_fees_usd: float = 0.0
    partial_fill_policy: str = "cancel_after_ttl"  # "cancel_after_ttl" or "hedge_taker"
    promotion_stage: str = "shadow"  # "shadow", "micro_live", "seed", "scale"

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


def _launch_rank(packet: ExecutionPacket, launch_order: list[str] | None) -> tuple[Any, ...]:
    """Return a deterministic sort key for a packet.

    When launch_order is provided, it overrides the default priority
    ordering for the first-claim pass while preserving the existing
    conflict-resolution semantics.
    """
    if launch_order:
        order_map = {name: idx for idx, name in enumerate(launch_order)}
        return (
            order_map.get(packet.strategy_id, len(order_map)),
            packet.priority,
            -packet.edge_estimate,
            packet.timestamp,
            packet.packet_id,
        )
    return (packet.priority, -packet.edge_estimate, packet.timestamp, packet.packet_id)


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
    "dual_sided_combined_cost_cap": 0.97,
    "dual_sided_reserve_pct": 0.20,
    "dual_sided_per_market_cap": 10.0,
    "dual_sided_max_markets": 6,
}


# ---------------------------------------------------------------------------
# Strike Desk
# ---------------------------------------------------------------------------


class StrikeDesk:
    """Aggregates signals from all money-making scanners into a
    priority-ordered execution queue with exposure management."""

    def __init__(
        self,
        config: Optional[dict[str, Any]] = None,
        tape_writer: Any | None = None,
    ) -> None:
        self._config: dict[str, Any] = {**DEFAULT_CONFIG, **(config or {})}
        self._capital: float = float(self._config["capital"])
        self._tape_writer = tape_writer

        # Exposure tracking: {market_id: usd_amount}
        self._market_exposure: dict[str, float] = {}
        # Lane exposure: {lane_name: usd_amount}
        self._lane_exposure: dict[str, float] = {}
        # Total desk exposure
        self._total_exposure: float = 0.0

        # Fill / rejection history
        self._fills: list[dict] = []
        self._rejections: list[dict] = []
        self._execution_log: list[dict[str, Any]] = []

        # Active packets (current cycle)
        self._active_packets: list[ExecutionPacket] = []
        self._last_shadow_alternatives: list[dict[str, Any]] = []
        self._packet_approval_seq: dict[str, int] = {}

        # Scanner instances (lazy-init, can be injected)
        self._neg_risk: Any = None
        self._whale: Any = None
        self._sniper: Any = None
        self._cross_plat: Any = None
        self._tournament: Any = None
        self._leader_follower: Any = None
        self._spread_capture: Any = None

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

        if SpreadCaptureScanner is not None:
            try:
                self._spread_capture = SpreadCaptureScanner(
                    ask_sum_threshold=float(self._config.get("dual_sided_combined_cost_cap", 0.97)),
                )
            except Exception as exc:
                logger.warning("SpreadCaptureScanner init failed: %s", exc)

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
        enabled_lanes: Optional[set[str]] = None,
        neg_risk_data: Any = None,
        whale_signals: Optional[list] = None,
        sniper_markets: Optional[list[dict]] = None,
        cross_plat_poly: Optional[list] = None,
        cross_plat_kalshi: Optional[list] = None,
        tournament_questions: Optional[list[dict]] = None,
        leader_follower_data: Optional[dict] = None,
        dual_sided_snapshots: Optional[list] = None,
    ) -> list[ExecutionPacket]:
        """Run all available scanners via asyncio.gather.

        Each scanner is wrapped so that a failure in one does not block
        the others.  Returns a flat list of ExecutionPackets from all
        lanes, unsorted.

        Keyword arguments allow injecting data for each lane (for tests
        or when live data is pre-fetched).
        """
        tasks = []

        def _enabled(name: str) -> bool:
            return enabled_lanes is None or name in enabled_lanes

        async def _safe_scan(name: str, coro: Any) -> list[ExecutionPacket]:
            try:
                return await coro
            except Exception as exc:
                logger.error("Lane %s scan failed: %s", name, exc)
                return []

        # Neg-risk
        if _enabled("neg_risk"):
            tasks.append(_safe_scan("neg_risk", self._scan_neg_risk(neg_risk_data)))
        # Whale
        if _enabled("whale"):
            tasks.append(_safe_scan("whale", self._scan_whale(whale_signals)))
        # Resolution sniper
        if _enabled("resolution"):
            tasks.append(_safe_scan("resolution", self._scan_resolution(sniper_markets)))
        # Cross-platform arb
        if _enabled("cross_plat"):
            tasks.append(_safe_scan("cross_plat", self._scan_cross_plat(cross_plat_poly, cross_plat_kalshi)))
        # LLM tournament
        if _enabled("tournament"):
            tasks.append(_safe_scan("tournament", self._scan_tournament(tournament_questions)))
        # Semantic leader-follower
        if _enabled("leader_follower"):
            tasks.append(_safe_scan("leader_follower", self._scan_leader_follower(leader_follower_data)))
        # Dual-sided spread capture
        if _enabled("dual_sided"):
            tasks.append(_safe_scan("dual_sided", self._scan_dual_sided(dual_sided_snapshots)))

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

        for market in markets:
            best_bid = market.get("best_bid")
            best_ask = market.get("best_ask")
            if best_bid is None or best_ask is None:
                continue
            try:
                fair_price = float(
                    market.get("mid")
                    if market.get("mid") is not None
                    else (float(best_bid) + float(best_ask)) / 2.0
                )
            except (TypeError, ValueError):
                fair_price = 0.5

            order_book = {
                "bids": [{"price": float(best_bid), "size": float(market.get("bid_depth_usd", 1.0) or 1.0)}],
                "asks": [{"price": float(best_ask), "size": float(market.get("ask_depth_usd", 1.0) or 1.0)}],
            }
            stale_quotes = self._sniper.detect_stale_quotes(
                market_id=str(market.get("market_id") or market.get("condition_id") or ""),
                question=str(market.get("question") or ""),
                order_book=order_book,
                fair_price_estimate=fair_price,
            )
            for quote in stale_quotes:
                if quote.stale_price >= quote.fair_price:
                    continue
                pkt = self._adapt_stale_quote(quote)
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

    async def _scan_dual_sided(
        self, snapshots: Optional[list] = None,
    ) -> list[ExecutionPacket]:
        """Scan for dual-sided spread capture opportunities.

        Accepts a list of MarketSnapshot objects (or dicts with the same
        fields).  Ranks them by locked-edge score, allocates notional,
        builds DualSidedSpreadIntent objects, and converts each intent
        into a linked pair of ExecutionPackets (one YES, one NO).
        """
        if rank_dual_sided_spread_markets is None or build_dual_sided_spread_intents is None:
            return []
        if not snapshots:
            return []

        # Coerce dicts to MarketSnapshot if needed
        typed_snapshots: list[Any] = []
        for snap in snapshots:
            if MarketSnapshot is not None and not isinstance(snap, MarketSnapshot):
                try:
                    typed_snapshots.append(MarketSnapshot(**snap))
                except Exception:
                    continue
            else:
                typed_snapshots.append(snap)

        combined_cost_cap = float(self._config.get("dual_sided_combined_cost_cap", 0.97))
        reserve_pct = float(self._config.get("dual_sided_reserve_pct", 0.20))
        per_market_cap = float(self._config.get("dual_sided_per_market_cap", 10.0))
        max_markets = int(self._config.get("dual_sided_max_markets", 6))

        ranked = rank_dual_sided_spread_markets(
            typed_snapshots,
            combined_cost_cap=combined_cost_cap,
        )
        if not ranked:
            return []

        allocations = allocate_dual_sided_spread_notional(
            bankroll_usd=self._capital,
            ranked_candidates=ranked,
            reserve_pct=reserve_pct,
            per_market_cap_usd=per_market_cap,
            max_markets=max_markets,
        )
        if not allocations:
            return []

        intents = build_dual_sided_spread_intents(
            allocations_usd=allocations,
            ranked_candidates=ranked,
        )

        packets: list[ExecutionPacket] = []
        for intent in intents:
            packets.extend(self._adapt_dual_sided(intent))

        logger.info(
            "scan_dual_sided: %d snapshots -> %d ranked -> %d intents -> %d packets",
            len(typed_snapshots), len(ranked), len(intents), len(packets),
        )
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

        # Build per-market direction+token_id map from calculate_optimal_portfolio
        # when available (real ArbitrageOpportunity objects).  This resolves YES vs NO
        # correctly for combinatorial legs where the NO token must be used.
        portfolio: dict = {}
        if callable(getattr(opportunity, "calculate_optimal_portfolio", None)):
            try:
                portfolio = opportunity.calculate_optimal_portfolio()
            except Exception:
                portfolio = {}

        for leg in opportunity.markets:
            market_id = leg.get("market_id", "")
            port_entry = portfolio.get(market_id, {})
            direction = port_entry.get("side", "YES")
            if direction == "NO":
                token_id = leg.get("no_token_id", port_entry.get("token_id", ""))
            else:
                token_id = leg.get("token_id", port_entry.get("token_id", ""))
            leg_price = leg.get("no_price", 0.0) if direction == "NO" else leg.get("yes_price", 0.0)
            pkt = ExecutionPacket(
                strategy_id="neg_risk",
                market_id=market_id,
                platform="polymarket",
                direction=direction,
                token_id=token_id,
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
                    "leg_price": leg_price,
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

    def _adapt_stale_quote(self, quote: Any) -> Optional[ExecutionPacket]:
        """Convert StaleQuote to a maker-first YES-side execution packet."""
        if quote is None:
            return None

        market_id = getattr(quote, "market_id", "")
        size = min(float(getattr(quote, "size_available", 1.0) or 1.0), self._max_per_market)
        size = max(1.0, size)
        evidence = (
            f"stale_quote|market={market_id}|side={getattr(quote, 'side', 'YES')}"
            f"|stale={getattr(quote, 'stale_price', 0.0):.4f}|fair={getattr(quote, 'fair_price', 0.0):.4f}"
        )

        return ExecutionPacket(
            strategy_id="stale_quote",
            market_id=market_id,
            platform="polymarket",
            direction="YES",
            token_id="",
            size_usd=round(size, 2),
            edge_estimate=round(float(getattr(quote, "edge", 0.0) or 0.0), 4),
            confidence=0.85,
            evidence_hash=_evidence_hash(evidence),
            max_slippage=float(self._config.get("default_max_slippage", 0.02)),
            ttl_seconds=15,
            order_type="maker",
            priority=PRIORITY_STALE_QUOTE,
            metadata={
                "question": getattr(quote, "question", ""),
                "stale_price": getattr(quote, "stale_price", 0.0),
                "fair_price": getattr(quote, "fair_price", 0.0),
                "size_available": getattr(quote, "size_available", 0.0),
                "likely_reason": getattr(quote, "likely_reason", ""),
                "execution_side": "buy_yes",
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

    def _adapt_dual_sided(self, intent: Any) -> list[ExecutionPacket]:
        """Convert a DualSidedSpreadIntent into a linked pair of ExecutionPackets.

        Returns two packets (YES leg, NO leg) with mutual linked_packets
        references.  Both legs are maker-only.
        """
        if intent is None:
            return []

        market_id = getattr(intent, "market_id", "")
        yes_price = float(getattr(intent, "yes_buy_price", 0.0))
        no_price = float(getattr(intent, "no_buy_price", 0.0))
        notional = float(getattr(intent, "notional_usd", 0.0))
        combined_cost = yes_price + no_price
        locked_edge = max(0.0, 1.0 - combined_cost)

        # Enforce combined cost cap
        cost_cap = float(self._config.get("dual_sided_combined_cost_cap", 0.97))
        if combined_cost >= cost_cap:
            logger.debug(
                "adapt_dual_sided: skipping %s — combined_cost=%.4f >= cap=%.4f",
                market_id, combined_cost, cost_cap,
            )
            return []

        group_id = uuid.uuid4().hex[:12]
        evidence = (
            f"dual_sided|market={market_id}"
            f"|yes={yes_price:.4f}|no={no_price:.4f}"
            f"|combined={combined_cost:.4f}|edge={locked_edge:.4f}"
        )

        per_leg = round(notional / 2.0, 2)
        timeout = int(getattr(intent, "timeout_seconds", 120))

        pkt_yes = ExecutionPacket(
            strategy_id="dual_sided",
            market_id=market_id,
            platform="polymarket",
            direction="YES",
            token_id="",
            size_usd=per_leg,
            edge_estimate=round(locked_edge, 4),
            confidence=0.90,
            evidence_hash=_evidence_hash(evidence),
            max_slippage=float(self._config.get("default_max_slippage", 0.02)),
            ttl_seconds=timeout,
            order_type="maker",
            priority=PRIORITY_DUAL_SIDED,
            metadata={
                "group_id": group_id,
                "leg": "yes",
                "yes_buy_price": yes_price,
                "no_buy_price": no_price,
                "combined_cost": round(combined_cost, 6),
                "locked_edge": round(locked_edge, 6),
                "reference_price": yes_price,
                "wallet_confirmation_mode": getattr(intent, "wallet_confirmation_mode", "overlay_only"),
            },
        )

        pkt_no = ExecutionPacket(
            strategy_id="dual_sided",
            market_id=market_id,
            platform="polymarket",
            direction="NO",
            token_id="",
            size_usd=per_leg,
            edge_estimate=round(locked_edge, 4),
            confidence=0.90,
            evidence_hash=_evidence_hash(evidence),
            max_slippage=float(self._config.get("default_max_slippage", 0.02)),
            ttl_seconds=timeout,
            order_type="maker",
            priority=PRIORITY_DUAL_SIDED,
            metadata={
                "group_id": group_id,
                "leg": "no",
                "yes_buy_price": yes_price,
                "no_buy_price": no_price,
                "combined_cost": round(combined_cost, 6),
                "locked_edge": round(locked_edge, 6),
                "reference_price": no_price,
                "wallet_confirmation_mode": getattr(intent, "wallet_confirmation_mode", "overlay_only"),
            },
        )

        # Link the two legs
        pkt_yes.linked_packets = [pkt_no.packet_id]
        pkt_no.linked_packets = [pkt_yes.packet_id]

        return [pkt_yes, pkt_no]

    # ------------------------------------------------------------------
    # Priority and conflict resolution
    # ------------------------------------------------------------------

    def prioritize_signals(
        self,
        packets: list[ExecutionPacket],
        launch_order: list[str] | None = None,
    ) -> list[ExecutionPacket]:
        """Sort packets by priority (P0 first) and apply conflict resolution.

        Conflict rules:
        1. Higher-priority lane wins on same market.
        2. Same-priority opposing signals on same market: both dropped,
           unless the packets are explicitly linked as a basket.
        3. Dedup: only one packet per (market_id, direction) unless linked.
        4. When launch_order is provided, its ordering takes precedence for
           the first-claim pass without changing the default desk policy.
        """
        sorted_packets = sorted(packets, key=lambda p: _launch_rank(p, launch_order))
        use_launch_order = bool(launch_order)

        # Track claimed markets: {market_id: (direction, claim_score, priority, packet_id, strategy_id)}
        claimed: dict[str, tuple[str, int, int, str, str]] = {}
        accepted: list[ExecutionPacket] = []
        dropped_ids: set[str] = set()
        shadow_alternatives: list[dict[str, Any]] = []

        for pkt in sorted_packets:
            mid = pkt.market_id
            pkt_rank = _launch_rank(pkt, launch_order)[0] if use_launch_order else pkt.priority
            if mid in claimed:
                prev_dir, prev_score, prev_pri, prev_id, prev_strategy_id = claimed[mid]

                # Same-score conflict with opposing direction: drop both,
                # unless the packets are explicitly linked as a basket pair.
                if prev_score == pkt_rank and prev_dir != pkt.direction:
                    linked_basket = prev_id in pkt.linked_packets
                    if linked_basket:
                        logger.info(
                            "Conflict: preserving linked basket pair %s and %s on market %s",
                            prev_id, pkt.packet_id, mid,
                        )
                        claimed[mid] = (pkt.direction, pkt_rank, pkt.priority, pkt.packet_id, pkt.strategy_id)
                        accepted.append(pkt)
                        shadow_alternatives.append({
                            "chosen_action": "linked_basket",
                            "rejected_actions": [],
                            "reason": "same_score_linked_opposing_preserved",
                            "market_id": mid,
                        })
                        continue

                    logger.info(
                        "Conflict: dropping both %s and %s on market %s (same score, opposing)",
                        prev_id, pkt.packet_id, mid,
                    )
                    dropped_ids.add(prev_id)
                    dropped_ids.add(pkt.packet_id)
                    shadow_alternatives.append({
                        "chosen_action": "none",
                        "rejected_actions": [
                            {
                                "packet_id": prev_id,
                                "strategy_id": prev_strategy_id,
                                "priority": prev_pri,
                                "direction": prev_dir,
                                "reason": "same_score_opposing",
                            },
                            {
                                "packet_id": pkt.packet_id,
                                "strategy_id": pkt.strategy_id,
                                "priority": pkt.priority,
                                "direction": pkt.direction,
                                "reason": "same_score_opposing",
                            },
                        ],
                        "reason": "same_score_opposing",
                        "market_id": mid,
                    })
                    continue

                # Earlier claim wins under the active ordering.
                if prev_score < pkt_rank:
                    logger.debug(
                        "Suppressed %s (P%d) on market %s — already claimed by %s",
                        pkt.packet_id, pkt.priority, mid, prev_id,
                    )
                    dropped_ids.add(pkt.packet_id)
                    shadow_alternatives.append({
                        "chosen_action": prev_id,
                        "rejected_actions": [
                            {
                                "packet_id": pkt.packet_id,
                                "strategy_id": pkt.strategy_id,
                                "priority": pkt.priority,
                                "direction": pkt.direction,
                                "reason": "later_claim_suppressed",
                            }
                        ],
                        "reason": "earlier_claim_wins",
                        "market_id": mid,
                    })
                    continue

                # Same score, same direction — keep the first packet.
                if prev_score == pkt_rank and prev_dir == pkt.direction:
                    dropped_ids.add(pkt.packet_id)
                    shadow_alternatives.append({
                        "chosen_action": prev_id,
                        "rejected_actions": [
                            {
                                "packet_id": pkt.packet_id,
                                "strategy_id": pkt.strategy_id,
                                "priority": pkt.priority,
                                "direction": pkt.direction,
                                "reason": "same_score_same_direction",
                            }
                        ],
                        "reason": "same_score_same_direction",
                        "market_id": mid,
                    })
                    continue

            claimed[mid] = (pkt.direction, pkt_rank, pkt.priority, pkt.packet_id, pkt.strategy_id)
            accepted.append(pkt)

        result = [p for p in accepted if p.packet_id not in dropped_ids]

        logger.info(
            "prioritize_signals: %d input -> %d accepted, %d dropped",
            len(packets), len(result), len(dropped_ids),
        )
        self._last_shadow_alternatives = shadow_alternatives
        return result

    # ------------------------------------------------------------------
    # Exposure checks
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Daily PnL demotion
    # ------------------------------------------------------------------

    def set_btc5_daily_pnl(
        self,
        *,
        et_day_pnl_usd: float = 0.0,
        rolling_24h_pnl_usd: float = 0.0,
    ) -> None:
        """Inject current BTC5 daily PnL for demotion checks.

        When BTC5 daily PnL is red beyond threshold, directional BTC5
        packets are suppressed and capital routes to structural lanes.
        """
        self._btc5_et_day_pnl = et_day_pnl_usd
        self._btc5_rolling_24h_pnl = rolling_24h_pnl_usd

    def is_btc5_demoted(self) -> tuple[bool, str]:
        """Check if BTC5 should be demoted due to daily PnL.

        Returns (demoted, reason).
        """
        threshold = self._config.get("btc5_daily_pnl_demotion_usd", -10.0)
        et_day = getattr(self, "_btc5_et_day_pnl", 0.0)
        rolling = getattr(self, "_btc5_rolling_24h_pnl", 0.0)

        if et_day < threshold:
            return True, f"btc5_et_day_pnl={et_day:.2f} < demotion_threshold={threshold}"
        if rolling < threshold:
            return True, f"btc5_rolling_24h_pnl={rolling:.2f} < demotion_threshold={threshold}"
        return False, ""

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

    def generate_packets(
        self,
        raw_packets: list[ExecutionPacket],
        launch_order: list[str] | None = None,
    ) -> list[ExecutionPacket]:
        """Full pipeline: prioritize, resolve conflicts, check exposure.

        Returns the final list of packets ready for execution.
        """
        prioritized = self.prioritize_signals(raw_packets, launch_order=launch_order)
        approved: list[ExecutionPacket] = []
        self._packet_approval_seq = {}

        # Check BTC5 daily PnL demotion
        btc5_demoted, btc5_demotion_reason = self.is_btc5_demoted()

        for pkt in prioritized:
            # Suppress directional BTC5 packets when demoted
            if btc5_demoted and pkt.strategy_id == "btc5":
                logger.info(
                    "BTC5 demoted — suppressing %s (%s): %s",
                    pkt.packet_id, pkt.direction, btc5_demotion_reason,
                )
                pkt.status = "rejected"
                self._rejections.append({
                    "packet_id": pkt.packet_id,
                    "reason": f"btc5_daily_pnl_demotion: {btc5_demotion_reason}",
                    "timestamp": time.time(),
                })
                if self._tape_writer is not None:
                    self._tape_writer.emit_decision(
                        "trade_rejected",
                        {
                            "packet_id": pkt.packet_id,
                            "strategy_id": pkt.strategy_id,
                            "reason": f"btc5_daily_pnl_demotion: {btc5_demotion_reason}",
                        },
                        correlation_id=pkt.packet_id,
                    )
                continue
            if self._tape_writer is not None:
                self._tape_writer.emit_decision(
                    "trade_proposed",
                    {
                        "packet_id": pkt.packet_id,
                        "strategy_id": pkt.strategy_id,
                        "market_id": pkt.market_id,
                        "platform": pkt.platform,
                        "direction": pkt.direction,
                        "size_usd": pkt.size_usd,
                        "edge_estimate": pkt.edge_estimate,
                        "confidence": pkt.confidence,
                        "priority": pkt.priority,
                        "order_type": pkt.order_type,
                        "linked_packets": list(pkt.linked_packets),
                        "metadata": dict(pkt.metadata),
                    },
                    correlation_id=pkt.packet_id,
                )
            allowed, reason = self.check_exposure(pkt)
            if allowed:
                approved.append(pkt)
                pkt.status = "pending"
                if self._tape_writer is not None:
                    evt = self._tape_writer.emit_decision(
                        "trade_approved",
                        {
                            "packet_id": pkt.packet_id,
                            "strategy_id": pkt.strategy_id,
                            "market_id": pkt.market_id,
                            "platform": pkt.platform,
                            "direction": pkt.direction,
                            "size_usd": pkt.size_usd,
                            "edge_estimate": pkt.edge_estimate,
                            "confidence": pkt.confidence,
                            "priority": pkt.priority,
                            "order_type": pkt.order_type,
                            "linked_packets": list(pkt.linked_packets),
                            "metadata": dict(pkt.metadata),
                            "reason": "exposure_ok",
                        },
                        causation_seq=None,
                        correlation_id=pkt.packet_id,
                    )
                    self._packet_approval_seq[pkt.packet_id] = evt.seq
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
                if self._tape_writer is not None:
                    self._tape_writer.emit_decision(
                        "trade_rejected",
                        {
                            "packet_id": pkt.packet_id,
                            "strategy_id": pkt.strategy_id,
                            "market_id": pkt.market_id,
                            "platform": pkt.platform,
                            "direction": pkt.direction,
                            "size_usd": pkt.size_usd,
                            "edge_estimate": pkt.edge_estimate,
                            "confidence": pkt.confidence,
                            "priority": pkt.priority,
                            "order_type": pkt.order_type,
                            "linked_packets": list(pkt.linked_packets),
                            "metadata": dict(pkt.metadata),
                            "reason": reason,
                        },
                        correlation_id=pkt.packet_id,
                    )

        self._active_packets = approved
        if self._tape_writer is not None:
            for alt in self._last_shadow_alternatives:
                self._tape_writer.emit_shadow_alternative(
                    chosen_action=str(alt.get("chosen_action", "")),
                    rejected_actions=list(alt.get("rejected_actions", [])),
                    reason=str(alt.get("reason", "")),
                    correlation_id=str(alt.get("market_id") or ""),
                    metadata={
                        "reason": alt.get("reason", ""),
                        "market_id": alt.get("market_id", ""),
                    },
                )
        return approved

    def _packet_to_order_payload(self, packet: ExecutionPacket) -> dict[str, Any]:
        """Translate a strike packet into the existing JJ Live order shape."""
        reference_price = float(
            packet.metadata.get(
                "reference_price",
                packet.metadata.get("midpoint", packet.metadata.get("best_bid", 0.5)),
            )
            or 0.5
        )
        order_size = round(packet.size_usd / max(reference_price, 0.01), 6)
        return {
            "signal": {
                "source": packet.strategy_id,
                "question": packet.metadata.get("question", packet.market_id),
                "direction": packet.direction,
                "edge": packet.edge_estimate,
                "confidence": packet.confidence,
                "priority": packet.priority,
                "packet_id": packet.packet_id,
            },
            "market_id": packet.market_id,
            "token_id": packet.token_id,
            "side": "BUY",
            "price": reference_price,
            "order_price": reference_price,
            "order_size": order_size,
            "size_usd": packet.size_usd,
            "category": packet.strategy_id,
            "trade_record": {
                "source": packet.strategy_id,
                "source_combo": packet.metadata.get("source_combo", packet.strategy_id),
                "source_components": list(packet.metadata.get("source_components", [])),
                "source_count": int(packet.metadata.get("source_count", 1) or 1),
                "signal_sources": list(packet.metadata.get("signal_sources", [packet.strategy_id])),
                "signal_metadata": dict(packet.metadata),
                "packet_id": packet.packet_id,
            },
            "order_metadata": {
                "packet_id": packet.packet_id,
                "strategy_id": packet.strategy_id,
                "market_id": packet.market_id,
                "priority": packet.priority,
                "order_type": packet.order_type,
                "ttl_seconds": packet.ttl_seconds,
                "max_slippage": packet.max_slippage,
                "linked_packets": list(packet.linked_packets),
                "reference_price": reference_price,
                "execution_style": "maker_first",
                "cancel_discipline": "deadline_cancel",
            },
        }

    async def execute_queue(
        self,
        packets: list[ExecutionPacket],
        executor: Any | None = None,
        *,
        tape_writer: Any | None = None,
        allow_taker_fallback: bool = False,
    ) -> dict[str, Any]:
        """Submit packets through the existing execution path in priority order."""
        tape = tape_writer or self._tape_writer
        summary = {
            "submitted": 0,
            "filled": 0,
            "rejected": 0,
            "cancelled": 0,
            "abandoned": 0,
            "abandoned_reason_taxonomy": {},
            "tape_events": 0,
        }

        if executor is None:
            summary["abandoned"] = len(packets)
            summary["abandoned_reason_taxonomy"] = {
                "shadow_no_executor": len(packets),
            }
            return summary

        place_order = getattr(executor, "place_order", executor)
        if not callable(place_order):
            raise TypeError("executor must be callable or expose place_order()")

        for packet in packets:
            payload = self._packet_to_order_payload(packet)
            approval_seq = self._packet_approval_seq.get(packet.packet_id)
            if tape is not None:
                tape.emit_execution(
                    "order_placed",
                    {
                        "packet_id": packet.packet_id,
                        "strategy_id": packet.strategy_id,
                        "market_id": packet.market_id,
                        "priority": packet.priority,
                        "order_type": packet.order_type,
                        "execution_style": "maker_first",
                        "allow_taker_fallback": allow_taker_fallback,
                        "payload": payload,
                    },
                    causation_seq=approval_seq,
                    correlation_id=packet.packet_id,
                )
                summary["tape_events"] += 1

            try:
                result = place_order(**payload)
                if inspect.isawaitable(result):
                    result = await result
            except Exception as exc:
                packet.status = "rejected"
                self._rejections.append({
                    "packet_id": packet.packet_id,
                    "reason": f"execution_error: {exc}",
                    "timestamp": time.time(),
                })
                summary["rejected"] += 1
                if tape is not None:
                    tape.emit_execution(
                        "order_status_changed",
                        {
                            "packet_id": packet.packet_id,
                            "strategy_id": packet.strategy_id,
                            "market_id": packet.market_id,
                            "status": "rejected",
                            "reason": f"execution_error: {exc}",
                        },
                        causation_seq=approval_seq,
                        correlation_id=packet.packet_id,
                    )
                    summary["tape_events"] += 1
                continue

            status = "submitted"
            filled = False
            fallback_used = False
            if isinstance(result, dict):
                status = str(result.get("status", status) or status)
                filled = bool(result.get("filled")) or status == "filled"
            elif isinstance(result, bool):
                filled = result
                status = "filled" if result else "rejected"
            elif result is None:
                status = "submitted"

            if (
                not filled
                and allow_taker_fallback
                and packet.priority <= PRIORITY_RESOLUTION
            ):
                fallback_payload = {
                    **payload,
                    "signal": {**payload["signal"], "execution_style": "taker"},
                    "order_metadata": {
                        **payload["order_metadata"],
                        "execution_style": "taker",
                    },
                }
                if tape is not None:
                    tape.emit_execution(
                        "order_placed",
                        {
                            "packet_id": packet.packet_id,
                            "strategy_id": packet.strategy_id,
                            "market_id": packet.market_id,
                            "priority": packet.priority,
                            "order_type": "taker",
                            "execution_style": "taker",
                            "allow_taker_fallback": True,
                            "payload": fallback_payload,
                        },
                        causation_seq=approval_seq,
                        correlation_id=packet.packet_id,
                    )
                    summary["tape_events"] += 1
                try:
                    fallback_result = place_order(**fallback_payload)
                    if inspect.isawaitable(fallback_result):
                        fallback_result = await fallback_result
                except Exception as exc:
                    status = f"taker_fallback_error: {exc}"
                else:
                    fallback_used = True
                    result = fallback_result
                    if isinstance(fallback_result, dict):
                        status = str(fallback_result.get("status", "submitted") or "submitted")
                        filled = bool(fallback_result.get("filled")) or status == "filled"
                    elif isinstance(fallback_result, bool):
                        filled = fallback_result
                        status = "filled" if fallback_result else "rejected"
                    elif fallback_result is None:
                        status = "submitted"

            rejected = status in {"rejected", "failed", "error"} or status.startswith("taker_fallback_error")
            if rejected and not filled:
                packet.status = "rejected"
                summary["rejected"] += 1
            else:
                packet.status = "filled" if filled else "pending"

            summary["submitted"] += 1
            self._execution_log.append({
                "packet_id": packet.packet_id,
                "strategy_id": packet.strategy_id,
                "market_id": packet.market_id,
                "status": status,
                "fallback_used": fallback_used,
                "timestamp": time.time(),
            })

            if tape is not None:
                if filled:
                    tape.emit_execution(
                        "order_filled",
                        {
                            "packet_id": packet.packet_id,
                            "strategy_id": packet.strategy_id,
                            "market_id": packet.market_id,
                            "fill_size_usd": packet.size_usd,
                            "fill_price": payload["price"],
                            "status": "filled",
                            "fallback_used": fallback_used,
                        },
                        causation_seq=approval_seq,
                        correlation_id=packet.packet_id,
                    )
                    summary["filled"] += 1
                    self.record_fill(packet, fill_price=payload["price"])
                    summary["tape_events"] += 1
                elif rejected:
                    tape.emit_execution(
                        "order_status_changed",
                        {
                            "packet_id": packet.packet_id,
                            "strategy_id": packet.strategy_id,
                            "market_id": packet.market_id,
                            "status": "rejected",
                            "execution_style": "maker_first",
                            "fallback_used": fallback_used,
                        },
                        causation_seq=approval_seq,
                        correlation_id=packet.packet_id,
                    )
                    summary["tape_events"] += 1
                else:
                    tape.emit_execution(
                        "order_status_changed",
                        {
                            "packet_id": packet.packet_id,
                            "strategy_id": packet.strategy_id,
                            "market_id": packet.market_id,
                            "status": status,
                            "execution_style": "maker_first",
                            "fallback_used": fallback_used,
                        },
                        causation_seq=approval_seq,
                        correlation_id=packet.packet_id,
                    )
                    summary["tape_events"] += 1

        return summary

    async def run_cycle(
        self,
        *,
        executor: Any | None = None,
        tape_writer: Any | None = None,
        allow_taker_fallback: bool = False,
        launch_order: list[str] | None = None,
        neg_risk_data: Any = None,
        whale_signals: Optional[list] = None,
        sniper_markets: Optional[list[dict]] = None,
        cross_plat_poly: Optional[list] = None,
        cross_plat_kalshi: Optional[list] = None,
        tournament_questions: Optional[list[dict]] = None,
        leader_follower_data: Optional[dict] = None,
        dual_sided_snapshots: Optional[list] = None,
    ) -> dict[str, Any]:
        """Run one strike-desk cycle from scan to execution."""
        if tape_writer is not None:
            self._tape_writer = tape_writer
        raw_packets = await self.scan_all_lanes(
            neg_risk_data=neg_risk_data,
            whale_signals=whale_signals,
            sniper_markets=sniper_markets,
            cross_plat_poly=cross_plat_poly,
            cross_plat_kalshi=cross_plat_kalshi,
            tournament_questions=tournament_questions,
            leader_follower_data=leader_follower_data,
            dual_sided_snapshots=dual_sided_snapshots,
        )
        approved_packets = self.generate_packets(raw_packets, launch_order=launch_order)
        execution_summary = await self.execute_queue(
            approved_packets,
            executor=executor,
            tape_writer=tape_writer,
            allow_taker_fallback=allow_taker_fallback,
        )
        return {
            "raw_packets": [pkt.to_dict() for pkt in raw_packets],
            "approved_packets": [pkt.to_dict() for pkt in approved_packets],
            "execution_summary": execution_summary,
            "diagnostics": self.get_diagnostics(),
            "shadow_alternatives": list(self._last_shadow_alternatives),
        }

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
            "spread_capture": self._spread_capture is not None,
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
