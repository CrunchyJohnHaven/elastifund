"""
Metrics computation for the paper-trade simulator.

Computes:
- PnL (total, per-trade, per-day)
- Max drawdown (peak-to-trough)
- Hit rate (win/loss ratio)
- Average edge (pre-cost and post-cost)
- Turnover
- Fee drag and slippage drag
- Per-trade logs and per-day summaries
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class TradeRecord:
    """Full record of a single simulated trade."""
    trade_id: int
    market_id: str
    question: str
    direction: str               # buy_yes | buy_no
    entry_price: float           # Market mid price at signal time
    fill_price: float            # Actual fill price after slippage/spread
    size_usd: float              # Dollar size of position
    shares: float                # Number of outcome shares
    edge_pre_cost: float         # Raw edge before costs
    edge_post_cost: float        # Edge after spread + slippage + fees
    slippage: float              # Price slippage
    spread_cost: float           # Half-spread cost
    fee_paid: float              # Entry fee in USD
    winner_fee: float            # Fee on winning payout
    outcome: Optional[str]       # YES_WON | NO_WON
    pnl: float                   # Realized PnL
    won: bool                    # Did this trade win?
    trade_date: str              # ISO date string
    capital_before: float        # Capital before this trade
    capital_after: float         # Capital after resolution


@dataclass
class DaySummary:
    """Per-day aggregated summary."""
    date: str
    trades_entered: int = 0
    trades_resolved: int = 0
    gross_pnl: float = 0.0
    fees_paid: float = 0.0
    slippage_cost: float = 0.0
    spread_cost: float = 0.0
    net_pnl: float = 0.0
    capital_eod: float = 0.0
    drawdown: float = 0.0
    cumulative_pnl: float = 0.0
    wins: int = 0
    losses: int = 0


@dataclass
class SimulationReport:
    """Complete simulation output report."""
    # Summary metrics
    total_trades: int = 0
    filled_trades: int = 0
    unfilled_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0

    total_pnl: float = 0.0
    avg_pnl_per_trade: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    hit_rate: float = 0.0

    avg_edge_pre_cost: float = 0.0
    avg_edge_post_cost: float = 0.0

    total_turnover: float = 0.0
    total_fees: float = 0.0
    total_slippage_cost: float = 0.0
    total_spread_cost: float = 0.0
    fee_drag_pct: float = 0.0
    slippage_drag_pct: float = 0.0
    spread_drag_pct: float = 0.0

    final_capital: float = 0.0
    return_pct: float = 0.0

    # Breakdowns
    by_direction: dict = field(default_factory=dict)
    per_trade_log: list = field(default_factory=list)
    per_day_summary: list = field(default_factory=list)

    # Assumption sensitivity
    assumptions_impact: dict = field(default_factory=dict)


def compute_max_drawdown(equity_curve: list[float]) -> tuple[float, float]:
    """
    Compute max drawdown from an equity curve.

    Returns (max_drawdown_absolute, max_drawdown_pct).
    """
    if not equity_curve:
        return 0.0, 0.0

    peak = equity_curve[0]
    max_dd = 0.0
    max_dd_pct = 0.0

    for value in equity_curve:
        if value > peak:
            peak = value
        dd = peak - value
        dd_pct = dd / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
            max_dd_pct = dd_pct

    return max_dd, max_dd_pct


def compute_hit_rate(trades: list[TradeRecord]) -> float:
    """Win rate across all resolved trades."""
    resolved = [t for t in trades if t.outcome is not None]
    if not resolved:
        return 0.0
    return sum(1 for t in resolved if t.won) / len(resolved)


def compute_direction_breakdown(trades: list[TradeRecord]) -> dict:
    """Break down metrics by direction (buy_yes vs buy_no)."""
    result = {}
    for direction in ("buy_yes", "buy_no"):
        dir_trades = [t for t in trades if t.direction == direction and t.outcome is not None]
        if not dir_trades:
            result[direction] = {
                "count": 0, "win_rate": 0.0, "avg_pnl": 0.0, "total_pnl": 0.0,
            }
            continue
        wins = sum(1 for t in dir_trades if t.won)
        total_pnl = sum(t.pnl for t in dir_trades)
        result[direction] = {
            "count": len(dir_trades),
            "win_rate": wins / len(dir_trades),
            "avg_pnl": total_pnl / len(dir_trades),
            "total_pnl": total_pnl,
        }
    return result


def build_per_day_summary(
    trades: list[TradeRecord],
    initial_capital: float,
) -> list[DaySummary]:
    """Aggregate trades into per-day summaries."""
    days: dict[str, DaySummary] = {}

    for t in trades:
        d = t.trade_date
        if d not in days:
            days[d] = DaySummary(date=d)
        day = days[d]
        day.trades_entered += 1
        if t.outcome is not None:
            day.trades_resolved += 1
            day.net_pnl += t.pnl
            day.fees_paid += t.fee_paid + t.winner_fee
            day.slippage_cost += t.slippage * t.size_usd
            day.spread_cost += t.spread_cost * t.size_usd
            if t.won:
                day.wins += 1
            else:
                day.losses += 1

    # Sort by date and compute cumulative
    sorted_days = sorted(days.values(), key=lambda d: d.date)
    cumulative = 0.0
    capital = initial_capital
    peak_capital = initial_capital
    for day in sorted_days:
        cumulative += day.net_pnl
        day.cumulative_pnl = cumulative
        capital = initial_capital + cumulative
        day.capital_eod = capital
        if capital > peak_capital:
            peak_capital = capital
        day.drawdown = (peak_capital - capital) / peak_capital if peak_capital > 0 else 0.0
        day.gross_pnl = day.net_pnl + day.fees_paid

    return sorted_days


def build_report(
    trades: list[TradeRecord],
    initial_capital: float,
    equity_curve: list[float],
) -> SimulationReport:
    """Build the full simulation report from trade records."""
    report = SimulationReport()

    filled = [t for t in trades if t.fill_price > 0]
    resolved = [t for t in filled if t.outcome is not None]

    report.total_trades = len(trades)
    report.filled_trades = len(filled)
    report.unfilled_trades = len(trades) - len(filled)
    report.winning_trades = sum(1 for t in resolved if t.won)
    report.losing_trades = sum(1 for t in resolved if not t.won)

    report.total_pnl = sum(t.pnl for t in resolved)
    report.avg_pnl_per_trade = report.total_pnl / len(resolved) if resolved else 0.0

    report.max_drawdown, report.max_drawdown_pct = compute_max_drawdown(equity_curve)
    report.hit_rate = compute_hit_rate(resolved)

    if resolved:
        report.avg_edge_pre_cost = sum(t.edge_pre_cost for t in resolved) / len(resolved)
        report.avg_edge_post_cost = sum(t.edge_post_cost for t in resolved) / len(resolved)

    report.total_turnover = sum(t.size_usd for t in filled)
    report.total_fees = sum(t.fee_paid + t.winner_fee for t in resolved)
    report.total_slippage_cost = sum(t.slippage * t.size_usd for t in filled)
    report.total_spread_cost = sum(t.spread_cost * t.size_usd for t in filled)

    if report.total_turnover > 0:
        report.fee_drag_pct = report.total_fees / report.total_turnover
        report.slippage_drag_pct = report.total_slippage_cost / report.total_turnover
        report.spread_drag_pct = report.total_spread_cost / report.total_turnover

    report.final_capital = equity_curve[-1] if equity_curve else initial_capital
    report.return_pct = (report.final_capital - initial_capital) / initial_capital if initial_capital > 0 else 0.0

    report.by_direction = compute_direction_breakdown(resolved)
    report.per_trade_log = [_trade_to_dict(t) for t in trades]
    report.per_day_summary = [_day_to_dict(d) for d in build_per_day_summary(resolved, initial_capital)]

    return report


def _trade_to_dict(t: TradeRecord) -> dict:
    return {
        "trade_id": t.trade_id,
        "market_id": t.market_id,
        "question": t.question[:80],
        "direction": t.direction,
        "entry_price": round(t.entry_price, 4),
        "fill_price": round(t.fill_price, 4),
        "size_usd": round(t.size_usd, 2),
        "shares": round(t.shares, 4),
        "edge_pre_cost": round(t.edge_pre_cost, 4),
        "edge_post_cost": round(t.edge_post_cost, 4),
        "slippage": round(t.slippage, 6),
        "spread_cost": round(t.spread_cost, 4),
        "fee_paid": round(t.fee_paid, 4),
        "winner_fee": round(t.winner_fee, 4),
        "outcome": t.outcome,
        "pnl": round(t.pnl, 4),
        "won": t.won,
        "date": t.trade_date,
    }


def _day_to_dict(d: DaySummary) -> dict:
    return {
        "date": d.date,
        "trades_entered": d.trades_entered,
        "trades_resolved": d.trades_resolved,
        "gross_pnl": round(d.gross_pnl, 4),
        "fees_paid": round(d.fees_paid, 4),
        "slippage_cost": round(d.slippage_cost, 4),
        "spread_cost": round(d.spread_cost, 4),
        "net_pnl": round(d.net_pnl, 4),
        "capital_eod": round(d.capital_eod, 2),
        "drawdown": round(d.drawdown, 4),
        "cumulative_pnl": round(d.cumulative_pnl, 4),
        "wins": d.wins,
        "losses": d.losses,
    }
