"""Execution planning for A-6 baskets."""

from __future__ import annotations

import time

from execution.multileg_executor import LegSpec, MultiLegAttempt, MultiLegExecutor
from signals.sum_violation.sum_state import attempt_to_linked_state
from strategies.a6_sum_violation import A6Opportunity, EventWatch


class A6ExecutionPlanner:
    """Translate an A-6 opportunity into the shared multi-leg state machine."""

    def __init__(
        self,
        *,
        leg_usd_cap: float = 5.0,
        executor: MultiLegExecutor | None = None,
    ) -> None:
        self.leg_usd_cap = max(0.1, float(leg_usd_cap))
        self.executor = executor or MultiLegExecutor()

    def build_attempt(
        self,
        watch: EventWatch,
        opportunity: A6Opportunity,
        *,
        now_ts: float | None = None,
    ) -> MultiLegAttempt:
        now = float(now_ts or time.time())
        watch_by_market = {leg.market_id: leg for leg in watch.legs}
        leg_specs: list[LegSpec] = []

        for idx, quote in enumerate(opportunity.legs, start=1):
            watch_leg = watch_by_market[quote.market_id]
            price = max(watch_leg.tick_size, quote.maker_bid_target)
            size = max(watch_leg.min_order_size or 0.0, self.leg_usd_cap / max(price, watch_leg.tick_size))
            leg_specs.append(
                LegSpec(
                    leg_id=f"{watch.event_id}-leg-{idx}",
                    market_id=watch_leg.market_id,
                    token_id=watch_leg.yes_token_id,
                    side="BUY",
                    price=price,
                    size=round(size, 6),
                    tick_size=watch_leg.tick_size,
                    min_size=watch_leg.min_order_size,
                )
            )

        return self.executor.create_attempt(
            attempt_id=f"a6-{watch.event_id}-{int(now)}",
            strategy_id="A6",
            group_id=watch.event_id,
            leg_specs=leg_specs,
            metadata={
                "event_id": watch.event_id,
                "title": watch.title,
                "neg_risk": watch.neg_risk,
                "maker_sum_bid": opportunity.maker_sum_bid,
                "sum_yes_ask": opportunity.sum_yes_ask,
                "execute_ready": opportunity.execute_ready,
                "orderbook_ok": opportunity.orderbook_ok,
                "liquidity_ok": opportunity.liquidity_ok,
                "reasons": list(opportunity.reasons),
            },
            now_ts=now,
        )

    @staticmethod
    def to_state_payload(attempt: MultiLegAttempt) -> dict:
        return attempt_to_linked_state(attempt)
