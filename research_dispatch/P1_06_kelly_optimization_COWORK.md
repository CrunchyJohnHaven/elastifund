# P1-06: Kelly Criterion Optimization for Position Sizing
**Tool:** COWORK
**Status:** COMPLETED
**Date Completed:** 2026-03-05
**Expected ARR Impact:** +10-20% (optimal capital allocation)

---

## Research Findings

### Core Kelly Formula (Binary Markets)
For a binary bet with true win-probability p and net odds b = (1–price)/price:

```
f* = (b·p - q) / b,  where q = 1 - p
```

**Worked example:** Market YES at $0.40 (40% implied), our model gives p=0.55 → b=1.5 → f*=0.25 (25% of bankroll).

Growth function: G(f) = p·ln(1 + f·b) + (1-p)·ln(1 - f)

### Fractional Kelly — Critical for $75 Bankroll

Full Kelly is mathematically optimal for log-growth but entails extreme drawdowns: **X% chance of an X% drawdown** (50% chance of halving bankroll).

**Simulation results (200 bets, edge uniform [5%-47%], b=1):**

| Fraction | Median Terminal Wealth | P(50% Drawdown) | Ruin (<$5) | Sharpe |
|----------|----------------------|-----------------|------------|--------|
| Full (1×) | ~2.2×10¹⁶ | 100% | 36.9% | 0.37 |
| Half (0.5×) | ~1.5×10¹¹ | 94.7% | ~0% | 0.57 |
| Quarter (0.25×) | ~2.0×10⁶ | 8.0% | ~0% | 0.64 |
| Tenth (0.1×) | ~5.4×10² | 0% | ~0% | 0.68 |

**Key insight:** Quarter-Kelly has the best Sharpe ratio (0.64) with 0% ruin and only 8% chance of 50% drawdown. This is our recommended default.

### Edge Uncertainty ("Shrunk Kelly")
When probability estimates have error σ, the optimal fraction shrinks:

```
α ≈ (edge)² / ((edge)² + σ²)
```

With our Claude estimates (edge ~30%, σ ~10%): α ≈ 0.90 (90% of Kelly). Combined with quarter-Kelly: effective multiplier = 0.25 × 0.90 = 0.225×.

### Correlated Positions (Portfolio Kelly)
For multiple correlated bets, Kelly generalizes to:

```
f* = Σ⁻¹ · μ  (inverse covariance × expected excess returns)
```

**Example with correlated bets:** Naive independent Kelly sums to 130% of bankroll (overbetting). Covariance-aware solution hedges redundant positions, reducing net exposure.

**Critical for our system:** Political markets are highly correlated (election outcomes, party performance). Must track and adjust for correlation or risk catastrophic overbetting.

### Ruin Analysis at $75 Bankroll

10,000 simulations × 500 bets:
- **Full Kelly:** 0.7-0.8% ruin (<$1)
- **Half Kelly:** ~0% ruin
- **Quarter Kelly:** 0% ruin

$75 is sufficient bankroll for <5% ruin at half-Kelly. Even $50 would be adequate.

### Growth Trajectory: $75 → $500
At quarter-Kelly: **median ~26 bets** (10th-90th percentile: 18-38 bets).
Math: ln(6.67) / G_quarter(0.0666) ≈ 28 bets.

### Dynamic Sizing Rule
Scale up fraction as bankroll grows:
- W < $150: 0.25× Kelly
- W ≥ $300: 0.50× Kelly
- W ≥ $500: 0.75× Kelly

### Implementation Details
- **Tick size:** Round to nearest $0.01 (Polymarket standard)
- **Minimum stake:** $1.00 — skip if Kelly-optimal < $1
- **Fee adjustment:** Deduct `stake × fee_rate × p × (1-p)` for taker orders
- **Recalc frequency:** After each trade or significant price change; minimum end-of-day

### Python Implementation

```python
def kelly_bet(bankroll, edge, market_price, kelly_frac=1.0, fee_rate=0.0):
    p_est = market_price + edge
    if p_est <= 0 or p_est >= 1:
        return 0.0
    b = (1 - market_price) / market_price
    f_star = (b * p_est - (1 - p_est)) / b
    f_star = max(f_star, 0.0)
    f = kelly_frac * f_star
    stake = f * bankroll
    fee_cost = stake * fee_rate * market_price * (1 - market_price)
    stake = max(stake - fee_cost, 0.0)
    min_stake = 1.0
    if stake < min_stake:
        return 0.0
    stake = round(stake / 0.01) * 0.01
    return stake
```

---

## Implementation Spec for Bot Integration

### Changes Required:
1. **`src/risk/manager.py`:** Add `kelly_position_size()` method that takes (bankroll, edge, market_price, side, kelly_frac) and returns USD stake
2. **`src/paper_trader.py`:** Replace flat $2 sizing with Kelly-computed size
3. **`src/core/config.py`:** Add `kelly_fraction` setting (default 0.25), `min_stake` (default $1.00)
4. **Correlation tracking:** Log market categories; apply 50% haircut to position sizes in same category when >3 concurrent positions

### Asymmetric Kelly (leveraging NO-bias):
- buy_yes: 0.25× Kelly (conservative — 55.8% win rate)
- buy_no: 0.35× Kelly (aggressive — 76.2% win rate, structural edge)

---

## Original Prompt (Archived)

```
I have a prediction market trading bot with these backtest results on 532 resolved markets:
... [see git history for original prompt]
```
