# EVIDENCE LEDGER MASTER

## Complete Claims Assessment

| # | Claim | Claim Type | Source of Evidence | Confidence (1-10) | Homepage Safe? | Plain-English Version | Risk if Overstated |
|---|-------|-----------|-------------------|------------------|----------------|----------------------|-------------------|
| 1 | 532 markets backtested | Historical Backtest | Our category database + trading history | 9/10 | **Yes** | We tested our model on 532 different prediction markets from historical data | Minimal—just a count |
| 2 | 68.5% calibrated win rate (out-of-sample) | Historical Backtest | Post-calibration evaluation on holdout 2024 data | 6/10 | **No** | Our model correctly predicted 68.5% of market outcomes in test data we didn't train on | Moderate—win rate sensitive to data selection; only 1 holdout period tested |
| 3 | 70.2% NO win rate | Historical Backtest | Category-specific performance metrics | 6/10 | **No** | We predicted "No" outcomes more accurately (70.2%) than "Yes" outcomes | High—heavily dependent on favorite-longshot bias; may not persist |
| 4 | +$276 simulated P&L on 372 trades | Historical Backtest | Backtest runner with midpoint price model | 5/10 | **No** | Model trades generated $276 profit across 372 historical scenarios | High—no slippage, midpoint-only pricing, no actual execution |
| 5 | Platt scaling improves Brier from 0.239 to 0.2451 | Historical Backtest (OOS validated) | Calibration pipeline on 2024 holdout | 7/10 | **No** | Platt scaling adjustment improved forecast accuracy metrics on test data | Moderate—barely better than random; small sample of validation trades |
| 6 | 0% ruin probability | Simulation (Monte Carlo) | 10,000 path simulation with Kelly-fraction sizing | 3/10 | **No** | Monte Carlo simulation suggests zero chance of account ruin over 1-year horizon | **Critical**—Monte Carlo results only as good as input assumptions; doesn't model regime change, edge decay, or black-swan liquidity events |
| 7 | +6,007% ARR (velocity-optimized) | Historical Backtest + Model Projection | Backtest with full leverage + quarter-Kelly + category routing | 2/10 | **No** | Theoretical annualized return if strategy maintains current performance at full scale | **Extremely High**—relies on aggressive assumptions; no live validation; assumes constant trade frequency; ignores fees/slippage |
| 8 | +124% to +872% ARR range | Historical Backtest + Model Projection | Backtest sensitivity analysis across Kelly fractions | 3/10 | **No** | Projected annual returns vary based on leverage assumptions | **Extremely High**—wide range masks deep uncertainty; not anchored to live performance |
| 9 | Quarter-Kelly outperforms flat by +309% | Historical Backtest | Leverage comparison in backtest | 5/10 | **No** | Backtest shows quarter-Kelly sizing produces 309% higher returns than equal-sized bets | High—leverage amplifies both wins and losses; no live validation |
| 10 | Anti-anchoring increases edge divergence 25.7% | Historical Backtest | Feature contribution analysis | 4/10 | **No** | Our debiasing technique showed 25.7% improvement in model separation on historical data | High—feature importance in backtest ≠ causal; may not generalize |
| 11 | Category routing improves win rate | Historical Backtest | Category-stratified performance | 6/10 | **No** | Routing trades to categories with better historical win rates improved overall accuracy | Moderate—assumes category characteristics are stable over time |
| 12 | NO-bias exploits favorite-longshot bias | Historical Backtest + Academic Research | Academic literature (Thorp, Sharpe) + our empirical data | 7/10 | **Maybe*** | Academic research supports that underdogs are underpriced; our data shows we capture this | Moderate—bias well-documented but competitive advantage likely short-lived |
| 13 | Weather arbitrage structural edge | Planned (NOAA only) | Conceptual; NOAA data only, not multi-model ensemble | 2/10 | **No** | Planned feature to incorporate weather data for event prediction | **Critical**—not yet tested; single-source data only; ensemble not implemented |
| 14 | Multi-model ensemble improves accuracy | Planned (skeleton only) | Skeleton code only; no integration or validation | 1/10 | **No** | Plan to combine multiple models for better predictions | **Critical**—completely unvalidated; exists only as concept |
| 15 | Paper trading running on VPS | Implemented (live) | 2 cycles post-calibration; 17 trades; $68 deployed | 9/10 | **Yes** | We are actively testing our model in real markets with real money (paper trades) | Low—we're transparent about small scale; this is early |
| 16 | Safety rails operational (6 types) | Implemented (live) | Safety module deployed; max-loss checks, position limits, circuit breakers | 8/10 | **Yes** | We have automated safeguards to prevent catastrophic losses | Low—safeguards are real, even if strategies are nascent |
| 17 | 42 research dispatch prompts built | Implemented (queue) | Prompt queue visible in codebase | 9/10 | **No** | We have built 42 automated research tasks to iteratively improve the model | Low—count is accurate; this is infrastructure for future development |
| 18 | Agentic RAG, market-making, cross-platform | Planned | Roadmap items only | 1/10 | **No** | We plan to build advanced features including AI-driven research and multi-exchange support | **Critical**—purely aspirational; no code or timeline |
| 19 | Profits fund veteran suicide prevention | Stated Mission | Public statement; $0 profits realized to date | 10/10 (truthful) | **No*** | We commit to donating future profits to veteran mental health support | Low on truthfulness, **High on sustainability**—we haven't earned profits yet; charitable commitment is real but contingent |
| 20 | $75 seed + $1,000/week deployment | Implemented (funded) | Invoice, bank account, VPS records | 9/10 | **Yes** | Our operation is seed-funded and we reinvest ~$1,000 per week into live trading | Low—numbers are verifiable; this is honest |

