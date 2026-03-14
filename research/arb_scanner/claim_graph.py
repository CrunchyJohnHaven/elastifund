"""
Claim normalization and relationship graph.

Normalizes claims from Polymarket and Kalshi into a unified representation,
builds a semantic relationship graph, and detects arbitrage-relevant connections.

Core concepts:
- Claim: Unified representation of a market/contract
- ParsedPredicate: Deterministic decomposition of a question (subject, metric, threshold, horizon)
- Relation: Connection between two claims (equivalence, implication, complement, etc.)
- ClaimGraph: Graph of claims with relations, supports queries
- Normalizers: Convert raw Polymarket/Kalshi data to Claims
- RelationBuilder: Cascade of deterministic, rule-based, and LLM-proposed relations
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Set, Tuple
from enum import Enum
import re
import hashlib
import json


class RelationType(Enum):
    """Relationship types between claims."""
    EQUIVALENT = "equivalent"  # Same outcome (e.g., BTC>$70k vs Bitcoin above 70000)
    COMPLEMENT = "complement"  # Exhaustive outcomes (YES+NO = $1)
    IMPLIES = "implies"  # If A true, B must be true
    REVERSE_IMPLIES = "reverse_implies"  # If B true, A must be true
    DISJOINT = "disjoint"  # Cannot both be true
    PARTITION_PEER = "partition_peer"  # Member of exhaustive partition (A, B, C outcomes)
    NEG_RISK_PEER = "neg_risk_peer"  # Paired under neg-risk rule (NO holder gets YES)
    UNRELATED = "unrelated"  # No meaningful relationship


@dataclass
class ParsedPredicate:
    """
    Deterministic decomposition of a market question.

    Examples:
    - "Will BTC > $70,000 on Dec 31?" -> subject="BTC", metric="price",
      comparator=">", threshold=70000, horizon="2024-12-31"
    - "US Unemployment < 4% by June 2026?" -> subject="US", metric="unemployment",
      comparator="<", threshold=4.0, horizon="2026-06-30"
    """
    subject: str  # "BTC", "US", "TechStock", etc.
    metric: str  # "price", "unemployment", "vote_count", "yes_votes", etc.
    comparator: str  # ">", "<", "==", ">=", "<=", "between"
    threshold: float  # Numeric threshold (or lower bound if "between")
    threshold_upper: Optional[float] = None  # Upper bound if comparator=="between"
    horizon: Optional[str] = None  # ISO 8601 date or "on resolution"
    jurisdiction: Optional[str] = None  # "US", "EU", etc.
    additional_context: Optional[str] = None  # Free-form: "excluding X", "as measured by Y"

    def to_dict(self) -> dict:
        """Serialize to dict."""
        return {
            "subject": self.subject,
            "metric": self.metric,
            "comparator": self.comparator,
            "threshold": self.threshold,
            "threshold_upper": self.threshold_upper,
            "horizon": self.horizon,
            "jurisdiction": self.jurisdiction,
            "additional_context": self.additional_context,
        }


@dataclass
class Claim:
    """
    Unified representation of a market or contract.

    Normalizes across Polymarket and Kalshi, storing the essential components
    for arbitrage analysis: what is being predicted, when, on which platform(s).
    """
    venue: str  # "polymarket" or "kalshi"
    event_id: str  # Polymarket event ID or Kalshi series ID
    market_id: str  # Polymarket market ID or Kalshi contract ID
    yes_token_id: str  # Polymarket YES token ID or Kalshi equivalent
    no_token_id: str  # Polymarket NO token ID or Kalshi equivalent
    question: str  # Full market question string
    description: Optional[str] = None  # Additional details
    resolution_source: Optional[str] = None  # "AMM", "UMA", "oracle feed", etc.
    category: Optional[str] = None  # "crypto", "politics", "sports", "economic"
    tags: List[str] = field(default_factory=list)  # ["BTC", "Q1-2026", "maker", etc.]
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    active: bool = True
    closed: bool = False
    enable_orderbook: bool = True
    neg_risk: bool = False  # True if this is a neg-risk market
    parsed_predicate: Optional[ParsedPredicate] = None
    semantic_fingerprint: str = ""  # Hash for dedup/equivalence matching

    def __post_init__(self):
        """Generate semantic fingerprint if not set."""
        if not self.semantic_fingerprint:
            self.semantic_fingerprint = self._compute_fingerprint()

    def _compute_fingerprint(self) -> str:
        """
        Compute deterministic hash of the claim's semantic content.

        Used for quick equivalence matching and deduplication.
        """
        core = f"{self.parsed_predicate.subject if self.parsed_predicate else ''}" \
               f":{self.parsed_predicate.metric if self.parsed_predicate else ''}" \
               f":{self.parsed_predicate.comparator if self.parsed_predicate else ''}" \
               f":{self.parsed_predicate.threshold if self.parsed_predicate else ''}"
        return hashlib.sha256(core.encode()).hexdigest()[:16]

    def __hash__(self):
        """Hash by (venue, market_id) for set/dict operations."""
        return hash((self.venue, self.market_id))

    def __eq__(self, other):
        """Equality by (venue, market_id)."""
        if not isinstance(other, Claim):
            return False
        return (self.venue, self.market_id) == (other.venue, other.market_id)


@dataclass
class Relation:
    """
    Semantic relationship between two claims.

    Verified_by indicates the source of confidence:
    - "deterministic": Rule-based or parsed structure (100% confidence)
    - "semantic": Embedding similarity or heuristic (high confidence)
    - "llm": LLM validation (high confidence, but requires latency)
    """
    relation_type: RelationType
    claim_a: Claim
    claim_b: Claim
    confidence: float  # 0.0 to 1.0
    explanation: str  # Human-readable reason for this relation
    verified_by: str = "deterministic"  # "deterministic", "semantic", "llm"

    def __hash__(self):
        """Hash by (claim_a, claim_b, relation_type)."""
        return hash((id(self.claim_a), id(self.claim_b), self.relation_type))


class ClaimGraph:
    """
    Graph of claims and relations, optimized for arbitrage queries.

    Supports:
    - Adding claims and relations
    - Querying connected components
    - Retrieving all relations for a claim
    - Path-finding for implication chains
    """

    def __init__(self):
        self.claims: Dict[str, Claim] = {}  # Key: (venue, market_id)
        self.relations: Set[Relation] = set()
        self.adjacency: Dict[Claim, List[Relation]] = {}  # Outgoing relations
        self.incoming: Dict[Claim, List[Relation]] = {}  # Incoming relations

    def add_claim(self, claim: Claim) -> None:
        """Add a claim to the graph."""
        key = (claim.venue, claim.market_id)
        if key not in self.claims:
            self.claims[key] = claim
            self.adjacency[claim] = []
            self.incoming[claim] = []

    def add_relation(self, relation: Relation) -> None:
        """
        Add a relation between two claims.

        Both claims must already be in the graph.
        """
        if relation.claim_a not in self.adjacency:
            self.add_claim(relation.claim_a)
        if relation.claim_b not in self.adjacency:
            self.add_claim(relation.claim_b)

        # Store as directed edge: a -> b
        self.relations.add(relation)
        self.adjacency[relation.claim_a].append(relation)
        self.incoming[relation.claim_b].append(relation)

    def get_claim(self, venue: str, market_id: str) -> Optional[Claim]:
        """Retrieve a claim by venue and market ID."""
        key = (venue, market_id)
        return self.claims.get(key)

    def get_relations_for_claim(self, claim: Claim) -> Tuple[List[Relation], List[Relation]]:
        """
        Get all relations involving a claim.

        Returns (outgoing, incoming) where outgoing are claim -> other
        and incoming are other -> claim.
        """
        outgoing = self.adjacency.get(claim, [])
        incoming = self.incoming.get(claim, [])
        return (outgoing, incoming)

    def get_connected_component(self, claim: Claim) -> Set[Claim]:
        """
        Get all claims reachable from a given claim via any relation.

        Uses breadth-first search.
        """
        visited = set()
        queue = [claim]

        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)

            # Add all neighbors
            outgoing, incoming = self.get_relations_for_claim(current)
            for rel in outgoing:
                if rel.claim_b not in visited:
                    queue.append(rel.claim_b)
            for rel in incoming:
                if rel.claim_a not in visited:
                    queue.append(rel.claim_a)

        return visited

    def find_implications_chain(self, claim_a: Claim, claim_b: Claim) -> Optional[List[Claim]]:
        """
        Find a chain of IMPLIES relations from claim_a to claim_b.

        Returns path (including endpoints) or None if no path exists.
        """
        from collections import deque

        queue = deque([(claim_a, [claim_a])])
        visited = {claim_a}

        while queue:
            current, path = queue.popleft()

            if current == claim_b:
                return path

            # Follow IMPLIES edges
            outgoing, _ = self.get_relations_for_claim(current)
            for rel in outgoing:
                if rel.relation_type in (RelationType.IMPLIES, RelationType.REVERSE_IMPLIES):
                    next_claim = rel.claim_b if rel.relation_type == RelationType.IMPLIES else rel.claim_a
                    if next_claim not in visited:
                        visited.add(next_claim)
                        queue.append((next_claim, path + [next_claim]))

        return None


def normalize_polymarket_claim(event: dict, market: dict) -> Claim:
    """
    Convert a Polymarket event + market to a normalized Claim.

    Args:
        event: Polymarket event dict (title, description, tags, startDate, endDate)
        market: Polymarket market dict (id, question, resolutionSource, tokens, orderbook)

    Returns:
        Normalized Claim object.
    """
    market_id = market.get("id")
    question = market.get("question", "")
    tokens = market.get("tokens", {})

    yes_token_id = tokens.get("1", "")
    no_token_id = tokens.get("0", "")

    event_id = event.get("id", "")
    category = event.get("category", "")
    tags = event.get("tags", [])

    start_date = None
    if event.get("startDate"):
        try:
            start_date = datetime.fromisoformat(event["startDate"].replace("Z", "+00:00"))
        except (ValueError, TypeError):
            pass

    end_date = None
    if event.get("endDate"):
        try:
            end_date = datetime.fromisoformat(event["endDate"].replace("Z", "+00:00"))
        except (ValueError, TypeError):
            pass

    parsed = parse_predicate(question, event.get("description"))

    return Claim(
        venue="polymarket",
        event_id=event_id,
        market_id=market_id,
        yes_token_id=yes_token_id,
        no_token_id=no_token_id,
        question=question,
        description=event.get("description"),
        resolution_source=market.get("resolutionSource"),
        category=category,
        tags=tags,
        start_date=start_date,
        end_date=end_date,
        active=event.get("active", True),
        closed=event.get("closed", False),
        enable_orderbook=market.get("enableOrderbook", True),
        neg_risk=market.get("negRisk", False),
        parsed_predicate=parsed,
    )


def normalize_kalshi_claim(market: dict) -> Claim:
    """
    Convert a Kalshi market dict to a normalized Claim.

    Args:
        market: Kalshi market dict (id, series_id, title, description, category, etc.)

    Returns:
        Normalized Claim object.
    """
    market_id = market.get("id")
    series_id = market.get("series_id", "")
    question = market.get("title", "")
    description = market.get("description", "")

    # Kalshi uses contract_a (YES) and contract_b (NO) tokens
    yes_token_id = market.get("yes_contract_id", market_id + "-YES")
    no_token_id = market.get("no_contract_id", market_id + "-NO")

    category = market.get("category", "")
    tags = [market.get("series_id", "")]

    start_date = None
    if market.get("start_date"):
        try:
            start_date = datetime.fromisoformat(market["start_date"].replace("Z", "+00:00"))
        except (ValueError, TypeError):
            pass

    end_date = None
    if market.get("end_date"):
        try:
            end_date = datetime.fromisoformat(market["end_date"].replace("Z", "+00:00"))
        except (ValueError, TypeError):
            pass

    parsed = parse_predicate(question, description)

    return Claim(
        venue="kalshi",
        event_id=series_id,
        market_id=market_id,
        yes_token_id=yes_token_id,
        no_token_id=no_token_id,
        question=question,
        description=description,
        resolution_source=market.get("resolution_source"),
        category=category,
        tags=tags,
        start_date=start_date,
        end_date=end_date,
        active=market.get("active", True),
        closed=market.get("closed", False),
        enable_orderbook=True,
        neg_risk=False,
        parsed_predicate=parsed,
    )


def parse_predicate(question: str, description: Optional[str] = None) -> ParsedPredicate:
    """
    Deterministic parser for structured predicates.

    Handles patterns like:
    - "Will BTC close above $70,000 on 2024-12-31?"
    - "US unemployment below 4% by June 2026?"
    - "Vote count for Proposition X exceeds 2M?"

    Falls back to heuristic extraction if pattern doesn't match exactly.

    Args:
        question: Market question string.
        description: Optional additional context.

    Returns:
        ParsedPredicate with best-effort parsing.
    """
    full_text = (question + " " + (description or "")).lower()

    # Default fallback
    default = ParsedPredicate(
        subject="UNKNOWN",
        metric="unknown",
        comparator="==",
        threshold=0.5,
        horizon=None,
        jurisdiction=None,
    )

    # Pattern 1: BTC / crypto prices
    btc_match = re.search(r'(btc|bitcoin).*?([<>=]+).*?\$?(\d+[,\d]*)', full_text)
    if btc_match:
        comparator = btc_match.group(2)
        threshold_str = btc_match.group(3).replace(",", "")
        try:
            threshold = float(threshold_str)
            return ParsedPredicate(
                subject="BTC",
                metric="price",
                comparator=comparator,
                threshold=threshold,
                horizon=_extract_date(full_text),
                jurisdiction=None,
            )
        except ValueError:
            pass

    # Pattern 2: Unemployment / economic indicators
    if "unemployment" in full_text:
        unemp_match = re.search(r'unemployment.*?([<>=]+).*?(\d+\.?\d*)%?', full_text)
        if unemp_match:
            comparator = unemp_match.group(1)
            try:
                threshold = float(unemp_match.group(2))
                return ParsedPredicate(
                    subject="US",
                    metric="unemployment",
                    comparator=comparator,
                    threshold=threshold,
                    horizon=_extract_date(full_text),
                    jurisdiction="US",
                )
            except ValueError:
                pass

    # Pattern 3: Vote counts
    if "vote" in full_text or "votes" in full_text:
        vote_match = re.search(r'votes?.*?([<>=]+).*?(\d+[,\d]*)', full_text)
        if vote_match:
            comparator = vote_match.group(1)
            threshold_str = vote_match.group(2).replace(",", "")
            try:
                threshold = float(threshold_str)
                return ParsedPredicate(
                    subject="VOTES",
                    metric="vote_count",
                    comparator=comparator,
                    threshold=threshold,
                    horizon=_extract_date(full_text),
                    jurisdiction=None,
                )
            except ValueError:
                pass

    # Fallback: try to extract any numeric threshold
    num_match = re.search(r'(\d+\.?\d*)', full_text)
    if num_match:
        try:
            threshold = float(num_match.group(1))
            return ParsedPredicate(
                subject="UNKNOWN",
                metric="unknown",
                comparator="==",
                threshold=threshold,
                horizon=_extract_date(full_text),
                jurisdiction=None,
            )
        except ValueError:
            pass

    return default


def _extract_date(text: str) -> Optional[str]:
    """Extract ISO 8601 date from text if present."""
    # ISO pattern
    iso_match = re.search(r'(\d{4}-\d{2}-\d{2})', text)
    if iso_match:
        return iso_match.group(1)

    # Common month patterns
    month_match = re.search(r'(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+(\d{1,2})?\s*,?\s*(\d{4})?', text)
    if month_match:
        month_map = {
            'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5, 'june': 6,
            'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12,
            'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
            'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
        }
        month = month_map.get(month_match.group(1).lower(), 1)
        day = int(month_match.group(2)) if month_match.group(2) else 15
        year = int(month_match.group(3)) if month_match.group(3) else 2026
        return f"{year:04d}-{month:02d}-{day:02d}"

    return None


def build_relation_candidates(claims: List[Claim]) -> List[Relation]:
    """
    Build candidate relations across claims using cascade approach.

    Cascade:
    1. Same-event deterministic equivalence (same event, same predicate)
    2. Cross-event rule-based relations (implication via predicate logic)
    3. Embedding shortlist (stub: would use embeddings in production)
    4. LLM verification (stub: would call LLM in production)

    Args:
        claims: List of claims to relate.

    Returns:
        List of relations with confidence scores.
    """
    relations = []

    # Stage 1: Same-event deterministic equivalence
    events = {}
    for claim in claims:
        event_key = (claim.venue, claim.event_id)
        if event_key not in events:
            events[event_key] = []
        events[event_key].append(claim)

    for event_claims in events.values():
        # Within same event, same predicate fingerprint = equivalent
        fingerprints = {}
        for claim in event_claims:
            fp = claim.semantic_fingerprint
            if fp not in fingerprints:
                fingerprints[fp] = []
            fingerprints[fp].append(claim)

        for fp, equiv_claims in fingerprints.items():
            for i, claim_a in enumerate(equiv_claims):
                for claim_b in equiv_claims[i+1:]:
                    relations.append(Relation(
                        relation_type=RelationType.EQUIVALENT,
                        claim_a=claim_a,
                        claim_b=claim_b,
                        confidence=1.0,
                        explanation="Same event, identical parsed predicate",
                        verified_by="deterministic",
                    ))

    # Stage 2: Cross-event rule-based implication
    for i, claim_a in enumerate(claims):
        for claim_b in claims[i+1:]:
            if claim_a.parsed_predicate and claim_b.parsed_predicate:
                pred_a = claim_a.parsed_predicate
                pred_b = claim_b.parsed_predicate

                # Same subject/metric, different thresholds = implication
                if pred_a.subject == pred_b.subject and pred_a.metric == pred_b.metric:
                    # e.g., "BTC > 80k" implies "BTC > 70k"
                    if pred_a.comparator == ">" and pred_b.comparator == ">":
                        if pred_a.threshold > pred_b.threshold:
                            relations.append(Relation(
                                relation_type=RelationType.IMPLIES,
                                claim_a=claim_a,
                                claim_b=claim_b,
                                confidence=0.95,
                                explanation=f"{pred_a.subject}>{pred_a.threshold} implies {pred_b.subject}>{pred_b.threshold}",
                                verified_by="deterministic",
                            ))

    # Stage 3: Complement detection (YES and NO in same market)
    for i, claim_a in enumerate(claims):
        for claim_b in claims[i+1:]:
            # Complement if same market, different outcome tokens
            if (claim_a.venue == claim_b.venue and
                claim_a.market_id == claim_b.market_id and
                claim_a.yes_token_id == claim_b.no_token_id):
                relations.append(Relation(
                    relation_type=RelationType.COMPLEMENT,
                    claim_a=claim_a,
                    claim_b=claim_b,
                    confidence=1.0,
                    explanation="YES and NO tokens of same market",
                    verified_by="deterministic",
                ))

    return relations
