#!/usr/bin/env python3
"""
Symbolic Alpha Discovery — GP-Based Interpretable Formula Search
================================================================
Discovers closed-form alpha expressions from trading feature data using
genetic programming. Instead of hand-tuned filter thresholds (delta > X,
VPIN > Y, hour not in Z), this module evolves the actual mathematical
boundary between profitable and unprofitable setups.

Architecture:
  1. Expression — Recursive tree node (operators, constants, variables)
  2. SymbolicAlphaDiscovery — GP engine (init, evolve, select, crossover, mutate)
  3. AlphaCandidate — Evaluated individual with fitness, complexity, Pareto rank
  4. Pareto front extraction — Returns the fitness vs complexity tradeoff surface

Design decisions:
  - Self-contained GP engine; no PySR/deap dependency
  - Protected division, log, exp prevent NaN/Inf during evaluation
  - Parsimony pressure prevents expression bloat
  - Tournament selection for robust search
  - Ramped half-and-half tree initialisation (mix of full and grow)
  - Pearson correlation fitness handles arbitrary-scale targets
  - Deterministic with random_seed for reproducibility

Author: JJ (autonomous)
Date: 2026-03-21
"""

from __future__ import annotations

import copy
import logging
import math
import random
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

try:
    from bot import elastic_client
except ImportError:  # pragma: no cover — script-style execution fallback
    try:
        import elastic_client  # type: ignore
    except ImportError:
        elastic_client = None  # type: ignore

logger = logging.getLogger("JJ.symbolic_alpha")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BINARY_OPS: tuple[str, ...] = ("+", "-", "*", "/")
_UNARY_OPS: tuple[str, ...] = ("sin", "exp", "log", "abs", "neg")
_ALL_OPS: tuple[str, ...] = _BINARY_OPS + _UNARY_OPS
_TERMINAL_TYPES: tuple[str, ...] = ("const", "var")

_EXP_CAP: float = 1e6        # cap for protected_exp
_LOG_ZERO_RETURN: float = 0.0  # return value for protected_log on non-positive input
_DIV_ZERO_RETURN: float = 1.0  # return value for protected_div on zero denominator


# ---------------------------------------------------------------------------
# Protected arithmetic helpers
# ---------------------------------------------------------------------------

def _protected_div(a: float, b: float) -> float:
    """Division that returns _DIV_ZERO_RETURN on zero or near-zero denominator."""
    if abs(b) < 1e-10:
        return _DIV_ZERO_RETURN
    return a / b


def _protected_log(a: float) -> float:
    """Natural log that returns _LOG_ZERO_RETURN on non-positive input."""
    if a <= 0.0:
        return _LOG_ZERO_RETURN
    return math.log(a)


def _protected_exp(a: float) -> float:
    """Exp capped at _EXP_CAP to prevent overflow."""
    try:
        result = math.exp(a)
    except OverflowError:
        return _EXP_CAP
    return min(result, _EXP_CAP)


# ---------------------------------------------------------------------------
# Expression tree
# ---------------------------------------------------------------------------