---

## CONFIDENCE & HOMEPAGE SAFETY SUMMARY

### GREEN (Safe for Homepage - Confidence 6+ AND Honest Risk Profile)
- **#1**: 532 markets backtested ✓
- **#15**: Paper trading on VPS ✓
- **#16**: Safety rails operational ✓
- **#20**: $75 seed + $1,000/week ✓

### YELLOW (Deeper Site Only - True but Needs Caveats)
- **#2**: 68.5% calibrated win rate (with "out-of-sample backtest" caveat)
- **#11**: Category routing improves win rate (with "historical data" caveat)
- **#12**: NO-bias exploits favorite-longshot (with "documented bias, not proprietary edge" caveat)

### RED (Keep Off Homepage - Misleading, Overfit, or Unsupported)
- **#3**: 70.2% NO win rate (category-specific overfitting signal)
- **#4**: +$276 P&L (no slippage, midpoint-only pricing)
- **#5**: Platt scaling improvement (barely beats random)
- **#6**: 0% ruin probability (Monte Carlo only; ignores regime change)
- **#7**: +6,007% ARR (extreme overpromising)
- **#8**: +124% to +872% ARR (range is meaningless without context)
- **#9**: Quarter-Kelly +309% (leverage amplification, not edge)
- **#10**: Anti-anchoring +25.7% (feature importance ≠ causality)
- **#13**: Weather arbitrage (completely untested)
- **#14**: Multi-model ensemble (skeleton code only)
- **#17**: 42 research prompts (implementation detail, not marketing)
- **#18**: Agentic RAG, market-making (vaporware)
- **#19**: Veteran charity (wait until profits exist)

---

## KEY RISK THEMES

### Backtest/Live Gap (CRITICAL)
- All RED claims assume backtests = future performance
- Live paper trading: 2 cycles, 17 trades, $0 realized P&L
- Statistically: need 50+ resolved markets to validate any claim
- **Risk**: Current live results don't confirm backtest assumptions

### Edge Decay (HIGH)
- Favorite-longshot bias is well-known (not proprietary)
- Competitive intelligence: OpenClaw $1.7M, Fredi9999 $16.62M
- As edge becomes known, markets price it in faster
- **Risk**: Win rate drops as competition adopts similar strategies

### Overfitting (CRITICAL)
- Calibration data used for both fitting AND evaluation (same 2024 data)
- Category routing: 70.2% NO-bias win rate suggests cherry-picking strong category
- Anti-anchoring feature: 25.7% improvement on same data used for training
- **Risk**: Generalization to 2025-2026 likely weaker than reported

### Simulation vs Reality (HIGH)
- Monte Carlo: 0% ruin assumes market liquidity always exists
- Kelly fraction: assumes consistent win rate (it won't be)
- Midpoint pricing: real Polymarket trades have 2-5% spread
- **Risk**: ARR projections are fiction; expected spread slippage alone erodes 50%+ of simulated edge

### Fee & Slippage Erosion (MEDIUM-HIGH)
- Polymarket is adding trading fees (announcement pending)
- Typical spread: 2-5% per side for small trades
- At current trade sizes ($5-50), slippage = $0.10-2.50 per trade
- **Risk**: Profitability disappears at scale if fees introduced

### Platform Risk (MEDIUM)
- Polymarket is only platform (concentrated risk)
- CFTC regulatory scrutiny increasing on prediction markets
- Polymarket may restrict US traders (jurisdiction risk)
- **Risk**: Platform shutdown = strategy dead

---

## WHAT WE'RE HONEST ABOUT

✓ We don't know if this works at scale (2 cycles is too small)
✓ Backtests can overfit (we used same data for fitting and testing)
✓ Edge may decay as competition adopts similar approaches
✓ We haven't made real profits yet (paper trading only)
✓ Monte Carlo outputs are only as good as input assumptions
✓ Leverage amplifies losses as well as gains
✓ Single platform creates concentration risk
✓ Regulatory environment is uncertain
✓ We're funding live tests with seed capital (~$1,000/week)

---

## NEXT MILESTONES FOR EVIDENCE

**To upgrade YELLOW claims to GREEN:**
1. **Win rate validation**: 50+ resolved markets in paper trading (current: 0 resolved)
2. **Live profitability**: $1,000+ realized P&L over 6 months (current: $0)
3. **Slippage model**: Trade with realistic spreads, measure actual execution costs
4. **Out-of-distribution test**: Run 2025 markets with model trained only on 2023-2024 data

**To claim any ARR projection:**
1. Establish baseline: 100+ consecutive trades at consistent win rate
2. Test at 10x current capital without strategy breaking down
3. Measure actual slippage and fees, not theoretical

**To claim structural edge:**
1. Show edge persists after competitors know about favorite-longshot bias
2. Demonstrate edge in new categories or market types

---

## COMMUNICATION RULES

**NEVER say:**
- "68.5% win rate" without "in historical backtests"
- "0% ruin probability" without "according to Monte Carlo simulation"
- "+6,007% ARR" on homepage (belongs in appendix with full disclaimers)
- "Proprietary edge" (favorite-longshot bias is 60-year-old academic finding)

**OKAY to say:**
- "We've tested our model on 532 historical markets"
- "In paper trading with real money on Polymarket"
- "Early results: 17 trades placed, awaiting resolution"
- "We built 6 safety systems to prevent large losses"

**REQUIRED caveats:**
- All projections assume strategies work as backtested (they usually don't)
- Past performance ≠ future results (especially true at small sample sizes)
- This is seed-stage research, not an investment product
- We haven't generated profits yet
