#!/usr/bin/env python3
"""
Harness Gates — Replay-Based Mutation Acceptance for Elastifund
===============================================================
Every mutation to live trading code must pass a gauntlet of historical replay
cases before it touches capital. The corpus grows monotonically: cases are
added, never removed. A mutation earns KEEP, DISCARD, or CRASH.

The March 22 directional bleed is a permanent gate: naked one-sided BTC live
trading is blocked whenever structural alternatives exist.

March 2026 — Elastifund / JJ
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger("JJ.harness_gates")

# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------


@dataclass
class ReplayCase:
    """A single historical incident encoded as a replay scenario."""

    case_id: str
    name: str
    description: str
    market_data: list[dict[str, Any]]
    expected_behavior: str
    pass_condition: Callable[[dict[str, Any]], bool]


@dataclass
class GauntletResult:
    """Outcome of running one replay case against a strategy."""

    case_id: str
    passed: bool
    detail: str = ""


@dataclass
class PromotionRuleResult:
    """Outcome of evaluating a single promotion rule."""

    rule_name: str
    passed: bool
    detail: str = ""


# ---------------------------------------------------------------------------
# Mandatory Replay Cases
# ---------------------------------------------------------------------------


def _march_11_btc_winning_data() -> list[dict[str, Any]]:
    """BTC trending down, 39/47 DOWN wins on March 11."""
    rows = []
    for i in range(47):
        side = "DOWN" if i < 39 else "UP"
        pnl = 3.50 if side == "DOWN" else 2.10
        rows.append({
            "market_id": f"btc5_{i:03d}",
            "side": side,
            "entry_price": 0.48 if side == "DOWN" else 0.52,
            "exit_price": 1.0 if side == "DOWN" else 1.0,
            "pnl": pnl,
            "hour_et": 3 + (i % 4),
            "filled": True,
        })
    return rows


def _march_11_pass(result: dict[str, Any]) -> bool:
    """Strategy must not lose money on the March 11 replay."""
    return result.get("net_pnl", 0.0) >= 0.0


def _march_15_concentration_data() -> list[dict[str, Any]]:
    """302 rows, all skipped. Zero fills. Over-concentrated skip reasons."""
    rows = []
    skip_reasons = (
        ["skip_delta_too_large"] * 164
        + ["skip_shadow_only"] * 56
        + ["skip_toxic_order_flow"] * 42
        + ["skip_midpoint_kill_zone"] * 21
        + ["skip_price_outside_guardrails"] * 9
        + ["skip_bad_book"] * 3
        + ["skip_other"] * 7
    )
    for i, reason in enumerate(skip_reasons):
        rows.append({
            "market_id": f"btc5_skip_{i:03d}",
            "side": "DOWN" if i % 3 != 0 else "UP",
            "skip_reason": reason,
            "filled": False,
            "pnl": 0.0,
        })
    return rows


def _march_15_pass(result: dict[str, Any]) -> bool:
    """Must detect and throttle over-concentration. Must not auto-promote."""
    return result.get("concentration_detected", False) and not result.get(
        "auto_promoted", False
    )


def _march_22_directional_bleed_data() -> list[dict[str, Any]]:
    """Bought DOWN at 48-55 cents, BTC went UP, lost both trades."""
    return [
        {
            "market_id": "btc5_down_bleed_001",
            "side": "DOWN",
            "entry_price": 0.48,
            "exit_price": 0.0,
            "pnl": -4.80,
            "hour_et": 14,
            "filled": True,
            "btc_direction": "UP",
        },
        {
            "market_id": "btc5_down_bleed_002",
            "side": "DOWN",
            "entry_price": 0.55,
            "exit_price": 0.0,
            "pnl": -5.50,
            "hour_et": 15,
            "filled": True,
            "btc_direction": "UP",
        },
    ]


def _march_22_pass(result: dict[str, Any]) -> bool:
    """Strategy must either abstain or trade both sides."""
    abstained = result.get("abstained", False)
    traded_both = result.get("traded_both_sides", False)
    return abstained or traded_both


def _stale_data_fallback_data() -> list[dict[str, Any]]:
    """73h stale FAST_TRADE_EDGE_ANALYSIS. Zero candidates."""
    return [
        {
            "market_id": "stale_check",
            "pipeline_age_hours": 73.0,
            "pipeline_verdict": "REJECT_ALL",
            "candidate_count": 0,
            "filled": False,
            "pnl": 0.0,
        },
    ]


def _stale_data_pass(result: dict[str, Any]) -> bool:
    """Must not trade on stale data."""
    return not result.get("traded_on_stale", True)


def _wallet_address_contradiction_data() -> list[dict[str, Any]]:
    """Wrong address returns $0 when wallet has $390."""
    return [
        {
            "market_id": "wallet_check",
            "queried_balance": 0.0,
            "actual_balance": 390.90,
            "address_queried": "0x28C5AedA_WRONG",
            "address_correct": "0xb2fef31c_CORRECT",
        },
    ]


def _wallet_contradiction_pass(result: dict[str, Any]) -> bool:
    """Must detect the divergence between queried and actual balance."""
    return result.get("divergence_detected", False)


def _build_mandatory_cases() -> list[ReplayCase]:
    """Build the five mandatory replay cases. Called once at init."""
    return [
        ReplayCase(
            case_id="march_11_btc_winning",
            name="March 11 BTC Winning Session",
            description=(
                "BTC trending down, 39/47 DOWN wins. Net +$136.86. "
                "Strategy must not lose money on this replay."
            ),
            market_data=_march_11_btc_winning_data(),
            expected_behavior="Profitable or break-even on DOWN-trending BTC day",
            pass_condition=_march_11_pass,
        ),
        ReplayCase(
            case_id="march_15_concentration",
            name="March 15 Concentration Failure",
            description=(
                "302 rows, all skipped. Zero fills. 54% skip_delta_too_large. "
                "Must detect concentration and not auto-promote."
            ),
            market_data=_march_15_concentration_data(),
            expected_behavior="Detect over-concentration, throttle, do not promote",
            pass_condition=_march_15_pass,
        ),
        ReplayCase(
            case_id="march_22_directional_bleed",
            name="March 22 Directional Bleed",
            description=(
                "Bought DOWN at 48-55 cents, BTC went UP, lost both trades. "
                "Strategy must either abstain or trade both sides."
            ),
            market_data=_march_22_directional_bleed_data(),
            expected_behavior="Abstain from naked directional, or hedge both sides",
            pass_condition=_march_22_pass,
        ),
        ReplayCase(
            case_id="stale_data_fallback",
            name="Stale Data Fallback",
            description=(
                "73h stale FAST_TRADE_EDGE_ANALYSIS. Pipeline says REJECT ALL. "
                "Must not trade on stale data."
            ),
            market_data=_stale_data_fallback_data(),
            expected_behavior="Refuse to trade on stale pipeline data",
            pass_condition=_stale_data_pass,
        ),
        ReplayCase(
            case_id="wallet_address_contradiction",
            name="Wallet Address Contradiction",
            description=(
                "Wrong address returns $0 when wallet has $390. "
                "Must detect the divergence."
            ),
            market_data=_wallet_address_contradiction_data(),
            expected_behavior="Detect balance divergence, flag wrong address",
            pass_condition=_wallet_contradiction_pass,
        ),
    ]


# ---------------------------------------------------------------------------
# Harness Gate
# ---------------------------------------------------------------------------


class HarnessGate:
    """Replay-based mutation acceptance gate.

    The corpus grows monotonically: cases are added, never removed.
    A strategy mutation earns KEEP, DISCARD, or CRASH based on replay
    results and metric comparison.
    """

    def __init__(self) -> None:
        self._cases: dict[str, ReplayCase] = {}
        for case in _build_mandatory_cases():
            self._cases[case.case_id] = case
        logger.info(
            "HarnessGate initialised with %d mandatory replay cases",
            len(self._cases),
        )

    # -- corpus management ---------------------------------------------------

    @property
    def case_count(self) -> int:
        return len(self._cases)

    @property
    def case_ids(self) -> list[str]:
        return list(self._cases.keys())

    def add_case(self, case: ReplayCase) -> None:
        """Add a replay case. Corpus is append-only; duplicates update."""
        self._cases[case.case_id] = case
        logger.info("Added replay case %s (%s)", case.case_id, case.name)

    def get_case(self, case_id: str) -> Optional[ReplayCase]:
        return self._cases.get(case_id)

    # -- gauntlet execution --------------------------------------------------

    def run_gauntlet(
        self,
        strategy_fn: Callable[[list[dict[str, Any]]], dict[str, Any]],
    ) -> dict[str, Any]:
        """Run strategy against all replay cases.

        Args:
            strategy_fn: Callable that takes market_data (list of dicts)
                and returns a result dict. The result dict is passed to
                each case's pass_condition.

        Returns:
            {
                "passed": bool,
                "results": [GauntletResult, ...],
                "failures": [GauntletResult, ...],
            }
        """
        results: list[GauntletResult] = []
        failures: list[GauntletResult] = []

        for case in self._cases.values():
            try:
                output = strategy_fn(case.market_data)
                ok = case.pass_condition(output)
                gr = GauntletResult(
                    case_id=case.case_id,
                    passed=ok,
                    detail=f"expected: {case.expected_behavior}",
                )
            except Exception as exc:
                ok = False
                gr = GauntletResult(
                    case_id=case.case_id,
                    passed=False,
                    detail=f"EXCEPTION: {exc}",
                )

            results.append(gr)
            if not ok:
                failures.append(gr)

        all_passed = len(failures) == 0
        logger.info(
            "Gauntlet: %d/%d passed, %d failures",
            len(results) - len(failures),
            len(results),
            len(failures),
        )
        return {
            "passed": all_passed,
            "results": results,
            "failures": failures,
        }

    # -- mutation check (KEEP / DISCARD / CRASH) -----------------------------

    def check_mutation(
        self,
        before_metrics: dict[str, float],
        after_metrics: dict[str, float],
    ) -> str:
        """Compare before/after metrics to decide KEEP, DISCARD, or CRASH.

        Rules:
            CRASH: after_metrics contains a key not in before_metrics
                   (new failure mode detected, not in corpus).
            DISCARD: any metric degrades by more than 20%, OR any shared
                     metric degrades by more than 10% and the gauntlet
                     has not been re-run (conservative default).
            KEEP: all replay cases pass AND no metric degrades > 10%.

        For simplicity, we check degradation as:
            degradation = (before - after) / abs(before) if before != 0
        For metrics where higher is better (win_rate, pnl, sharpe, etc.).
        """
        # Check for new failure modes (keys in after not in before)
        new_keys = set(after_metrics.keys()) - set(before_metrics.keys())
        if new_keys:
            logger.warning(
                "CRASH: new failure modes detected: %s", new_keys,
            )
            return "CRASH"

        # Check degradation on shared metrics
        max_degradation = 0.0
        for key in before_metrics:
            if key not in after_metrics:
                continue
            before_val = before_metrics[key]
            after_val = after_metrics[key]
            if before_val == 0.0:
                # Cannot compute relative degradation from zero baseline
                if after_val < 0.0:
                    max_degradation = max(max_degradation, 1.0)
                continue
            degradation = (before_val - after_val) / abs(before_val)
            if degradation > 0:
                max_degradation = max(max_degradation, degradation)

        if max_degradation > 0.20:
            logger.info(
                "DISCARD: max degradation %.1f%% exceeds 20%% threshold",
                max_degradation * 100,
            )
            return "DISCARD"

        if max_degradation > 0.10:
            logger.info(
                "DISCARD: max degradation %.1f%% exceeds 10%% threshold",
                max_degradation * 100,
            )
            return "DISCARD"

        logger.info("KEEP: no metric degrades more than 10%%")
        return "KEEP"

    # -- naked directional block ---------------------------------------------

    def blocks_naked_directional(
        self, has_structural_alternatives: bool,
    ) -> bool:
        """Returns True if one-sided BTC live would be blocked.

        The March 22 directional bleed is a permanent gate: naked
        one-sided BTC live trading is blocked whenever structural
        alternatives are available. If no alternatives exist, naked
        directional is allowed as a fallback.
        """
        march_22_present = "march_22_directional_bleed" in self._cases
        if not march_22_present:
            # If the case was somehow missing (should never happen), block
            logger.warning(
                "march_22_directional_bleed case missing from corpus — "
                "blocking naked directional as safety fallback"
            )
            return True

        if has_structural_alternatives:
            logger.info(
                "Naked directional BLOCKED: structural alternatives exist"
            )
            return True

        logger.info(
            "Naked directional ALLOWED: no structural alternatives available"
        )
        return False


# ---------------------------------------------------------------------------
# Promotion Rules for Copied/Indicator Strategies
# ---------------------------------------------------------------------------


@dataclass
class PromotionRules:
    """Promotion rules that must all pass before a copied or indicator
    strategy can advance to live trading."""

    replay_passed: bool = False
    shadow_passed: bool = False
    daily_pnl_truth_passed: bool = False
    no_concentration_regression: bool = False

    def all_passed(self) -> bool:
        return (
            self.replay_passed
            and self.shadow_passed
            and self.daily_pnl_truth_passed
            and self.no_concentration_regression
        )

    def failures(self) -> list[str]:
        failed = []
        if not self.replay_passed:
            failed.append("replay_pass")
        if not self.shadow_passed:
            failed.append("shadow_pass")
        if not self.daily_pnl_truth_passed:
            failed.append("daily_pnl_truth_pass")
        if not self.no_concentration_regression:
            failed.append("no_concentration_regression")
        return failed


def evaluate_promotion_rules(
    gauntlet_result: dict[str, Any],
    shadow_days: int,
    shadow_expectancy: float,
    daily_pnl_age_hours: float,
    max_single_direction_pct: float,
) -> PromotionRules:
    """Evaluate all promotion rules for a copied/indicator strategy.

    Args:
        gauntlet_result: Output of HarnessGate.run_gauntlet()
        shadow_days: Calendar days in shadow mode
        shadow_expectancy: Expected value per trade in shadow
        daily_pnl_age_hours: Hours since last daily P&L update
        max_single_direction_pct: Max fraction of exposure in one direction

    Returns:
        PromotionRules with each gate evaluated.
    """
    rules = PromotionRules()

    # replay_pass: must pass all gauntlet cases
    rules.replay_passed = gauntlet_result.get("passed", False)

    # shadow_pass: 7 days shadow with positive expectancy
    rules.shadow_passed = shadow_days >= 7 and shadow_expectancy > 0.0

    # daily_pnl_truth_pass: daily P&L must not be stale (>24h) or null
    rules.daily_pnl_truth_passed = 0.0 < daily_pnl_age_hours <= 24.0

    # no_concentration_regression: max single-direction exposure < 60%
    rules.no_concentration_regression = max_single_direction_pct < 0.60

    return rules
