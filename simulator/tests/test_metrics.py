"""Unit tests for metrics calculations."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from metrics import (
    compute_max_drawdown,
    compute_hit_rate,
    compute_direction_breakdown,
    build_per_day_summary,
    build_report,
    TradeRecord,
)


def _make_trade(
    trade_id=1, direction="buy_yes", fill_price=0.50, size_usd=2.0,
    edge_pre=0.10, edge_post=0.05, slippage=0.005, spread=0.015,
    fee=0.04, winner_fee=0.0, outcome="YES_WON", pnl=1.0, won=True,
    date="2026-01-15",
) -> TradeRecord:
    return TradeRecord(
        trade_id=trade_id,
        market_id=f"mkt_{trade_id}",
        question=f"Test question {trade_id}?",
        direction=direction,
        entry_price=0.50,
        fill_price=fill_price,
        size_usd=size_usd,
        shares=size_usd / fill_price if fill_price > 0 else 0,
        edge_pre_cost=edge_pre,
        edge_post_cost=edge_post,
        slippage=slippage,
        spread_cost=spread,
        fee_paid=fee,
        winner_fee=winner_fee,
        outcome=outcome,
        pnl=pnl,
        won=won,
        trade_date=date,
        capital_before=75.0,
        capital_after=76.0 if won else 73.0,
    )


# --- Max drawdown ---

def test_max_drawdown_monotonic_up():
    dd, dd_pct = compute_max_drawdown([100, 101, 102, 103])
    assert dd == 0.0
    assert dd_pct == 0.0

def test_max_drawdown_monotonic_down():
    dd, dd_pct = compute_max_drawdown([100, 90, 80, 70])
    assert dd == 30.0
    assert abs(dd_pct - 0.30) < 1e-6

def test_max_drawdown_recovery():
    dd, dd_pct = compute_max_drawdown([100, 90, 95, 110, 105])
    assert dd == 10.0  # 100 → 90
    assert abs(dd_pct - 0.10) < 1e-6

def test_max_drawdown_multiple_dips():
    dd, dd_pct = compute_max_drawdown([100, 95, 105, 85, 110])
    assert dd == 20.0  # 105 → 85
    assert abs(dd_pct - 20.0 / 105.0) < 1e-6

def test_max_drawdown_empty():
    dd, dd_pct = compute_max_drawdown([])
    assert dd == 0.0

def test_max_drawdown_single_point():
    dd, dd_pct = compute_max_drawdown([50])
    assert dd == 0.0


# --- Hit rate ---

def test_hit_rate_all_wins():
    trades = [_make_trade(i, won=True, outcome="YES_WON") for i in range(5)]
    assert compute_hit_rate(trades) == 1.0

def test_hit_rate_all_losses():
    trades = [_make_trade(i, won=False, outcome="NO_WON", pnl=-2.0) for i in range(5)]
    assert compute_hit_rate(trades) == 0.0

def test_hit_rate_mixed():
    trades = [
        _make_trade(1, won=True, outcome="YES_WON"),
        _make_trade(2, won=True, outcome="YES_WON"),
        _make_trade(3, won=False, outcome="NO_WON", pnl=-2.0),
    ]
    assert abs(compute_hit_rate(trades) - 2/3) < 1e-6

def test_hit_rate_excludes_unresolved():
    trades = [
        _make_trade(1, won=True, outcome="YES_WON"),
        _make_trade(2, won=False, outcome=None, pnl=0.0),  # Unresolved
    ]
    assert compute_hit_rate(trades) == 1.0  # Only resolved counted

def test_hit_rate_empty():
    assert compute_hit_rate([]) == 0.0


# --- Direction breakdown ---

def test_direction_breakdown():
    trades = [
        _make_trade(1, direction="buy_yes", won=True, outcome="YES_WON", pnl=2.0),
        _make_trade(2, direction="buy_yes", won=False, outcome="NO_WON", pnl=-2.0),
        _make_trade(3, direction="buy_no", won=True, outcome="NO_WON", pnl=1.5),
    ]
    bd = compute_direction_breakdown(trades)
    assert bd["buy_yes"]["count"] == 2
    assert bd["buy_yes"]["win_rate"] == 0.5
    assert abs(bd["buy_yes"]["total_pnl"] - 0.0) < 1e-6
    assert bd["buy_no"]["count"] == 1
    assert bd["buy_no"]["win_rate"] == 1.0
    assert abs(bd["buy_no"]["total_pnl"] - 1.5) < 1e-6

def test_direction_breakdown_empty():
    bd = compute_direction_breakdown([])
    assert bd["buy_yes"]["count"] == 0
    assert bd["buy_no"]["count"] == 0


# --- Per-day summary ---

def test_per_day_summary_single_day():
    trades = [
        _make_trade(1, won=True, pnl=1.5, date="2026-01-15", fee=0.04, winner_fee=0.02),
        _make_trade(2, won=False, pnl=-2.0, date="2026-01-15", fee=0.04, winner_fee=0.0),
    ]
    days = build_per_day_summary(trades, 75.0)
    assert len(days) == 1
    assert days[0].date == "2026-01-15"
    assert days[0].wins == 1
    assert days[0].losses == 1
    assert abs(days[0].net_pnl - (-0.5)) < 1e-6

def test_per_day_summary_multi_day():
    trades = [
        _make_trade(1, won=True, pnl=3.0, date="2026-01-15"),
        _make_trade(2, won=True, pnl=2.0, date="2026-01-16"),
    ]
    days = build_per_day_summary(trades, 75.0)
    assert len(days) == 2
    assert days[0].date == "2026-01-15"
    assert days[1].date == "2026-01-16"
    assert abs(days[1].cumulative_pnl - 5.0) < 1e-6

def test_per_day_drawdown():
    trades = [
        _make_trade(1, won=True, pnl=5.0, date="2026-01-15"),
        _make_trade(2, won=False, pnl=-10.0, date="2026-01-16"),
    ]
    days = build_per_day_summary(trades, 75.0)
    # Day 1: capital = 80, peak = 80
    # Day 2: capital = 70, drawdown = (80-70)/80 = 0.125
    assert abs(days[1].drawdown - 0.125) < 1e-6


# --- Full report ---

def test_build_report_basic():
    trades = [
        _make_trade(1, direction="buy_yes", won=True, pnl=2.0, fee=0.04, winner_fee=0.04,
                     slippage=0.005, spread=0.015, size_usd=2.0),
        _make_trade(2, direction="buy_no", won=True, pnl=1.5, fee=0.04, winner_fee=0.03,
                     slippage=0.003, spread=0.015, size_usd=2.0),
        _make_trade(3, direction="buy_yes", won=False, pnl=-2.0, fee=0.04, winner_fee=0.0,
                     slippage=0.005, spread=0.015, size_usd=2.0),
    ]
    equity = [75.0, 77.0, 78.5, 76.5]
    report = build_report(trades, 75.0, equity)

    assert report.total_trades == 3
    assert report.filled_trades == 3
    assert report.winning_trades == 2
    assert report.losing_trades == 1
    assert abs(report.hit_rate - 2/3) < 1e-6
    assert abs(report.total_pnl - 1.5) < 1e-6
    assert report.final_capital == 76.5

def test_build_report_includes_per_trade_log():
    trades = [_make_trade(1)]
    equity = [75.0, 76.0]
    report = build_report(trades, 75.0, equity)
    assert len(report.per_trade_log) == 1
    assert report.per_trade_log[0]["trade_id"] == 1

def test_build_report_return_pct():
    trades = [_make_trade(1, pnl=7.5)]
    equity = [75.0, 82.5]
    report = build_report(trades, 75.0, equity)
    assert abs(report.return_pct - 0.10) < 1e-6  # 10% return

def test_build_report_unfilled():
    trades = [
        _make_trade(1, fill_price=0.0, pnl=0.0, outcome=None, won=False),  # Unfilled
        _make_trade(2, won=True, pnl=1.0),
    ]
    equity = [75.0, 76.0]
    report = build_report(trades, 75.0, equity)
    assert report.filled_trades == 1
    assert report.unfilled_trades == 1

def test_build_report_empty():
    report = build_report([], 75.0, [75.0])
    assert report.total_trades == 0
    assert report.hit_rate == 0.0
    assert report.total_pnl == 0.0


# --- Sizing integration (from sizing module) ---

def test_sizing_imports():
    from sizing import fixed_fraction_size, kelly_size, capped_size, compute_position_size

    # Fixed fraction
    assert abs(fixed_fraction_size(75.0, 0.027) - 2.025) < 1e-6

    # Kelly with no edge → 0
    assert kelly_size(75.0, 0.0, 0.5) == 0.0

    # Kelly with edge
    size = kelly_size(75.0, 0.10, 0.60, kelly_fraction=0.25)
    assert size > 0

    # Capped
    capped = capped_size(75.0, 0.50, 0.80, max_position_usd=5.0)
    assert capped <= 5.0


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
