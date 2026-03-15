"""
Sophisticated Binary Option Pricing Engine for Prediction Markets.

Prediction markets are binary options that pay $1 if the event occurs, $0 otherwise.
This module provides multiple pricing models, Greeks, and trading signal generation
for Polymarket prediction market positions.

Models included:
1. Black-Scholes Binary Option Pricing
2. Implied Volatility Extraction
3. Greeks (Delta, Theta, Vega, Gamma)
4. Merton Jump-Diffusion Model
5. Ornstein-Uhlenbeck Mean-Reversion Model
6. Information-Theoretic Pricing
7. Volatility Surface
8. Risk-Neutral Pricing
9. Composite Signal Generator
"""

from dataclasses import dataclass
from typing import Optional, Tuple, List, Dict
import numpy as np
from scipy import stats
from scipy.optimize import minimize_scalar, fminbound
from scipy.interpolate import griddata
import warnings

warnings.filterwarnings("ignore")


# ============================================================================
# 1. BLACK-SCHOLES BINARY OPTION PRICING
# ============================================================================

def black_scholes_binary(
    market_price: float,
    implied_vol: float,
    time_to_resolution_days: float,
    risk_free_rate: float = 0.05,
) -> float:
    """
    Price a binary (cash-or-nothing) option using adapted Black-Scholes formula.

    For prediction markets:
    - S = current market price (0 to 1)
    - K = 0.50 (fair value threshold)
    - σ = implied volatility from spread
    - r = risk-free rate
    - T = time to resolution in years

    Returns the fair value of the YES position.

    Formula:
        Price = e^(-rT) * N(d2)
        d2 = (ln(S/K) + (r - σ²/2)T) / (σ√T)

    Args:
        market_price: Current market price (0.0 to 1.0)
        implied_vol: Implied volatility (annualized)
        time_to_resolution_days: Days until market resolves
        risk_free_rate: Annual risk-free rate (default: 5%)

    Returns:
        Fair value price for the YES option (0.0 to 1.0)
    """
    # Validate inputs
    if not 0 <= market_price <= 1:
        raise ValueError(f"market_price must be between 0 and 1, got {market_price}")
    if implied_vol < 0:
        raise ValueError(f"implied_vol must be non-negative, got {implied_vol}")
    if time_to_resolution_days <= 0:
        raise ValueError(f"time_to_resolution_days must be positive, got {time_to_resolution_days}")

    # Edge cases
    if implied_vol < 1e-6:
        return market_price

    T = time_to_resolution_days / 365.0
    S = market_price
    K = 0.50
    r = risk_free_rate
    sigma = implied_vol

    # Avoid log(0)
    if S < 1e-6:
        S = 1e-6
    elif S > 1 - 1e-6:
        S = 1 - 1e-6

    # Calculate d2
    numerator = np.log(S / K) + (r - sigma ** 2 / 2) * T
    denominator = sigma * np.sqrt(T)

    if abs(denominator) < 1e-10:
        return market_price

    d2 = numerator / denominator

    # Price = e^(-rT) * N(d2)
    discount_factor = np.exp(-r * T)
    price = discount_factor * stats.norm.cdf(d2)

    return np.clip(price, 0.0, 1.0)


# ============================================================================
# 2. IMPLIED VOLATILITY EXTRACTION
# ============================================================================

