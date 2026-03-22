#!/usr/bin/env python3
"""
Hawkes Process Order Flow Model
================================
Models order flow in prediction markets using Hawkes processes — self-exciting
point processes where each event increases the probability of subsequent events.

Replaces heuristic VPIN thresholds with a principled model of order arrival
dynamics that can detect informed-trader cascades.

Hawkes intensity:
    λ(t) = μ + Σ α * exp(-β * (t - t_i))  for all t_i < t

Where:
    μ = baseline intensity (background rate)
    α = excitation magnitude (each event boosts future intensity)
    β = decay rate (how quickly excitation fades)
    α/β = branching ratio (if ≥ 1, process is unstable/explosive)

Separate Hawkes processes are maintained for buy and sell sides.
Cascade detection fires when intensity > cascade_threshold * baseline.

Author: JJ (autonomous)
Date: 2026-03-21
"""

from __future__ import annotations

import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

try:
    from bot import elastic_client
except ImportError:  # pragma: no cover - script-style execution fallback
    try:
        import elastic_client  # type: ignore
    except ImportError:
        elastic_client = None  # type: ignore

logger = logging.getLogger("JJ.hawkes_flow")

# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------


@dataclass
class HawkesState:
    """Snapshot of Hawkes process state for one side."""

    intensity: float            # Current estimated intensity λ(t)
    baseline_intensity: float   # μ parameter
    excitation: float           # α parameter
    decay: float                # β parameter
    branching_ratio: float      # α/β — key diagnostic
    is_cascade: bool            # True if intensity >> baseline
    cascade_strength: float     # How many multiples above baseline
    event_count: int
    last_event_time: float


class OrderFlowEvent:
    """Represents a single order flow event."""

    __slots__ = ("timestamp", "side", "size", "price", "market_id")

    def __init__(
        self,
        timestamp: float,
        side: str,
        size: float,
        price: float,
        market_id: str = "",
    ):
        self.timestamp = timestamp
        self.side = side          # "buy" or "sell"
        self.size = size
        self.price = price
        self.market_id = market_id

    def __repr__(self) -> str:
        return (
            f"OrderFlowEvent(t={self.timestamp:.3f}, side={self.side!r}, "
            f"size={self.size}, price={self.price})"
        )


# ---------------------------------------------------------------------------
# Single-side Hawkes kernel
# ---------------------------------------------------------------------------


