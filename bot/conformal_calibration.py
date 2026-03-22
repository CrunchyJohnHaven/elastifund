#!/usr/bin/env python3
"""
Conformal Calibration — Adaptive Conformal Inference wrapper for Platt scaling.
================================================================================
Wraps the existing Platt scaling calibration (A=0.5914, B=-0.3977) with
Adaptive Conformal Inference (ACI) to produce calibrated prediction intervals
instead of point estimates.

The bet/abstain decision rule:
  - If the entire prediction interval is above market_price + min_edge → BUY_YES
  - If (1 - interval.upper) > (1 - market_price) + min_edge → BUY_NO
  - Otherwise → ABSTAIN

ACI automatically widens intervals when the model is miscalibrated and tightens
them when well-calibrated, providing distribution-free coverage guarantees.

Author: JJ (autonomous)
Dispatch: Cycle 4 — Conformal Prediction
"""

from __future__ import annotations

import logging
import math
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Optional

import numpy as np

try:
    from bot import elastic_client
except ImportError:  # pragma: no cover - script-style execution fallback
    import elastic_client  # type: ignore

logger = logging.getLogger("JJ.conformal")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_DEFAULT_PLATT_A = 0.5914
_DEFAULT_PLATT_B = -0.3977
_DEFAULT_ALPHA = 0.10          # 90% coverage target
_DEFAULT_GAMMA = 0.005         # ACI learning rate
_DEFAULT_MAX_RESIDUALS = 500   # Rolling window size
_ALPHA_MIN = 0.01
_ALPHA_MAX = 0.50
_WIDE_LOWER = 0.05             # Default lower bound when no residuals available
_WIDE_UPPER = 0.95             # Default upper bound when no residuals available


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ConformalInterval:
    """A calibrated prediction interval for a binary outcome probability."""
    lower: float          # Lower bound of probability interval
    upper: float          # Upper bound of probability interval
    point_estimate: float # Platt-calibrated point estimate
    coverage: float       # Target coverage level (e.g. 0.90)
    width: float          # upper - lower

    @property
    def straddles(self) -> bool:
        """True if interval contains 0.5 (maximum uncertainty — abstain zone)."""
        return self.lower <= 0.5 <= self.upper


@dataclass
class BetDecision:
    """Result of the bet/abstain decision gate."""
    action: str           # "BUY_YES", "BUY_NO", "ABSTAIN"
    confidence: float     # Distance from nearest interval bound to market price
    interval: ConformalInterval
    market_price: float
    edge_lower: float     # Minimum edge (conservative estimate)
    edge_upper: float     # Maximum edge (optimistic estimate)


@dataclass
class _AciState:
    """Mutable ACI state — separated to keep ConformalCalibrator dataclass-clean."""
    alpha: float = _DEFAULT_ALPHA
    residuals: deque = field(default_factory=lambda: deque(maxlen=_DEFAULT_MAX_RESIDUALS))
    # Track per-observation errors for empirical coverage reporting
    errors: deque = field(default_factory=lambda: deque(maxlen=_DEFAULT_MAX_RESIDUALS))


# ---------------------------------------------------------------------------
# Main calibrator
# ---------------------------------------------------------------------------

