#!/usr/bin/env python3
"""
Ensemble Toxicity Detector with Thompson Sampling
==================================================
Implements an adaptive ensemble of three toxicity detectors — VPIN, PIN,
and Entropy-based — weighted via Thompson Sampling so the ensemble learns
which detector to trust per market regime.

Replaces single-threshold VPIN with a multi-signal adaptive gate that
continuously updates detector credibility based on ground-truth feedback.

Thompson Sampling mechanics:
  - Each detector maintains Beta(α, β) posterior
  - α = correct toxic predictions, β = incorrect predictions
  - At score time: sample θ_i ~ Beta(α_i, β_i) for each detector
  - Weight_i = θ_i / Σ θ_j
  - Combined score = Σ weight_i * score_i

Ground truth arrives post-trade: if we lost money within 5 minutes of the
signal, the market was "toxic". Call update_reward() or update_all_rewards()
with the outcome.

Author: JJ (autonomous)
Date: 2026-03-21
"""

import logging
import math
from abc import ABC, abstractmethod
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

logger = logging.getLogger("JJ.ensemble_toxicity")


# ---------------------------------------------------------------------------
# Core data structures
# ---------------------------------------------------------------------------

@dataclass
class TradeTick:
    """A single trade from the CLOB WebSocket. Mirrors vpin_toxicity.TradeTick."""
    timestamp: float    # Unix timestamp
    price: float        # Execution price (0-1)
    size: float         # Number of shares / contracts
    side: str           # "buy" or "sell" (aggressor side)
    market_id: str = ""


@dataclass
class EnsembleScore:
    """Full output from one EnsembleToxicity.score() call."""
    combined_score: float           # Weighted ensemble toxicity in [0, 1]
    is_toxic: bool                  # combined_score > toxic_threshold
    detector_scores: dict[str, float]   # Individual detector scores
    detector_weights: dict[str, float]  # Thompson Sampling weights used
    selected_detector: str          # Detector with highest sampled θ this round
    confidence: float               # How certain the ensemble is (0-1)


# ---------------------------------------------------------------------------
# Detector interface
# ---------------------------------------------------------------------------

class ToxicityDetector(ABC):
    """Abstract base class for all toxicity detectors."""

    @abstractmethod
    def score(self, trades: list[TradeTick]) -> float:
        """Return toxicity score in [0, 1]. Higher = more toxic."""

    @abstractmethod
    def name(self) -> str:
        """Detector name for logging and keying."""


# ---------------------------------------------------------------------------
# Detector 1: VPIN
# ---------------------------------------------------------------------------

class VPINDetector(ToxicityDetector):
    """
    Volume-Synchronized Probability of Informed Trading.

    Groups trades into equal-volume buckets, then computes the mean absolute
    buy/sell imbalance across a rolling window of buckets.

    High VPIN → one side consistently dominates → informed flow.
    """

    def __init__(self, bucket_size: float = 500.0, window_buckets: int = 10):
        self._bucket_size = max(bucket_size, 1.0)
        self._window = max(window_buckets, 1)

    def name(self) -> str:
        return "vpin"

    def score(self, trades: list[TradeTick]) -> float:
        if not trades:
            return 0.5

        # Fill buckets greedily
        buckets: list[tuple[float, float]] = []  # (buy_vol, sell_vol)
        buy_vol = 0.0
        sell_vol = 0.0
        accumulated = 0.0

        for trade in trades:
            remaining = trade.size
            while remaining > 0:
                space = self._bucket_size - accumulated
                fill = min(remaining, space)
                if trade.side == "buy":
                    buy_vol += fill
                else:
                    sell_vol += fill
                accumulated += fill
                remaining -= fill

                if accumulated >= self._bucket_size:
                    buckets.append((buy_vol, sell_vol))
                    buy_vol = 0.0
                    sell_vol = 0.0
                    accumulated = 0.0

        if not buckets:
            return 0.5

        # Rolling window: last `window` buckets
        window = buckets[-self._window:]
        imbalances = []
        for bv, sv in window:
            total = bv + sv
            if total > 0:
                imbalances.append(abs(bv - sv) / total)

        if not imbalances:
            return 0.5

        return float(np.mean(imbalances))


# ---------------------------------------------------------------------------
# Detector 2: PIN (Easley et al., method-of-moments)
# ---------------------------------------------------------------------------

