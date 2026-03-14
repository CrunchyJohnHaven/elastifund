# DISPATCH 102: BTC5 Promotion Evidence and Scale Decision

**Date:** 2026-03-14
**Author:** JJ (autonomous analysis)
**Data Source:** Polymarket-History-2026-03-13.csv (wallet export)
**Data Range:** March 9-11, 2026 (2.2 trading days, 243 resolved markets)
**Supersedes:** Prior DISPATCH_102 from March 14 (which used stale March 10 data)

## Executive Summary

The BTC5 maker sleeve does NOT pass the promotion gate for scaling to $10/trade. The previous CLAUDE.md claim of "+$131.52, 128 contracts, 75/53 W/L, 1.49 profit factor" was based on a stale March 10 snapshot that captured only the profitable first day. Full wallet export analysis reveals a barely-positive edge that gave back 89% of Day 1 profits on Days 2-3.

**Recommendation: HOLD at $5/trade. Do not scale.**

## Honest Numbers

| Metric | Previous Claim (CLAUDE.md) | Wallet-Verified Reality |
|--------|---------------------------|------------------------|
| Total resolved | 128 contracts | 243 markets |
| Win rate | 58.6% (75/53 W/L) | 51.4% (125W/118L) |
| Cumulative PnL | +$131.52 | +$14.62 |
| Profit factor | 1.49 | 1.01 |
| Avg win | +$5.35 | +$9.57 |
| Avg loss | -$5.10 | -$10.01 |
| Max drawdown | Not reported | $236.68 (71% of capital) |

## Why the Numbers Diverged

The March 10 manual wallet-export read counted "BTC closed cashflow" using a methodology that likely:
1. Included only fully-settled markets from March 9 (the best day)
2. Excluded markets from March 10 that had resolved at a loss by March 13
3. May have counted redeems as wins without checking cost-vs-revenue

The wallet export CSV uses "Redeem" for any binary market that resolves in the held direction. But buying at $0.52 and redeeming at $1.00 is a win; buying at $0.48 and the market resolving against you (no Redeem row, cost lost) is a loss. The correct methodology counts PnL = revenue - cost per market, classifying markets with no redeem as total losses.

## Promotion Gate Results

| Gate | Threshold | Actual | Result |
|------|-----------|--------|--------|
| Closed trades | >= 50 | 243 | PASS |
| Win rate | >= 55% | 51.4% | FAIL |
| Cumulative PnL | > 0 | +$14.62 | PASS |
| Profit factor | > 1.1 | 1.01 | FAIL |
| Max DD < 50% capital | < $166.50 | $236.68 | FAIL |
| Sharpe > 0.5 | > 0.5 | 0.80 | PASS |

**Overall: FAIL (3 of 6 gates failed)**

## Direction Analysis

| Direction | Wins | Losses | Win Rate | PnL |
|-----------|------|--------|----------|-----|
| DOWN | 107 | 99 | 51.9% | +$52.80 |
| UP | 18 | 19 | 48.6% | -$38.18 |

DOWN is slightly profitable. UP is net negative.

## Daily Breakdown

| Date | Wins | Losses | PnL | Note |
|------|------|--------|-----|------|
| March 9 | 62 | 38 | +$136.86 | Strong first day, BTC fear index at extremes |
| March 10 | 20 | 29 | -$38.70 | Losses exceeded wins |
| March 11 | 43 | 51 | -$83.53 | Worst day, gave back most of March 9 gains |

## Hour-of-Day Edge Map (ET)

Profitable hours: 03-06 ET (+$193.14), 12-19 ET (+$128.37)
Losing hours: 00-02 ET (-$105.03), 08-09 ET (-$153.96)

A time-of-day filter suppressing 00-02 and 08-09 ET would improve net PnL substantially.

## Risk Metrics

- **Kelly fraction:** 0.006 (effectively zero; at this edge, optimal bet size is trivial)
- **Max drawdown:** $236.68 (71% of $333 capital)
- **Annualized Sharpe:** 0.80 (heavily influenced by March 9 outlier)

## Recommendations

### Do NOT scale to $10/trade.

1. **Implement time-of-day filter**: Suppress trading during 00-02 ET and 08-09 ET
2. **Run 7+ more days at $5/trade** before reconsidering scale
3. **Fix zero-fill problem first**: System has been producing 0 fills since ~March 11
4. **DOWN-only mode**: DOWN has a slight edge; UP is net negative
5. **Tighter guardrails during losing hours**: Reduce position size by 50% during 00-02 and 08-09 ET

## Corrected CLAUDE.md Figures

- BTC5 cumulative PnL: +$14.62 (wallet-verified, March 9-11)
- BTC5 markets: 243 resolved, 125W/118L, 51.4% win rate
- Profit factor: 1.01
- Max drawdown: $236.68 (71% of capital)
- Direction: DOWN slightly positive (+$52.80), UP net negative (-$38.18)
- Kelly: 0.006
- Status: HOLD at $5/trade, do NOT scale