def implied_volatility(
    market_price: float,
    bid: float,
    ask: float,
    time_to_resolution_days: float,
    initial_guess: float = 0.5,
) -> float:
    """
    Extract implied volatility from bid-ask spread.

    Method 1: σ_implied ≈ spread / (price * sqrt(T))
    Method 2: Solve inverse Black-Scholes (solver method)
    Uses method 2 for accuracy.

    Args:
        market_price: Mid-price (bid + ask) / 2
        bid: Bid price
        ask: Ask price
        time_to_resolution_days: Days until resolution
        initial_guess: Initial guess for solver

    Returns:
        Implied volatility (annualized)
    """
    if bid >= ask:
        raise ValueError(f"bid ({bid}) must be less than ask ({ask})")

    spread = ask - bid
    T = time_to_resolution_days / 365.0

    # Quick estimate
    if market_price > 0 and T > 0:
        quick_estimate = spread / (market_price * np.sqrt(T))
    else:
        quick_estimate = 0.5

    # If spread is very small, return minimum volatility
    if spread < 1e-4:
        return 0.05

    # Use solver to find IV that matches market price
    def objective(vol):
        try:
            bs_price = black_scholes_binary(market_price, vol, time_to_resolution_days)
            return abs(bs_price - market_price) ** 2
        except:
            return 1e10

    result = minimize_scalar(
        objective,
        bounds=(0.01, 3.0),
        method='bounded',
    )

    implied_vol = result.x if result.success else quick_estimate
    return np.clip(implied_vol, 0.01, 3.0)


# ============================================================================
# 3. GREEKS FOR PREDICTION MARKETS
# ============================================================================

@dataclass
class BinaryGreeks:
    """
    Greeks for binary options in prediction markets.

    Attributes:
        delta: Price sensitivity to underlying (dp/dS)
        theta: Time decay (dp/dT) - positive approaching expiry
        vega: Volatility sensitivity (dp/dσ)
        gamma: Delta acceleration (d²p/dS²)
        price: Current fair value
    """
    delta: float
    theta: float
    vega: float
    gamma: float
    price: float


def compute_greeks(
    market_price: float,
    implied_vol: float,
    time_to_resolution_days: float,
    risk_free_rate: float = 0.05,
    bump: float = 1e-4,
) -> BinaryGreeks:
    """
    Compute all Greeks for a binary option position.

    Greeks indicate sensitivity to various market factors:
    - Delta (Δ): How much price changes with market price moves
    - Theta (Θ): Time decay as market approaches resolution
    - Vega (ν): Sensitivity to volatility changes
    - Gamma (Γ): How fast delta changes (convexity)

    Args:
        market_price: Current market price (0.0 to 1.0)
        implied_vol: Implied volatility
        time_to_resolution_days: Days until resolution
        risk_free_rate: Risk-free rate
        bump: Perturbation size for numerical derivatives

    Returns:
        BinaryGreeks dataclass with all Greeks
    """
    # Base price
    price = black_scholes_binary(
        market_price, implied_vol, time_to_resolution_days, risk_free_rate
    )

    # Delta: dp/dS (numerical derivative)
    price_up = black_scholes_binary(
        market_price + bump, implied_vol, time_to_resolution_days, risk_free_rate
    )
    delta = (price_up - price) / bump

    # Gamma: d²p/dS² (second derivative)
    price_down = black_scholes_binary(
        market_price - bump, implied_vol, time_to_resolution_days, risk_free_rate
    )
    gamma = (price_up - 2 * price + price_down) / (bump ** 2)

    # Theta: dp/dT (time decay, in days)
    if time_to_resolution_days > 1:
        price_t_minus_1 = black_scholes_binary(
            market_price, implied_vol, time_to_resolution_days - 1, risk_free_rate
        )
        theta = price - price_t_minus_1
    else:
        theta = 0.0

    # Vega: dp/dσ (volatility sensitivity)
    if implied_vol > bump:
        price_vol_up = black_scholes_binary(
            market_price, implied_vol + bump, time_to_resolution_days, risk_free_rate
        )
        vega = (price_vol_up - price) / bump
    else:
        vega = 0.0

    return BinaryGreeks(
        delta=float(delta),
        theta=float(theta),
        vega=float(vega),
        gamma=float(gamma),
        price=float(price),
    )


# ============================================================================
# 4. MERTON JUMP-DIFFUSION MODEL
# ============================================================================

