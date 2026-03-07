"""
LMSR Bayesian Engine — Real-time pricing inefficiency detector.

Third signal source for jj_live.py hybrid architecture.
Based on internal research paper QR-PM-2026-0041.

Math:
  - Cost function: C(q) = b * ln(sum(exp(qi/b)))
  - Price function (softmax): pi(q) = exp(qi/b) / sum(exp(qj/b))
  - Bayesian update in log-space: log P(H|D) = log P(H) + sum(log P(Dk|H)) - log Z
  - EV = p_hat - p_market
  - Kelly capped at 1/16 for fast markets (per research paper annotation)

Target cycle: 828ms avg, 1776ms p99.
"""

import time
import math
import logging
import asyncio
import requests
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List, Tuple
from collections import defaultdict

logger = logging.getLogger("lmsr_engine")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TRADES_API = "https://data-api.polymarket.com/trades"
GAMMA_API = "https://gamma-api.polymarket.com"

# Cycle timing targets (ms)
TARGET_CYCLE_MS = 828
P99_CYCLE_MS = 1776

# Kelly sizing
MAX_KELLY_FRACTION_FAST = 1 / 16  # NEVER full Kelly on 5-min markets
MAX_KELLY_FRACTION_SLOW = 0.25     # Quarter-Kelly for slow markets

# Inefficiency thresholds
DEFAULT_ENTRY_THRESHOLD = 0.05     # 5% divergence to enter
DEFAULT_EXIT_THRESHOLD = 0.02      # 2% divergence to exit (close signal)
MIN_TRADES_FOR_SIGNAL = 10         # Need enough trades to form posterior
TAKER_FEE_DEFAULT = 0.0            # Maker orders = zero fees

# Bayesian priors
DEFAULT_PRIOR_STRENGTH = 5.0       # Equivalent sample size of prior
LOG_LIKELIHOOD_CAP = 5.0           # Cap individual log-likelihoods for stability

# Liquidity estimation
DEFAULT_B = 1000.0                 # Default liquidity parameter
MIN_B = 10.0
MAX_B = 1_000_000.0


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class LMSRState:
    """Internal state for a single market being tracked."""
    market_id: str
    question: str
    n_outcomes: int = 2
    quantities: List[float] = field(default_factory=lambda: [0.0, 0.0])
    b: float = DEFAULT_B
    log_posterior: List[float] = field(default_factory=lambda: [0.0, 0.0])
    trades_processed: int = 0
    last_trade_timestamp: float = 0.0
    last_clob_price: float = 0.5
    created_at: float = field(default_factory=time.time)


@dataclass
class CycleMetrics:
    """Timing instrumentation for a single cycle."""
    ingestion_ms: float = 0.0
    posterior_ms: float = 0.0
    comparison_ms: float = 0.0
    total_ms: float = 0.0


# ---------------------------------------------------------------------------
# LMSR Math (numerically stable)
# ---------------------------------------------------------------------------

def _logsumexp(values: List[float]) -> float:
    """Numerically stable log-sum-exp."""
    if not values:
        return float('-inf')
    max_val = max(values)
    if max_val == float('-inf'):
        return float('-inf')
    return max_val + math.log(sum(math.exp(v - max_val) for v in values))


def lmsr_cost(quantities: List[float], b: float) -> float:
    """
    LMSR cost function: C(q) = b * ln(sum(exp(qi/b)))

    Uses logsumexp for numerical stability on large q vectors.
    """
    scaled = [q / b for q in quantities]
    return b * _logsumexp(scaled)


def lmsr_prices(quantities: List[float], b: float) -> List[float]:
    """
    LMSR price function (softmax): pi(q) = exp(qi/b) / sum(exp(qj/b))

    Returns probability vector for each outcome.
    The market IS a neural network classifier pricing beliefs.
    """
    scaled = [q / b for q in quantities]
    max_s = max(scaled)
    exps = [math.exp(s - max_s) for s in scaled]
    total = sum(exps)
    return [e / total for e in exps]


