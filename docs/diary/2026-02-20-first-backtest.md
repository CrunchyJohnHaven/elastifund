# Day 5: February 20, 2026 — First Backtest: 532 Markets

## What the Agent Did Today

Ran Claude Haiku against 532 resolved Polymarket markets. For each market, the AI estimated the probability of the YES outcome without seeing the market price (anti-anchoring discipline). Then we compared those estimates to what actually happened.

## What I Built Today

- Market scanner (`scanner.py`) — fetches active and resolved markets from Gamma API
- Claude probability estimator (`claude_analyzer.py`) — sends each market question to Claude with anti-anchoring prompt
- Backtest engine (`backtest/engine.py`) — runs the estimator against resolved markets, computes accuracy metrics
- Paper trader (`paper_trader.py`) — simulates trades based on the estimator's signals

## The Results

| Metric | Value |
|--------|-------|
| Markets tested | 532 |
| Markets with signal (>5% edge) | 470 (88%) |
| Win rate | 64.9% |
| Brier score | 0.2391 |
| Simulated P&L (flat $2 bets) | +$280.00 |
| Buy YES win rate | 55.8% |
| Buy NO win rate | **76.2%** |

## What I Learned

Two things jumped out:

**1. The NO-side bias is enormous.** The AI wins 76.2% of the time when buying NO versus only 55.8% when buying YES. This is the favorite-longshot bias in action — prediction market participants systematically overprice low-probability exciting events and underprice boring-but-likely outcomes. The academic literature (Whelan 2025, Becker 2025) documents this, and our data confirms it perfectly.

**2. Claude is systematically overconfident on YES.** When Claude says it's 90% confident in YES, the actual hit rate is only ~63%. This is acquiescence bias — the AI agrees with the framing of YES questions. This means our raw estimates need calibration before they're tradeable.

The win rate of 64.9% sounds good, but Brier score of 0.2391 is mediocre. A perfect forecaster scores 0. Random guessing on binary events scores 0.25. We're barely above random. The edge is real but thin — and that's before transaction costs.

## Key Numbers

| Metric | Value |
|--------|-------|
| Capital | $0 |
| Strategies tested | 1 |
| Tests passing | 12 |
| Research dispatches | 8 |

## Tomorrow's Plan

Implement Platt scaling calibration. If we can correct Claude's overconfidence, win rate should improve significantly. Also: implement asymmetric thresholds (higher bar for YES signals, lower for NO) to exploit the favorite-longshot bias.

---

*Tags: #strategy-tested #live-trading #research-cycle*
