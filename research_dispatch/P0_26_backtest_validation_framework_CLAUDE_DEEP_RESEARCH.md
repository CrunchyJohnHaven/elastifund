# P0-26: Backtesting Validation Framework — Deep Research
**Priority**: P0 (Critical)
**Source**: Claude Deep Research
**Date**: 2026-03-05
**Status**: RESEARCH COMPLETE → IMPROVEMENTS IMPLEMENTING

## Executive Summary
Validating 128% ARR on Polymarket requires passing three gates: realistic simulation (fees, slippage, fill rates), rigorous statistical validation (Deflated Sharpe Ratio, CPCV, Monte Carlo ruin), and honest calibration against NOAA forecast accuracy. Current backtest likely overstates returns by 20-50% due to missing microstructure constraints.

## Key Findings

### 1. Data Infrastructure Limitations
- Polymarket CLOB `/prices-history` returns only midpoint prices — no orderbook depth
- For resolved markets, granularity degrades to 12-hour intervals
- Realistic backtesting requires live L2 orderbook recording via WebSocket (`wss://ws-subscriptions-clob.polymarket.com/ws/`)
- Third-party: PolymarketData.co offers configurable-resolution bid/ask depth snapshots
- Rate limits: 1,500 req/10s for `/book`, 1,000/10s for price history

### 2. Simulation Constraints (will erode 20-50% of backtested returns)

**Fees:**
- Most markets: zero taker fees
- 5-min/15-min crypto markets: parabolic fee peaking at ~1.56% at 50¢
- Weather markets: 2% winner fee on resolved positions (no taker fee)
- Minimum exploitable edge: 2.5-3% after spread costs

**Slippage by market tier:**
| Market Type | Typical Spread | Slippage per $1K |
|---|---|---|
| High-volume politics/crypto | 1-2¢ | 0.1-0.5% |
| Major US city weather | 4-10¢ | 0.5-2% |
| International weather | 10-30¢ | 2-10%+ |
| Niche/illiquid | 10-34¢+ | Untradeable at scale |

**Fill rates:**
- 30-60% for limit orders within 2¢ of midpoint
- Near-zero for orders 5¢+ away in zero-volume markets
- Off-chain matching with no transparent queue priority

### 3. Statistical Validation Requirements

**Minimum sample sizes:**
| Trades (n) | 95% CI for 60% WR | z-stat vs 50% | p-value |
|---|---|---|---|
| 50 | [46.4%, 73.6%] | 1.41 | 0.079 — not significant |
| 100 | [50.4%, 69.6%] | 2.00 | 0.023 — barely |
| 200 | [53.2%, 66.8%] | 2.83 | 0.002 — significant |
| 385 | [55.1%, 64.9%] | 3.92 | <0.0001 — highly significant |

**Brier Score Decomposition (Murphy 1973):**
```
BS = Reliability − Resolution + Uncertainty
```
- Polymarket aggregate Brier: 0.058 at 12-hour horizons
- Highly liquid markets: 0.026
- Profitable strategy target: BS < 0.15

### 4. De Prado's Overfitting Detection

**Deflated Sharpe Ratio:**
```
DSR = Φ[(SR̂ − SR₀) × √(T−1) / √(1 − γ₃·SR̂ + (γ₄−1)/4 · SR̂²)]
```
- DSR ≥ 0.95 required for genuine skill at 95% confidence
- After 1,000 independent backtests with zero skill, expected max Sharpe = 3.26

**CPCV (Combinatorial Purged Cross-Validation):**
- Probability of Backtest Overfitting (PBO) target: < 0.40
- Values > 0.50 indicate likely overfit
- Implementations: `skfolio.model_selection.CombinatorialPurgedCV`, `mlfinlab`

### 5. Kelly Criterion for Binary Contracts
```
f* = (p − c) / (1 − c)
```
- At p=0.70, c=0.55: f* = 33.3% (dangerously aggressive)
- Half-Kelly sacrifices ~25% geometric growth, dramatically reduces variance
- Quarter-Kelly defensible given probability estimation uncertainty
- Never >20-25% on single market; adjust for fees: effective_edge = (p − c) − fee_rate

### 6. Monte Carlo Requirements
- Target: < 5% probability of 50% drawdown
- Minimum 10,000 simulations
- 95th percentile drawdown = 1.5-3× backtest max drawdown
- Strategy showing 23% max drawdown may face 50-70% in practice

### 7. Weather Market Edge
- NOAA 24-hour MAE: ~2-3°F (85-90% accuracy)
- 12-hour MAE: ~1.4°F
- 357 active weather markets covering 30+ cities
- Documented profitable traders: "gopfan2" ($2M+ net profit)
- Edge compressing as more bots enter

**Forecast model update windows:**
- GFS: 00, 06, 12, 18 UTC
- ECMWF: 00, 12 UTC
- HRRR: Hourly (US only)

### 8. Validation Thresholds
| Metric | Healthy | Red Flag |
|---|---|---|
| Backtest Sharpe | 0.5-2.5 | > 3.0 |
| OOS/IS Sharpe Ratio | > 0.50 | < 0.50 |
| Deflated Sharpe Ratio | > 0.95 | < 0.95 |
| PBO (CPCV) | < 0.40 | > 0.50 |
| Monte Carlo P(Ruin) | < 5% | > 10% |
| Min trades for significance | 200-500 | < 100 |

### 9. Regulatory Status (March 2026)
- Polymarket acquired QCEX ($112M) for CFTC DCM license (July 2025)
- US relaunch December 2, 2025 (invite-only, KYC required)
- Two platforms: global crypto-wallet (geo-blocked US) and US CFTC-regulated
- Insider trading rules fully apply (CEA Section 6(c)(1))
- State-level friction: MA, NV, MD issuing cease-and-desist orders

### 10. Fund Structure Notes
- Delaware LP/LLC; prediction market contracts are CFTC-regulated derivatives
- Private Fund Adviser Exemption for AUM < $150M
- Reg D 506(b): up to 35 non-accredited + unlimited accredited
- Section 3(c)(1): max 100 beneficial owners

## Action Items for System Improvement
1. ✅ Add depth-based slippage model to backtest engine
2. ✅ Add 2% winner fee to weather market simulation
3. ✅ Implement Deflated Sharpe Ratio calculation
4. ✅ Add Brier score decomposition (Murphy)
5. ✅ Add fill rate modeling (30-60%)
6. ✅ Implement statistical significance testing (binomial CI)
7. ✅ Enhance Monte Carlo with ruin probability at 50% drawdown threshold
8. ✅ Add Kelly criterion with fee adjustment
9. ⬜ Record live L2 orderbook data via WebSocket (future)
10. ⬜ Implement CPCV (requires mlfinlab dependency)
