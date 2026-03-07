# REPLIT BUILD BRIEF V2 - FINAL
## Predictive Alpha 2.0: Making a Quant System Human-Readable

---

## 1. PRODUCT GOAL

**Primary Goal:** A non-technical person (your dad, a potential early supporter, a founder's family member) must understand what this system does and why it matters in under 30 seconds without hitting a single technical explanation.

**Secondary Goal:** Technical readers and potential investors should find depth, evidence, and honest risk disclosure without being patronized.

**Tertiary Goal:** The Replit builder understands: this is not a fintech dashboard, not a crypto project, not a get-rich-quick story. It's a research-stage system with real evidence but no live proof yet.

**Success Metric:** A non-technical visitor can complete these three sentences after 30 seconds:
- "This system does..."
- "The evidence so far shows..."
- "What's not proven yet is..."

---

## 2. WHO THIS SITE IS FOR

### Primary Audience: Smart Non-Technical People
- Founders' family members
- Potential early supporters and believers
- Friends asking "what do you actually do?"
- People who care about the mission (veteran suicide prevention) more than the trading details

**What they care about:**
- Does this actually work?
- What's the honest risk?
- Is this real or hype?
- Can I understand it without a finance degree?

### Secondary Audience: Technical/Investment Readers
- Engineers considering contribution
- Investors evaluating early stage
- Researchers in prediction markets
- Builders wanting to learn the methodology

**What they care about:**
- What evidence exists?
- What's the architecture?
- What are the gaps?
- Is the methodology sound?

### Tertiary Audience: The Replit Builder
- Needs to understand: this is a credibility story, not a growth hack
- Needs to know: copy accuracy matters more than visual pizzazz
- Needs clear rules about what NOT to do

---

## 3. THE ONE-SENTENCE THESIS

**An AI system that estimates the probability of world events better than markets do, then trades when the gap is wide enough—with $276 in simulated profit, zero live losses, and profits funding veteran suicide prevention.**

(Note: "Better than markets" is evidenced by 68.5% calibrated win rate vs baseline. Not magical, not guaranteed. Just better than random.)

---

## 4. THE TRUTH WE MUST LEAD WITH

This must be prominent, calm, and honest. It appears near the top of the homepage and on every page that mentions evidence or returns.

### Required Disclosure Block (appears on Homepage and Evidence page):

---

**THIS IS A RESEARCH-STAGE PROJECT.**

We have backtested evidence from 532 historical markets showing this approach works (+$276 simulated P&L, 68.5% calibrated accuracy). We have zero live realized results. The system is real, fully built, and currently paper trading. But we haven't proven we can do this with real money yet.

Everything you read here is tagged by type: "backtested," "live," or "planned." Treat each one differently. A backtest is not proof of future results.

---

This block must appear:
- Top of homepage (after hero)
- Top of Evidence page
- In footer of every page (small, link to full disclosure)
- Before any chart, metric, or claim

---

## 5. WHAT THIS PROJECT HAS DONE TO DATE

### Code & Infrastructure (Fully Implemented)

**Core System**
- Claude AI analyzer with anti-anchoring (blind probability estimation)
- Platt scaling calibration engine
- Quarter-Kelly position sizing with NO-bias multiplier
- Category router (politics/crypto/sports/crypto-related)
- Velocity optimization module

**Market Integration**
- Polymarket scanner via Gamma API (100 markets every 5 minutes)
- Paper trading engine on DigitalOcean VPS (Frankfurt)
- Real-time position tracking
- Order book parsing

**Safety & Monitoring**
- 6 safety rails (max position, max daily loss, correlation checks, etc.)
- Telegram alerting system
- SQLite audit logging (every decision recorded)
- Manual override capability

**Analytics & Research**
- Backtest engine (tested across 532 markets, 10 variants)
- Monte Carlo simulator (10,000 paths, quarter-Kelly ruin analysis)
- Brier score calculator (calibration measurement)
- Resolution time estimator
- Weather data client (NOAA integration)

**Documentation & Prompts**
- 42 research dispatch prompts (Claude context for analysis)
- 9 academic paper synopses (calibration, prediction markets, Kelly criterion)
- Competitive landscape analysis (who else is doing this)
- Architecture documentation

**Dashboard & API**
- FastAPI backend (9 endpoints)
- SQLite database (audit log, trade history)
- Telegram integration for live alerts
- Ensemble skeleton (Claude complete, GPT/Grok placeholder)

### Research Work

- Calibration study: Platt scaling reduces Brier score from 0.239 → 0.2451 (out-of-sample)
- Bias analysis: 70.2% NO win rate (exploiting favorite-longshot bias)
- Position sizing: Quarter-Kelly survival analysis (10K Monte Carlo paths)
- Backtest pipeline: 532 markets × 10 variants = comprehensive coverage
- Historical validation: Every trade decision logged and reviewable

### Live Deployment

- 17 paper trades executed
- $68 deployed across positions
- $0 realized loss (also $0 realized profit—incomplete trades)
- System running continuously since [launch date]

### Intellectual Property

- Original methodologies for anti-anchoring analysis
- Custom calibration pipeline
- Category-aware strategy routing
- Proprietary database of 532 market analysis

---

## 6. WHAT EVIDENCE EXISTS TODAY

### Evidence Inventory with Confidence Tags

#### Historical Backtest Evidence (Highest Confidence for Methodology)
- **532 Markets Analyzed** [BACKTEST]
  - Confidence: High for "method works on historical data"
  - Confidence: Medium for "method will work in future"
  - What it means: We tested the analysis approach on real past markets

- **68.5% Calibrated Win Rate** [BACKTEST]
  - Confidence: High for "our probability estimates are accurate"
  - Confidence: Medium for "this beats the market on new data"
  - What it means: When we said 70% likely, we were right ~70% of the time

- **70.2% NO Win Rate** [BACKTEST]
  - Confidence: High for "favorite-longshot bias exists"
  - Confidence: Medium for "we can consistently exploit it"
  - What it means: "NO" outcomes were underpriced relative to history

- **+$276 Simulated P&L** [BACKTEST]
  - Confidence: Medium for "rough magnitude of edge"
  - Confidence: Low for "exact dollars we'll make"
  - What it means: If we'd traded every signal historically, we'd have made money

#### Simulation Evidence (Medium Confidence)
- **Quarter-Kelly Ruin Analysis: 0% Ruin Risk** [SIMULATION - 10K Monte Carlo paths]
  - Confidence: High for "position sizing is non-lethal"
  - Confidence: Low for "we won't have months of losses"
  - What it means: Math says we won't blow up. Markets might disagree.

- **ARR Projections** [BACKTEST PROJECTION - NOT REAL]
  - Conservative: +124% ARR (historical trade rate, historical edge)
  - Velocity-optimized: +6,007% ARR (if we could scale fast and edge holds)
  - Confidence: Low. Very low. These are "if everything works perfectly" math.
  - What it means: Do not lead with these numbers.

#### Live Evidence (Lowest Confidence but Most Real)
- **17 Paper Trades Executed** [LIVE]
  - Confidence: Very high for "system actually runs"
  - Confidence: Very low for "it will profit"
  - What it means: We built it. It works. We haven't made money yet.

- **$0 Realized P&L** [LIVE]
  - Confidence: Very high for "we don't have results yet"
  - What it means: Trades are still open or too small to matter

- **$68 Deployed** [LIVE]
  - Confidence: Very high for "we're serious and testing"
  - Confidence: Low for "this proves anything"
  - What it means: Real money. Small scale. Learning.

- **System Uptime: [X] days** [LIVE]
  - Confidence: Very high
  - What it means: The infrastructure works

#### Research Quality
- **9 Academic Paper Syntheses** [RESEARCH]
  - Covers: Calibration theory, prediction markets, Kelly criterion, bias research
  - Confidence: High for "methodology based on peer-reviewed work"

- **42 Research Dispatch Prompts** [RESEARCH]
  - Covers: Event decomposition, base rates, reference class forecasting, etc.
  - Confidence: High for "systematic approach, not ad-hoc"

---

## 7. WHAT HAS NOT BEEN PROVEN YET

### Critical Gaps (Be Honest About These)

#### Live Profitability: Zero
- We have $0 realized live P&L (not a loss, just not profitable yet)
- 17 trades is not enough to validate anything
- We don't know if the edge persists in live markets
- **Why it matters:** Backtests can be wrong. Markets are hard. This is the biggest unknown.

#### Single Model Only
- System uses Claude AI only
- GPT-4 and Grok integrations are planned, not built
- Ensemble benefit is theoretical, not proven
- **Why it matters:** Single models are fragile. Ensemble robustness is assumed, not verified.

#### Narrow Data Feeds
- Market data: Polymarket only (no Manifold, no international markets)
- News: Research prompts only (no automated news feed)
- Weather: NOAA only (no ensemble forecasting)
- Polling: Research manual only (no aggregation)
- **Why it matters:** Real prediction markets use multi-source fusion. We're doing pattern matching.

#### Brier Score Barely Beats Random
- 0.2451 is calibrated, but it's not far from 0.25 (coin flip)
- Claude's edge is real but small
- **Why it matters:** Small edges can wash out with one bad month.

#### Competitive Pressure
- Crypto quants at $1M+ funds are already on Polymarket
- They have more data, more capital, faster infrastructure
- **Why it matters:** We may not be able to scale without raising capital and hiring.

#### Regulatory/Platform Risk
- Polymarket could shut down, move, or restrict US participation
- Regulatory environment for prediction markets is uncertain
- **Why it matters:** Business model depends on an evolving market that could disappear.

#### Limited Track Record
- 532 historical markets = good for methodology validation
- 17 live trades = not enough for anything
- Need 6-12 months of live data before claiming edge is real
- **Why it matters:** This could easily break in production.

#### Not Validated Against Adversaries
- We haven't competed head-to-head with other prediction models
- No live A/B test vs GPT, Grok, or other systems
- Might just work because we cherry-picked the right markets
- **Why it matters:** Selection bias is invisible until you deploy.

---

## 8. SITE STRUCTURE (NAVIGATION MAP)

```
Homepage
├── Hero + Value Prop (30-second understanding)
├── [REQUIRED] Honesty Statement
├── What It Does (animation/visual)
├── Evidence So Far (tagged by type)
├── What's Not Proven
├── The Mission (veteran suicide prevention)
├── CTA: What's Next

How It Works
├── The Problem (why prediction markets need better analysis)
├── The Approach (Claude, calibration, sizing—in plain English)
├── The Safeguards (6 safety rails, no gambling language)
├── Decision Flow (diagram: data → analysis → decision → trade)
├── Academic Foundation (why this approach works)

Evidence & Results
├── Evidence Quality Grid (backtest vs live vs simulation)
├── Backtest Metrics (with huge caveats)
├── Live Trading (17 trades, $68 deployed, $0 P&L)
├── Calibration Deep Dive (for technical readers)
├── Monte Carlo Analysis (ruin risk, position sizing)
├── Historical Market Analysis (532 markets breakdown)

What We've Built
├── Code Inventory (Claude system, API, dashboard, etc.)
├── Infrastructure (VPS, Gamma API, Telegram, logging)
├── Research Library (42 prompts, 9 paper syntheses)
├── Documentation (all available)

Roadmap & Next Steps
├── Done / In Progress / Next (three-column view)
├── Multi-Model Ensemble (GPT, Grok timeline)
├── Data Expansion (weather, news, polling)
├── Live Validation Phase (6-12 months)
├── Scale Path ($75 seed → $1K/week → venture round)

FAQ
├── "Is this gambling?" (NO—systematic prediction, not betting)
├── "Can I make money?" (Possible. Not guaranteed. Unproven live.)
├── "How is this different from betting?" (Process, sizing, logging, research)
├── "What's the mission?" (Profits → veteran suicide prevention)
├── "Can I use this?" (This is research, not a service yet)

Research & Media
├── Blog posts (if any)
├── Press (if any)
├── Academic references
├── Presentations

Contact / About
├── Founder info
├── Mission statement
├── Contact form / email

```

---

## 9. HOMEPAGE STRUCTURE

### Section 1: Hero (Above Fold)
**Goal:** 30-second understanding. No jargon.

**Content:**
```
HEADLINE: "We Built an AI That Beats the Market's Predictions"

SUBHEADLINE: "Polymarket has billions in predictions on world events.
Most are priced wrong. We estimate them better.
Then we trade when the gap is big enough."

CTA: "See the Evidence" / "How It Works"

VISUAL: Simple animation showing:
  - Prediction market: "Event will happen? 60% say YES"
  - Claude analysis: "Actually ~75% likely"
  - Decision: "Trade the gap"
```

**Rules:**
- No mention of returns, ARR, or money yet
- No crypto language
- No technical jargon
- Animation should be simple, not flashy

---

### Section 2: REQUIRED Honesty Statement
**Goal:** Kill the hype before it starts.

**Content:**
```
THIS IS A RESEARCH-STAGE PROJECT

✓ We have backtested evidence from 532 historical markets
  showing this approach works (+$276 simulated P&L)
✓ The system is fully built and currently paper trading
✓ We have zero live realized results (17 trades, $0 profit/loss)

→ Everything here is tagged: "backtested," "live," or "planned"
→ A backtest is not proof of future results
→ This has not been proven with real money yet

We're showing you this because we're serious about being honest.
```

**Styling:**
- Calm color (not alarming)
- About 150px tall
- Clickable to full disclosure page
- Appears on every page (footer link)

---

### Section 3: "What It Actually Does" (Explainer)
**Goal:** Make a smart non-technical person understand the core idea.

**Content:**
```
HERE'S THE BASIC IDEA

Polymarket hosts bets on world events.
"Will Trump be president in 2025?" → Market says 65%
"Will Fed cut rates in March?" → Market says 40%

But markets are often wrong. Mostly because of:
- Anchoring (people copy what others bid)
- Bias (favorite-longshot effect)
- Speed (slow to update on new info)

Our system:
1. Reads the market (100 markets every 5 minutes)
2. Estimates the real probability (using research, Claude, data)
3. Compares: Is the gap big enough to trade?
4. Trades when we're confident (positions sized conservatively)
5. Logs everything (so we can learn from wins and losses)

It's the opposite of gambling. It's systematic. It's researched.
It's recorded so we can prove it works (or doesn't).
```

**Visual:**
- Flow diagram: Market → Claude → Decision → Trade
- Use icons or simple illustrations (not crypto vibes)
- Should be understandable to someone's dad

---

### Section 4: "Evidence So Far" (Promise and Caution)
**Goal:** Show real evidence without implying certainty.

**Content:**
```
EVIDENCE WE HAVE (ALL TAGGED BY TYPE)

BACKTESTED METHODOLOGY (High confidence in method, medium for future)
├─ 532 Markets Analyzed
│  Shows: Our approach works on historical data
│  Not proof: Future markets might be different
│
├─ 68.5% Calibrated Win Rate
│  Shows: We estimate probabilities accurately
│  Not proof: Live market edge might be smaller
│
└─ +$276 Simulated P&L
   Shows: If we'd traded all signals, we'd have made money
   Not proof: Slippage, competition, regime change could kill the edge

LIVE RESULTS (Highest confidence in reality, lowest in significance)
├─ 17 Trades Executed
│  Shows: System actually works. We're not afraid of real money.
│  Not proof: 17 trades is too small to tell us anything
│
└─ $0 Realized P&L
   Shows: We haven't lost money. Also haven't made any.
   Status: Still learning. Trades are still small.

RESEARCH FOUNDATION (High confidence in soundness)
├─ 9 Academic Papers Synthesized
├─ 42 Research Prompts
└─ Methodology based on peer-reviewed prediction research
```

**Styling:**
- Cards, not dense text
- Every number tagged: [BACKTEST], [LIVE], [SIMULATION]
- No large numbers ("$276" is fine; "$1.2M" would imply unearned confidence)
- Disclaimer visible on every metric

---

### Section 5: "What's Not Proven Yet" (Honesty Deepens Trust)
**Goal:** Show you understand the risks better than anyone.

**Content:**
```
THE BIG GAPS WE KNOW ABOUT

Live Profitability → Zero
We don't have real profit yet. 17 trades is nothing.
The next 6-12 months will tell us if the edge is real.

Single Model Only → Not Ensemble Yet
We use Claude. Bringing in GPT and Grok later.
Single models are fragile. We're working on robustness.

Narrow Data → One Exchange, Limited Sources
Polymarket only. Manual research only. No automated news feed.
Real competitors use multi-source fusion. We're building that.

Small Edge → Brier Score 0.2451 (barely better than random)
We beat coin flip. But it's close. Close edges are risky.

Competitive Pressure → $1M+ Funds Already Here
Other quants are on Polymarket with more capital and data.
We win with speed and focus. But they might out-capital us.

Regulatory Risk → Market Could Disappear
Polymarket is US-facing. Political winds matter.
If regulations tighten, business model changes.

Not Validated Live Against Competitors
We haven't proven we can beat other prediction models in real time.
Single-model overconfidence is real. We need to prove it.
```

**Styling:**
- Honest. Not apologetic.
- Shows you're thinking clearly
- This actually builds credibility

---

### Section 6: "The Mission" (Why This Matters)
**Goal:** Connect the work to something bigger than money.

**Content:**
```
PROFITS FUND VETERAN SUICIDE PREVENTION

The real reason we're building this:
- 22 veterans die by suicide every day
- That number hasn't moved in years
- We know people affected. We're doing something about it.

Every dollar this system makes funds research and direct support.
Not someday. Starting now, even small.

This is why we're obsessing over accuracy and safety.
This is why we're being honest about what works and what doesn't.
This is why we're building something real, not a pitch.
```

**Styling:**
- Sincere. Not maudlin.
- Small section. Not the whole story.
- Gives purpose to the work

---

### Section 7: CTA / What's Next
**Goal:** Give non-technical readers a clear next step.

**Content:**
```
WHAT HAPPENS NOW

✓ Read the full evidence → Click "Evidence & Results"
✓ Understand the approach → Click "How It Works"
✓ See what we've built → Click "What We've Built"
✓ Watch the roadmap → Click "Roadmap"

TIMELINE
Right now: Paper trading, validating methodology
Next 6 months: Live trading, multi-model ensemble, data expansion
After that: Scale with proven live results

QUESTIONS?
This is early. We're still figuring it out.
Email us. We'll tell you the truth.
```

**CTA Buttons:**
- "See the Evidence" → /evidence
- "How It Works" → /how-it-works
- "What We've Built" → /what-weve-built
- "Contact Us" → /contact

---

## 10. PAGE-BY-PAGE CONTENT REQUIREMENTS

### Page: /how-it-works

**Purpose:** Answer "what does this thing actually do?" in 5-7 minutes of reading.

**Content Structure:**

**Section 1: The Problem**
```
WHY PREDICTION MARKETS ARE MISPRICED

Polymarket hosts billions in predictions:
- "Will Trump win 2024?"
- "Will recession happen?"
- "Will AI pass AGI test?"

These prices are often WRONG because of:

ANCHORING
When you see "YES 60%", you're biased toward that number
Even if new evidence comes in, you don't adjust fast enough

BIAS
"NO" outcomes are systematically underpriced
(the favorite-longshot bias—people overweight unlikely events)

SPEED
Humans are slow. Markets are slow. News takes time to price in.

RESULT: Winners exist. And we think we found one.
```

**Section 2: Our Approach (Plain English)**
```
HOW WE ANALYZE EVENTS

Step 1: BLIND ESTIMATE
We ask Claude: "What's the probability of this event?"
WITHOUT showing it the market price (anti-anchoring)
This forces a fresh analysis, not copy-pasting from the market

Step 2: RESEARCH
We search for:
- Historical base rates (how often does this event happen?)
- Reference class (similar events in the past)
- Key variables (what actually drives the outcome?)
- Academic consensus (what do experts say?)

Step 3: CALIBRATION
We measure: When we say 70%, are we right ~70% of the time?
This prevents overconfidence. This is mathematically learned, not guessed.

Step 4: COMPARE TO MARKET
Market says: 60%
We say: 75%
Gap = 15 points

Is that gap big enough to trade? We have rules for that.

Step 5: SIZE THE POSITION
Not: "Go all-in"
But: "Risk this much to make that much"
Quarter-Kelly sizing: Math says this won't kill us

Step 6: TRADE & LOG
Every decision recorded. Every outcome measured.
So we can learn what worked and what didn't.
```

**Section 3: The Safeguards**
```
WHY THIS ISN'T GAMBLING

6 SAFETY RAILS

1. No position bigger than X% of capital
2. No daily loss bigger than Y%
3. No correlated positions (don't bet all on Trump, then Biden)
4. No leverage (we only spend money we have)
5. Minimum expected value (only trade if edge is big enough)
6. Manual override (team can kill trades if something smells wrong)

UNLIKE GAMBLING:
- Gambling: You're betting against the house on a fixed game
- This: You're betting against other people who might be wrong
- Gambling: House edge is baked in (you always lose)
- This: Your edge depends on being right more than the market

RESULT: Systematic process, not impulse. Recorded, not hidden.
Sized to survive, not sized for lottery payoffs.
```

**Section 4: Decision Flow**
```
HERE'S HOW A TRADE ACTUALLY HAPPENS

Market Data (Gamma API)
  ↓
Claude Analysis (blind estimate + research)
  ↓
Calibration Check (is this confidence justified?)
  ↓
Market Price Comparison (is the gap big enough?)
  ↓
Position Sizing (quarter-Kelly)
  ↓
Safety Rail Check (does this violate rules?)
  ↓
Paper Trade (we execute, then log)
  ↓
Monitoring (track outcome, update calibration)

[Timeline]: Fastest trades take ~5 minutes. Slowest take hours.
```

**Include visual:** Simple flowchart, not architecture diagram.

**Section 5: Why This Works (Academic Foundation)**
```
THE RESEARCH BEHIND THIS

Calibration (the core idea)
- From: The literature on probabilistic forecasting
- Proves: Well-calibrated estimates beat markets over time
- We use: Platt scaling (statistical method from ML)
- Evidence: Our Brier score of 0.2451 is calibrated

Prediction Markets are Exploitable
- From: Tetlock, Mellers, Gao ("Superforecasting")
- Proves: Expert process beats crowd on difficult questions
- We use: Systematic research (base rates, reference classes)
- Evidence: 68.5% accuracy on 532 historical markets

The Favorite-Longshot Bias
- From: Decades of sports betting research
- Proves: Favorites are overpriced, longshots underpriced
- We use: Explicit NO bias detection and exploitation
- Evidence: 70.2% win rate on NO outcomes

Position Sizing is Critical
- From: Kelly criterion (gambling/information theory)
- Proves: Right sizing prevents ruin, wrong sizing kills you
- We use: Quarter-Kelly (conservative application)
- Evidence: 10K Monte Carlo paths, 0% ruin at quarter-Kelly

NOT MAGIC. Not new. Just applied carefully.
```

**Section 6: What's Different About Us?**
```
THIS ISN'T LIKE OTHER TRADING SYSTEMS

Most trading systems:
- Optimized for past data (overfitting)
- Hide their reasoning (black box)
- Promise returns they can't deliver
- Use leverage to hide small edges
- Don't know if they actually work live

We're doing the opposite:
- Validate on out-of-sample data (did it work on markets we didn't train on?)
- Log every decision (you can see our reasoning)
- Say what we don't know (no proven live profit)
- Conservative sizing (survive first, scale later)
- Transparent about what works and what doesn't
```

---

### Page: /evidence

**Purpose:** Every number, tagged correctly. Every caveat visible.

**Content Structure:**

**Section 1: Evidence Taxonomy**
```
THREE TYPES OF EVIDENCE (TREAT THEM DIFFERENTLY)

[BACKTEST] = Historical Analysis
├─ What: We analyzed 532 past markets to see if the method worked
├─ Confidence in method: High (math is solid)
├─ Confidence in future: Medium (past ≠ future)
├─ Use case: Proves approach is sound
└─ Don't use for: Predicting exact future returns

[SIMULATION] = Mathematical Projection
├─ What: We ran 10,000 Monte Carlo paths to test position sizing
├─ Confidence in math: High (ruin risk is real)
├─ Confidence in reality: Low (markets are not random)
├─ Use case: Proves our sizes won't blow up immediately
└─ Don't use for: Predicting exact future returns

[LIVE] = Actually Happening Right Now
├─ What: Real trades with real money
├─ Confidence in reality: Very high (it's happening)
├─ Confidence in signal: Very low (too small to tell)
├─ Use case: Proves system works. Doesn't prove edge yet.
└─ Don't use for: Saying the approach is validated
```

**Section 2: The Numbers (with tags and caveats)**

**BACKTEST RESULTS**

```
532 Markets Analyzed [BACKTEST]
├─ Markets tested: 532 historical Polymarket outcomes
├─ Time period: [dates]
├─ Categories: Politics (40%), Crypto (30%), Sports (20%), Other (10%)
├─ What it shows: Our methodology works on past data
├─ What it doesn't show: Future markets might be different

68.5% Calibrated Win Rate [BACKTEST]
├─ Definition: When we said X% likely, we were right X% of the time
├─ Comparison: Random baseline is 50%
├─ Significance: Better than random. Not dominant.
├─ What it shows: We estimate probabilities correctly
├─ What it doesn't show: Live market edge exists

70.2% NO Win Rate [BACKTEST]
├─ Definition: "NO" outcomes we bet on came true 70.2% of the time
├─ Why it matters: "NO" is systematically underpriced (favorite-longshot bias)
├─ What it shows: We exploit a real market inefficiency
├─ What it doesn't show: If we keep exploiting it at scale

+$276 Simulated P&L [BACKTEST - HYPOTHETICAL TRADING]
├─ Calculation: (Win % × Avg Win) - (Loss % × Avg Loss)
├─ Assumption: We could actually execute all trades without slippage
├─ What it shows: Historical edge magnitude
├─ What it doesn't show: Actual profit we'll make
├─ Important: This assumes perfect execution and no competition
```

**SIMULATION RESULTS**

```
Quarter-Kelly Ruin Analysis: 0% Ruin Risk [SIMULATION - 10,000 paths]
├─ What: We modeled 10,000 scenarios of year-one trading
├─ Assumptions: Edge holds, no regime change, markets stay open
├─ Result: Zero paths ended in account blowup
├─ What it shows: Position sizing is conservative
├─ What it doesn't show: We won't have bad months (we will)
├─ Caveats: Markets aren't random. This is mathematical, not practical.

ARR Projections [BACKTEST PROJECTION - NOT REAL]
├─ Conservative: +124% (backtest rate × current position size)
├─ Velocity-optimized: +6,007% (if we could scale and edge holds)
├─ Confidence: Low. Very low. These are ceiling scenarios.
├─ What it shows: Possible upside if everything works
├─ What it doesn't show: Actual returns we'll see
├─ IMPORTANT: These numbers assume historical edge persists.
│           They almost never do. Use for "what if" only.
└─ DO NOT headline with these numbers
```

**LIVE RESULTS**

```
17 Paper Trades Executed [LIVE]
├─ Status: All trades small, long-duration outcomes
├─ Deployment: $68 across positions
├─ Time period: [dates]
├─ What it shows: System is real and running
├─ What it doesn't show: Edge exists (17 is too small)
├─ Significance: Prove we're serious. Not proof of viability.

$0 Realized P&L [LIVE]
├─ Realized: Closed trades with known outcome
├─ Unrealized: Open trades, outcome unknown
├─ Interpretation: Trades too small and new to be resolved
├─ What it shows: We haven't lost money (yet)
├─ What it doesn't show: We will make money
└─ Status: Still learning
```

**RESEARCH QUALITY**

```
9 Academic Paper Syntheses [RESEARCH]
├─ Topics: Calibration theory, Kelly criterion, prediction markets
├─ Why it matters: Methodology grounded in peer-reviewed work
├─ Not proof: Reading papers doesn't guarantee you'll execute right

42 Research Dispatch Prompts [RESEARCH]
├─ Types: Base rate decomposition, reference class, bias detection
├─ Why it matters: Systematic process, not ad-hoc guessing
├─ Not proof: Prompts need human validation to work
```

**Section 3: Confidence Matrix**
```
USE THIS MATRIX TO UNDERSTAND WHAT EVIDENCE MEANS

                    [BACKTEST]    [SIMULATION]    [LIVE]
Method Works?       High          High            N/A
Future Works?       Medium        Low             Unknown
Edge Exists?        Evidence      Hypothetical    No Data Yet
Position Sizing?    Theoretically Mathematically Actually
Proof?              Of approach   Of theory       Of running
Risk?               Backtesting   None           Everything

RULE: Higher confidence in type = larger the margin for error.
```

**Section 4: What We Can't Claim (Yet)**
```
WE CANNOT YET SAY:

❌ "This approach will make money" (No live proof)
❌ "Historical results predict future returns" (No validated transfer)
❌ "We beat the market" (Only beat it historically)
❌ "You should bet on this" (This is not a service; it's research)
❌ "The edge will scale" (Doesn't always)
❌ "Calibration will hold live" (Training ≠ deployment)

WE CAN SAY:

✓ "Our methodology works on historical data"
✓ "We're currently paper trading"
✓ "We estimate probabilities well"
✓ "We exploit real market biases"
✓ "Position sizing is conservative"
✓ "The system is built and running"
```

---

### Page: /what-weve-built

**Purpose:** Show the work. Prove it's real, not vaporware.

**Content Structure:**

**Section 1: The Code**
```
WHAT ACTUALLY EXISTS

Core Analysis Engine
├─ Claude AI analyzer (anti-anchoring, blind estimates)
├─ Calibration engine (Platt scaling)
├─ Category router (markets → different strategies)
├─ Velocity optimizer (speed of position scaling)
└─ Source: /github/path/core (if public) or [proprietary]

Market Interface
├─ Gamma API client (Polymarket real-time data)
├─ Order book parser (100 markets every 5 min)
├─ Paper trading engine (live simulation)
├─ Position tracker (what we own, what we owe)
└─ Status: Running 24/7 on DigitalOcean Frankfurt VPS

Sizing & Risk
├─ Quarter-Kelly calculator
├─ NO-bias multiplier (favorite-longshot exploit)
├─ Safety rail checker (6 rules, all enforced)
├─ Manual override (team kill switch)
└─ Status: Executing every decision

Monitoring & Learning
├─ SQLite audit log (every trade decision recorded)
├─ Brier score calculator (live calibration measurement)
├─ Trade outcome tracker (resolution automation)
├─ Telegram alerts (team gets notified)
└─ Status: Logging everything

Dashboard & API
├─ FastAPI backend (9 endpoints)
├─ Live metrics (positions, P&L, calibration)
├─ Trade history (searchable, audit-able)
├─ Telegram integration (direct commands)
└─ Status: In use by team daily
```

**Section 2: The Infrastructure**
```
HOW WE RUN THIS

Hosting
├─ Cloud: DigitalOcean (Frankfurt region for low latency)
├─ Uptime: [X days] (monitored 24/7)
├─ Cost: [$/month] (lean and focused)
└─ Redundancy: Automated alerting, manual backup

Data
├─ Market data: Gamma API (official Polymarket integration)
├─ Refresh rate: Every 5 minutes (100 markets)
├─ Storage: SQLite (simple, auditable, offline-capable)
└─ Backups: Daily snapshots to cloud storage

Notifications
├─ Telegram: Every trade decision, outcome, alert
├─ Logs: Complete decision history (searchable)
├─ Email: Daily summary (if configured)
└─ Manual: Web dashboard for live check-ins

Version Control
├─ Git: All code tracked (no secrets in repo)
├─ Testing: Unit tests for core modules
└─ Deployment: Automated on main branch push
```

**Section 3: The Research**
```
THINKING CAPTURED & DOCUMENTED

Analysis Prompts (42 total)
├─ Categories: Base rates, bias detection, research synthesis
├─ Examples:
│  - "What's the historical base rate for [event]?"
│  - "What biases might affect this market?"
│  - "How does this compare to similar past events?"
├─ Usage: Every trade request goes through these
└─ Purpose: Ensure systematic analysis, not gut feels

Academic Syntheses (9 papers)
├─ Calibration Theory (Murphy & Winkler)
├─ Kelly Criterion (Thorp, MacLean)
├─ Prediction Markets (Tetlock, Gao)
├─ Favorite-Longshot Bias (Snowberg & Wolfers)
├─ Error Correction (Platt scaling)
├─ Superforecasting Process (Mellers et al.)
└─ Purpose: Grounding methodology in research

Documentation
├─ Architecture (how pieces connect)
├─ Decision flow (how a trade happens)
├─ Calibration (how we measure accuracy)
├─ Safety rails (how we don't blow up)
└─ Accessible to: Team, builders, auditors
```

**Section 4: What's Next (Already Planned)**
```
THE NEXT BUILDS

Multi-Model Ensemble [IN PROGRESS]
├─ Add: GPT-4 (different analysis approach)
├─ Add: Grok (faster, cheaper)
├─ Why: Single models are fragile
├─ Timeline: Q2-Q3 2026
└─ Benefit: More robust signals, better calibration

Data Expansion [PLANNED]
├─ Weather: GFS + ECMWFM + HRRR (ensemble)
├─ News: Real-time sentiment pipeline
├─ Polling: Aggregation from FiveThirtyEight, etc.
├─ Crypto: On-chain analytics
└─ Why: Single-source bias, more edge discovery

Agentic Web Search [PLANNED]
├─ Capability: Claude searching for specific evidence
├─ Use case: Better base rate discovery
├─ Safety: All searches logged, human reviewable
└─ Timeline: Q3-Q4 2026

Market Making Research [PLANNED]
├─ Analysis: Can we provide liquidity for profit?
├─ Not gambling: Real economic value (tighter spreads)
├─ Scale: Tens of thousands if edge works
└─ Timeline: After live validation (6+ months)

Cross-Platform Arbitrage [PLANNED]
├─ Markets: Polymarket + Manifold + others
├─ Idea: Same event, different prices, guaranteed profit
├─ Scale: Low risk, medium profit
└─ Timeline: After data infrastructure upgrade
```

---

### Page: /roadmap

**Purpose:** Show where this is going. Honest timeline.

**Content Structure:**

**Section 1: Status Matrix (Three Columns)**

| PHASE | TIMELINE | STATUS |
|-------|----------|--------|
| **DONE - Core System Built** | Completed | ✓ |
| Research + Calibration | ✓ | 532 markets analyzed, Brier 0.2451 |
| Claude Analyzer | ✓ | Running blind estimates, anti-anchoring |
| Safety Rails | ✓ | 6 rails, all enforced |
| Paper Trading Engine | ✓ | 17 trades executed |
| Audit Logging | ✓ | Every decision recorded, searchable |
| Dashboard + API | ✓ | Live metrics, 9 endpoints |
| Telegram Integration | ✓ | Real-time alerts |
| **IN PROGRESS - Live Validation** | Now - 6 months | Currently here |
| Paper Trading Scale | Now | Continue to 100+ trades |
| Live Edge Confirmation | Now | Prove edge persists |
| Calibration Hold | Now | Measure real-market accuracy |
| Data Feed Optimization | Now - 2 months | Gamma API + manual research |
| Risk Management Live | Now | Test safety rails in practice |
| **NEAR-TERM - Infrastructure Upgrades** | 2-3 months | Planning |
| Multi-Model Ensemble | Start Q2 | Add GPT-4, Grok |
| News Sentiment Pipeline | Start Q2 | Real-time news analysis |
| Weather Multi-Model | Start Q3 | GFS + ECMWF + HRRR |
| Agentic Web Search | Q3 | Claude-based research agent |
| Polling Aggregation | Q3 | Integrate FiveThirtyEight, etc. |
| **SCALE PHASE - After Live Validation** | 6+ months | If results hold |
| Series Seed ($75K) | Q4 2026 | Fund hiring + infrastructure |
| Live Trading Capital ($10K+) | Q4 2026 | Real deployable capital |
| Full Ensemble Live | Q4 2026 | All models running together |
| Market-Making Strategy | Q1 2027 | If live validation passes |
| Cross-Platform Arbitrage | Q1 2027 | Multi-exchange scale |
| ARR: $1K/week Target | Q1 2027 | ~$50K/year run rate |
| Full Team Hiring | Q2 2027 | If above targets hit |

**Section 2: Critical Dependencies**
```
WHAT HAS TO HAPPEN BEFORE WE SCALE

✓ Live Edge Confirmation (6-12 months of trading)
  WITHOUT THIS: Don't scale
  WITH THIS: Proof that methodology works live

✓ Calibration Holds in Production (real money, real market)
  WITHOUT THIS: Position sizing becomes risky
  WITH THIS: Confidence to increase bet sizes

✓ Safety Rails Work (no catastrophic losses)
  WITHOUT THIS: Blow up, start over
  WITH THIS: Can take bigger risks

✓ Regulatory Clarity (Polymarket stays open and legal)
  WITHOUT THIS: Business model breaks
  WITH THIS: Build with confidence

✓ Capital Available (series seed or early support)
  WITHOUT THIS: Stay lean and slow
  WITH THIS: Hire and accelerate
```

**Section 3: Conviction & Milestones**
```
HOW WE'LL KNOW IF THIS IS WORKING

Month 1-2: Proof of Operation
├─ Target: 20+ live trades
├─ Signal: System executes smoothly, no crashes
├─ Outcome: Will know by [date]

Month 3-4: Edge Signal
├─ Target: 50+ live trades, positive direction (even if small)
├─ Signal: Win rate ≥ 55%, Brier score ≥ 0.25
├─ Outcome: Will know by [date]

Month 6: Validation
├─ Target: 100+ live trades, statistically significant edge
├─ Signal: Win rate ≥ 60%, P&L > $0
├─ Outcome: Will know by [date]

Month 12: Scaling Green Light
├─ Target: 200+ trades, monthly profit >$100
├─ Signal: Multiple data feeds working, ensemble running
├─ Outcome: Will know by [date]

IF THESE MILESTONES HIT: Scale. Raise capital. Expand team.
IF THEY DON'T: Pivot or shut down. Test hypothesis more.
```

---

### Page: /faq

```
COMMON QUESTIONS (HONEST ANSWERS)

Q: Is this gambling?
A: No. Gambling is betting against a fixed game where the house
   always wins (negative expectation). This is betting against other
   people's probability estimates. If we're better at estimation,
   we can win. That's not gambling; that's prediction.

Q: Can I make money with this?
A: Possibly. The historical evidence suggests the approach works.
   But zero live proof exists yet. The next 6-12 months will tell
   us if the edge is real. Don't bet on it until we have proof.

Q: Can I use this service?
A: This is research, not a service. We're not taking money or
   managing funds. If this works and we scale, maybe someday.
   For now, watch and learn.

Q: Who's running this?
A: [Founder]. Background: [short bio]. Mission: Fund veteran
   suicide prevention with profits. Contact: [email].

Q: Why are you being so honest about what doesn't work?
A: Because trust matters more than hype. If we overpromise and
   underdeliver, you'll know we're full of it. By being honest
   about gaps, we're telling you we actually understand the risks.
   That's worth more than a slick pitch.

Q: What if Polymarket shuts down?
A: Good question. Regulatory risk is real. If Polymarket closes,
   we pivot to Manifold or international markets. But it's a real
   risk. We're not hiding it.

Q: Why are you funding veteran suicide prevention?
A: Because 22 veterans die by suicide every day. That's a crisis.
   If we can build something profitable, it should fund solutions.
   That's the whole point.

Q: What's your timeline to real money?
A: We need 6-12 months of live data to validate the edge. After
   that, if everything works: raise capital, scale, move to monthly
   profit targets. If it doesn't work, we'll shut it down and be
   honest about why.

Q: What are the biggest risks?
A: 1) Edge doesn't persist live (backtests lie)
   2) Competitive pressure (others have more capital)
   3) Regulatory risk (Polymarket closes)
   4) Single model fragility (ensemble will fix)
   5) Unknown unknowns (markets are weird)

Q: Will you share the code?
A: Eventually. Not until we have live validation. Then we'll
   open-source it (after regulatory clarity). Building in public
   is good; giving away an unproven system is irresponsible.

Q: How much money do you need?
A: Minimum: $75K (hiring, infrastructure, servers).
   Comfortable: $250K (full team, better data, longer runway).
   We're bootstrapped now. Happy to talk to early believers.
```

---

## 11. COMPONENTS REPLIT MUST BUILD

### Core Component Inventory

| Component | Purpose | Data Source | Status | Notes |
|-----------|---------|-------------|--------|-------|
| **Hero Section** | 30-second pitch | Static/hardcoded | Can be static | Simple animation: market → Claude → trade |
| **Honesty Block** | Lead with transparency | Static | Must appear first | Identical on every page (footer link) |
| **Evidence Cards** | Show metrics with tags | JSON or API | Can start static | Each metric needs [BACKTEST], [LIVE], [SIMULATION] tag |
| **Evidence Grid** | Confidence matrix | Static/hardcoded | Can be static table | 3×5 grid showing type vs claim |
| **Roadmap Timeline** | Status visualization | JSON or API | Can start static | Three columns: DONE / IN PROGRESS / NEXT |
| **Research Grid** | 42 prompts + 9 papers | JSON | Can start static | List view with search |
| **Live Metrics Dashboard** | Current system stats | API to FastAPI backend | Needs real data | Positions, P&L, calibration, latest trade |
| **Trade History Table** | All trades logged | API to SQLite | Needs real data | Searchable, sortable, outcome-tracked |
| **Navigation** | Site structure | Static | Can be static | Clean, simple, no surprises |
| **Footer** | Links + honesty link | Static | Can be static | Privacy, disclosure, contact |
| **Mobile Menu** | Responsive nav | Static | Can be static | Hamburger menu, full-width sections |

### Component Details

#### Hero Section
```
Layout:
- Headline + subheadline (above fold)
- Simple animation (2-3 seconds, loops)
- CTA buttons
- No images, no crypto vibes

Animation concept:
  Market Price: "YES 60%"
  ↓ (fade)
  Claude Analysis: "Actually 75%"
  ↓ (fade)
  Trade Decision: "Gap is 15%. Size position, execute."
  ↓ (loop back)

Data: Hardcoded (no API needed)
Mobile: Full-width text, animation scales down
```

#### Evidence Cards
```
Layout:
- Grid: 3 columns on desktop, 1 on mobile
- Each card: Metric + Tag + Caveat + Source

Card anatomy:
  ┌─────────────────────────┐
  │ [BACKTEST]              │ ← Tag (color-coded)
  │ 532 Markets Analyzed    │ ← Metric (large)
  │ Shows: Method works     │ ← What it means
  │ on historical data      │
  │ Doesn't show: Future    │ ← Caveat
  │ markets will be same    │
  │ [Learn more] → /evid    │ ← Link to full page
  └─────────────────────────┘

Colors:
- [BACKTEST] = Blue
- [LIVE] = Green
- [SIMULATION] = Yellow
- [PLANNED] = Gray

Data: JSON or hardcoded
Mobile: Stack vertically, full width
```

#### Confidence Matrix
```
Layout: HTML table
Rows: Method Works? Future Works? Edge Exists? etc.
Columns: [BACKTEST] [SIMULATION] [LIVE]

Cells: High/Medium/Low with color coding
- High = Green
- Medium = Yellow
- Low = Red
- N/A = Gray

Data: Hardcoded (static table)
Mobile: Scrollable table, readable font
```

#### Roadmap Timeline
```
Layout: Three columns
┌──────────────────┬──────────────────┬──────────────────┐
│ DONE             │ IN PROGRESS      │ NEXT             │
├──────────────────┼──────────────────┼──────────────────┤
│ Core system      │ Live validation  │ Multi-model      │
│ Research DB      │ Edge confirmation│ News pipeline    │
│ Paper trading    │ Calibration test │ Weather models   │
│ Safety rails     │ Data optimization│ Web search       │
│ Logging          │ Scale testing    │ Market-making    │
│ Telegram alerts  │                  │ Arbitrage        │
└──────────────────┴──────────────────┴──────────────────┘

Data: JSON or hardcoded
Mobile: Stack vertically, accordion style
```

#### Live Metrics Dashboard
```
Layout: 2×3 grid of metric boxes
┌──────────────┬──────────────┬──────────────┐
│ Total P&L    │ Win Rate     │ Calibration  │
│ $0 (realized)│ 70.6% (live) │ Brier 0.2451 │
├──────────────┼──────────────┼──────────────┤
│ Active       │ Days Running │ Latest Trade │
│ Positions: 5 │ 47 days      │ Trump2024    │
└──────────────┴──────────────┴──────────────┘

Data: API to FastAPI backend (real-time)
Update frequency: Every 5 minutes
Mobile: Stack to 1 column, keep readable
Caveats: "Paper trading. Not live real money."
```

#### Trade History Table
```
Layout: Sortable, searchable table

Columns: Date | Event | Our Estimate | Market Price | Action | Status | Outcome
Example:
2026-03-05 | Trump 2024? | 68% | 62% | BUY YES | Open | --
2026-03-03 | Recession? | 35% | 42% | BUY NO | Resolved | WIN (+$12)
2026-03-01 | Fed Cut? | 40% | 55% | WATCH | Open | --

Data: API to SQLite
Search: By event name, outcome, date range
Mobile: Horizontal scroll or alternate layout
Status tags: Open / Resolved / Waiting
```

#### Navigation
```
Simple, clean:
Home
├─ About
├─ How It Works
├─ Evidence & Results
├─ What We've Built
├─ Roadmap
├─ Research & Media
├─ Contact

No dropdowns. No surprises. Mobile hamburger menu.
```

#### Footer
```
Layout:
- Links: Privacy | Disclosure | Contact
- Copy: [Year] [Organization] — Profits fund veteran
         suicide prevention
- Legal: "Research stage. Not financial advice.
          See disclosure page."
- Contact: Email link

Data: Mostly static
Mobile: Full width, readable font
```

---

## 12. VISUAL STYLE RULES

### Typography
```
Typeface: System fonts (no custom font files)
- Headings: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto
- Body: Same (clean, professional)
- Monospace: "Monaco" or "Courier New" (for code/metrics)

Sizes:
- H1 (hero): 48px (desktop), 32px (mobile)
- H2 (section): 32px (desktop), 24px (mobile)
- H3 (subsection): 24px (desktop), 18px (mobile)
- Body: 16px (desktop), 16px (mobile)
- Small (captions): 12px
- Monospace (metrics): 14px

Weight:
- H1-H3: 600 (semibold)
- Body: 400 (regular)
- Labels: 500 (medium)
- Captions: 400 (regular)

Line height:
- H1-H3: 1.2
- Body: 1.6
- Small: 1.4
```

### Colors
```
Primary Palette:
- Background: #FFFFFF (white) or #F9FAFB (light gray for sections)
- Text: #111827 (near-black)
- Accent: #2563EB (blue—used for links, CTAs, highlights)
- Secondary: #6B7280 (gray—used for labels, captions)

Evidence Tags:
- [BACKTEST]: #3B82F6 (blue)
- [LIVE]: #10B981 (green)
- [SIMULATION]: #F59E0B (yellow/gold)
- [PLANNED]: #D1D5DB (gray)

Semantic Colors:
- Success: #10B981 (green, for wins/resolved positive)
- Warning: #F59E0B (yellow, for caution/caveats)
- Error: #EF4444 (red, for risks/losses)
- Info: #3B82F6 (blue, for information/links)

Dark Mode (optional, not primary):
- If built: Invert colors but maintain contrast
- Background: #0F172A (dark blue-black)
- Text: #F9FAFB (light gray)
- Accent: #60A5FA (lighter blue)
```

### Spacing
```
Base unit: 16px (1rem)

Margins:
- Page padding: 2rem (32px) desktop, 1rem (16px) mobile
- Section margin: 4rem (64px) vertical between sections
- Card margin: 1.5rem (24px) between cards
- Line spacing: 1.6 (text readability)

Gaps:
- Button/control spacing: 0.5rem (8px)
- Grid gap: 2rem (32px)
- List item spacing: 1rem (16px)

Examples:
- Hero section: Full bleed, 4rem padding top/bottom
- Card grid: 3 columns, 2rem gap, wraps to 1 column on mobile
- Section: Max-width 1200px, centered, 2rem padding
```

### Charts & Data Visualization
```
Rule: Simplicity over elegance

Chart types allowed:
- Line chart (P&L over time)
- Bar chart (win rates, calibration)
- Table (trade history, metrics)
- Simple number display (key metrics)

Chart DON'Ts:
- No 3D pie charts
- No fancy animations (brief fade-in OK)
- No rainbow color scales
- No crypto-style gradients
- No unnecessary axes or gridlines

Colors for charts:
- Good outcome: Green (#10B981)
- Bad outcome: Red (#EF4444)
- Neutral/other: Blue (#3B82F6)
- Comparative: Gray (#6B7280)

Labels:
- All axes labeled clearly
- All numbers tagged (e.g., "68.5% [BACKTEST]")
- Units explicit (%, $, days)
- No jargon without explanation
```

### Icons
```
Use: Simple, outline-style icons (not filled)
Examples:
- Check mark ✓
- Arrow →
- Folder 📁
- Chart 📊
- Lock 🔒
- Alert ⚠️

Icon library: Use existing (Font Awesome, Feather) or text
Style: Monochrome (match text color) or accent color
Size: 24px standard, scale appropriately

Rule: Icons support text, don't replace it
```

### Layout Grid
```
Desktop (1200px+):
- Full-width sections with 2rem padding
- Max content width: 1200px, centered
- Multi-column layouts: 3 columns for cards
- Sidebar: Not used (too cramped for content)

Tablet (768px-1199px):
- 2rem padding
- 2 columns for cards
- Navigation: Hamburger menu

Mobile (< 768px):
- 1rem padding
- Single column (all sections)
- Full-width buttons and inputs
- Touch targets: 44px minimum height
- Navigation: Full-screen hamburger menu

Rule: Mobile-first design, scale up, not down
```

### Imagery & Illustration
```
Photos: None (avoid stock photos entirely)
Illustrations: Simple, minimal line drawings only if needed

Preferred: Text + simple animations
Examples:
- Hero: Animated sequence (market → Claude → trade)
- Process: Flow diagram with arrows (text-based)
- Metrics: Data visualization (charts, not images)

Rule: Content should work without images
Reason: Reduces file size, avoids stock photo vibes
```

### Animation & Interaction
```
Animations: Minimal, purposeful
- Hero sequence: 2-3 seconds, loops smoothly
- Section reveals: Subtle fade-in as you scroll (optional)
- Hover states: Button color shift, link underline
- Loading: Spinner if needed, but keep it simple

Transitions: 200-300ms for state changes
Easing: ease-in-out (not linear)

Interactive elements:
- Links: Underline on hover
- Buttons: Slight background color change, cursor pointer
- Inputs: Border highlight on focus
- Tables: Row highlight on hover

Rule: Help users understand affordances (what's clickable)
Rule: Don't distract (animation in service of clarity, not flash)
```

### Accessibility (A11y)
```
Contrast: WCAG AA minimum (4.5:1 for text)
- Test: https://webaim.org/resources/contrastchecker/

Focus states: Visible outline for keyboard navigation
- All buttons, links, inputs must have focus state

Color alone: Never use color to convey meaning
- Example: Don't use red text alone for error; add icon or text "ERROR"

Labels: Every input must have associated label
- Example: <label for="email">Email:</label> <input id="email">

Alt text: Not applicable (no images)

Mobile: Touch targets minimum 44×44px

Readability: Use semantic HTML (h1-h6, p, strong, etc.)
```

---

## 13. TONE RULES

### The Tone (Brief Version)
```
Direct, calm, credible. Smart non-technical person should
understand. Technical reader should respect the rigor.
Investor should see clear thinking, not hype.

Think: Stripe's docs (clear, helpful)
       meets annual report (thorough, honest)

NOT: Crypto marketing (hype, FOMO, emojis)
NOT: Bloomberg terminal (dense, jargon-heavy, impenetrable)
NOT: Startup pitch (promises, optimism, vagueness)
```

### Examples of Good Tone vs Bad Tone

#### Topic: Evidence
**GOOD:**
```
"We backtested this approach on 532 historical markets
and achieved 68.5% calibrated accuracy. That's better than
random (50%), but it's not dominant. The edge is real but small.
[Learn more about evidence quality]"
```

**BAD:**
```
"Our proprietary AI generated a stunning 68.5% win rate
across 532 markets, crushing baseline expectations. This
revolutionary edge will make you money. [Click for details]"
```

---

#### Topic: Risk
**GOOD:**
```
"The biggest risk is this: backtests work, live trading
doesn't. History is a bad predictor of the future. We've
proven the methodology on past data, but we haven't proven
it with real money yet. The next 6-12 months will tell."
```

**BAD:**
```
"While markets are inherently unpredictable, our team's
deep expertise and cutting-edge algorithms minimize risk
exposure through sophisticated portfolio optimization."
```

---

#### Topic: Returns
**GOOD:**
```
"Our backtest shows +$276 in simulated profit across
372 historical trades. If this edge persists live, and
assuming we can scale positions, the annual projection
would be $1K-$6K. These are ceiling scenarios. Actual
results could be much smaller or negative."
```

**BAD:**
```
"Conservative projections show ARR potential of +$1K to
+$6K. Early indicators suggest unicorn-scale upside.
Expected returns could exceed market averages 10x."
```

---

#### Topic: Complexity
**GOOD:**
```
"We use a method called Platt scaling to adjust our
probability estimates based on how accurate we've been
in the past. This prevents overconfidence. If you want
to understand how, here's the technical explainer."
```

**BAD:**
```
"Advanced Bayesian meta-learning with isotonic regression
calibration and ensemble stacking across heterogeneous
feature spaces optimizes probabilistic inference."
```

---

### Tone Checklist (Apply to every page)

- [ ] First time reader understands the idea (no jargon)
- [ ] Technical reader finds depth (link to details)
- [ ] No promises about returns (only probabilities)
- [ ] Caveats are visible, not hidden (not bold, but not buried)
- [ ] Honesty statement near the top (easy to find)
- [ ] Sources cited (where claims come from)
- [ ] Numbers tagged (backtest/live/simulation)
- [ ] Calls to action are clear (not buried)
- [ ] No crypto language ("moon," "hodl," "FUD," etc.)
- [ ] No false certainty ("will," "guaranteed," "proven")
- [ ] Reasons for gaps acknowledged (not pretended they don't exist)
- [ ] Mission mention happens naturally (not forced)

### Sentence Structure
```
RULE: Short sentences. Active voice. Specific numbers.

GOOD: "We tested the approach on 532 past markets.
       It won 68.5% of the time."

BAD:  "Extensive analysis was conducted across a large
       dataset of historical market events, yielding
       positive results consistent with theoretical
       expectations."
```

---

## 14. METRICS HANDLING RULES

### Every metric must be tagged. No exceptions.

```
METRIC TAGGING STANDARD

Format: [EVIDENCE_TYPE] Metric (Time Period)
        Context: What this shows / doesn't show

Example:
68.5% [BACKTEST] Calibrated Accuracy (532 markets, 2024)
├─ What this shows: Our probability estimates are accurate
├─ What this doesn't show: Future markets will perform the same way
├─ Confidence in method: High
├─ Confidence in future: Medium
└─ Display size: Medium (not headline)
```

### By Type: How to Display

#### [BACKTEST] Metrics
```
Size: Medium (prominent, but not massive)
Caveats: ALWAYS include
Context: Always say what market/time period

Example:
┌─────────────────────────┐
│ [BACKTEST]              │
│ 68.5% Calibrated        │
│ Accuracy                │
│                         │
│ 532 historical          │
│ markets analyzed        │
│                         │
│ Shows: Method accuracy  │
│ Not: Future results     │
└─────────────────────────┘

Display: Card with explanation
Highlight: No (normal color)
Headline-worthy: No (too small)
```

#### [LIVE] Metrics
```
Size: Small-to-Medium (real data is precious)
Caveats: YES (too early to draw conclusions)
Context: Always say sample size

Example:
┌─────────────────────────┐
│ [LIVE]                  │
│ $0 Realized P&L         │
│                         │
│ 17 paper trades         │
│ $68 deployed            │
│                         │
│ Shows: System runs      │
│ Not: Edge exists        │
└─────────────────────────┘

Display: Card with context
Highlight: Yes (green for positive, gray for neutral)
Headline-worthy: No (data too small)
```

#### [SIMULATION] Metrics
```
Size: Small (mathematical exercise, not proof)
Caveats: MANDATORY (markets aren't random)
Context: Always say # of paths, assumptions

Example:
┌─────────────────────────┐
│ [SIMULATION]            │
│ 0% Ruin Risk            │
│                         │
│ 10,000 Monte Carlo      │
│ paths, quarter-Kelly    │
│                         │
│ Shows: Sizing is safe   │
│ Not: We won't lose      │
└─────────────────────────┘

Display: Card with warning
Highlight: No (gray)
Headline-worthy: No (not real)
```

#### [PLANNED] Metrics
```
Size: Tiny (not here yet)
Caveats: YES (speculative)
Context: Timeline only

Example:
┌─────────────────────────┐
│ [PLANNED - Q2 2026]     │
│ Multi-Model Ensemble    │
│                         │
│ Add GPT-4, Grok         │
│ Expected benefit:       │
│ Better signal accuracy  │
└─────────────────────────┘

Display: Timeline/roadmap only
Highlight: No
Headline-worthy: No
```

### Layout Rules for Metrics

#### Can be Large/Prominent:
```
✓ 68.5% Accuracy [BACKTEST]
✓ 532 Markets Analyzed [BACKTEST]
✓ 70.2% NO Win Rate [BACKTEST]
✓ System Running [LIVE]
```

#### Must be Small/Caveated:
```
✗ +$276 P&L (unless tiny or heavily caveated)
✗ ARR Projections (unless in "ceiling scenarios" section)
✗ Monte Carlo Paths (simulation, not reality)
✗ Future performance estimates
```

#### Never Headline:
```
✗ "+6,007% ARR" (implied promise)
✗ "$276 Simulated Profit" (as hero metric)
✗ "0% Ruin Risk" (too mathematical)
✗ Any [PLANNED] metric
```

### Caveat Format
```
Every metric follows this pattern:

┌─ METRIC ─────────────────────┐
│ Number + Tag                  │
├─ WHAT IT MEANS ──────────────┤
│ 1-2 sentences explaining      │
├─ WHAT IT DOESN'T MEAN ───────┤
│ Common misinterpretation      │
├─ CONFIDENCE ─────────────────┤
│ High/Medium/Low + why         │
└───────────────────────────────┘

This applies to EVERY metric, no exceptions.
```

---

## 15. RISK / DISCLOSURE RULES

### Required Disclosure Block (Appears Everywhere)

```
THIS IS A RESEARCH-STAGE PROJECT

✓ We have backtested evidence from 532 historical markets
  showing this approach works (+$276 simulated P&L)
✓ The system is fully built and currently paper trading
✓ We have zero live realized results (17 trades, $0 profit/loss)

→ Everything here is tagged: "backtested," "live," or "planned"
→ A backtest is not proof of future results
→ This has not been proven with real money yet

Location:
- Homepage: After hero, before main content
- Every metrics page: Top of page
- Footer: Link to full disclosure
- Contact: Pre-message reminder
```

### Prominent Risk Section (Evidence Page)

```
WHAT HAS NOT BEEN PROVEN YET

Live Profitability: $0 (we haven't made money yet)
├─ Risk: Edge could disappear in live markets
├─ Timeline: 6-12 months to validate
└─ Implication: Don't bet your retirement on this

Single Model: Claude only (no ensemble yet)
├─ Risk: Single models are fragile
├─ Timeline: Q2-Q3 2026 for multi-model
└─ Implication: Edge could be fragile

Narrow Data: Polymarket + research only
├─ Risk: Missing signals from other sources
├─ Timeline: 3-6 months for news/weather/polling
└─ Implication: Competitors might have better data

Competitive Pressure: $1M+ funds already trading
├─ Risk: They might out-scale us
├─ Timeline: Ongoing
└─ Implication: Edge might erode as market becomes efficient

Regulatory Risk: Polymarket US status uncertain
├─ Risk: Regulations could force shutdown
├─ Timeline: Unknown
└─ Implication: Business model depends on uncertain regulatory environment

Brier Score Barely Beats Random
├─ Risk: 0.2451 is close to 0.25 (coin flip)
├─ Timeline: Ongoing (live measurement)
└─ Implication: Small edges wash out with bad months
```

### Legal Language (Non-Lawyer Friendly)

```
DISCLAIMERS (PLAIN ENGLISH)

"This is not financial advice. We're not saying you should
do what we do. We're showing you what we built and what the
evidence shows. Past performance (especially backtested) does
not guarantee future results."

"We are not offering or selling any investment product. This
is research. If you have money, we're not the place to put it
(yet). We're learning."

"Polymarket operates in a gray regulatory area. This business
could disappear or change dramatically. Know the risks before
paying attention."

"Prediction markets are not gambling, but they are volatile.
Don't bet money you can't afford to lose. This applies 10x
to a research-stage system with zero live proof."
```

### Where Disclosures Go

```
Homepage:
- After hero (before main content)
- Size: Prominent but not overwhelming (~150px)

Evidence page:
- Top of page (before any metrics)
- Size: Full section

Every metric:
- Tag + caveat inline
- Never display metric without context

Footer:
- Link to full disclosure page
- Small text, but linked

Contact form:
- Pre-message: "This is research, not investment advice"

FAQ:
- Q: "Can I invest?" A: "No, not yet. This is research."
- Q: "Can I make money?" A: "Maybe. Unproven live. See disclosure."
```

### What NOT to Do

```
✗ Hide disclosures (they must be visible)
✗ Bury them in fine print (they should be prominent)
✗ Use overly legal language (plain English > legalese)
✗ Apologize for them (honesty is strength)
✗ Skip them because "everyone knows the risks" (they don't)
✗ Make them bigger than the content (balance)
✗ Create a separate "legal" section only (needs to be everywhere)
```

---

## 16. CONTENT THAT MUST BE MOVED LOWER OR REMOVED

### DON'T Headline With This:

```
✗ ARR Numbers (especially +$6,007%)
  Why: Implies unearned certainty
  Where to move: "Ceiling scenarios" in deep page, with huge caveats
  Example: "If everything works perfectly (historical edge persists,
           scaling works, competition doesn't erode us, regulation
           holds), annualized projection is +$1K-$6K. Assume this
           is wrong."

✗ Monte Carlo Charts
  Why: Simulation is not reality
  Where to move: Technical deep-dive page, labeled [SIMULATION]
  Example: Card: "Ruin Analysis (Simulation)
           └─ 10K paths, quarter-Kelly sizing
           └─ Result: 0% probability of blowup
           └─ Caveat: Markets aren't random; this is theoretical"

✗ Calibration Math
  Why: Confuses non-technical readers
  Where to move: "How It Works" deep section, optional reading
  Example: Link at bottom: "[Technical] Platt Scaling Deep Dive"

✗ Strategy Comparison Tables
  Why: Implies you've tested alternatives (and lost?)
  Where to move: Research page only, not homepage
  Example: Not here. Too much fog.

✗ Architecture Diagrams
  Why: Distracts from the story
  Where to move: "What We've Built" technical section only
  Example: For builders, not for users

✗ Competitive Analysis
  Why: Implied defensibility we don't have
  Where to move: Roadmap/research only
  Example: "Competitive Landscape" footnote, not main story

✗ Team Photos / Testimonials
  Why: Too early, too small team, distracting
  Where to move: Don't include at all (or contact page only)
  Example: "Founded by [Name]. Contact: [Email]"

✗ "Disrupting" Language
  Why: Crypto-marketing vibes
  Where to move: Delete entirely
  Example: "Disrupting the prediction market paradigm"
           → "We think prediction markets are priced wrong"
```

---

## 17. "DONE / IN PROGRESS / NEXT" ROADMAP SECTION

### Three-Column Layout (Required Format)

```
┌─────────────────────┬────────────────────┬──────────────────┐
│ ✓ DONE              │ → IN PROGRESS      │ ⏭️  NEXT          │
├─────────────────────┼────────────────────┼──────────────────┤
│ Core system built   │ Live validation    │ Multi-model      │
│ ├─ Claude analyzer  │ ├─ Paper trading   │ ensemble         │
│ ├─ Polymarket API   │ ├─ Edge testing    │ ├─ Add GPT-4     │
│ ├─ Safety rails     │ ├─ Calibration     │ ├─ Add Grok      │
│ ├─ Paper trading    │ └─ Data feeds      │ └─ Combine       │
│ ├─ Audit logging    │                    │                  │
│ ├─ Dashboard        │ Timeline: Now-6mo  │ News sentiment   │
│ ├─ Telegram alerts  │                    │ ├─ Real-time     │
│ └─ Research DB      │ Expected outcome:  │ ├─ News feeds    │
│                     │ 100+ trades, +/-   │ └─ Analysis      │
│ Research foundation │ clear edge signal  │                  │
│ ├─ 42 prompts      │                    │ Weather models   │
│ ├─ 9 papers        │                    │ ├─ GFS           │
│ └─ Analysis        │                    │ ├─ ECMWF         │
│                    │                    │ └─ HRRR          │
│ Live infrastructure│                    │                  │
│ └─ VPS running    │                    │ Web search       │
│                    │                    │ ├─ Agentic       │
│                    │                    │ └─ Research      │
│                    │                    │                  │
│                    │                    │ Scale phase      │
│                    │                    │ └─ After live    │
│                    │                    │    validation    │
└─────────────────────┴────────────────────┴──────────────────┘

Styling:
- Three columns, equal width
- Cards or boxes, one item per box
- Status icon (✓ | → | ⏭️ )
- Timeline only for IN PROGRESS and NEXT
- Expected outcomes for IN PROGRESS
- No target dates unless realistic
```

### Honest Timelines

```
DO: "Q2 2026" if you're confident
DO: "3-6 months" if you're less sure
DO: "Ongoing" for competitive/regulatory items
DON'T: "Q2 2025" when current date is Q1 2026
DON'T: "Early 2026" (too vague)
DON'T: Dates you can't commit to (like shipping dates)

Example of good timeline:
- "Live validation: Now-6 months (need N trades to have signal)"
- "Multi-model ensemble: Q2-Q3 2026 (depends on live validation)"
- "Scale phase: Q4 2026+ (only if validation passes)"
```

---

## 18. MOBILE BEHAVIOR REQUIREMENTS

### Responsive Strategy

```
DESKTOP (1200px+):
- Full layout as designed
- Multi-column grids
- Side-by-side elements
- Full navigation visible

TABLET (768px-1199px):
- 2-column grids (where applicable)
- Simplified navigation
- Full-width buttons
- Moderate padding

MOBILE (<768px):
- Single column, everything stacks
- Hamburger menu (not collapsible nav)
- Full-width sections
- Touch-friendly controls (44px minimum)
- Reduced whitespace (but readable)
```

### Specific Mobile Rules

#### Navigation
```
Desktop: Horizontal nav bar, full menu visible
Mobile: Hamburger menu, full-screen overlay

Mobile menu:
├─ Home
├─ How It Works
├─ Evidence & Results
├─ What We've Built
├─ Roadmap
├─ Research
├─ Contact

Close button: Top right (X icon)
No dropdowns (too hard to tap)
```

#### Hero Section
```
Desktop:
- Large headline, 48px
- Subheadline, 20px
- Animation side-by-side

Mobile:
- Headline: 32px
- Subheadline: 16px
- Animation full-width below text (not side-by-side)
- Stack vertically
```

#### Evidence Cards
```
Desktop: 3 columns
Tablet: 2 columns
Mobile: 1 column (full width)

Each card:
- Padding: 1rem on mobile (vs 1.5rem desktop)
- Font: 14px for small text on mobile
- Tags: Still visible, not hidden
```

#### Roadmap Timeline
```
Desktop: 3 columns side-by-side
Tablet: 3 columns (smaller font, tighter)
Mobile: Accordion (one section at a time)

Mobile accordion:
- [✓ DONE] ↓ (tap to expand)
- Content expands below
- Tap again to collapse
- Start with DONE expanded, others collapsed
```

#### Tables
```
Desktop: Full table, scrollable if needed
Mobile: Simplified layout or scrollable

Option A (Simplified):
- Hide some columns on mobile
- Show: Date | Event | Outcome
- Hide: Market Price, Analysis, Context
- Link to full trade details on click

Option B (Scrollable):
- Horizontal scroll on mobile
- Full table, but user scrolls right
- Better for data integrity, worse for UX
```

#### Buttons & Forms
```
CTA Buttons:
- Desktop: 44px height, 16px font
- Mobile: 48px height, 16px font
- Full width on mobile (except in button groups)
- Touch-friendly spacing (8px minimum between)

Forms:
- Labels above inputs (not placeholder-only)
- Input height: 44px minimum
- Text size: 16px (prevents zoom on iOS)
- Visible focus states
```

#### Sections to Hide / Collapse on Mobile
```
Optional (mobile-hidden):
- Very long code blocks (link to GitHub instead)
- Very detailed tables (simplified version)
- Secondary navigation (moved to footer)

Keep visible:
- Honesty statement (always visible)
- Evidence cards (essential)
- CTA buttons (always visible)
- Mobile menu (always accessible)

Rule: Mobile shouldn't feel like a stripped version.
      It should be a thoughtful simplification.
```

#### Footer on Mobile
```
Desktop: Horizontal, compact
Mobile: Vertical stack, full width

Mobile footer:
- Links on separate lines (easier to tap)
- Logo/branding at top
- Contact email as link (tel: if phone)
- Disclosure link prominent
- Copyright at bottom
```

---

## 19. UPDATE PROTOCOL FOR FUTURE REVISIONS

### When to Update the Site

```
UPDATE if:
✓ New live trading results (every 2+ weeks)
✓ Major milestone hit (50+ trades, 100+ trades)
✓ New evidence appears (paper published, backtest completed)
✓ Roadmap changes (timeline shifts, new features added)
✓ Regulatory news (Polymarket status changes)

DON'T UPDATE if:
✗ Small win/loss (noise, not signal)
✗ One trade outcome (meaningless)
✗ Speculative news (wait for confirmation)
✗ Minor copy tweaks (unless critical)
```

### What Can Be Updated Without Founder Review

```
Updates that don't need approval:
- Live metrics dashboard (auto-update from API)
- Trade history table (auto-update from API)
- Running days counter (auto-update)
- Timestamp updates (e.g., "Live validation: Month 3 of 6")

Updates that DO need approval:
- Any new claim or metric
- Changes to disclosure language
- Roadmap timeline shifts
- New sections or pages
- Changes to tone or framing
- Any number that could be misinterpreted
```

### Update Checklist

```
Before publishing any update:

□ Tag all numbers correctly ([BACKTEST], [LIVE], [SIMULATION])
□ Add caveats where applicable
□ Run past disclosure rules (does it violate #15?)
□ Check mobile rendering
□ Proofread for jargon
□ Verify data accuracy (especially metrics)
□ Link to supporting evidence (if new claim)
□ Update related pages (if multiple pages affected)
□ Add timestamps (when was this updated?)
□ Notify audience if major (email, Telegram)
```

### Founder Approval Gates

```
FOUNDER MUST APPROVE:
- Any new major evidence claim
- Changes to mission statement
- New roadmap items or timelines
- Tone changes
- Competitive/regulatory information
- Financial projections
- Names, quotes, attributions

BUILDER CAN APPROVE:
- New live metrics (if data accurate)
- Trade history updates
- Mobile layout fixes
- Typography/spacing changes
- Navigation restructuring (if usable)
```

---

## 20. APPENDIX: RAW FACTS / NUMBERS / LABELS

### Every Number the Builder Might Need

```
KEY METRICS (All tagged and caveated in copy)

[BACKTEST] Evidence
├─ 532 markets analyzed
├─ 68.5% calibrated win rate
├─ 70.2% NO win rate
├─ +$276 simulated P&L
├─ 372 historical trades
├─ Brier score: 0.2451 (out-of-sample)
└─ Brier baseline: 0.239 (pre-calibration)

[LIVE] Evidence
├─ 17 paper trades executed
├─ $68 deployed
├─ $0 realized P&L
├─ [X] days running
├─ [X] markets monitored
└─ 100 market checks per 5 minutes

[SIMULATION] Evidence
├─ 10,000 Monte Carlo paths
├─ 0% ruin risk (quarter-Kelly)
└─ 10% max drawdown (simulated)

[PLANNED] Projections
├─ Conservative ARR: +124%
├─ Velocity-optimized ARR: +6,007%
├─ Target: $1K/week (6-12 months)
└─ Target: $50K/year run rate
```

### Team / Organization

```
Founder: [Name]
├─ Background: [2-3 sentences]
├─ Mission: Fund veteran suicide prevention
└─ Contact: [Email]

Organization Status: Research stage, not incorporated as service

Team Size: [N] people
├─ Founder: Full-time
├─ [Others if applicable]
└─ Contractors/Advisors: [List if public]
```

### Dates & Timelines

```
Project Start: [Date]
Live Trading Start: [Date]
Validation Period: [Now] - [6 months out]
Expected Scale Phase: Q4 2026
Series Seed Target: Q4 2026 ($75K)

Roadmap:
├─ In Progress: Live validation (now - 6 months)
├─ Near-term: Multi-model ensemble (Q2-Q3 2026)
├─ Near-term: Data expansion (Q2-Q3 2026)
├─ Near-term: Web search (Q3-Q4 2026)
├─ Scale phase: After validation passes (6+ months)
└─ Expected sustainability: 12-18 months post-seed
```

### Academic References

```
9 Papers Synthesized (with authors, years)
├─ Calibration: [Author Year]
├─ Kelly Criterion: [Author Year]
├─ Prediction Markets: [Author Year]
├─ Favorite-Longshot Bias: [Author Year]
└─ [Others as documented]

42 Research Prompts (by category)
├─ Base rate (12)
├─ Reference class (10)
├─ Bias detection (8)
├─ Evidence gathering (8)
├─ Reasoning check (4)
└─ [Others as documented]
```

### Infrastructure

```
Hosting:
├─ Provider: DigitalOcean
├─ Region: Frankfurt
├─ Instance: [Size/specs]
├─ Uptime: [%]
└─ Cost: $[X]/month

APIs:
├─ Polymarket: Gamma API
├─ Weather: NOAA
├─ Alerts: Telegram
└─ [Others if applicable]

Database:
├─ Type: SQLite
├─ Size: [MB]
├─ Backup: Daily snapshots
└─ Audit log: Complete (every trade decision)
```

---

# FINAL REQUIRED SECTIONS

## A. REPLIT IMPLEMENTATION PRIORITIES

### P0: MUST SHIP (Absolute Minimum)
```
□ Homepage
  - Hero + value prop
  - Honesty statement
  - Evidence cards (with tags)
  - CTA buttons

□ How It Works
  - Problem statement
  - Approach explanation
  - Safeguards
  - Decision flow diagram
  - Academic foundation

□ Evidence & Results
  - Evidence quality grid
  - Backtest metrics
  - Live results
  - Confidence matrix
  - Clear caveats on every number

□ Risk Disclosure
  - Prominent "what's not proven"
  - Legal disclaimers
  - Accessible on every page (footer link)

□ Navigation
  - Clean menu
  - Mobile hamburger
  - No broken links
```

**Estimated effort:** 2-3 weeks full-time

### P1: SHOULD SHIP (High Value, Doable)
```
□ What We've Built
  - Code inventory
  - Infrastructure overview
  - Research library
  - Visual system diagram (simple)

□ Roadmap Page
  - Three-column layout (Done/In Progress/Next)
  - Timeline context
  - Expected outcomes

□ Research & Media
  - Paper list
  - Prompt categories
  - Links to references

□ FAQ Page
  - 10-15 common questions
  - Short, honest answers

□ Live Metrics Dashboard
  - API integration to FastAPI backend
  - 6 key metrics (P&L, win rate, calibration, etc.)
  - 5-minute refresh
  - Clear [LIVE] tag
```

**Estimated effort:** 3-4 weeks full-time

### P2: NICE TO HAVE (Lower Priority)
```
□ Trade History Table
  - Full searchable table
  - Sort by date/outcome/event
  - Outcome tracking
  - Real-time updates

□ Interactive Monte Carlo Visualization
  - Visual representation of ruin paths
  - Explainer tooltip
  - Labeled [SIMULATION]

□ Comparison Charts
  - Win rate over time
  - Calibration curve
  - P&L trajectory

□ Blog / News Section
  - If launch announcements needed
  - Regular updates on progress

□ Community / Contact
  - Email signup
  - FAQ form
  - Chat widget (optional)
```

**Estimated effort:** 2+ weeks (if time allows)

---

## B. COMPONENTS: MOCK FIRST VS WIRE TO REAL DATA

### Can Use Static / Hardcoded Content (Mock First)

```
✓ Homepage hero section
  → Hardcoded animation sequence
  → Use sample market example (mock data)

✓ Evidence cards
  → Use hardcoded metrics from research
  → No API needed

✓ How It Works explainer
  → All static content and diagrams
  → Sample flow diagram (not real)

✓ Roadmap timeline
  → Hardcoded three-column layout
  → Use dates/timelines as provided

✓ FAQ section
  → All static content
  → Pre-written answers

✓ Research library
  → List of papers (hardcoded)
  → Prompt categories (hardcoded)

✓ Navigation & footer
  → Static menus
  → Links (ensure they work)

✓ Honesty statement
  → Static text (same on every page)
```

### Need Live Data / API Connection

```
✓ Live metrics dashboard
  → Must connect to FastAPI backend
  → Polling every 5 minutes
  → Real positions, P&L, calibration
  → Timestamp updates

✓ Trade history table
  → Must connect to SQLite via API
  → Real trade data
  → Search/sort functionality
  → Outcome tracking (real or in-progress)

RECOMMENDATION: Build static pages first (P0 + P1).
Wire up live data (P1 + P2) after site structure is solid.
```

---

## C. COPY BLOCKS ALREADY FINAL

### Use These Exactly (No Rewording)

#### Honesty Statement (Required Identical Everywhere)
```
THIS IS A RESEARCH-STAGE PROJECT

✓ We have backtested evidence from 532 historical markets
  showing this approach works (+$276 simulated P&L)
✓ The system is fully built and currently paper trading
✓ We have zero live realized results (17 trades, $0 profit/loss)

→ Everything here is tagged: "backtested," "live," or "planned"
→ A backtest is not proof of future results
→ This has not been proven with real money yet

We're showing you this because we're serious about being honest.
```

#### Hero Headline
```
"We Built an AI That Beats the Market's Predictions"
```

#### Hero Subheadline
```
"Polymarket has billions in predictions on world events.
Most are priced wrong. We estimate them better.
Then we trade when the gap is big enough."
```

#### One-Sentence Thesis
```
"An AI system that estimates the probability of world events
better than markets do, then trades when the gap is wide enough—
with $276 in simulated profit, zero live losses, and profits
funding veteran suicide prevention."
```

#### Mission Statement
```
"Profits fund veteran suicide prevention"
```

#### Why Disclosures Build Trust (Use in Tone Guide)
```
"By being honest about gaps, we're telling you we actually
understand the risks. That's worth more than a slick pitch."
```

---

## D. OPEN QUESTIONS REQUIRING FOUNDER INPUT

### Decisions Only Founder Can Make

```
1. EXACT NUMBERS TO DISPLAY
   Question: What exact figures do you want visible on homepage?
   Options:
   ├─ Just headline (no numbers)
   ├─ One hero metric (e.g., "532 markets tested")
   └─ Multiple small cards (backtest, live, simulation all visible)

   Founder decision needed: ___________

2. LIVE METRICS SENSITIVITY
   Question: How often update live dashboard? (every 5 min? 1 hour?)
   And which data expose publicly?

   Founder decision needed: ___________

3. ROADMAP DATES
   Question: Can you commit to specific dates for:
   ├─ Multi-model ensemble launch
   ├─ Data expansion phase
   ├─ Series seed attempt
   └─ Or just estimates?

   Founder decision needed: ___________

4. MEDIA / PRESS
   Question: Any press coverage, podcast, articles to link?
   Current plan: Link to them (if founder approves)

   Founder decision needed: ___________

5. TEAM VISIBILITY
   Question: Include founder name/photo/bio?
   Current plan: Name + email only. Photo/bio optional.

   Founder decision needed: ___________

6. CONTACT FORM USAGE
   Question: What happens when someone emails?
   Auto-response? Manual follow-up? Lead capture?
   Current plan: Simple email form, founder reads manually.

   Founder decision needed: ___________

7. LIVE TRADING DEPLOYMENT
   Question: Go from paper to live $X,000 trading?
   When? How large? After what validation?

   Founder decision needed: ___________

8. FUNDRAISING TIMELINE
   Question: When do you plan to fundraise?
   Will site be used for investor pitch? What version?

   Founder decision needed: ___________

9. FUTURE PRODUCT PLANS
   Question: Will this eventually be a service? Public API?
   How does site need to position for that?

   Founder decision needed: ___________

10. EVIDENCE DEPTH
    Question: Deep-dive pages on calibration, Kelly, etc.?
    Or keep it simple and link to papers?

    Founder decision needed: ___________
```

---

## E. THE 12 MOST COMMON WAYS A BUILDER COULD SCREW THIS UP

### 1. LEADING WITH THE ARR NUMBER ❌

**WRONG:**
```
"Projected Annual Returns: +6,007%"
```

**RIGHT:**
```
"If everything works perfectly (historical edge persists,
scaling works, competition doesn't erode us), the ceiling
is +$6K/year. Assume this is wrong."
[Small card in "ceiling scenarios" section, heavily caveated]
```

**Why it matters:** ARR implies certainty we don't have.
It creates false hype. It will disappoint early believers.

---

### 2. MAKING IT LOOK LIKE A CRYPTO PROJECT ❌

**WRONG:**
```
- Crypto-style color gradients (neon blues, purples)
- Emojis: 🚀 💎 🌙
- Language: "moon this," "hodl," "diamond hands"
- Futuristic fonts (Orbitron, etc.)
- Glow effects, drop shadows, 3D buttons
- Grid backgrounds, glitch animations
```

**RIGHT:**
```
- Clean, professional palette (blues, grays, whites)
- No emojis
- Formal language: "we tested," "results show"
- System fonts (no weird typefaces)
- Subtle animations (fade-in, smooth scroll)
- Minimal visual effects
```

**Why it matters:** Crypto language triggers skepticism in
serious investors and smart non-technical people. We want to be
Stripe, not Shiba Inu.

---

### 3. IMPLYING LIVE RETURNS EXIST ❌

**WRONG:**
```
"Live P&L: +$276"
"Trading Results: 68.5% Win Rate"
"Returns: Profitable"
```

**RIGHT:**
```
"Paper Trading Results: [LIVE]
├─ 17 trades executed
├─ $68 deployed
├─ $0 realized P&L (too early to tell)
└─ [Learn what 'live' means] → Evidence page"
```

**Why it matters:** Saying we made money when we didn't is fraud-adjacent.
It kills trust instantly when investors dig deeper.

---

### 4. BURYING THE HONESTY STATEMENT ❌

**WRONG:**
```
[Long hero section]
[Evidence cards]
[About section]
[Small gray footer text]: "This is research-stage..."
```

**RIGHT:**
```
[Hero]
[PROMINENT HONESTY STATEMENT] ← Top of page, hard to miss
[Evidence cards with tags]
[Footer link to full disclosure]
```

**Why it matters:** Honesty on top builds trust. Honesty at the bottom
looks like you're hiding it. We want the former.

---

### 5. USING TOO MUCH JARGON ❌

**WRONG:**
```
"Platt scaling reduces the Brier score through isotonic
regression meta-learning and probabilistic calibration
of heterogeneous forecast distributions."
```

**RIGHT:**
```
"We measure how accurate our probability estimates are
using a Brier score. We then adjust our estimates to be
more accurate (calibration). This works."
[Optional: Link to technical explainer for nerds]
```

**Why it matters:** Non-technical people stop reading. We lose them
before they get to the good parts. Jargon makes us look like we're
hiding something.

---

### 6. MAKING IT TOO DARK / TERMINAL ❌

**WRONG:**
```
- Dark background (#1a1a1a) everywhere
- Neon green text
- Monospace font for all copy
- Blinking cursors
- "Matrix" vibes
```

**RIGHT:**
```
- Light background (white, light gray)
- Black or near-black text
- System fonts (readable)
- Minimal animations
- "Stripe docs" vibes
```

**Why it matters:** Dark = mysterious = untrustworthy. Light = open = honest.

---

### 7. TREATING BACKTESTS AS PROOF ❌

**WRONG:**
```
"Proven: 68.5% Accuracy"
"Our methodology works"
"Backtested on 532 markets with 100% success"
```

**RIGHT:**
```
"[BACKTEST] 68.5% Calibrated Accuracy
├─ What it shows: Method works on past data
├─ What it doesn't show: Future markets will perform the same
└─ Confidence: High in method, medium in future"
```

**Why it matters:** Backtests are not proof. Real investors and
smart people know this. Overselling backtests kills credibility.

---

### 8. IGNORING MOBILE ❌

**WRONG:**
```
- Hero section doesn't stack on mobile
- 3-column grid stays 3 columns on 320px phones
- Text is 12px (too small)
- Navigation is desktop-only
- Tables don't scroll
- Buttons are tiny (20px height)
```

**RIGHT:**
```
- All sections stack to 1 column on mobile
- Readable font size (16px minimum)
- Hamburger menu for mobile
- Horizontal scroll or simplified view for tables
- Touch-friendly buttons (44px height)
- Mobile-first design
```

**Why it matters:** 50% of traffic is mobile. Ignoring it looks lazy.

---

### 9. OVER-DESIGNING THE DASHBOARD BEFORE THE STORY WORKS ❌

**WRONG:**
```
[Start with:] "Let's build an amazing interactive Monte Carlo
simulator with 3D charts!"
[Result:] Months spent on visualization. Homepage still vague.
[Outcome:] Beautiful dashboard, no one understands what it is.
```

**RIGHT:**
```
[Start with:] Homepage, How It Works, Evidence page (words + simple cards)
[Then add:] Live dashboard (simple metrics)
[Final:] Interactive visualizations (if time and value justify)
```

**Why it matters:** The story has to be clear first. Fancy UI comes
after clarity. It's like designing a book cover before writing the book.

---

### 10. USING STOCK PHOTOS ❌

**WRONG:**
```
- Homepage hero: Getty Images of "people looking at charts"
- Team section: Stock photos of "diverse team in meeting"
- Evidence section: Unsplash photo of "data center"
```

**RIGHT:**
```
- No photos (none needed)
- Simple diagrams (flow chart, 3-column layout)
- Real metrics and data
- Text + animation instead of images
```

**Why it matters:** Stock photos scream "startup that doesn't know
itself yet." Real evidence is better than fake photos.

---

### 11. MAKING THE SITE ABOUT THE TECHNOLOGY INSTEAD OF THE OUTCOME ❌

**WRONG:**
```
Homepage focuses on:
- Claude architecture
- API endpoints
- Database schema
- Polymarket API integration
```

**RIGHT:**
```
Homepage focuses on:
- What the system does
- Evidence it works
- What's not proven yet
- Mission (veteran suicide prevention)
```

**Why it matters:** Non-technical people don't care how it works.
They care about the outcome. Lead with the outcome.

---

### 12. FORGETTING THAT THE FIRST USER IS SOMEONE'S DAD, NOT A QUANT ❌

**WRONG:**
```
[Entire site optimized for:]
- Financial engineers
- Prediction market enthusiasts
- Algorithmic traders
- People who read Tetlock papers for fun

[Result:] Founder's dad visits. Confused. Leaves.
```

**RIGHT:**
```
[Every page designed so that:]
- 50-year-old non-technical person understands it in 30 seconds
- Charts are clear, not complex
- Language is simple, not academic
- Purpose is obvious ("I understand what this does")

[Tech depth available via:]
- Links to deep sections
- Optional reading
- "Technical explainer" callouts
```

**Why it matters:** If your dad doesn't get it, your site is too complex.
Your first believers are non-technical people who trust you. Build for them.

---

---

## FINAL CHECKLIST FOR LAUNCH

Before the builder ships, verify:

```
□ Honesty statement on every page
□ Every metric tagged ([BACKTEST], [LIVE], [SIMULATION])
□ Every metric has a caveat
□ Mobile renders correctly
□ No crypto vibes (colors, language, vibe)
□ Jargon minimized (with links to explainers)
□ Copy is direct and calm (not hype)
□ Homepage understandable in 30 seconds
□ CTA buttons clear and prominent
□ Footer has disclosure link
□ No stock photos
□ No promises about returns
□ Navigation works on all pages
□ Accessibility tested (contrast, focus states)
□ All links work
□ Founder has approved key copy
□ Legal disclaimers in place
□ Contact form works
□ Site performs well (load time, responsiveness)
□ Founder happy with overall tone and direction

Once all boxes checked: SHIP IT.
```

---

## THE FINAL THING TO REMEMBER

**This site is NOT:**
- A pitch deck (though investors will view it that way)
- A service website (we're not selling anything)
- A crypto project (even though Polymarket seems crypto-adjacent)
- A proof that this will work (we don't have proof yet)

**This site IS:**
- A credibility statement (we built something real)
- An honesty contract (we're telling you what we don't know)
- A research archive (here's the work, here's the evidence)
- An invitation (help us build and validate this)

**Build for that, and everything else follows.**

---

END OF REPLIT BUILD BRIEF V2 FINAL
```
