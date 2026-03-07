"""Real-Time Bayesian Signal Processing for sequential belief updating.

Implements the Bayesian agent decision architecture from QR-PM-2026-0041:
- Sequential Bayesian updating in log-space for numerical stability
- Multiple evidence source integration (Claude, news, volume, price action)
- Position sizing via expected value: EV = p_hat - p_market

Reference: "Real-Time Bayesian Signal Processing Agent Decision Architecture"

Core update rule (log-space, numerically stable):
    log P(H|D) = log P(H) + sum(log P(Dk|H)) - log Z

where Z is the normalizing constant.

Update cycle latency targets (production):
    Component                    Avg      p99
    Data ingestion (API/ws)      128ms    348ms
    Bayesian posterior           15ms     28ms
    LMSR price comparison        3ms      8ms
    Order execution (CLOB)       690ms    1400ms
    Total cycle                  828ms    1776ms
"""
from __future__ import annotations

import math
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

try:
    import structlog
    logger = structlog.get_logger(__name__)
    _USE_STRUCTLOG = True
except ImportError:
    logger = logging.getLogger(__name__)
    _USE_STRUCTLOG = False


def _log(level: str, msg: str, **kwargs) -> None:
    if _USE_STRUCTLOG:
        getattr(logger, level)(msg, **kwargs)
    else:
        extra = " ".join(f"{k}={v}" for k, v in kwargs.items())
        getattr(logger, level)(f"{msg} {extra}")


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------

@dataclass
class Evidence:
    """A single piece of evidence for Bayesian updating."""
    source: str           # e.g., "claude", "news", "volume_spike", "price_action"
    likelihood_yes: float # P(D|H=YES) — how likely is this evidence if YES
    likelihood_no: float  # P(D|H=NO) — how likely is this evidence if NO
    timestamp: float = 0.0
    description: str = ""
    weight: float = 1.0   # Evidence weight multiplier (0-1, for decay)

    @property
    def log_likelihood_ratio(self) -> float:
        """Log-likelihood ratio: log(P(D|YES) / P(D|NO))."""
        if self.likelihood_no <= 0:
            return 30.0  # Cap at extreme
        if self.likelihood_yes <= 0:
            return -30.0
        return math.log(self.likelihood_yes / self.likelihood_no)


@dataclass
class BeliefState:
    """Current belief state for a market hypothesis."""
    market_id: str
    log_odds: float = 0.0        # log(P(YES) / P(NO)), 0 = 50/50
    evidence_count: int = 0
    last_update: float = 0.0
    evidence_history: list[Evidence] = field(default_factory=list)
    max_history: int = 50

    @property
    def probability_yes(self) -> float:
        """Convert log-odds to probability: P(YES) = sigmoid(log_odds)."""
        clamped = max(-30, min(30, self.log_odds))
        return 1.0 / (1.0 + math.exp(-clamped))

    @property
    def probability_no(self) -> float:
        return 1.0 - self.probability_yes


# ---------------------------------------------------------------------------
# Bayesian Signal Processor
# ---------------------------------------------------------------------------

