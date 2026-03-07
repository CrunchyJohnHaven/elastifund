#!/usr/bin/env python3
"""
Semantic Lead-Lag Arbitrage Engine
===================================
Dispatch: Structural Alpha in Prediction Markets

Exploits cross-market information asymmetries via dual-stage filtering:
1. Statistical: Granger causality on log-odds transformed price series
2. Semantic: LLM verification of economic transmission mechanism

The statistical stage identifies candidate leader-follower pairs where
one market's price history predicts another. The semantic stage kills
spurious correlations by requiring a plausible causal narrative.

Expected impact (per dispatch):
  - Win rate: 51.4% → 54.5% (+3.1pp)
  - Avg loss magnitude: -46.5%
  - Total profit: +205%

The key insight: truncating false-positive correlations matters more
than finding true positives. The semantic filter is the alpha.

Author: JJ (autonomous)
Date: 2026-03-07
"""

import asyncio
import json
import logging
import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import numpy as np

logger = logging.getLogger("JJ.lead_lag")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class PairDirection(Enum):
    ALIGNED = 1       # Leader success → follower success
    INVERSE = -1      # Leader success → follower failure
    UNKNOWN = 0


@dataclass
class MarketTimeSeries:
    """Price time series for a single market, stored in log-odds space."""
    market_id: str
    question: str
    timestamps: list[float] = field(default_factory=list)
    prices: list[float] = field(default_factory=list)       # Raw prices (0-1)
    log_odds: list[float] = field(default_factory=list)      # Transformed

    def add_price(self, timestamp: float, price: float):
        """Add a price observation and compute log-odds transform."""
        # Clamp to avoid log(0) or log(inf)
        p = max(0.001, min(0.999, price))
        lo = math.log(p / (1.0 - p))

        self.timestamps.append(timestamp)
        self.prices.append(price)
        self.log_odds.append(lo)

    @property
    def n_obs(self) -> int:
        return len(self.prices)

    def get_recent(self, n: int = 100) -> tuple[list[float], list[float]]:
        """Get most recent n observations as (timestamps, log_odds)."""
        return self.timestamps[-n:], self.log_odds[-n:]


@dataclass
class LeadLagPair:
    """A candidate leader-follower pair with statistical + semantic scores."""
    leader_id: str
    follower_id: str
    leader_question: str
    follower_question: str

    # Statistical metrics
    granger_p_value: float = 1.0       # Lower = stronger causal signal
    granger_f_stat: float = 0.0
    optimal_lag: int = 1               # Best lag length (in observation periods)
    var_r_squared: float = 0.0         # VAR model fit

    # Semantic metrics
    semantic_valid: bool = False
    semantic_direction: PairDirection = PairDirection.UNKNOWN
    semantic_confidence: float = 0.0   # 0-1 LLM confidence in transmission mechanism
    transmission_mechanism: str = ""   # Human-readable explanation

    # Combined score
    combined_score: float = 0.0

    # Status
    active: bool = True
    created_at: float = field(default_factory=time.time)
    last_validated: float = 0.0

    def compute_combined_score(self):
        """Combined ranking: statistical strength * semantic confidence."""
        if not self.semantic_valid:
            self.combined_score = 0.0
            return

        # Statistical score: -log10(p_value) capped at 10
        stat_score = min(10.0, -math.log10(max(1e-10, self.granger_p_value)))

        # Semantic score: confidence from LLM
        sem_score = self.semantic_confidence

        # Combined: geometric mean favors pairs strong on both dimensions
        self.combined_score = (stat_score * sem_score) ** 0.5


@dataclass
class LeadLagSignal:
    """Trading signal from the lead-lag engine."""
    leader_id: str
    follower_id: str
    direction: PairDirection
    leader_price_change: float    # Recent leader price movement
    expected_follower_move: float # Expected follower movement (same units)
    confidence: float             # 0-1
    pair_score: float             # Combined pair quality score
    timestamp: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Granger Causality Calculator
# ---------------------------------------------------------------------------