def lmsr_trade_cost(
    quantities: List[float], b: float, outcome_idx: int, delta: float
) -> float:
    """
    Cost to buy delta shares of outcome outcome_idx.
    Cost = C(q1,...,qi+delta,...,qn) - C(q1,...,qi,...,qn)
    """
    cost_before = lmsr_cost(quantities, b)
    new_quantities = list(quantities)
    new_quantities[outcome_idx] += delta
    cost_after = lmsr_cost(new_quantities, b)
    return cost_after - cost_before


def lmsr_max_loss(b: float, n: int = 2) -> float:
    """Maximum market maker loss: Lmax = b * ln(n)"""
    return b * math.log(n)


# ---------------------------------------------------------------------------
# Liquidity Parameter Estimation
# ---------------------------------------------------------------------------

def estimate_b_from_spread(
    bid: float, ask: float, n_outcomes: int = 2
) -> float:
    """
    Estimate liquidity parameter b from observed bid-ask spread.

    Tighter spread → larger b → more liquid market.
    For binary markets: spread ≈ 1/(2b) near p=0.5.
    """
    spread = ask - bid
    if spread <= 0 or spread >= 1.0:
        return DEFAULT_B

    # For binary LMSR near p=0.5: spread ≈ 1/(2b)
    # → b ≈ 1/(2*spread)
    b_est = 1.0 / (2.0 * spread)

    # Scale by outcome count
    b_est *= math.log(n_outcomes)

    return max(MIN_B, min(MAX_B, b_est))


def estimate_b_from_volume(daily_volume: float, n_outcomes: int = 2) -> float:
    """
    Estimate b from daily trading volume.
    Higher volume → more liquidity → larger b.
    """
    if daily_volume <= 0:
        return DEFAULT_B
    # Heuristic: b ≈ daily_volume / 10
    b_est = daily_volume / 10.0
    return max(MIN_B, min(MAX_B, b_est))


# ---------------------------------------------------------------------------
# Bayesian Posterior Updater (log-space)
# ---------------------------------------------------------------------------

class BayesianUpdater:
    """
    Sequential Bayesian updater operating in log-space.

    Prior: LMSR fair price at cycle start.
    Likelihood: each new trade updates posterior.
    log P(H|D) = log P(H) + sum(log P(Dk|H)) - log Z
    """

    def __init__(self, prior_probs: List[float], prior_strength: float = DEFAULT_PRIOR_STRENGTH):
        """
        Args:
            prior_probs: Initial probability vector (e.g., from LMSR prices)
            prior_strength: Equivalent sample size of prior (higher = more resistant to updates)
        """
        self.n_outcomes = len(prior_probs)
        self.prior_strength = prior_strength

        # Initialize log-posterior from prior
        self.log_posterior = []
        for p in prior_probs:
            p_clamped = max(1e-10, min(1 - 1e-10, p))
            self.log_posterior.append(math.log(p_clamped))

        self.n_updates = 0

    def update(self, outcome_idx: int, trade_size: float, price: float) -> List[float]:
        """
        Update posterior with a new trade observation.

        A trade on outcome_idx at price p with size s is evidence:
        - For outcome_idx: weight proportional to size * price
        - Against other outcomes: weight proportional to size * (1 - price)

        Returns updated probability vector.
        """
        if outcome_idx < 0 or outcome_idx >= self.n_outcomes:
            return self.get_posterior()

        # Trade size as evidence weight (normalized by prior strength)
        weight = min(trade_size, 100.0) / (self.prior_strength * 10.0)

        # Log-likelihood for each outcome
        price_clamped = max(0.01, min(0.99, price))

        for i in range(self.n_outcomes):
            if i == outcome_idx:
                # Trade supports this outcome
                ll = weight * math.log(price_clamped)
            else:
                # Trade is evidence against this outcome
                ll = weight * math.log(1.0 - price_clamped)

            # Cap log-likelihoods for stability
            ll = max(-LOG_LIKELIHOOD_CAP, min(LOG_LIKELIHOOD_CAP, ll))
            self.log_posterior[i] += ll

        self.n_updates += 1
        return self.get_posterior()

    def get_posterior(self) -> List[float]:
        """Get normalized posterior probabilities from log-space."""
        log_z = _logsumexp(self.log_posterior)
        probs = []
        for lp in self.log_posterior:
            probs.append(math.exp(lp - log_z))
        return probs

    def get_log_posterior(self) -> List[float]:
        """Get raw log-posterior (unnormalized)."""
        return list(self.log_posterior)


