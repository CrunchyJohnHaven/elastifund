"""Live violation checks for B-1 cached dependency edges."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from infra.clob_ws import BestBidAskStore


@dataclass(frozen=True)
class DepTradeLeg:
    market_id: str
    token_id: str
    side: str
    ask_price: float


@dataclass(frozen=True)
class DepViolation:
    edge_id: str
    relation: str
    confidence: float
    epsilon: float
    violation_mag: float
    legs: tuple[DepTradeLeg, ...]
    details: dict[str, Any]


class DepViolationMonitor:
    """Evaluate long-only arbitrage portfolios from cached dependency edges."""

    def __init__(
        self,
        *,
        token_map: Mapping[str, Mapping[str, str]],
        c1: float = 1.5,
        nonatomic_penalty: float = 0.01,
    ) -> None:
        self.token_map = {str(k): dict(v) for k, v in token_map.items()}
        self.c1 = float(c1)
        self.nonatomic_penalty = float(nonatomic_penalty)

    def compute_violation(
        self,
        edge: Mapping[str, Any],
        quote_store: BestBidAskStore,
    ) -> DepViolation | None:
        a_market_id = str(edge.get("a_market_id") or edge.get("market_a") or "")
        b_market_id = str(edge.get("b_market_id") or edge.get("market_b") or "")
        relation = str(edge.get("relation") or edge.get("relation_type") or "")
        confidence = float(edge.get("confidence") or edge.get("semantic_confidence") or 0.0)

        a_meta = self.token_map.get(a_market_id)
        b_meta = self.token_map.get(b_market_id)
        if not a_meta or not b_meta:
            return None

        a_yes = quote_store.get(a_meta.get("yes_token_id", ""))
        b_yes = quote_store.get(b_meta.get("yes_token_id", ""))
        a_no = quote_store.get(a_meta.get("no_token_id", ""))
        b_no = quote_store.get(b_meta.get("no_token_id", ""))

        if relation in {"A_implies_B", "subset"}:
            if not a_yes or not b_yes or not a_no:
                return None
            epsilon = self.c1 * ((a_yes.best_ask - a_yes.best_bid) + (b_yes.best_ask - b_yes.best_bid)) + self.nonatomic_penalty
            mag = a_yes.best_ask - b_yes.best_ask - epsilon
            if mag <= 0:
                return None
            return DepViolation(
                edge_id=str(edge.get("edge_id") or ""),
                relation=relation,
                confidence=confidence,
                epsilon=epsilon,
                violation_mag=mag,
                legs=(
                    DepTradeLeg(b_market_id, b_meta["yes_token_id"], "BUY", b_yes.best_ask),
                    DepTradeLeg(a_market_id, a_meta["no_token_id"], "BUY", a_no.best_ask),
                ),
                details={"portfolio": "YES(B)+NO(A)"},
            )

        if relation == "B_implies_A":
            if not a_yes or not b_yes or not b_no:
                return None
            epsilon = self.c1 * ((a_yes.best_ask - a_yes.best_bid) + (b_yes.best_ask - b_yes.best_bid)) + self.nonatomic_penalty
            mag = b_yes.best_ask - a_yes.best_ask - epsilon
            if mag <= 0:
                return None
            return DepViolation(
                edge_id=str(edge.get("edge_id") or ""),
                relation=relation,
                confidence=confidence,
                epsilon=epsilon,
                violation_mag=mag,
                legs=(
                    DepTradeLeg(a_market_id, a_meta["yes_token_id"], "BUY", a_yes.best_ask),
                    DepTradeLeg(b_market_id, b_meta["no_token_id"], "BUY", b_no.best_ask),
                ),
                details={"portfolio": "YES(A)+NO(B)"},
            )

        if relation == "mutually_exclusive":
            if not a_yes or not b_yes or not a_no or not b_no:
                return None
            epsilon = self.c1 * ((a_yes.best_ask - a_yes.best_bid) + (b_yes.best_ask - b_yes.best_bid)) + self.nonatomic_penalty
            mag = (a_yes.best_ask + b_yes.best_ask) - 1.0 - epsilon
            if mag <= 0:
                return None
            return DepViolation(
                edge_id=str(edge.get("edge_id") or ""),
                relation=relation,
                confidence=confidence,
                epsilon=epsilon,
                violation_mag=mag,
                legs=(
                    DepTradeLeg(a_market_id, a_meta["no_token_id"], "BUY", a_no.best_ask),
                    DepTradeLeg(b_market_id, b_meta["no_token_id"], "BUY", b_no.best_ask),
                ),
                details={"portfolio": "NO(A)+NO(B)"},
            )

        if relation == "complementary":
            if not a_yes or not b_yes or not a_no or not b_no:
                return None
            epsilon = self.c1 * ((a_yes.best_ask - a_yes.best_bid) + (b_yes.best_ask - b_yes.best_bid)) + self.nonatomic_penalty
            yes_sum = a_yes.best_ask + b_yes.best_ask
            if yes_sum < 1.0 - epsilon:
                return DepViolation(
                    edge_id=str(edge.get("edge_id") or ""),
                    relation=relation,
                    confidence=confidence,
                    epsilon=epsilon,
                    violation_mag=(1.0 - epsilon) - yes_sum,
                    legs=(
                        DepTradeLeg(a_market_id, a_meta["yes_token_id"], "BUY", a_yes.best_ask),
                        DepTradeLeg(b_market_id, b_meta["yes_token_id"], "BUY", b_yes.best_ask),
                    ),
                    details={"portfolio": "YES(A)+YES(B)"},
                )
            no_sum = a_no.best_ask + b_no.best_ask
            if yes_sum > 1.0 + epsilon:
                return DepViolation(
                    edge_id=str(edge.get("edge_id") or ""),
                    relation=relation,
                    confidence=confidence,
                    epsilon=epsilon,
                    violation_mag=yes_sum - (1.0 + epsilon),
                    legs=(
                        DepTradeLeg(a_market_id, a_meta["no_token_id"], "BUY", a_no.best_ask),
                        DepTradeLeg(b_market_id, b_meta["no_token_id"], "BUY", b_no.best_ask),
                    ),
                    details={"portfolio": "NO(A)+NO(B)", "no_sum": no_sum},
                )

        return None
