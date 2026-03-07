# HOMEPAGE SAFE CLAIMS

## What We Built

### Core Infrastructure
**Claim**: "We have 42 automated research tasks that continuously improve our model"
- **Why it's safe**: This is factual—the prompt queue exists in codebase
- **Tone**: Emphasizes continuous improvement mindset
- **Caveat to include**: "Our research process is ongoing and improvements are validated before deployment"

**Claim**: "We built 6 safety systems to prevent large losses in automated trading"
- **Why it's safe**: All modules deployed and operational
- **What they do**: Max-loss cutoffs, position limits, circuit breakers, liquidity checks, drawdown floors, emergency shutdown
- **Caveat to include**: "These are guard rails for an early-stage strategy, not guarantees against loss"

**Claim**: "Paper trading on Polymarket with real money"
- **Why it's safe**: 2 cycles completed; 17 actual trades with $68 deployed
- **Tone**: Shows we put our money where our mouth is
- **Caveat to include**: "Early stage—no markets have resolved yet, so no P&L data to report"

### Funding & Commitment
**Claim**: "Seed-funded with ~$1,000/week reinvested into live tests"
- **Why it's safe**: Bank records verify this
- **Tone**: Shows we're serious, not just hypothetical
- **Caveat to include**: "We're using seed capital to build proof of concept, not promising returns"

**Claim**: "We commit to donating future profits to veteran suicide prevention"
- **Why it's safe**: This is our stated mission
- **Caveat to include**: "We haven't generated profits yet—this commitment applies once/if we do"

---

## What the Backtests Show

### Market Coverage
**Claim**: "We've tested our model on 532 different prediction markets"
- **Why it's safe**: Defensible—that's our category database
- **What to emphasize**: Breadth of testing across different market types
- **Caveat to include**: "These were historical markets; backtests don't guarantee future performance"

### Directional Performance
**Claim**: "Our model performed better on markets where the prediction was 'No'"
- **Why it's safe**: Empirically true in 2024 data (70.2% win rate on NO trades)
- **Academic context**: "This aligns with well-documented research showing underdogs are systematically underpriced"
- **Caveat to include**: "Past market patterns don't guarantee future accuracy, especially as other traders learn the same pattern"

### Model Improvements
**Claim**: "We use statistical calibration to improve forecast accuracy"
- **Why it's safe**: Platt scaling is standard ML technique
- **What NOT to say**: "Improves from 0.239 to 0.2451 in Brier score" (barely beats random)
- **What to say instead**: "We use established statistical methods to align predicted probabilities with actual outcomes"
- **Caveat to include**: "Calibration is validated on test data, but small sample sizes mean future performance may differ"

### Category-Specific Insights
**Claim**: "We've identified that certain prediction market categories have stronger historical accuracy"
- **Why it's safe**: True—some categories performed better than others
- **What NOT to say**: Specific percentages without mentioning sample size
- **What to say instead**: "Routing trades toward historically stronger categories improved overall performance in backtests"
- **Caveat to include**: "Category characteristics may shift over time; we monitor performance continuously"

---

## What We're Doing Next

### Near-Term (Next 3 Months)
**Claim**: "Continuing paper trading to validate model performance with real market data"
- **Why it's safe**: This is our actual plan
- **Tone**: Transparent about needing more evidence
- **What to emphasize**: Rigorous validation before scaling

**Claim**: "Building more granular slippage modeling to estimate real execution costs"
- **Why it's safe**: Important next step; shows we know about a major gap
- **Caveat to include**: "Current backtests assume midpoint pricing; real trading has spreads of 2-5%"

### Medium-Term (3-12 Months)
**Claim**: "Expanding to additional prediction market platforms for diversification"
- **Why it's safe**: Reduces single-platform risk; this is sensible risk management
- **Caveat to include**: "Platform availability and regulations are evolving; we'll adapt as landscape changes"

**Claim**: "Incorporating weather data to improve forecasts on weather-sensitive categories"
- **Why it's safe**: This is planned; NOAA data available
- **What NOT to say**: "Multi-model ensemble improves accuracy" (skeleton code only, unvalidated)
- **What to say instead**: "Adding alternative data sources to expand our information advantage"
- **Caveat to include**: "New data sources need careful validation before incorporation into live trading"

### Longer-Term (12+ Months)
**Claim**: "Research into agentic systems for continuous market research and hypothesis testing"
- **Why it's safe**: This is on our roadmap
- **Caveat to include**: "This is exploratory research; no timeline or certainty of success"