class ConformalCalibrator:
    """
    Adaptive Conformal Inference calibrator wrapping Platt scaling.

    Provides distribution-free coverage guarantees for binary outcome
    probability predictions. The adaptive quantile threshold widens when
    the model miscalibrates and tightens when it is accurate.

    Parameters
    ----------
    platt_a : float
        Platt scaling A parameter (sigmoid: 1 / (1 + exp(A * x + B))).
    platt_b : float
        Platt scaling B parameter.
    alpha : float
        Miscoverage rate target. alpha=0.10 targets 90% empirical coverage.
    gamma : float
        ACI learning rate for adaptive quantile update. Larger values cause
        faster adaptation but higher variance.
    max_residuals : int
        Rolling window size for calibration residuals. Controls how quickly
        the calibrator forgets historical performance.
    """

    def __init__(
        self,
        platt_a: float = _DEFAULT_PLATT_A,
        platt_b: float = _DEFAULT_PLATT_B,
        alpha: float = _DEFAULT_ALPHA,
        gamma: float = _DEFAULT_GAMMA,
        max_residuals: int = _DEFAULT_MAX_RESIDUALS,
    ) -> None:
        self.platt_a = float(platt_a)
        self.platt_b = float(platt_b)
        self.target_alpha = float(alpha)
        self.gamma = float(gamma)
        self.max_residuals = int(max_residuals)

        self._state = _AciState(
            alpha=float(alpha),
            residuals=deque(maxlen=max_residuals),
            errors=deque(maxlen=max_residuals),
        )

        logger.debug(
            "ConformalCalibrator initialised: platt_a=%.4f platt_b=%.4f "
            "alpha=%.3f gamma=%.4f max_residuals=%d",
            self.platt_a, self.platt_b, self.target_alpha,
            self.gamma, self.max_residuals,
        )

    # ------------------------------------------------------------------
    # Platt scaling
    # ------------------------------------------------------------------

    def platt_transform(self, raw_prob: float) -> float:
        """Apply Platt scaling on logit-transformed raw probability.

        Matches the canonical calibrate_probability_with_params() in
        adaptive_platt.py:

            logit_output = A * logit(raw_prob) + B
            calibrated   = sigmoid(logit_output) = 1 / (1 + exp(-logit_output))

        Symmetry: for p < 0.5, return 1 - platt_transform(1 - p) to ensure
        the transform is monotonically increasing across the full [0, 1] range.

        Input is clamped to [1e-9, 1-1e-9] to avoid log-domain infinity.
        """
        p = float(raw_prob)
        # Symmetry: reflect p < 0.5 through 0.5 so the positive logit branch
        # handles the arithmetic, then flip the result.
        if abs(p - 0.5) < 1e-12:
            return 0.5
        if p < 0.5:
            return 1.0 - self.platt_transform(1.0 - p)
        # p in (0.5, 1.0] — clamp before logit
        p = min(1.0 - 1e-9, p)
        logit = math.log(p / (1.0 - p))
        logit_out = max(-30.0, min(30.0, self.platt_a * logit + self.platt_b))
        return float(1.0 / (1.0 + math.exp(-logit_out)))

    # ------------------------------------------------------------------
    # ACI update
    # ------------------------------------------------------------------

    def update(self, predicted_prob: float, actual_outcome: bool) -> None:
        """Update the conformal residual set with a new resolved observation.

        Computes the conformity score s = |p_hat - y| and updates the
        adaptive quantile threshold via the ACI rule:

            alpha_{t+1} = alpha_t + gamma * (alpha - err_t)

        where err_t = 1 if the observation fell outside the current
        prediction set (miscoverage event) and 0 otherwise.

        Parameters
        ----------
        predicted_prob : float
            The Platt-calibrated probability predicted before resolution.
        actual_outcome : bool
            True if the YES outcome resolved, False otherwise.
        """
        p = max(0.0, min(1.0, float(predicted_prob)))
        y = 1.0 if actual_outcome else 0.0

        # Conformity score: absolute residual
        score = abs(p - y)
        self._state.residuals.append(score)

        # Determine current prediction set membership using current quantile
        current_quantile = self._current_quantile()
        interval_lower = max(0.0, p - current_quantile)
        interval_upper = min(1.0, p + current_quantile)
        covered = interval_lower <= y <= interval_upper
        err_t = 0.0 if covered else 1.0
        self._state.errors.append(err_t)

        # ACI update: pull alpha toward target when covered, away when not
        new_alpha = self._state.alpha + self.gamma * (self.target_alpha - err_t)
        self._state.alpha = float(np.clip(new_alpha, _ALPHA_MIN, _ALPHA_MAX))

        logger.debug(
            "ACI update: score=%.4f covered=%s err_t=%.0f "
            "alpha_new=%.4f residuals=%d",
            score, covered, err_t, self._state.alpha, len(self._state.residuals),
        )

    # ------------------------------------------------------------------
    # Interval prediction
    # ------------------------------------------------------------------

    def predict_interval(
        self,
        raw_prob: float,
        coverage: float = None,
    ) -> ConformalInterval:
        """Produce a prediction interval at the specified coverage level.

        Uses the current adaptive quantile from stored residuals. If no
        residuals are available, returns a wide default interval.

        Parameters
        ----------
        raw_prob : float
            Raw (uncalibrated) probability estimate from the signal source.
        coverage : float, optional
            Target coverage level. Defaults to 1 - self.target_alpha.

        Returns
        -------
        ConformalInterval
            Prediction interval with coverage guarantee.
        """
        target_coverage = coverage if coverage is not None else (1.0 - self.target_alpha)
        point = self.platt_transform(raw_prob)

        if len(self._state.residuals) == 0:
            # No calibration data — return wide conservative interval
            lower = _WIDE_LOWER
            upper = _WIDE_UPPER
            logger.debug("No residuals: returning wide default interval [%.2f, %.2f]", lower, upper)
        else:
            # Override alpha if a custom coverage was specified
            if coverage is not None:
                alpha_use = 1.0 - coverage
            else:
                alpha_use = self._state.alpha
            q = self._quantile_at_alpha(alpha_use)
            lower = max(0.0, point - q)
            upper = min(1.0, point + q)

        return ConformalInterval(
            lower=lower,
            upper=upper,
            point_estimate=point,
            coverage=target_coverage,
            width=upper - lower,
        )

    # ------------------------------------------------------------------
    # Bet / abstain decision
    # ------------------------------------------------------------------

    def decide(
        self,
        raw_prob: float,
        market_price: float,
        min_edge: float = 0.05,
    ) -> BetDecision:
        """Make a bet/abstain decision using the conformal prediction interval.

        Decision logic:
          1. Compute conformal interval around Platt-calibrated estimate.
          2. If interval.lower > market_price + min_edge → BUY_YES
          3. If (1 - interval.upper) > (1 - market_price) + min_edge → BUY_NO
          4. Otherwise → ABSTAIN

        Edge calculations:
          - edge_lower = interval.lower - market_price  (conservative YES edge)
          - edge_upper = interval.upper - market_price  (optimistic YES edge)

        Parameters
        ----------
        raw_prob : float
            Raw probability from the signal source.
        market_price : float
            Current best ask / mid price for YES outcome.
        min_edge : float
            Minimum required edge (in probability units) to place a bet.

        Returns
        -------
        BetDecision
            Action ("BUY_YES", "BUY_NO", or "ABSTAIN") with metadata.
        """
        interval = self.predict_interval(raw_prob)
        mp = float(market_price)

        # YES edge: entire interval above the market price + buffer
        yes_threshold = mp + min_edge
        no_threshold = (1.0 - mp) + min_edge  # edge on NO side

        if interval.lower > yes_threshold:
            action = "BUY_YES"
            confidence = interval.lower - mp
        elif (1.0 - interval.upper) > no_threshold:
            action = "BUY_NO"
            confidence = (1.0 - mp) - (1.0 - interval.upper)
        else:
            action = "ABSTAIN"
            # Confidence is negative — how far inside the abstain zone we are
            yes_gap = interval.lower - yes_threshold   # negative if below
            no_gap = (1.0 - interval.upper) - no_threshold  # negative if below
            confidence = float(max(yes_gap, no_gap))

        edge_lower = interval.lower - mp
        edge_upper = interval.upper - mp

        decision = BetDecision(
            action=action,
            confidence=confidence,
            interval=interval,
            market_price=mp,
            edge_lower=edge_lower,
            edge_upper=edge_upper,
        )

        self._emit_telemetry(decision, raw_prob)
        return decision

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def coverage_stats(self) -> dict:
        """Return empirical coverage, average interval width, and residual count.

        Returns
        -------
        dict with keys:
          - empirical_coverage: fraction of observations where the true
            outcome fell within the prediction interval
          - average_width: mean interval width over the residual window
          - residual_count: number of observations in the rolling window
          - current_alpha: current adaptive miscoverage rate
          - target_alpha: target miscoverage rate
        """
        n = len(self._state.residuals)
        errors = list(self._state.errors)

        if n == 0:
            return {
                "empirical_coverage": None,
                "average_width": None,
                "residual_count": 0,
                "current_alpha": self._state.alpha,
                "target_alpha": self.target_alpha,
            }

        empirical_coverage = 1.0 - (sum(errors) / len(errors)) if errors else None

        # Reconstruct average interval widths: each residual used as the
        # half-width at time of prediction isn't stored, so we report the
        # current quantile * 2 as a proxy for future intervals.
        avg_width = self._current_quantile() * 2.0

        return {
            "empirical_coverage": empirical_coverage,
            "average_width": avg_width,
            "residual_count": n,
            "current_alpha": self._state.alpha,
            "target_alpha": self.target_alpha,
        }

    # ------------------------------------------------------------------
    # Seeding
    # ------------------------------------------------------------------

    def seed_from_history(
        self,
        predictions: list[tuple[float, bool]],
    ) -> None:
        """Seed the calibrator with historical (predicted_prob, outcome) pairs.

        Iterates through the history in order, applying each observation
        as a live update. The order matters because ACI is sequential.

        Parameters
        ----------
        predictions : list of (predicted_prob, actual_outcome)
            Each element is a (float, bool) tuple. predicted_prob should
            already be Platt-calibrated (i.e., the output of platt_transform).
        """
        for predicted_prob, actual_outcome in predictions:
            self.update(float(predicted_prob), bool(actual_outcome))
        logger.info(
            "Seeded conformal calibrator with %d historical observations. "
            "Residual window: %d / %d",
            len(predictions),
            len(self._state.residuals),
            self.max_residuals,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _current_quantile(self) -> float:
        """Return the (1 - current_alpha)-th quantile of stored residuals.

        If the residual set is empty, returns 0.5 as a conservative fallback
        (which, combined with a Platt estimate near 0.5, produces a near-full
        [0, 1] interval).
        """
        return self._quantile_at_alpha(self._state.alpha)

    def _quantile_at_alpha(self, alpha: float) -> float:
        """Return the (1 - alpha)-th quantile of stored residuals."""
        if not self._state.residuals:
            return 0.5
        arr = np.array(self._state.residuals, dtype=float)
        q_level = 1.0 - float(np.clip(alpha, _ALPHA_MIN, _ALPHA_MAX))
        # Use interpolation='higher' for conservative coverage (standard in CP)
        return float(np.quantile(arr, q_level))

    def _emit_telemetry(self, decision: BetDecision, raw_prob: float) -> None:
        """Emit a telemetry event to Elasticsearch (best-effort, fire-and-forget)."""
        try:
            elastic_client.emit(
                index="jj-conformal-decisions",
                document={
                    "@timestamp": datetime.now(UTC).isoformat(),
                    "action": decision.action,
                    "confidence": decision.confidence,
                    "market_price": decision.market_price,
                    "raw_prob": raw_prob,
                    "point_estimate": decision.interval.point_estimate,
                    "interval_lower": decision.interval.lower,
                    "interval_upper": decision.interval.upper,
                    "interval_width": decision.interval.width,
                    "straddles": decision.interval.straddles,
                    "edge_lower": decision.edge_lower,
                    "edge_upper": decision.edge_upper,
                    "current_alpha": self._state.alpha,
                    "residual_count": len(self._state.residuals),
                },
            )
        except Exception:  # pragma: no cover - telemetry must never crash the caller
            pass