def merton_jump_diffusion_price(
    market_price: float,
    volatility: float,
    time_days: float,
    jump_intensity: float = 0.5,
    jump_mean: float = -0.05,
    jump_std: float = 0.10,
    risk_free_rate: float = 0.05,
    num_jumps_range: int = 10,
) -> float:
    """
    Price binary option using Merton jump-diffusion model.

    Prediction markets have JUMP RISK — sudden news causes price to leap 20-50%.
    This model accounts for jumps via Poisson process.

    Model: dS = μSdt + σSdW + J*dN
    where:
        N ~ Poisson(λ) = jump intensity
        J ~ Normal(mean, std) = jump size distribution

    Method: Solve using weighted average of prices conditional on number of jumps.

    Args:
        market_price: Current market price
        volatility: Continuous volatility component
        time_days: Days until resolution
        jump_intensity: Expected jumps per year (default: 0.5)
        jump_mean: Mean jump size (default: -0.05 = -5%)
        jump_std: Jump size std dev (default: 0.10 = 10%)
        risk_free_rate: Annual risk-free rate
        num_jumps_range: Max number of jumps to consider in sum

    Returns:
        Fair value adjusted for jump risk
    """
    T = time_days / 365.0

    # Expected number of jumps
    lambda_t = jump_intensity * T

    # Initialize price accumulator
    total_price = 0.0
    total_weight = 0.0

    # Sum over possible number of jumps (0, 1, 2, ..., num_jumps_range)
    for n in range(num_jumps_range + 1):
        # Probability of exactly n jumps (Poisson)
        prob_n_jumps = stats.poisson.pmf(n, lambda_t)

        if prob_n_jumps < 1e-8:
            continue

        # For n jumps, adjust the diffusion component
        # σ_n is the effective volatility with n jumps
        sigma_n = np.sqrt(volatility ** 2 + (n * jump_std ** 2) / T) if T > 0 else volatility

        # Adjusted price accounting for jump contribution
        # The mean price impact from n jumps
        jump_impact = n * jump_mean  # Expected total jump magnitude

        # Price with this jump scenario: use BS with adjusted vol
        # and shifted mean
        adjusted_price = market_price * (1 + jump_impact)
        adjusted_price = np.clip(adjusted_price, 0.001, 0.999)

        conditional_price = black_scholes_binary(
            adjusted_price, sigma_n, time_days, risk_free_rate
        )

        total_price += conditional_price * prob_n_jumps
        total_weight += prob_n_jumps

    # Normalize
    if total_weight > 0:
        fair_value = total_price / total_weight
    else:
        fair_value = market_price

    return np.clip(fair_value, 0.0, 1.0)


# ============================================================================
# 5. ORNSTEIN-UHLENBECK MEAN-REVERSION MODEL
# ============================================================================

def ornstein_uhlenbeck_fair_value(
    price_history: List[float],
    current_price: float,
    dt: float = 1.0,
) -> Tuple[float, float, float]:
    """
    Estimate fair value and mean reversion speed using Ornstein-Uhlenbeck model.

    Markets oscillate around a long-run fair value. This detects temporary mispricings.

    Model: dX = θ(μ - X)dt + σdW
    where:
        θ = speed of mean reversion (higher = faster reversion)
        μ = long-run mean (equilibrium price)
        σ = volatility

    Args:
        price_history: Historical prices (at least 2 points)
        current_price: Current market price
        dt: Time step (default: 1 day)

    Returns:
        Tuple of (fair_value, reversion_speed, volatility)
    """
    if len(price_history) < 2:
        return current_price, 0.0, 0.0

    prices = np.array(price_history, dtype=float)

    # Calculate price differences
    diffs = np.diff(prices)

    # Estimate long-run mean (simple average for now)
    long_run_mean = np.mean(prices)

    # Deviations from mean
    deviations = prices[:-1] - long_run_mean

    # Estimate reversion speed via regression
    # dX ≈ -θ(X - μ)dt + σdW
    # E[dX | X] ≈ -θ(X - μ)dt

    if np.std(deviations) > 1e-10:
        # Regression: dX = -θ(X - μ)dt + noise
        coefficients = np.polyfit(deviations, diffs, 1)
        theta = -coefficients[0] / dt  # Reversion speed
        theta = max(0, theta)  # Ensure non-negative
    else:
        theta = 0.0

    # Volatility of residuals
    if len(diffs) > 1:
        residuals = diffs - (-theta * deviations * dt)
        sigma = np.std(residuals)
    else:
        sigma = 0.0

    return float(long_run_mean), float(theta), float(sigma)


