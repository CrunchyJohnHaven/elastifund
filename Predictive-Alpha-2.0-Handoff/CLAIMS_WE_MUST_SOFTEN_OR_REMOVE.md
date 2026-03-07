# CLAIMS WE MUST SOFTEN OR REMOVE

## Critical (Remove Entirely or Reposition as Aspirational)

### 1. "+6,007% ARR (velocity-optimized)"
**Current form**: "Expected annualized return of +6,007% with full leverage and quarter-Kelly sizing"

**Why it's problematic**:
- Rest entirely on assumptions that violate reality (midpoint pricing, no slippage, consistent trade frequency)
- 6,007% implies you double your money 60 times per year (absurd on face value)
- Nobody trades at "full leverage" without blowing up
- This is snake oil language—10x returns promised based on backtests
- Would trigger instant regulatory scrutiny if placed on homepage

**What a skeptic will say**:
"If you have a +6,007% strategy, why are you trading with $68 and asking for $1,000/week?"

**What to do instead**:
**Option A (Aspiration)**: "Our research suggests potential for substantial returns at scale IF our backtests validate in live trading. Current early testing stage—we're focused on proof-of-concept, not returns projection."

**Option B (Honest)**: "We've modeled multiple scenarios ranging from +124% to +872% ARR under different leverage assumptions. These are theoretical; actual live returns may be significantly lower due to slippage, fees, and edge decay."

**Option C (Best)**: Remove it entirely. Stick with "We're researching prediction market trading. Early backtests are promising. No live profits yet."

---

### 2. "0% Ruin Probability (Monte Carlo 10K paths)"
**Current form**: "Monte Carlo simulation shows zero probability of account ruin over 12 months"

**Why it's problematic**:
- Monte Carlo is garbage-in-garbage-out
- Our assumptions: constant 68.5% win rate, $5-50 trade sizes, Kelly fraction sizing, no black swans
- Reality check: win rate will drift, fees will increase, correlation between trades isn't zero, platform could shut down
- "0%" is not a number—it means "we can't model what could kill us"
- This is false confidence at its most dangerous

**What a skeptic will say**:
"Your simulation shows 0% ruin because you didn't model the things that actually ruin traders"

**What to do instead**:
**Option A (Honest)**: "We stress-test our strategy with Monte Carlo simulations assuming multiple downside scenarios. Our base case shows drawdowns of X%, which we can stomach. Our safety systems monitor for tail risks."

**Option B (Best)**: Don't mention ruin probability at all. Instead: "We built drawdown limits and emergency cutoffs. Maximum historical drawdown in backtests was X%. Real trading may have larger swings."

---

### 3. "+124% to +872% ARR Range"
**Current form**: "Projected annualized returns range from +124% to +872% depending on leverage"

