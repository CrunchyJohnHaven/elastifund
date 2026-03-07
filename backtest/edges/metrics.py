"""EV calculator and slippage model for Polymarket trades."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# Polymarket fee schedule
WINNER_FEE_RATE = 0.02  # 2% fee on winning positions


@dataclass
class SlippageModel:
    """Model execution slippage based on order size and market depth.

    For Polymarket CLOB, slippage comes from:
    1. Spread: difference between best bid/ask
    2. Market impact: walking the book on larger orders
    """

    half_spread: float = 0.02  # Default 2c half-spread for liquid markets
    impact_per_dollar: float = 0.001  # 0.1c per $1 of order size

    def estimate(self, order_size: float, market_price: float) -> float:
        """Estimate total slippage in price terms.

        Returns the price adjustment (always positive = cost).
        """
        spread_cost = self.half_spread
        impact_cost = self.impact_per_dollar * order_size
        return min(spread_cost + impact_cost, 0.10)  # Cap at 10c


# Default slippage models by market liquidity tier
SLIPPAGE_TIGHT = SlippageModel(half_spread=0.01, impact_per_dollar=0.0005)
SLIPPAGE_NORMAL = SlippageModel(half_spread=0.02, impact_per_dollar=0.001)
SLIPPAGE_WIDE = SlippageModel(half_spread=0.04, impact_per_dollar=0.002)


def expected_value(
    win_prob: float,
    market_price: float,
    direction: str,
    order_size: float = 2.0,
    slippage: Optional[SlippageModel] = None,
) -> dict:
    """Compute expected value of a trade net of fees and slippage.

    Args:
        win_prob: Estimated probability of winning (0-1)
        market_price: Current market price for YES outcome (0-1)
        direction: "buy_yes" or "buy_no"
        order_size: Trade size in USDC
        slippage: Slippage model to use (default: SLIPPAGE_NORMAL)

    Returns:
        Dict with ev, gross_ev, fee_cost, slippage_cost, breakeven_prob
    """
    if slippage is None:
        slippage = SLIPPAGE_NORMAL

    slip = slippage.estimate(order_size, market_price)

    if direction == "buy_yes":
        entry = min(market_price + slip, 0.99)
        p_win = win_prob
    else:
        entry = min((1.0 - market_price) + slip, 0.99)
        p_win = 1.0 - win_prob if direction == "buy_no" else win_prob

    if direction == "buy_no":
        p_win = 1.0 - win_prob  # probability NO wins

    # Shares purchased
    shares = order_size / entry

    # Winning: payout - fee - cost
    gross_payout = shares * 1.0
    fee = gross_payout * WINNER_FEE_RATE
    win_pnl = gross_payout - fee - order_size

    # Losing: lose entire cost
    lose_pnl = -order_size

    # EV
    gross_ev = p_win * (shares * 1.0 - order_size) + (1.0 - p_win) * lose_pnl
    fee_cost = p_win * fee
    slippage_cost = slip * shares  # approximate
    net_ev = gross_ev - fee_cost

    # Breakeven probability (what win rate makes EV = 0)
    # p * (payout - fee - cost) + (1-p) * (-cost) = 0
    # p * (payout - fee) = cost
    net_payout = shares * (1.0 - WINNER_FEE_RATE)
    breakeven = order_size / net_payout if net_payout > 0 else 1.0

    return {
        "ev": round(net_ev, 4),
        "gross_ev": round(gross_ev, 4),
        "fee_cost": round(fee_cost, 4),
        "slippage_cost": round(slippage_cost, 4),
        "entry_price": round(entry, 4),
        "shares": round(shares, 4),
        "win_pnl": round(win_pnl, 4),
        "lose_pnl": round(lose_pnl, 4),
        "breakeven_prob": round(breakeven, 4),
        "p_win": round(p_win, 4),
        "edge_over_breakeven": round(p_win - breakeven, 4),
    }


def kelly_fraction(
    win_prob: float,
    market_price: float,
    direction: str,
    fraction: float = 0.25,
) -> float:
    """Compute fractional Kelly bet size as fraction of bankroll.

    Args:
        win_prob: Estimated probability of winning
        market_price: Current YES price
        direction: "buy_yes" or "buy_no"
        fraction: Kelly fraction (0.25 = quarter-Kelly)

    Returns:
        Fraction of bankroll to bet (0.0 to 1.0)
    """
    payout = 1.0 - WINNER_FEE_RATE  # $0.98 net per winning share

    if direction == "buy_yes":
        p = win_prob
        cost = market_price
    else:
        p = 1.0 - win_prob
        cost = 1.0 - market_price

    if cost <= 0 or cost >= payout:
        return 0.0

    odds = (payout - cost) / cost
    if odds <= 0:
        return 0.0

    kelly = (p * odds - (1.0 - p)) / odds
    return max(0.0, min(kelly * fraction, 0.20))  # Cap at 20%


def arr_estimate(
    avg_ev_per_trade: float,
    trades_per_day: float,
    capital: float,
    infra_monthly: float = 20.0,
) -> dict:
    """Estimate annualized rate of return.

    Args:
        avg_ev_per_trade: Average EV per trade in USDC
        trades_per_day: Expected trades per day
        capital: Starting capital
        infra_monthly: Monthly infrastructure cost

    Returns:
        Dict with daily/monthly/annual projections
    """
    daily_gross = avg_ev_per_trade * trades_per_day
    monthly_gross = daily_gross * 30
    monthly_net = monthly_gross - infra_monthly
    annual_net = monthly_net * 12
    arr_pct = (annual_net / capital) * 100 if capital > 0 else 0.0

    return {
        "daily_gross": round(daily_gross, 2),
        "monthly_gross": round(monthly_gross, 2),
        "monthly_net": round(monthly_net, 2),
        "annual_net": round(annual_net, 2),
        "arr_pct": round(arr_pct, 1),
        "capital": capital,
        "trades_per_day": trades_per_day,
    }