@dataclass
class Expression:
    """A symbolic expression tree node.

    Terminals:
        op == "const"  →  leaf with numeric value `value`
        op == "var"    →  leaf that looks up `var_name` in the variables dict

    Unary operators (sin, exp, log, abs, neg):
        children has exactly 1 element

    Binary operators (+, -, *, /):
        children has exactly 2 elements
    """

    op: str
    children: list = field(default_factory=list)
    value: float = 0.0
    var_name: str = ""

    # ------------------------------------------------------------------
    def evaluate(self, variables: dict[str, float]) -> float:
        """Recursively evaluate the expression given variable values."""
        op = self.op

        if op == "const":
            return self.value

        if op == "var":
            return variables.get(self.var_name, 0.0)

        # Unary
        if op in _UNARY_OPS:
            a = self.children[0].evaluate(variables)
            if op == "sin":
                return math.sin(a)
            if op == "exp":
                return _protected_exp(a)
            if op == "log":
                return _protected_log(a)
            if op == "abs":
                return abs(a)
            if op == "neg":
                return -a

        # Binary
        a = self.children[0].evaluate(variables)
        b = self.children[1].evaluate(variables)
        if op == "+":
            return a + b
        if op == "-":
            return a - b
        if op == "*":
            return a * b
        if op == "/":
            return _protected_div(a, b)

        raise ValueError(f"Unknown op: {op!r}")

    # ------------------------------------------------------------------
    def to_string(self) -> str:
        """Human-readable infix notation."""
        op = self.op

        if op == "const":
            return f"{self.value:.4g}"

        if op == "var":
            return self.var_name

        if op in _UNARY_OPS:
            inner = self.children[0].to_string()
            if op == "neg":
                return f"(-{inner})"
            return f"{op}({inner})"

        # Binary
        left = self.children[0].to_string()
        right = self.children[1].to_string()
        return f"({left} {op} {right})"

    # ------------------------------------------------------------------
    def complexity(self) -> int:
        """Number of nodes in the tree."""
        if not self.children:
            return 1
        return 1 + sum(c.complexity() for c in self.children)

    # ------------------------------------------------------------------
    def depth(self) -> int:
        """Maximum depth of the tree (root = 0)."""
        if not self.children:
            return 0
        return 1 + max(c.depth() for c in self.children)

    # ------------------------------------------------------------------
    def collect_nodes(self) -> list[Expression]:
        """Return a flat list of all nodes (including self) in pre-order."""
        nodes: list[Expression] = [self]
        for child in self.children:
            nodes.extend(child.collect_nodes())
        return nodes


# ---------------------------------------------------------------------------
# Alpha candidate (evaluated individual)
# ---------------------------------------------------------------------------

@dataclass
class AlphaCandidate:
    expression: Expression
    fitness: float = 0.0       # How well it predicts profitable trades
    complexity: int = 0        # Tree size (Occam penalty applied during GP)
    pareto_rank: int = 0       # Rank on fitness-complexity Pareto front (0 = best)
    sharpe: float = 0.0        # Estimated Sharpe if used as threshold signal
    accuracy: float = 0.0      # Classification accuracy on held-out 20% split
    formula_str: str = ""      # Human-readable formula


# ---------------------------------------------------------------------------
# Main GP engine
# ---------------------------------------------------------------------------

