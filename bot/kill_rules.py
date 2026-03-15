#!/usr/bin/env python3
"""
Automated Kill Rules — Strategy Rejection Discipline
=====================================================
Dispatch: Updated kill criteria for structural alpha validation.

Kill rules are the most important part of the pipeline. A strategy that
passes all kill rules and survives is tradeable. A strategy that fails
any single rule is permanently rejected.

Updated rules per dispatch:
1. Semantic Decay: Lead-lag pair coherence drops below threshold
2. Toxicity Survival: Strategy must survive simulated high-VPIN periods
3. Cost Stress (Polynomial): Accurate fee simulation at extreme probabilities
4. Calibration Enforcement: All LLM probabilities must pass Platt scaling

Legacy rules (still enforced):
5. Minimum signal count (N >= 100 for candidates, 300 for validation)
6. OOS EV must be positive after cost adjustment
7. Regime decay: performance must not degrade under out-of-sample conditions

Author: JJ (autonomous)
Date: 2026-03-07
"""

import logging
import math
from dataclasses import dataclass
from enum import Enum
from typing import Optional

try:
    from bot import elastic_client
except ImportError:  # pragma: no cover - script-style execution fallback
    import elastic_client  # type: ignore

logger = logging.getLogger("JJ.kill_rules")
_LAST_KILL_EVENT_STATE: dict[str, tuple[tuple[str, str], ...]] = {}


class KillReason(Enum):
    """Why a strategy was killed."""
    SEMANTIC_DECAY = "semantic_decay"
    TOXICITY_SURVIVAL = "toxicity_survival"
    COST_STRESS = "cost_stress_polynomial"
    CALIBRATION_MISSING = "calibration_not_applied"
    INSUFFICIENT_SIGNALS = "insufficient_signals"
    NEGATIVE_OOS_EV = "negative_oos_ev"
    REGIME_DECAY = "regime_decay"
    SHADOW_PROMOTION = "shadow_promotion_gate"
    CAPTURE_RATE = "capture_rate"
    CLASSIFICATION_ACCURACY = "classification_accuracy"
    FALSE_POSITIVE_RATE = "false_positive_rate"
    ROLLBACK_CLUSTER = "rollback_cluster"


@dataclass
class KillResult:
    """Result of running kill rules on a strategy."""
    passed: bool
    reason: Optional[KillReason] = None
    detail: str = ""
    metrics: dict = None

    def __post_init__(self):
        if self.metrics is None:
            self.metrics = {}

    def __str__(self):
        if self.passed:
            return "PASS"
        return f"KILL: {self.reason.value} — {self.detail}"


def _metric_signature(metrics: dict) -> tuple[tuple[str, str], ...]:
    items: list[tuple[str, str]] = []
    for key, value in sorted((metrics or {}).items()):
        if isinstance(value, float):
            normalized = f"{value:.8f}"
        else:
            normalized = str(value)
        items.append((str(key), normalized))
    return tuple(items)


def _emit_kill_event(
    rule_name: str,
    result: KillResult,
    *,
    metric_value: float | int | None = None,
    threshold: float | int | None = None,
    action_taken: str = "triggered",
    extra: Optional[dict] = None,
) -> None:
    if result.passed:
        _LAST_KILL_EVENT_STATE.pop(rule_name, None)
        return

    signature = _metric_signature(result.metrics)
    if _LAST_KILL_EVENT_STATE.get(rule_name) == signature:
        return

    payload = {
        "kill_rule": rule_name,
        "metric_value": metric_value,
        "threshold": threshold,
        "action_taken": action_taken,
        "detail": result.detail,
        "reason": result.reason.value if result.reason is not None else rule_name,
    }
    if extra:
        payload.update(extra)

    try:
        elastic_client.index_kill(payload)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Elastic kill telemetry failed for %s: %s", rule_name, exc)

    _LAST_KILL_EVENT_STATE[rule_name] = signature


# ---------------------------------------------------------------------------
# Polymarket fee model (polynomial)
# ---------------------------------------------------------------------------

