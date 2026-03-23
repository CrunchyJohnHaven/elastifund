"""Kalshi Longshot Fade Strategy — systematic NO basket for low-probability YES contracts.

Theory:
    Kalshi YES contracts priced 1-5 cents represent markets where the crowd assigns
    1-5% probability. Longshots are systematically overpriced in prediction markets
    (favorite-longshot bias). Buying NO (= selling YES) at 95-99 cents has a strong
    structural edge IF fees don't consume it.

    The critical wrinkle: Kalshi rounds fees UP to the nearest cent. For a 2-cent
    NO contract, the taker fee at 7% is 0.14 cents → rounds up to 1 cent. That is
    a 50% fee drag on a 2-cent position. Fee rounding destroys edge at very low prices.

    This strategy gates every candidate on fee_drag < max_fee_drag_pct before trading.

Kill discipline:
    After 30 settled trades, check:
    - Win rate < 0.88 (losing money if YES ever hits)
    - Profit factor < 1.0 (net EV negative)
    Strategy kills itself and logs a KILL record.

March 2026 — Elastifund / JJ
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from .base import BacktestResult, Signal

logger = logging.getLogger("JJ.kalshi_longshot_fade")

# ---------------------------------------------------------------------------
# Subjective rule markers — markets with these in title/rules are REJECTED
# because settlement is discretionary and the NO buyer can lose on a coin flip.
# ---------------------------------------------------------------------------
_SUBJECTIVE_MARKERS: tuple[str, ...] = (
    "best",
    "biggest",
    "better than",
    "most",
    "favorite",
    "popular",
    "impact",
    "significant",
    "substantial",
    "major",
    "notable",
    "important",
    "likely",
    "expected to",
    "projected",
    "sentiment",
    "approval rating",
    "opinion",
    "predict",
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class LongshotFadeConfig:
    """All tunable parameters for the Kalshi Longshot Fade strategy."""

    # Price gate: YES must be in this range (inclusive, in dollars, not cents)
    min_yes_price: float = 0.01
    max_yes_price: float = 0.05

    # Fee multipliers (Kalshi schedule as of March 2026)
    # Taker: 7% of trade value; Maker: 1.75% of trade value
    taker_fee_multiplier: float = 0.07
    maker_fee_multiplier: float = 0.0175

    # Maximum acceptable fee as a fraction of NO price paid
    # e.g. 0.20 means fee cannot exceed 20% of position cost
    max_fee_drag_pct: float = 0.20

    # Kelly sizing — quarter-Kelly conservative default
    kelly_fraction: float = 0.25

    # Position size limits
    max_position_usd: float = 10.0
    min_position_usd: float = 1.0  # Minimum size for bootstrap data collection
    max_open_positions: int = 10

    # Basket diversification: no more than this many positions per category
    max_per_category: int = 3

    # Time to resolution: reject markets closing in less than min_hours
    # or more than max_days days (stale markets with low liquidity)
    min_hours_to_resolution: float = 1.0
    max_days_to_resolution: float = 30.0

    # Kill conditions (checked after min_settled trades)
    min_settled_for_kill_check: int = 30
    kill_win_rate_threshold: float = 0.88
    kill_profit_factor_threshold: float = 1.0

    # Beta prior for posterior lower bound computation
    prior_alpha: float = 2.0  # Slight prior toward YES losing (realistic)
    prior_beta: float = 1.0
    credible_level: float = 0.05  # Lower 5th percentile of Beta posterior


# ---------------------------------------------------------------------------
# Market candidate
# ---------------------------------------------------------------------------


@dataclass
class LongshotCandidate:
    """A Kalshi market that has passed all gates and is ready to trade."""

    condition_id: str
    title: str
    category: str
    yes_price: float  # in dollars, e.g. 0.03
    no_price: float   # = 1.0 - yes_price before fees
    taker_fee: float  # in dollars per contract
    maker_fee: float  # in dollars per contract
    fee_drag_pct: float  # taker_fee / no_price
    breakeven_win_rate: float  # minimum WR for NO buyer to profit
    p_lower: float  # Beta posterior lower bound on P(YES fails)
    kelly_fraction_raw: float  # raw Kelly before scaling
    kelly_fraction_sized: float  # after multiplying by config.kelly_fraction
    suggested_position_usd: float
    hours_to_resolution: float
    rule_type: str  # "objective" or "subjective"
    gate_failures: list[str] = field(default_factory=list)
    score: float = 0.0  # Ranking score (higher = better)


# ---------------------------------------------------------------------------
# Fee computation (Kalshi-specific with mandatory ceiling rounding)
# ---------------------------------------------------------------------------


def compute_kalshi_fee(contracts: float, price: float, is_maker: bool = False) -> float:
    """
    Compute Kalshi fee for a position with MANDATORY ceiling rounding.

    Kalshi rounds fees UP to the nearest cent per their fee schedule.
    This is the critical implementation detail: raw_fee * 100 rounded UP.

    Args:
        contracts: Number of contracts (1 contract = $1 max payout)
        price: Price per contract in dollars (e.g. 0.03 for 3 cents YES)
        is_maker: If True, use maker rate (1.75%); else taker rate (7%)

    Returns:
        Fee in dollars, rounded UP to nearest cent.

    Example:
        compute_kalshi_fee(1, 0.02, is_maker=False)
        raw = 1 * 0.02 * 0.07 = 0.0014
        rounded up = ceil(0.0014 * 100) / 100 = ceil(0.14) / 100 = 1 / 100 = 0.01
        >>> 0.01  (50% fee drag on a 2-cent position!)
    """
    if contracts <= 0 or price <= 0:
        return 0.0

    rate = 0.0175 if is_maker else 0.07
    raw_fee = contracts * price * rate

    # Ceiling rounding to nearest cent — this is NOT optional, it is Kalshi's actual behavior
    fee_cents = math.ceil(raw_fee * 100)
    return fee_cents / 100.0


# ---------------------------------------------------------------------------
# Breakeven win rate for NO buyer
# ---------------------------------------------------------------------------


def compute_breakeven_win_rate(no_price: float, fee: float) -> float:
    """
    Minimum fraction of NO contracts that must resolve YES=NO (i.e., event does NOT happen)
    for the strategy to break even after fees.

    NO buyer pays: no_price + fee per contract
    NO buyer receives: $1.00 per contract when YES resolves 0

    Breakeven: WR * 1.00 = no_price + fee
    WR_breakeven = no_price + fee

    If no_price = 0.97, fee = 0.01 → WR_be = 0.98 (need 98% of positions to win).

    Args:
        no_price: Cost of NO contract in dollars (e.g. 0.97)
        fee: Fee per contract in dollars

    Returns:
        Breakeven win rate as a fraction (0-1).
    """
    total_cost = no_price + fee
    if total_cost <= 0:
        return 1.0
    return min(1.0, total_cost)


# ---------------------------------------------------------------------------
# Beta posterior lower bound (pure Python, no scipy)
# ---------------------------------------------------------------------------


def compute_posterior_lower_bound(
    wins: int,
    losses: int,
    alpha: float = 2.0,
    beta: float = 1.0,
    credible: float = 0.05,
) -> float:
    """
    Compute the lower credible bound on P(NO wins) using a Beta posterior.

    Prior: Beta(alpha, beta) — default (2, 1) slightly favors NO winning.
    Posterior: Beta(alpha + wins, beta + losses)
    Returns: q_{credible} of the posterior (e.g., 5th percentile).

    This gives a CONSERVATIVE estimate of P(YES=0) — we only trade when
    even the pessimistic view clears the fee hurdle.

    Implementation uses bisection on the regularized incomplete beta,
    borrowing the implementation from bot/bayesian_promoter.py.

    Args:
        wins: Observed NO wins (YES resolved 0)
        losses: Observed NO losses (YES resolved 1)
        alpha: Beta prior alpha (pseudo-wins)
        beta: Beta prior beta (pseudo-losses)
        credible: Quantile level (0.05 = 5th percentile = conservative lower bound)

    Returns:
        p_lower in [0, 1]
    """
    a = alpha + wins
    b = beta + losses

    if a <= 0 or b <= 0:
        return 0.0

    # Bisection on the regularized incomplete beta I_x(a, b) = credible
    # I_x(a, b) = P(X <= x) where X ~ Beta(a, b)
    # We want x such that I_x(a, b) = credible

    lo, hi = 0.0, 1.0
    for _ in range(100):  # 100 iterations → precision ~ 2^-100
        mid = (lo + hi) / 2.0
        if mid <= 0:
            lo = 1e-15
            continue
        if mid >= 1:
            hi = 1.0 - 1e-15
            continue
        cdf_mid = _regularized_incomplete_beta(mid, a, b)
        if cdf_mid < credible:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-10:
            break

    return (lo + hi) / 2.0


def _regularized_incomplete_beta(x: float, a: float, b: float) -> float:
    """
    I_x(a, b) — regularized incomplete beta function (standard CDF of Beta(a,b)).

    Uses the correct Numerical Recipes (Press et al.) modified Lentz algorithm
    with the proper initialization term (qap = a+1 in the first denominator).
    Symmetry reflection for numerical stability when x > (a+1)/(a+b+2).

    Verified correct for Beta(1,1), Beta(2,1), Beta(1,2), Beta(3,3).
    """
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0

    # Symmetry for numerical stability
    if x > (a + 1.0) / (a + b + 2.0):
        return 1.0 - _regularized_incomplete_beta(1.0 - x, b, a)

    ln_prefix = (
        a * math.log(x)
        + b * math.log(1.0 - x)
        - math.log(a)
        - (math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b))
    )

    cf = _beta_cf(x, a, b)
    return math.exp(ln_prefix) * cf


def _beta_cf(x: float, a: float, b: float, max_iter: int = 200, tol: float = 1e-12) -> float:
    """
    Continued fraction for the incomplete beta function.

    Correct NR (Press et al.) modified Lentz implementation. The key difference
    from naive Lentz: the first denominator term uses qap = a+1, not 1.0, which
    accounts for the leading term of the CF series.
    """
    tiny = 1e-30
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0

    # Initialize with the first term: 1 - (a+b)*x/(a+1)
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d

    for m in range(1, max_iter + 1):
        m2 = 2 * m
        # Even step
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c

        # Odd step
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta

        if abs(delta - 1.0) < tol:
            return h

    return h


# ---------------------------------------------------------------------------
# Kelly sizing
# ---------------------------------------------------------------------------


def compute_robust_kelly(p_lower: float, no_price: float, fee: float) -> float:
    """
    Kelly fraction using the CONSERVATIVE (lower bound) probability.

    Kelly for buying NO:
        b = (1.0 - no_price - fee) / (no_price + fee)  # net odds on a win
        f* = (p * b - (1 - p)) / b

    Using p_lower instead of p_hat makes this "robust Kelly" — sizes
    as if probability is at the pessimistic credible bound.

    Returns:
        Raw Kelly fraction in [0, 1], or 0.0 if no positive edge.
    """
    total_cost = no_price + fee
    if total_cost <= 0 or total_cost >= 1.0:
        return 0.0

    net_win = 1.0 - total_cost  # dollar profit per contract if YES fails
    if net_win <= 0:
        return 0.0

    # Net odds: b = net_win / total_cost
    b = net_win / total_cost
    p = max(0.0, min(1.0, p_lower))

    # Kelly formula: f* = (p*b - (1-p)) / b
    numerator = p * b - (1.0 - p)
    if numerator <= 0:
        return 0.0

    return min(1.0, numerator / b)


# ---------------------------------------------------------------------------
# Main strategy class
# ---------------------------------------------------------------------------


class KalshiLongshotFadeStrategy:
    """
    Systematic NO basket on Kalshi contracts where YES is priced 1-5 cents.

    Structural edge: longshot bias means these contracts are consistently
    overpriced relative to true probability. Buying NO captures the
    misprice — subject to fee viability.

    Gates (all must pass):
        1. price_range: YES in [min_yes_price, max_yes_price]
        2. rule_quality: no subjective settlement language
        3. time_to_resolution: within [min_hours, max_days]
        4. fee_viability: taker fee drag < max_fee_drag_pct
        5. basket_limits: category concentration cap not breached

    Kill conditions (checked post-30 settled trades):
        - Win rate < 0.88 (YES is hitting more than expected)
        - Profit factor < 1.0 (net negative EV)
    """

    name: str = "Kalshi Longshot Fade (NO Basket)"
    description: str = (
        "Systematic NO basket for Kalshi YES contracts priced 1-5 cents. "
        "Exploits longshot bias with fee viability gating and robust Kelly sizing."
    )

    def __init__(self, config: Optional[LongshotFadeConfig] = None):
        self.config = config or LongshotFadeConfig()
        self._settled_trades: list[dict[str, Any]] = []
        self._open_positions: dict[str, LongshotCandidate] = {}  # condition_id → candidate
        self._category_counts: dict[str, int] = {}
        self._killed: bool = False
        self._kill_reason: str = ""
        logger.info(
            "KalshiLongshotFadeStrategy initialized: yes_range=[%.2f, %.2f] "
            "max_fee_drag=%.0f%% kelly=%.2f max_pos=$%.2f",
            self.config.min_yes_price,
            self.config.max_yes_price,
            self.config.max_fee_drag_pct * 100,
            self.config.kelly_fraction,
            self.config.max_position_usd,
        )

    # ------------------------------------------------------------------
    # Public API: Strategy protocol
    # ------------------------------------------------------------------

    def generate_signals(
        self,
        market_data: list[dict[str, Any]],
        price_data: list[dict[str, Any]],  # unused: we use market_data prices
        trade_data: list[dict[str, Any]],  # unused: no flow signal needed
        features: list[dict[str, Any]],    # unused: pure price + rule gate
    ) -> list[Signal]:
        """
        Scan market_data for longshot candidates and emit NO signals.

        Each market dict must have at minimum:
            condition_id: str
            title: str
            category: str
            yes_price: float (dollars)
            closes_at: float (Unix timestamp) or hours_to_close: float

        Returns list of Signal objects ordered by score descending.
        """
        if self._killed:
            logger.warning("Strategy killed (%s), returning no signals.", self._kill_reason)
            return []

        if self.check_kill_conditions():
            return []

        candidates = self.scan_candidates(market_data)
        signals = []

        for candidate in candidates:
            # Skip if already in open positions
            if candidate.condition_id in self._open_positions:
                continue

            # Check global position limit
            if len(self._open_positions) >= self.config.max_open_positions:
                logger.debug(
                    "Position limit reached (%d/%d), skipping %s",
                    len(self._open_positions),
                    self.config.max_open_positions,
                    candidate.condition_id,
                )
                break

            # Compute position size in dollars.
            # Use minimum position during bootstrap (no settled data) so the
            # strategy can collect data even before the posterior has warmed up.
            is_bootstrap = len(self._settled_trades) < self.config.min_settled_for_kill_check
            if candidate.suggested_position_usd > 0:
                position_usd = min(candidate.suggested_position_usd, self.config.max_position_usd)
            elif is_bootstrap:
                position_usd = self.config.min_position_usd
            else:
                continue

            edge = candidate.p_lower - candidate.breakeven_win_rate
            confidence = max(0.0, min(1.0, candidate.p_lower))

            signal = Signal(
                strategy=self.name,
                condition_id=candidate.condition_id,
                timestamp_ts=int(time.time()),
                side="NO",
                entry_price=candidate.no_price,
                confidence=confidence,
                edge_estimate=edge,
                metadata={
                    "yes_price": candidate.yes_price,
                    "taker_fee": candidate.taker_fee,
                    "fee_drag_pct": round(candidate.fee_drag_pct, 4),
                    "breakeven_win_rate": round(candidate.breakeven_win_rate, 4),
                    "p_lower": round(candidate.p_lower, 4),
                    "kelly_raw": round(candidate.kelly_fraction_raw, 4),
                    "kelly_sized": round(candidate.kelly_fraction_sized, 4),
                    "position_usd": round(position_usd, 2),
                    "category": candidate.category,
                    "rule_type": candidate.rule_type,
                    "hours_to_resolution": round(candidate.hours_to_resolution, 1),
                    "score": round(candidate.score, 4),
                },
            )
            signals.append(signal)

            # Track open position
            self._open_positions[candidate.condition_id] = candidate
            self._category_counts[candidate.category] = (
                self._category_counts.get(candidate.category, 0) + 1
            )

        logger.info(
            "generate_signals: %d candidates → %d signals emitted",
            len(candidates),
            len(signals),
        )
        return signals

    def backtest(
        self,
        signals: list[Signal],
        resolutions: dict[str, str],
        backtester: Any,
    ) -> BacktestResult:
        """
        Delegate scoring to the backtesting engine.

        resolutions: {condition_id: "YES" | "NO"} — resolved outcome.
        A NO signal wins when resolution == "NO" (YES event did not happen).
        """
        return backtester.score(
            signals=signals,
            resolutions=resolutions,
            strategy_name=self.name,
        )

    # ------------------------------------------------------------------
    # Core scanning logic
    # ------------------------------------------------------------------

    def scan_candidates(self, markets: list[dict[str, Any]]) -> list[LongshotCandidate]:
        """
        Apply all gates to market list, return ranked LongshotCandidate objects.

        Markets that fail any gate are excluded. Remaining candidates are
        sorted by score descending (highest edge-to-fee ratio first).

        Args:
            markets: List of market dicts from Kalshi API

        Returns:
            Sorted list of LongshotCandidate objects passing all gates.
        """
        candidates: list[LongshotCandidate] = []
        rejected_counts: dict[str, int] = {}

        for market in markets:
            try:
                candidate = self._evaluate_market(market)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Error evaluating market %s: %s",
                    market.get("condition_id", "unknown"),
                    exc,
                )
                continue

            if candidate is None:
                continue

            if candidate.gate_failures:
                for gate in candidate.gate_failures:
                    rejected_counts[gate] = rejected_counts.get(gate, 0) + 1
                continue

            candidates.append(candidate)

        # Apply basket concentration limits (category cap)
        # Reset category tracking for this scan (we track live positions separately)
        scan_category_counts: dict[str, int] = dict(self._category_counts)
        final_candidates: list[LongshotCandidate] = []

        # Sort by score before applying basket limits
        candidates.sort(key=lambda c: c.score, reverse=True)

        for candidate in candidates:
            cat_count = scan_category_counts.get(candidate.category, 0)
            if cat_count >= self.config.max_per_category:
                candidate.gate_failures.append("basket_limit_category")
                rejected_counts["basket_limit_category"] = (
                    rejected_counts.get("basket_limit_category", 0) + 1
                )
                continue
            scan_category_counts[candidate.category] = cat_count + 1
            final_candidates.append(candidate)

        logger.info(
            "scan_candidates: %d markets → %d passed | rejections: %s",
            len(markets),
            len(final_candidates),
            dict(sorted(rejected_counts.items(), key=lambda kv: -kv[1])),
        )
        return final_candidates

    def _evaluate_market(self, market: dict[str, Any]) -> Optional[LongshotCandidate]:
        """
        Evaluate a single market against all gates (except basket limits).

        Returns LongshotCandidate with gate_failures populated if rejected,
        or a clean candidate if all gates pass. Returns None if market data
        is malformed.
        """
        condition_id = str(market.get("condition_id") or market.get("ticker") or "")
        if not condition_id:
            return None

        title = str(market.get("title") or market.get("question") or "")
        category = str(market.get("category") or "other").lower().strip()

        # --- Extract and validate yes_price ---
        try:
            yes_price_raw = market.get("yes_price") or market.get("yes_ask") or market.get("last_price")
            yes_price = float(yes_price_raw or 0.0)
        except (TypeError, ValueError):
            return None

        # Kalshi sometimes reports prices in cents (integer); normalise to dollars
        if yes_price > 1.0:
            yes_price = yes_price / 100.0

        no_price = round(1.0 - yes_price, 6)

        # --- Extract hours to resolution ---
        hours_to_resolution = self._extract_hours_to_resolution(market)

        gate_failures: list[str] = []

        # Gate 1: Price range
        if not (self.config.min_yes_price <= yes_price <= self.config.max_yes_price):
            gate_failures.append("price_range")

        # Gate 2: Rule quality (objective vs subjective)
        rules_text = str(market.get("rules_primary") or market.get("rules") or title)
        rule_type = self._classify_rule_type(title, rules_text)
        if rule_type == "subjective":
            gate_failures.append("rule_quality_subjective")

        # Gate 3: Time to resolution
        if hours_to_resolution < self.config.min_hours_to_resolution:
            gate_failures.append("time_too_short")
        if hours_to_resolution > self.config.max_days_to_resolution * 24:
            gate_failures.append("time_too_long")

        # Gate 4: Fee viability (compute fee on 1 contract for gate check)
        taker_fee = compute_kalshi_fee(1, yes_price, is_maker=False)
        maker_fee = compute_kalshi_fee(1, yes_price, is_maker=True)
        fee_drag_pct = taker_fee / no_price if no_price > 0 else 1.0

        if fee_drag_pct > self.config.max_fee_drag_pct:
            gate_failures.append("fee_drag_too_high")

        # Compute auxiliary metrics even for rejected markets (useful for logging)
        breakeven_wr = compute_breakeven_win_rate(no_price, taker_fee)

        # Posterior lower bound — use observed settled data for prior update
        settled_wins = sum(1 for t in self._settled_trades if t.get("outcome") == "win")
        settled_losses = sum(1 for t in self._settled_trades if t.get("outcome") == "loss")
        p_lower = compute_posterior_lower_bound(
            wins=settled_wins,
            losses=settled_losses,
            alpha=self.config.prior_alpha,
            beta=self.config.prior_beta,
            credible=self.config.credible_level,
        )

        kelly_raw = compute_robust_kelly(p_lower, no_price, taker_fee)
        kelly_sized = kelly_raw * self.config.kelly_fraction

        # Suggested position: kelly_sized * bankroll; capped by config
        suggested_position_usd = min(
            kelly_sized * 100.0,  # Assumes $100 per-niche allocation; caller can scale
            self.config.max_position_usd,
        )

        # Ranking score: edge-to-fee ratio weighted by time efficiency
        edge = max(0.0, p_lower - breakeven_wr)
        time_efficiency = 1.0 / max(1.0, hours_to_resolution / 24.0)  # Prefer faster resolution
        score = edge * kelly_sized * time_efficiency if not gate_failures else 0.0

        return LongshotCandidate(
            condition_id=condition_id,
            title=title,
            category=category,
            yes_price=yes_price,
            no_price=no_price,
            taker_fee=taker_fee,
            maker_fee=maker_fee,
            fee_drag_pct=fee_drag_pct,
            breakeven_win_rate=breakeven_wr,
            p_lower=p_lower,
            kelly_fraction_raw=kelly_raw,
            kelly_fraction_sized=kelly_sized,
            suggested_position_usd=suggested_position_usd,
            hours_to_resolution=hours_to_resolution,
            rule_type=rule_type,
            gate_failures=gate_failures,
            score=score,
        )

    def _classify_rule_type(self, title: str, rules_text: str) -> str:
        """
        Classify market settlement as 'objective' or 'subjective'.

        Objective examples: "Will BTC close above $X on DATE?", "Will GDP be > X?"
        Subjective examples: "Will the Fed's most significant action be X?",
                             "Will the market have a major crash?"

        Returns 'subjective' if any marker phrase is found in title or rules_text.
        Returns 'objective' otherwise.
        """
        combined = (title + " " + rules_text).lower()
        for marker in _SUBJECTIVE_MARKERS:
            if marker in combined:
                logger.debug(
                    "Subjective marker '%s' found in: %.80s",
                    marker,
                    combined[:80],
                )
                return "subjective"
        return "objective"

    def _extract_hours_to_resolution(self, market: dict[str, Any]) -> float:
        """
        Extract hours until market closes from multiple possible field names.

        Kalshi API returns close_time as ISO 8601 string or Unix timestamp.
        Returns hours as float. Returns large value (9999) if not determinable.
        """
        now = time.time()

        # Try hours_to_close directly (pre-computed field)
        if "hours_to_close" in market:
            try:
                return float(market["hours_to_close"])
            except (TypeError, ValueError):
                pass

        # Try Unix timestamp fields
        for field_name in ("closes_at", "close_time", "expiration_time", "end_date_ts"):
            ts = market.get(field_name)
            if ts is None:
                continue
            try:
                ts_float = float(ts)
                if ts_float > now:
                    return (ts_float - now) / 3600.0
            except (TypeError, ValueError):
                pass

        # Try ISO 8601 string fields
        for field_name in ("close_time_str", "closes_at_str", "expiration"):
            ts_str = market.get(field_name)
            if ts_str is None:
                continue
            try:
                # Basic ISO 8601 parse (YYYY-MM-DDTHH:MM:SSZ)
                import datetime
                ts_str_clean = str(ts_str).replace("Z", "+00:00")
                dt = datetime.datetime.fromisoformat(ts_str_clean)
                ts_float = dt.timestamp()
                if ts_float > now:
                    return (ts_float - now) / 3600.0
            except (ValueError, AttributeError):
                pass

        return 9999.0  # Unknown — will fail time_too_long gate

    # ------------------------------------------------------------------
    # Kill condition checks
    # ------------------------------------------------------------------

    def check_kill_conditions(self) -> bool:
        """
        Evaluate kill conditions against settled trade history.

        Called automatically by generate_signals(). Also callable directly
        for monitoring.

        Kill criteria:
            After >= min_settled_for_kill_check trades:
            - win_rate < kill_win_rate_threshold (YES is hitting too often)
            - profit_factor < kill_profit_factor_threshold (net EV negative)

        Returns:
            True if strategy was killed (or was already killed), False otherwise.
        """
        if self._killed:
            return True

        n_settled = len(self._settled_trades)
        if n_settled < self.config.min_settled_for_kill_check:
            return False

        wins = sum(1 for t in self._settled_trades if t.get("outcome") == "win")
        losses = n_settled - wins
        win_rate = wins / n_settled

        # Profit factor: gross profit / gross loss
        gross_profit = sum(
            t.get("pnl", 0.0)
            for t in self._settled_trades
            if t.get("pnl", 0.0) > 0
        )
        gross_loss = abs(sum(
            t.get("pnl", 0.0)
            for t in self._settled_trades
            if t.get("pnl", 0.0) < 0
        ))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        kill_reasons = []
        if win_rate < self.config.kill_win_rate_threshold:
            kill_reasons.append(
                f"win_rate={win_rate:.3f} < threshold={self.config.kill_win_rate_threshold}"
            )
        if profit_factor < self.config.kill_profit_factor_threshold:
            kill_reasons.append(
                f"profit_factor={profit_factor:.3f} < threshold={self.config.kill_profit_factor_threshold}"
            )

        if kill_reasons:
            self._killed = True
            self._kill_reason = "; ".join(kill_reasons)
            logger.error(
                "KILL: KalshiLongshotFadeStrategy killed after %d trades. "
                "WR=%.3f PF=%.3f Reasons: %s",
                n_settled,
                win_rate,
                profit_factor,
                self._kill_reason,
            )
            return True

        logger.debug(
            "Kill check passed: n=%d WR=%.3f PF=%.3f (thresholds: WR>%.2f PF>%.2f)",
            n_settled,
            win_rate,
            profit_factor,
            self.config.kill_win_rate_threshold,
            self.config.kill_profit_factor_threshold,
        )
        return False

    # ------------------------------------------------------------------
    # Trade lifecycle management
    # ------------------------------------------------------------------

    def record_settlement(
        self,
        condition_id: str,
        outcome: str,
        pnl: float,
    ) -> None:
        """
        Record a settled trade for kill condition tracking.

        Args:
            condition_id: Market identifier
            outcome: "win" (YES resolved 0) or "loss" (YES resolved 1)
            pnl: Net P&L after fees in dollars
        """
        if outcome not in ("win", "loss"):
            logger.warning("Invalid outcome '%s' for %s, expected win|loss", outcome, condition_id)
            return

        self._settled_trades.append({
            "condition_id": condition_id,
            "outcome": outcome,
            "pnl": pnl,
            "timestamp": time.time(),
        })

        # Remove from open positions
        if condition_id in self._open_positions:
            candidate = self._open_positions.pop(condition_id)
            cat = candidate.category
            if cat in self._category_counts and self._category_counts[cat] > 0:
                self._category_counts[cat] -= 1

        logger.info(
            "Settlement recorded: %s outcome=%s pnl=%.4f | "
            "total_settled=%d wins=%d",
            condition_id,
            outcome,
            pnl,
            len(self._settled_trades),
            sum(1 for t in self._settled_trades if t.get("outcome") == "win"),
        )

    def status(self) -> dict[str, Any]:
        """Return current strategy status dict for monitoring."""
        n = len(self._settled_trades)
        wins = sum(1 for t in self._settled_trades if t.get("outcome") == "win")
        win_rate = wins / n if n > 0 else None

        gross_profit = sum(
            t.get("pnl", 0.0) for t in self._settled_trades if t.get("pnl", 0.0) > 0
        )
        gross_loss = abs(sum(
            t.get("pnl", 0.0) for t in self._settled_trades if t.get("pnl", 0.0) < 0
        ))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else None

        return {
            "strategy": self.name,
            "killed": self._killed,
            "kill_reason": self._kill_reason or None,
            "settled_trades": n,
            "open_positions": len(self._open_positions),
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "category_counts": dict(self._category_counts),
            "config": {
                "min_yes_price": self.config.min_yes_price,
                "max_yes_price": self.config.max_yes_price,
                "max_fee_drag_pct": self.config.max_fee_drag_pct,
                "kelly_fraction": self.config.kelly_fraction,
                "max_position_usd": self.config.max_position_usd,
                "max_open_positions": self.config.max_open_positions,
                "max_per_category": self.config.max_per_category,
            },
        }