# ============================================================================
# 6. INFORMATION-THEORETIC PRICING
# ============================================================================

def information_edge(
    our_probability: float,
    market_price: float,
    epsilon: float = 1e-10,
) -> Tuple[float, float, float]:
    """
    Compute information-theoretic edge vs market price.

    Measures divergence between our estimate and market's implied probability.
    Higher divergence = larger mispricing opportunity.

    Args:
        our_probability: Our estimate of event probability (0.0 to 1.0)
        market_price: Market's implied probability (0.0 to 1.0)
        epsilon: Numerical stability constant

    Returns:
        Tuple of (kl_divergence, shannon_entropy, edge_score)
        - kl_divergence: KL(market || ours) - measure of mispricing
        - shannon_entropy: Entropy of market price
        - edge_score: Normalized edge strength (0-100)
    """
    # Clamp probabilities to valid range
    p = np.clip(our_probability, epsilon, 1 - epsilon)
    q = np.clip(market_price, epsilon, 1 - epsilon)

    # KL Divergence: D_KL(q || p)
    # Measures how different q (market) is from p (ours)
    kl_div = q * np.log(q / p) + (1 - q) * np.log((1 - q) / (1 - p))

    # Shannon Entropy: H(X) = -[p*ln(p) + (1-p)*ln(1-p)]
    # Maximum entropy at 0.5 (maximum uncertainty)
    entropy = -(q * np.log(q) + (1 - q) * np.log(1 - q))

    # Edge score: Scale KL divergence, normalized by entropy
    # Higher entropy = lower information content
    max_entropy = np.log(2)  # Maximum entropy (at p=0.5)
    entropy_factor = max(0.1, entropy / max_entropy)

    # Edge score from 0-100: higher KL divergence and lower entropy = stronger edge
    edge_score = min(100.0, (kl_div / entropy_factor) * 100)

    return float(kl_div), float(entropy), float(edge_score)


# ============================================================================
# 7. VOLATILITY SURFACE
# ============================================================================

