#!/usr/bin/env python3
"""
Capital Router — Structural Priority Enforcement for JJ
========================================================
Routes capital across strategy lanes with structural alpha first,
directional betting last. Born from the March 22 lesson: predicting
BTC direction is a losing game at our scale. Resolution sniping,
neg-risk arbitrage, and dual-sided pairs don't need direction.

Lane priority (P0 = highest):
  P0  neg_risk           — guaranteed-profit baskets (no direction needed)
  P1  cross_plat         — cross-platform arbitrage
  P2  resolution_sniper  — known-outcome resolution sniping
  P3  dual_sided_pair    — buy both sides below $0.97 combined
  P4  whale_copy         — consensus copy-trade signals
  P5  semantic_lead_lag  — statistical lead-lag signals
  P6  llm_tournament     — LLM consensus-divergence (disabled: cost per signal)
  P7  directional_btc5   — FROZEN until promotion gate passes

Design:
  - Allocation is proportional to max_capital_pct among enabled lanes
  - Frozen lanes get zero capital regardless of config
  - Directional BTC5 requires explicit promotion gate pass to unfreeze
  - All state changes logged for audit trail

Author: JJ (autonomous)
Date: 2026-03-22
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Optional

logger = logging.getLogger("JJ.capital_router")


# ---------------------------------------------------------------------------
# Re-export PromotionStage for convenience; fall back to local definition
# ---------------------------------------------------------------------------

try:
    from bot.promotion_manager import PromotionStage
except ImportError:
    try:
        from promotion_manager import PromotionStage  # type: ignore
    except ImportError:

        class PromotionStage(IntEnum):  # type: ignore[no-redef]
            HYPOTHESIS = 0
            BACKTESTED = 1
            SHADOW = 2
            MICRO_LIVE = 3
            SEED = 4
            SCALE = 5
            CORE = 6


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class LaneConfig:
    """Configuration for a single capital lane."""

    lane_name: str
    priority: int                       # P0 (highest) to P7 (lowest)
    enabled: bool = True
    max_capital_pct: float = 0.10       # Max fraction of total capital
    min_edge: float = 0.01             # Minimum edge to deploy
    order_type: str = "maker"          # "maker" or "taker"
    stage: int = 0                     # PromotionStage value

    # Dual-sided pair specific (ignored for other lanes)
    combined_cost_cap: float = 0.97
    reserve_pct: float = 0.20
    per_market_cap_usd: float = 10.0
    max_markets: int = 6

    def __post_init__(self) -> None:
        if self.priority < 0 or self.priority > 7:
            raise ValueError(f"Priority must be 0-7, got {self.priority}")
        if self.max_capital_pct < 0.0 or self.max_capital_pct > 1.0:
            raise ValueError(f"max_capital_pct must be 0.0-1.0, got {self.max_capital_pct}")
        if self.order_type not in ("maker", "taker"):
            raise ValueError(f"order_type must be 'maker' or 'taker', got {self.order_type}")


@dataclass
class FreezeRecord:
    """Audit record for lane freeze/unfreeze events."""

    lane_name: str
    action: str          # "freeze" or "unfreeze"
    reason: str
    timestamp: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Default lane configurations
# ---------------------------------------------------------------------------

def _default_lane_configs() -> list[LaneConfig]:
    """Return the default lane configuration — structural first, directional last."""
    return [
        LaneConfig(
            lane_name="neg_risk",
            priority=0,
            enabled=True,
            max_capital_pct=0.15,
            min_edge=0.005,
            order_type="maker",
            stage=int(PromotionStage.MICRO_LIVE),
        ),
        LaneConfig(
            lane_name="cross_plat",
            priority=1,
            enabled=True,
            max_capital_pct=0.12,
            min_edge=0.008,
            order_type="maker",
            stage=int(PromotionStage.SHADOW),
        ),
        LaneConfig(
            lane_name="resolution_sniper",
            priority=2,
            enabled=True,
            max_capital_pct=0.20,
            min_edge=0.01,
            order_type="maker",
            stage=int(PromotionStage.MICRO_LIVE),
        ),
        LaneConfig(
            lane_name="dual_sided_pair",
            priority=3,
            enabled=True,
            max_capital_pct=0.15,
            min_edge=0.01,
            order_type="maker",
            stage=int(PromotionStage.SHADOW),
            combined_cost_cap=0.97,
            reserve_pct=0.20,
            per_market_cap_usd=10.0,
            max_markets=6,
        ),
        LaneConfig(
            lane_name="whale_copy",
            priority=4,
            enabled=True,
            max_capital_pct=0.10,
            min_edge=0.02,
            order_type="maker",
            stage=int(PromotionStage.SHADOW),
        ),
        LaneConfig(
            lane_name="semantic_lead_lag",
            priority=5,
            enabled=True,
            max_capital_pct=0.10,
            min_edge=0.02,
            order_type="maker",
            stage=int(PromotionStage.HYPOTHESIS),
        ),
        LaneConfig(
            lane_name="llm_tournament",
            priority=6,
            enabled=False,  # Too expensive per signal for now
            max_capital_pct=0.08,
            min_edge=0.03,
            order_type="maker",
            stage=int(PromotionStage.HYPOTHESIS),
        ),
        LaneConfig(
            lane_name="directional_btc5",
            priority=7,
            enabled=False,  # FROZEN — lost money March 22 predicting BTC direction
            max_capital_pct=0.10,
            min_edge=0.03,
            order_type="maker",
            stage=int(PromotionStage.HYPOTHESIS),
        ),
    ]


# ---------------------------------------------------------------------------
# Capital Router
# ---------------------------------------------------------------------------


class CapitalRouter:
    """Routes capital across strategy lanes, enforcing structural priority.

    Structural edges (resolution sniping, neg-risk, dual-sided pairs) get
    capital before any directional bet. Directional BTC5 is frozen by default
    and requires explicit promotion gate pass to re-enter micro-live.
    """

    def __init__(
        self,
        total_capital: float,
        config: Optional[list[LaneConfig]] = None,
    ) -> None:
        self.total_capital = max(total_capital, 0.0)
        self._lanes: dict[str, LaneConfig] = {}
        self._freeze_log: list[FreezeRecord] = []

        for lc in (config or _default_lane_configs()):
            self._lanes[lc.lane_name] = lc

        enabled_count = sum(1 for lc in self._lanes.values() if lc.enabled)
        frozen_count = sum(1 for lc in self._lanes.values() if not lc.enabled)
        logger.info(
            "Capital router initialized: $%.2f total, %d lanes (%d enabled, %d frozen)",
            self.total_capital,
            len(self._lanes),
            enabled_count,
            frozen_count,
        )

    # -- Query methods -------------------------------------------------------

    def get_lane_budget(self, lane_name: str) -> float:
        """Return dollar budget for a lane. Zero if disabled or unknown."""
        lc = self._lanes.get(lane_name)
        if lc is None or not lc.enabled:
            return 0.0
        return self.total_capital * lc.max_capital_pct

    def is_lane_enabled(self, lane_name: str) -> bool:
        """Return True if the lane exists and is enabled."""
        lc = self._lanes.get(lane_name)
        return lc is not None and lc.enabled

    def get_lane_config(self, lane_name: str) -> Optional[LaneConfig]:
        """Return LaneConfig for a lane, or None if unknown."""
        return self._lanes.get(lane_name)

    # -- Freeze / unfreeze ---------------------------------------------------

    def freeze_lane(self, lane_name: str, reason: str) -> None:
        """Disable a lane with a logged reason."""
        lc = self._lanes.get(lane_name)
        if lc is None:
            logger.warning("Cannot freeze unknown lane: %s", lane_name)
            return
        if not lc.enabled:
            logger.debug("Lane %s already frozen", lane_name)
            return
        lc.enabled = False
        record = FreezeRecord(lane_name=lane_name, action="freeze", reason=reason)
        self._freeze_log.append(record)
        logger.info("LANE FROZEN: %s — %s", lane_name, reason)

    def unfreeze_lane(self, lane_name: str) -> None:
        """Re-enable a lane. Caller is responsible for verifying promotion gate."""
        lc = self._lanes.get(lane_name)
        if lc is None:
            logger.warning("Cannot unfreeze unknown lane: %s", lane_name)
            return
        if lc.enabled:
            logger.debug("Lane %s already active", lane_name)
            return
        lc.enabled = True
        record = FreezeRecord(lane_name=lane_name, action="unfreeze", reason="promotion_gate_passed")
        self._freeze_log.append(record)
        logger.info("LANE UNFROZEN: %s", lane_name)

    # -- Routing table -------------------------------------------------------

    def get_routing_table(self) -> list[dict[str, Any]]:
        """Return sorted routing table for display/logging."""
        rows = []
        for lc in sorted(self._lanes.values(), key=lambda x: x.priority):
            rows.append({
                "lane": lc.lane_name,
                "priority": f"P{lc.priority}",
                "enabled": lc.enabled,
                "max_capital_pct": lc.max_capital_pct,
                "budget_usd": self.total_capital * lc.max_capital_pct if lc.enabled else 0.0,
                "min_edge": lc.min_edge,
                "order_type": lc.order_type,
                "stage": lc.stage,
            })
        return rows

    # -- Capital allocation --------------------------------------------------

    def allocate(self, total_capital: float) -> dict[str, float]:
        """Distribute capital across enabled lanes, proportional to max_capital_pct.

        Updates internal total_capital and returns {lane_name: dollar_budget}.
        Allocations are capped at max_capital_pct * total_capital per lane.
        If sum of max_capital_pct for enabled lanes exceeds 1.0, each lane
        gets its proportional share of the available capital.
        """
        self.total_capital = max(total_capital, 0.0)
        if self.total_capital == 0.0:
            return {lc.lane_name: 0.0 for lc in self._lanes.values()}

        enabled = {
            name: lc for name, lc in self._lanes.items() if lc.enabled
        }

        if not enabled:
            logger.warning("All lanes frozen — zero allocation")
            return {lc.lane_name: 0.0 for lc in self._lanes.values()}

        total_pct = sum(lc.max_capital_pct for lc in enabled.values())
        allocation: dict[str, float] = {}

        for name, lc in self._lanes.items():
            if not lc.enabled:
                allocation[name] = 0.0
            elif total_pct <= 1.0:
                # Under-allocated: each lane gets its full max_capital_pct
                allocation[name] = self.total_capital * lc.max_capital_pct
            else:
                # Over-allocated: scale proportionally
                share = lc.max_capital_pct / total_pct
                allocation[name] = self.total_capital * share

        return allocation

    # -- Directional block ---------------------------------------------------

    def should_block_directional(self, btc5_promotion_passed: bool = False) -> bool:
        """Return True if directional BTC5 should be blocked.

        Directional trades are blocked unless:
        1. The promotion gate has explicitly passed, AND
        2. The lane is currently enabled
        """
        if btc5_promotion_passed and self.is_lane_enabled("directional_btc5"):
            return False
        return True

    # -- Freeze log ----------------------------------------------------------

    def get_freeze_log(self) -> list[dict[str, Any]]:
        """Return freeze/unfreeze history for audit."""
        return [
            {
                "lane": r.lane_name,
                "action": r.action,
                "reason": r.reason,
                "timestamp": r.timestamp,
            }
            for r in self._freeze_log
        ]

    # -- Repr ----------------------------------------------------------------

    def __repr__(self) -> str:
        enabled = sum(1 for lc in self._lanes.values() if lc.enabled)
        return (
            f"CapitalRouter(capital=${self.total_capital:.2f}, "
            f"lanes={len(self._lanes)}, enabled={enabled})"
        )