class GrangerCausalityTest:
    """Bivariate Granger causality test using OLS-based VAR.

    Implements the F-test for whether lagged values of X improve
    prediction of Y beyond Y's own autoregressive history.

    Uses numpy-only implementation (no statsmodels dependency).
    """

    @staticmethod
    def _ols_residuals(X: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, float]:
        """OLS fit, returns (residuals, RSS)."""
        # X: (n, k), y: (n,)
        try:
            beta = np.linalg.lstsq(X, y, rcond=None)[0]
            residuals = y - X @ beta
            rss = float(np.sum(residuals ** 2))
            return residuals, rss
        except np.linalg.LinAlgError:
            return y, float(np.sum(y ** 2))

    @staticmethod
    def test(
        x: list[float],
        y: list[float],
        max_lag: int = 5,
    ) -> tuple[float, float, int]:
        """Run Granger causality test: does X Granger-cause Y?

        Args:
            x: Leader time series (log-odds)
            y: Follower time series (log-odds)
            max_lag: Maximum lag to test

        Returns:
            (best_p_value, best_f_stat, best_lag)
        """
        x = np.array(x, dtype=np.float64)
        y = np.array(y, dtype=np.float64)

        n = len(x)
        if n < max_lag + 10:
            return 1.0, 0.0, 1

        best_p = 1.0
        best_f = 0.0
        best_lag = 1

        for lag in range(1, max_lag + 1):
            # Build lagged matrices
            T = n - lag

            # Restricted model: Y_t ~ Y_{t-1} ... Y_{t-lag} + const
            Y = y[lag:]
            X_restricted = np.column_stack([
                y[lag - j - 1:n - j - 1] for j in range(lag)
            ] + [np.ones(T)])

            # Unrestricted model: Y_t ~ Y_{t-1}...Y_{t-lag} + X_{t-1}...X_{t-lag} + const
            X_unrestricted = np.column_stack([
                y[lag - j - 1:n - j - 1] for j in range(lag)
            ] + [
                x[lag - j - 1:n - j - 1] for j in range(lag)
            ] + [np.ones(T)])

            _, rss_r = GrangerCausalityTest._ols_residuals(X_restricted, Y)
            _, rss_u = GrangerCausalityTest._ols_residuals(X_unrestricted, Y)

            # F-test
            df1 = lag  # number of restrictions
            df2 = T - 2 * lag - 1  # residual df

            if df2 <= 0 or rss_u <= 0:
                continue

            f_stat = ((rss_r - rss_u) / df1) / (rss_u / df2)

            # Approximate p-value using F-distribution
            # Use scipy if available, else use approximation
            try:
                from scipy import stats as sp_stats
                p_value = 1.0 - sp_stats.f.cdf(f_stat, df1, df2)
            except ImportError:
                # Beta-function approximation of F CDF
                p_value = _f_pvalue_approx(f_stat, df1, df2)

            if p_value < best_p:
                best_p = p_value
                best_f = f_stat
                best_lag = lag

        return best_p, best_f, best_lag


def _f_pvalue_approx(f_stat: float, df1: int, df2: int) -> float:
    """Rough F-distribution p-value approximation when scipy unavailable.

    Uses the relationship between F and normal for large df.
    Good enough for screening (we validate with semantic layer anyway).
    """
    if f_stat <= 0:
        return 1.0

    # Approximation via chi-squared
    x = df1 * f_stat / (df1 * f_stat + df2)
    # Regularized incomplete beta function approximation
    # For large df2, F approaches chi-squared/df1
    # Quick approximation: standard normal tail
    z = (f_stat ** (1/3) * (1 - 2/(9*df2)) - (1 - 2/(9*df1))) / \
        ((2/(9*df1) + f_stat ** (2/3) * 2/(9*df2)) ** 0.5)

    # Standard normal CDF approximation
    if z > 6:
        return 1e-9
    if z < -6:
        return 1.0

    t = 1.0 / (1.0 + 0.2316419 * abs(z))
    d = 0.3989423 * math.exp(-z * z / 2)
    p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274))))

    if z > 0:
        return p
    return 1.0 - p


