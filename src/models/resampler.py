"""Historical bootstrap probability model."""

from __future__ import annotations

import math
import random


class HistoricalResampler:
    """Estimate short-horizon up probability from resampled historical returns."""

    def __init__(self, seed: int = 42):
        self.seed = seed

    def probability_up(
        self,
        current_price: float,
        open_price: float,
        realized_log_returns: list[float],
        horizon_steps: int,
        paths: int,
    ) -> float:
        if current_price <= 0.0 or open_price <= 0.0:
            return 0.5
        if not realized_log_returns:
            return 0.5

        rng = random.Random(self.seed)
        hits = 0
        for _ in range(max(paths, 1)):
            s = current_price
            for _ in range(max(horizon_steps, 1)):
                s *= math.exp(realized_log_returns[rng.randrange(0, len(realized_log_returns))])
            if s >= open_price:
                hits += 1
        return hits / max(paths, 1)
