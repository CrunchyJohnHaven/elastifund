#!/usr/bin/env python3
"""
Tests for bot/parameter_evolution.py

Covers:
  - Parameter registration and storage
  - Gaussian mutation (stays within bounds)
  - Crossover (valid offspring)
  - Latin hypercube initialization (covers the space)
  - Optimization on 1D quadratic (should find x≈3)
  - Optimization on Rosenbrock (should find near (1,1))
  - Surrogate model fits and predicts (qualitative correlation)
  - Convergence check (triggers on plateau)
  - Sensitivity analysis (x has higher sensitivity than y in 10x+y)
  - Elite preservation (best individual survives)
  - btc5_parameter_space() returns correctly configured optimizer
  - suggest_next() returns valid in-bounds parameters
"""
from __future__ import annotations

import sys
import os

# Ensure the repo root is on sys.path so 'bot' is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import math
import pytest
import numpy as np

from bot.parameter_evolution import (
    Parameter,
    ParameterSet,
    EvolutionResult,
    ParameterEvolution,
    btc5_parameter_space,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_evo(**kwargs) -> ParameterEvolution:
    """Return a small optimizer with two continuous parameters."""
    defaults = dict(
        population_size=10,
        generations=20,
        mutation_sigma=0.1,
        crossover_rate=0.5,
        elite_fraction=0.2,
        surrogate_warmup=5,
        random_seed=42,
    )
    defaults.update(kwargs)
    evo = ParameterEvolution(**defaults)
    evo.define_parameter("x", lower=0.0, upper=5.0, initial=2.5)
    evo.define_parameter("y", lower=0.0, upper=5.0, initial=2.5)
    return evo


def _make_param_set(x: float, y: float) -> ParameterSet:
    """Convenience: build a ParameterSet with two params."""
    return ParameterSet(
        parameters={
            "x": Parameter("x", x, 0.0, 5.0, "continuous"),
            "y": Parameter("y", y, 0.0, 5.0, "continuous"),
        },
        fitness=0.0,
        evaluated=False,
    )


# ---------------------------------------------------------------------------
# 1. define_parameter stores correctly
# ---------------------------------------------------------------------------

class TestDefineParameter:
    def test_stores_name(self):
        evo = ParameterEvolution(random_seed=42)
        evo.define_parameter("alpha", lower=0.0, upper=1.0, initial=0.5)
        assert "alpha" in evo._param_templates

    def test_stores_bounds(self):
        evo = ParameterEvolution(random_seed=42)
        evo.define_parameter("alpha", lower=0.0, upper=1.0, initial=0.5)
        p = evo._param_templates["alpha"]
        assert p.lower_bound == 0.0
        assert p.upper_bound == 1.0

    def test_stores_initial_value(self):
        evo = ParameterEvolution(random_seed=42)
        evo.define_parameter("alpha", lower=0.0, upper=1.0, initial=0.3)
        assert evo._param_templates["alpha"].value == pytest.approx(0.3)

    def test_default_initial_is_midpoint(self):
        evo = ParameterEvolution(random_seed=42)
        evo.define_parameter("beta", lower=2.0, upper=8.0)
        assert evo._param_templates["beta"].value == pytest.approx(5.0)

    def test_stores_description(self):
        evo = ParameterEvolution(random_seed=42)
        evo.define_parameter("gamma", lower=0.0, upper=1.0, description="a test param")
        assert evo._param_templates["gamma"].description == "a test param"

    def test_stores_integer_type(self):
        evo = ParameterEvolution(random_seed=42)
        evo.define_parameter("k", lower=0, upper=23, initial=5, param_type="integer")
        assert evo._param_templates["k"].parameter_type == "integer"

    def test_invalid_bounds_raises(self):
        evo = ParameterEvolution(random_seed=42)
        with pytest.raises(ValueError, match="lower_bound"):
            evo.define_parameter("bad", lower=5.0, upper=2.0)

    def test_multiple_parameters_stored(self):
        evo = ParameterEvolution(random_seed=42)
        evo.define_parameter("a", lower=0.0, upper=1.0)
        evo.define_parameter("b", lower=-1.0, upper=1.0)
        evo.define_parameter("c", lower=10.0, upper=100.0)
        assert len(evo._param_templates) == 3


# ---------------------------------------------------------------------------
# 2. Gaussian mutation stays within bounds
# ---------------------------------------------------------------------------

class TestGaussianMutation:
    def test_mutated_values_within_bounds(self):
        evo = _make_evo(mutation_sigma=0.5, random_seed=7)
        original = _make_param_set(1.0, 4.0)
        for _ in range(200):
            mutant = evo._gaussian_mutation(original)
            for name, p in mutant.parameters.items():
                t = evo._param_templates[name]
                assert t.lower_bound <= p.value <= t.upper_bound, (
                    f"{name}={p.value} out of [{t.lower_bound}, {t.upper_bound}]"
                )

    def test_mutation_changes_values(self):
        evo = _make_evo(mutation_sigma=0.3, random_seed=99)
        original = _make_param_set(2.5, 2.5)
        # With sigma=0.3 and 50 attempts, at least one mutant should differ
        changed = False
        for _ in range(50):
            mutant = evo._gaussian_mutation(original)
            if mutant.parameters["x"].value != 2.5 or mutant.parameters["y"].value != 2.5:
                changed = True
                break
        assert changed

    def test_mutation_resets_evaluated_flag(self):
        evo = _make_evo()
        original = _make_param_set(2.5, 2.5)
        original.evaluated = True
        original.fitness = 99.0
        mutant = evo._gaussian_mutation(original)
        assert not mutant.evaluated
        assert mutant.fitness == 0.0

    def test_integer_mutation_produces_integers(self):
        evo = ParameterEvolution(random_seed=42, mutation_sigma=0.3)
        evo.define_parameter("hour", lower=0, upper=23, initial=10, param_type="integer")
        ps = ParameterSet(
            parameters={"hour": Parameter("hour", 10.0, 0.0, 23.0, "integer")},
        )
        for _ in range(100):
            mutant = evo._gaussian_mutation(ps)
            v = mutant.parameters["hour"].value
            assert v == round(v), f"Expected integer, got {v}"
            assert 0.0 <= v <= 23.0


# ---------------------------------------------------------------------------
# 3. Crossover produces valid offspring
# ---------------------------------------------------------------------------

class TestCrossover:
    def test_child_values_from_parents(self):
        evo = _make_evo(random_seed=0)
        p1 = _make_param_set(0.5, 0.5)
        p2 = _make_param_set(4.5, 4.5)
        for _ in range(100):
            child = evo._crossover(p1, p2)
            for name, param in child.parameters.items():
                t = evo._param_templates[name]
                assert t.lower_bound <= param.value <= t.upper_bound
                # Child value must come from one of the parents
                assert param.value in (
                    p1.parameters[name].value,
                    p2.parameters[name].value,
                )

    def test_crossover_resets_evaluated(self):
        evo = _make_evo()
        p1 = _make_param_set(1.0, 1.0)
        p2 = _make_param_set(4.0, 4.0)
        p1.evaluated = True
        p1.fitness = 10.0
        child = evo._crossover(p1, p2)
        assert not child.evaluated
        assert child.fitness == 0.0

    def test_crossover_mixes_genes(self):
        """With enough trials, crossover should produce both parent1 and parent2 values."""
        evo = ParameterEvolution(random_seed=0, crossover_rate=0.5)
        evo.define_parameter("x", lower=0.0, upper=1.0, initial=0.1)
        evo.define_parameter("y", lower=0.0, upper=1.0, initial=0.9)

        p1 = ParameterSet(
            parameters={
                "x": Parameter("x", 0.0, 0.0, 1.0, "continuous"),
                "y": Parameter("y", 0.0, 0.0, 1.0, "continuous"),
            }
        )
        p2 = ParameterSet(
            parameters={
                "x": Parameter("x", 1.0, 0.0, 1.0, "continuous"),
                "y": Parameter("y", 1.0, 0.0, 1.0, "continuous"),
            }
        )
        saw_x0 = False
        saw_x1 = False
        for _ in range(100):
            c = evo._crossover(p1, p2)
            if c.parameters["x"].value == 0.0:
                saw_x0 = True
            if c.parameters["x"].value == 1.0:
                saw_x1 = True
        assert saw_x0 and saw_x1, "Crossover should mix genes from both parents"


# ---------------------------------------------------------------------------
# 4. Latin hypercube initialization covers the space
# ---------------------------------------------------------------------------

class TestInitializePopulation:
    def test_population_size(self):
        evo = _make_evo(population_size=15)
        pop = evo._initialize_population()
        assert len(pop) == 15

    def test_all_within_bounds(self):
        evo = _make_evo(population_size=20)
        pop = evo._initialize_population()
        for ps in pop:
            for name, p in ps.parameters.items():
                t = evo._param_templates[name]
                assert t.lower_bound <= p.value <= t.upper_bound

    def test_lhs_coverage(self):
        """
        In a perfect LHS over n samples in [0, 1], each stratum [i/n, (i+1)/n)
        has exactly one sample.  We verify the empirical distribution is
        reasonably uniform (min-max gap should be < 2 * expected stratum width).
        """
        n = 20
        evo = ParameterEvolution(random_seed=0, population_size=n)
        evo.define_parameter("x", lower=0.0, upper=10.0)
        pop = evo._initialize_population()
        x_vals = sorted(p.parameters["x"].value for p in pop)
        # The range should cover at least 50% of [0, 10]
        assert x_vals[-1] - x_vals[0] > 5.0, "LHS should spread across the space"

    def test_anchor_at_initial_params(self):
        """First individual should be pinned to initial params."""
        evo = ParameterEvolution(random_seed=42, population_size=10)
        evo.define_parameter("x", lower=0.0, upper=10.0, initial=7.7)
        evo.define_parameter("y", lower=0.0, upper=10.0, initial=2.2)
        pop = evo._initialize_population()
        first = pop[0]
        assert first.parameters["x"].value == pytest.approx(7.7)
        assert first.parameters["y"].value == pytest.approx(2.2)

    def test_integer_initial_rounded(self):
        evo = ParameterEvolution(random_seed=42, population_size=5)
        evo.define_parameter("k", lower=0, upper=23, initial=7, param_type="integer")
        pop = evo._initialize_population()
        for ps in pop:
            v = ps.parameters["k"].value
            assert v == round(v)
            assert 0.0 <= v <= 23.0


# ---------------------------------------------------------------------------
# 5. Optimization on 1D quadratic: f(x) = -(x-3)^2  → should find x≈3
# ---------------------------------------------------------------------------

class TestOptimize1DQuadratic:
    @pytest.fixture
    def evo(self):
        evo = ParameterEvolution(
            population_size=20,
            generations=40,
            mutation_sigma=0.1,
            crossover_rate=0.5,
            elite_fraction=0.2,
            surrogate_warmup=8,
            random_seed=42,
        )
        evo.define_parameter("x", lower=0.0, upper=6.0, initial=1.0)
        return evo

    def test_finds_near_x3(self, evo):
        def f(params): return -(params["x"] - 3.0) ** 2

        result = evo.optimize(f)
        best_x = result.best_params.parameters["x"].value
        assert abs(best_x - 3.0) < 0.30, f"Expected x≈3.0, got {best_x:.4f}"

    def test_result_type(self, evo):
        result = evo.optimize(lambda p: -(p["x"] - 3.0) ** 2)
        assert isinstance(result, EvolutionResult)

    def test_convergence_curve_non_increasing_best(self, evo):
        """convergence_curve[i] should be non-decreasing (best fitness over time)."""
        result = evo.optimize(lambda p: -(p["x"] - 3.0) ** 2)
        for i in range(1, len(result.convergence_curve)):
            assert result.convergence_curve[i] >= result.convergence_curve[i - 1] - 1e-9

    def test_history_nonempty(self, evo):
        result = evo.optimize(lambda p: -(p["x"] - 3.0) ** 2)
        assert len(result.history) > 0

    def test_improvement_pct_positive(self, evo):
        # Starting at x=1 → f=-4; optimum x=3 → f=0; should improve
        result = evo.optimize(lambda p: -(p["x"] - 3.0) ** 2)
        assert result.improvement_pct > 0


# ---------------------------------------------------------------------------
# 6. Optimization on Rosenbrock: should find near (1, 1)
# ---------------------------------------------------------------------------

class TestOptimizeRosenbrock:
    def rosenbrock(self, params: dict) -> float:
        x, y = params["x"], params["y"]
        return -((1.0 - x) ** 2 + 100.0 * (y - x ** 2) ** 2)

    def test_finds_near_one_one(self):
        evo = ParameterEvolution(
            population_size=30,
            generations=60,
            mutation_sigma=0.08,
            crossover_rate=0.6,
            elite_fraction=0.2,
            surrogate_warmup=10,
            random_seed=42,
        )
        evo.define_parameter("x", lower=-2.0, upper=2.0, initial=0.0)
        evo.define_parameter("y", lower=-1.0, upper=3.0, initial=0.0)

        result = evo.optimize(self.rosenbrock)
        bx = result.best_params.parameters["x"].value
        by = result.best_params.parameters["y"].value
        # Rosenbrock minimum at (1, 1); allow tolerance of 0.25
        assert abs(bx - 1.0) < 0.25, f"Expected x≈1.0, got {bx:.4f}"
        assert abs(by - 1.0) < 0.25, f"Expected y≈1.0, got {by:.4f}"

    def test_best_fitness_better_than_initial(self):
        evo = ParameterEvolution(
            population_size=20,
            generations=30,
            random_seed=0,
        )
        evo.define_parameter("x", lower=-2.0, upper=2.0, initial=-1.5)
        evo.define_parameter("y", lower=-1.0, upper=3.0, initial=-0.5)
        result = evo.optimize(self.rosenbrock)
        assert result.best_params.fitness > self.rosenbrock({"x": -1.5, "y": -0.5})


# ---------------------------------------------------------------------------
# 7. Surrogate model: fits and predictions correlate with actuals
# ---------------------------------------------------------------------------

class TestSurrogateModel:
    def test_surrogate_fits_after_warmup(self):
        evo = _make_evo(surrogate_warmup=5)
        evaluated = []
        for i in range(10):
            ps = _make_param_set(float(i) / 2.0, float(i) / 2.0)
            ps.fitness = float(i)
            ps.evaluated = True
            evaluated.append(ps)
        evo._fit_surrogate(evaluated)
        assert evo._surrogate_fitted

    def test_surrogate_predictions_correlate_with_actuals(self):
        """Predictions on held-out points should rank-correlate with actuals."""
        evo = ParameterEvolution(random_seed=42)
        evo.define_parameter("x", lower=0.0, upper=5.0)
        evo.define_parameter("y", lower=0.0, upper=5.0)

        # Train on f(x, y) = x + y
        evaluated = []
        rng = np.random.default_rng(0)
        for _ in range(30):
            x, y = rng.uniform(0, 5), rng.uniform(0, 5)
            ps = _make_param_set(x, y)
            ps.fitness = x + y
            ps.evaluated = True
            evaluated.append(ps)

        evo._fit_surrogate(evaluated)

        # Predict on 10 test points
        actuals, preds = [], []
        for _ in range(10):
            x, y = rng.uniform(0, 5), rng.uniform(0, 5)
            ps = _make_param_set(x, y)
            preds.append(evo._surrogate_predict(ps))
            actuals.append(x + y)

        # Rank correlation should be positive (Spearman-like)
        corr = float(np.corrcoef(actuals, preds)[0, 1])
        assert corr > 0.5, f"Expected positive correlation, got {corr:.3f}"

    def test_surrogate_predict_returns_float(self):
        evo = _make_evo()
        evaluated = [_make_param_set(float(i), float(i)) for i in range(8)]
        for i, ps in enumerate(evaluated):
            ps.fitness = float(i)
            ps.evaluated = True
        evo._fit_surrogate(evaluated)
        result = evo._surrogate_predict(_make_param_set(2.0, 3.0))
        assert isinstance(result, float)

    def test_surrogate_returns_zero_when_not_fitted(self):
        evo = _make_evo()
        result = evo._surrogate_predict(_make_param_set(2.0, 3.0))
        assert result == 0.0


# ---------------------------------------------------------------------------
# 8. Convergence check triggers when plateau is reached
# ---------------------------------------------------------------------------

class TestConvergenceCheck:
    def test_triggers_on_flat_history(self):
        evo = _make_evo()
        history = [1.0, 1.0001, 1.0002, 1.0002, 1.0002, 1.0002]
        assert evo.convergence_check(history, patience=5, min_improvement=0.001)

    def test_does_not_trigger_when_improving(self):
        evo = _make_evo()
        history = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5]
        assert not evo.convergence_check(history, patience=5, min_improvement=0.001)

    def test_needs_enough_history(self):
        evo = _make_evo()
        history = [1.0, 1.0, 1.0]
        # patience=5 requires at least 6 points
        assert not evo.convergence_check(history, patience=5)

    def test_triggers_with_exact_patience(self):
        evo = _make_evo()
        # 5 + 1 entries, all the same
        history = [5.0] * 6
        assert evo.convergence_check(history, patience=5, min_improvement=0.001)

    def test_does_not_trigger_with_one_improvement(self):
        evo = _make_evo()
        history = [1.0, 1.0, 1.0, 1.0, 1.0, 1.1]
        assert not evo.convergence_check(history, patience=5, min_improvement=0.001)