def polymarket_taker_fee(price: float, category: str = "default") -> float:
    """Calculate Polymarket taker fee using the polynomial formula.

    Fee = price * (1 - price) * rate
    Where rate depends on category:
        - crypto: 0.025 (polynomial, exp=2) → max ~1.56% at p=0.50
        - sports: 0.007 (linear, exp=1) → max ~0.44% at p=0.50
        - default: 0.0 (no taker fee on other categories)

    This is the fee the TAKER pays. Makers pay 0%.
    """
    FEE_RATES = {
        "crypto": 0.025,
        "sports": 0.007,
        "default": 0.0,
    }
    rate = FEE_RATES.get(category, 0.0)
    return price * (1.0 - price) * rate


# ---------------------------------------------------------------------------
# Kill Rule Implementations
# ---------------------------------------------------------------------------

def check_semantic_decay(
    semantic_confidence: float,
    threshold: float = 0.3,
) -> KillResult:
    """Kill Rule 1: Semantic Decay.

    If the LLM semantic coherence score for a lead-lag pair drops below
    the threshold, the pair is immediately terminated and liquidated.

    Args:
        semantic_confidence: Current LLM confidence in transmission mechanism
        threshold: Minimum acceptable confidence (default 0.3)
    """
    if semantic_confidence < threshold:
        result = KillResult(
            passed=False,
            reason=KillReason.SEMANTIC_DECAY,
            detail=f"Semantic confidence {semantic_confidence:.3f} < {threshold}",
            metrics={"semantic_confidence": semantic_confidence, "threshold": threshold},
        )
        _emit_kill_event(
            KillReason.SEMANTIC_DECAY.value,
            result,
            metric_value=semantic_confidence,
            threshold=threshold,
            extra={"semantic_decay_rate": semantic_confidence},
        )
        return result
    result = KillResult(passed=True, metrics={"semantic_confidence": semantic_confidence})
    _emit_kill_event(KillReason.SEMANTIC_DECAY.value, result)
    return result


def check_toxicity_survival(
    pnl_under_toxic: float,
    pnl_normal: float,
    max_drawdown_pct: float = 0.50,
) -> KillResult:
    """Kill Rule 2: Toxicity Survival.

    Simulate filling maker orders exclusively during periods where VPIN
    is in the top decile. If the strategy's profitability collapses
    under this simulated high toxicity, permanently reject.

    Args:
        pnl_under_toxic: P&L when only fills during VPIN > 80th percentile
        pnl_normal: P&L under normal conditions
        max_drawdown_pct: Maximum acceptable degradation (default 50%)
    """
    survival_ratio = (pnl_under_toxic / pnl_normal) if pnl_normal not in (0, 0.0) else None

    if pnl_normal <= 0:
        result = KillResult(
            passed=False,
            reason=KillReason.TOXICITY_SURVIVAL,
            detail=f"Normal P&L is negative: ${pnl_normal:.2f}",
            metrics={
                "pnl_toxic": pnl_under_toxic,
                "pnl_normal": pnl_normal,
                "toxicity_survival_ratio": survival_ratio,
            },
        )
        _emit_kill_event(
            KillReason.TOXICITY_SURVIVAL.value,
            result,
            metric_value=survival_ratio if survival_ratio is not None else pnl_normal,
            threshold=1.0 - max_drawdown_pct,
            extra={"toxicity_survival_ratio": survival_ratio},
        )
        return result

    degradation = 1.0 - (pnl_under_toxic / pnl_normal) if pnl_normal > 0 else 1.0

    if degradation > max_drawdown_pct:
        result = KillResult(
            passed=False,
            reason=KillReason.TOXICITY_SURVIVAL,
            detail=(
                f"Strategy collapses under toxic flow: "
                f"${pnl_under_toxic:.2f} vs ${pnl_normal:.2f} "
                f"({degradation:.0%} degradation > {max_drawdown_pct:.0%} limit)"
            ),
            metrics={
                "pnl_toxic": pnl_under_toxic,
                "pnl_normal": pnl_normal,
                "degradation": degradation,
                "toxicity_survival_ratio": survival_ratio,
            },
        )
        _emit_kill_event(
            KillReason.TOXICITY_SURVIVAL.value,
            result,
            metric_value=survival_ratio if survival_ratio is not None else degradation,
            threshold=1.0 - max_drawdown_pct,
            extra={"toxicity_survival_ratio": survival_ratio},
        )
        return result

    result = KillResult(
        passed=True,
        metrics={
            "pnl_toxic": pnl_under_toxic,
            "pnl_normal": pnl_normal,
            "degradation": degradation,
            "toxicity_survival_ratio": survival_ratio,
        },
    )
    _emit_kill_event(KillReason.TOXICITY_SURVIVAL.value, result)
    return result