class PINDetector(ToxicityDetector):
    """
    Probability of Informed Trading — simplified Easley et al. estimator.

    Model:
      - With prob α, an information event occurs.
      - Given info event, bad news with prob δ (only sell-side informed),
        good news otherwise (only buy-side informed).
      - Informed traders arrive at rate μ; uninformed at rate ε on each side.

    Method-of-moments: fit α, δ, μ, ε to observed (B, S) counts.

    PIN = αμ / (αμ + 2ε)
    """

    def name(self) -> str:
        return "pin"

    def score(self, trades: list[TradeTick]) -> float:
        if not trades:
            return 0.5

        buys = sum(1 for t in trades if t.side == "buy")
        sells = sum(1 for t in trades if t.side == "sell")
        n = buys + sells

        if n == 0:
            return 0.5

        # Method-of-moments estimates
        # E[B] = α(1-δ)μ + ε,  E[S] = αδμ + ε
        # Sum:  E[B]+E[S] = αμ + 2ε
        # Diff: E[B]-E[S] = α(1-2δ)μ
        #
        # Simplified: assume δ=0.5 (symmetric info), so directional term vanishes.
        # Then: E[B] = E[S] = αμ/2 + ε
        # Total rate = αμ + 2ε  => uninformed rate ε = (n/2 - informed_arrivals/2)
        #
        # Use imbalance to infer informed component:
        total = float(n)
        imbalance = abs(buys - sells) / total  # fraction of directional flow

        # Uninformed flow is the symmetric component
        min_side = float(min(buys, sells))
        uninformed_est = min_side / (total / 2.0) if total > 0 else 1.0  # ratio 0-1

        # ε ~ symmetric per-side rate, μ ~ informed rate (excess directional)
        # alpha estimate: proportion of volume that is "directed"
        alpha_est = imbalance  # [0, 1]
        epsilon_est = max(min_side / total, 1e-6)
        mu_est = max((abs(buys - sells) / total), 1e-6)

        pin = (alpha_est * mu_est) / (alpha_est * mu_est + 2.0 * epsilon_est)
        return float(np.clip(pin, 0.0, 1.0))


# ---------------------------------------------------------------------------
# Detector 3: Entropy
# ---------------------------------------------------------------------------

class EntropyDetector(ToxicityDetector):
    """
    Information-theoretic toxicity detector.

    Compute Shannon entropy of the trade size distribution across discrete bins.

    Low entropy  → concentrated sizes → institutional / informed (TOXIC)
    High entropy → diverse sizes      → retail / uninformed (SAFE)

    Score = 1 - (H / H_max)  so high score = toxic.
    """

    def __init__(self, n_bins: int = 10):
        self._n_bins = max(n_bins, 2)

    def name(self) -> str:
        return "entropy"

    def score(self, trades: list[TradeTick]) -> float:
        if not trades:
            return 0.5

        sizes = np.array([t.size for t in trades], dtype=float)

        # Edge case: all identical sizes → zero entropy → max toxicity score
        if np.std(sizes) < 1e-10:
            return 1.0

        # Bin sizes into equal-width histogram
        counts, _ = np.histogram(sizes, bins=self._n_bins)
        counts = counts[counts > 0].astype(float)
        probs = counts / counts.sum()

        # Shannon entropy
        h = -float(np.sum(probs * np.log(probs + 1e-12)))
        h_max = math.log(self._n_bins)  # maximum possible entropy

        if h_max < 1e-10:
            return 0.5

        # Invert: low entropy → high toxicity score
        normalized_entropy = h / h_max
        return float(np.clip(1.0 - normalized_entropy, 0.0, 1.0))


# ---------------------------------------------------------------------------
# Thompson Sampling Ensemble
# ---------------------------------------------------------------------------

@dataclass
class _DetectorState:
    """Beta posterior state for one detector."""
    alpha: float = 1.0   # successes (correct toxic predictions)
    beta: float = 1.0    # failures  (incorrect predictions)

    @property
    def expected_weight(self) -> float:
        """Mean of Beta(α, β) = α / (α + β)."""
        return self.alpha / (self.alpha + self.beta)

    def sample(self, rng: np.random.Generator) -> float:
        """Sample θ from Beta(α, β)."""
        return float(rng.beta(self.alpha, self.beta))