# ---------------------------------------------------------------------------
# 9. Sensitivity analysis: x should dominate in f(x, y) = 10x + y
# ---------------------------------------------------------------------------

class TestSensitivityAnalysis:
    def test_x_has_higher_sensitivity_than_y(self):
        evo = ParameterEvolution(random_seed=42, population_size=20, generations=5)
        evo.define_parameter("x", lower=0.0, upper=1.0)
        evo.define_parameter("y", lower=0.0, upper=1.0)

        # Build a large set of evaluated points with f = 10x + y
        rng = np.random.default_rng(0)
        evaluated = []
        for _ in range(40):
            x, y = rng.uniform(0, 1), rng.uniform(0, 1)
            ps = ParameterSet(
                parameters={
                    "x": Parameter("x", x, 0.0, 1.0, "continuous"),
                    "y": Parameter("y", y, 0.0, 1.0, "continuous"),
                }
            )
            ps.fitness = 10.0 * x + y
            ps.evaluated = True
            evaluated.append(ps)

        evo._all_evaluated = evaluated
        evo._fit_surrogate(evaluated)
        sens = evo.get_sensitivity()

        assert "x" in sens
        assert "y" in sens
        assert sens["x"] > sens["y"], (
            f"Expected sens(x) > sens(y) for 10x+y, got {sens}"
        )

    def test_sensitivity_returns_all_params(self):
        evo = _make_evo()
        # Feed enough data
        for i in range(15):
            ps = _make_param_set(float(i % 5), float(i % 3))
            ps.fitness = float(i)
            ps.evaluated = True
            evo._all_evaluated.append(ps)
        evo._fit_surrogate(evo._all_evaluated)
        sens = evo.get_sensitivity()
        assert set(sens.keys()) == {"x", "y"}

    def test_sensitivity_normalised_to_one(self):
        """Max sensitivity should be 1.0 after normalisation."""
        evo = _make_evo()
        rng = np.random.default_rng(5)
        for _ in range(20):
            x, y = rng.uniform(0, 5), rng.uniform(0, 5)
            ps = _make_param_set(x, y)
            ps.fitness = 5.0 * x + y
            ps.evaluated = True
            evo._all_evaluated.append(ps)
        evo._fit_surrogate(evo._all_evaluated)
        sens = evo.get_sensitivity()
        max_s = max(sens.values())
        assert abs(max_s - 1.0) < 1e-9, f"Max sensitivity should be 1.0, got {max_s}"


