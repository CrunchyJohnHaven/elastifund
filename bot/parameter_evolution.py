#!/usr/bin/env python3
"""
Parameter Evolution — Self-Evolving Parameter Optimization for BTC5 and Beyond
===============================================================================
Implements a CMA-ES-inspired evolutionary strategy with quadratic surrogate
model to automatically tune trading parameters (skip thresholds, time-of-day
filters, directional biases).

Objective: maximize fill_rate × edge_per_fill on a rolling window.

Architecture:
  - Parameter / ParameterSet / EvolutionResult: data containers
  - ParameterEvolution: main optimizer with GP surrogate (quadratic OLS)
  - btc5_parameter_space(): pre-configured for BTC5 tuning

March 2026 — Elastifund / JJ
"""
from __future__ import annotations

import copy
import logging
import math
import random
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np

logger = logging.getLogger("JJ.parameter_evolution")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Parameter:
    name: str
    value: float
    lower_bound: float
    upper_bound: float
    parameter_type: str  # "continuous", "integer", "categorical"
    description: str = ""

    def _validate(self) -> None:
        if self.lower_bound >= self.upper_bound:
            raise ValueError(
                f"Parameter '{self.name}': lower_bound ({self.lower_bound}) "
                f"must be < upper_bound ({self.upper_bound})"
            )
        if self.parameter_type not in {"continuous", "integer", "categorical"}:
            raise ValueError(
                f"Parameter '{self.name}': unknown type '{self.parameter_type}'"
            )

    def clamp(self, v: float) -> float:
        """Clamp value to [lower_bound, upper_bound] and apply integer rounding."""
        v = float(np.clip(v, self.lower_bound, self.upper_bound))
        if self.parameter_type == "integer":
            v = float(round(v))
        return v

    @property
    def range(self) -> float:
        return self.upper_bound - self.lower_bound


@dataclass
class ParameterSet:
    parameters: dict[str, Parameter]
    fitness: float = 0.0
    generation: int = 0
    evaluated: bool = False

    def to_dict(self) -> dict[str, float]:
        """Return {name: value} mapping."""
        return {name: p.value for name, p in self.parameters.items()}

    def copy(self) -> "ParameterSet":
        """Deep copy."""
        new_params = {
            name: Parameter(
                name=p.name,
                value=p.value,
                lower_bound=p.lower_bound,
                upper_bound=p.upper_bound,
                parameter_type=p.parameter_type,
                description=p.description,
            )
            for name, p in self.parameters.items()
        }
        return ParameterSet(
            parameters=new_params,
            fitness=self.fitness,
            generation=self.generation,
            evaluated=self.evaluated,
        )


@dataclass
class EvolutionResult:
    best_params: ParameterSet
    history: list[ParameterSet]  # All evaluated parameter sets
    generations_run: int
    convergence_curve: list[float]  # Best fitness per generation
    improvement_pct: float  # Improvement over initial params


# ---------------------------------------------------------------------------
# Core optimizer
# ---------------------------------------------------------------------------