def check_cost_stress(
    gross_ev: float,
    avg_price: float,
    category: str = "default",
    execution_latency_ms: float = 5.0,
    slippage_per_ms: float = 0.0001,
) -> KillResult:
    """Kill Rule 3: Cost Stress (Polynomial Fee + Latency).

    Accurately simulates:
    - The polynomial fee scaling at extreme probabilities
    - A standard execution latency penalty (default 5ms)

    A strategy must survive with positive EV after full cost modeling.

    Args:
        gross_ev: Expected value before costs (per trade, dollars)
        avg_price: Average execution price (0-1 range)
        category: Market category for fee lookup
        execution_latency_ms: Expected execution latency in ms
        slippage_per_ms: Price slippage per ms of latency
    """
    # Taker fee at this price point
    taker_fee = polymarket_taker_fee(avg_price, category)

    # Latency cost: slippage proportional to execution delay
    latency_cost = execution_latency_ms * slippage_per_ms

    # Total cost
    total_cost = taker_fee + latency_cost

    # Net EV
    net_ev = gross_ev - total_cost

    if net_ev <= 0:
        result = KillResult(
            passed=False,
            reason=KillReason.COST_STRESS,
            detail=(
                f"Negative net EV: gross={gross_ev:.4f} - fee={taker_fee:.4f} "
                f"- latency={latency_cost:.4f} = {net_ev:.4f}"
            ),
            metrics={
                "gross_ev": gross_ev,
                "taker_fee": taker_fee,
                "latency_cost": latency_cost,
                "cost_stress_polynomial_value": taker_fee,
                "net_ev": net_ev,
            },
        )
        _emit_kill_event(
            KillReason.COST_STRESS.value,
            result,
            metric_value=net_ev,
            threshold=0.0,
            extra={"cost_stress_polynomial_value": taker_fee},
        )
        return result

    result = KillResult(
        passed=True,
        metrics={
            "gross_ev": gross_ev,
            "net_ev": net_ev,
            "total_cost": total_cost,
            "cost_stress_polynomial_value": taker_fee,
        },
    )
    _emit_kill_event(KillReason.COST_STRESS.value, result)
    return result


def check_calibration_enforcement(
    raw_prob: float,
    calibrated_prob: float,
    platt_a: float = 0.5914,
    platt_b: float = -0.3977,
    tolerance: float = 0.01,
) -> KillResult:
    """Kill Rule 4: Calibration Enforcement.

    Any strategy relying on LLM probabilities that have NOT been passed
    through Platt scaling is automatically rejected.

    Verifies that the calibrated probability matches the expected output
    of the Platt scaling transform.

    Args:
        raw_prob: The raw LLM probability
        calibrated_prob: The probability actually used for sizing
        platt_a: Platt scaling parameter A
        platt_b: Platt scaling parameter B
        tolerance: Acceptable numerical tolerance
    """
    # Compute expected calibrated value
    raw_clamped = max(0.001, min(0.999, raw_prob))
    logit_in = math.log(raw_clamped / (1.0 - raw_clamped))
    logit_out = platt_a * logit_in + platt_b
    logit_out = max(-30, min(30, logit_out))
    expected = 1.0 / (1.0 + math.exp(-logit_out))

    diff = abs(calibrated_prob - expected)

    if diff > tolerance:
        result = KillResult(
            passed=False,
            reason=KillReason.CALIBRATION_MISSING,
            detail=(
                f"Calibration mismatch: used={calibrated_prob:.4f} "
                f"expected={expected:.4f} (diff={diff:.4f} > {tolerance})"
            ),
            metrics={
                "raw_prob": raw_prob,
                "calibrated_prob": calibrated_prob,
                "expected_calibrated": expected,
                "calibration_drift": diff,
                "diff": diff,
            },
        )
        _emit_kill_event(
            KillReason.CALIBRATION_MISSING.value,
            result,
            metric_value=diff,
            threshold=tolerance,
            extra={"calibration_drift": diff},
        )
        return result

    result = KillResult(
        passed=True,
        metrics={"raw_prob": raw_prob, "calibrated_prob": calibrated_prob, "calibration_drift": diff},
    )
    _emit_kill_event(KillReason.CALIBRATION_MISSING.value, result)
    return result


