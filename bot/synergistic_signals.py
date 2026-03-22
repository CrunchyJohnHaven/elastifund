#!/usr/bin/env python3
"""
Synergistic Signal Optimizer
=============================
Discovers and optimally combines complementary trading signals using
reinforcement learning. Inspired by alphagen (RL-MLDM/alphagen).

Core insight: individual signals may be weak, but their *combination* can be
strong — IF they capture different information. This module explicitly
optimises for signal synergy: signals that are individually weak but jointly
strong.

Algorithm
---------
1. Compute standalone Sharpe for each candidate signal.
2. Compute pairwise Pearson correlations (low correlation = high synergy
   potential).
3. RL loop (epsilon-greedy exploration, policy-gradient update):
   a. Start with the best individual signal.
   b. Try add/remove/reweight actions.
   c. Evaluate combined Sharpe on the full series.
   d. Reward = improvement in combined Sharpe.
4. Within each candidate combination, run gradient descent (softmax
   parameterisation) to find optimal weights.
5. Track top-k combinations across all episodes.

Author: JJ (autonomous)
Date: 2026-03-21
"""

from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

logger = logging.getLogger("JJ.synergistic_signals")

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class Signal:
    """Metadata for a single input signal."""

    name: str
    values: list[float]          # Time-series of raw signal values
    standalone_sharpe: float     # Annualised Sharpe when used alone


@dataclass
class SignalCombination:
    """A weighted combination of signals with performance metrics."""

    signals: list[str]                      # Names of included signals
    weights: list[float]                    # Optimal weights (sum to 1, positive)
    combined_sharpe: float                  # Joint annualised Sharpe ratio
    synergy_score: float                    # combined_sharpe - max(standalone_sharpes)
    correlation_matrix: list[list[float]]   # Pairwise Pearson correlations

    def predict(self, signal_values: dict[str, float]) -> float:
        """Apply weights to current signal values and return combined score.

        Unknown signal names are treated as zero (graceful degradation).
        """
        total = 0.0
        for name, w in zip(self.signals, self.weights):
            total += w * signal_values.get(name, 0.0)
        return total


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _annualisation_factor(n: int) -> float:
    """Return sqrt(252) unconditionally — all series are treated as daily."""
    return math.sqrt(252)


def _safe_sharpe(returns: np.ndarray) -> float:
    """Compute annualised Sharpe; return 0.0 for degenerate series."""
    if len(returns) < 2:
        return 0.0
    std = float(np.std(returns, ddof=1))
    if std < 1e-12:
        return 0.0
    return float(np.mean(returns) / std) * _annualisation_factor(len(returns))


def _softmax(logits: np.ndarray) -> np.ndarray:
    """Numerically stable softmax."""
    shifted = logits - np.max(logits)
    exp = np.exp(shifted)
    return exp / exp.sum()


def _pearson(a: np.ndarray, b: np.ndarray) -> float:
    """Pearson correlation coefficient; returns 0.0 on degenerate inputs.

    Uses numpy's corrcoef for consistency (sample covariance / sample stds).
    """
    if len(a) < 2 or len(b) < 2:
        return 0.0
    std_a = float(np.std(a, ddof=1))
    std_b = float(np.std(b, ddof=1))
    if std_a < 1e-12 or std_b < 1e-12:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


# ---------------------------------------------------------------------------
# Main optimiser
# ---------------------------------------------------------------------------


