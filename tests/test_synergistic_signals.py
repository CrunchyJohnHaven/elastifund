#!/usr/bin/env python3
"""
Tests for bot/synergistic_signals.py
=====================================
All tests are deterministic (fixed random seed) and make zero external calls.

Run with:
    pytest tests/test_synergistic_signals.py -v
"""

from __future__ import annotations

import math
import sys
import os

import numpy as np
import pytest

# Ensure project root is on sys.path so both import styles work in the test
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bot.synergistic_signals import (
    Signal,
    SignalCombination,
    SynergisticSignalOptimizer,
    _pearson,
    _safe_sharpe,
    _softmax,
)


# ---------------------------------------------------------------------------
# Fixtures & synthetic data generators
# ---------------------------------------------------------------------------

N = 300  # length of synthetic time series


def _make_random_series(seed: int, scale: float = 1.0) -> list[float]:
    rng = np.random.default_rng(seed)
    return (rng.standard_normal(N) * scale).tolist()


def _make_synergistic_pair(n: int = N) -> tuple[list[float], list[float], list[float]]:
    """Return (signal_A, signal_B, target) where A and B are individually weak
    but A+B is strongly predictive of target.

    A = sin(t), B = cos(t), target = sign(sin(t) + cos(t)).
    """
    t = np.linspace(0, 4 * math.pi, n)
    signal_a = np.sin(t).tolist()
    signal_b = np.cos(t).tolist()
    combined = np.sin(t) + np.cos(t)
    target = np.sign(combined).tolist()
    return signal_a, signal_b, target


# ---------------------------------------------------------------------------
# Low-level helper tests
# ---------------------------------------------------------------------------


class TestSafeSharp:
    def test_known_positive_sharpe(self):
        """Uniform positive returns → Sharpe = mean/std * sqrt(252) > 0."""
        rng = np.random.default_rng(0)
        ret = rng.standard_normal(252) * 0.01 + 0.005   # positive drift
        sharpe = _safe_sharpe(ret)
        assert sharpe > 0.0

    def test_zero_variance_returns_zero(self):
        """Constant returns → std = 0 → Sharpe = 0."""
        ret = np.full(100, 0.01)
        assert _safe_sharpe(ret) == 0.0

    def test_single_element_returns_zero(self):
        """Need at least 2 points; single-element series returns 0."""
        assert _safe_sharpe(np.array([0.05])) == 0.0

    def test_zero_mean_negative_returns(self):
        """Series with negative mean should produce negative Sharpe."""
        rng = np.random.default_rng(7)
        ret = rng.standard_normal(252) * 0.01 - 0.005
        sharpe = _safe_sharpe(ret)
        assert sharpe < 0.0

    def test_annualisation(self):
        """Sharpe should scale by sqrt(252)."""
        ret = np.array([0.01, -0.01, 0.01, -0.01] * 50, dtype=float)
        sharpe = _safe_sharpe(ret)
        mean_r = float(np.mean(ret))
        std_r = float(np.std(ret, ddof=1))
        expected = mean_r / std_r * math.sqrt(252)
        assert abs(sharpe - expected) < 1e-9


class TestSoftmax:
    def test_sums_to_one(self):
        logits = np.array([1.0, 2.0, 0.5, -1.0])
        result = _softmax(logits)
        assert abs(result.sum() - 1.0) < 1e-9

    def test_all_positive(self):
        logits = np.array([0.5, -2.0, 3.0])
        result = _softmax(logits)
        assert np.all(result > 0)

    def test_numerically_stable_large_logits(self):
        logits = np.array([1000.0, 999.0, 998.0])
        result = _softmax(logits)
        assert np.isfinite(result).all()
        assert abs(result.sum() - 1.0) < 1e-9


class TestPearson:
    def test_perfect_correlation(self):
        a = np.arange(10, dtype=float)
        b = np.arange(10, dtype=float)
        assert abs(_pearson(a, b) - 1.0) < 1e-9

    def test_perfect_anti_correlation(self):
        a = np.arange(10, dtype=float)
        b = -np.arange(10, dtype=float)
        assert abs(_pearson(a, b) + 1.0) < 1e-9

    def test_zero_variance(self):
        a = np.ones(10)
        b = np.arange(10, dtype=float)
        assert _pearson(a, b) == 0.0