class VolatilitySurface:
    """
    Volatility surface across multiple markets and time horizons.

    Maps implied volatility as a function of:
    - Time to resolution (days)
    - Price level (moneyness relative to 0.5)

    Identifies volatility smile/skew patterns.
    """

    def __init__(self):
        """Initialize empty volatility surface."""
        self.data_points: List[Dict] = []
        self._surface = None

    def add_data_point(
        self,
        time_days: float,
        market_price: float,
        implied_vol: float,
        market_id: Optional[str] = None,
    ) -> None:
        """
        Add a volatility observation to the surface.

        Args:
            time_days: Days to resolution
            market_price: Market price (0.0 to 1.0)
            implied_vol: Implied volatility at this point
            market_id: Optional market identifier
        """
        self.data_points.append({
            'time_days': time_days,
            'market_price': market_price,
            'implied_vol': implied_vol,
            'market_id': market_id,
        })
        self._surface = None  # Invalidate cache

    def add_market_data(
        self,
        market_id: str,
        bid: float,
        ask: float,
        time_days: float,
    ) -> None:
        """
        Add market data (bid-ask spread) to surface.

        Args:
            market_id: Market identifier
            bid: Bid price
            ask: Ask price
            time_days: Days to resolution
        """
        market_price = (bid + ask) / 2
        iv = implied_volatility(market_price, bid, ask, time_days)
        self.add_data_point(time_days, market_price, iv, market_id)

    def interpolate(self, time_days: float, market_price: float) -> Optional[float]:
        """
        Interpolate implied volatility at given point.

        Args:
            time_days: Days to resolution
            market_price: Market price

        Returns:
            Interpolated implied volatility, or None if insufficient data
        """
        if len(self.data_points) < 4:
            return None

        points = np.array([[d['time_days'], d['market_price']] for d in self.data_points])
        values = np.array([d['implied_vol'] for d in self.data_points])

        try:
            iv = griddata(
                points,
                values,
                (time_days, market_price),
                method='linear',
            )
            return float(iv) if not np.isnan(iv) else None
        except Exception:
            return None

    def get_smile(self, time_days: float) -> Optional[Tuple[np.ndarray, np.ndarray]]:
        """
        Get volatility smile at specific time horizon.

        Returns:
            Tuple of (price_levels, volatilities) at this time, or None
        """
        if len(self.data_points) < 3:
            return None

        # Filter data at this time (within tolerance)
        time_tolerance = 1.0
        filtered = [
            d for d in self.data_points
            if abs(d['time_days'] - time_days) < time_tolerance
        ]

        if len(filtered) < 2:
            return None

        prices = np.array([d['market_price'] for d in filtered])
        vols = np.array([d['implied_vol'] for d in filtered])

        # Sort by price
        sort_idx = np.argsort(prices)
        return prices[sort_idx], vols[sort_idx]

    def get_term_structure(self, market_price: float) -> Optional[Tuple[np.ndarray, np.ndarray]]:
        """
        Get term structure of volatility at specific price level.

        Returns:
            Tuple of (times, volatilities) at this price, or None
        """
        if len(self.data_points) < 3:
            return None

        # Filter data at this price (within tolerance)
        price_tolerance = 0.05
        filtered = [
            d for d in self.data_points
            if abs(d['market_price'] - market_price) < price_tolerance
        ]

        if len(filtered) < 2:
            return None

        times = np.array([d['time_days'] for d in filtered])
        vols = np.array([d['implied_vol'] for d in filtered])

        # Sort by time
        sort_idx = np.argsort(times)
        return times[sort_idx], vols[sort_idx]


# ============================================================================
# 8. RISK-NEUTRAL PRICING
# ============================================================================

def risk_neutral_probability(
    bid: float,
    ask: float,
    time_to_resolution_days: float,
    risk_free_rate: float = 0.05,
) -> Tuple[float, float, float]:
    """
    Extract risk-neutral probability from bid-ask spread.

    Risk-neutral probabilities reflect market pricing but NOT actual probabilities.
    The difference between physical (real-world) and risk-neutral probabilities
    represents the risk premium.

    For binary options: Risk-neutral price ≈ P(Q) where Q is risk-neutral measure.

    Args:
        bid: Bid price (discounted risk-neutral value for YES)
        ask: Ask price (upper bound on risk-neutral value for YES)
        time_to_resolution_days: Days until resolution
        risk_free_rate: Risk-free rate

    Returns:
        Tuple of (risk_neutral_prob, bid_probability, ask_probability)
    """
    T = time_to_resolution_days / 365.0
    discount_factor = np.exp(-risk_free_rate * T)

    # Approximate risk-neutral probability from prices
    # Mid-price approximates risk-neutral probability (for liquid markets)
    mid_price = (bid + ask) / 2
    risk_neutral_prob = mid_price / discount_factor if discount_factor > 0 else mid_price

    # Bound by bid-ask
    bid_prob = bid / discount_factor if discount_factor > 0 else bid
    ask_prob = ask / discount_factor if discount_factor > 0 else ask

    # Clamp to [0, 1]
    risk_neutral_prob = np.clip(risk_neutral_prob, 0.0, 1.0)
    bid_prob = np.clip(bid_prob, 0.0, 1.0)
    ask_prob = np.clip(ask_prob, 0.0, 1.0)

    return float(risk_neutral_prob), float(bid_prob), float(ask_prob)


# ============================================================================
# 9. COMPOSITE SIGNAL GENERATOR
# ============================================================================