# ---------------------------------------------------------------------------
# Position Sizing
# ---------------------------------------------------------------------------

def compute_ev(p_hat: float, p_market: float) -> float:
    """Expected value: EV = p_hat - p_market"""
    return p_hat - p_market


def kelly_fraction(
    ev: float,
    p_market: float,
    fast_market: bool = True,
    taker_fee: float = 0.0,
) -> float:
    """
    Kelly criterion fraction for position sizing.

    f* = EV / (odds - 1), capped at 1/16 for fast markets.
    NEVER full Kelly on 5-min markets (per research paper annotation).
    """
    if ev <= 0:
        return 0.0

    # Net EV after fees
    net_ev = ev - taker_fee
    if net_ev <= 0:
        return 0.0

    # Decimal odds for a binary bet at price p
    # If buying YES at p, payout is 1/p, so odds = 1/p
    # odds - 1 = (1 - p) / p
    if p_market <= 0 or p_market >= 1:
        return 0.0

    odds_minus_1 = (1.0 - p_market) / p_market
    if odds_minus_1 <= 0:
        return 0.0

    f = net_ev / odds_minus_1

    # Cap based on market speed
    max_f = MAX_KELLY_FRACTION_FAST if fast_market else MAX_KELLY_FRACTION_SLOW
    return max(0.0, min(max_f, f))


# ---------------------------------------------------------------------------
# LMSR Engine (Main Class)
# ---------------------------------------------------------------------------

