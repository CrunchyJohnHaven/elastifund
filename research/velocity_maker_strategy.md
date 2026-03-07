# Velocity Maker Strategy

**Status:** Active (deploying March 7, 2026)
**Thesis:** Combine fast-resolving markets + maker-only execution + category targeting for maximum capital velocity and structural edge.

## Quantified Edge Sources

### 1. Capital Velocity (Backtest-Proven)
- <24h markets: **72% win rate**, $0.88 avg P&L, 0.3369 avg edge
- Velocity top-5 per cycle: **6,007% ARR** vs 1,130% baseline (+432%)
- Average resolution drops from 35.1 days → 4.7 days
- Source: `backtest/data/velocity_analysis.json`, 470 trades

### 2. Maker Structural Edge (72.1M Trades)
- Makers: **+1.12%** excess return (CI: [+1.11%, +1.13%])
- Takers: **-1.12%** excess return
- 0% maker fees on all markets + daily USDC rebates
- Source: jbecker.dev, $18.26B volume dataset

### 3. Category-Specific Gaps (Maker-Taker Differential)
| Category | Gap (pp) | Competition |
|---|---|---|
| World Events | 7.32 | Very low |
| Media | 7.28 | Very low |
| Entertainment | 4.79 | Low |
| Crypto | 2.69 | High |
| Sports | 2.23 | Medium |
| Politics | 1.02 | High |
| Finance | 0.17 | Very high |

### 4. Optimism Tax (YES Longshot Bias)
- YES contracts at 1¢: **-41% EV** for takers
- NO contracts at 1¢: **+23% EV** for takers
- 64pp divergence at same price level
- NO outperforms YES at 69/99 price levels
- Action: Prefer NO-side trades, sell into YES longshot flow

## Target Market Types

### Tier 1: Fast-Resolving Event Markets
- Resolution: <24 hours
- Categories: Entertainment, World Events, Media, Sports (game-day)
- Execution: Maker limit orders, Claude probability estimation
- Scan interval: 60 seconds

### Tier 2: Daily Weather Markets (Future)
- 153+ markets daily, 0% fees
- Edge: Professional forecast models (GFS, ECMWF) vs crowd
- Resolution: End of day
- Competition: Very low

### Tier 3: 5-Minute Crypto Markets (Future)
- BTC/ETH/SOL/XRP Up/Down
- Requires WebSocket integration + real-time exchange feeds
- 0% maker fees + rebates
- More competitive but high volume

## Execution Rules

1. **Maker-only orders** — never cross the spread
2. **NO-side preference** — exploit the optimism tax
3. **Position size: $2-5** per trade (paper mode)
4. **Max 5 concurrent positions** — capital velocity over diversification
5. **Exit on edge capture** — don't hold to resolution if 80% of edge captured
6. **Scan interval: 60s** — responsive to fast markets
7. **Skip if estimated resolution > 7 days** — velocity filter

## Implementation Architecture

```
Every 60 seconds:
  1. SCAN    Fetch markets, filter by resolution time (<24h priority)
  2. RANK    Score by: velocity_score * category_edge_multiplier
  3. ANALYZE Claude estimates probability (anti-anchoring prompt)
  4. FILTER  Edge > 5%, confidence >= medium, liquidity > $100
  5. SIZE    Kelly criterion with time-aware dampener
  6. EXECUTE Maker limit order (current price - 1¢ for buys)
  7. MONITOR Check exits on existing positions
  8. RESOLVE Check if open positions have resolved
```

## Key Parameters
- `scan_interval`: 60s
- `min_edge_threshold`: 0.05
- `min_liquidity`: 100
- `max_concurrent_positions`: 5
- `position_size_usd`: 2.0
- `max_resolution_days`: 7
- `preferred_resolution_hours`: 24
- `maker_only`: true
- `no_side_preference_weight`: 1.2

## Risk Controls
- Max daily drawdown: 15% of capital
- Max single position: 10% of capital
- Volatility pause: Skip if price moved >20% in last hour
- Kill switch: Automatic on 3 consecutive losses

## Success Metrics
- Target win rate: >65% (backtest shows 72% on <24h)
- Target capital velocity: >1000% ARR
- Target resolved trades per week: 5+
- Zero ruin probability across Monte Carlo simulations

## References
- jbecker.dev/research/prediction-market-microstructure (72.1M trades)
- backtest/data/velocity_analysis.json (432% ARR improvement)
- backtest/data/combined_calibrator_results.json (category Brier scores)
- Polymarket docs: fees, maker rebates, CLOB API