class ParameterEvolution:
    """
    CMA-ES-inspired evolutionary strategy with quadratic surrogate model.

    After surrogate_warmup evaluations, fits a quadratic OLS model to predict
    fitness from parameters, enabling cheaper exploration of the landscape.
    """

    def __init__(
        self,
        population_size: int = 20,
        generations: int = 30,
        mutation_sigma: float = 0.1,
        crossover_rate: float = 0.5,
        elite_fraction: float = 0.2,
        surrogate_warmup: int = 10,
        random_seed: int = 42,
    ) -> None:
        if elite_fraction <= 0 or elite_fraction >= 1:
            raise ValueError("elite_fraction must be in (0, 1)")
        if population_size < 4:
            raise ValueError("population_size must be >= 4")

        self.population_size = population_size
        self.generations = generations
        self.mutation_sigma = mutation_sigma
        self.crossover_rate = crossover_rate
        self.elite_fraction = elite_fraction
        self.surrogate_warmup = surrogate_warmup
        self.random_seed = random_seed

        # Parameter registry (ordered, preserved for surrogate feature vectors)
        self._param_templates: dict[str, Parameter] = {}

        # Surrogate model state
        self._surrogate_coeffs: Optional[np.ndarray] = None  # OLS coefficients
        self._surrogate_fitted = False

        # Full evaluation history (for sensitivity + suggest_next)
        self._all_evaluated: list[ParameterSet] = []

        # Seeded RNG — deterministic
        self._rng = random.Random(random_seed)
        self._np_rng = np.random.default_rng(random_seed)

    # ------------------------------------------------------------------
    # Public API: parameter registration
    # ------------------------------------------------------------------

    def define_parameter(
        self,
        name: str,
        lower: float,
        upper: float,
        initial: Optional[float] = None,
        param_type: str = "continuous",
        description: str = "",
    ) -> None:
        """Register a parameter to be optimized."""
        if initial is None:
            initial = (lower + upper) / 2.0
        p = Parameter(
            name=name,
            value=initial,
            lower_bound=lower,
            upper_bound=upper,
            parameter_type=param_type,
            description=description,
        )
        p._validate()
        self._param_templates[name] = p
        logger.debug("Registered parameter '%s': [%g, %g] initial=%g", name, lower, upper, initial)

    # ------------------------------------------------------------------
    # Public API: optimization entry point
    # ------------------------------------------------------------------

    def optimize(
        self,
        objective_fn: Callable[[dict[str, float]], float],
        initial_params: Optional[dict[str, float]] = None,
    ) -> EvolutionResult:
        """
        Run the evolution loop.

        Args:
            objective_fn: Callable({param_name: value}) -> float (higher = better)
            initial_params: Optional starting point override

        Returns:
            EvolutionResult with best_params, history, convergence_curve,
            improvement_pct.
        """
        if not self._param_templates:
            raise ValueError("No parameters registered. Call define_parameter() first.")

        logger.info(
            "Starting evolution: pop=%d, generations=%d, surrogate_warmup=%d",
            self.population_size, self.generations, self.surrogate_warmup,
        )

        # Merge any caller-supplied initial values into templates
        if initial_params:
            for name, val in initial_params.items():
                if name in self._param_templates:
                    t = self._param_templates[name]
                    self._param_templates[name] = Parameter(
                        name=t.name,
                        value=t.clamp(val),
                        lower_bound=t.lower_bound,
                        upper_bound=t.upper_bound,
                        parameter_type=t.parameter_type,
                        description=t.description,
                    )

        # Initialize population
        population = self._initialize_population(initial_params)

        # Evaluate generation 0
        for individual in population:
            individual.fitness = objective_fn(individual.to_dict())
            individual.evaluated = True
            individual.generation = 0
            self._all_evaluated.append(individual)

        population.sort(key=lambda ps: ps.fitness, reverse=True)
        best_overall = population[0].copy()
        initial_fitness = best_overall.fitness
        convergence_curve: list[float] = [best_overall.fitness]
        history: list[ParameterSet] = [p.copy() for p in population]

        n_elite = max(1, int(self.population_size * self.elite_fraction))

        for gen in range(1, self.generations + 1):
            # Fit surrogate after warmup
            if len(self._all_evaluated) >= self.surrogate_warmup:
                self._fit_surrogate(self._all_evaluated)

            elite = population[:n_elite]
            offspring: list[ParameterSet] = []

            while len(offspring) < self.population_size - n_elite:
                # Select parents from top half of current population
                pool_size = max(2, self.population_size // 2)
                p1 = self._rng.choice(population[:pool_size])
                p2 = self._rng.choice(population[:pool_size])

                if self._rng.random() < self.crossover_rate:
                    child = self._crossover(p1, p2)
                else:
                    child = p1.copy()

                child = self._gaussian_mutation(child)

                # Surrogate pre-screening: skip evaluation if surrogate predicts bad
                if self._surrogate_fitted:
                    surrogate_score = self._surrogate_predict(child)
                    # Accept if surrogate predicts above median of current pop
                    median_fit = population[len(population) // 2].fitness
                    if surrogate_score < median_fit * 0.5 and len(offspring) > 0:
                        # Pre-screened out — try again (don't waste objective calls)
                        continue

                child.fitness = objective_fn(child.to_dict())
                child.evaluated = True
                child.generation = gen
                self._all_evaluated.append(child)
                offspring.append(child)

            # Next generation: elite + offspring
            population = elite + offspring
            population.sort(key=lambda ps: ps.fitness, reverse=True)

            gen_best = population[0]
            if gen_best.fitness > best_overall.fitness:
                best_overall = gen_best.copy()
                logger.info(
                    "Gen %d: new best fitness=%.6f (%s)",
                    gen, best_overall.fitness,
                    ", ".join(f"{k}={v:.4f}" for k, v in best_overall.to_dict().items()),
                )

            convergence_curve.append(best_overall.fitness)
            history.extend(p.copy() for p in offspring)

            # Early stopping
            if self.convergence_check(convergence_curve):
                logger.info("Converged at generation %d (fitness=%.6f)", gen, best_overall.fitness)
                break

        improvement_pct = (
            ((best_overall.fitness - initial_fitness) / abs(initial_fitness) * 100.0)
            if initial_fitness != 0.0
            else 0.0
        )

        logger.info(
            "Evolution complete: best_fitness=%.6f, improvement=%.1f%%",
            best_overall.fitness, improvement_pct,
        )

        return EvolutionResult(
            best_params=best_overall,
            history=history,
            generations_run=len(convergence_curve) - 1,
            convergence_curve=convergence_curve,
            improvement_pct=improvement_pct,
        )

    # ------------------------------------------------------------------
    # Evolutionary operators
    # ------------------------------------------------------------------

    def _gaussian_mutation(self, params: ParameterSet) -> ParameterSet:
        """
        Add Gaussian noise scaled by parameter range (mutation_sigma × range).
        Clips to bounds and respects integer types.
        """
        mutant = params.copy()
        for name, p in mutant.parameters.items():
            template = self._param_templates[name]
            noise = self._rng.gauss(0.0, self.mutation_sigma * template.range)
            mutant.parameters[name] = Parameter(
                name=p.name,
                value=template.clamp(p.value + noise),
                lower_bound=p.lower_bound,
                upper_bound=p.upper_bound,
                parameter_type=p.parameter_type,
                description=p.description,
            )
        mutant.fitness = 0.0
        mutant.evaluated = False
        return mutant

    def _crossover(self, parent1: ParameterSet, parent2: ParameterSet) -> ParameterSet:
        """
        Uniform crossover: each parameter is randomly drawn from one parent.
        """
        child = parent1.copy()
        for name in child.parameters:
            if self._rng.random() < 0.5:
                src = parent2.parameters[name]
                t = self._param_templates[name]
                child.parameters[name] = Parameter(
                    name=name,
                    value=src.value,
                    lower_bound=t.lower_bound,
                    upper_bound=t.upper_bound,
                    parameter_type=t.parameter_type,
                    description=t.description,
                )
        child.fitness = 0.0
        child.evaluated = False
        return child

    def _initialize_population(
        self, initial: Optional[dict] = None
    ) -> list[ParameterSet]:
        """
        Latin hypercube sampling (LHS) around the initial point.

        LHS guarantees one sample per stratum in each dimension, giving
        much better coverage than pure random for small populations.
        """
        n = self.population_size
        names = list(self._param_templates.keys())
        d = len(names)

        # LHS: generate stratified samples in [0, 1]^d
        lhs = np.zeros((n, d))
        for j in range(d):
            perm = self._np_rng.permutation(n)
            lhs[:, j] = (perm + self._np_rng.random(n)) / n

        population: list[ParameterSet] = []
        for i in range(n):
            ps_params: dict[str, Parameter] = {}
            for j, name in enumerate(names):
                t = self._param_templates[name]
                raw = t.lower_bound + lhs[i, j] * t.range
                ps_params[name] = Parameter(
                    name=t.name,
                    value=t.clamp(raw),
                    lower_bound=t.lower_bound,
                    upper_bound=t.upper_bound,
                    parameter_type=t.parameter_type,
                    description=t.description,
                )
            population.append(ParameterSet(parameters=ps_params))

        # Pin first individual to initial params (best-known starting point)
        if initial or any(
            t.value != (t.lower_bound + t.upper_bound) / 2.0
            for t in self._param_templates.values()
        ):
            anchor_params: dict[str, Parameter] = {}
            for name, t in self._param_templates.items():
                override = initial.get(name) if initial else None
                val = t.clamp(override if override is not None else t.value)
                anchor_params[name] = Parameter(
                    name=t.name,
                    value=val,
                    lower_bound=t.lower_bound,
                    upper_bound=t.upper_bound,
                    parameter_type=t.parameter_type,
                    description=t.description,
                )
            population[0] = ParameterSet(parameters=anchor_params)

        return population

    # ------------------------------------------------------------------
    # Surrogate model (quadratic OLS)
    # ------------------------------------------------------------------

    def _feature_vector(self, ps: ParameterSet) -> np.ndarray:
        """Build [1, x1, x2, ..., x1², x2², ..., x1*x2, ...] feature vector."""
        names = list(self._param_templates.keys())
        vals = np.array([ps.parameters[n].value for n in names], dtype=float)
        # Normalise to [0, 1] for numerical stability
        for j, name in enumerate(names):
            t = self._param_templates[name]
            r = t.range
            vals[j] = (vals[j] - t.lower_bound) / r if r > 0 else 0.0

        # Intercept + linear + quadratic + pairwise cross terms
        features = [1.0]
        features.extend(vals.tolist())
        # Quadratic diagonal
        features.extend((v * v for v in vals))
        # Pairwise interactions (only when d is small enough)
        d = len(vals)
        if d <= 20:
            for a in range(d):
                for b in range(a + 1, d):
                    features.append(float(vals[a] * vals[b]))
        return np.array(features, dtype=float)

    def _fit_surrogate(self, evaluated: list[ParameterSet]) -> None:
        """
        Fit quadratic OLS surrogate: fitness ≈ φ(params)ᵀ β.
        Uses all evaluated individuals.
        """
        if len(evaluated) < 3:
            return

        X = np.array([self._feature_vector(ps) for ps in evaluated])
        y = np.array([ps.fitness for ps in evaluated])

        # OLS with L2 regularisation: β = (XᵀX + λI)⁻¹ Xᵀy
        lam = 1e-6
        XtX = X.T @ X
        XtX += lam * np.eye(XtX.shape[0])
        Xty = X.T @ y
        try:
            self._surrogate_coeffs = np.linalg.solve(XtX, Xty)
            self._surrogate_fitted = True
        except np.linalg.LinAlgError:
            logger.warning("Surrogate OLS solve failed — using raw evaluations only")
            self._surrogate_fitted = False

    def _surrogate_predict(self, params: ParameterSet) -> float:
        """Predict fitness using the surrogate model."""
        if not self._surrogate_fitted or self._surrogate_coeffs is None:
            return 0.0
        phi = self._feature_vector(params)
        n_features = len(self._surrogate_coeffs)
        if len(phi) != n_features:
            # Dimension mismatch — skip
            return 0.0
        return float(self._surrogate_coeffs @ phi)

    # ------------------------------------------------------------------
    # Convergence checking
    # ------------------------------------------------------------------

    def convergence_check(
        self,
        history: list[float],
        patience: int = 5,
        min_improvement: float = 0.001,
    ) -> bool:
        """
        Return True if the best fitness has not improved by min_improvement
        in the last patience generations.
        """
        if len(history) < patience + 1:
            return False
        window = history[-(patience + 1):]
        improvement = window[-1] - window[0]
        # Allow negative improvement tolerance for maximisation problems
        return improvement < min_improvement

    # ------------------------------------------------------------------
    # Post-optimisation analysis
    # ------------------------------------------------------------------

    def get_sensitivity(self) -> dict[str, float]:
        """
        Compute sensitivity of each parameter as |∂fitness/∂param|.
        Uses the surrogate's linear coefficients (first-order terms) as a
        proxy for the gradient magnitude, normalised to [0, 1].

        Returns {param_name: sensitivity_score} — higher = more important.
        """
        if not self._surrogate_fitted or self._surrogate_coeffs is None:
            logger.warning("Surrogate not fitted — sensitivity unavailable")
            return {name: 0.0 for name in self._param_templates}

        names = list(self._param_templates.keys())
        d = len(names)
        # Coefficients 1..d are the linear (first-order) terms
        # They are in normalised space; multiply by 1/range to get physical gradient
        linear_coeffs = self._surrogate_coeffs[1: d + 1]  # skip intercept
        sensitivities: dict[str, float] = {}
        for j, name in enumerate(names):
            t = self._param_templates[name]
            # Un-normalise: coefficient in physical space = coeff / range
            phys_grad = abs(linear_coeffs[j]) * (1.0 / t.range if t.range > 0 else 0.0)
            sensitivities[name] = phys_grad

        # Normalise to [0, 1] for easy interpretation
        max_s = max(sensitivities.values()) if sensitivities else 1.0
        if max_s > 0:
            sensitivities = {k: v / max_s for k, v in sensitivities.items()}

        return sensitivities

    def suggest_next(self) -> dict[str, float]:
        """
        Suggest the most promising next evaluation point using an
        Expected Improvement (EI) approximation via surrogate.

        EI ≈ max(surrogate_predict(x) - best_so_far, 0)
        We sample many random candidates and return the argmax.

        Returns {param_name: value} within bounds.
        """
        if not self._surrogate_fitted or not self._all_evaluated:
            # Fall back to random sample from the feasible space
            names = list(self._param_templates.keys())
            return {
                name: self._param_templates[name].clamp(
                    self._rng.uniform(
                        self._param_templates[name].lower_bound,
                        self._param_templates[name].upper_bound,
                    )
                )
                for name in names
            }

        best_so_far = max(ps.fitness for ps in self._all_evaluated)
        n_candidates = 500
        best_candidate: Optional[ParameterSet] = None
        best_ei = -math.inf

        for _ in range(n_candidates):
            # Random candidate
            cand_params: dict[str, Parameter] = {}
            for name, t in self._param_templates.items():
                raw = self._rng.uniform(t.lower_bound, t.upper_bound)
                cand_params[name] = Parameter(
                    name=t.name,
                    value=t.clamp(raw),
                    lower_bound=t.lower_bound,
                    upper_bound=t.upper_bound,
                    parameter_type=t.parameter_type,
                    description=t.description,
                )
            cand = ParameterSet(parameters=cand_params)
            pred = self._surrogate_predict(cand)
            ei = max(pred - best_so_far, 0.0)
            if ei > best_ei:
                best_ei = ei
                best_candidate = cand

        if best_candidate is None:
            # Fallback
            return {
                name: self._param_templates[name].value
                for name in self._param_templates
            }

        return best_candidate.to_dict()


# ---------------------------------------------------------------------------
# Pre-configured BTC5 optimizer
# ---------------------------------------------------------------------------

def btc5_parameter_space() -> ParameterEvolution:
    """
    Pre-configured ParameterEvolution for BTC5 trading parameters.

    Covers the eight knobs most likely to explain BTC5's skip/fill behaviour:
      max_abs_delta, vpin_toxic_threshold, min_spread, max_spread,
      hour_start_et, hour_end_et, down_bias_weight, shadow_threshold.
    """
    evo = ParameterEvolution(
        population_size=20,
        generations=30,
        mutation_sigma=0.10,
        crossover_rate=0.50,
        elite_fraction=0.20,
        surrogate_warmup=10,
        random_seed=42,
    )

    evo.define_parameter(
        "max_abs_delta",
        lower=0.001,
        upper=0.020,
        initial=0.003,
        param_type="continuous",
        description="Maximum absolute delta allowed before skip_delta_too_large fires.",
    )
    evo.define_parameter(
        "vpin_toxic_threshold",
        lower=0.50,
        upper=0.90,
        initial=0.75,
        param_type="continuous",
        description="VPIN threshold above which order flow is considered toxic.",
    )
    evo.define_parameter(
        "min_spread",
        lower=0.01,
        upper=0.10,
        initial=0.02,
        param_type="continuous",
        description="Minimum bid-ask spread required to enter a position.",
    )
    evo.define_parameter(
        "max_spread",
        lower=0.05,
        upper=0.30,
        initial=0.15,
        param_type="continuous",
        description="Maximum bid-ask spread; wider spreads indicate stale books.",
    )
    evo.define_parameter(
        "hour_start_et",
        lower=0,
        upper=23,
        initial=3,
        param_type="integer",
        description="Start of the active trading window (ET hour, inclusive).",
    )
    evo.define_parameter(
        "hour_end_et",
        lower=0,
        upper=23,
        initial=19,
        param_type="integer",
        description="End of the active trading window (ET hour, inclusive).",
    )
    evo.define_parameter(
        "down_bias_weight",
        lower=0.0,
        upper=2.0,
        initial=1.0,
        param_type="continuous",
        description="Multiplicative weight for DOWN signals (>1 = DOWN-biased).",
    )
    evo.define_parameter(
        "shadow_threshold",
        lower=0.01,
        upper=0.20,
        initial=0.05,
        param_type="continuous",
        description="Minimum shadow candle fraction to allow entry.",
    )

    return evo
