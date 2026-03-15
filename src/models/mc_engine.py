"""Reusable Monte Carlo engine for short-horizon BTC path simulation."""

from __future__ import annotations

from dataclasses import dataclass
import math
import random
from typing import Iterable


@dataclass
class MCParams:
    s0: float
    mu_per_sec: float
    sigma_per_sqrt_sec: float
    horizon_sec: int
    dt_sec: int = 1
    paths: int = 10_000
    seed: int = 42


class MonteCarloEngine:
    """Short-horizon simulation engine with multiple path-generation modes."""

    def __init__(self, seed: int = 42):
        self.seed = seed

    def simulate_gbm(self, params: MCParams) -> list[float]:
        rng = random.Random(params.seed)
        steps = max(1, params.horizon_sec // max(1, params.dt_sec))
        dt = max(1, params.dt_sec)
        out: list[float] = []

        for _ in range(params.paths):
            s = params.s0
            for _ in range(steps):
                z = rng.gauss(0.0, 1.0)
                drift = (params.mu_per_sec - 0.5 * (params.sigma_per_sqrt_sec ** 2)) * dt
                shock = params.sigma_per_sqrt_sec * math.sqrt(dt) * z
                s *= math.exp(drift + shock)
            out.append(s)
        return out

    def simulate_jump_diffusion(
        self,
        params: MCParams,
        jump_lambda: float = 0.05,
        jump_mu: float = -0.02,
        jump_sigma: float = 0.03,
    ) -> list[float]:
        rng = random.Random(params.seed)
        steps = max(1, params.horizon_sec // max(1, params.dt_sec))
        dt = max(1, params.dt_sec)
        out: list[float] = []

        for _ in range(params.paths):
            s = params.s0
            for _ in range(steps):
                z = rng.gauss(0.0, 1.0)
                jump = 0.0
                if rng.random() < jump_lambda * (dt / 60.0):
                    jump = rng.gauss(jump_mu, jump_sigma)
                drift = (params.mu_per_sec - 0.5 * (params.sigma_per_sqrt_sec ** 2)) * dt
                shock = params.sigma_per_sqrt_sec * math.sqrt(dt) * z
                s *= math.exp(drift + shock + jump)
            out.append(s)
        return out

    def simulate_regime_switching(
        self,
        params: MCParams,
        low_sigma: float,
        high_sigma: float,
        p_low_to_high: float = 0.05,
        p_high_to_low: float = 0.10,
    ) -> list[float]:
        rng = random.Random(params.seed)
        steps = max(1, params.horizon_sec // max(1, params.dt_sec))
        dt = max(1, params.dt_sec)
        out: list[float] = []

        for _ in range(params.paths):
            s = params.s0
            high_regime = False
            for _ in range(steps):
                if high_regime and rng.random() < p_high_to_low:
                    high_regime = False
                elif not high_regime and rng.random() < p_low_to_high:
                    high_regime = True

                sigma = high_sigma if high_regime else low_sigma
                z = rng.gauss(0.0, 1.0)
                drift = (params.mu_per_sec - 0.5 * (sigma**2)) * dt
                shock = sigma * math.sqrt(dt) * z
                s *= math.exp(drift + shock)
            out.append(s)
        return out

    def simulate_historical_resample(
        self,
        s0: float,
        horizon_steps: int,
        realized_step_returns: Iterable[float],
        paths: int,
        seed: int,
    ) -> list[float]:
        rng = random.Random(seed)
        returns = list(realized_step_returns)
        if not returns:
            return [s0] * paths

        out: list[float] = []
        for _ in range(paths):
            s = s0
            for _ in range(max(1, horizon_steps)):
                r = returns[rng.randrange(0, len(returns))]
                s *= math.exp(r)
            out.append(s)
        return out

    @staticmethod
    def probability_close_above(paths: list[float], threshold: float) -> float:
        if not paths:
            return 0.5
        wins = sum(1 for value in paths if value >= threshold)
        return wins / len(paths)