class BayesianSignalProcessor:
    """Sequential Bayesian belief updater for prediction markets.

    Maintains a running belief (log-odds) for each tracked market and
    updates it as new evidence arrives. All computation is in log-space
    for numerical stability.

    Core equation:
        log P(H|D1,...,Di) = log P(H) + sum_k(log P(Dk|H)) - log Z

    In log-odds form (avoids computing Z):
        log_odds_posterior = log_odds_prior + sum_k(log_likelihood_ratio_k)
    """

    def __init__(
        self,
        evidence_decay_hours: float = 24.0,
        max_log_odds: float = 5.0,
        min_evidence_weight: float = 0.1,
    ):
        """Initialize the Bayesian signal processor.

        Args:
            evidence_decay_hours: Half-life for evidence decay (older evidence
                gets less weight). Set to 0 to disable decay.
            max_log_odds: Maximum absolute log-odds (prevents extreme beliefs).
                log_odds=5 corresponds to ~99.3% probability.
            min_evidence_weight: Floor for decayed evidence weight.
        """
        self.evidence_decay_hours = evidence_decay_hours
        self.max_log_odds = max_log_odds
        self.min_evidence_weight = min_evidence_weight
        self._beliefs: dict[str, BeliefState] = {}

    def get_or_create_belief(
        self,
        market_id: str,
        prior_yes: float = 0.5,
    ) -> BeliefState:
        """Get existing belief or create new one with given prior.

        Args:
            market_id: Market identifier.
            prior_yes: Prior probability of YES (default 0.5 = uninformative).

        Returns:
            BeliefState for this market.
        """
        if market_id not in self._beliefs:
            prior_yes = max(0.001, min(0.999, prior_yes))
            log_odds = math.log(prior_yes / (1 - prior_yes))
            self._beliefs[market_id] = BeliefState(
                market_id=market_id,
                log_odds=log_odds,
                last_update=time.time(),
            )
        return self._beliefs[market_id]

    def update(
        self,
        market_id: str,
        evidence: Evidence,
    ) -> BeliefState:
        """Update belief for a market with new evidence.

        Applies Bayes' rule in log-odds space:
            log_odds_new = log_odds_old + weight * log(P(D|YES) / P(D|NO))

        Args:
            market_id: Market identifier.
            evidence: New evidence to incorporate.

        Returns:
            Updated BeliefState.
        """
        belief = self.get_or_create_belief(market_id)
        evidence.timestamp = evidence.timestamp or time.time()

        # Apply evidence decay based on age
        weight = evidence.weight
        if self.evidence_decay_hours > 0 and belief.last_update > 0:
            age_hours = (evidence.timestamp - belief.last_update) / 3600.0
            if age_hours > 0:
                # Exponential decay with half-life
                decay = math.exp(-0.693 * age_hours / self.evidence_decay_hours)
                weight *= max(self.min_evidence_weight, decay)

        # Bayesian update in log-odds space
        llr = evidence.log_likelihood_ratio
        belief.log_odds += weight * llr

        # Clamp to prevent extreme beliefs
        belief.log_odds = max(-self.max_log_odds, min(self.max_log_odds, belief.log_odds))

        belief.evidence_count += 1
        belief.last_update = evidence.timestamp

        # Maintain evidence history
        belief.evidence_history.append(evidence)
        if len(belief.evidence_history) > belief.max_history:
            belief.evidence_history = belief.evidence_history[-belief.max_history:]

        _log(
            "debug",
            "bayesian_update",
            market_id=market_id,
            source=evidence.source,
            llr=round(llr, 4),
            weight=round(weight, 4),
            log_odds=round(belief.log_odds, 4),
            p_yes=round(belief.probability_yes, 4),
            evidence_count=belief.evidence_count,
        )

        return belief

    def batch_update(
        self,
        market_id: str,
        evidences: list[Evidence],
    ) -> BeliefState:
        """Update belief with multiple evidence items at once.

        Args:
            market_id: Market identifier.
            evidences: List of evidence to incorporate sequentially.

        Returns:
            Updated BeliefState after all evidence processed.
        """
        belief = self.get_or_create_belief(market_id)
        for ev in evidences:
            belief = self.update(market_id, ev)
        return belief

    def expected_value(
        self,
        market_id: str,
        market_price: float,
    ) -> float:
        """Compute expected value of a position.

        EV = p_hat * (1-p) - (1-p_hat) * p = p_hat - p

        Where p_hat is our Bayesian estimate, p is market price.

        Args:
            market_id: Market identifier.
            market_price: Current market YES price (0-1).

        Returns:
            Expected value. Positive = buy YES is +EV.
        """
        belief = self._beliefs.get(market_id)
        if belief is None:
            return 0.0
        return belief.probability_yes - market_price

    def get_signal(
        self,
        market_id: str,
        market_price: float,
        min_edge: float = 0.05,
        fee_rate: float = 0.02,
    ) -> dict:
        """Generate a trading signal from current belief state.

        Args:
            market_id: Market identifier.
            market_price: Current market YES price.
            min_edge: Minimum edge after fees to signal a trade.
            fee_rate: Fee rate for edge calculation.

        Returns:
            Signal dict with direction, edge, probability, etc.
        """
        belief = self._beliefs.get(market_id)
        if belief is None:
            return {"direction": "hold", "edge": 0.0, "reason": "no_belief_state"}

        ev = self.expected_value(market_id, market_price)
        fee = market_price * (1 - market_price) * fee_rate
        net_edge = abs(ev) - fee

        if net_edge >= min_edge:
            direction = "buy_yes" if ev > 0 else "buy_no"
        else:
            direction = "hold"

        return {
            "direction": direction,
            "edge": net_edge if direction != "hold" else 0.0,
            "raw_ev": ev,
            "p_bayesian": belief.probability_yes,
            "log_odds": belief.log_odds,
            "evidence_count": belief.evidence_count,
            "fee": fee,
            "reason": f"bayesian_ev={ev:.4f}, edge={net_edge:.4f}",
        }

    def reset_belief(self, market_id: str) -> None:
        """Reset belief to uninformative prior."""
        if market_id in self._beliefs:
            del self._beliefs[market_id]

    def get_all_beliefs(self) -> dict[str, BeliefState]:
        """Return all current belief states."""
        return dict(self._beliefs)