# ---------------------------------------------------------------------------
# SignalCombination.predict
# ---------------------------------------------------------------------------


class TestSignalCombinationPredict:
    def test_applies_weights_correctly(self):
        combo = SignalCombination(
            signals=["a", "b"],
            weights=[0.6, 0.4],
            combined_sharpe=1.0,
            synergy_score=0.5,
            correlation_matrix=[[1.0, 0.0], [0.0, 1.0]],
        )
        result = combo.predict({"a": 2.0, "b": 3.0})
        assert abs(result - (0.6 * 2.0 + 0.4 * 3.0)) < 1e-9

    def test_missing_signal_treated_as_zero(self):
        combo = SignalCombination(
            signals=["a", "b"],
            weights=[0.5, 0.5],
            combined_sharpe=1.0,
            synergy_score=0.2,
            correlation_matrix=[[1.0, 0.0], [0.0, 1.0]],
        )
        result = combo.predict({"a": 4.0})   # "b" not provided
        assert abs(result - 2.0) < 1e-9     # 0.5*4 + 0.5*0

    def test_single_signal(self):
        combo = SignalCombination(
            signals=["x"],
            weights=[1.0],
            combined_sharpe=0.8,
            synergy_score=0.0,
            correlation_matrix=[[1.0]],
        )
        assert abs(combo.predict({"x": 3.5}) - 3.5) < 1e-9


# ---------------------------------------------------------------------------
# Optimizer — correlation matrix
# ---------------------------------------------------------------------------


class TestCorrelationMatrix:
    def test_diagonal_is_one(self):
        opt = SynergisticSignalOptimizer(random_seed=42)
        signals = {
            "a": _make_random_series(0),
            "b": _make_random_series(1),
            "c": _make_random_series(2),
        }
        opt._signal_names = ["a", "b", "c"]
        matrix = opt._correlation_matrix(signals)
        for i in range(3):
            assert abs(matrix[i][i] - 1.0) < 1e-9

    def test_matrix_is_symmetric(self):
        opt = SynergisticSignalOptimizer(random_seed=42)
        signals = {
            "a": _make_random_series(0),
            "b": _make_random_series(1),
            "c": _make_random_series(2),
        }
        opt._signal_names = ["a", "b", "c"]
        matrix = opt._correlation_matrix(signals)
        for i in range(3):
            for j in range(3):
                assert abs(matrix[i][j] - matrix[j][i]) < 1e-9

    def test_perfectly_correlated_signals(self):
        series = list(range(N))
        opt = SynergisticSignalOptimizer(random_seed=42)
        opt._signal_names = ["a", "b"]
        matrix = opt._correlation_matrix({"a": series, "b": series})
        assert abs(matrix[0][1] - 1.0) < 1e-9

    def test_anti_correlated_signals(self):
        series = list(range(N))
        neg_series = [-x for x in series]
        opt = SynergisticSignalOptimizer(random_seed=42)
        opt._signal_names = ["a", "b"]
        matrix = opt._correlation_matrix({"a": series, "b": neg_series})
        assert abs(matrix[0][1] + 1.0) < 1e-9


# ---------------------------------------------------------------------------
# Optimizer — standalone Sharpe
# ---------------------------------------------------------------------------


class TestStandaloneSharp:
    def test_known_directional_signal(self):
        """Signal that perfectly predicts sign of target should have high Sharpe."""
        rng = np.random.default_rng(99)
        target = rng.standard_normal(252).tolist()
        signal = [v + 0.001 for v in target]   # nearly perfect predictor
        opt = SynergisticSignalOptimizer(random_seed=42)
        sharpe = opt._compute_standalone_sharpe(signal, target)
        assert sharpe > 1.0   # should be very high

    def test_anti_correlated_signal_lower(self):
        """Signal that predicts opposite sign should have low (negative) Sharpe."""
        rng = np.random.default_rng(11)
        target = rng.standard_normal(252).tolist()
        signal = [-v - 0.001 for v in target]   # opposite predictor
        opt = SynergisticSignalOptimizer(random_seed=42)
        sharpe = opt._compute_standalone_sharpe(signal, target)
        assert sharpe < 0.0


