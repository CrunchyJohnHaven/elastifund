"""Two-leg execution planning for B-1 violations."""

from __future__ import annotations

import time

from execution.multileg_executor import LegSpec, MultiLegAttempt, MultiLegExecutor
from signals.dep_graph.dep_monitor import DepViolation


class DepExecutionPlanner:
    """Convert a B-1 violation into the shared two-leg execution state."""

    def __init__(
        self,
        *,
        leg_usd_cap: float = 5.0,
        executor: MultiLegExecutor | None = None,
    ) -> None:
        self.leg_usd_cap = max(0.1, float(leg_usd_cap))
        self.executor = executor or MultiLegExecutor()

    def build_attempt(self, violation: DepViolation, *, now_ts: float | None = None) -> MultiLegAttempt:
        now = float(now_ts or time.time())
        leg_specs: list[LegSpec] = []
        for idx, leg in enumerate(violation.legs, start=1):
            price = max(0.001, float(leg.ask_price))
            size = self.leg_usd_cap / price
            leg_specs.append(
                LegSpec(
                    leg_id=f"{violation.edge_id}-leg-{idx}",
                    market_id=leg.market_id,
                    token_id=leg.token_id,
                    side=leg.side,
                    price=round(price, 6),
                    size=round(size, 6),
                    tick_size=0.001,
                    min_size=0.0,
                )
            )

        return self.executor.create_attempt(
            attempt_id=f"b1-{violation.edge_id}-{int(now)}",
            strategy_id="B1",
            group_id=violation.edge_id,
            leg_specs=leg_specs,
            metadata={
                "edge_id": violation.edge_id,
                "relation": violation.relation,
                "confidence": violation.confidence,
                "epsilon": violation.epsilon,
                "violation_mag": violation.violation_mag,
                "details": dict(violation.details),
            },
            now_ts=now,
        )