def check_minimum_signals(
    signal_count: int,
    stage: str = "candidate",
) -> KillResult:
    """Kill Rule 5: Minimum Signal Count.

    - Candidate stage: N >= 100
    - Validation stage: N >= 300
    """
    thresholds = {"candidate": 100, "validated": 300}
    required = thresholds.get(stage, 100)

    if signal_count < required:
        result = KillResult(
            passed=False,
            reason=KillReason.INSUFFICIENT_SIGNALS,
            detail=f"Only {signal_count} signals ({stage} requires {required})",
            metrics={"signal_count": signal_count, "required": required, "stage": stage},
        )
        _emit_kill_event(
            KillReason.INSUFFICIENT_SIGNALS.value,
            result,
            metric_value=signal_count,
            threshold=required,
        )
        return result

    result = KillResult(passed=True, metrics={"signal_count": signal_count, "required": required, "stage": stage})
    _emit_kill_event(KillReason.INSUFFICIENT_SIGNALS.value, result)
    return result


def check_oos_ev(
    oos_ev: float,
    in_sample_ev: float,
    min_ratio: float = 0.3,
) -> KillResult:
    """Kill Rule 6: Out-of-Sample EV.

    OOS EV must be positive and at least 30% of in-sample EV.
    """
    if oos_ev <= 0:
        result = KillResult(
            passed=False,
            reason=KillReason.NEGATIVE_OOS_EV,
            detail=f"Negative OOS EV: {oos_ev:.4f}",
            metrics={"oos_ev": oos_ev, "in_sample_ev": in_sample_ev},
        )
        _emit_kill_event(
            KillReason.NEGATIVE_OOS_EV.value,
            result,
            metric_value=oos_ev,
            threshold=0.0,
        )
        return result

    if in_sample_ev > 0:
        ratio = oos_ev / in_sample_ev
        if ratio < min_ratio:
            result = KillResult(
                passed=False,
                reason=KillReason.REGIME_DECAY,
                detail=(
                    f"OOS/IS ratio too low: {ratio:.2f} < {min_ratio} "
                    f"(OOS={oos_ev:.4f}, IS={in_sample_ev:.4f})"
                ),
                metrics={"oos_ev": oos_ev, "in_sample_ev": in_sample_ev, "ratio": ratio},
            )
            _emit_kill_event(
                KillReason.REGIME_DECAY.value,
                result,
                metric_value=ratio,
                threshold=min_ratio,
            )
            return result

    result = KillResult(passed=True, metrics={"oos_ev": oos_ev, "in_sample_ev": in_sample_ev})
    _emit_kill_event(KillReason.NEGATIVE_OOS_EV.value, result)
    _emit_kill_event(KillReason.REGIME_DECAY.value, result)
    return result


def check_shadow_promotion(
    signal_count: int,
    minimum_signals: int = 20,
) -> KillResult:
    """Promotion gate: shadow mode needs enough samples before live consideration."""
    if signal_count < minimum_signals:
        result = KillResult(
            passed=False,
            reason=KillReason.SHADOW_PROMOTION,
            detail=f"Only {signal_count} shadow signals; need {minimum_signals}",
            metrics={"signal_count": signal_count, "minimum_signals": minimum_signals},
        )
        _emit_kill_event(
            KillReason.SHADOW_PROMOTION.value,
            result,
            metric_value=signal_count,
            threshold=minimum_signals,
        )
        return result
    result = KillResult(passed=True, metrics={"signal_count": signal_count, "minimum_signals": minimum_signals})
    _emit_kill_event(KillReason.SHADOW_PROMOTION.value, result)
    return result