# ---------------------------------------------------------------------------
# Evidence Factory — helpers to create Evidence from raw signals
# ---------------------------------------------------------------------------

def evidence_from_claude(
    probability: float,
    confidence: float = 0.6,
) -> Evidence:
    """Create evidence from Claude's probability estimate.

    Converts Claude's probability into a likelihood ratio.
    Higher confidence = stronger evidence weight.

    Args:
        probability: Claude's estimated P(YES), 0-1.
        confidence: Claude's confidence level (0-1).

    Returns:
        Evidence object.
    """
    p = max(0.01, min(0.99, probability))
    return Evidence(
        source="claude",
        likelihood_yes=p,
        likelihood_no=1 - p,
        weight=0.5 + 0.5 * confidence,  # Scale weight by confidence
        timestamp=time.time(),
        description=f"Claude estimate: {p:.2%} (confidence: {confidence:.1%})",
    )


def evidence_from_price_move(
    price_change: float,
    volume_ratio: float = 1.0,
) -> Evidence:
    """Create evidence from a significant price movement.

    Market price movements encode information from other traders.
    Weight by volume ratio (high volume = more informed).

    Args:
        price_change: Price change (positive = YES price went up).
        volume_ratio: Current volume / average volume (>1 = above average).

    Returns:
        Evidence object.
    """
    # Price move magnitude maps to likelihood ratio
    # A 5% move with normal volume is moderate evidence
    magnitude = abs(price_change)
    base_lr = 1.0 + magnitude * 5.0  # 5% move → LR of 1.25

    if price_change > 0:
        l_yes = base_lr
        l_no = 1.0
    else:
        l_yes = 1.0
        l_no = base_lr

    # Volume-weighted: high volume = more informative
    weight = min(1.0, 0.3 * math.sqrt(volume_ratio))

    return Evidence(
        source="price_action",
        likelihood_yes=l_yes,
        likelihood_no=l_no,
        weight=weight,
        timestamp=time.time(),
        description=f"Price move: {price_change:+.2%}, volume ratio: {volume_ratio:.1f}x",
    )


def evidence_from_news_sentiment(
    sentiment_score: float,
    relevance: float = 0.5,
) -> Evidence:
    """Create evidence from news sentiment analysis.

    Args:
        sentiment_score: Sentiment (-1 to +1, positive = bullish for YES).
        relevance: How relevant the news is to this market (0-1).

    Returns:
        Evidence object.
    """
    # Map sentiment to likelihood ratio
    # Strong positive sentiment → higher P(D|YES)
    score = max(-1, min(1, sentiment_score))

    if score >= 0:
        l_yes = 1.0 + score * 2.0
        l_no = 1.0
    else:
        l_yes = 1.0
        l_no = 1.0 + abs(score) * 2.0

    weight = 0.2 * relevance  # News is weak evidence by default

    return Evidence(
        source="news_sentiment",
        likelihood_yes=l_yes,
        likelihood_no=l_no,
        weight=weight,
        timestamp=time.time(),
        description=f"News sentiment: {score:+.2f}, relevance: {relevance:.2f}",
    )


def evidence_from_volume_spike(
    volume_ratio: float,
    price_direction: float,
) -> Evidence:
    """Create evidence from unusual volume activity.

    High volume + price direction = informed trading signal.

    Args:
        volume_ratio: Current volume / average volume.
        price_direction: Sign of concurrent price move (+1/-1).

    Returns:
        Evidence object.
    """
    if volume_ratio < 1.5:
        # Not a significant spike
        return Evidence(
            source="volume",
            likelihood_yes=1.0,
            likelihood_no=1.0,
            weight=0.0,
            description="Volume normal, no signal",
        )

    strength = math.log(volume_ratio)  # ln(2x) = 0.69, ln(5x) = 1.61

    if price_direction > 0:
        l_yes = 1.0 + strength
        l_no = 1.0
    else:
        l_yes = 1.0
        l_no = 1.0 + strength

    return Evidence(
        source="volume_spike",
        likelihood_yes=l_yes,
        likelihood_no=l_no,
        weight=min(0.5, 0.2 * strength),
        timestamp=time.time(),
        description=f"Volume spike: {volume_ratio:.1f}x, direction: {'YES' if price_direction > 0 else 'NO'}",
    )
