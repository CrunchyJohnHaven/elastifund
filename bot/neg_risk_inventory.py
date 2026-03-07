#!/usr/bin/env python3
"""Inventory and safety logic for Polymarket neg-risk baskets."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Iterable

try:
    from bot.resolution_normalizer import (
        NormalizedMarket,
        is_named_outcome,
        is_tradable_outcome,
        normalize_outcome_name,
    )
except ImportError:  # pragma: no cover - direct script mode
    from resolution_normalizer import (  # type: ignore
        NormalizedMarket,
        is_named_outcome,
        is_tradable_outcome,
        normalize_outcome_name,
    )


@dataclass(frozen=True)
class ConversionRecord:
    event_id: str
    from_outcome: str
    quantity: float
    generated_outcomes: tuple[str, ...]
    ts: int


@dataclass(frozen=True)
class MergeRecord:
    event_id: str
    outcome: str
    quantity: float
    tx_hash: str | None
    ts: int


class NegRiskInventory:
    """Track neg-risk inventory and enforce augmented-event trading constraints."""

    def __init__(self) -> None:
        self._event_named_outcomes: dict[str, set[str]] = {}
        self._event_augmented: dict[str, bool] = {}
        self._event_neg_risk: dict[str, bool] = {}
        self._positions: dict[tuple[str, str, str], float] = {}
        self._avg_cost: dict[tuple[str, str, str], float] = {}
        self._conversions: list[ConversionRecord] = []
        self._merges: list[MergeRecord] = []

    def register_market(self, market: NormalizedMarket) -> None:
        event_id = market.event_id
        if event_id not in self._event_named_outcomes:
            self._event_named_outcomes[event_id] = set()

        for outcome in market.outcomes:
            normalized = normalize_outcome_name(outcome)
            if is_named_outcome(normalized):
                self._event_named_outcomes[event_id].add(normalized)

        if market.outcome:
            normalized = normalize_outcome_name(market.outcome)
            if is_named_outcome(normalized):
                self._event_named_outcomes[event_id].add(normalized)

        self._event_augmented[event_id] = (
            self._event_augmented.get(event_id, False)
            or market.profile.is_augmented_neg_risk
        )
        self._event_neg_risk[event_id] = (
            self._event_neg_risk.get(event_id, False)
            or market.profile.is_neg_risk
        )

    def route_exchange(self, market: NormalizedMarket) -> str:
        """Route neg-risk markets through the adapter exchange path."""
        return "neg_risk_ctf_exchange" if market.profile.is_neg_risk else "standard_clob"

    def validate_order(self, market: NormalizedMarket, outcome: str) -> bool:
        """Block unsafe legs in augmented neg-risk events."""
        return is_tradable_outcome(market, outcome)

    def record_fill(
        self,
        *,
        event_id: str,
        outcome: str,
        side: str,
        quantity: float,
        price: float,
    ) -> None:
        key = (event_id, normalize_outcome_name(outcome), side.upper())
        prev_qty = self._positions.get(key, 0.0)
        prev_avg = self._avg_cost.get(key, 0.0)

        new_qty = prev_qty + float(quantity)
        if new_qty < 0:
            raise ValueError("position quantity cannot go negative")

        if new_qty == 0:
            self._positions.pop(key, None)
            self._avg_cost.pop(key, None)
            return

        weighted_avg = (
            ((prev_qty * prev_avg) + (float(quantity) * float(price))) / new_qty
            if quantity > 0
            else prev_avg
        )
        self._positions[key] = new_qty
        self._avg_cost[key] = weighted_avg

    def quantity(self, event_id: str, outcome: str, side: str) -> float:
        key = (event_id, normalize_outcome_name(outcome), side.upper())
        return self._positions.get(key, 0.0)

    def event_positions(self, event_id: str) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        for (eid, outcome, side), qty in self._positions.items():
            if eid != event_id:
                continue
            out.setdefault(outcome, {})[side] = qty
        return out

    def convert_no_to_yes_others(self, *, event_id: str, outcome: str, quantity: float) -> ConversionRecord:
        """Atomically convert NO(outcome) into YES(other named outcomes)."""
        if quantity <= 0:
            raise ValueError("quantity must be positive")

        outcome_norm = normalize_outcome_name(outcome)
        no_key = (event_id, outcome_norm, "NO")
        available = self._positions.get(no_key, 0.0)
        if available + 1e-9 < quantity:
            raise ValueError("insufficient NO inventory for conversion")

        named = sorted(self._event_named_outcomes.get(event_id, set()))
        others = tuple(name for name in named if name != outcome_norm)
        if not others:
            raise ValueError("cannot convert without alternate named outcomes")

        # Compute post-conversion state first, then commit.
        new_positions = dict(self._positions)
        new_positions[no_key] = max(0.0, available - quantity)
        if new_positions[no_key] == 0:
            new_positions.pop(no_key, None)

        for other in others:
            yes_key = (event_id, other, "YES")
            new_positions[yes_key] = new_positions.get(yes_key, 0.0) + quantity

        self._positions = new_positions

        record = ConversionRecord(
            event_id=event_id,
            from_outcome=outcome_norm,
            quantity=float(quantity),
            generated_outcomes=others,
            ts=int(time.time()),
        )
        self._conversions.append(record)
        return record

    def conversions(self) -> tuple[ConversionRecord, ...]:
        return tuple(self._conversions)

    def apply_merge(
        self,
        *,
        event_id: str,
        outcome: str,
        quantity: float,
        tx_hash: str | None = None,
    ) -> MergeRecord:
        """Reduce offsetting YES/NO inventory after an on-chain merge."""
        if quantity <= 0:
            raise ValueError("quantity must be positive")

        outcome_norm = normalize_outcome_name(outcome)
        yes_key = (event_id, outcome_norm, "YES")
        no_key = (event_id, outcome_norm, "NO")

        available_yes = self._positions.get(yes_key, 0.0)
        available_no = self._positions.get(no_key, 0.0)
        if available_yes + 1e-9 < quantity or available_no + 1e-9 < quantity:
            raise ValueError("insufficient YES/NO inventory for merge")

        new_positions = dict(self._positions)
        new_avg_cost = dict(self._avg_cost)

        for key, remaining in (
            (yes_key, available_yes - quantity),
            (no_key, available_no - quantity),
        ):
            if remaining <= 1e-9:
                new_positions.pop(key, None)
                new_avg_cost.pop(key, None)
            else:
                new_positions[key] = remaining

        self._positions = new_positions
        self._avg_cost = new_avg_cost

        record = MergeRecord(
            event_id=event_id,
            outcome=outcome_norm,
            quantity=float(quantity),
            tx_hash=tx_hash,
            ts=int(time.time()),
        )
        self._merges.append(record)
        return record

    def merges(self) -> tuple[MergeRecord, ...]:
        return tuple(self._merges)

    def is_event_augmented(self, event_id: str) -> bool:
        return self._event_augmented.get(event_id, False)

    def is_event_neg_risk(self, event_id: str) -> bool:
        return self._event_neg_risk.get(event_id, False)

    def named_outcomes(self, event_id: str) -> tuple[str, ...]:
        return tuple(sorted(self._event_named_outcomes.get(event_id, set())))

    def register_markets(self, markets: Iterable[NormalizedMarket]) -> None:
        for market in markets:
            self.register_market(market)