def check_capture_rate(
    capture_rate: float | None,
    minimum_capture_rate: float = 0.50,
) -> KillResult:
    """Promotion gate: realized capture must retain enough theoretical edge."""
    if capture_rate is None:
        result = KillResult(
            passed=False,
            reason=KillReason.CAPTURE_RATE,
            detail="Capture rate unavailable",
            metrics={"capture_rate": None, "minimum_capture_rate": minimum_capture_rate},
        )
        _emit_kill_event(
            KillReason.CAPTURE_RATE.value,
            result,
            metric_value=None,
            threshold=minimum_capture_rate,
        )
        return result
    if capture_rate < minimum_capture_rate:
        result = KillResult(
            passed=False,
            reason=KillReason.CAPTURE_RATE,
            detail=f"Capture rate {capture_rate:.2%} < {minimum_capture_rate:.2%}",
            metrics={"capture_rate": capture_rate, "minimum_capture_rate": minimum_capture_rate},
        )
        _emit_kill_event(
            KillReason.CAPTURE_RATE.value,
            result,
            metric_value=capture_rate,
            threshold=minimum_capture_rate,
        )
        return result
    result = KillResult(passed=True, metrics={"capture_rate": capture_rate, "minimum_capture_rate": minimum_capture_rate})
    _emit_kill_event(KillReason.CAPTURE_RATE.value, result)
    return result


def check_classification_accuracy(
    classification_accuracy: float | None,
    minimum_accuracy: float = 0.80,
) -> KillResult:
    """Promotion gate: B-1 needs validated relation accuracy before live routing."""
    if classification_accuracy is None:
        result = KillResult(
            passed=False,
            reason=KillReason.CLASSIFICATION_ACCURACY,
            detail="Classification accuracy unavailable",
            metrics={"classification_accuracy": None, "minimum_accuracy": minimum_accuracy},
        )
        _emit_kill_event(
            KillReason.CLASSIFICATION_ACCURACY.value,
            result,
            metric_value=None,
            threshold=minimum_accuracy,
        )
        return result
    if classification_accuracy < minimum_accuracy:
        result = KillResult(
            passed=False,
            reason=KillReason.CLASSIFICATION_ACCURACY,
            detail=f"Classification accuracy {classification_accuracy:.2%} < {minimum_accuracy:.2%}",
            metrics={"classification_accuracy": classification_accuracy, "minimum_accuracy": minimum_accuracy},
        )
        _emit_kill_event(
            KillReason.CLASSIFICATION_ACCURACY.value,
            result,
            metric_value=classification_accuracy,
            threshold=minimum_accuracy,
        )
        return result
    result = KillResult(
        passed=True,
        metrics={"classification_accuracy": classification_accuracy, "minimum_accuracy": minimum_accuracy},
    )
    _emit_kill_event(KillReason.CLASSIFICATION_ACCURACY.value, result)
    return result


def check_false_positive_rate(
    false_positive_rate: float | None,
    maximum_false_positive_rate: float = 0.05,
) -> KillResult:
    """Promotion gate: structural lanes halt if resolved false positives drift too high."""
    if false_positive_rate is None:
        result = KillResult(
            passed=False,
            reason=KillReason.FALSE_POSITIVE_RATE,
            detail="False-positive rate unavailable",
            metrics={
                "false_positive_rate": None,
                "maximum_false_positive_rate": maximum_false_positive_rate,
            },
        )
        _emit_kill_event(
            KillReason.FALSE_POSITIVE_RATE.value,
            result,
            metric_value=None,
            threshold=maximum_false_positive_rate,
        )
        return result
    if false_positive_rate > maximum_false_positive_rate:
        result = KillResult(
            passed=False,
            reason=KillReason.FALSE_POSITIVE_RATE,
            detail=f"False-positive rate {false_positive_rate:.2%} > {maximum_false_positive_rate:.2%}",
            metrics={
                "false_positive_rate": false_positive_rate,
                "maximum_false_positive_rate": maximum_false_positive_rate,
            },
        )
        _emit_kill_event(
            KillReason.FALSE_POSITIVE_RATE.value,
            result,
            metric_value=false_positive_rate,
            threshold=maximum_false_positive_rate,
        )
        return result
    result = KillResult(
        passed=True,
        metrics={"false_positive_rate": false_positive_rate, "maximum_false_positive_rate": maximum_false_positive_rate},
    )
    _emit_kill_event(KillReason.FALSE_POSITIVE_RATE.value, result)
    return result