class SymbolicAlphaDiscovery:
    """Genetic programming for symbolic regression.

    Evolves populations of expression trees to find the best alpha formula.
    """

    def __init__(
        self,
        population_size: int = 200,
        generations: int = 50,
        max_depth: int = 5,
        tournament_size: int = 7,
        crossover_rate: float = 0.7,
        mutation_rate: float = 0.2,
        parsimony_coefficient: float = 0.01,
        random_seed: int = 42,
    ) -> None:
        self.population_size = population_size
        self.generations = generations
        self.max_depth = max_depth
        self.tournament_size = tournament_size
        self.crossover_rate = crossover_rate
        self.mutation_rate = mutation_rate
        self.parsimony_coefficient = parsimony_coefficient
        self.random_seed = random_seed

        self._rng = random.Random(random_seed)
        self._np_rng = np.random.default_rng(random_seed)

        self._variables: list[str] = []
        self._pareto_candidates: list[AlphaCandidate] = []
        self._best_expression: Optional[Expression] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fit(
        self,
        X: dict[str, list[float]],
        y: list[float],
        feature_names: list[str] | None = None,
    ) -> list[AlphaCandidate]:
        """Run symbolic regression.

        Args:
            X: {feature_name: [values]}
            y: Target variable (e.g., trade P&L or binary profitable/unprofitable)
            feature_names: Optional display names (unused; X keys are used directly)

        Returns:
            Pareto front of AlphaCandidate objects (fitness vs complexity).
        """
        if not X:
            raise ValueError("X must contain at least one feature")
        n_samples = len(next(iter(X.values())))
        if n_samples == 0:
            raise ValueError("X contains zero samples")
        if len(y) != n_samples:
            raise ValueError(f"len(y)={len(y)} != n_samples={n_samples}")

        self._variables = list(X.keys())
        y_arr = np.array(y, dtype=float)

        # Convert X to list-of-dicts for fast row access during evaluation
        rows: list[dict[str, float]] = [
            {k: float(X[k][i]) for k in self._variables}
            for i in range(n_samples)
        ]

        # Train / held-out split (80/20) for accuracy estimation
        split = max(1, int(0.8 * n_samples))
        rows_train = rows[:split]
        y_train = y_arr[:split]
        rows_held = rows[split:] if split < n_samples else rows
        y_held = y_arr[split:] if split < n_samples else y_arr

        logger.info(
            "SymbolicAlpha.fit: %d samples, %d features, %d generations, pop=%d",
            n_samples,
            len(self._variables),
            self.generations,
            self.population_size,
        )

        # 1. Initialise random population
        population = [
            self._random_tree(self.max_depth, self._variables)
            for _ in range(self.population_size)
        ]

        # 2. Generational loop
        for gen in range(self.generations):
            fitnesses = [
                self._evaluate_fitness(expr, rows_train, y_train)
                for expr in population
            ]

            next_pop: list[Expression] = []

            # Elitism: carry the best individual unchanged
            best_idx = int(np.argmax(fitnesses))
            next_pop.append(copy.deepcopy(population[best_idx]))

            while len(next_pop) < self.population_size:
                r = self._rng.random()
                if r < self.crossover_rate:
                    p1 = self._tournament_select(population, fitnesses)
                    p2 = self._tournament_select(population, fitnesses)
                    child = self._crossover(p1, p2)
                elif r < self.crossover_rate + self.mutation_rate:
                    parent = self._tournament_select(population, fitnesses)
                    child = self._mutate(parent, self._variables)
                else:
                    child = self._tournament_select(population, fitnesses)
                    child = copy.deepcopy(child)

                # Clip depth after genetic operations to prevent unbounded growth
                if child.depth() > self.max_depth * 2:
                    child = self._random_tree(self.max_depth, self._variables)

                next_pop.append(child)

            population = next_pop[:self.population_size]

            if (gen + 1) % 10 == 0:
                best_f = max(fitnesses)
                logger.debug("Gen %d/%d  best_fitness=%.4f", gen + 1, self.generations, best_f)

        # 3. Final evaluation on full training set, build candidates
        final_fitnesses = [
            self._evaluate_fitness(expr, rows_train, y_train)
            for expr in population
        ]

        all_candidates: list[AlphaCandidate] = []
        for expr, fit in zip(population, final_fitnesses):
            preds_held = self._predict_rows(expr, rows_held)
            acc = self._classification_accuracy(preds_held, y_held)
            sharpe = self._estimate_sharpe(preds_held, y_held)
            cand = AlphaCandidate(
                expression=expr,
                fitness=fit,
                complexity=expr.complexity(),
                sharpe=sharpe,
                accuracy=acc,
                formula_str=expr.to_string(),
            )
            all_candidates.append(cand)

        # 4. Extract Pareto front
        pareto = self._pareto_front(all_candidates)
        self._pareto_candidates = pareto

        # Store best (highest fitness on Pareto front)
        if pareto:
            self._best_expression = max(pareto, key=lambda c: c.fitness).expression

        logger.info(
            "SymbolicAlpha.fit done: Pareto front size=%d", len(pareto)
        )
        return pareto

    # ------------------------------------------------------------------

    def predict(self, best_expr: Expression, X: dict[str, list[float]]) -> list[float]:
        """Apply a discovered expression to new data."""
        n = len(next(iter(X.values())))
        rows = [{k: float(X[k][i]) for k in X} for i in range(n)]
        return self._predict_rows(best_expr, rows)

    # ------------------------------------------------------------------

    def get_best_formula(self) -> str:
        """Return the best formula as a human-readable string."""
        if self._best_expression is None:
            return ""
        return self._best_expression.to_string()

    # ------------------------------------------------------------------

    def feature_importance(self) -> dict[str, float]:
        """Analyze Pareto front to determine which features appear most often.

        Returns a dict {feature_name: frequency} where frequency is the
        fraction of Pareto-front candidates that include the feature at least once.
        """
        if not self._pareto_candidates:
            return {}
        counts: dict[str, int] = {v: 0 for v in self._variables}
        total = len(self._pareto_candidates)
        for cand in self._pareto_candidates:
            present = set()
            for node in cand.expression.collect_nodes():
                if node.op == "var" and node.var_name in counts:
                    present.add(node.var_name)
            for feat in present:
                counts[feat] += 1
        return {k: counts[k] / total for k in counts}

    # ------------------------------------------------------------------
    # Tree generation
    # ------------------------------------------------------------------

    def _random_tree(self, max_depth: int, variables: list[str]) -> Expression:
        """Generate a random expression tree using ramped half-and-half.

        At even calls: 'full' method (all leaves at max depth).
        At odd calls: 'grow' method (leaves can appear at any depth).
        Randomness comes from self._rng for determinism.
        """
        method = self._rng.choice(("full", "grow"))
        return self._build_tree(max_depth, variables, method, current_depth=0)

    def _build_tree(
        self,
        max_depth: int,
        variables: list[str],
        method: str,
        current_depth: int,
    ) -> Expression:
        """Recursive tree builder."""
        must_be_terminal = current_depth >= max_depth
        if not must_be_terminal and method == "grow":
            # grow: equal probability of terminal vs function
            must_be_terminal = self._rng.random() < 0.4

        if must_be_terminal or not variables:
            return self._random_terminal(variables)

        # Pick an operator
        op = self._rng.choice(_ALL_OPS)
        if op in _BINARY_OPS:
            left = self._build_tree(max_depth, variables, method, current_depth + 1)
            right = self._build_tree(max_depth, variables, method, current_depth + 1)
            return Expression(op=op, children=[left, right])
        else:
            child = self._build_tree(max_depth, variables, method, current_depth + 1)
            return Expression(op=op, children=[child])

    def _random_terminal(self, variables: list[str]) -> Expression:
        """Return a random terminal: const or var."""
        if variables and self._rng.random() < 0.6:
            return Expression(op="var", var_name=self._rng.choice(variables))
        # Constant: uniform in [-3, 3]
        val = self._rng.uniform(-3.0, 3.0)
        return Expression(op="const", value=val)

    # ------------------------------------------------------------------
    # Fitness
    # ------------------------------------------------------------------

    def _evaluate_fitness(
        self,
        expr: Expression,
        rows: list[dict[str, float]],
        y: np.ndarray,
    ) -> float:
        """Fitness = Pearson correlation with target - parsimony * complexity.

        Protected: NaN/Inf predictions are replaced with 0.0.
        Returns 0.0 when correlation cannot be computed (e.g., constant predictions).
        """
        preds = self._predict_rows(expr, rows)
        pred_arr = np.array(preds, dtype=float)

        # Replace non-finite values
        pred_arr = np.where(np.isfinite(pred_arr), pred_arr, 0.0)

        # Pearson correlation
        corr = _pearson_correlation(pred_arr, y)

        # Parsimony penalty
        penalty = self.parsimony_coefficient * expr.complexity()
        return corr - penalty

    def _predict_rows(
        self, expr: Expression, rows: list[dict[str, float]]
    ) -> list[float]:
        """Evaluate expression on each row, returning raw predictions."""
        results: list[float] = []
        for row in rows:
            try:
                val = expr.evaluate(row)
            except Exception:
                val = 0.0
            if not math.isfinite(val):
                val = 0.0
            results.append(val)
        return results

    # ------------------------------------------------------------------
    # Genetic operators
    # ------------------------------------------------------------------

    def _crossover(self, parent1: Expression, parent2: Expression) -> Expression:
        """Subtree crossover: pick a random node in parent1 and replace it
        with a random subtree from parent2."""
        child = copy.deepcopy(parent1)
        donor = copy.deepcopy(parent2)

        # Collect all mutable nodes in child (non-root so we can replace via parent ref)
        child_nodes = child.collect_nodes()
        donor_nodes = donor.collect_nodes()

        if len(child_nodes) < 2 or not donor_nodes:
            return child

        # Pick a random non-root node in child to replace
        target_idx = self._rng.randint(1, len(child_nodes) - 1)
        donor_subtree = copy.deepcopy(self._rng.choice(donor_nodes))

        # Replace the node at target_idx by traversal
        _replace_node(child, target_idx, donor_subtree)
        return child

    def _mutate(self, expr: Expression, variables: list[str]) -> Expression:
        """Point mutation: randomly change one node's operation or value."""
        result = copy.deepcopy(expr)
        nodes = result.collect_nodes()
        if not nodes:
            return result

        target = self._rng.choice(nodes)

        if target.op == "const":
            # Nudge the constant value
            target.value += self._rng.gauss(0, 1.0)
        elif target.op == "var":
            if variables:
                target.var_name = self._rng.choice(variables)
        else:
            n_children = len(target.children)
            if n_children == 2:
                target.op = self._rng.choice(_BINARY_OPS)
            elif n_children == 1:
                target.op = self._rng.choice(_UNARY_OPS)

        return result

    def _tournament_select(
        self, population: list[Expression], fitnesses: list[float]
    ) -> Expression:
        """Tournament selection: pick tournament_size random individuals,
        return the one with highest fitness."""
        size = min(self.tournament_size, len(population))
        indices = self._rng.sample(range(len(population)), size)
        best_idx = max(indices, key=lambda i: fitnesses[i])
        return population[best_idx]

    # ------------------------------------------------------------------
    # Pareto front
    # ------------------------------------------------------------------

    def _pareto_front(
        self, candidates: list[AlphaCandidate]
    ) -> list[AlphaCandidate]:
        """Extract non-dominated solutions on (fitness, -complexity) objectives.

        A candidate A dominates B if:
            A.fitness >= B.fitness AND A.complexity <= B.complexity
            with at least one strict inequality.

        Returns candidates sorted by descending fitness.
        """
        if not candidates:
            return []

        # Deduplicate by formula string to keep front clean
        seen: dict[str, AlphaCandidate] = {}
        for cand in candidates:
            key = cand.formula_str
            if key not in seen or cand.fitness > seen[key].fitness:
                seen[key] = cand
        unique = list(seen.values())

        front: list[AlphaCandidate] = []
        for i, a in enumerate(unique):
            dominated = False
            for j, b in enumerate(unique):
                if i == j:
                    continue
                # b dominates a?
                if (
                    b.fitness >= a.fitness
                    and b.complexity <= a.complexity
                    and (b.fitness > a.fitness or b.complexity < a.complexity)
                ):
                    dominated = True
                    break
            if not dominated:
                a.pareto_rank = 0
                front.append(a)

        front.sort(key=lambda c: c.fitness, reverse=True)
        return front

    # ------------------------------------------------------------------
    # Metrics helpers
    # ------------------------------------------------------------------

    def _classification_accuracy(
        self, preds: list[float], y: np.ndarray
    ) -> float:
        """Binary accuracy: sign(pred) == sign(y - median(y))."""
        if len(preds) == 0:
            return 0.0
        median_y = float(np.median(y))
        correct = sum(
            1
            for p, yi in zip(preds, y)
            if (p >= 0) == (yi >= median_y)
        )
        return correct / len(preds)

    def _estimate_sharpe(self, preds: list[float], y: np.ndarray) -> float:
        """Estimate Sharpe of a long/short signal based on predicted sign.

        Returns PnL = sum(sign(pred_i) * y_i) / std(y) / sqrt(n).
        Protected against zero std.
        """
        if len(preds) == 0:
            return 0.0
        signs = np.array([1.0 if p >= 0 else -1.0 for p in preds])
        returns = signs * y
        std = float(np.std(returns))
        if std < 1e-12:
            return 0.0
        mean_r = float(np.mean(returns))
        return mean_r / std


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _pearson_correlation(a: np.ndarray, b: np.ndarray) -> float:
    """Pearson correlation between two arrays. Returns 0.0 if undefined."""
    if len(a) < 2:
        return 0.0
    std_a = float(np.std(a))
    std_b = float(np.std(b))
    if std_a < 1e-12 or std_b < 1e-12:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def _replace_node(root: Expression, target_idx: int, replacement: Expression) -> bool:
    """Replace the node at target_idx (pre-order traversal, 0-indexed) in-place.

    Returns True if the replacement was made.
    Uses a mutable counter via a list to allow mutation inside the recursive closure.
    """
    counter = [0]

    def _traverse(node: Expression) -> bool:
        for idx, child in enumerate(node.children):
            counter[0] += 1
            if counter[0] == target_idx:
                node.children[idx] = replacement
                return True
            if _traverse(child):
                return True
        return False

    _traverse(root)
    return counter[0] >= target_idx