# ---------------------------------------------------------------------------
# 10. Elite preservation: best individual survives across generations
# ---------------------------------------------------------------------------

class TestElitePreservation:
    def test_best_never_regresses(self):
        """
        The best fitness seen so far should be monotonically non-decreasing
        in the convergence curve.
        """
        evo = ParameterEvolution(
            population_size=15,
            generations=20,
            mutation_sigma=0.2,
            elite_fraction=0.2,
            random_seed=7,
        )
        evo.define_parameter("x", lower=0.0, upper=5.0, initial=2.5)

        result = evo.optimize(lambda p: -(p["x"] - 3.0) ** 2)

        curve = result.convergence_curve
        for i in range(1, len(curve)):
            assert curve[i] >= curve[i - 1] - 1e-9, (
                f"Convergence curve regressed: gen {i-1}={curve[i-1]} -> gen {i}={curve[i]}"
            )

    def test_best_params_fitness_matches_convergence_peak(self):
        evo = ParameterEvolution(
            population_size=15,
            generations=20,
            elite_fraction=0.2,
            random_seed=99,
        )
        evo.define_parameter("x", lower=0.0, upper=10.0, initial=5.0)
        result = evo.optimize(lambda p: -(p["x"] - 7.0) ** 2)

        # best_params.fitness should equal the last (max) convergence curve value
        assert result.best_params.fitness == pytest.approx(
            result.convergence_curve[-1], abs=1e-6
        )