@dataclass
class CompositeSignalResult:
    """
    Trading signal from composite pricing model.

    Attributes:
        fair_value_estimate: Blended fair value from all models (0.0 to 1.0)
        confidence: Confidence in estimate (0.0 to 1.0)
        edge_vs_market: Absolute edge magnitude (price difference)
        greeks: BinaryGreeks for this position
        signal_strength: Signal strength (0.0 to 10.0)
        recommended_action: Trading action ("buy_yes", "buy_no", "hold")
        model_contributions: Dict of contributions from each model
    """
    fair_value_estimate: float
    confidence: float
    edge_vs_market: float
    greeks: BinaryGreeks
    signal_strength: float
    recommended_action: str
    model_contributions: Dict[str, float]


class CompositeSignal:
    """
    Composite trading signal combining all pricing models.

    Generates unified trading signals from:
    1. Black-Scholes binary pricing
    2. Merton jump-diffusion
    3. Ornstein-Uhlenbeck mean reversion
    4. Risk-neutral probability extraction
    5. Information-theoretic edge
    """

    def __init__(
        self,
        bs_weight: float = 0.35,
        merton_weight: float = 0.15,
        ou_weight: float = 0.20,
        rn_weight: float = 0.15,
        info_weight: float = 0.15,
    ):
        """
        Initialize composite signal with model weights.

        Args:
            bs_weight: Black-Scholes weight
            merton_weight: Merton jump-diffusion weight
            ou_weight: Ornstein-Uhlenbeck weight
            rn_weight: Risk-neutral weight
            info_weight: Information-theoretic weight
        """
        total = bs_weight + merton_weight + ou_weight + rn_weight + info_weight
        self.bs_weight = bs_weight / total
        self.merton_weight = merton_weight / total
        self.ou_weight = ou_weight / total
        self.rn_weight = rn_weight / total
        self.info_weight = info_weight / total

    def generate_signal(
        self,
        market_price: float,
        bid: float,
        ask: float,
        time_to_resolution_days: float,
        price_history: Optional[List[float]] = None,
        our_probability: Optional[float] = None,
        jump_intensity: float = 0.5,
        risk_free_rate: float = 0.05,
        min_signal_strength: float = 2.0,
    ) -> CompositeSignalResult:
        """
        Generate composite trading signal.

        Args:
            market_price: Current mid-price
            bid: Bid price
            ask: Ask price
            time_to_resolution_days: Days until resolution
            price_history: Optional historical prices for OU model
            our_probability: Our probability estimate (optional)
            jump_intensity: Expected jumps per year
            risk_free_rate: Risk-free rate
            min_signal_strength: Minimum signal to trade

        Returns:
            CompositeSignalResult with trading recommendation
        """
        # Calculate implied volatility
        iv = implied_volatility(market_price, bid, ask, time_to_resolution_days)

        # 1. Black-Scholes price
        bs_price = black_scholes_binary(
            market_price, iv, time_to_resolution_days, risk_free_rate
        )

        # 2. Merton jump-diffusion price
        merton_price = merton_jump_diffusion_price(
            market_price, iv, time_to_resolution_days,
            jump_intensity=jump_intensity,
            risk_free_rate=risk_free_rate,
        )

        # 3. Ornstein-Uhlenbeck fair value
        if price_history and len(price_history) > 2:
            ou_fair_value, _, _ = ornstein_uhlenbeck_fair_value(
                price_history, market_price
            )
        else:
            ou_fair_value = market_price

        # 4. Risk-neutral probability
        rn_prob, _, _ = risk_neutral_probability(
            bid, ask, time_to_resolution_days, risk_free_rate
        )

        # 5. Information-theoretic edge
        if our_probability is not None:
            kl_div, entropy, edge_score = information_edge(our_probability, market_price)
            info_price = our_probability
        else:
            info_price = market_price
            edge_score = 0.0

        # Composite fair value
        fair_value = (
            self.bs_weight * bs_price +
            self.merton_weight * merton_price +
            self.ou_weight * ou_fair_value +
            self.rn_weight * rn_prob +
            self.info_weight * info_price
        )

        # Calculate edge
        edge = fair_value - market_price
        edge_magnitude = abs(edge)

        # Confidence: Higher agreement between models = higher confidence
        model_prices = np.array([bs_price, merton_price, ou_fair_value, rn_prob, info_price])
        model_std = np.std(model_prices)
        confidence = 1.0 / (1.0 + model_std)  # Higher agreement = higher confidence

        # Compute Greeks for recommended position
        greeks = compute_greeks(market_price, iv, time_to_resolution_days, risk_free_rate)

        # Signal strength (0-10 scale)
        # Based on edge magnitude and confidence
        signal_strength = edge_magnitude * confidence * 10.0

        # Recommendation
        if signal_strength < min_signal_strength:
            recommended_action = "hold"
        elif edge > 0:
            recommended_action = "buy_yes"
        else:
            recommended_action = "buy_no"

        # Model contributions
        model_contributions = {
            'black_scholes': float(bs_price),
            'merton_jump': float(merton_price),
            'ou_mean_reversion': float(ou_fair_value),
            'risk_neutral': float(rn_prob),
            'information_theoretic': float(info_price),
        }

        return CompositeSignalResult(
            fair_value_estimate=float(np.clip(fair_value, 0.0, 1.0)),
            confidence=float(confidence),
            edge_vs_market=float(edge),
            greeks=greeks,
            signal_strength=float(signal_strength),
            recommended_action=recommended_action,
            model_contributions=model_contributions,
        )