class LMSREngine:
    """
    Real-time LMSR pricing and Bayesian inefficiency detector.
    Third signal source for jj_live.py hybrid architecture.

    Cycle: poll trades → update Bayesian posterior → compare to LMSR fair price
           → generate signal if divergence exceeds threshold → size position.
    """

    def __init__(
        self,
        entry_threshold: float = DEFAULT_ENTRY_THRESHOLD,
        exit_threshold: float = DEFAULT_EXIT_THRESHOLD,
        prior_strength: float = DEFAULT_PRIOR_STRENGTH,
        poll_interval_sec: float = 1.0,
    ):
        self.entry_threshold = entry_threshold
        self.exit_threshold = exit_threshold
        self.prior_strength = prior_strength
        self.poll_interval_sec = poll_interval_sec

        # Market states: market_id → LMSRState
        self.markets: Dict[str, LMSRState] = {}
        # Bayesian updaters: market_id → BayesianUpdater
        self.updaters: Dict[str, BayesianUpdater] = {}
        # Cycle metrics
        self.metrics_history: List[CycleMetrics] = []
        self._max_metrics = 1000

        # Session for HTTP connection pooling
        self._session = requests.Session()

    def _get_or_create_state(
        self, market_id: str, question: str, clob_price: float, b: float = DEFAULT_B
    ) -> LMSRState:
        """Get or create tracking state for a market."""
        if market_id not in self.markets:
            state = LMSRState(
                market_id=market_id,
                question=question,
                b=b,
                last_clob_price=clob_price,
            )
            self.markets[market_id] = state

            # Initialize Bayesian updater with CLOB price as prior
            prior = [clob_price, 1.0 - clob_price]
            self.updaters[market_id] = BayesianUpdater(
                prior_probs=prior,
                prior_strength=self.prior_strength,
            )
        return self.markets[market_id]

    def fetch_recent_trades(
        self, market_id: Optional[str] = None, limit: int = 100
    ) -> List[dict]:
        """
        Fetch recent trades from Polymarket data API.
        Target: 120ms avg, 340ms p99.
        """
        params = {"limit": limit}
        if market_id:
            params["conditionId"] = market_id

        try:
            resp = self._session.get(TRADES_API, params=params, timeout=2.0)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.warning(f"Failed to fetch trades: {e}")
            return []

    def ingest_trades(self, state: LMSRState, trades: List[dict]) -> int:
        """
        Process new trades and update Bayesian posterior.
        Target: 15ms avg, 28ms p99.

        Returns number of new trades processed.
        """
        updater = self.updaters.get(state.market_id)
        if not updater:
            return 0

        new_count = 0
        for trade in trades:
            ts = trade.get("timestamp", 0)
            if isinstance(ts, str):
                try:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    ts = dt.timestamp()
                except (ValueError, TypeError):
                    ts = 0

            # Skip already-processed trades
            if ts <= state.last_trade_timestamp:
                continue

            # Extract trade data
            side = trade.get("side", "").upper()
            outcome_index = int(trade.get("outcomeIndex", 0))
            size = float(trade.get("size", 0))
            price = float(trade.get("price", 0.5))

            # Map (side, outcomeIndex) to effective outcome
            # BUY outcome_0 = evidence for outcome 0
            # SELL outcome_0 = evidence for outcome 1
            if side == "SELL":
                effective_outcome = 1 - outcome_index
            else:
                effective_outcome = outcome_index

            # Update quantities (track cumulative flow)
            if side == "BUY":
                state.quantities[outcome_index] += size
            else:
                state.quantities[outcome_index] -= size

            # Bayesian update
            updater.update(effective_outcome, size, price)

            state.last_trade_timestamp = ts
            state.trades_processed += 1
            new_count += 1

        return new_count

    def compute_signal(
        self, state: LMSRState, clob_mid: float
    ) -> Optional[dict]:
        """
        Compare LMSR/Bayesian fair price vs CLOB mid price.
        Target: 3ms avg, 8ms p99.

        Returns signal dict compatible with jj_live.py format, or None.
        """
        updater = self.updaters.get(state.market_id)
        if not updater:
            return None

        # Need minimum trades for a meaningful signal
        if state.trades_processed < MIN_TRADES_FOR_SIGNAL:
            return None

        # Get Bayesian posterior (our estimate)
        posterior = updater.get_posterior()
        p_hat_yes = posterior[0]  # Probability of outcome 0 (YES)

        # LMSR fair prices from quantity flow
        lmsr_fair = lmsr_prices(state.quantities, state.b)
        p_lmsr_yes = lmsr_fair[0]

        # Blend: 60% Bayesian posterior, 40% LMSR flow price
        p_blended = 0.6 * p_hat_yes + 0.4 * p_lmsr_yes

        # Divergence from CLOB
        divergence = p_blended - clob_mid
        abs_div = abs(divergence)

        # Update stored CLOB price
        state.last_clob_price = clob_mid

        if abs_div < self.entry_threshold:
            return None

        # Determine direction
        if divergence > 0:
            # Our estimate > market → market underpriced YES → buy YES
            direction = "buy_yes"
            edge = divergence
            estimated_prob = p_blended
        else:
            # Our estimate < market → market overpriced YES → buy NO
            direction = "buy_no"
            edge = -divergence
            estimated_prob = 1.0 - p_blended

        # Confidence based on evidence strength
        # More trades + larger divergence = higher confidence
        evidence_factor = min(1.0, state.trades_processed / 50.0)
        divergence_factor = min(1.0, abs_div / 0.20)
        confidence = 0.3 + 0.4 * evidence_factor + 0.3 * divergence_factor
        confidence = min(0.95, confidence)

        # Position sizing: 1/16 Kelly for LMSR (always treated as fast)
        f = kelly_fraction(
            ev=edge,
            p_market=clob_mid if direction == "buy_yes" else (1.0 - clob_mid),
            fast_market=True,
            taker_fee=TAKER_FEE_DEFAULT,
        )

        return {
            "market_id": state.market_id,
            "question": state.question,
            "direction": direction,
            "market_price": clob_mid,
            "estimated_prob": round(estimated_prob, 4),
            "edge": round(edge, 4),
            "confidence": round(confidence, 4),
            "reasoning": (
                f"LMSR Bayesian: posterior={p_hat_yes:.3f}, "
                f"lmsr_flow={p_lmsr_yes:.3f}, blended={p_blended:.3f}, "
                f"clob={clob_mid:.3f}, divergence={abs_div:.3f}, "
                f"trades={state.trades_processed}"
            ),
            "source": "lmsr",
            "taker_fee": TAKER_FEE_DEFAULT,
            "category": "any",
            "resolution_hours": None,
            "velocity_score": 0.0,
            "kelly_fraction": round(f, 6),
        }

    def get_signal(self, market: dict) -> Optional[dict]:
        """
        Single-market signal generation (synchronous).
        Called from jj_live.py confirmation layer.

        Args:
            market: dict with {id, question, outcomePrices, ...} from Gamma API

        Returns:
            Signal dict or None if no signal.
        """
        market_id = market.get("id") or market.get("condition_id", "")
        question = market.get("question", market.get("title", ""))

        # Extract CLOB mid price
        prices = market.get("outcomePrices", [])
        if isinstance(prices, str):
            try:
                import json as _json
                prices = _json.loads(prices)
            except Exception:
                prices = []
        if not prices:
            return None

        try:
            clob_mid = float(prices[0])
        except (IndexError, ValueError, TypeError):
            return None

        # Estimate liquidity parameter
        b = DEFAULT_B
        volume = market.get("volume", 0)
        if volume:
            try:
                b = estimate_b_from_volume(float(volume))
            except (ValueError, TypeError):
                pass

        # Get or create state
        state = self._get_or_create_state(market_id, question, clob_mid, b)

        # Fetch and ingest recent trades
        t0 = time.monotonic()
        trades = self.fetch_recent_trades(market_id=market_id, limit=100)
        t_ingest = time.monotonic()

        new = self.ingest_trades(state, trades)
        t_posterior = time.monotonic()

        # Compute signal
        signal = self.compute_signal(state, clob_mid)
        t_compare = time.monotonic()

        # Record metrics
        metrics = CycleMetrics(
            ingestion_ms=(t_ingest - t0) * 1000,
            posterior_ms=(t_posterior - t_ingest) * 1000,
            comparison_ms=(t_compare - t_posterior) * 1000,
            total_ms=(t_compare - t0) * 1000,
        )
        self.metrics_history.append(metrics)
        if len(self.metrics_history) > self._max_metrics:
            self.metrics_history = self.metrics_history[-self._max_metrics:]

        if signal and new > 0:
            logger.info(
                f"LMSR signal: {question[:60]} → {signal['direction']} "
                f"edge={signal['edge']:.3f} conf={signal['confidence']:.3f} "
                f"({metrics.total_ms:.0f}ms)"
            )

        return signal

    def get_signals(self, markets: List[dict]) -> List[dict]:
        """
        Batch signal generation across multiple markets.

        Args:
            markets: List of market dicts from Gamma API

        Returns:
            List of signal dicts (only markets with signals).
        """
        signals = []
        for market in markets:
            try:
                signal = self.get_signal(market)
                if signal:
                    signals.append(signal)
            except Exception as e:
                mid = market.get("id", "?")
                logger.warning(f"LMSR error for {mid}: {e}")
        return signals

    def get_timing_stats(self) -> dict:
        """Get avg and p99 latency stats."""
        if not self.metrics_history:
            return {"avg_ms": 0, "p99_ms": 0, "cycles": 0}

        totals = [m.total_ms for m in self.metrics_history]
        totals_sorted = sorted(totals)
        n = len(totals_sorted)

        avg = sum(totals) / n
        p99_idx = min(n - 1, int(n * 0.99))
        p99 = totals_sorted[p99_idx]

        ingestions = [m.ingestion_ms for m in self.metrics_history]
        posteriors = [m.posterior_ms for m in self.metrics_history]
        comparisons = [m.comparison_ms for m in self.metrics_history]

        return {
            "avg_ms": round(avg, 1),
            "p99_ms": round(p99, 1),
            "cycles": n,
            "breakdown": {
                "ingestion_avg_ms": round(sum(ingestions) / n, 1),
                "posterior_avg_ms": round(sum(posteriors) / n, 1),
                "comparison_avg_ms": round(sum(comparisons) / n, 1),
            },
        }

    def get_active_markets(self) -> List[str]:
        """List market IDs currently being tracked."""
        return list(self.markets.keys())

    def reset_market(self, market_id: str):
        """Reset state for a specific market."""
        self.markets.pop(market_id, None)
        self.updaters.pop(market_id, None)

    def cleanup_stale(self, max_age_seconds: float = 3600):
        """Remove markets that haven't had trades in max_age_seconds."""
        now = time.time()
        stale = [
            mid for mid, state in self.markets.items()
            if (now - state.created_at) > max_age_seconds
            and state.trades_processed == 0
        ]
        for mid in stale:
            self.reset_market(mid)
        if stale:
            logger.info(f"Cleaned up {len(stale)} stale LMSR markets")