# ---------------------------------------------------------------------------
# Optimizer — combined Sharpe
# ---------------------------------------------------------------------------


class TestCombinedSharpe:
    def test_uniform_weights_equal_sharpe(self):
        """With uniform weights and identical signals, combined == standalone."""
        rng = np.random.default_rng(5)
        target = rng.standard_normal(252).tolist()
        signal = [v + 0.001 for v in target]
        opt = SynergisticSignalOptimizer(random_seed=42)
        standalone = opt._compute_standalone_sharpe(signal, target)
        combined = opt._compute_combined_sharpe(
            {"s": signal}, {"s": 1.0}, target
        )
        assert abs(combined - standalone) < 1e-6

    def test_two_signals_uniform_weights(self):
        """Combined Sharpe with two identical signals should equal standalone."""
        rng = np.random.default_rng(6)
        target = rng.standard_normal(252).tolist()
        signal = [v + 0.002 for v in target]
        opt = SynergisticSignalOptimizer(random_seed=42)
        standalone = opt._compute_standalone_sharpe(signal, target)
        combined = opt._compute_combined_sharpe(
            {"a": signal, "b": signal},
            {"a": 0.5, "b": 0.5},
            target,
        )
        # Composite is same direction as signal, so Sharpe should be equal
        assert abs(combined - standalone) < 1e-6


# ---------------------------------------------------------------------------
# Optimizer — synergy score
# ---------------------------------------------------------------------------


class TestSynergyScore:
    def test_positive_synergy_when_combined_better(self):
        opt = SynergisticSignalOptimizer(random_seed=42)
        synergy = opt._compute_synergy(2.0, [0.8, 1.5])
        assert synergy == pytest.approx(0.5)

    def test_negative_synergy_when_combined_worse(self):
        opt = SynergisticSignalOptimizer(random_seed=42)
        synergy = opt._compute_synergy(1.0, [1.3, 0.9])
        assert synergy == pytest.approx(-0.3)

    def test_zero_synergy_equal_performance(self):
        opt = SynergisticSignalOptimizer(random_seed=42)
        synergy = opt._compute_synergy(1.5, [0.5, 1.5])
        assert synergy == pytest.approx(0.0)

    def test_empty_standalone_returns_zero(self):
        opt = SynergisticSignalOptimizer(random_seed=42)
        assert opt._compute_synergy(1.5, []) == 0.0


# ---------------------------------------------------------------------------
# Optimizer — weight optimization
# ---------------------------------------------------------------------------


class TestWeightOptimization:
    def test_single_signal_weight_is_one(self):
        rng = np.random.default_rng(0)
        target = rng.standard_normal(200).tolist()
        signal = [v + 0.01 for v in target]
        opt = SynergisticSignalOptimizer(random_seed=42)
        weights = opt._optimize_weights({"s": signal}, target, ["s"])
        assert abs(weights["s"] - 1.0) < 1e-9

    def test_weights_sum_to_one(self):
        rng = np.random.default_rng(0)
        target = rng.standard_normal(200).tolist()
        signals = {
            "a": _make_random_series(1),
            "b": _make_random_series(2),
            "c": _make_random_series(3),
        }
        opt = SynergisticSignalOptimizer(random_seed=42)
        weights = opt._optimize_weights(signals, target, ["a", "b", "c"])
        total = sum(weights.values())
        assert abs(total - 1.0) < 1e-6

    def test_weights_are_positive(self):
        rng = np.random.default_rng(0)
        target = rng.standard_normal(200).tolist()
        signals = {
            "a": _make_random_series(1),
            "b": _make_random_series(2),
        }
        opt = SynergisticSignalOptimizer(random_seed=42)
        weights = opt._optimize_weights(signals, target, ["a", "b"])
        for w in weights.values():
            assert w > 0.0

    def test_empty_subset_returns_empty(self):
        rng = np.random.default_rng(0)
        target = rng.standard_normal(200).tolist()
        opt = SynergisticSignalOptimizer(random_seed=42)
        result = opt._optimize_weights({}, target, [])
        assert result == {}


