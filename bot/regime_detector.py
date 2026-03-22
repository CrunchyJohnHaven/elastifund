#!/usr/bin/env python3
"""
Bayesian Online Change-Point Detection (BOCPD) — Regime Detector
=================================================================
Implements Adams & MacKay 2007 BOCPD on rolling trade P&L to detect
regime shifts in real-time. When a shift is detected, the system enters
TRANSITION state and suppresses trading until the new regime stabilizes.

Algorithm:
  Maintains a probability distribution over run lengths (how long since
  the last changepoint). At each timestep:
    1. Compute predictive probability of new observation under each run length
    2. Compute growth probabilities (extending current run)
    3. Compute changepoint probability (P(run_length = 0) after normalization)
    4. Normalize posterior over run lengths

  Conjugate prior: Normal-Inverse-Gamma (NIG)
    - Analytically tractable — no MCMC needed
    - Predictive distribution is Student-t (heavier tails = more robust)
    - Sufficient statistics: mu, kappa, alpha, beta per run length

CP Detection Signal (key implementation note):
  In BOCPD, P(r_t = 0 | x_{1:t}) = h after normalization when the run-length
  distribution has most mass at a single long run. This is a mathematical
  identity: the CP probability is the hazard rate times the evidence ratio,
  and after normalization it converges to h in a stable regime.

  The ACTIONABLE signal is the TOTAL MASS on short run lengths:
    changepoint_prob = sum_{r=0}^{short_run_window-1} P(r_t = r | x_{1:t})

  After a genuine regime shift:
    - P(x_new | long run trained on old regime) → near 0
    - P(x_new | short run / prior) remains reasonable
    - Mass migrates from long runs to short runs (r=1, 2, ...)
    - sum P(r < short_window) spikes toward 1.0

  `changepoint_threshold` is compared against this short-run probability mass,
  NOT against P(r=0) alone.

Integration:
  After each trade resolves:
    regime = detector.observe(trade_pnl, timestamp)
    if not detector.should_trade():
        logger.warning("Regime shift detected — suppressing trades")

Author: JJ (autonomous)
Date: 2026-03-21
Reference: Adams & MacKay 2007, "Bayesian Online Changepoint Detection"
"""

import logging
import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import numpy as np

logger = logging.getLogger("JJ.regime_detector")

# ---------------------------------------------------------------------------
# State Enums and Data Classes
# ---------------------------------------------------------------------------


class RegimeState(Enum):
    STABLE = "stable"           # In a known regime, safe to trade
    TRANSITION = "transition"   # Changepoint detected, suppressing trades
    WARMUP = "warmup"           # Insufficient data (< min_observations)


@dataclass
class RegimeSnapshot:
    state: RegimeState
    run_length: int                # Most probable run length
    changepoint_prob: float        # P(run_length < short_run_window) — see module docstring
    regime_mean: float             # Estimated mean of current regime
    regime_var: float              # Estimated variance of current regime
    observations_seen: int
    last_changepoint_idx: int      # Index of most recent detected changepoint
    timestamp: float


# ---------------------------------------------------------------------------
# NIG Sufficient Statistics per Run Length
# ---------------------------------------------------------------------------

@dataclass
class _NIGParams:
    """Normal-Inverse-Gamma parameters for one run-length hypothesis."""
    mu: float       # Posterior mean hyperparameter
    kappa: float    # Precision on mean
    alpha: float    # Shape for variance
    beta: float     # Rate for variance
    n: int = 0      # Observations accumulated in this run


# ---------------------------------------------------------------------------
# Core Detector
# ---------------------------------------------------------------------------