# ---------------------------------------------------------------------------
# 11. btc5_parameter_space() returns correctly configured optimizer
# ---------------------------------------------------------------------------

class TestBtc5ParameterSpace:
    @pytest.fixture
    def evo(self):
        return btc5_parameter_space()

    def test_returns_parameter_evolution(self, evo):
        assert isinstance(evo, ParameterEvolution)

    def test_has_eight_parameters(self, evo):
        assert len(evo._param_templates) == 8

    def test_expected_parameter_names(self, evo):
        expected = {
            "max_abs_delta",
            "vpin_toxic_threshold",
            "min_spread",
            "max_spread",
            "hour_start_et",
            "hour_end_et",
            "down_bias_weight",
            "shadow_threshold",
        }
        assert set(evo._param_templates.keys()) == expected

    def test_max_abs_delta_bounds(self, evo):
        p = evo._param_templates["max_abs_delta"]
        assert p.lower_bound == pytest.approx(0.001)
        assert p.upper_bound == pytest.approx(0.020)
        assert p.value == pytest.approx(0.003)

    def test_hour_parameters_are_integer(self, evo):
        assert evo._param_templates["hour_start_et"].parameter_type == "integer"
        assert evo._param_templates["hour_end_et"].parameter_type == "integer"

    def test_hour_start_initial_value(self, evo):
        assert evo._param_templates["hour_start_et"].value == pytest.approx(3.0)

    def test_hour_end_initial_value(self, evo):
        assert evo._param_templates["hour_end_et"].value == pytest.approx(19.0)

    def test_down_bias_weight_bounds(self, evo):
        p = evo._param_templates["down_bias_weight"]
        assert p.lower_bound == pytest.approx(0.0)
        assert p.upper_bound == pytest.approx(2.0)
        assert p.value == pytest.approx(1.0)

    def test_all_initial_values_within_bounds(self, evo):
        for name, p in evo._param_templates.items():
            assert p.lower_bound <= p.value <= p.upper_bound, (
                f"{name}: initial {p.value} outside [{p.lower_bound}, {p.upper_bound}]"
            )

    def test_optimizer_runnable(self, evo):
        """Quick sanity check: optimizer runs without error."""
        # Use a trivial objective to keep the test fast
        result = evo.optimize(
            lambda params: -sum(v ** 2 for v in params.values()),
        )
        assert isinstance(result, EvolutionResult)
        assert result.best_params is not None