# ---------------------------------------------------------------------------
# Semantic Validator (LLM-based)
# ---------------------------------------------------------------------------

SEMANTIC_PROMPT = """You are a quantitative analyst evaluating whether two prediction market contracts have a genuine causal relationship.

LEADER MARKET: "{leader_question}"
FOLLOWER MARKET: "{follower_question}"

Statistical analysis shows that price changes in the LEADER market predict future price changes in the FOLLOWER market with a lag of {lag} observation periods (p-value: {p_value:.6f}).

Your task:
1. Identify the resolution criteria for both markets
2. Determine if real-world information validating the LEADER contract would mechanically and predictably alter the probability of the FOLLOWER contract
3. Describe the economic transmission mechanism in 1-2 sentences
4. Assess the direction: would LEADER success make FOLLOWER success MORE likely (+1) or LESS likely (-1)?

Respond in this exact JSON format:
{{
    "valid_causal_link": true/false,
    "direction": 1 or -1,
    "confidence": 0.0-1.0,
    "transmission_mechanism": "One sentence explanation of how information flows from leader to follower"
}}

IMPORTANT: Be skeptical. Many statistical correlations are spurious. Only validate if there is a clear, logical, mechanistic reason why information about the leader would change the follower's probability. Coincidental topic similarity is NOT sufficient."""


class SemanticValidator:
    """LLM-based semantic filter for lead-lag pair validation.

    Queries Claude to determine if a statistically significant lead-lag
    relationship has a plausible economic transmission mechanism.

    This is the core alpha: killing false positives reduces avg loss by 46.5%.
    """

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or _get_api_key()
        self._client = None

    def _get_client(self):
        """Lazy-init Anthropic client."""
        if self._client is None:
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=self._api_key)
            except ImportError:
                logger.error("anthropic library not installed")
                raise
        return self._client

    async def validate_pair(self, pair: LeadLagPair) -> LeadLagPair:
        """Validate a candidate pair using LLM semantic analysis.

        Modifies the pair in-place and returns it.
        """
        prompt = SEMANTIC_PROMPT.format(
            leader_question=pair.leader_question,
            follower_question=pair.follower_question,
            lag=pair.optimal_lag,
            p_value=pair.granger_p_value,
        )

        try:
            client = self._get_client()
            # Run sync API call in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(None, lambda: client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            ))

            # Parse response
            text = response.content[0].text.strip()

            # Extract JSON from response
            json_start = text.find("{")
            json_end = text.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                result = json.loads(text[json_start:json_end])

                pair.semantic_valid = bool(result.get("valid_causal_link", False))
                direction = int(result.get("direction", 0))
                pair.semantic_direction = PairDirection(direction) if direction in (1, -1) else PairDirection.UNKNOWN
                pair.semantic_confidence = float(result.get("confidence", 0.0))
                pair.transmission_mechanism = str(result.get("transmission_mechanism", ""))
                pair.last_validated = time.time()

                logger.info(
                    f"Semantic validation: {pair.leader_question[:40]}... → "
                    f"{pair.follower_question[:40]}... | "
                    f"valid={pair.semantic_valid} conf={pair.semantic_confidence:.2f} "
                    f"dir={pair.semantic_direction.name}"
                )
            else:
                logger.warning(f"Could not parse LLM response for pair validation")
                pair.semantic_valid = False

        except Exception as e:
            logger.error(f"Semantic validation failed: {e}")
            pair.semantic_valid = False

        pair.compute_combined_score()
        return pair


def _get_api_key() -> str:
    """Get Anthropic API key from environment."""
    import os
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        logger.warning("ANTHROPIC_API_KEY not set — semantic validation disabled")
    return key


# ---------------------------------------------------------------------------
# Lead-Lag Engine (main orchestrator)
# ---------------------------------------------------------------------------