class EnsembleToxicity:
    """
    Adaptive ensemble of VPIN, PIN, and Entropy toxicity detectors.

    Thompson Sampling weights are updated as ground truth arrives. Detectors
    that correctly identify toxic markets accumulate credibility; those that
    mis-fire lose it. The ensemble automatically migrates toward whichever
    detector fits the current market regime best.

    Usage:
        ensemble = EnsembleToxicity(toxic_threshold=0.65)
        result = ensemble.score(trades)
        if result.is_toxic:
            cancel_maker_orders(market_id)
        # ... 5 minutes later, after PnL is known ...
        ensemble.update_all_rewards(was_toxic=True)
    """

    def __init__(
        self,
        toxic_threshold: float = 0.65,
        bucket_size: float = 500.0,
        window_buckets: int = 10,
        min_trades: int = 20,
        prior_alpha: float = 1.0,
        prior_beta: float = 1.0,
        seed: Optional[int] = None,
    ):
        """
        Args:
            toxic_threshold:  Combined score above which is_toxic=True.
            bucket_size:      VPIN bucket volume size.
            window_buckets:   VPIN rolling window in buckets.
            min_trades:       Minimum trades required to produce a scored result.
                              Fewer → returns neutral score (0.5).
            prior_alpha:      Beta prior α for all detectors (initial successes).
            prior_beta:       Beta prior β for all detectors (initial failures).
            seed:             Optional RNG seed for reproducibility in tests.
        """
        self._toxic_threshold = toxic_threshold
        self._min_trades = min_trades
        self._prior_alpha = prior_alpha
        self._prior_beta = prior_beta
        self._rng = np.random.default_rng(seed)

        # Detectors (order is stable; dict preserves insertion order in Py3.7+)
        self._detectors: dict[str, ToxicityDetector] = {
            "vpin": VPINDetector(bucket_size=bucket_size, window_buckets=window_buckets),
            "pin": PINDetector(),
            "entropy": EntropyDetector(),
        }

        # Thompson Sampling posteriors
        self._states: dict[str, _DetectorState] = {
            name: _DetectorState(alpha=prior_alpha, beta=prior_beta)
            for name in self._detectors
        }

        # Bookkeeping
        self._total_updates: int = 0
        self._toxic_update_count: int = 0
        self._last_scores: dict[str, float] = {}
        self._last_weights: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def score(self, trades: list[TradeTick]) -> EnsembleScore:
        """
        Run all detectors and combine via Thompson Sampling weights.

        If fewer than min_trades are provided, returns a neutral score
        (0.5) without updating posteriors.

        Steps:
            1. Each detector produces a score in [0, 1].
            2. Sample θ_i ~ Beta(α_i, β_i) for each detector.
            3. weight_i = θ_i / Σ θ_j
            4. combined = Σ weight_i * score_i
            5. Build and return EnsembleScore.
        """
        if len(trades) < self._min_trades:
            neutral_weights = {n: 1.0 / len(self._detectors) for n in self._detectors}
            return EnsembleScore(
                combined_score=0.5,
                is_toxic=False,
                detector_scores={n: 0.5 for n in self._detectors},
                detector_weights=neutral_weights,
                selected_detector=list(self._detectors.keys())[0],
                confidence=0.0,
            )

        # Step 1: get individual detector scores
        raw_scores: dict[str, float] = {}
        for name, detector in self._detectors.items():
            try:
                s = detector.score(trades)
                raw_scores[name] = float(np.clip(s, 0.0, 1.0))
            except Exception:
                logger.exception("Detector %s raised an exception; using 0.5", name)
                raw_scores[name] = 0.5

        # Step 2: Thompson Sampling — sample from each Beta posterior
        sampled: dict[str, float] = {
            name: state.sample(self._rng)
            for name, state in self._states.items()
        }

        # Step 3: normalise to get weights
        total_sampled = sum(sampled.values())
        if total_sampled < 1e-12:
            weights = {n: 1.0 / len(self._detectors) for n in self._detectors}
        else:
            weights = {n: v / total_sampled for n, v in sampled.items()}

        # Step 4: weighted average score
        combined = float(sum(weights[n] * raw_scores[n] for n in self._detectors))
        combined = float(np.clip(combined, 0.0, 1.0))

        # Detector with the highest sampled θ is "selected" this round
        selected = max(sampled, key=lambda n: sampled[n])

        # Confidence: how strongly the detectors agree (1 - std of scores)
        score_values = list(raw_scores.values())
        agreement = 1.0 - float(np.std(score_values))
        # Also scale by distance from 0.5 — near-0.5 ensemble is low-confidence
        distance_from_neutral = abs(combined - 0.5) * 2.0
        confidence = float(np.clip(agreement * distance_from_neutral, 0.0, 1.0))

        is_toxic = combined > self._toxic_threshold

        # Cache for update_all_rewards
        self._last_scores = raw_scores.copy()
        self._last_weights = weights.copy()

        if is_toxic:
            logger.warning(
                "ENSEMBLE TOXIC: score=%.3f (vpin=%.3f pin=%.3f entropy=%.3f) "
                "selected=%s confidence=%.3f",
                combined,
                raw_scores.get("vpin", 0.5),
                raw_scores.get("pin", 0.5),
                raw_scores.get("entropy", 0.5),
                selected,
                confidence,
            )
            self._emit_telemetry(combined, raw_scores, weights, selected)

        return EnsembleScore(
            combined_score=combined,
            is_toxic=is_toxic,
            detector_scores=raw_scores,
            detector_weights=weights,
            selected_detector=selected,
            confidence=confidence,
        )

    def update_reward(self, detector_name: str, correct: bool) -> None:
        """
        Update Thompson Sampling posterior for a single detector.

        Args:
            detector_name: One of "vpin", "pin", "entropy".
            correct:        True if the detector's toxic prediction was correct.
        """
        if detector_name not in self._states:
            logger.warning("Unknown detector name for update: %s", detector_name)
            return

        state = self._states[detector_name]
        if correct:
            state.alpha += 1.0
            logger.debug("Detector %s rewarded (α=%.1f β=%.1f)", detector_name, state.alpha, state.beta)
        else:
            state.beta += 1.0
            logger.debug("Detector %s penalised (α=%.1f β=%.1f)", detector_name, state.alpha, state.beta)

    def update_all_rewards(self, was_toxic: bool) -> None:
        """
        Update all detectors based on whether the market was actually toxic.

        A detector is "correct" if:
          - was_toxic=True  and detector score > 0.5 (it predicted toxic)
          - was_toxic=False and detector score <= 0.5 (it predicted safe)

        Falls back to 0.5 for any detector not in the last score cache.
        """
        self._total_updates += 1
        if was_toxic:
            self._toxic_update_count += 1

        for name in self._detectors:
            last_score = self._last_scores.get(name, 0.5)
            predicted_toxic = last_score > 0.5
            correct = (predicted_toxic == was_toxic)
            self.update_reward(name, correct)

    def get_weights(self) -> dict[str, float]:
        """Return current expected weights (mean of Beta posteriors)."""
        total = sum(s.expected_weight for s in self._states.values())
        if total < 1e-12:
            return {n: 1.0 / len(self._detectors) for n in self._detectors}
        return {n: s.expected_weight / total for n, s in self._states.items()}

    def get_diagnostics(self) -> dict:
        """
        Return full diagnostic information.

        Schema:
            {
                'detector_stats': {
                    name: {'alpha': float, 'beta': float, 'expected_weight': float}
                },
                'total_updates': int,
                'toxic_rate': float,
                'ensemble_agreement': float,
            }
        """
        stats: dict[str, dict] = {}
        for name, state in self._states.items():
            stats[name] = {
                "alpha": state.alpha,
                "beta": state.beta,
                "expected_weight": state.expected_weight,
            }

        # Agreement: standard deviation of last cached scores (lower = more agreement)
        if self._last_scores:
            vals = list(self._last_scores.values())
            agreement = float(1.0 - np.std(vals))
        else:
            agreement = 1.0  # no data yet → technically fully "agreed" at neutral

        toxic_rate = (
            self._toxic_update_count / self._total_updates
            if self._total_updates > 0
            else 0.0
        )

        return {
            "detector_stats": stats,
            "total_updates": self._total_updates,
            "toxic_rate": toxic_rate,
            "ensemble_agreement": float(np.clip(agreement, 0.0, 1.0)),
        }

    def reset_priors(self) -> None:
        """Reset all detectors to uniform Beta(prior_alpha, prior_beta) priors."""
        for state in self._states.values():
            state.alpha = self._prior_alpha
            state.beta = self._prior_beta
        self._total_updates = 0
        self._toxic_update_count = 0
        self._last_scores = {}
        self._last_weights = {}
        logger.info("EnsembleToxicity: all priors reset to Beta(%.1f, %.1f)",
                    self._prior_alpha, self._prior_beta)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _emit_telemetry(
        self,
        combined: float,
        scores: dict[str, float],
        weights: dict[str, float],
        selected: str,
    ) -> None:
        """Emit telemetry to elastic_client if available."""
        if elastic_client is None:
            return
        try:
            payload = {
                "event": "ensemble_toxicity_detected",
                "combined_score": combined,
                "detector_scores": scores,
                "detector_weights": weights,
                "selected_detector": selected,
            }
            elastic_client.emit("toxicity", payload)  # type: ignore[attr-defined]
        except Exception:
            pass  # telemetry is best-effort