# ---------------------------------------------------------------------------
# Optimizer — fit on synthetic synergistic signals
# ---------------------------------------------------------------------------


class TestFitSynergisticSignals:
    def test_synergistic_pair_detected(self):
        """sin(t) and cos(t) individually predict sign(sin+cos) weakly but
        together they predict it perfectly.  After fit(), combined Sharpe should
        exceed both standalone Sharpes."""
        sig_a, sig_b, target = _make_synergistic_pair(N)
        opt = SynergisticSignalOptimizer(
            episodes=100, random_seed=42, exploration_rate=0.5
        )
        result = opt.fit({"a": sig_a, "b": sig_b}, target)
        assert result.combined_sharpe >= max(
            opt._standalone_sharpes["a"], opt._standalone_sharpes["b"]
        )

    def test_synergy_score_positive_for_synergistic_pair(self):
        sig_a, sig_b, target = _make_synergistic_pair(N)
        opt = SynergisticSignalOptimizer(
            episodes=100, random_seed=42, exploration_rate=0.5
        )
        result = opt.fit({"a": sig_a, "b": sig_b}, target)
        # Synergy score = combined_sharpe - max(standalones)
        # For a truly synergistic pair this should be >= 0
        assert result.synergy_score >= 0.0

    def test_fit_returns_signal_combination_type(self):
        sig_a, sig_b, target = _make_synergistic_pair(N)
        opt = SynergisticSignalOptimizer(episodes=50, random_seed=42)
        result = opt.fit({"a": sig_a, "b": sig_b}, target)
        assert isinstance(result, SignalCombination)

    def test_fit_weights_are_valid(self):
        sig_a, sig_b, target = _make_synergistic_pair(N)
        opt = SynergisticSignalOptimizer(episodes=50, random_seed=42)
        result = opt.fit({"a": sig_a, "b": sig_b}, target)
        assert abs(sum(result.weights) - 1.0) < 1e-6
        for w in result.weights:
            assert w > 0.0

    def test_single_signal_fit(self):
        """Edge case: one signal.  Combination should be just that signal."""
        rng = np.random.default_rng(0)
        target = rng.standard_normal(200).tolist()
        signal = [v + 0.01 for v in target]
        opt = SynergisticSignalOptimizer(episodes=50, random_seed=42)
        result = opt.fit({"solo": signal}, target)
        assert result.signals == ["solo"]
        assert abs(result.weights[0] - 1.0) < 1e-6

    def test_correlation_matrix_in_result(self):
        """Result must include a valid symmetric correlation matrix."""
        sig_a, sig_b, target = _make_synergistic_pair(N)
        opt = SynergisticSignalOptimizer(episodes=50, random_seed=42)
        result = opt.fit({"a": sig_a, "b": sig_b}, target)
        n = len(result.signals)
        assert len(result.correlation_matrix) == n
        for row in result.correlation_matrix:
            assert len(row) == n
        for i in range(n):
            assert abs(result.correlation_matrix[i][i] - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# Optimizer — get_top_combinations
# ---------------------------------------------------------------------------


class TestGetTopCombinations:
    def test_returns_k_results(self):
        sig_a, sig_b, target = _make_synergistic_pair(N)
        opt = SynergisticSignalOptimizer(episodes=100, random_seed=42)
        opt.fit({"a": sig_a, "b": sig_b}, target)
        top5 = opt.get_top_combinations(k=5)
        # May have fewer than 5 distinct combinations; at least 1
        assert len(top5) >= 1
        assert len(top5) <= 5

    def test_sorted_by_sharpe_descending(self):
        sig_a, sig_b, target = _make_synergistic_pair(N)
        opt = SynergisticSignalOptimizer(episodes=100, random_seed=42)
        opt.fit({"a": sig_a, "b": sig_b}, target)
        top = opt.get_top_combinations(k=10)
        for i in range(len(top) - 1):
            assert top[i].combined_sharpe >= top[i + 1].combined_sharpe

    def test_k_larger_than_available_returns_all(self):
        rng = np.random.default_rng(0)
        target = rng.standard_normal(100).tolist()
        signal = [v + 0.01 for v in target]
        opt = SynergisticSignalOptimizer(episodes=2, random_seed=42)
        opt.fit({"s": signal}, target)
        # Only 1 signal → very few combinations
        result = opt.get_top_combinations(k=100)
        assert len(result) >= 1


# ---------------------------------------------------------------------------
# Optimizer — analyze_synergy
# ---------------------------------------------------------------------------


class TestAnalyzeSynergy:
    def _run_fit(self) -> SynergisticSignalOptimizer:
        sig_a, sig_b, target = _make_synergistic_pair(N)
        extra = _make_random_series(77)
        opt = SynergisticSignalOptimizer(episodes=80, random_seed=42)
        opt.fit({"a": sig_a, "b": sig_b, "c": extra}, target)
        return opt

    def test_returns_required_keys(self):
        opt = self._run_fit()
        analysis = opt.analyze_synergy()
        assert "pairwise_synergy" in analysis
        assert "best_pair" in analysis
        assert "correlation_rankings" in analysis
        assert "diversity_score" in analysis

    def test_pairwise_synergy_has_all_pairs(self):
        opt = self._run_fit()
        analysis = opt.analyze_synergy()
        pairs = set(analysis["pairwise_synergy"].keys())
        expected_count = 3   # 3 choose 2
        assert len(pairs) == expected_count

    def test_best_pair_is_tuple_of_signal_names(self):
        opt = self._run_fit()
        analysis = opt.analyze_synergy()
        best = analysis["best_pair"]
        assert isinstance(best, tuple)
        assert len(best) == 2
        assert best[0] in opt._signal_names
        assert best[1] in opt._signal_names

    def test_best_pair_matches_highest_synergy(self):
        opt = self._run_fit()
        analysis = opt.analyze_synergy()
        best_pair = analysis["best_pair"]
        best_synergy = analysis["pairwise_synergy"][best_pair]
        for pair, synergy in analysis["pairwise_synergy"].items():
            assert synergy <= best_synergy + 1e-9

    def test_correlation_rankings_sorted_by_abs_corr(self):
        opt = self._run_fit()
        analysis = opt.analyze_synergy()
        rankings = analysis["correlation_rankings"]
        for i in range(len(rankings) - 1):
            assert abs(rankings[i][2]) <= abs(rankings[i + 1][2]) + 1e-9

    def test_diversity_score_between_zero_and_one(self):
        opt = self._run_fit()
        analysis = opt.analyze_synergy()
        ds = analysis["diversity_score"]
        assert 0.0 <= ds <= 1.0

    def test_single_signal_analyze_synergy(self):
        """Single signal → no pairs, graceful output."""
        rng = np.random.default_rng(0)
        target = rng.standard_normal(100).tolist()
        signal = [v + 0.01 for v in target]
        opt = SynergisticSignalOptimizer(episodes=5, random_seed=42)
        opt.fit({"s": signal}, target)
        analysis = opt.analyze_synergy()
        assert analysis["pairwise_synergy"] == {}
        assert analysis["diversity_score"] == 0.0


# ---------------------------------------------------------------------------
# Optimizer — predict
# ---------------------------------------------------------------------------


class TestPredict:
    def test_predict_before_fit_raises(self):
        opt = SynergisticSignalOptimizer(random_seed=42)
        with pytest.raises(RuntimeError, match="fit\\(\\)"):
            opt.predict({"a": 1.0})

    def test_predict_after_fit_returns_float(self):
        sig_a, sig_b, target = _make_synergistic_pair(N)
        opt = SynergisticSignalOptimizer(episodes=50, random_seed=42)
        opt.fit({"a": sig_a, "b": sig_b}, target)
        result = opt.predict({"a": 0.5, "b": -0.3})
        assert isinstance(result, float)
        assert math.isfinite(result)

    def test_predict_consistent_with_manual_calculation(self):
        sig_a, sig_b, target = _make_synergistic_pair(N)
        opt = SynergisticSignalOptimizer(episodes=50, random_seed=42)
        best = opt.fit({"a": sig_a, "b": sig_b}, target)
        current = {"a": 1.0, "b": 2.0}
        predicted = opt.predict(current)
        expected = best.predict(current)
        assert abs(predicted - expected) < 1e-9


# ---------------------------------------------------------------------------
# Exploration decay
# ---------------------------------------------------------------------------


class TestExplorationDecay:
    def test_exploration_rate_decreases_over_episodes(self):
        """Epsilon must be strictly non-increasing across all episodes."""
        sig_a, sig_b, target = _make_synergistic_pair(N)
        opt = SynergisticSignalOptimizer(
            episodes=50,
            random_seed=42,
            exploration_rate=0.5,
            exploration_decay=0.99,
        )
        opt.fit({"a": sig_a, "b": sig_b}, target)
        rates = opt._episode_exploration_rates
        assert len(rates) > 0
        for i in range(len(rates) - 1):
            assert rates[i] >= rates[i + 1] - 1e-12

    def test_exploration_decay_is_applied(self):
        """After many episodes, exploration rate should be well below initial."""
        sig_a, sig_b, target = _make_synergistic_pair(N)
        opt = SynergisticSignalOptimizer(
            episodes=100,
            random_seed=42,
            exploration_rate=0.8,
            exploration_decay=0.95,
        )
        opt.fit({"a": sig_a, "b": sig_b}, target)
        initial = opt._episode_exploration_rates[0]
        final = opt._episode_exploration_rates[-1]
        assert final < initial


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_same_seed_same_result(self):
        sig_a, sig_b, target = _make_synergistic_pair(N)
        opt1 = SynergisticSignalOptimizer(episodes=50, random_seed=7)
        opt2 = SynergisticSignalOptimizer(episodes=50, random_seed=7)
        r1 = opt1.fit({"a": sig_a, "b": sig_b}, target)
        r2 = opt2.fit({"a": sig_a, "b": sig_b}, target)
        assert r1.signals == r2.signals
        assert r1.combined_sharpe == r2.combined_sharpe
        for w1, w2 in zip(r1.weights, r2.weights):
            assert abs(w1 - w2) < 1e-9

    def test_different_seeds_may_differ(self):
        sig_a, sig_b, target = _make_synergistic_pair(N)
        opt1 = SynergisticSignalOptimizer(episodes=50, random_seed=1)
        opt2 = SynergisticSignalOptimizer(episodes=50, random_seed=99)
        r1 = opt1.fit({"a": sig_a, "b": sig_b}, target)
        r2 = opt2.fit({"a": sig_a, "b": sig_b}, target)
        # They might happen to agree, but this is a sanity check that seeds are used
        # We just verify both return valid combinations
        assert isinstance(r1, SignalCombination)
        assert isinstance(r2, SignalCombination)


# ---------------------------------------------------------------------------
# Max signals constraint
# ---------------------------------------------------------------------------


class TestMaxSignals:
    def test_combination_never_exceeds_max_signals(self):
        """No returned combination should have more signals than max_signals."""
        rng = np.random.default_rng(0)
        target = rng.standard_normal(N).tolist()
        signals = {f"s{i}": _make_random_series(i) for i in range(8)}
        opt = SynergisticSignalOptimizer(
            max_signals=3, episodes=80, random_seed=42
        )
        result = opt.fit(signals, target)
        assert len(result.signals) <= 3

    def test_top_k_combinations_respect_max_signals(self):
        rng = np.random.default_rng(0)
        target = rng.standard_normal(N).tolist()
        signals = {f"s{i}": _make_random_series(i) for i in range(6)}
        opt = SynergisticSignalOptimizer(
            max_signals=2, episodes=60, random_seed=42
        )
        opt.fit(signals, target)
        for combo in opt.get_top_combinations(k=10):
            assert len(combo.signals) <= 2