class SynergisticSignalOptimizer:
    """
    Uses a simple policy-gradient RL approach:
    - State:  current signal combination + recent performance
    - Action: add signal / remove signal / reweight
    - Reward: improvement in combined Sharpe ratio
    """

    def __init__(
        self,
        max_signals: int = 5,
        episodes: int = 200,
        learning_rate: float = 0.01,
        discount_factor: float = 0.99,
        exploration_rate: float = 0.3,
        exploration_decay: float = 0.995,
        min_synergy: float = 0.1,
        random_seed: int = 42,
    ) -> None:
        self.max_signals = max_signals
        self.episodes = episodes
        self.learning_rate = learning_rate
        self.discount_factor = discount_factor
        self.exploration_rate = exploration_rate
        self.exploration_decay = exploration_decay
        self.min_synergy = min_synergy
        self.random_seed = random_seed

        # State built during fit()
        self._signal_names: list[str] = []
        self._standalone_sharpes: dict[str, float] = {}
        self._corr_matrix: list[list[float]] = []
        self._top_k: list[SignalCombination] = []
        self._best: Optional[SignalCombination] = None
        # Track exploration rate decay across episodes (stored for introspection)
        self._episode_exploration_rates: list[float] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fit(
        self,
        signals: dict[str, list[float]],
        target: list[float],
        signal_names: Optional[list[str]] = None,
    ) -> SignalCombination:
        """Find the optimal signal combination.

        Parameters
        ----------
        signals:
            Mapping of signal name → time-series values.  All series must have
            the same length as *target*.
        target:
            Target variable (trade P&L or binary outcome).  Used to compute
            long/short returns from each signal.
        signal_names:
            Explicit ordering of signal names.  If None, uses sorted keys of
            *signals*.

        Returns
        -------
        Best SignalCombination found.
        """
        rng = random.Random(self.random_seed)
        np.random.seed(self.random_seed)

        names = signal_names if signal_names is not None else sorted(signals.keys())
        self._signal_names = names

        # Align lengths — truncate to shortest
        min_len = min(len(target), *(len(signals[n]) for n in names))
        target_arr = np.array(target[:min_len], dtype=float)
        sig_arrays: dict[str, np.ndarray] = {
            n: np.array(signals[n][:min_len], dtype=float) for n in names
        }

        # Phase 1: standalone performance
        for n in names:
            self._standalone_sharpes[n] = self._compute_standalone_sharpe(
                sig_arrays[n].tolist(), target_arr.tolist()
            )

        # Phase 2: pairwise correlations
        self._corr_matrix = self._correlation_matrix(
            {n: sig_arrays[n].tolist() for n in names}
        )

        # Phase 3: RL loop
        # Start from the best individual signal
        best_start = max(names, key=lambda n: self._standalone_sharpes[n])
        current_set: list[str] = [best_start]
        current_weights = self._optimize_weights(
            {n: sig_arrays[n].tolist() for n in names},
            target_arr.tolist(),
            current_set,
        )
        current_sharpe = self._compute_combined_sharpe(
            {n: sig_arrays[n].tolist() for n in names},
            current_weights,
            target_arr.tolist(),
        )

        best_sharpe = current_sharpe
        best_set = list(current_set)
        best_weights = dict(current_weights)

        # Policy parameters: log-odds weight for "add" vs "remove" action
        policy_logits: dict[str, float] = {n: 0.0 for n in names}

        epsilon = self.exploration_rate
        self._episode_exploration_rates = []

        for episode in range(self.episodes):
            self._episode_exploration_rates.append(epsilon)

            # Collect candidate actions
            candidates_add = [n for n in names if n not in current_set]
            candidates_remove = [n for n in current_set if len(current_set) > 1]

            if not candidates_add and not candidates_remove:
                epsilon *= self.exploration_decay
                continue

            # Choose action: explore randomly or exploit policy
            if rng.random() < epsilon:
                # Explore: pick a random add/remove
                all_actions: list[tuple[str, str]] = (
                    [("add", n) for n in candidates_add]
                    + [("remove", n) for n in candidates_remove]
                )
                action_type, action_signal = rng.choice(all_actions)
            else:
                # Exploit: pick highest-value action by policy logits
                scored_add = [
                    (policy_logits.get(n, 0.0), "add", n)
                    for n in candidates_add
                    if len(current_set) < self.max_signals
                ]
                scored_remove = [
                    (-policy_logits.get(n, 0.0), "remove", n)
                    for n in candidates_remove
                ]
                all_scored = scored_add + scored_remove
                if not all_scored:
                    epsilon *= self.exploration_decay
                    continue
                all_scored.sort(key=lambda x: x[0], reverse=True)
                _, action_type, action_signal = all_scored[0]

            # Apply action to build trial set
            trial_set = list(current_set)
            if action_type == "add" and action_signal not in trial_set:
                if len(trial_set) < self.max_signals:
                    trial_set.append(action_signal)
            elif action_type == "remove" and action_signal in trial_set:
                trial_set.remove(action_signal)

            if not trial_set:
                epsilon *= self.exploration_decay
                continue

            # Optimise weights for the trial set
            trial_weights = self._optimize_weights(
                {n: sig_arrays[n].tolist() for n in names},
                target_arr.tolist(),
                trial_set,
            )
            trial_sharpe = self._compute_combined_sharpe(
                {n: sig_arrays[n].tolist() for n in names},
                trial_weights,
                target_arr.tolist(),
            )

            # Reward = improvement in Sharpe
            reward = trial_sharpe - current_sharpe

            # Policy gradient update
            if action_type == "add":
                policy_logits[action_signal] += (
                    self.learning_rate * reward * self.discount_factor
                )
            else:
                policy_logits[action_signal] -= (
                    self.learning_rate * reward * self.discount_factor
                )

            # Accept move if it improved (greedy acceptance)
            if trial_sharpe > current_sharpe:
                current_set = trial_set
                current_weights = trial_weights
                current_sharpe = trial_sharpe

            # Track global best
            if trial_sharpe > best_sharpe:
                best_sharpe = trial_sharpe
                best_set = list(trial_set)
                best_weights = dict(trial_weights)

            # Track top-k (keep best SignalCombination objects)
            self._maybe_add_to_top_k(
                trial_set,
                trial_weights,
                trial_sharpe,
                {n: sig_arrays[n].tolist() for n in names},
            )

            epsilon *= self.exploration_decay

        # Build and store the best combination
        standalone_sharpes_used = [
            self._standalone_sharpes.get(n, 0.0) for n in best_set
        ]
        synergy = self._compute_synergy(best_sharpe, standalone_sharpes_used)
        corr_sub = self._sub_correlation_matrix(
            best_set,
            {n: sig_arrays[n].tolist() for n in names},
        )
        best_combo = SignalCombination(
            signals=best_set,
            weights=[best_weights.get(n, 1.0 / len(best_set)) for n in best_set],
            combined_sharpe=best_sharpe,
            synergy_score=synergy,
            correlation_matrix=corr_sub,
        )
        self._best = best_combo

        # Ensure best is in top-k
        self._maybe_add_to_top_k(
            best_set,
            best_weights,
            best_sharpe,
            {n: sig_arrays[n].tolist() for n in names},
        )

        logger.info(
            "fit complete: best_set=%s sharpe=%.4f synergy=%.4f",
            best_set,
            best_sharpe,
            synergy,
        )
        return best_combo

    def get_top_combinations(self, k: int = 5) -> list[SignalCombination]:
        """Return top-k combinations found during optimisation.

        Sorted by combined Sharpe descending.  If fewer than *k* were found,
        returns all that are available.
        """
        sorted_top = sorted(
            self._top_k, key=lambda c: c.combined_sharpe, reverse=True
        )
        return sorted_top[:k]

    def analyze_synergy(self) -> dict:
        """Return analysis of which signal pairs have highest synergy potential.

        Returns
        -------
        dict with keys:
            pairwise_synergy: {(s1, s2): synergy_score}
            best_pair: (str, str)
            correlation_rankings: [(s1, s2, corr)] sorted by |corr| ascending
            diversity_score: float — mean of (1 - |corr|) across all pairs
        """
        names = self._signal_names
        n = len(names)
        if n < 2:
            return {
                "pairwise_synergy": {},
                "best_pair": (names[0], names[0]) if names else ("", ""),
                "correlation_rankings": [],
                "diversity_score": 0.0,
            }

        corr = self._corr_matrix
        pairwise_synergy: dict[tuple[str, str], float] = {}
        correlation_rankings: list[tuple[str, str, float]] = []

        for i in range(n):
            for j in range(i + 1, n):
                c = corr[i][j]
                # Synergy potential: low correlation, both signals have some
                # standalone Sharpe.  Proxy: average standalone Sharpe * (1-|corr|)
                avg_sharpe = (
                    self._standalone_sharpes.get(names[i], 0.0)
                    + self._standalone_sharpes.get(names[j], 0.0)
                ) / 2.0
                pair_synergy = avg_sharpe * (1.0 - abs(c))
                pairwise_synergy[(names[i], names[j])] = pair_synergy
                correlation_rankings.append((names[i], names[j], c))

        best_pair = max(pairwise_synergy, key=lambda p: pairwise_synergy[p])
        correlation_rankings.sort(key=lambda x: abs(x[2]))

        # Diversity score: mean of (1 - |corr|) across all unique pairs
        diversity_score = float(
            np.mean([1.0 - abs(c) for _, _, c in correlation_rankings])
        ) if correlation_rankings else 0.0

        return {
            "pairwise_synergy": pairwise_synergy,
            "best_pair": best_pair,
            "correlation_rankings": correlation_rankings,
            "diversity_score": diversity_score,
        }

    def predict(self, current_signals: dict[str, float]) -> float:
        """Apply the best combination to current signal values.

        Returns
        -------
        Weighted combination score.  Raises RuntimeError if fit() has not been
        called.
        """
        if self._best is None:
            raise RuntimeError("fit() must be called before predict()")
        return self._best.predict(current_signals)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_standalone_sharpe(
        self, signal: list[float], target: list[float]
    ) -> float:
        """Sharpe ratio of a single signal used as a long/flat trading rule.

        Signal > 0 → position = +1 (long), signal <= 0 → position = 0 (flat).
        Returns = position * target.
        """
        sig = np.array(signal, dtype=float)
        tgt = np.array(target, dtype=float)
        min_len = min(len(sig), len(tgt))
        sig = sig[:min_len]
        tgt = tgt[:min_len]
        position = (sig > 0).astype(float)
        returns = position * tgt
        return _safe_sharpe(returns)

    def _compute_combined_sharpe(
        self,
        signals: dict[str, list[float]],
        weights: dict[str, float],
        target: list[float],
    ) -> float:
        """Sharpe of a weighted combination used as a long/flat trading rule."""
        names_used = list(weights.keys())
        if not names_used:
            return 0.0

        arrays = [np.array(signals[n], dtype=float) for n in names_used]
        wt = np.array([weights[n] for n in names_used], dtype=float)
        tgt = np.array(target, dtype=float)

        min_len = min(len(tgt), *(len(a) for a in arrays))
        arrays = [a[:min_len] for a in arrays]
        tgt = tgt[:min_len]

        combined = np.stack(arrays, axis=0)   # (n_signals, T)
        composite = (wt[:, None] * combined).sum(axis=0)   # (T,)
        position = (composite > 0).astype(float)
        returns = position * tgt
        return _safe_sharpe(returns)

    def _compute_synergy(
        self, combined_sharpe: float, standalone_sharpes: list[float]
    ) -> float:
        """Synergy = combined_sharpe - max(standalone_sharpes).

        Positive synergy means the combination is better than any individual.
        """
        if not standalone_sharpes:
            return 0.0
        return combined_sharpe - max(standalone_sharpes)

    def _correlation_matrix(
        self, signals: dict[str, list[float]]
    ) -> list[list[float]]:
        """Full pairwise Pearson correlation matrix in self._signal_names order."""
        names = self._signal_names
        n = len(names)
        arrays = [np.array(signals.get(name, []), dtype=float) for name in names]
        min_len = min((len(a) for a in arrays), default=0)
        arrays = [a[:min_len] for a in arrays]

        matrix: list[list[float]] = []
        for i in range(n):
            row: list[float] = []
            for j in range(n):
                if i == j:
                    row.append(1.0)
                elif j < i:
                    row.append(matrix[j][i])  # symmetric
                else:
                    row.append(_pearson(arrays[i], arrays[j]))
            matrix.append(row)
        return matrix

    def _sub_correlation_matrix(
        self, subset: list[str], signals: dict[str, list[float]]
    ) -> list[list[float]]:
        """Pairwise Pearson correlation matrix restricted to *subset* signals."""
        arrays = [np.array(signals[n], dtype=float) for n in subset]
        min_len = min((len(a) for a in arrays), default=0)
        arrays = [a[:min_len] for a in arrays]
        n = len(subset)
        matrix: list[list[float]] = []
        for i in range(n):
            row: list[float] = []
            for j in range(n):
                if i == j:
                    row.append(1.0)
                elif j < i:
                    row.append(matrix[j][i])
                else:
                    row.append(_pearson(arrays[i], arrays[j]))
            matrix.append(row)
        return matrix

    def _optimize_weights(
        self,
        signals: dict[str, list[float]],
        target: list[float],
        signal_subset: list[str],
    ) -> dict[str, float]:
        """Given a fixed signal subset, find optimal weights via gradient descent
        on negative Sharpe.

        Uses softmax parameterisation so weights are always positive and sum to 1.
        """
        k = len(signal_subset)
        if k == 0:
            return {}
        if k == 1:
            return {signal_subset[0]: 1.0}

        # Prepare arrays once
        arrays = [np.array(signals[n], dtype=float) for n in signal_subset]
        tgt = np.array(target, dtype=float)
        min_len = min(len(tgt), *(len(a) for a in arrays))
        arrays = [a[:min_len] for a in arrays]
        tgt = tgt[:min_len]
        stacked = np.stack(arrays, axis=0)  # (k, T)

        logits = np.zeros(k, dtype=float)
        best_sharpe = -np.inf
        best_logits = logits.copy()

        lr = self.learning_rate * 10   # weight optimisation uses larger step
        n_iters = 100

        for _ in range(n_iters):
            wt = _softmax(logits)
            composite = (wt[:, None] * stacked).sum(axis=0)
            position = (composite > 0).astype(float)
            returns = position * tgt

            sharpe = _safe_sharpe(returns)
            if sharpe > best_sharpe:
                best_sharpe = sharpe
                best_logits = logits.copy()

            # Numerical gradient on negative Sharpe w.r.t. logits
            grad = np.zeros(k, dtype=float)
            eps = 1e-4
            for idx in range(k):
                logits_p = logits.copy()
                logits_p[idx] += eps
                wt_p = _softmax(logits_p)
                comp_p = (wt_p[:, None] * stacked).sum(axis=0)
                pos_p = (comp_p > 0).astype(float)
                ret_p = pos_p * tgt
                sharpe_p = _safe_sharpe(ret_p)
                grad[idx] = (sharpe_p - sharpe) / eps   # gradient of Sharpe

            # Gradient ascent (maximise Sharpe)
            logits = logits + lr * grad

        wt_final = _softmax(best_logits)
        return {name: float(wt_final[i]) for i, name in enumerate(signal_subset)}

    def _maybe_add_to_top_k(
        self,
        trial_set: list[str],
        trial_weights: dict[str, float],
        trial_sharpe: float,
        signals: dict[str, list[float]],
        k: int = 20,
    ) -> None:
        """Insert trial combination into self._top_k if it qualifies."""
        standalone = [
            self._standalone_sharpes.get(n, 0.0) for n in trial_set
        ]
        synergy = self._compute_synergy(trial_sharpe, standalone)
        corr_sub = self._sub_correlation_matrix(trial_set, signals)
        combo = SignalCombination(
            signals=list(trial_set),
            weights=[trial_weights.get(n, 1.0 / len(trial_set)) for n in trial_set],
            combined_sharpe=trial_sharpe,
            synergy_score=synergy,
            correlation_matrix=corr_sub,
        )
        self._top_k.append(combo)
        # Keep only top-k by Sharpe to bound memory
        self._top_k.sort(key=lambda c: c.combined_sharpe, reverse=True)
        if len(self._top_k) > k:
            self._top_k = self._top_k[:k]