**Why it's problematic**:
- A 700% spread is meaningless—it tells readers "we don't know"
- This is cover-your-ass language
- +124% is already absurd (you'd quadruple your money in 3 years)
- +872% is... unhinged
- Nobody believes a range this wide is actual forecasting
- Reads like "we made up both numbers and split the difference"

**What a skeptic will say**:
"You listed a range so wide it proves you don't know what will happen"

**What to do instead**:
**Remove entirely**. Don't publish ranges. Either:
- Give one conservative estimate with full caveats, OR
- Say "We don't know what future returns will be; we're early stage"

---

### 4. "68.5% Calibrated Win Rate (Out-of-Sample)"
**Current form**: "Our model achieved a 68.5% win rate on out-of-sample 2024 test data"

**Why it's problematic**:
- Confidence level only 6/10 because:
  - Only one test period (2024)
  - Same data used for both calibration fitting AND final evaluation (data leakage)
  - 0 resolved trades in paper trading to validate
  - Win rate is sensitive to category mix and market selection
- "Out-of-sample" is true but misleading: you didn't use 2025 data (real out-of-sample)
- Implies we can predict the future to 68.5% accuracy (dangerous overconfidence)

**What a skeptic will say**:
"You're quoting in-sample test data. Test it on 2025 markets you've never seen. THAT would be impressive."

**What to do instead**:
**If mentioned at all**: "In historical backtests, our model showed 68.5% accuracy on 2024 markets (data we didn't train on directly). This is a useful benchmark but doesn't guarantee future performance. We'll report actual live trading accuracy once we have 50+ resolved markets."

**Better**: Don't cite a specific number. Instead: "Our backtests show the model performs better than random guessing. We're validating actual performance with live trading."

---

### 5. "70.2% NO Win Rate"
**Current form**: "Model correctly predicted 'No' outcomes 70.2% of the time"

**Why it's problematic**:
- This is the most dangerous claim in our portfolio
- Symptom of overfitting to one category
- We're extracting all the easy money from a known bias (favorite-longshot)
- As competition learns about this bias, it decays FAST
- Citing this number implies we think we own this strategy

**What a skeptic will say**:
"Congratulations, you discovered an academic paper from 1960. How long until everyone else does?"

**What to do instead**:
**Remove from marketing**: This belongs in research notebooks, not homepage
**If mentioned on deeper pages**: "Historical data shows 'No' predictions performed better. Academic research suggests markets systematically underprice underdogs. We've identified this pattern in Polymarket. As competition learns about it, this advantage may erode."

---

### 6. "Platt Scaling Improves Brier from 0.239 to 0.2451"
**Current form**: "Calibration improves forecast accuracy: Brier score 0.239 to 0.2451"

**Why it's problematic**:
- Brier score of 0.2451 is barely better than random (0.25)
- We're bragging about a 5-basis-point improvement
- This reads as "we are slightly less dumb than guessing"
- Nobody cares about 0.239 vs 0.2451 on a homepage

**What a skeptic will say**:
"Wait, you're showing off that your model barely beats random guessing?"

**What to do instead**:
**Remove entirely from marketing**: This is a technical detail
**If mentioned in research context**: "Calibration adjustment improved forecast accuracy slightly. Additional research needed to determine if improvement is statistically significant."

---

## Major (Soften with Caveats)

### 7. "Quarter-Kelly Outperforms Flat by +309%"
**Current form**: "Quarter-Kelly sizing produced 309% higher returns than equal-sizing in backtests"

**Why it's problematic**:
- This confuses "leverage amplification" with "edge"
- Kelly fraction isn't magic—it amplifies both wins AND losses
- Quarter-Kelly on a mediocre edge is still a mediocre edge, just with higher variance
- Real traders blow up using full Kelly; quarter-Kelly is safer but not a "strategy"
- Sounds like "we found magic," when it's really "we sized bets differently"

**What a skeptic will say**:
"So you leveraged up and made more money. That's not beating the market; that's using debt. What happens when you lose?"

**What to do instead**:
**Remove the "+309% comparison**. Instead:
"We use fractional-Kelly sizing to adjust bet size based on confidence. This increases position when we're most confident and decreases during uncertainty. [Caveat: Kelly sizing assumes accurate win rate estimates; real rates drift, so full Kelly is dangerous. We use quarter-Kelly for safety.]"

---

### 8. "Anti-Anchoring Increases Edge Divergence 25.7%"
**Current form**: "Our debiasing technique increases model differentiation by 25.7%"

**Why it's problematic**:
- This is feature importance on training data (not validation)
- Feature importance ≠ causal effect
- We trained on this data, then measured on the same data
- "Edge divergence" is jargon nobody understands
- Sounds impressive but is low-confidence (4/10)

**What a skeptic will say**:
"You measured a feature on the same data you trained it on. That's not surprising; of course it 'helps.' Test it on 2025 data."

**What to do instead**:
**Remove from marketing entirely**. This is a technical research finding, not a selling point.
**If mentioned in research context**: "Preliminary analysis suggests our debiasing approach may improve model separation. Needs validation on out-of-distribution data before drawing conclusions."

---

### 9. "Category Routing Improves Win Rate"
**Current form**: "Routing trades to best-performing categories increased overall win rate"

**Why it's problematic**:
- In backtests, every strategy looks better when you "route" to categories where it works
- This is a form of survivorship bias
- We haven't tested: does category strength persist? Can we predict it in advance?
- Live trading shows 17 trades across multiple categories (too small to validate routing)

**What a skeptic will say**:
"You looked at which categories did well, then said 'let's trade those.' Of course that works. Does it work if you pick them blind?"

**What to do instead**:
**Soften to**: "We allocate more capital to categories where our model has shown stronger historical performance. This is based on backtests; we're validating with live trading."

---

### 10. "Weather Arbitrage Structural Edge"
**Current form**: "Weather data integration provides structural advantage for event prediction"

**Why it's problematic**:
- Completely untested (confidence 2/10)
- We have NOAA data but haven't integrated it
- "Multi-model ensemble" doesn't exist (skeleton code only)
- Claiming "edge" on something you haven't built is vaporware talk
- Real reason we want weather data: it correlates with event outcomes; so does everyone else

**What a skeptic will say**:
"You're planning to use publicly available weather data? So is everyone else on Earth."

**What to do instead**:
**Remove "edge" language**. Instead:
"We're researching how to incorporate weather data into event forecasts. NOAA data is publicly available; the question is how to weight it relative to market prices. This is early research."

---

### 11. "Multi-Model Ensemble Improves Accuracy"
**Current form**: "Ensemble of multiple models produces better predictions than single model"

**Why it's problematic**:
- Skeleton code only (confidence 1/10)
- Hasn't been trained, validated, or tested
- No ensemble logic; just scaffolding
- Claiming "improvements" before you've built it is false marketing

**What a skeptic will say**:
"Show me the results. You haven't built it yet."

**What to do instead**:
**Remove from any claim about current capability**. Instead:
"We plan to combine multiple forecasting approaches for robustness. Research in progress."

---

### 12. "Agentic RAG, Market-Making, Cross-Platform"
**Current form**: "Building AI-driven research agents, market-making, and multi-exchange support"

**Why it's problematic**:
- Roadmap aspirations, not implemented features
- "Agentic RAG" is jargon nobody understands and we haven't coded
- Market-making is easy to describe, hard to execute (requires capital + liquidity)
- Cross-platform means Manifold Markets API (one extra illiquid venue)
- This is classic startup vaporware

**What a skeptic will say**:
"So... you don't have any of this yet?"

**What to do instead**:
**Remove from homepage entirely**. Put in "Roadmap" section:
"We're exploring: 1) Automated research iteration loops, 2) Liquidity provision on multiple platforms, 3) Expansion beyond Polymarket. Timeline and viability TBD."

---

## Minor (Clarify or Reframe)

### 13. "532 Markets Backtested"
**Current form**: "Tested on 532 historical markets"

**Why it's fine**: This is defensible and cool
**But add caveat**: "These were historical markets; backtests measure how well our approach worked on past data, not future performance"

---

### 14. "42 Research Dispatch Prompts"
**Current form**: "42 automated research tasks to continuously improve model"

**Why it's fine**: This is true and shows engineering effort
**But don't oversell**: This is infrastructure, not a product feature. Say "We've built 42 research tasks to iterate on model improvements" not "42 cutting-edge AI agents."

---

### 15. "6 Safety Systems"
**Current form**: "6 types of safety guard rails to prevent catastrophic loss"

**Why it's fine**: Actual implementation; deserves to be mentioned
**But add context**: "These are safeguards against extreme scenarios. They're not guarantees. They're guard rails for a strategy still in validation phase."

---

### 16. "Paper Trading with Real Money"
**Current form**: "We're putting real money on Polymarket ($68 deployed)"

**Why it's fine**: Honest, shows we believe in this
**Reframe slightly**: "We've deployed ~$68 of seed capital across 17 trades on Polymarket. This is real money we're willing to lose. We're waiting for market resolution before evaluating results."

---

## SUMMARY: WHAT TO KILL

| Claim | Action | Why |
|-------|--------|-----|
| +6,007% ARR | **KILL** | Snake oil math; violates every real-world assumption |
| 0% Ruin Probability | **KILL** | False confidence; Monte Carlo assumes away real risks |
| +124% to +872% Range | **KILL** | Meaningless; proves we don't know |
| 68.5% Win Rate | **SOFTEN** | Only if "in historical backtests on 2024 data" |
| 70.2% NO Win Rate | **KILL from marketing** | This is overfitting to one category; belongs in research notes |
| Platt Scaling Brier | **KILL** | Barely beats random; don't advertise mediocrity |
| Quarter-Kelly +309% | **KILL comparison** | Reframe as leverage/sizing, not edge |
| Anti-Anchoring 25.7% | **KILL** | Feature importance on same data used for training |
| Weather Arbitrage | **REMOVE "edge"** | Untested; public data doesn't give advantage |
| Multi-Model Ensemble | **KILL from current claims** | Doesn't exist yet |
| Agentic RAG, Market-Making | **KILL from marketing** | Vaporware; put on roadmap instead |
| Profits to Veterans | **SOFTEN** | "...once/if we generate profits" must be explicit |

---

## REWRITE TEMPLATE

When you encounter a claim that needs softening, use this format:

**OLD**: [Current claim as stated]

**PROBLEM**: [Why it's problematic—overfitting, unsupported, snake oil, etc.]

**NEW**: [Honest version that's still interesting]

**CAVEAT TO ADD**: [The sentence that salvages credibility]

---

Example applied to "+6,007% ARR":

**OLD**: "Projected ARR of +6,007% with velocity-optimized strategy"

**PROBLEM**: Rest on midpoint pricing + no slippage + consistent trade frequency. This is backtest fantasy.

**NEW**: "Early backtests suggest strong upside potential at scale. We're focused on proof-of-concept with real money first."

**CAVEAT**: "Projected returns are highly sensitive to assumptions about execution costs and market behavior. Actual results will likely differ significantly."

---

## PRESENTATION ORDER FOR STAKEHOLDERS

**Show in this order**:
1. EVIDENCE_LEDGER_MASTER (shows we did the analysis)
2. HOMEPAGE_SAFE_CLAIMS (here's what's actually defensible)
3. CLAIMS_WE_MUST_SOFTEN_OR_REMOVE (here's what we're cutting)
4. HONESTY_BOX_COPY (here's how we'll communicate it)

**Message**: "We'd rather be boring and credible than exciting and wrong."