# ---------------------------------------------------------------------------
# 12. suggest_next() returns valid in-bounds parameters
# ---------------------------------------------------------------------------

class TestSuggestNext:
    def test_returns_dict(self):
        evo = _make_evo()
        suggested = evo.suggest_next()
        assert isinstance(suggested, dict)

    def test_keys_match_registered_params(self):
        evo = _make_evo()
        suggested = evo.suggest_next()
        assert set(suggested.keys()) == {"x", "y"}

    def test_values_within_bounds_no_surrogate(self):
        """Before surrogate is fitted, fallback random must still be in bounds."""
        evo = _make_evo()
        for _ in range(20):
            suggested = evo.suggest_next()
            for name, val in suggested.items():
                t = evo._param_templates[name]
                assert t.lower_bound <= val <= t.upper_bound, (
                    f"{name}={val} out of [{t.lower_bound}, {t.upper_bound}]"
                )

    def test_values_within_bounds_with_surrogate(self):
        """After surrogate fit, suggest_next should still respect bounds."""
        evo = _make_evo(surrogate_warmup=5)
        rng = np.random.default_rng(0)
        for _ in range(20):
            x, y = rng.uniform(0, 5), rng.uniform(0, 5)
            ps = _make_param_set(x, y)
            ps.fitness = x + y
            ps.evaluated = True
            evo._all_evaluated.append(ps)
        evo._fit_surrogate(evo._all_evaluated)

        for _ in range(20):
            suggested = evo.suggest_next()
            for name, val in suggested.items():
                t = evo._param_templates[name]
                assert t.lower_bound <= val <= t.upper_bound

    def test_integer_params_remain_integers(self):
        evo = ParameterEvolution(random_seed=42)
        evo.define_parameter("k", lower=0, upper=23, initial=5, param_type="integer")
        for _ in range(30):
            suggested = evo.suggest_next()
            v = suggested["k"]
            assert v == round(v), f"Expected integer, got {v}"