# ---------------------------------------------------------------------------
# Async Cycle Controller
# ---------------------------------------------------------------------------

async def run_lmsr_cycle(
    engine: LMSREngine,
    markets: List[dict],
    on_signal=None,
) -> List[dict]:
    """
    Single async cycle of the LMSR engine.

    Target: 828ms average, 1776ms p99.
    Poll → update posterior → compare → signal.

    Args:
        engine: LMSREngine instance
        markets: List of market dicts from Gamma API
        on_signal: Optional callback for each signal

    Returns:
        List of signal dicts generated this cycle.
    """
    loop = asyncio.get_event_loop()

    # Run synchronous engine in thread pool to avoid blocking
    signals = await loop.run_in_executor(None, engine.get_signals, markets)

    if on_signal:
        for signal in signals:
            try:
                if asyncio.iscoroutinefunction(on_signal):
                    await on_signal(signal)
                else:
                    on_signal(signal)
            except Exception as e:
                logger.warning(f"Signal callback error: {e}")

    return signals


async def run_lmsr_loop(
    engine: LMSREngine,
    get_markets,
    on_signal=None,
    interval_sec: float = 1.0,
    max_cycles: int = 0,
):
    """
    Continuous LMSR monitoring loop.

    Args:
        engine: LMSREngine instance
        get_markets: Callable returning list of market dicts
        on_signal: Callback for each signal
        interval_sec: Seconds between cycles
        max_cycles: Stop after N cycles (0 = infinite)
    """
    cycle = 0
    while max_cycles == 0 or cycle < max_cycles:
        cycle += 1
        t0 = time.monotonic()

        try:
            markets = get_markets() if callable(get_markets) else get_markets
            signals = await run_lmsr_cycle(engine, markets, on_signal)

            if signals:
                logger.info(f"LMSR cycle {cycle}: {len(signals)} signals")

        except Exception as e:
            logger.error(f"LMSR cycle {cycle} error: {e}")

        # Maintain target cycle time
        elapsed = time.monotonic() - t0
        sleep_time = max(0, interval_sec - elapsed)
        if sleep_time > 0:
            await asyncio.sleep(sleep_time)

    stats = engine.get_timing_stats()
    logger.info(
        f"LMSR loop stopped after {cycle} cycles. "
        f"Avg: {stats['avg_ms']:.0f}ms, P99: {stats['p99_ms']:.0f}ms"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    """CLI for testing the LMSR engine standalone."""
    import argparse

    parser = argparse.ArgumentParser(description="LMSR Bayesian Engine")
    parser.add_argument(
        "mode",
        choices=["test_math", "scan", "monitor"],
        help="test_math: verify formulas, scan: one-shot scan, monitor: continuous loop",
    )
    parser.add_argument("--market-id", help="Specific market condition ID")
    parser.add_argument("--cycles", type=int, default=10, help="Max cycles for monitor mode")
    parser.add_argument("--threshold", type=float, default=0.05, help="Entry threshold")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    if args.mode == "test_math":
        print("=== LMSR Math Verification ===\n")

        # Binary market, equal quantities
        q = [0.0, 0.0]
        b = 100.0
        prices = lmsr_prices(q, b)
        print(f"Equal quantities q={q}, b={b}")
        print(f"  Prices: {prices}")
        print(f"  Cost: {lmsr_cost(q, b):.4f}")
        print(f"  Max loss: {lmsr_max_loss(b):.4f}")
        assert abs(prices[0] - 0.5) < 1e-6, "Equal q should give 50/50"

        # After buying 50 shares of YES
        q2 = [50.0, 0.0]
        prices2 = lmsr_prices(q2, b)
        trade_cost = lmsr_trade_cost([0.0, 0.0], b, 0, 50.0)
        print(f"\nAfter buying 50 YES shares:")
        print(f"  Prices: {prices2}")
        print(f"  Trade cost: {trade_cost:.4f}")
        assert prices2[0] > 0.5, "Buying YES should increase YES price"

        # Bayesian update
        print("\n=== Bayesian Updater ===\n")
        updater = BayesianUpdater([0.5, 0.5])
        print(f"Prior: {updater.get_posterior()}")
        updater.update(0, 10.0, 0.6)  # Trade on YES at 0.6
        post1 = updater.get_posterior()
        print(f"After YES trade (size=10, price=0.6): {post1}")
        assert post1[0] > 0.5, "YES trade should increase YES posterior"

        updater.update(1, 20.0, 0.7)  # Trade on NO at 0.7
        post2 = updater.get_posterior()
        print(f"After NO trade (size=20, price=0.7): {post2}")

        # Kelly sizing
        print("\n=== Kelly Sizing ===\n")
        ev = compute_ev(0.55, 0.45)
        f_fast = kelly_fraction(ev, 0.45, fast_market=True)
        f_slow = kelly_fraction(ev, 0.45, fast_market=False)
        print(f"EV = {ev:.4f}")
        print(f"Kelly (fast, 1/16 cap): {f_fast:.6f}")
        print(f"Kelly (slow, 1/4 cap): {f_slow:.6f}")
        assert f_fast <= MAX_KELLY_FRACTION_FAST + 1e-9
        assert f_slow <= MAX_KELLY_FRACTION_SLOW + 1e-9

        print("\nAll math checks passed.")

    elif args.mode == "scan":
        engine = LMSREngine(entry_threshold=args.threshold)

        if args.market_id:
            market = {"id": args.market_id, "question": "CLI test market"}
            signal = engine.get_signal(market)
            if signal:
                print(f"Signal: {signal}")
            else:
                stats = engine.get_timing_stats()
                print(f"No signal. Timing: {stats}")
        else:
            # Fetch some markets from Gamma API
            try:
                resp = requests.get(
                    f"{GAMMA_API}/markets",
                    params={"limit": 20, "active": True, "closed": False},
                    timeout=5,
                )
                resp.raise_for_status()
                markets = resp.json()
                signals = engine.get_signals(markets)
                print(f"Scanned {len(markets)} markets, {len(signals)} signals")
                for s in signals:
                    print(f"  {s['question'][:50]} → {s['direction']} edge={s['edge']:.3f}")
            except Exception as e:
                print(f"Error: {e}")

    elif args.mode == "monitor":
        engine = LMSREngine(entry_threshold=args.threshold)

        def get_markets():
            try:
                resp = requests.get(
                    f"{GAMMA_API}/markets",
                    params={"limit": 20, "active": True, "closed": False},
                    timeout=5,
                )
                resp.raise_for_status()
                return resp.json()
            except Exception:
                return []

        def on_signal(sig):
            print(f"SIGNAL: {sig['question'][:50]} → {sig['direction']} edge={sig['edge']:.3f}")

        asyncio.run(run_lmsr_loop(
            engine, get_markets, on_signal,
            interval_sec=1.0, max_cycles=args.cycles,
        ))


if __name__ == "__main__":
    main()
