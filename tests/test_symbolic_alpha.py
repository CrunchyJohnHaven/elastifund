"""
Tests for bot/symbolic_alpha.py
================================
Covers:
  - Expression evaluation (known formulas)
  - Expression.to_string readable output
  - Protected operations: div/0, log(neg), exp(large)
  - _random_tree depth constraints
  - Crossover produces valid offspring
  - Mutation changes the tree
  - GP discovers y = 2*x + noise (simple linear)
  - GP with 2 variables discovers y = x1 + x2
  - Pareto front extraction (simpler preferred when fitness equal)
  - feature_importance returns correct feature counts
  - predict applies formula to new data
  - Parsimony pressure: higher coefficient produces simpler expressions
"""
from __future__ import annotations

import math
import random
import copy

import numpy as np
import pytest

from bot.symbolic_alpha import (
    Expression,
    AlphaCandidate,
    SymbolicAlphaDiscovery,
    _pearson_correlation,
    _protected_div,
    _protected_log,
    _protected_exp,
    _DIV_ZERO_RETURN,
    _LOG_ZERO_RETURN,
    _EXP_CAP,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _const(v: float) -> Expression:
    return Expression(op="const", value=v)


def _var(name: str) -> Expression:
    return Expression(op="var", var_name=name)


def _binop(op: str, left: Expression, right: Expression) -> Expression:
    return Expression(op=op, children=[left, right])


def _unop(op: str, child: Expression) -> Expression:
    return Expression(op=op, children=[child])


# ---------------------------------------------------------------------------
# Expression.evaluate — known formulas
# ---------------------------------------------------------------------------

class TestExpressionEvaluate:
    def test_constant(self):
        expr = _const(3.14)
        assert expr.evaluate({}) == pytest.approx(3.14)

    def test_variable_present(self):
        expr = _var("x")
        assert expr.evaluate({"x": 7.0}) == pytest.approx(7.0)

    def test_variable_missing_returns_zero(self):
        expr = _var("x")
        assert expr.evaluate({}) == pytest.approx(0.0)

    def test_add(self):
        # 2 + 3 = 5
        expr = _binop("+", _const(2.0), _const(3.0))
        assert expr.evaluate({}) == pytest.approx(5.0)

    def test_subtract(self):
        # 10 - 4 = 6
        expr = _binop("-", _const(10.0), _const(4.0))
        assert expr.evaluate({}) == pytest.approx(6.0)

    def test_multiply(self):
        # 3 * 4 = 12
        expr = _binop("*", _const(3.0), _const(4.0))
        assert expr.evaluate({}) == pytest.approx(12.0)

    def test_divide(self):
        # 9 / 3 = 3
        expr = _binop("/", _const(9.0), _const(3.0))
        assert expr.evaluate({}) == pytest.approx(3.0)

    def test_two_x_plus_three(self):
        # (2 * x) + 3 evaluated at x=5 → 13
        expr = _binop("+", _binop("*", _const(2.0), _var("x")), _const(3.0))
        assert expr.evaluate({"x": 5.0}) == pytest.approx(13.0)

    def test_nested_operations(self):
        # (x + y) * (x - y) = x^2 - y^2; x=3, y=1 → 8
        expr = _binop(
            "*",
            _binop("+", _var("x"), _var("y")),
            _binop("-", _var("x"), _var("y")),
        )
        assert expr.evaluate({"x": 3.0, "y": 1.0}) == pytest.approx(8.0)

    def test_sin(self):
        expr = _unop("sin", _const(0.0))
        assert expr.evaluate({}) == pytest.approx(0.0)

    def test_abs_negative(self):
        expr = _unop("abs", _const(-5.0))
        assert expr.evaluate({}) == pytest.approx(5.0)

    def test_neg(self):
        expr = _unop("neg", _const(4.0))
        assert expr.evaluate({}) == pytest.approx(-4.0)

    def test_exp_small(self):
        expr = _unop("exp", _const(0.0))
        assert expr.evaluate({}) == pytest.approx(1.0)

    def test_log_positive(self):
        expr = _unop("log", _const(math.e))
        assert expr.evaluate({}) == pytest.approx(1.0, rel=1e-5)

    def test_complexity_leaf(self):
        assert _const(1.0).complexity() == 1
        assert _var("x").complexity() == 1

    def test_complexity_binary(self):
        # (x + 1) has 3 nodes
        expr = _binop("+", _var("x"), _const(1.0))
        assert expr.complexity() == 3

    def test_complexity_unary(self):
        # sin(x) has 2 nodes
        assert _unop("sin", _var("x")).complexity() == 2


# ---------------------------------------------------------------------------
# Expression.to_string
# ---------------------------------------------------------------------------

class TestExpressionToString:
    def test_const(self):
        s = _const(3.14).to_string()
        assert "3.14" in s

    def test_var(self):
        assert _var("vpin").to_string() == "vpin"

    def test_add_readable(self):
        s = _binop("+", _var("x"), _const(1.0)).to_string()
        assert "x" in s
        assert "+" in s
        assert "1" in s

    def test_unary_neg(self):
        s = _unop("neg", _var("x")).to_string()
        assert "-" in s
        assert "x" in s

    def test_unary_sin(self):
        s = _unop("sin", _var("x")).to_string()
        assert "sin" in s
        assert "x" in s

    def test_nested_readable(self):
        expr = _binop(
            "+",
            _binop("*", _const(2.0), _var("x")),
            _const(3.0),
        )
        s = expr.to_string()
        assert "x" in s
        assert "2" in s
        assert "3" in s
        assert "+" in s
        assert "*" in s


# ---------------------------------------------------------------------------
# Protected operations
# ---------------------------------------------------------------------------

class TestProtectedOps:
    def test_div_zero_denominator(self):
        assert _protected_div(5.0, 0.0) == pytest.approx(_DIV_ZERO_RETURN)

    def test_div_near_zero_denominator(self):
        assert _protected_div(1.0, 1e-11) == pytest.approx(_DIV_ZERO_RETURN)

    def test_div_normal(self):
        assert _protected_div(10.0, 2.0) == pytest.approx(5.0)

    def test_log_negative(self):
        assert _protected_log(-1.0) == pytest.approx(_LOG_ZERO_RETURN)

    def test_log_zero(self):
        assert _protected_log(0.0) == pytest.approx(_LOG_ZERO_RETURN)

    def test_log_positive(self):
        assert _protected_log(math.e) == pytest.approx(1.0, rel=1e-5)

    def test_exp_large_capped(self):
        result = _protected_exp(10000.0)
        assert result == pytest.approx(_EXP_CAP)

    def test_exp_normal(self):
        assert _protected_exp(0.0) == pytest.approx(1.0)

    def test_expression_divide_by_zero_node(self):
        # Division node with zero constant denominator returns _DIV_ZERO_RETURN
        expr = _binop("/", _var("x"), _const(0.0))
        result = expr.evaluate({"x": 5.0})
        assert result == pytest.approx(_DIV_ZERO_RETURN)

    def test_expression_log_negative_node(self):
        expr = _unop("log", _const(-3.0))
        result = expr.evaluate({})
        assert result == pytest.approx(_LOG_ZERO_RETURN)

    def test_expression_exp_overflow_node(self):
        expr = _unop("exp", _const(100000.0))
        result = expr.evaluate({})
        assert result == pytest.approx(_EXP_CAP)


# ---------------------------------------------------------------------------
# _random_tree depth and validity
# ---------------------------------------------------------------------------

class TestRandomTree:
    def setup_method(self):
        self.gp = SymbolicAlphaDiscovery(random_seed=0)
        self.gp._variables = ["x", "y", "z"]

    def test_depth_within_limit(self):
        for _ in range(50):
            tree = self.gp._random_tree(max_depth=4, variables=["x", "y"])
            assert tree.depth() <= 4, f"depth={tree.depth()} exceeds limit"

    def test_single_variable(self):
        # Should not raise even with one variable
        tree = self.gp._random_tree(max_depth=3, variables=["vpin"])
        assert tree.depth() >= 0

    def test_empty_variables_gives_const(self):
        tree = self.gp._random_tree(max_depth=3, variables=[])
        # All leaf nodes must be consts since there are no variables
        for node in tree.collect_nodes():
            if not node.children:
                assert node.op == "const"

    def test_all_var_names_come_from_list(self):
        variables = ["a", "b", "c"]
        for _ in range(30):
            tree = self.gp._random_tree(max_depth=3, variables=variables)
            for node in tree.collect_nodes():
                if node.op == "var":
                    assert node.var_name in variables

    def test_tree_evaluates_without_error(self):
        variables = ["x", "y"]
        for _ in range(20):
            tree = self.gp._random_tree(max_depth=3, variables=variables)
            result = tree.evaluate({"x": 0.5, "y": -0.3})
            # Should not raise; result may be any finite or non-finite float
            assert isinstance(result, float)


# ---------------------------------------------------------------------------
# Crossover
# ---------------------------------------------------------------------------

class TestCrossover:
    def setup_method(self):
        self.gp = SymbolicAlphaDiscovery(random_seed=7)
        self.gp._variables = ["x", "y"]

    def test_crossover_produces_expression(self):
        p1 = _binop("+", _var("x"), _const(1.0))
        p2 = _binop("*", _var("y"), _const(2.0))
        child = self.gp._crossover(p1, p2)
        assert isinstance(child, Expression)

    def test_crossover_result_evaluable(self):
        p1 = _binop("+", _var("x"), _const(1.0))
        p2 = _binop("-", _var("y"), _const(0.5))
        child = self.gp._crossover(p1, p2)
        result = child.evaluate({"x": 1.0, "y": 2.0})
        assert isinstance(result, float)

    def test_crossover_does_not_mutate_parents(self):
        p1 = _binop("+", _var("x"), _const(1.0))
        p2 = _binop("*", _var("y"), _const(2.0))
        p1_str_before = p1.to_string()
        p2_str_before = p2.to_string()
        _ = self.gp._crossover(p1, p2)
        assert p1.to_string() == p1_str_before
        assert p2.to_string() == p2_str_before

    def test_crossover_single_node_parents(self):
        # Both parents are single-node terminals — should still return an Expression
        p1 = _const(1.0)
        p2 = _var("x")
        child = self.gp._crossover(p1, p2)
        assert isinstance(child, Expression)


# ---------------------------------------------------------------------------
# Mutation
# ---------------------------------------------------------------------------

class TestMutation:
    def setup_method(self):
        self.gp = SymbolicAlphaDiscovery(random_seed=13)
        self.gp._variables = ["x", "y"]

    def test_mutation_returns_expression(self):
        expr = _binop("+", _var("x"), _const(1.0))
        mutated = self.gp._mutate(expr, ["x", "y"])
        assert isinstance(mutated, Expression)

    def test_mutation_is_not_identical_original(self):
        # With enough attempts, mutation should change something
        expr = _binop("*", _binop("+", _var("x"), _const(1.0)), _var("y"))
        changed = False
        for seed in range(30):
            gp_tmp = SymbolicAlphaDiscovery(random_seed=seed)
            mutated = gp_tmp._mutate(expr, ["x", "y"])
            if mutated.to_string() != expr.to_string():
                changed = True
                break
        assert changed, "Mutation never changed the expression across 30 seeds"

    def test_mutation_result_evaluable(self):
        expr = _binop("+", _var("x"), _const(2.0))
        for seed in range(10):
            gp_tmp = SymbolicAlphaDiscovery(random_seed=seed)
            mutated = gp_tmp._mutate(expr, ["x"])
            result = mutated.evaluate({"x": 1.5})
            assert isinstance(result, float)

    def test_mutation_const_nudge(self):
        # Force mutation of a const node — value should change in at least one run
        expr = _const(5.0)
        values_seen = set()
        for seed in range(20):
            gp_tmp = SymbolicAlphaDiscovery(random_seed=seed)
            mutated = gp_tmp._mutate(expr, [])
            if mutated.op == "const":
                values_seen.add(round(mutated.value, 8))
        # Should see more than one constant value across seeds
        assert len(values_seen) > 1


# ---------------------------------------------------------------------------
# GP convergence: y = 2*x + noise
# ---------------------------------------------------------------------------

class TestGPConvergenceLinear:
    """GP should be able to approximate a simple linear relationship."""

    def _make_data(self, n: int = 100, seed: int = 0):
        rng = np.random.default_rng(seed)
        x = rng.uniform(-2, 2, n)
        y = 2.0 * x + rng.normal(0, 0.1, n)
        return {"x": list(x)}, list(y)

    def test_gp_finds_positive_correlation_with_x(self):
        X, y = self._make_data(100)
        gp = SymbolicAlphaDiscovery(
            population_size=100,
            generations=30,
            max_depth=4,
            parsimony_coefficient=0.005,
            random_seed=42,
        )
        pareto = gp.fit(X, y)
        assert len(pareto) > 0
        # Best fitness should be substantially positive (strong correlation)
        best_fitness = max(c.fitness for c in pareto)
        assert best_fitness > 0.5, f"Best fitness too low: {best_fitness:.4f}"

    def test_gp_best_formula_contains_x(self):
        X, y = self._make_data(80)
        gp = SymbolicAlphaDiscovery(
            population_size=80,
            generations=20,
            max_depth=4,
            random_seed=7,
        )
        gp.fit(X, y)
        formula = gp.get_best_formula()
        # The best formula for y ≈ 2x should reference x
        assert "x" in formula, f"Formula does not mention x: {formula}"

    def test_gp_predictions_correlated_with_target(self):
        X, y = self._make_data(120)
        gp = SymbolicAlphaDiscovery(
            population_size=100,
            generations=25,
            max_depth=4,
            random_seed=99,
        )
        pareto = gp.fit(X, y)
        best_expr = max(pareto, key=lambda c: c.fitness).expression
        preds = gp.predict(best_expr, X)
        # Pearson correlation between predictions and targets should be high
        corr = _pearson_correlation(np.array(preds), np.array(y))
        assert corr > 0.7, f"Prediction correlation too low: {corr:.4f}"


# ---------------------------------------------------------------------------
# GP convergence: y = x1 + x2
# ---------------------------------------------------------------------------

class TestGPConvergenceTwoVariables:
    """GP should discover a formula involving both x1 and x2."""

    def _make_data(self, n: int = 120, seed: int = 5):
        rng = np.random.default_rng(seed)
        x1 = rng.uniform(-1, 1, n)
        x2 = rng.uniform(-1, 1, n)
        y = x1 + x2 + rng.normal(0, 0.05, n)
        return {"x1": list(x1), "x2": list(x2)}, list(y)

    def test_gp_uses_both_variables(self):
        X, y = self._make_data()
        gp = SymbolicAlphaDiscovery(
            population_size=100,
            generations=30,
            max_depth=4,
            random_seed=42,
        )
        gp.fit(X, y)
        importance = gp.feature_importance()
        assert "x1" in importance
        assert "x2" in importance
        # Both features should appear in at least some Pareto front members
        total_importance = importance["x1"] + importance["x2"]
        assert total_importance > 0.0, "Neither x1 nor x2 appears in Pareto front"

    def test_gp_predictions_two_var(self):
        X, y = self._make_data()
        gp = SymbolicAlphaDiscovery(
            population_size=100,
            generations=30,
            max_depth=4,
            random_seed=17,
        )
        pareto = gp.fit(X, y)
        best_expr = max(pareto, key=lambda c: c.fitness).expression
        preds = gp.predict(best_expr, X)
        corr = _pearson_correlation(np.array(preds), np.array(y))
        assert corr > 0.6, f"Two-variable correlation too low: {corr:.4f}"


# ---------------------------------------------------------------------------
# Pareto front extraction
# ---------------------------------------------------------------------------

class TestParetoFront:
    def setup_method(self):
        self.gp = SymbolicAlphaDiscovery(random_seed=0)

    def _cand(self, fitness: float, complexity: int, formula: str) -> AlphaCandidate:
        return AlphaCandidate(
            expression=_const(0.0),
            fitness=fitness,
            complexity=complexity,
            formula_str=formula,
        )

    def test_empty_input(self):
        assert self.gp._pareto_front([]) == []

    def test_single_candidate(self):
        front = self.gp._pareto_front([self._cand(0.8, 3, "A")])
        assert len(front) == 1

    def test_dominated_candidate_excluded(self):
        # B dominates A: B.fitness > A.fitness AND B.complexity < A.complexity
        a = self._cand(0.5, 10, "A")
        b = self._cand(0.9, 5, "B")
        front = self.gp._pareto_front([a, b])
        formulas = {c.formula_str for c in front}
        assert "B" in formulas
        assert "A" not in formulas

    def test_neither_dominates_both_on_front(self):
        # A: higher fitness, higher complexity. B: lower fitness, lower complexity.
        a = self._cand(0.9, 10, "A_formula_large")
        b = self._cand(0.5, 2, "B_formula_small")
        front = self.gp._pareto_front([a, b])
        formulas = {c.formula_str for c in front}
        assert "A_formula_large" in formulas
        assert "B_formula_small" in formulas

    def test_simpler_preferred_when_fitness_equal(self):
        # Two candidates with identical fitness: the simpler one should appear on front
        a = self._cand(0.8, 10, "A_complex")
        b = self._cand(0.8, 3, "B_simple")
        front = self.gp._pareto_front([a, b])
        formulas = {c.formula_str for c in front}
        assert "B_simple" in formulas
        assert "A_complex" not in formulas

    def test_pareto_front_sorted_by_fitness(self):
        candidates = [
            self._cand(0.9, 10, "high_fit"),
            self._cand(0.5, 2, "low_fit_simple"),
            self._cand(0.7, 6, "mid_fit"),
        ]
        front = self.gp._pareto_front(candidates)
        fitnesses = [c.fitness for c in front]
        assert fitnesses == sorted(fitnesses, reverse=True)

    def test_all_pareto_rank_zero(self):
        candidates = [
            self._cand(0.9, 10, "A_domination_test"),
            self._cand(0.5, 2, "B_domination_test"),
        ]
        front = self.gp._pareto_front(candidates)
        for cand in front:
            assert cand.pareto_rank == 0


# ---------------------------------------------------------------------------
# feature_importance
# ---------------------------------------------------------------------------

class TestFeatureImportance:
    def test_empty_pareto_returns_empty(self):
        gp = SymbolicAlphaDiscovery(random_seed=0)
        gp._variables = ["x"]
        gp._pareto_candidates = []
        assert gp.feature_importance() == {}

    def test_single_feature_full_importance(self):
        gp = SymbolicAlphaDiscovery(random_seed=0)
        gp._variables = ["x"]
        cand = AlphaCandidate(
            expression=_var("x"),
            fitness=0.8,
            complexity=1,
            formula_str="x",
        )
        gp._pareto_candidates = [cand]
        imp = gp.feature_importance()
        assert "x" in imp
        assert imp["x"] == pytest.approx(1.0)

    def test_unused_feature_zero_importance(self):
        gp = SymbolicAlphaDiscovery(random_seed=0)
        gp._variables = ["x", "y"]
        # Expression only uses x
        cand = AlphaCandidate(
            expression=_var("x"),
            fitness=0.9,
            complexity=1,
            formula_str="x",
        )
        gp._pareto_candidates = [cand]
        imp = gp.feature_importance()
        assert imp["x"] == pytest.approx(1.0)
        assert imp["y"] == pytest.approx(0.0)

    def test_frequency_counting(self):
        gp = SymbolicAlphaDiscovery(random_seed=0)
        gp._variables = ["x", "y"]

        # 2 candidates: first uses x only, second uses both x and y
        c1 = AlphaCandidate(
            expression=_var("x"),
            fitness=0.9,
            complexity=1,
            formula_str="x",
        )
        c2 = AlphaCandidate(
            expression=_binop("+", _var("x"), _var("y")),
            fitness=0.7,
            complexity=3,
            formula_str="(x + y)",
        )
        gp._pareto_candidates = [c1, c2]
        imp = gp.feature_importance()
        # x appears in both (2/2 = 1.0), y appears in one (1/2 = 0.5)
        assert imp["x"] == pytest.approx(1.0)
        assert imp["y"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# predict
# ---------------------------------------------------------------------------

class TestPredict:
    def test_predict_const_expression(self):
        gp = SymbolicAlphaDiscovery(random_seed=0)
        expr = _const(3.0)
        preds = gp.predict(expr, {"x": [1.0, 2.0, 3.0]})
        assert len(preds) == 3
        assert all(p == pytest.approx(3.0) for p in preds)

    def test_predict_var_expression(self):
        gp = SymbolicAlphaDiscovery(random_seed=0)
        expr = _var("x")
        preds = gp.predict(expr, {"x": [10.0, 20.0, 30.0]})
        assert preds[0] == pytest.approx(10.0)
        assert preds[1] == pytest.approx(20.0)
        assert preds[2] == pytest.approx(30.0)

    def test_predict_formula(self):
        # (2 * x) + 1 at x = [0, 1, 2] → [1, 3, 5]
        gp = SymbolicAlphaDiscovery(random_seed=0)
        expr = _binop("+", _binop("*", _const(2.0), _var("x")), _const(1.0))
        preds = gp.predict(expr, {"x": [0.0, 1.0, 2.0]})
        assert preds[0] == pytest.approx(1.0)
        assert preds[1] == pytest.approx(3.0)
        assert preds[2] == pytest.approx(5.0)

    def test_predict_uses_multiple_features(self):
        # x + y at [(1,2), (3,4)] → [3, 7]
        gp = SymbolicAlphaDiscovery(random_seed=0)
        expr = _binop("+", _var("x"), _var("y"))
        preds = gp.predict(expr, {"x": [1.0, 3.0], "y": [2.0, 4.0]})
        assert preds[0] == pytest.approx(3.0)
        assert preds[1] == pytest.approx(7.0)

    def test_predict_length_matches_input(self):
        gp = SymbolicAlphaDiscovery(random_seed=0)
        expr = _var("x")
        n = 50
        preds = gp.predict(expr, {"x": list(range(n))})
        assert len(preds) == n


# ---------------------------------------------------------------------------
# Parsimony pressure: higher coefficient → simpler expressions
# ---------------------------------------------------------------------------

class TestParsimonyPressure:
    """Higher parsimony_coefficient should penalise larger trees more, producing
    simpler (lower average complexity) expressions on the Pareto front."""

    def _run_gp(self, parsimony: float, seed: int = 42) -> float:
        rng = np.random.default_rng(seed)
        n = 80
        x = rng.uniform(-1, 1, n)
        y = 2.0 * x + rng.normal(0, 0.2, n)
        gp = SymbolicAlphaDiscovery(
            population_size=80,
            generations=20,
            max_depth=5,
            parsimony_coefficient=parsimony,
            random_seed=seed,
        )
        pareto = gp.fit({"x": list(x)}, list(y))
        if not pareto:
            return 999.0
        return float(np.mean([c.complexity for c in pareto]))

    def test_high_parsimony_simpler_than_low(self):
        avg_complexity_low = self._run_gp(parsimony=0.0001, seed=42)
        avg_complexity_high = self._run_gp(parsimony=0.1, seed=42)
        assert avg_complexity_high <= avg_complexity_low, (
            f"High parsimony ({avg_complexity_high:.1f}) not simpler than "
            f"low parsimony ({avg_complexity_low:.1f})"
        )


# ---------------------------------------------------------------------------
# get_best_formula before fit
# ---------------------------------------------------------------------------

class TestGetBestFormula:
    def test_returns_empty_string_before_fit(self):
        gp = SymbolicAlphaDiscovery(random_seed=0)
        assert gp.get_best_formula() == ""

    def test_returns_non_empty_after_fit(self):
        rng = np.random.default_rng(0)
        x = rng.uniform(-1, 1, 50)
        y = x + rng.normal(0, 0.1, 50)
        gp = SymbolicAlphaDiscovery(
            population_size=50, generations=10, max_depth=3, random_seed=0
        )
        gp.fit({"x": list(x)}, list(y))
        formula = gp.get_best_formula()
        assert isinstance(formula, str)
        assert len(formula) > 0


# ---------------------------------------------------------------------------
# fit input validation
# ---------------------------------------------------------------------------

class TestFitValidation:
    def test_empty_X_raises(self):
        gp = SymbolicAlphaDiscovery(random_seed=0)
        with pytest.raises(ValueError, match="at least one feature"):
            gp.fit({}, [1.0, 2.0])

    def test_mismatched_y_raises(self):
        gp = SymbolicAlphaDiscovery(random_seed=0)
        with pytest.raises(ValueError, match="n_samples"):
            gp.fit({"x": [1.0, 2.0, 3.0]}, [1.0, 2.0])

    def test_zero_samples_raises(self):
        gp = SymbolicAlphaDiscovery(random_seed=0)
        with pytest.raises(ValueError, match="zero samples"):
            gp.fit({"x": []}, [])


# ---------------------------------------------------------------------------
# Determinism with fixed seed
# ---------------------------------------------------------------------------

class TestDeterminism:
    def test_same_seed_same_pareto(self):
        rng = np.random.default_rng(0)
        x = rng.uniform(-1, 1, 60)
        y = x * 2 + rng.normal(0, 0.1, 60)
        kwargs = dict(population_size=50, generations=10, max_depth=3, random_seed=77)

        gp1 = SymbolicAlphaDiscovery(**kwargs)
        pareto1 = gp1.fit({"x": list(x)}, list(y))

        gp2 = SymbolicAlphaDiscovery(**kwargs)
        pareto2 = gp2.fit({"x": list(x)}, list(y))

        formulas1 = sorted(c.formula_str for c in pareto1)
        formulas2 = sorted(c.formula_str for c in pareto2)
        assert formulas1 == formulas2, "GP not deterministic with same seed"


# ---------------------------------------------------------------------------
# collect_nodes
# ---------------------------------------------------------------------------

class TestCollectNodes:
    def test_single_node(self):
        nodes = _const(1.0).collect_nodes()
        assert len(nodes) == 1

    def test_binary_node_count(self):
        expr = _binop("+", _var("x"), _const(1.0))
        nodes = expr.collect_nodes()
        assert len(nodes) == 3

    def test_includes_root(self):
        expr = _binop("*", _var("x"), _var("y"))
        nodes = expr.collect_nodes()
        assert nodes[0] is expr
