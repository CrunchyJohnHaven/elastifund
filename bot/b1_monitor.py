#!/usr/bin/env python3
"""Phase-1 B-1 live monitor for implication and exclusion violations."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import time
from typing import Any, Mapping, Sequence

try:
    from bot.constraint_arb_engine import ConstraintArbEngine, GraphEdge, MarketQuote
    from bot.resolution_normalizer import NormalizedMarket, resolution_equivalence_gate
except ImportError:  # pragma: no cover - direct script mode
    from constraint_arb_engine import ConstraintArbEngine, GraphEdge, MarketQuote  # type: ignore
    from resolution_normalizer import NormalizedMarket, resolution_equivalence_gate  # type: ignore


TRADABLE_RELATIONS = frozenset({"A_implies_B", "B_implies_A", "mutually_exclusive"})
LOG_ONLY_RELATIONS = frozenset({"complementary", "subset", "conditional_chain"})


def _now_ts() -> int:
    return int(time.time())


@dataclass(frozen=True)
class B1LegQuote:
    leg_id: str
    market_id: str
    side: str
    best_bid: float
    best_ask: float
    updated_ts: int


@dataclass(frozen=True)
class B1Opportunity:
    opportunity_id: str
    edge_id: str
    relation_type: str
    basket_action: str
    market_ids: tuple[str, str]
    legs: tuple[B1LegQuote, B1LegQuote]
    trigger_edge: float
    theoretical_edge: float
    payoff_floor: float
    relation_confidence: float
    resolution_gate_status: str
    resolution_gate_reasons: tuple[str, ...]
    quote_age_seconds: int
    detected_at_ts: int
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class B1MonitorTrace:
    edge_id: str
    relation_type: str
    market_ids: tuple[str, str]
    reason: str
    detected_at_ts: int
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class B1MonitorBatch:
    executable: tuple[B1Opportunity, ...]
    log_only: tuple[B1MonitorTrace, ...]
    dropped: tuple[B1MonitorTrace, ...]

    @property
    def metrics(self) -> dict[str, int]:
        stale = sum(1 for row in self.dropped if row.reason == "stale_book")
        gated = sum(1 for row in self.dropped if row.reason == "resolution_gate_failed")
        duplicate = sum(1 for row in self.dropped if row.reason == "duplicate_snapshot")
        return {
            "executable_count": len(self.executable),
            "log_only_count": len(self.log_only),
            "dropped_count": len(self.dropped),
            "stale_book_count": stale,
            "resolution_gate_drop_count": gated,
            "duplicate_drop_count": duplicate,
        }


class B1Monitor:
    """Convert graph edges + live quotes into executable B-1 shadow opportunities."""

    def __init__(
        self,
        *,
        relation_threshold: float = 0.03,
        stale_book_seconds: int = 30,
        snapshot_dedupe_seconds: int = 15,
    ) -> None:
        self.relation_threshold = float(relation_threshold)
        self.stale_book_seconds = int(stale_book_seconds)
        self.snapshot_dedupe_seconds = max(1, int(snapshot_dedupe_seconds))
        self._seen_signatures: set[tuple[str, int, int, int]] = set()

    def scan_engine(self, engine: ConstraintArbEngine, *, now_ts: int | None = None) -> B1MonitorBatch:
        return self.scan(
            markets=engine.markets,
            edges=engine.edges.values(),
            quotes=engine.quotes,
            now_ts=now_ts,
        )

    def scan(
        self,
        *,
        markets: Mapping[str, NormalizedMarket],
        edges: Sequence[GraphEdge] | Mapping[str, GraphEdge],
        quotes: Mapping[str, MarketQuote],
        now_ts: int | None = None,
    ) -> B1MonitorBatch:
        now_ts = int(now_ts or _now_ts())
        edge_rows = list(edges.values()) if isinstance(edges, Mapping) else list(edges)

        executable: list[B1Opportunity] = []
        log_only: list[B1MonitorTrace] = []
        dropped: list[B1MonitorTrace] = []

        for edge in sorted(edge_rows, key=lambda row: row.edge_id):
            market_a = markets.get(edge.market_a)
            market_b = markets.get(edge.market_b)
            quote_a = quotes.get(edge.market_a)
            quote_b = quotes.get(edge.market_b)
            market_ids = (edge.market_a, edge.market_b)

            if not market_a or not market_b or not quote_a or not quote_b:
                dropped.append(
                    B1MonitorTrace(
                        edge_id=edge.edge_id,
                        relation_type=edge.relation_type,
                        market_ids=market_ids,
                        reason="missing_market_or_quote",
                        detected_at_ts=now_ts,
                    )
                )
                continue

            gate = resolution_equivalence_gate([market_a, market_b])
            if not gate.passed:
                dropped.append(
                    B1MonitorTrace(
                        edge_id=edge.edge_id,
                        relation_type=edge.relation_type,
                        market_ids=market_ids,
                        reason="resolution_gate_failed",
                        detected_at_ts=now_ts,
                        details={"gate_reasons": list(gate.reasons)},
                    )
                )
                continue

            if edge.relation_type in LOG_ONLY_RELATIONS:
                log_only.append(
                    B1MonitorTrace(
                        edge_id=edge.edge_id,
                        relation_type=edge.relation_type,
                        market_ids=market_ids,
                        reason="phase1_log_only",
                        detected_at_ts=now_ts,
                        details={"gate_reasons": list(gate.reasons)},
                    )
                )
                continue

            if edge.relation_type not in TRADABLE_RELATIONS:
                continue

            max_age = max(now_ts - quote_a.updated_ts, now_ts - quote_b.updated_ts)
            if max_age > self.stale_book_seconds:
                dropped.append(
                    B1MonitorTrace(
                        edge_id=edge.edge_id,
                        relation_type=edge.relation_type,
                        market_ids=market_ids,
                        reason="stale_book",
                        detected_at_ts=now_ts,
                        details={"quote_age_seconds": max_age},
                    )
                )
                continue

            opportunity = self._build_opportunity(
                edge=edge,
                market_a=market_a,
                market_b=market_b,
                quote_a=quote_a,
                quote_b=quote_b,
                gate_reasons=gate.reasons,
                now_ts=now_ts,
            )
            if opportunity is None:
                continue

            dedupe_key = (
                edge.edge_id,
                now_ts // self.snapshot_dedupe_seconds,
                int(opportunity.trigger_edge * 10_000),
                int(opportunity.theoretical_edge * 10_000),
            )
            if dedupe_key in self._seen_signatures:
                dropped.append(
                    B1MonitorTrace(
                        edge_id=edge.edge_id,
                        relation_type=edge.relation_type,
                        market_ids=market_ids,
                        reason="duplicate_snapshot",
                        detected_at_ts=now_ts,
                        details={
                            "trigger_edge": opportunity.trigger_edge,
                            "theoretical_edge": opportunity.theoretical_edge,
                        },
                    )
                )
                continue

            self._seen_signatures.add(dedupe_key)
            executable.append(opportunity)

        return B1MonitorBatch(
            executable=tuple(executable),
            log_only=tuple(log_only),
            dropped=tuple(dropped),
        )

    def _build_opportunity(
        self,
        *,
        edge: GraphEdge,
        market_a: NormalizedMarket,
        market_b: NormalizedMarket,
        quote_a: MarketQuote,
        quote_b: MarketQuote,
        gate_reasons: Sequence[str],
        now_ts: int,
    ) -> B1Opportunity | None:
        if edge.relation_type == "A_implies_B":
            trigger_edge = quote_a.yes_bid - quote_b.yes_ask
            legs = (
                self._make_leg_quote(market_id=market_a.market_id, side="NO", quote=quote_a),
                self._make_leg_quote(market_id=market_b.market_id, side="YES", quote=quote_b),
            )
            basket_action = "buy_no_a_buy_yes_b"
        elif edge.relation_type == "B_implies_A":
            trigger_edge = quote_b.yes_bid - quote_a.yes_ask
            legs = (
                self._make_leg_quote(market_id=market_b.market_id, side="NO", quote=quote_b),
                self._make_leg_quote(market_id=market_a.market_id, side="YES", quote=quote_a),
            )
            basket_action = "buy_no_b_buy_yes_a"
        elif edge.relation_type == "mutually_exclusive":
            trigger_edge = quote_a.yes_bid + quote_b.yes_bid - 1.0
            legs = (
                self._make_leg_quote(market_id=market_a.market_id, side="NO", quote=quote_a),
                self._make_leg_quote(market_id=market_b.market_id, side="NO", quote=quote_b),
            )
            basket_action = "buy_no_pair"
        else:
            return None

        if trigger_edge <= self.relation_threshold:
            return None

        total_cost = sum(leg.best_ask for leg in legs)
        theoretical_edge = 1.0 - total_cost
        if theoretical_edge <= 0:
            return None

        quote_age = max(now_ts - leg.updated_ts for leg in legs)
        payload = (
            f"{edge.edge_id}|{edge.relation_type}|"
            f"{legs[0].market_id}:{legs[0].side}:{legs[0].best_ask:.4f}|"
            f"{legs[1].market_id}:{legs[1].side}:{legs[1].best_ask:.4f}|"
            f"{now_ts // self.snapshot_dedupe_seconds}"
        )
        opportunity_id = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:20]
        return B1Opportunity(
            opportunity_id=opportunity_id,
            edge_id=edge.edge_id,
            relation_type=edge.relation_type,
            basket_action=basket_action,
            market_ids=(market_a.market_id, market_b.market_id),
            legs=legs,
            trigger_edge=float(trigger_edge),
            theoretical_edge=float(theoretical_edge),
            payoff_floor=1.0,
            relation_confidence=float(edge.semantic_confidence),
            resolution_gate_status="passed",
            resolution_gate_reasons=tuple(gate_reasons),
            quote_age_seconds=int(quote_age),
            detected_at_ts=now_ts,
            details={
                "market_a_question": market_a.question,
                "market_b_question": market_b.question,
                "quote_a_yes_bid": quote_a.yes_bid,
                "quote_a_yes_ask": quote_a.yes_ask,
                "quote_b_yes_bid": quote_b.yes_bid,
                "quote_b_yes_ask": quote_b.yes_ask,
                "trigger_threshold": self.relation_threshold,
            },
        )

    @staticmethod
    def _make_leg_quote(*, market_id: str, side: str, quote: MarketQuote) -> B1LegQuote:
        side_upper = side.upper()
        if side_upper == "YES":
            best_bid = float(quote.yes_bid)
            best_ask = float(quote.yes_ask)
        elif side_upper == "NO":
            best_bid = float(quote.no_bid)
            best_ask = float(quote.no_ask)
        else:
            raise ValueError(f"unsupported leg side: {side}")

        return B1LegQuote(
            leg_id=f"{market_id}:{side_upper}",
            market_id=market_id,
            side=side_upper,
            best_bid=best_bid,
            best_ask=best_ask,
            updated_ts=int(quote.updated_ts),
        )