# ============================================================================
# DEMONSTRATION AND TESTING
# ============================================================================

if __name__ == "__main__":
    print("=" * 80)
    print("BINARY OPTION PRICING ENGINE FOR PREDICTION MARKETS")
    print("=" * 80)
    print()

    # Example market data
    market_price = 0.65
    bid = 0.63
    ask = 0.67
    time_to_resolution_days = 30.0
    price_history = [0.60, 0.62, 0.64, 0.65, 0.66, 0.65]
    our_estimate = 0.70  # We think probability is 70%

    print(f"Market Data:")
    print(f"  Bid: {bid:.4f}")
    print(f"  Ask: {ask:.4f}")
    print(f"  Mid: {market_price:.4f}")
    print(f"  Time to resolution: {time_to_resolution_days} days")
    print()

    # ===== Model 1: Black-Scholes =====
    print("-" * 80)
    print("1. BLACK-SCHOLES BINARY OPTION PRICING")
    print("-" * 80)
    iv = implied_volatility(market_price, bid, ask, time_to_resolution_days)
    print(f"Implied Volatility: {iv:.4f} ({iv*100:.2f}%)")

    bs_price = black_scholes_binary(market_price, iv, time_to_resolution_days)
    print(f"Black-Scholes Fair Value: {bs_price:.4f}")
    print(f"Edge vs Market: {(bs_price - market_price):.4f}")
    print()

    # ===== Model 2: Greeks =====
    print("-" * 80)
    print("2. GREEKS")
    print("-" * 80)
    greeks = compute_greeks(market_price, iv, time_to_resolution_days)
    print(f"Delta (Δ):  {greeks.delta:.6f}  (price sensitivity)")
    print(f"Gamma (Γ):  {greeks.gamma:.6f}  (delta acceleration)")
    print(f"Theta (Θ):  {greeks.theta:.6f}  (daily time decay)")
    print(f"Vega (ν):   {greeks.vega:.6f}  (volatility sensitivity)")
    print()

    # ===== Model 3: Merton Jump-Diffusion =====
    print("-" * 80)
    print("3. MERTON JUMP-DIFFUSION MODEL")
    print("-" * 80)
    merton_price = merton_jump_diffusion_price(
        market_price, iv, time_to_resolution_days,
        jump_intensity=0.5,
        jump_mean=-0.05,
        jump_std=0.10,
    )
    print(f"Merton Fair Value: {merton_price:.4f}")
    print(f"Jump Adjustment: {(merton_price - bs_price):.4f}")
    print()

    # ===== Model 4: Ornstein-Uhlenbeck =====
    print("-" * 80)
    print("4. ORNSTEIN-UHLENBECK MEAN-REVERSION")
    print("-" * 80)
    ou_fair, ou_theta, ou_sigma = ornstein_uhlenbeck_fair_value(price_history, market_price)
    print(f"Long-run Fair Value: {ou_fair:.4f}")
    print(f"Mean Reversion Speed (θ): {ou_theta:.4f} per day")
    print(f"Volatility: {ou_sigma:.4f}")
    print(f"Mispricing (market - fair): {(market_price - ou_fair):.4f}")
    print()

    # ===== Model 5: Information Theory =====
    print("-" * 80)
    print("5. INFORMATION-THEORETIC PRICING")
    print("-" * 80)
    kl_div, entropy, edge_score = information_edge(our_estimate, market_price)
    print(f"Our Probability Estimate: {our_estimate:.4f}")
    print(f"KL Divergence: {kl_div:.6f}")
    print(f"Shannon Entropy: {entropy:.6f}")
    print(f"Edge Score: {edge_score:.2f}")
    print()

    # ===== Model 6: Volatility Surface =====
    print("-" * 80)
    print("6. VOLATILITY SURFACE")
    print("-" * 80)
    vol_surface = VolatilitySurface()
    markets = [
        (0.60, 30),
        (0.65, 30),
        (0.70, 30),
        (0.65, 7),
        (0.65, 60),
    ]
    for price, days in markets:
        # Simulate market data
        bid_sim = price - 0.02
        ask_sim = price + 0.02
        vol_surface.add_market_data("sample_market", bid_sim, ask_sim, days)

    print(f"Added {len(vol_surface.data_points)} data points to surface")
    interpolated = vol_surface.interpolate(35, 0.65)
    print(f"Interpolated IV at T=35d, P=0.65: {interpolated:.4f}" if interpolated else "N/A")
    print()

    # ===== Model 7: Risk-Neutral Probability =====
    print("-" * 80)
    print("7. RISK-NEUTRAL PRICING")
    print("-" * 80)
    rn_prob, rn_bid, rn_ask = risk_neutral_probability(bid, ask, time_to_resolution_days)
    print(f"Risk-Neutral Probability (mid): {rn_prob:.4f}")
    print(f"Risk-Neutral Probability (bid): {rn_bid:.4f}")
    print(f"Risk-Neutral Probability (ask): {rn_ask:.4f}")
    print(f"Risk Premium: {(rn_prob - our_estimate):.4f}")
    print()

    # ===== Model 8: Composite Signal =====
    print("-" * 80)
    print("8. COMPOSITE SIGNAL GENERATOR")
    print("-" * 80)
    compositor = CompositeSignal()
    signal = compositor.generate_signal(
        market_price=market_price,
        bid=bid,
        ask=ask,
        time_to_resolution_days=time_to_resolution_days,
        price_history=price_history,
        our_probability=our_estimate,
        jump_intensity=0.5,
    )

    print(f"Fair Value Estimate: {signal.fair_value_estimate:.4f}")
    print(f"Confidence: {signal.confidence:.2%}")
    print(f"Edge vs Market: {signal.edge_vs_market:.4f}")
    print(f"Signal Strength: {signal.signal_strength:.2f} / 10")
    print(f"Recommended Action: {signal.recommended_action.upper()}")
    print()
    print("Model Contributions:")
    for model_name, contribution in signal.model_contributions.items():
        print(f"  {model_name:25s}: {contribution:.4f}")
    print()
    print("Greeks for Recommended Position:")
    print(f"  Delta: {signal.greeks.delta:.6f}")
    print(f"  Gamma: {signal.greeks.gamma:.6f}")
    print(f"  Theta: {signal.greeks.theta:.6f}")
    print(f"  Vega:  {signal.greeks.vega:.6f}")
    print()

    print("=" * 80)
    print("END OF DEMONSTRATION")
    print("=" * 80)