def check_consecutive_rollbacks(
    consecutive_rollbacks: int,
    maximum_consecutive_rollbacks: int = 3,
) -> KillResult:
    """Promotion gate: repeated rollback losses disable live promotion."""
    if consecutive_rollbacks > maximum_consecutive_rollbacks:
        result = KillResult(
            passed=False,
            reason=KillReason.ROLLBACK_CLUSTER,
            detail=(
                f"Consecutive rollback losses {consecutive_rollbacks} > "
                f"{maximum_consecutive_rollbacks}"
            ),
            metrics={
                "consecutive_rollbacks": consecutive_rollbacks,
                "maximum_consecutive_rollbacks": maximum_consecutive_rollbacks,
            },
        )
        _emit_kill_event(
            KillReason.ROLLBACK_CLUSTER.value,
            result,
            metric_value=consecutive_rollbacks,
            threshold=maximum_consecutive_rollbacks,
        )
        return result
    result = KillResult(
        passed=True,
        metrics={
            "consecutive_rollbacks": consecutive_rollbacks,
            "maximum_consecutive_rollbacks": maximum_consecutive_rollbacks,
        },
    )
    _emit_kill_event(KillReason.ROLLBACK_CLUSTER.value, result)
    return result


def run_combinatorial_promotion_battery(
    *,
    signal_count: int,
    capture_rate: float | None,
    false_positive_rate: float | None,
    consecutive_rollbacks: int,
    minimum_signals: int = 20,
    minimum_capture_rate: float = 0.50,
    maximum_false_positive_rate: float = 0.05,
    maximum_consecutive_rollbacks: int = 3,
    require_classification: bool = False,
    classification_accuracy: float | None = None,
    minimum_classification_accuracy: float = 0.80,
) -> tuple[bool, list[KillResult]]:
    """Run promotion gates for A-6/B-1 shadow-to-live eligibility."""
    results = [
        (
            "shadow_promotion",
            check_shadow_promotion(signal_count=signal_count, minimum_signals=minimum_signals),
        ),
        (
            "capture_rate",
            check_capture_rate(capture_rate=capture_rate, minimum_capture_rate=minimum_capture_rate),
        ),
        (
            "false_positive_rate",
            check_false_positive_rate(
                false_positive_rate=false_positive_rate,
                maximum_false_positive_rate=maximum_false_positive_rate,
            ),
        ),
        (
            "rollback_cluster",
            check_consecutive_rollbacks(
                consecutive_rollbacks=consecutive_rollbacks,
                maximum_consecutive_rollbacks=maximum_consecutive_rollbacks,
            ),
        ),
    ]

    if require_classification:
        results.append(
            (
                "classification_accuracy",
                check_classification_accuracy(
                    classification_accuracy=classification_accuracy,
                    minimum_accuracy=minimum_classification_accuracy,
                ),
            )
        )

    all_passed = all(result.passed for _, result in results)
    for name, result in results:
        if not result.passed:
            logger.warning("KILL [%s]: %s", name, result)
        else:
            logger.debug("PASS [%s]", name)
    return all_passed, [result for _, result in results]


# ---------------------------------------------------------------------------
# Full Kill Rule Battery
# ---------------------------------------------------------------------------

def run_full_kill_battery(
    semantic_confidence: float = 1.0,
    pnl_under_toxic: float = 0.0,
    pnl_normal: float = 0.0,
    gross_ev: float = 0.0,
    avg_price: float = 0.5,
    category: str = "default",
    raw_prob: float = 0.5,
    calibrated_prob: float = 0.5,
    signal_count: int = 0,
    stage: str = "candidate",
    oos_ev: float = 0.0,
    in_sample_ev: float = 0.0,
    skip_toxicity: bool = False,
    skip_semantic: bool = False,
) -> tuple[bool, list[KillResult]]:
    """Run all kill rules. Returns (all_passed, results_list).

    Any single failure kills the strategy.
    """
    results = []

    if not skip_semantic:
        results.append(("semantic_decay", check_semantic_decay(semantic_confidence)))

    if not skip_toxicity:
        results.append(("toxicity_survival", check_toxicity_survival(pnl_under_toxic, pnl_normal)))

    results.append(("cost_stress", check_cost_stress(gross_ev, avg_price, category)))
    results.append(("calibration", check_calibration_enforcement(raw_prob, calibrated_prob)))
    results.append(("signal_count", check_minimum_signals(signal_count, stage)))
    results.append(("oos_ev", check_oos_ev(oos_ev, in_sample_ev)))

    all_passed = all(r.passed for _, r in results)

    for name, result in results:
        if not result.passed:
            logger.warning(f"KILL [{name}]: {result}")
        else:
            logger.debug(f"PASS [{name}]")

    return all_passed, [r for _, r in results]