class BayesianChangePointDetector:
    """
    Online Bayesian Change-Point Detector using Normal-Inverse-Gamma conjugate prior.

    Parameters
    ----------
    hazard_rate : float
        1 / expected_run_length. Higher = more changepoints expected.
        Default 1/50 means we expect a regime shift every ~50 observations.
    mu_prior : float
        Prior mean of the P&L generating process.
    kappa_prior : float
        Prior precision on the mean (higher = tighter prior on mean).
    alpha_prior : float
        Prior shape for variance (Inverse-Gamma).
    beta_prior : float
        Prior rate for variance (Inverse-Gamma).
    changepoint_threshold : float
        Threshold on the short-run probability mass sum_{r<short_run_window} P(r).
        Exceeding this threshold declares a regime shift.
        Default 0.5 works well for strong shifts (3+ sigma mean change).
    short_run_window : int
        Number of run lengths (0..short_run_window-1) summed to compute
        changepoint_prob. Must be much smaller than typical stable run length.
        Default 5: captures the probability mass that collapses to recent runs
        after a shift.
    stabilization_window : int
        Number of observations to wait in TRANSITION before returning to STABLE.
    min_observations : int
        Minimum observations before changepoint detection activates.
    max_run_length : int
        Maximum run length to track (bounds memory at O(max_run_length)).
    """

    def __init__(
        self,
        hazard_rate: float = 1.0 / 50,
        mu_prior: float = 0.0,
        kappa_prior: float = 1.0,
        alpha_prior: float = 1.0,
        beta_prior: float = 1.0,
        changepoint_threshold: float = 0.5,
        short_run_window: int = 5,
        stabilization_window: int = 10,
        min_observations: int = 20,
        max_run_length: int = 300,
    ) -> None:
        self._hazard_rate = hazard_rate
        self._mu0 = mu_prior
        self._kappa0 = kappa_prior
        self._alpha0 = alpha_prior
        self._beta0 = beta_prior
        self._cp_threshold = changepoint_threshold
        self._short_run_window = short_run_window
        self._stabilization_window = stabilization_window
        self._min_obs = min_observations
        self._max_run_length = max_run_length

        # State
        self._observations_seen: int = 0
        self._total_changepoints: int = 0
        self._last_changepoint_idx: int = 0
        self._state: RegimeState = RegimeState.WARMUP
        self._transition_steps_remaining: int = 0
        self._last_snapshot: Optional[RegimeSnapshot] = None

        # Run-length posterior: log probabilities indexed by run length
        # _log_R[r] = log P(run_length = r | data_{1:t})
        # Index 0 = new run just started (run_length = 0).
        # Grows by 1 each step until max_run_length, then truncates.
        self._log_R: np.ndarray = np.array([0.0])  # P(r=0) = 1 initially
        self._nig_params: list[_NIGParams] = [
            _NIGParams(mu=mu_prior, kappa=kappa_prior, alpha=alpha_prior, beta=beta_prior)
        ]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def observe(self, value: float, timestamp: Optional[float] = None) -> RegimeSnapshot:
        """
        Process one new P&L observation and update the run-length posterior.

        NIG sufficient statistic sequential update (one obs at a time):
            kappa_new = kappa + 1
            mu_new    = (kappa * mu + x) / (kappa + 1)
            alpha_new = alpha + 0.5
            beta_new  = beta + kappa * (x - mu)^2 / (2 * (kappa + 1))

        Predictive distribution is Student-t:
            t_{2*alpha}(x | mu, beta*(kappa+1)/(alpha*kappa))

        Returns
        -------
        RegimeSnapshot
            Current regime state after incorporating this observation.
        """
        if timestamp is None:
            timestamp = time.time()

        self._observations_seen += 1

        # --- Step 1: Compute log predictive probability under each run length ---
        n_runs = len(self._log_R)
        log_pred = np.empty(n_runs)
        for r in range(n_runs):
            log_pred[r] = self._log_student_t_pred(value, self._nig_params[r])

        # --- Step 2: Compute unnormalized growth and changepoint probabilities ---
        # Growth: extend run length r -> r+1 (with probability 1 - hazard_rate)
        log_growth = self._log_R + log_pred + math.log(1.0 - self._hazard_rate)

        # Changepoint: all run lengths collapse to 0
        # P(r_{t+1}=0 | x_t) unnorm = sum_r P(r_t=r) * P(x_t|r) * hazard_rate
        log_cp_unnorm = np.logaddexp.reduce(
            self._log_R + log_pred + math.log(self._hazard_rate)
        )

        # --- Step 3: Build new posterior array ---
        # new_log_R[0]   = CP term (run_length = 0 means changepoint just occurred)
        # new_log_R[r+1] = growth from run_length r (r=0..n_runs-1)
        new_log_R = np.empty(n_runs + 1)
        new_log_R[0] = log_cp_unnorm
        new_log_R[1:] = log_growth

        # --- Step 4: Truncate at max_run_length ---
        if len(new_log_R) > self._max_run_length:
            overflow = np.logaddexp.reduce(new_log_R[self._max_run_length:])
            new_log_R = new_log_R[: self._max_run_length]
            new_log_R[-1] = np.logaddexp(new_log_R[-1], overflow)

        # --- Step 5: Normalize ---
        log_norm = np.logaddexp.reduce(new_log_R)
        new_log_R -= log_norm

        # --- Step 6: Update NIG params for each run length ---
        # run_length=0: always the fresh prior
        new_nig: list[_NIGParams] = [
            _NIGParams(mu=self._mu0, kappa=self._kappa0, alpha=self._alpha0, beta=self._beta0)
        ]
        # run_length r+1: grew from old run_length r, so update NIG with new obs
        grow_count = len(new_log_R) - 1
        for r in range(min(grow_count, n_runs)):
            new_nig.append(self._update_nig(self._nig_params[r], value))

        # If truncated, pad remaining NIG entries using the last available updated params
        while len(new_nig) < len(new_log_R):
            new_nig.append(self._update_nig(self._nig_params[-1], value))

        self._log_R = new_log_R
        self._nig_params = new_nig

        # --- Step 7: Compute changepoint signal and MAP run length ---
        # changepoint_prob = P(run_length < short_run_window | data_{1:t})
        # This is the mass that migrates to short runs after a regime shift.
        win = min(self._short_run_window, len(new_log_R))
        cp_prob = float(np.sum(np.exp(new_log_R[:win])))
        # Clip to [0, 1] to guard against floating-point edge cases
        cp_prob = max(0.0, min(1.0, cp_prob))

        map_run_length = int(np.argmax(new_log_R))

        # --- Step 8: Update state machine ---
        self._update_state(cp_prob)

        # --- Step 9: Estimate current regime mean and variance ---
        regime_mean, regime_var = self._estimate_regime_stats(map_run_length)

        snapshot = RegimeSnapshot(
            state=self._state,
            run_length=map_run_length,
            changepoint_prob=cp_prob,
            regime_mean=regime_mean,
            regime_var=regime_var,
            observations_seen=self._observations_seen,
            last_changepoint_idx=self._last_changepoint_idx,
            timestamp=timestamp,
        )
        self._last_snapshot = snapshot

        if self._state == RegimeState.TRANSITION:
            logger.warning(
                "Regime shift detected at obs=%d | short_run_mass=%.4f | MAP run_length=%d",
                self._observations_seen,
                cp_prob,
                map_run_length,
            )
        else:
            logger.debug(
                "obs=%d state=%s | short_run_mass=%.4f | MAP run=%d | mean=%.4f var=%.4f",
                self._observations_seen,
                self._state.value,
                cp_prob,
                map_run_length,
                regime_mean,
                regime_var,
            )

        return snapshot

    def should_trade(self) -> bool:
        """True if the regime is STABLE and we have enough observations."""
        return self._state == RegimeState.STABLE

    def get_regime_summary(self) -> dict:
        """Summary statistics for the current regime."""
        map_run_length = int(np.argmax(self._log_R))
        win = min(self._short_run_window, len(self._log_R))
        cp_prob = float(max(0.0, min(1.0, np.sum(np.exp(self._log_R[:win])))))
        regime_mean, regime_var = self._estimate_regime_stats(map_run_length)

        return {
            "state": self._state.value,
            "observations_seen": self._observations_seen,
            "map_run_length": map_run_length,
            "changepoint_prob": cp_prob,
            "regime_mean": regime_mean,
            "regime_var": regime_var,
            "total_changepoints": self._total_changepoints,
            "last_changepoint_idx": self._last_changepoint_idx,
            "transition_steps_remaining": self._transition_steps_remaining,
            "hazard_rate": self._hazard_rate,
            "changepoint_threshold": self._cp_threshold,
        }

    def reset(self) -> None:
        """Reset all state. Use when starting a new trading session."""
        self._observations_seen = 0
        self._total_changepoints = 0
        self._last_changepoint_idx = 0
        self._state = RegimeState.WARMUP
        self._transition_steps_remaining = 0
        self._last_snapshot = None
        self._log_R = np.array([0.0])
        self._nig_params = [
            _NIGParams(
                mu=self._mu0,
                kappa=self._kappa0,
                alpha=self._alpha0,
                beta=self._beta0,
            )
        ]
        logger.info("RegimeDetector reset.")

    # ------------------------------------------------------------------
    # Static utility
    # ------------------------------------------------------------------

    @staticmethod
    def student_t_pdf(x: float, mu: float, sigma2: float, nu: float) -> float:
        """
        Student-t probability density function.

        p(x) = Gamma((nu+1)/2) / [Gamma(nu/2) * sqrt(nu*pi*sigma2)]
               * (1 + (x-mu)^2 / (nu*sigma2))^(-(nu+1)/2)

        Parameters
        ----------
        x : float
            Evaluation point.
        mu : float
            Location parameter.
        sigma2 : float
            Scale^2 parameter (not the distribution variance).
        nu : float
            Degrees of freedom (must be > 0).

        Returns
        -------
        float
            Probability density at x.
        """
        if nu <= 0.0 or sigma2 <= 0.0:
            raise ValueError(f"nu and sigma2 must be positive; got nu={nu}, sigma2={sigma2}")

        sigma = math.sqrt(sigma2)
        z = (x - mu) / sigma
        log_p = (
            math.lgamma((nu + 1.0) / 2.0)
            - math.lgamma(nu / 2.0)
            - 0.5 * math.log(nu * math.pi * sigma2)
            - ((nu + 1.0) / 2.0) * math.log(1.0 + z * z / nu)
        )
        return math.exp(log_p)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _log_student_t_pred(self, x: float, params: _NIGParams) -> float:
        """
        Log predictive density of x under the Student-t marginal implied
        by the NIG posterior.

        Predictive: t_{2*alpha}(x | mu, beta*(kappa+1)/(alpha*kappa))
        """
        nu = 2.0 * params.alpha
        sigma2 = params.beta * (params.kappa + 1.0) / (params.alpha * params.kappa)

        if sigma2 <= 0.0 or nu <= 0.0:
            return -1e10

        z = (x - params.mu) / math.sqrt(sigma2)
        log_p = (
            math.lgamma((nu + 1.0) / 2.0)
            - math.lgamma(nu / 2.0)
            - 0.5 * math.log(nu * math.pi * sigma2)
            - ((nu + 1.0) / 2.0) * math.log(1.0 + z * z / nu)
        )
        return log_p

    def _update_nig(self, params: _NIGParams, x: float) -> _NIGParams:
        """
        Bayesian update of NIG sufficient statistics after observing x.

        One-observation sequential update:
            kappa_new = kappa + 1
            mu_new    = (kappa * mu + x) / kappa_new
            alpha_new = alpha + 0.5
            beta_new  = beta + kappa*(x - mu)^2 / (2*(kappa+1))
        """
        kappa_new = params.kappa + 1.0
        mu_new = (params.kappa * params.mu + x) / kappa_new
        alpha_new = params.alpha + 0.5
        beta_new = params.beta + params.kappa * (x - params.mu) ** 2 / (2.0 * kappa_new)
        return _NIGParams(mu=mu_new, kappa=kappa_new, alpha=alpha_new, beta=beta_new, n=params.n + 1)

    def _update_state(self, cp_prob: float) -> None:
        """Transition the state machine based on the short-run probability mass."""
        if self._observations_seen < self._min_obs:
            self._state = RegimeState.WARMUP
            return

        if self._state == RegimeState.WARMUP:
            self._state = RegimeState.STABLE

        if self._state == RegimeState.STABLE:
            if cp_prob >= self._cp_threshold:
                self._state = RegimeState.TRANSITION
                self._transition_steps_remaining = self._stabilization_window
                self._total_changepoints += 1
                self._last_changepoint_idx = self._observations_seen
                logger.info(
                    "Entering TRANSITION at obs=%d | short_run_mass=%.4f",
                    self._observations_seen,
                    cp_prob,
                )
        elif self._state == RegimeState.TRANSITION:
            self._transition_steps_remaining -= 1
            if self._transition_steps_remaining <= 0:
                self._state = RegimeState.STABLE
                logger.info(
                    "Stabilized — returning to STABLE at obs=%d",
                    self._observations_seen,
                )

    def _estimate_regime_stats(self, map_run_length: int) -> tuple[float, float]:
        """
        Return (mean, variance) for the current regime via MAP run length NIG params.

        Posterior mean of the NIG is mu.
        Posterior mean of variance is beta/(alpha-1) when alpha > 1, else beta/alpha.
        """
        if map_run_length >= len(self._nig_params):
            map_run_length = len(self._nig_params) - 1

        p = self._nig_params[map_run_length]
        regime_mean = p.mu
        if p.alpha > 1.0:
            regime_var = p.beta / (p.alpha - 1.0)
        else:
            regime_var = p.beta / p.alpha
        return regime_mean, regime_var