class _SideKernel:
    """
    Univariate Hawkes kernel for one side (buy or sell).

    Maintains:
    - A sliding window of event timestamps
    - Online MLE estimates of (μ, α, β)
    - Current compensator (recursive sum for O(1) intensity evaluation)
    """

    def __init__(
        self,
        mu_init: float,
        alpha_init: float,
        beta_init: float,
        window_seconds: float,
        learning_rate: float,
        min_events_for_fit: int,
    ) -> None:
        # Parameters (positive constraints enforced on update)
        self.mu = mu_init
        self.alpha = alpha_init
        self.beta = beta_init

        # Hyperparameters
        self.window_seconds = window_seconds
        self.learning_rate = learning_rate
        self.min_events_for_fit = min_events_for_fit

        # Event history in window
        self._events: deque[float] = deque()   # timestamps
        self._event_count: int = 0
        self._last_event_time: float = 0.0

        # Recursive compensator R(t) = Σ exp(-β*(t - t_i))
        # Updated incrementally: on new event at t_new,
        #   R(t_new) = 1 + R(t_prev) * exp(-β * (t_new - t_prev))
        self._R: float = 0.0
        self._t_R: float = 0.0   # time at which _R was last computed

    # ------------------------------------------------------------------ #
    # Core intensity computation
    # ------------------------------------------------------------------ #

    def intensity_at(self, t: float) -> float:
        """λ(t) = μ + α * R(t).  R(t) decays from _R at time _t_R."""
        if not self._events:
            return self.mu
        dt = t - self._t_R
        r_t = self._R * math.exp(-self.beta * max(dt, 0.0))
        return self.mu + self.alpha * r_t

    # ------------------------------------------------------------------ #
    # Event ingestion
    # ------------------------------------------------------------------ #

    def add_event(self, t: float) -> None:
        """Register a new event at time t and update compensator."""
        # Prune events outside the window
        cutoff = t - self.window_seconds
        while self._events and self._events[0] < cutoff:
            self._events.popleft()

        # Decay existing compensator to current time
        if self._events:
            dt = t - self._t_R
            self._R = self._R * math.exp(-self.beta * max(dt, 0.0))
        else:
            self._R = 0.0

        # New event contributes +1 to compensator
        self._R += 1.0
        self._t_R = t

        self._events.append(t)
        self._event_count += 1
        self._last_event_time = t

        # Attempt online MLE update when enough history
        if len(self._events) >= self.min_events_for_fit:
            self._online_mle_step(t)

    # ------------------------------------------------------------------ #
    # Online MLE
    # ------------------------------------------------------------------ #

    def _online_mle_step(self, T: float) -> None:
        """
        One normalized gradient-ascent step on the Hawkes log-likelihood.

        Log-likelihood (exponential kernel):
            L = Σᵢ log(μ + α * Rᵢ)  -  μ*T_span  -  (α/β) * Σᵢ (1 - exp(-β*(T-tᵢ)))

        Normalized per-event gradients (divide all terms by n for stable scale):
            ∂L/∂μ  ≈ (1/n) * [Σᵢ 1/(μ + α*Rᵢ)  -  T_span]
            ∂L/∂α  ≈ (1/n) * [Σᵢ Rᵢ/(μ + α*Rᵢ)  -  (1/β)*Σᵢ(1-e^{-β(T-tᵢ)})]
            ∂L/∂β  ≈ (1/n) * [(α/β²)*Σᵢ(1-e^{-β(T-tᵢ)}) - (α/β)*Σᵢ(T-tᵢ)e^{-β(T-tᵢ)}]

        Dividing by n normalises scale regardless of window length, preventing
        the μ gradient from exploding when T_span is large.

        Rᵢ = Σⱼ<ᵢ exp(-β*(tᵢ-tⱼ))  computed recursively in O(N).
        """
        events = list(self._events)
        n = len(events)
        if n < 2:
            return

        mu, alpha, beta = self.mu, self.alpha, self.beta
        T_span = T - events[0]
        if T_span <= 0.0:
            return

        # Compute recursive R values at each event time
        R_vals: list[float] = []
        R_cur = 0.0
        t_prev = events[0]
        for t_i in events:
            if t_i > events[0]:
                R_cur = R_cur * math.exp(-beta * (t_i - t_prev))
                R_cur += 1.0   # contribution of the previous event
            t_prev = t_i
            R_vals.append(R_cur)

        # Accumulate unnormalised gradient sums
        sum_inv_lam = 0.0    # Σ 1/λᵢ
        sum_R_over_lam = 0.0  # Σ Rᵢ/λᵢ
        integral_alpha = 0.0  # Σ (1 - e^{-β(T-tᵢ)})
        integral_beta = 0.0   # Σ (T-tᵢ) e^{-β(T-tᵢ)}

        for i, t_i in enumerate(events):
            lam_i = mu + alpha * R_vals[i]
            if lam_i <= 1e-15:
                continue
            sum_inv_lam += 1.0 / lam_i
            sum_R_over_lam += R_vals[i] / lam_i

            dt_to_T = T - t_i
            e_term = math.exp(-beta * dt_to_T)
            integral_alpha += 1.0 - e_term
            integral_beta += dt_to_T * e_term

        # Normalised gradients (1/n factor keeps scale independent of window size)
        inv_n = 1.0 / n
        grad_mu = inv_n * (sum_inv_lam - T_span)
        grad_alpha = inv_n * (sum_R_over_lam - integral_alpha / beta)
        grad_beta = inv_n * (
            (alpha / (beta * beta)) * integral_alpha
            - (alpha / beta) * integral_beta
        )

        # Gradient clipping: limit step to ±5 in normalised space
        clip = 5.0
        grad_mu = max(-clip, min(clip, grad_mu))
        grad_alpha = max(-clip, min(clip, grad_alpha))
        grad_beta = max(-clip, min(clip, grad_beta))

        # Gradient-ascent update
        lr = self.learning_rate
        new_mu = mu + lr * grad_mu
        new_alpha = alpha + lr * grad_alpha
        new_beta = beta + lr * grad_beta

        # Enforce positivity and numerical stability
        self.mu = max(1e-6, new_mu)
        self.alpha = max(1e-6, new_alpha)
        self.beta = max(1e-4, new_beta)

        # Enforce branching ratio < 0.99 (prevent explosive process)
        if self.alpha / self.beta >= 0.99:
            self.alpha = 0.98 * self.beta

        # Recompute compensator with updated parameters
        self._rebuild_compensator(T)

    def _rebuild_compensator(self, T: float) -> None:
        """Recompute recursive compensator from scratch with current params."""
        if not self._events:
            self._R = 0.0
            self._t_R = T
            return
        R = 0.0
        t_prev = None
        for t_i in self._events:
            if t_prev is not None:
                R = R * math.exp(-self.beta * (t_i - t_prev))
            R += 1.0
            t_prev = t_i
        # Decay to current time T
        R *= math.exp(-self.beta * max(T - self._events[-1], 0.0))
        self._R = R
        self._t_R = T

    # ------------------------------------------------------------------ #
    # Accessors
    # ------------------------------------------------------------------ #

    @property
    def branching_ratio(self) -> float:
        return self.alpha / self.beta

    @property
    def event_count(self) -> int:
        return len(self._events)

    @property
    def total_event_count(self) -> int:
        return self._event_count

    @property
    def last_event_time(self) -> float:
        return self._last_event_time

    def reset(self, mu: float, alpha: float, beta: float) -> None:
        self.mu = mu
        self.alpha = alpha
        self.beta = beta
        self._events.clear()
        self._event_count = 0
        self._last_event_time = 0.0
        self._R = 0.0
        self._t_R = 0.0

    def event_rate(self, now: float) -> float:
        """Events per second in the current window."""
        if not self._events:
            return 0.0
        window_actual = min(self.window_seconds, now - self._events[0] + 1e-9)
        return len(self._events) / window_actual


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class HawkesOrderFlow:
    """
    Bivariate Hawkes process model for prediction-market order flow.

    Maintains separate Hawkes kernels for buy and sell sides.
    Detects informed-trader cascades when intensity significantly exceeds
    the background rate.

    Usage::

        hof = HawkesOrderFlow()
        for tick in clob_feed:
            evt = OrderFlowEvent(tick.ts, tick.side, tick.size, tick.price)
            state = hof.observe(evt)
            if state.is_cascade:
                logger.warning("Cascade detected — side=%s strength=%.1fx",
                               "buy" if hof._buy.intensity_at(tick.ts) >
                               hof._sell.intensity_at(tick.ts) else "sell",
                               state.cascade_strength)
        signal = hof.get_signal()
        if signal["is_toxic"]:
            pull_quotes()
    """

    def __init__(
        self,
        mu_init: float = 0.1,
        alpha_init: float = 0.5,
        beta_init: float = 1.0,
        cascade_threshold: float = 3.0,
        window_seconds: float = 300.0,
        learning_rate: float = 0.01,
        min_events_for_fit: int = 20,
    ) -> None:
        """
        Args:
            mu_init: Initial baseline intensity (events/sec background rate).
            alpha_init: Initial excitation magnitude.
            beta_init: Initial decay rate (higher = faster decay).
            cascade_threshold: Intensity / baseline ratio that triggers cascade.
            window_seconds: Sliding window for event memory (seconds).
            learning_rate: Online MLE gradient-ascent step size.
            min_events_for_fit: Minimum events before fitting parameters.
        """
        self._mu0 = mu_init
        self._alpha0 = alpha_init
        self._beta0 = beta_init
        self._cascade_threshold = cascade_threshold
        self._window_seconds = window_seconds
        self._learning_rate = learning_rate
        self._min_events_for_fit = min_events_for_fit

        self._buy = _SideKernel(
            mu_init, alpha_init, beta_init,
            window_seconds, learning_rate, min_events_for_fit
        )
        self._sell = _SideKernel(
            mu_init, alpha_init, beta_init,
            window_seconds, learning_rate, min_events_for_fit
        )

        self._last_observe_time: float = 0.0

    # ------------------------------------------------------------------ #
    # Core observation
    # ------------------------------------------------------------------ #

    def observe(self, event: OrderFlowEvent) -> HawkesState:
        """
        Process a new order flow event and update the Hawkes model.

        Steps:
        1. Route event to buy or sell kernel.
        2. Compute current intensity.
        3. Update parameter estimates via online MLE.
        4. Check cascade condition.
        5. Return current HawkesState.

        Returns:
            HawkesState describing the *active* side's process after update.
        """
        t = event.timestamp
        self._last_observe_time = t

        side = event.side.lower()
        if side == "buy":
            kernel = self._buy
        elif side == "sell":
            kernel = self._sell
        else:
            raise ValueError(f"event.side must be 'buy' or 'sell', got {event.side!r}")

        kernel.add_event(t)

        # Compute state for the active side
        intensity = kernel.intensity_at(t)
        baseline = kernel.mu
        cascade_strength = intensity / baseline if baseline > 0 else 1.0
        is_cascade = cascade_strength >= self._cascade_threshold

        if is_cascade:
            logger.warning(
                "Hawkes cascade detected — side=%s intensity=%.4f baseline=%.4f "
                "strength=%.1fx market=%s",
                side, intensity, baseline, cascade_strength,
                event.market_id or "unknown",
            )
            self._emit_cascade_telemetry(event, intensity, cascade_strength)

        return HawkesState(
            intensity=intensity,
            baseline_intensity=baseline,
            excitation=kernel.alpha,
            decay=kernel.beta,
            branching_ratio=kernel.branching_ratio,
            is_cascade=is_cascade,
            cascade_strength=cascade_strength,
            event_count=kernel.total_event_count,
            last_event_time=kernel.last_event_time,
        )

    # ------------------------------------------------------------------ #
    # Intensity queries
    # ------------------------------------------------------------------ #

    def compute_intensity(self, t: float, side: Optional[str] = None) -> float:
        """
        Compute the Hawkes intensity at time t.

        Args:
            t: Unix timestamp to evaluate intensity at.
            side: "buy", "sell", or None (combined buy+sell).

        Returns:
            Intensity value λ(t).
        """
        if side is None:
            return self._buy.intensity_at(t) + self._sell.intensity_at(t)
        side = side.lower()
        if side == "buy":
            return self._buy.intensity_at(t)
        if side == "sell":
            return self._sell.intensity_at(t)
        raise ValueError(f"side must be 'buy', 'sell', or None, got {side!r}")

    # ------------------------------------------------------------------ #
    # Derived signals
    # ------------------------------------------------------------------ #

    def get_flow_imbalance(self) -> float:
        """
        Compute buy_intensity / (buy_intensity + sell_intensity) - 0.5.

        Returns:
            Float in [-0.5, +0.5].
            Positive = buy pressure, negative = sell pressure, 0 = balanced.
        """
        t = self._last_observe_time or time.time()
        buy_i = self._buy.intensity_at(t)
        sell_i = self._sell.intensity_at(t)
        total = buy_i + sell_i
        if total <= 0.0:
            return 0.0
        return buy_i / total - 0.5

    def is_toxic(self) -> bool:
        """
        True if either side is in a cascade state.

        Indicates potential informed trading activity — consider pulling quotes.
        """
        t = self._last_observe_time or time.time()
        for kernel in (self._buy, self._sell):
            intensity = kernel.intensity_at(t)
            baseline = kernel.mu
            if baseline > 0 and (intensity / baseline) >= self._cascade_threshold:
                return True
        return False

    def get_signal(self) -> dict:
        """
        Return a comprehensive signal dict for integration into the main bot.

        Schema::

            {
                "buy_intensity": float,
                "sell_intensity": float,
                "buy_cascade": bool,
                "sell_cascade": bool,
                "flow_imbalance": float,       # [-0.5, +0.5]
                "branching_ratio_buy": float,
                "branching_ratio_sell": float,
                "is_toxic": bool,
                "event_rate": float,           # events/sec in window (combined)
            }
        """
        t = self._last_observe_time or time.time()

        buy_i = self._buy.intensity_at(t)
        sell_i = self._sell.intensity_at(t)

        buy_cascade = (
            self._buy.mu > 0
            and (buy_i / self._buy.mu) >= self._cascade_threshold
        )
        sell_cascade = (
            self._sell.mu > 0
            and (sell_i / self._sell.mu) >= self._cascade_threshold
        )

        total = buy_i + sell_i
        flow_imbalance = (buy_i / total - 0.5) if total > 0 else 0.0

        buy_rate = self._buy.event_rate(t)
        sell_rate = self._sell.event_rate(t)

        return {
            "buy_intensity": buy_i,
            "sell_intensity": sell_i,
            "buy_cascade": buy_cascade,
            "sell_cascade": sell_cascade,
            "flow_imbalance": flow_imbalance,
            "branching_ratio_buy": self._buy.branching_ratio,
            "branching_ratio_sell": self._sell.branching_ratio,
            "is_toxic": buy_cascade or sell_cascade,
            "event_rate": buy_rate + sell_rate,
        }

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    def reset(self) -> None:
        """Clear all events and reset parameters to initial values."""
        self._buy.reset(self._mu0, self._alpha0, self._beta0)
        self._sell.reset(self._mu0, self._alpha0, self._beta0)
        self._last_observe_time = 0.0
        logger.debug("HawkesOrderFlow reset to initial state")

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _emit_cascade_telemetry(
        self,
        event: OrderFlowEvent,
        intensity: float,
        cascade_strength: float,
    ) -> None:
        """Emit cascade event to Elasticsearch telemetry (best-effort)."""
        if elastic_client is None:
            return
        try:
            elastic_client.index_signal(
                {
                    "signal_type": "hawkes_cascade",
                    "market_id": event.market_id,
                    "side": event.side,
                    "intensity": intensity,
                    "cascade_strength": cascade_strength,
                    "timestamp": event.timestamp,
                }
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("Hawkes telemetry emit failed: %s", exc)