---

## SECTION ORGANIZATION FOR HOMEPAGE

### "Our Approach" Section
- 532 markets backtested
- 6 safety systems
- Continuous research (42 prompts)
- Statistical calibration methods

### "Early Results" Section
- Paper trading with real money
- 17 trades deployed
- Awaiting market resolution
- Zero profits to date (transparency)

### "Commitment & Risk" Section
- Seed-funded operation
- $1,000/week reinvestment
- Future veteran charity commitment
- We know backtests can overfit (honesty)

### "Backtests Show" Section
- Strong performance on underdog ("No") predictions
- Category-specific advantages
- Better when routing by category strength
- Important caveat: historical ≠ future

### "What's Next" Section
- Live validation priority
- Slippage & fee modeling
- Multi-platform expansion
- Alternative data integration

---

## CAVEATS THAT MUST APPEAR

These should be placed visually near relevant claims (not buried):

1. **On any win rate or accuracy number**:
   "These results are from historical backtests and may not predict future performance."

2. **On any ARR or profitability claim**:
   "We have not generated profits yet. Paper trading is underway with early-stage results."

3. **On any "edge" claim**:
   "Markets are competitive and prices may move against us. Our advantages may erode over time."

4. **On Polymarket specifically**:
   "Our strategy depends entirely on one platform. Platform changes, regulatory shifts, or fees could significantly impact viability."

5. **On Monte Carlo or simulations**:
   "Simulations are only as good as their assumptions. Real market conditions may differ significantly."

---

## EXAMPLES OF GOOD HOMEPAGE LANGUAGE

**✓ GOOD**:
"We've tested our model on 532 historical prediction markets and identified patterns that outperformed random guessing in backtests. We're now validating these patterns with real money on Polymarket. Early paper trading is underway—we've placed 17 trades and are waiting for market resolution before drawing conclusions."

**✗ BAD**:
"68.5% win rate. +6,007% projected ARR. 0% ruin probability. 20-year-old research team with $1.7M in funding."

**✓ GOOD**:
"Our model performs better on underdogs ('No' predictions), which aligns with 60 years of academic research showing these markets are mispriced. This is not proprietary—it's a known pattern. What's new is our systematic approach to capturing it at scale."

**✗ BAD**:
"We've discovered a proprietary edge in prediction markets worth billions."

**✓ GOOD**:
"Our safety systems include: max-loss cutoffs ($X per day), position limits (max $Y per trade), circuit breakers for volatility spikes, liquidity checks, and emergency shutdown. These guard rails are essential because strategies often behave differently in production than in backtests."

**✗ BAD**:
"0% ruin probability. We've eliminated downside risk."

---

## TONE GUIDELINES

- **Honest first**: Always admit what we don't know
- **Humble**: Acknowledge competition and market efficiency
- **Rigorous**: Show the work, not just conclusions
- **Transparent**: Lead with caveats on speculative claims
- **Grounded**: Use actual numbers (17 trades, $68, 2 cycles) not projections
- **Forward-looking**: Show roadmap without false certainty

---

## WHAT NOT TO CLAIM

❌ Any ROI or return projection (wait for 50+ resolved trades)
❌ "Proprietary edge" (favorite-longshot bias is academic knowledge)
❌ "0% risk" (all trading has risks)
❌ "Beat the market" (Polymarket is not "the market"; it's one illiquid niche)
❌ Specific accuracy percentages without "historical backtest" caveat
❌ Any feature that exists in code but isn't validated (weather, ensemble, agentic)
❌ ARR projections (belongs in investor deck with full disclaimers, not homepage)
❌ "AI is predicting the future" (we're making probabilistic bets on incomplete information)

---

## CHECKLIST FOR HOMEPAGE COPY

Before publishing any claim, ask:

- [ ] Is this fact verifiable? (bank records, code, backtest runner)
- [ ] Would we defend this on a podcast? (honest answer should be yes)
- [ ] Does it require a caveat? (if yes, is caveat prominent?)
- [ ] Could a skeptic legitimately attack this? (if yes, we're not being honest enough)
- [ ] Are we comparing apples to apples? (backtests vs live; simulation vs reality)
- [ ] Does this claim rest on assumptions that might break? (if yes, state them)
- [ ] Have we tested this in production? (if no, say so)
- [ ] Would we tell our moms this? (honesty test)
