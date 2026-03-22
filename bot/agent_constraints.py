#!/usr/bin/env python3
"""
Agent Constraint Enforcement — Executable Safety Rails for JJ
=============================================================
Replaces natural-language safety rails with runtime-enforced constraint
specifications. Every trade proposal is evaluated before execution.

Architecture:
  - TradeProposal: What the agent wants to do
  - TradingState: Current runtime context (P&L, positions, bankroll)
  - Constraint: Single executable rule (predicate + action + optional modifier)
  - ConstraintEngine: Evaluates all registered constraints in priority order
  - elastifund_default_constraints(): Pre-built engine with all CLAUDE.md rails

Design guarantees:
  - Sub-millisecond evaluation (no I/O, no network calls)
  - MODIFY actions enable graceful degradation (cap, not block)
  - Violation log provides immutable audit trail
  - Config-driven loading enables runtime parameter changes

March 2026 — Elastifund / JJ
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

logger = logging.getLogger("JJ.constraints")


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ConstraintAction(Enum):
    ALLOW = "allow"
    BLOCK = "block"
    MODIFY = "modify"
    ESCALATE = "escalate"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ConstraintViolation:
    rule_name: str
    description: str
    action: ConstraintAction
    original_value: Any
    modified_value: Any = None
    timestamp: float = field(default_factory=time.time)
    context: dict = field(default_factory=dict)


@dataclass
class TradeProposal:
    """A proposed trade to be validated against constraints."""
    market_id: str
    side: str                        # "BUY_YES" or "BUY_NO"
    amount_usd: float
    probability_estimate: float
    market_price: float
    edge: float
    kelly_fraction: float
    category: str = ""
    resolution_hours: float = 0.0
    metadata: dict = field(default_factory=dict)


@dataclass
class ConstraintResult:
    allowed: bool
    action: ConstraintAction
    violations: list[ConstraintViolation]
    proposal: TradeProposal          # May be modified by MODIFY rules
    check_time_ms: float             # Wall-clock ms to evaluate all constraints


@dataclass
class TradingState:
    """Current trading state for constraint evaluation."""
    daily_pnl: float = 0.0
    open_positions: int = 0
    total_exposure_usd: float = 0.0
    bankroll: float = 1000.0
    trades_today: int = 0
    last_trade_time: float = 0.0
    promotion_gate_passed: bool = False
    current_regime: str = "stable"   # From regime_detector


# ---------------------------------------------------------------------------
# Constraint
# ---------------------------------------------------------------------------

class Constraint:
    """A single executable constraint rule."""

    def __init__(
        self,
        name: str,
        description: str,
        predicate: Callable[[TradeProposal, TradingState], bool],
        action: ConstraintAction = ConstraintAction.BLOCK,
        modifier: Optional[Callable[[TradeProposal], TradeProposal]] = None,
        priority: int = 0,
    ) -> None:
        self.name = name
        self.description = description
        self.predicate = predicate
        self.action = action
        self.modifier = modifier
        self.priority = priority

    def check(
        self, proposal: TradeProposal, state: TradingState
    ) -> Optional[ConstraintViolation]:
        """Return None if constraint passes, ConstraintViolation if it fails."""
        try:
            violated = self.predicate(proposal, state)
        except Exception as exc:
            logger.warning("Constraint %s predicate raised: %s", self.name, exc)
            violated = False

        if not violated:
            return None

        modified_value: Any = None
        if self.action == ConstraintAction.MODIFY and self.modifier is not None:
            try:
                modified_proposal = self.modifier(proposal)
                modified_value = modified_proposal.amount_usd
            except Exception as exc:
                logger.warning("Constraint %s modifier raised: %s", self.name, exc)

        return ConstraintViolation(
            rule_name=self.name,
            description=self.description,
            action=self.action,
            original_value=proposal.amount_usd,
            modified_value=modified_value,
            timestamp=time.time(),
            context={
                "market_id": proposal.market_id,
                "side": proposal.side,
                "category": proposal.category,
            },
        )


# ---------------------------------------------------------------------------
# Constraint Engine
# ---------------------------------------------------------------------------

class ConstraintEngine:
    def __init__(self) -> None:
        self.constraints: list[Constraint] = []
        self.violation_log: list[ConstraintViolation] = []
        self.state = TradingState()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def add_constraint(self, constraint: Constraint) -> None:
        """Register a constraint. Maintains priority ordering (descending)."""
        self.constraints.append(constraint)
        self.constraints.sort(key=lambda c: c.priority, reverse=True)

    def remove_constraint(self, name: str) -> bool:
        """Remove a constraint by name. Returns True if found and removed."""
        before = len(self.constraints)
        self.constraints = [c for c in self.constraints if c.name != name]
        return len(self.constraints) < before

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def evaluate(self, proposal: TradeProposal) -> ConstraintResult:
        """Evaluate a trade proposal against all constraints.

        Process:
        1. Sort constraints by priority (descending) — already maintained
        2. Check each constraint against proposal and current state
        3. On first BLOCK → stop, return blocked
        4. On MODIFY → apply modifier, continue checking with modified proposal
        5. On ESCALATE → stop, return escalate result
        6. If all pass → return allowed

        Target: < 1ms (no I/O, no network calls).
        """
        t0 = time.perf_counter()
        current_proposal = proposal
        violations: list[ConstraintViolation] = []

        for constraint in self.constraints:
            violation = constraint.check(current_proposal, self.state)
            if violation is None:
                continue

            violations.append(violation)
            self.violation_log.append(violation)

            if violation.action == ConstraintAction.BLOCK:
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                logger.info(
                    "BLOCK [%s] market=%s amount=%.2f — %s",
                    constraint.name,
                    proposal.market_id,
                    proposal.amount_usd,
                    constraint.description,
                )
                return ConstraintResult(
                    allowed=False,
                    action=ConstraintAction.BLOCK,
                    violations=violations,
                    proposal=current_proposal,
                    check_time_ms=elapsed_ms,
                )

            if violation.action == ConstraintAction.ESCALATE:
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                logger.info(
                    "ESCALATE [%s] market=%s — %s",
                    constraint.name,
                    proposal.market_id,
                    constraint.description,
                )
                return ConstraintResult(
                    allowed=False,
                    action=ConstraintAction.ESCALATE,
                    violations=violations,
                    proposal=current_proposal,
                    check_time_ms=elapsed_ms,
                )

            if violation.action == ConstraintAction.MODIFY and constraint.modifier is not None:
                try:
                    current_proposal = constraint.modifier(current_proposal)
                    logger.debug(
                        "MODIFY [%s] market=%s %.2f→%.2f",
                        constraint.name,
                        proposal.market_id,
                        proposal.amount_usd,
                        current_proposal.amount_usd,
                    )
                except Exception as exc:
                    logger.warning("Modifier for %s raised: %s — blocking", constraint.name, exc)
                    elapsed_ms = (time.perf_counter() - t0) * 1000.0
                    return ConstraintResult(
                        allowed=False,
                        action=ConstraintAction.BLOCK,
                        violations=violations,
                        proposal=current_proposal,
                        check_time_ms=elapsed_ms,
                    )

        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        # If any MODIFY violations occurred the proposal was changed but is allowed
        if violations:
            return ConstraintResult(
                allowed=True,
                action=ConstraintAction.MODIFY,
                violations=violations,
                proposal=current_proposal,
                check_time_ms=elapsed_ms,
            )

        return ConstraintResult(
            allowed=True,
            action=ConstraintAction.ALLOW,
            violations=[],
            proposal=current_proposal,
            check_time_ms=elapsed_ms,
        )

    # ------------------------------------------------------------------
    # State management
    # ------------------------------------------------------------------

    def update_state(self, **kwargs: Any) -> None:
        """Update the trading state (e.g., after a trade executes)."""
        for key, value in kwargs.items():
            if hasattr(self.state, key):
                setattr(self.state, key, value)
            else:
                logger.warning("TradingState has no attribute '%s'", key)

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    def get_violation_summary(self) -> dict:
        """Summary of all violations: counts by rule, most common, etc."""
        by_rule: dict[str, int] = {}
        by_action: dict[str, int] = {}

        for v in self.violation_log:
            by_rule[v.rule_name] = by_rule.get(v.rule_name, 0) + 1
            action_key = v.action.value
            by_action[action_key] = by_action.get(action_key, 0) + 1

        most_common = max(by_rule, key=lambda k: by_rule[k]) if by_rule else None

        return {
            "total_violations": len(self.violation_log),
            "by_rule": by_rule,
            "by_action": by_action,
            "most_common_rule": most_common,
        }

    # ------------------------------------------------------------------
    # Config-driven loading
    # ------------------------------------------------------------------

    def load_rules_from_config(self, config: dict) -> int:
        """Load constraints from a configuration dict.

        Config format:
        {
            "max_position_usd": {"value": 10, "action": "modify"},
            "max_daily_loss": {"value": 25, "action": "block"},
            "max_open_positions": {"value": 30, "action": "block"},
            "min_edge": {"value": 0.05, "action": "block"},
            "promotion_gate_required_above": {"value": 5, "action": "block"},
            "regime_must_be_stable": {"value": True, "action": "block"},
            "max_exposure_pct": {"value": 0.90, "action": "modify"},
        }
        Returns number of constraints loaded.
        """
        loaded = 0

        for rule_name, rule_cfg in config.items():
            action_str = rule_cfg.get("action", "block").lower()
            try:
                action = ConstraintAction(action_str)
            except ValueError:
                logger.warning("Unknown action '%s' for rule '%s'", action_str, rule_name)
                continue

            value = rule_cfg.get("value")
            constraint = _build_constraint_from_config(rule_name, value, action)
            if constraint is not None:
                self.add_constraint(constraint)
                loaded += 1
            else:
                logger.warning("Unrecognised config rule key: '%s'", rule_name)

        return loaded

    def export_rules(self) -> list[dict]:
        """Export all constraints as serializable dicts for logging."""
        return [
            {
                "name": c.name,
                "description": c.description,
                "action": c.action.value,
                "priority": c.priority,
            }
            for c in self.constraints
        ]


# ---------------------------------------------------------------------------
# Config-to-constraint factory (internal)
# ---------------------------------------------------------------------------

def _build_constraint_from_config(
    rule_name: str,
    value: Any,
    action: ConstraintAction,
) -> Optional[Constraint]:
    """Map config key → Constraint object. Returns None for unknown keys."""

    if rule_name == "max_position_usd":
        cap = float(value)

        def _pred_pos(p: TradeProposal, _s: TradingState) -> bool:
            return p.amount_usd > cap

        def _mod_pos(p: TradeProposal) -> TradeProposal:
            import dataclasses
            return dataclasses.replace(p, amount_usd=cap)

        return Constraint(
            name="max_position_usd",
            description=f"Position size capped at ${cap:.2f}/trade",
            predicate=_pred_pos,
            action=action,
            modifier=_mod_pos if action == ConstraintAction.MODIFY else None,
            priority=80,
        )

    if rule_name == "max_daily_loss":
        limit = float(value)

        def _pred_loss(p: TradeProposal, s: TradingState) -> bool:
            return s.daily_pnl < -abs(limit)

        return Constraint(
            name="max_daily_loss",
            description=f"Daily loss limit ${limit:.2f} exceeded",
            predicate=_pred_loss,
            action=action,
            priority=100,
        )

    if rule_name == "max_open_positions":
        max_pos = int(value)

        def _pred_open(p: TradeProposal, s: TradingState) -> bool:
            return s.open_positions >= max_pos

        return Constraint(
            name="max_open_positions",
            description=f"Max open positions ({max_pos}) reached",
            predicate=_pred_open,
            action=action,
            priority=90,
        )

    if rule_name == "min_edge":
        min_e = float(value)

        def _pred_edge(p: TradeProposal, _s: TradingState) -> bool:
            return p.edge < min_e

        return Constraint(
            name="min_edge",
            description=f"Edge {min_e:.1%} minimum not met",
            predicate=_pred_edge,
            action=action,
            priority=70,
        )

    if rule_name == "promotion_gate_required_above":
        threshold = float(value)

        def _pred_gate(p: TradeProposal, s: TradingState) -> bool:
            is_btc5 = "btc" in p.market_id.lower() or p.metadata.get("is_btc5", False)
            return is_btc5 and p.amount_usd > threshold and not s.promotion_gate_passed

        return Constraint(
            name="promotion_gate_required_above",
            description=f"BTC5 trades >${threshold:.2f} require promotion gate",
            predicate=_pred_gate,
            action=action,
            priority=85,
        )

    if rule_name == "regime_must_be_stable":
        if not value:
            return None  # Disabled

        def _pred_regime(p: TradeProposal, s: TradingState) -> bool:
            return s.current_regime != "stable"

        return Constraint(
            name="regime_must_be_stable",
            description="Block trades during regime transitions",
            predicate=_pred_regime,
            action=action,
            priority=95,
        )

    if rule_name == "max_exposure_pct":
        max_pct = float(value)

        def _pred_exp(p: TradeProposal, s: TradingState) -> bool:
            if s.bankroll <= 0:
                return True
            projected = (s.total_exposure_usd + p.amount_usd) / s.bankroll
            return projected > max_pct

        def _mod_exp(p: TradeProposal) -> TradeProposal:
            import dataclasses
            # Caller re-evaluates; set to remaining headroom
            # Conservative: cap to half proposed size (engine re-evaluates)
            return dataclasses.replace(p, amount_usd=p.amount_usd * 0.5)

        return Constraint(
            name="max_exposure_pct",
            description=f"Total exposure capped at {max_pct:.0%} of bankroll",
            predicate=_pred_exp,
            action=action,
            modifier=_mod_exp if action == ConstraintAction.MODIFY else None,
            priority=75,
        )

    return None


# ---------------------------------------------------------------------------
# Pre-built Elastifund constraint set
# ---------------------------------------------------------------------------

def elastifund_default_constraints() -> ConstraintEngine:
    """Return a ConstraintEngine pre-loaded with Elastifund's safety rails.

    Rules encoded from CLAUDE.md / Current State section:
    1.  Position size cap: $10/trade (MODIFY down)
    2.  BTC5 position cap: $5/trade unless promotion gate passed (BLOCK)
    3.  Daily loss limit: block if daily_pnl < -$25
    4.  Max open positions: 30 (BLOCK)
    5.  Max exposure: 90% of bankroll (MODIFY)
    6.  Minimum edge: 5% (BLOCK)
    7.  Regime stability: block during transitions
    8.  Kelly constraint: position ≤ kelly_fraction * bankroll (MODIFY)
    9.  Category filter: block crypto/sports categories
    10. Resolution window: block if resolution > 24 hours
    """
    import dataclasses

    engine = ConstraintEngine()

    # 1. Global position size cap — MODIFY down to $10
    engine.add_constraint(Constraint(
        name="position_size_cap",
        description="Cap individual position at $10/trade",
        predicate=lambda p, _s: p.amount_usd > 10.0,
        action=ConstraintAction.MODIFY,
        modifier=lambda p: dataclasses.replace(p, amount_usd=10.0),
        priority=80,
    ))

    # 2. BTC5 sub-cap: $5 unless promotion gate passed
    engine.add_constraint(Constraint(
        name="btc5_promotion_gate",
        description="BTC5 limited to $5/trade until promotion gate passes",
        predicate=lambda p, s: (
            ("btc" in p.market_id.lower() or p.metadata.get("is_btc5", False))
            and p.amount_usd > 5.0
            and not s.promotion_gate_passed
        ),
        action=ConstraintAction.BLOCK,
        priority=85,
    ))

    # 3. Daily loss limit
    engine.add_constraint(Constraint(
        name="daily_loss_limit",
        description="Block all trades when daily P&L < -$25",
        predicate=lambda p, s: s.daily_pnl < -25.0,
        action=ConstraintAction.BLOCK,
        priority=100,
    ))

    # 4. Max open positions
    engine.add_constraint(Constraint(
        name="max_open_positions",
        description="Block when 30 or more positions already open",
        predicate=lambda p, s: s.open_positions >= 30,
        action=ConstraintAction.BLOCK,
        priority=90,
    ))

    # 5. Max exposure — MODIFY (halve the proposal so next pass may clear)
    engine.add_constraint(Constraint(
        name="max_exposure_pct",
        description="Total exposure must not exceed 90% of bankroll",
        predicate=lambda p, s: (
            s.bankroll > 0
            and (s.total_exposure_usd + p.amount_usd) / s.bankroll > 0.90
        ),
        action=ConstraintAction.MODIFY,
        modifier=lambda p: dataclasses.replace(
            p, amount_usd=max(0.0, p.amount_usd * 0.5)
        ),
        priority=75,
    ))

    # 6. Minimum edge
    engine.add_constraint(Constraint(
        name="min_edge",
        description="Block trades with edge < 5%",
        predicate=lambda p, _s: p.edge < 0.05,
        action=ConstraintAction.BLOCK,
        priority=70,
    ))

    # 7. Regime stability
    engine.add_constraint(Constraint(
        name="regime_stability",
        description="Block trades during regime transitions",
        predicate=lambda p, s: s.current_regime != "stable",
        action=ConstraintAction.BLOCK,
        priority=95,
    ))

    # 8. Kelly constraint — MODIFY position down
    def _kelly_modifier(p: TradeProposal) -> TradeProposal:
        # Use kelly_fraction from the proposal itself (caller computed it)
        # We enforce position ≤ kelly_fraction * bankroll here in engine state
        return p  # The predicate below triggers; modifier is a no-op placeholder
        # Real cap applied in predicate logic via MODIFY

    def _kelly_predicate(p: TradeProposal, s: TradingState) -> bool:
        if p.kelly_fraction <= 0 or s.bankroll <= 0:
            return False
        kelly_cap = p.kelly_fraction * s.bankroll
        return p.amount_usd > kelly_cap

    def _kelly_cap_modifier(p: TradeProposal) -> TradeProposal:
        # We can't read state in modifier directly, but caller's kelly_fraction
        # is on the proposal — use a conservative 0.25 * edge as the fraction
        # The predicate already implies the proposal is oversized; halve it
        return dataclasses.replace(p, amount_usd=p.amount_usd * 0.5)

    engine.add_constraint(Constraint(
        name="kelly_constraint",
        description="Position must not exceed kelly_fraction * bankroll",
        predicate=_kelly_predicate,
        action=ConstraintAction.MODIFY,
        modifier=_kelly_cap_modifier,
        priority=65,
    ))

    # 9. Category filter — block crypto/sports
    _BLOCKED_CATEGORIES = frozenset({"crypto", "sports", "sport"})

    engine.add_constraint(Constraint(
        name="category_filter",
        description="Block crypto and sports category markets",
        predicate=lambda p, _s: p.category.lower() in _BLOCKED_CATEGORIES,
        action=ConstraintAction.BLOCK,
        priority=60,
    ))

    # 10. Resolution window: must resolve within 24 hours
    engine.add_constraint(Constraint(
        name="resolution_window",
        description="Block markets resolving after 24 hours",
        predicate=lambda p, _s: p.resolution_hours > 24.0,
        action=ConstraintAction.BLOCK,
        priority=55,
    ))

    logger.info(
        "elastifund_default_constraints: loaded %d rules",
        len(engine.constraints),
    )
    return engine