class LeadLagEngine:
    """Orchestrates the full semantic lead-lag arbitrage pipeline.

    Pipeline:
    1. Collect price history for all tracked markets
    2. Run pairwise Granger causality tests (O(n^2) — capped at top N markets)
    3. Filter by statistical significance (p < 0.05)
    4. Send top K candidates to semantic validator
    5. Build ranked portfolio of validated pairs
    6. Generate trading signals when leader moves and follower hasn't caught up

    Usage:
        engine = LeadLagEngine()

        # Feed price data continuously
        engine.update_price("market_a", timestamp, 0.65)
        engine.update_price("market_b", timestamp, 0.40)

        # Periodically scan for pairs (every 5-10 min)
        pairs = await engine.scan_for_pairs()

        # Check for actionable signals
        signals = engine.get_signals()
    """

    # Configuration
    MIN_OBSERVATIONS = 20       # Minimum price history for Granger test
    MAX_MARKETS_SCAN = 50       # Cap on markets to test (O(n^2) constraint)
    MAX_LAG = 5                 # Maximum lag periods for Granger test
    STAT_THRESHOLD = 0.05       # P-value threshold for statistical significance
    TOP_K_SEMANTIC = 10         # Max candidates sent to LLM for validation
    SIGNAL_THRESHOLD = 0.03     # Min leader move to generate signal (3% in log-odds)
    PAIR_EXPIRY = 3600.0        # Re-validate pairs after 1 hour

    def __init__(self):
        self._series: dict[str, MarketTimeSeries] = {}
        self._pairs: list[LeadLagPair] = []
        self._validator = SemanticValidator()
        self._last_scan: float = 0.0

    def update_price(
        self, market_id: str, timestamp: float, price: float,
        question: str = "",
    ):
        """Record a new price observation for a market."""
        if market_id not in self._series:
            self._series[market_id] = MarketTimeSeries(
                market_id=market_id,
                question=question,
            )

        self._series[market_id].add_price(timestamp, price)

        # Update question if provided
        if question and not self._series[market_id].question:
            self._series[market_id].question = question

    async def scan_for_pairs(
        self,
        market_ids: Optional[list[str]] = None,
    ) -> list[LeadLagPair]:
        """Run the full lead-lag scan pipeline.

        1. Select markets with sufficient history
        2. Run pairwise Granger causality
        3. Filter statistically significant pairs
        4. Validate top-K with LLM semantic filter
        5. Return ranked, validated pairs

        Returns:
            List of validated LeadLagPair objects, ranked by combined score.
        """
        self._last_scan = time.time()

        # Step 1: Select markets with enough data
        candidates = []
        for mid, series in self._series.items():
            if market_ids and mid not in market_ids:
                continue
            if series.n_obs >= self.MIN_OBSERVATIONS:
                candidates.append(mid)

        candidates = candidates[:self.MAX_MARKETS_SCAN]

        if len(candidates) < 2:
            logger.info(f"Lead-lag scan: only {len(candidates)} markets with sufficient data, need 2+")
            return []

        logger.info(f"Lead-lag scan: testing {len(candidates)} markets ({len(candidates) * (len(candidates)-1)} pairs)")

        # Step 2: Pairwise Granger causality
        stat_pairs = []
        granger = GrangerCausalityTest()

        for i, leader_id in enumerate(candidates):
            for j, follower_id in enumerate(candidates):
                if i == j:
                    continue

                leader = self._series[leader_id]
                follower = self._series[follower_id]

                # Align time series (use last N common observations)
                n = min(leader.n_obs, follower.n_obs, 100)
                x = leader.log_odds[-n:]
                y = follower.log_odds[-n:]

                p_value, f_stat, best_lag = granger.test(x, y, max_lag=self.MAX_LAG)

                if p_value < self.STAT_THRESHOLD:
                    pair = LeadLagPair(
                        leader_id=leader_id,
                        follower_id=follower_id,
                        leader_question=leader.question,
                        follower_question=follower.question,
                        granger_p_value=p_value,
                        granger_f_stat=f_stat,
                        optimal_lag=best_lag,
                    )
                    stat_pairs.append(pair)

        logger.info(f"Lead-lag scan: {len(stat_pairs)} statistically significant pairs (p < {self.STAT_THRESHOLD})")

        if not stat_pairs:
            return []

        # Step 3: Sort by statistical strength, take top K
        stat_pairs.sort(key=lambda p: p.granger_p_value)
        top_candidates = stat_pairs[:self.TOP_K_SEMANTIC]

        # Step 4: Semantic validation
        validated = []
        for pair in top_candidates:
            try:
                await self._validator.validate_pair(pair)
                if pair.semantic_valid and pair.combined_score > 0:
                    validated.append(pair)
                    logger.info(
                        f"VALIDATED: {pair.leader_question[:30]}... → "
                        f"{pair.follower_question[:30]}... "
                        f"score={pair.combined_score:.3f}"
                    )
                else:
                    logger.info(
                        f"REJECTED (semantic): {pair.leader_question[:30]}... → "
                        f"{pair.follower_question[:30]}..."
                    )
            except Exception as e:
                logger.error(f"Validation error: {e}")
                continue

        # Step 5: Rank by combined score
        validated.sort(key=lambda p: -p.combined_score)

        self._pairs = validated
        logger.info(f"Lead-lag scan complete: {len(validated)} validated pairs")

        return validated

    def get_signals(self) -> list[LeadLagSignal]:
        """Check validated pairs for actionable trading signals.

        A signal fires when:
        1. The leader has moved significantly (> SIGNAL_THRESHOLD in log-odds)
        2. The follower hasn't moved proportionally yet
        3. The pair is still valid (not expired)
        """
        signals = []
        now = time.time()

        for pair in self._pairs:
            if not pair.active:
                continue

            # Check expiry
            if now - pair.last_validated > self.PAIR_EXPIRY:
                logger.info(f"Pair expired: {pair.leader_id[:12]}... → {pair.follower_id[:12]}...")
                pair.active = False
                continue

            leader = self._series.get(pair.leader_id)
            follower = self._series.get(pair.follower_id)

            if not leader or not follower:
                continue
            if leader.n_obs < pair.optimal_lag + 2:
                continue

            # Check leader movement over the optimal lag window
            lag = pair.optimal_lag
            if leader.n_obs < lag + 1 or follower.n_obs < 2:
                continue

            leader_move = leader.log_odds[-1] - leader.log_odds[-1 - lag]
            follower_recent = follower.log_odds[-1] - follower.log_odds[-2] if follower.n_obs > 1 else 0.0

            # Direction-adjusted expected move
            direction_mult = pair.semantic_direction.value if pair.semantic_direction != PairDirection.UNKNOWN else 1
            expected_follower = leader_move * direction_mult

            # Signal fires if leader moved enough and follower hasn't caught up
            if abs(leader_move) > self.SIGNAL_THRESHOLD:
                # Check if follower has already moved in expected direction
                follower_gap = expected_follower - follower_recent

                if abs(follower_gap) > self.SIGNAL_THRESHOLD * 0.5:
                    signal = LeadLagSignal(
                        leader_id=pair.leader_id,
                        follower_id=pair.follower_id,
                        direction=pair.semantic_direction,
                        leader_price_change=leader_move,
                        expected_follower_move=expected_follower,
                        confidence=pair.combined_score * min(1.0, abs(leader_move) / self.SIGNAL_THRESHOLD),
                        pair_score=pair.combined_score,
                    )
                    signals.append(signal)

        return signals

    def get_active_pairs(self) -> list[LeadLagPair]:
        """Get currently active, validated pairs."""
        return [p for p in self._pairs if p.active]

    def get_status(self) -> dict:
        """Engine status for logging/monitoring."""
        return {
            "markets_tracked": len(self._series),
            "active_pairs": len(self.get_active_pairs()),
            "total_pairs_tested": len(self._pairs),
            "last_scan": self._last_scan,
            "series_lengths": {
                mid[:12]: s.n_obs for mid, s in self._series.items()
            },
        }
