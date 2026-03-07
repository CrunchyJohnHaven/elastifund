"""Execution-aware monitoring for B-1 dependency-graph violations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from infra.clob_ws import BestBidAskStore
from strategies.b1_dependency_graph import GraphStore, MarketMeta, PairEdge


@dataclass(frozen=True)
class B1ViolationSignal:
    edge_label: str
    market_ids: tuple[str, str]
    action: str
    gross_edge: float
    details: dict[str, Any]


class B1ViolationMonitor:
    def __init__(
        self,
        *,
        graph_store: GraphStore,
        quote_store: BestBidAskStore,
        implication_threshold: float = 0.02,
        complementary_threshold: float = 0.02,
        max_stale_seconds: float = 2.0,
    ) -> None:
        self.graph_store = graph_store
        self.quote_store = quote_store
        self.implication_threshold = float(implication_threshold)
        self.complementary_threshold = float(complementary_threshold)
        self.max_stale_seconds = float(max_stale_seconds)

    def scan(self, *, min_confidence: float = 0.8) -> list[B1ViolationSignal]:
        out: list[B1ViolationSignal] = []
        for edge in self.graph_store.load_edges(min_confidence=min_confidence):
            market_a = self.graph_store.get_market(edge.a_id)
            market_b = self.graph_store.get_market(edge.b_id)
            if market_a is None or market_b is None:
                continue
            signal = self._check_edge(edge, market_a, market_b)
            if signal is not None:
                out.append(signal)
        return out

    def _check_edge(self, edge: PairEdge, market_a: MarketMeta, market_b: MarketMeta) -> B1ViolationSignal | None:
        if not market_a.yes_token_id or not market_b.yes_token_id:
            return None
        if not self.quote_store.is_fresh(market_a.yes_token_id, max_age_seconds=self.max_stale_seconds):
            return None
        if not self.quote_store.is_fresh(market_b.yes_token_id, max_age_seconds=self.max_stale_seconds):
            return None

        quote_a = self.quote_store.get(market_a.yes_token_id)
        quote_b = self.quote_store.get(market_b.yes_token_id)
        if quote_a is None or quote_b is None:
            return None

        bid_a = float(quote_a.best_bid)
        ask_a = float(quote_a.best_ask)
        bid_b = float(quote_b.best_bid)
        ask_b = float(quote_b.best_ask)

        if edge.label in {"A_implies_B", "subset"} and bid_a > ask_b + self.implication_threshold:
            return B1ViolationSignal(
                edge_label=edge.label,
                market_ids=(market_a.market_id, market_b.market_id),
                action="sell_A_buy_B",
                gross_edge=bid_a - ask_b,
                details={"bid_a": bid_a, "ask_b": ask_b},
            )

        if edge.label == "B_implies_A" and bid_b > ask_a + self.implication_threshold:
            return B1ViolationSignal(
                edge_label=edge.label,
                market_ids=(market_a.market_id, market_b.market_id),
                action="sell_B_buy_A",
                gross_edge=bid_b - ask_a,
                details={"bid_b": bid_b, "ask_a": ask_a},
            )

        if edge.label == "mutually_exclusive" and bid_a + bid_b > 1.0 + self.implication_threshold:
            return B1ViolationSignal(
                edge_label=edge.label,
                market_ids=(market_a.market_id, market_b.market_id),
                action="buy_no_pair",
                gross_edge=(bid_a + bid_b) - 1.0,
                details={"bid_a": bid_a, "bid_b": bid_b},
            )

        if edge.label == "complementary":
            total_bid = bid_a + bid_b
            if total_bid < 1.0 - self.complementary_threshold:
                return B1ViolationSignal(
                    edge_label=edge.label,
                    market_ids=(market_a.market_id, market_b.market_id),
                    action="buy_yes_pair",
                    gross_edge=1.0 - total_bid,
                    details={"bid_a": bid_a, "bid_b": bid_b},
                )
            if total_bid > 1.0 + self.complementary_threshold:
                return B1ViolationSignal(
                    edge_label=edge.label,
                    market_ids=(market_a.market_id, market_b.market_id),
                    action="buy_no_pair",
                    gross_edge=total_bid - 1.0,
                    details={"bid_a": bid_a, "bid_b": bid_b},
                )

        return None