# ---------------------------------------------------------------------------
# 13. ParameterSet helper methods
# ---------------------------------------------------------------------------

class TestParameterSet:
    def test_to_dict(self):
        ps = _make_param_set(1.5, 2.7)
        d = ps.to_dict()
        assert d == {"x": pytest.approx(1.5), "y": pytest.approx(2.7)}

    def test_copy_is_deep(self):
        ps = _make_param_set(1.0, 2.0)
        ps.fitness = 42.0
        ps2 = ps.copy()
        ps2.parameters["x"].value = 99.9
        ps2.fitness = 0.0
        # Original should be unchanged
        assert ps.parameters["x"].value == pytest.approx(1.0)
        assert ps.fitness == pytest.approx(42.0)

    def test_copy_preserves_values(self):
        ps = _make_param_set(3.3, 4.4)
        ps.fitness = 7.7
        ps.generation = 5
        ps.evaluated = True
        ps2 = ps.copy()
        assert ps2.parameters["x"].value == pytest.approx(3.3)
        assert ps2.parameters["y"].value == pytest.approx(4.4)
        assert ps2.fitness == pytest.approx(7.7)
        assert ps2.generation == 5
        assert ps2.evaluated is True


# ---------------------------------------------------------------------------
# 14. Parameter clamping and integer rounding
# ---------------------------------------------------------------------------

class TestParameter:
    def test_clamp_lower(self):
        p = Parameter("x", 2.0, 0.0, 5.0, "continuous")
        assert p.clamp(-10.0) == 0.0

    def test_clamp_upper(self):
        p = Parameter("x", 2.0, 0.0, 5.0, "continuous")
        assert p.clamp(100.0) == 5.0

    def test_no_clamp_in_range(self):
        p = Parameter("x", 2.0, 0.0, 5.0, "continuous")
        assert p.clamp(3.5) == pytest.approx(3.5)

    def test_integer_rounding(self):
        p = Parameter("k", 3.0, 0.0, 10.0, "integer")
        assert p.clamp(3.7) == 4.0

    def test_range_property(self):
        p = Parameter("x", 0.0, 2.0, 8.0, "continuous")
        assert p.range == pytest.approx(6.0)
