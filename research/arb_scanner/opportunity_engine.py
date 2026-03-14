"""
Portfolio evaluator and opportunity detector.

Implements seven arbitrage templates:
1. ComplementBoxArb - buy YES+NO, merge for $1
2. UnderroundArb - buy exhaustive outcomes for < $1
3. NegRiskConversionArb - buy NO, convert to YES basket
4. ImplicationArb - buy YES(B) + NO(A) when A implies B
5. TemporalArb - time-nested implication
6. MutualExclusionArb - buy NO(A) + NO(B) when exhaustive
7. CrossPlatformArb - same contract on Polymarket vs Kalshi

Each template evaluates wallets, computes edge, and estimates capital-days return.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from abc import ABC, abstractmethod
import math

from .claim_graph import Claim, ClaimGraph, RelationType


@dataclass
class OrderBook:
    """Simplified order book representation."""
    venue: str  # "polymarket" or "kalshi"
    token_id: str
    bids: List[Tuple[float, float]] = field(default_factory=list)  # (price, size)
    asks: List[Tuple[float, float]] = field(default_factory=list)  # (price, size)

    def best_bid(self) -> Optional[float]:
        """Highest bid price."""
        return self.bids[0][0] if self.bids else None

    def best_ask(self) -> Optional[float]:
        """Lowest ask price."""
        return self.asks[0][0] if self.asks else None

    def walk_book_buy(self, size: float) -> float:
        """Execute market buy of size, walk asks. Returns total cost."""
        cost = 0.0
        remaining = size
        for ask_price, ask_size in self.asks:
            if remaining <= 0:
                break
            take = min(remaining, ask_size)
            cost += take * ask_price
            remaining -= take
        return cost

    def walk_book_sell(self, size: float) -> float:
        """Execute market sell of size, walk bids. Returns total proceeds."""
        proceeds = 0.0
        remaining = size
        for bid_price, bid_size in self.bids:
            if remaining <= 0:
                break
            take = min(remaining, bid_size)
            proceeds += take * bid_price
            remaining -= take
        return proceeds


@dataclass
class FeeModel:
    """Fee structure across venues."""
    polymarket_taker_rate: float = 0.02  # 2% taker fee (dynamic per token, stub here)
    polymarket_maker_rate: float = 0.0  # 0% maker
    kalshi_taker_rate: float = 0.01  # 1% taker (varies by series)
    kalshi_maker_rate: float = 0.0  # 0% maker
    transform_cost_rate: float = 0.0005  # 0.05% for split/merge/convert (gas-less via relayer)

    def taker_fee(self, venue: str, size: float, side_proceeds: float) -> float:
        """Calculate taker fee for a transaction."""
        rate = self.polymarket_taker_rate if venue == "polymarket" else self.kalshi_taker_rate
        return side_proceeds * rate

    def transform_cost(self, size: float) -> float:
        """Cost for immediate transforms (split, merge, convert)."""
        return size * self.transform_cost_rate


@dataclass
class ArbOpportunity:
    """
    Identified arbitrage opportunity.

    Represents a specific route with estimated costs, payouts, and capital efficiency.
    """
    route: str  # Template name: "ComplementBox", "Underround", etc.
    size_q: float  # Share units to trade
    net_locked_edge: float  # Locked profit if completed, in dollars
    executable_cost: float  # All-in cost to execute (slippage + fees)
    guaranteed_payout: float  # Minimum payout at resolution (usually $1 * q)
    legs: List[Dict]  # List of execution legs with venue, token, side, price
    holding_period_estimate: float  # Days until resolution
    capital_days_return: float  # (edge / cost) / holding_period (annualized)
    arb_template: Optional['ArbTemplate'] = None

    def roi_pct(self) -> float:
        """Simple ROI: net edge / locked cost."""
        return 100.0 * (self.net_locked_edge / self.executable_cost) if self.executable_cost > 0 else 0.0

    def arr_pct(self) -> float:
        """Annualized return: capital-days ARR."""
        return 365.0 * self.capital_days_return if self.holding_period_estimate > 0 else 0.0


class ArbTemplate(ABC):
    """Abstract base for arbitrage templates."""

    def __init__(self, name: str, fees: FeeModel):
        self.name = name
        self.fees = fees

    @abstractmethod
    def is_applicable(self, claims: List[Claim], graph: ClaimGraph) -> bool:
        """Check if this template applies to the given claims."""
        pass

    @abstractmethod
    def find_opportunities(
        self,
        graph: ClaimGraph,
        books: Dict[str, OrderBook],
        min_edge: float = 0.01,
    ) -> List[ArbOpportunity]:
        """
        Scan for opportunities under this template.

        Args:
            graph: Claim graph with relations
            books: Dict mapping token_id -> OrderBook
            min_edge: Minimum edge threshold to report

        Returns:
            List of ArbOpportunity instances
        """
        pass

    def executable_cost(self, q: float, books: Dict[str, OrderBook]) -> float:
        """
        Walk the books to find actual execution cost for size q.

        This is the primary mechanism to avoid over-optimism (displayed mid != executable).
        """
        pass

    def guaranteed_min_payout(self, q: float) -> float:
        """Minimum payout if trade completes and all outcomes resolve correctly."""
        return q  # Most arbs resolve to $1 per share


class ComplementBoxArb(ArbTemplate):
    """
    Buy YES and NO in same market, sell immediately for $1 or merge.

    Edge: (best_bid_yes + best_bid_no) > $1 (sell box)
    Or: (best_ask_yes + best_ask_no) < $1 (buy box)
    """

    def __init__(self, fees: FeeModel):
        super().__init__("ComplementBox", fees)

    def is_applicable(self, claims: List[Claim], graph: ClaimGraph) -> bool:
        """Applicable if graph contains YES/NO pairs."""
        for claim in claims:
            outgoing, incoming = graph.get_relations_for_claim(claim)
            for rel in outgoing + incoming:
                if rel.relation_type == RelationType.COMPLEMENT:
                    return True
        return False

    def find_opportunities(
        self,
        graph: ClaimGraph,
        books: Dict[str, OrderBook],
        min_edge: float = 0.01,
    ) -> List[ArbOpportunity]:
        """Find YES/NO pairs with positive edge."""
        opportunities = []

        # Find all complement pairs
        for relation in graph.relations:
            if relation.relation_type != RelationType.COMPLEMENT:
                continue

            claim_yes = relation.claim_a
            claim_no = relation.claim_b

            yes_book = books.get(claim_yes.yes_token_id)
            no_book = books.get(claim_no.no_token_id)

            if not yes_book or not no_book:
                continue

            # Sell box: if we can sell YES at bid and NO at bid for > $1
            yes_bid = yes_book.best_bid()
            no_bid = no_book.best_bid()

            if yes_bid and no_bid:
                sell_box_proceeds = yes_bid + no_bid
                if sell_box_proceeds > 1.0 + min_edge:
                    # We'd need to own YES + NO first (synthetic short)
                    # Edge is proceeds - cost to acquire (usually ~$1 to buy both)
                    edge = sell_box_proceeds - 1.0
                    opp = ArbOpportunity(
                        route=f"{self.name}::SellBox[{claim_yes.market_id}]",
                        size_q=1.0,  # 1 share unit
                        net_locked_edge=edge,
                        executable_cost=1.0,  # Cost to buy both legs
                        guaranteed_payout=1.0,
                        legs=[
                            {"venue": claim_yes.venue, "token_id": claim_yes.yes_token_id, "side": "SELL", "size": 1.0},
                            {"venue": claim_no.venue, "token_id": claim_no.no_token_id, "side": "SELL", "size": 1.0},
                        ],
                        holding_period_estimate=0.0,  # Immediate transform
                        capital_days_return=float('inf') if edge > 0 else 0.0,
                        arb_template=self,
                    )
                    opportunities.append(opp)

            # Buy box: if we can buy YES at ask and NO at ask for < $1
            yes_ask = yes_book.best_ask()
            no_ask = no_book.best_ask()

            if yes_ask and no_ask:
                buy_box_cost = yes_ask + no_ask
                if buy_box_cost < 1.0 - min_edge:
                    edge = 1.0 - buy_box_cost
                    opp = ArbOpportunity(
                        route=f"{self.name}::BuyBox[{claim_yes.market_id}]",
                        size_q=1.0,
                        net_locked_edge=edge,
                        executable_cost=buy_box_cost,
                        guaranteed_payout=1.0,
                        legs=[
                            {"venue": claim_yes.venue, "token_id": claim_yes.yes_token_id, "side": "BUY", "size": 1.0},
                            {"venue": claim_no.venue, "token_id": claim_no.no_token_id, "side": "BUY", "size": 1.0},
                        ],
                        holding_period_estimate=0.0,
                        capital_days_return=float('inf') if edge > 0 else 0.0,
                        arb_template=self,
                    )
                    opportunities.append(opp)

        return opportunities


class UnderroundArb(ArbTemplate):
    """
    For exhaustive outcomes (partition), buy all YES for < $1.

    Example: {BTC>70k, BTC 60-70k, BTC<60k} must sum to $1 at resolution.
    If we can buy all three outcomes for < $1 total, we profit.
    """

    def __init__(self, fees: FeeModel):
        super().__init__("Underround", fees)

    def is_applicable(self, claims: List[Claim], graph: ClaimGraph) -> bool:
        """Applicable if graph contains partition peers."""
        for relation in graph.relations:
            if relation.relation_type == RelationType.PARTITION_PEER:
                return True
        return False

    def find_opportunities(
        self,
        graph: ClaimGraph,
        books: Dict[str, OrderBook],
        min_edge: float = 0.01,
    ) -> List[ArbOpportunity]:
        """Find exhaustive partitions that buy for < $1."""
        opportunities = []

        # Stub: would need to identify partition clusters
        # For now, return empty (full implementation requires graph analysis)
        return opportunities


class NegRiskConversionArb(ArbTemplate):
    """
    In neg-risk markets: buy NO, convert to YES basket, sell.

    Example: In a neg-risk BTC market, NO holder gets YES in a portfolio.
    If the YES basket trades below par, we arbitrage.
    """

    def __init__(self, fees: FeeModel):
        super().__init__("NegRiskConversion", fees)

    def is_applicable(self, claims: List[Claim], graph: ClaimGraph) -> bool:
        """Applicable if graph contains neg-risk peers."""
        for claim in claims:
            if claim.neg_risk:
                return True
        return False

    def find_opportunities(
        self,
        graph: ClaimGraph,
        books: Dict[str, OrderBook],
        min_edge: float = 0.01,
    ) -> List[ArbOpportunity]:
        """Find neg-risk conversion opportunities."""
        opportunities = []
        # Stub: would require basket composition and pricing
        return opportunities


class ImplicationArb(ArbTemplate):
    """
    If A implies B: buy YES(B) + NO(A).

    Guaranteed payout:
    - If A false: NO(A)=$1, YES(B) is free profit (A doesn't imply B, contradiction)
    - If A true: B must be true, YES(B)=$1, NO(A)=$0
    So minimum payout is $1.

    Edge: cost < $1.
    """

    def __init__(self, fees: FeeModel):
        super().__init__("Implication", fees)

    def is_applicable(self, claims: List[Claim], graph: ClaimGraph) -> bool:
        """Applicable if graph has IMPLIES relations."""
        for rel in graph.relations:
            if rel.relation_type == RelationType.IMPLIES:
                return True
        return False

    def find_opportunities(
        self,
        graph: ClaimGraph,
        books: Dict[str, OrderBook],
        min_edge: float = 0.01,
    ) -> List[ArbOpportunity]:
        """Find A=>B pairs where YES(B) + NO(A) < $1."""
        opportunities = []

        for relation in graph.relations:
            if relation.relation_type != RelationType.IMPLIES:
                continue

            claim_a = relation.claim_a
            claim_b = relation.claim_b

            # Get order books
            yes_b_book = books.get(claim_b.yes_token_id)
            no_a_book = books.get(claim_a.no_token_id)

            if not yes_b_book or not no_a_book:
                continue

            # Cost to buy YES(B) and NO(A)
            yes_b_ask = yes_b_book.best_ask()
            no_a_ask = no_a_book.best_ask()

            if yes_b_ask and no_a_ask:
                cost = yes_b_ask + no_a_ask
                if cost < 1.0 - min_edge:
                    edge = 1.0 - cost
                    opp = ArbOpportunity(
                        route=f"{self.name}[{claim_a.market_id} => {claim_b.market_id}]",
                        size_q=1.0,
                        net_locked_edge=edge,
                        executable_cost=cost,
                        guaranteed_payout=1.0,
                        legs=[
                            {"venue": claim_b.venue, "token_id": claim_b.yes_token_id, "side": "BUY", "size": 1.0},
                            {"venue": claim_a.venue, "token_id": claim_a.no_token_id, "side": "BUY", "size": 1.0},
                        ],
                        holding_period_estimate=(claim_a.end_date - claim_a.start_date).days if claim_a.end_date and claim_a.start_date else 30,
                        capital_days_return=edge / (cost * 30.0) if cost > 0 else 0.0,
                        arb_template=self,
                    )
                    opportunities.append(opp)

        return opportunities


class TemporalArb(ArbTemplate):
    """
    Time-nested implication: if Jun event implies Dec event.

    Example: "Will BTC > 70k by Jun 30?" implies "Will BTC > 70k by Dec 31?"
    because Jun resolution date < Dec resolution date.

    Buy YES(Dec) + NO(Jun) for edge if combined cost < $1.
    """

    def __init__(self, fees: FeeModel):
        super().__init__("Temporal", fees)

    def is_applicable(self, claims: List[Claim], graph: ClaimGraph) -> bool:
        """Applicable if graph has temporal ordering."""
        # Check for multiple claims with same subject/metric but different dates
        subjects = {}
        for claim in graph.claims.values():
            if claim.parsed_predicate:
                key = (claim.parsed_predicate.subject, claim.parsed_predicate.metric)
                if key not in subjects:
                    subjects[key] = []
                subjects[key].append(claim)

        for claim_list in subjects.values():
            if len(claim_list) > 1:
                return True
        return False

    def find_opportunities(
        self,
        graph: ClaimGraph,
        books: Dict[str, OrderBook],
        min_edge: float = 0.01,
    ) -> List[ArbOpportunity]:
        """Find temporal arbs."""
        opportunities = []
        # Stub: would require date-based implication matching
        return opportunities


class MutualExclusionArb(ArbTemplate):
    """
    If A and B cannot both be true: buy NO(A) + NO(B).

    Example: "Will Trump win?" and "Will Biden win?" are mutually exclusive.
    Buying NO on both guarantees $1 payout (at least one must be NO).

    Edge: cost < $1.
    """

    def __init__(self, fees: FeeModel):
        super().__init__("MutualExclusion", fees)

    def is_applicable(self, claims: List[Claim], graph: ClaimGraph) -> bool:
        """Applicable if graph has DISJOINT relations."""
        for rel in graph.relations:
            if rel.relation_type == RelationType.DISJOINT:
                return True
        return False

    def find_opportunities(
        self,
        graph: ClaimGraph,
        books: Dict[str, OrderBook],
        min_edge: float = 0.01,
    ) -> List[ArbOpportunity]:
        """Find mutually exclusive pairs where NO(A) + NO(B) < $1."""
        opportunities = []

        for relation in graph.relations:
            if relation.relation_type != RelationType.DISJOINT:
                continue

            claim_a = relation.claim_a
            claim_b = relation.claim_b

            no_a_book = books.get(claim_a.no_token_id)
            no_b_book = books.get(claim_b.no_token_id)

            if not no_a_book or not no_b_book:
                continue

            no_a_ask = no_a_book.best_ask()
            no_b_ask = no_b_book.best_ask()

            if no_a_ask and no_b_ask:
                cost = no_a_ask + no_b_ask
                if cost < 1.0 - min_edge:
                    edge = 1.0 - cost
                    opp = ArbOpportunity(
                        route=f"{self.name}[{claim_a.market_id} ∨ {claim_b.market_id}]",
                        size_q=1.0,
                        net_locked_edge=edge,
                        executable_cost=cost,
                        guaranteed_payout=1.0,
                        legs=[
                            {"venue": claim_a.venue, "token_id": claim_a.no_token_id, "side": "BUY", "size": 1.0},
                            {"venue": claim_b.venue, "token_id": claim_b.no_token_id, "side": "BUY", "size": 1.0},
                        ],
                        holding_period_estimate=30,
                        capital_days_return=edge / (cost * 30.0) if cost > 0 else 0.0,
                        arb_template=self,
                    )
                    opportunities.append(opp)

        return opportunities


class CrossPlatformArb(ArbTemplate):
    """
    Same contract on multiple platforms: arbitrage price differences.

    Example: BTC>70k on Polymarket trading 0.65 vs Kalshi trading 0.62.
    Buy Kalshi, sell Polymarket for edge.
    """

    def __init__(self, fees: FeeModel):
        super().__init__("CrossPlatform", fees)

    def is_applicable(self, claims: List[Claim], graph: ClaimGraph) -> bool:
        """Applicable if graph has EQUIVALENT claims across venues."""
        for rel in graph.relations:
            if rel.relation_type == RelationType.EQUIVALENT:
                if rel.claim_a.venue != rel.claim_b.venue:
                    return True
        return False

    def find_opportunities(
        self,
        graph: ClaimGraph,
        books: Dict[str, OrderBook],
        min_edge: float = 0.01,
    ) -> List[ArbOpportunity]:
        """Find cross-platform equivalent claims with price differential."""
        opportunities = []

        for relation in graph.relations:
            if relation.relation_type != RelationType.EQUIVALENT:
                continue
            if relation.claim_a.venue == relation.claim_b.venue:
                continue  # Only cross-venue

            claim_poly = relation.claim_a if relation.claim_a.venue == "polymarket" else relation.claim_b
            claim_kalshi = relation.claim_b if relation.claim_a.venue == "polymarket" else relation.claim_a

            yes_poly_book = books.get(claim_poly.yes_token_id)
            yes_kalshi_book = books.get(claim_kalshi.yes_token_id)

            if not yes_poly_book or not yes_kalshi_book:
                continue

            # If Kalshi ask < Polymarket bid, we can buy Kalshi and sell Polymarket
            kalshi_ask = yes_kalshi_book.best_ask()
            poly_bid = yes_poly_book.best_bid()

            if kalshi_ask and poly_bid and kalshi_ask < poly_bid:
                edge = poly_bid - kalshi_ask
                if edge > min_edge:
                    opp = ArbOpportunity(
                        route=f"{self.name}[Kalshi vs Polymarket, {claim_kalshi.question[:30]}...]",
                        size_q=1.0,
                        net_locked_edge=edge,
                        executable_cost=kalshi_ask,
                        guaranteed_payout=1.0,
                        legs=[
                            {"venue": "kalshi", "token_id": claim_kalshi.yes_token_id, "side": "BUY", "size": 1.0},
                            {"venue": "polymarket", "token_id": claim_poly.yes_token_id, "side": "SELL", "size": 1.0},
                        ],
                        holding_period_estimate=0.1,  # Quick settlement
                        capital_days_return=edge / (kalshi_ask * 0.1) if kalshi_ask > 0 else 0.0,
                        arb_template=self,
                    )
                    opportunities.append(opp)

        return opportunities


def evaluate_all_opportunities(
    graph: ClaimGraph,
    books: Dict[str, OrderBook],
    fees: Optional[FeeModel] = None,
    min_edge: float = 0.01,
) -> List[ArbOpportunity]:
    """
    Scan all templates for arbitrage opportunities.

    Args:
        graph: Claim graph with relations
        books: Dict mapping token_id -> OrderBook
        fees: Fee model (default: FeeModel())
        min_edge: Minimum edge threshold

    Returns:
        Sorted list of ArbOpportunity by capital-days ARR, descending.
    """
    if fees is None:
        fees = FeeModel()

    templates = [
        ComplementBoxArb(fees),
        UnderroundArb(fees),
        NegRiskConversionArb(fees),
        ImplicationArb(fees),
        TemporalArb(fees),
        MutualExclusionArb(fees),
        CrossPlatformArb(fees),
    ]

    all_opportunities = []
    claims = list(graph.claims.values())

    for template in templates:
        if template.is_applicable(claims, graph):
            opps = template.find_opportunities(graph, books, min_edge)
            all_opportunities.extend(opps)

    # Sort by capital-days ARR descending
    all_opportunities.sort(key=lambda x: x.arr_pct(), reverse=True)
    return all_opportunities
