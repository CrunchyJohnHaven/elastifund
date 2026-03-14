# 10x Cowork Prompts — Highest Leverage System Improvements
**Created:** 2026-03-05
**Focus:** Maximum speed of system improvement + investor material updates

---

## Prompt 1: Live vs Backtest Performance Audit
**Priority:** P0 | **Impact:** Trust + Strategy Validation

```
I have a Polymarket trading bot in paper trading. Read my STRATEGY_REPORT.md and INVESTOR_REPORT.md in the selected folder.

The bot has been paper trading — pull all available data from paper_trades.json on the VPS and compare it against the backtest predictions (64.9% win rate, $0.60 avg P&L, 76% NO win rate).

Build me a single-page LIVE VS BACKTEST SCORECARD as a .docx:
- Side-by-side: backtest predicted vs actual live for every key metric
- Flag any metric where live deviates >10% from backtest
- Statistical significance test (are we seeing enough trades to trust the numbers?)
- Clear verdict: "Backtest is holding" or "Backtest is diverging — here's where"
- Actionable recommendation: what to adjust if diverging

This is the most important thing to know right now. If the backtest doesn't hold live, nothing else matters.
```

---

## Prompt 2: Investor Report Refresh with Latest Performance
**Priority:** P0 | **Impact:** Investor readiness

```
Read INVESTOR_REPORT.md and STRATEGY_REPORT.md in my selected folder. Also read the backtest/ data directory for the latest numbers.

Update the Investor Report with:
1. Latest live paper trading results alongside the backtest data
2. Any new resolved trades and updated win rates
3. Refresh all tables with current numbers
4. Add a "Live Trading Update" section showing paper trading performance since launch
5. If we now have live data that differs from backtest, update the Monte Carlo projections accordingly

Then regenerate the report as a polished .docx with professional formatting — headers, table styling, proper spacing. This goes to potential investors. Make it look like a real hedge fund quarterly letter.

Keep all risk disclosures and disclaimers. Update the date to today.
```

---

## Prompt 3: Calibration Correction Impact Analysis
**Priority:** P0 | **Impact:** +30-50% ARR (biggest single alpha improvement)

```
Read STRATEGY_REPORT.md in my selected folder. Focus on the calibration table:

Claude says 90%+ → actual 63%. Claude says 70-80% → actual 53%. The raw Brier score is 0.239 (barely better than random).

But our "Calibrated + Selective" strategy variant already hits 83.1% win rate.

I need you to:
1. Build a detailed analysis of EXACTLY how much money we're leaving on the table by not having the calibration fix deployed live
2. Model three scenarios: (a) current baseline strategy, (b) with calibration correction only, (c) with calibration + selective filtering
3. Calculate the dollar difference per month at $75, $1,000, $10,000 capital levels
4. Create a clear one-page brief I can use to prioritize this work — show the ROI of implementing the calibration fix vs everything else on our roadmap

Output as a .docx with tables showing the dollar impact.
```

---

## Prompt 4: Fund Legal Structure Decision Matrix
**Priority:** P0 | **Impact:** Determines if we can legally accept investor money

```
Read Private_Placement_Memorandum.docx and Investor_Subscription_Agreement.docx in my selected folder.

I need a DECISION MATRIX for the legal structure of this prediction market fund. We're at the stage where we need to decide:

1. Entity type: LLC vs LP vs Series LLC — pros/cons for a small quant fund (<$500K AUM initially)
2. Regulatory status: Do we need to register as an investment adviser? Exemptions available?
3. Polymarket-specific: Is trading on Polymarket legally clear for a fund? CFTC implications?
4. Tax treatment: Are prediction market gains capital gains, gambling income, or ordinary income?
5. State formation: Delaware vs Wyoming vs other for crypto-adjacent fund
6. Accredited investor requirements: What paperwork do we actually need?
7. Cost estimate: Legal formation costs, ongoing compliance costs, annual filings

Create a structured .docx decision matrix with clear YES/NO recommendations for each decision point. Include the specific next steps (file X form, hire Y type of attorney, etc.).
```

---

## Prompt 5: NO-Bias Alpha Deep Dive + Implementation Spec
**Priority:** P0 | **Impact:** Win rate 56% → 76% on half the portfolio

```
Read STRATEGY_REPORT.md in my selected folder. Focus on the NO bias finding:
- buy_no: 76.2% win rate (210 trades)
- buy_yes: 55.8% win rate (260 trades)

This is our single biggest edge. I need:

1. ANALYSIS: Why does betting NO work so much better? Is it because prediction markets have a "longshot bias" (people overpay for exciting YES outcomes)? Or is Claude specifically better at identifying overpriced YES events? Break down the mechanics.

2. STRATEGY SPEC: Design a "NO-biased" strategy variant for the live bot:
   - What % of capital should go to NO-only trades vs mixed?
   - Should we use different edge thresholds for YES vs NO? (e.g., 10% for YES, 5% for NO)
   - Position sizing: should NO trades get larger positions (Kelly-adjusted)?
   - What's the expected impact on monthly P&L?

3. RISK CHECK: What could make the NO bias disappear? Market structure changes, more sophisticated traders, category-specific effects?

Output as a .docx with the implementation spec I can hand directly to Claude Code for implementation.
```

---

## Prompt 6: Monte Carlo Model Stress Test
**Priority:** P1 | **Impact:** Investor confidence + risk management

```
Read INVESTOR_REPORT.md and STRATEGY_REPORT.md in my selected folder. Also look at backtest/monte_carlo.py if available.

Our Monte Carlo shows 0% probability of total loss and median +1,124% annual return at $75 capital. These numbers feel too good — investors will be skeptical.

Stress test the Monte Carlo model:
1. What assumptions is the model making? List every one.
2. Which assumptions are most fragile? (e.g., constant win rate, no correlation between losses, fixed position sizing)
3. Run adverse scenarios: What if win rate drops to 55%? 50%? What if there's a 10-trade losing streak? What if Polymarket liquidity drops 50%?
4. What's the REALISTIC worst-case drawdown an investor should expect?
5. How should we present Monte Carlo results to sophisticated investors who will poke holes?

Create a .docx "Monte Carlo Assumptions & Stress Test" appendix we can attach to the investor report. Be brutally honest — overpromising kills credibility.
```

---

## Prompt 7: Competitor & Market Landscape Brief
**Priority:** P1 | **Impact:** Investor material + strategic positioning

```
I'm building an AI prediction market trading fund. Search the web for current information on:

1. Other AI/algorithmic prediction market traders — who's doing this? Any public track records?
2. Polymarket's current status: volume, regulatory situation, growth trajectory
3. Other prediction market platforms we should consider: Kalshi, Metaculus, Manifold, etc.
4. Academic research on prediction market efficiency and LLM forecasting ability
5. How our 64.9% backtest win rate compares to known benchmarks (superforecasters, prediction market literature)

Create a 2-page .docx "Competitive Landscape & Market Analysis" brief that:
- Positions our system relative to competitors
- Identifies our moat (what's defensible about our approach?)
- Highlights market tailwinds (prediction markets growing, regulatory clarity)
- Flags threats (more AI traders entering, market efficiency increasing)

This goes into the investor appendix. Be specific with data, not vague.
```

---

## Prompt 8: Fee Structure & Investor Economics Optimizer
**Priority:** P1 | **Impact:** Directly determines fund economics

```
Read INVESTOR_REPORT.md in my selected folder. Current proposed terms:
- 0% management fee, 30% carry above high-water mark
- $1,000 minimum investment
- 90-day lock-up, 30-day withdrawal notice, quarterly withdrawals

I need an analysis:
1. How do our terms compare to standard quant fund / crypto fund structures?
2. Model investor returns at different capital levels ($1K, $5K, $10K, $50K) using our base case projections, AFTER fees
3. At what AUM level does this become economically viable for us? (covering infra costs, time, legal)
4. Should we charge management fee at small scale to cover costs?
5. Is 30% carry competitive, or should it be 20% (standard) or higher (justified by returns)?
6. What fee structure maximizes chance of attracting first $100K in AUM?

Create a .docx with comparison tables and a recommended fee structure with rationale.
```

---

## Prompt 9: Pitch Sheet / One-Pager Redesign
**Priority:** P1 | **Impact:** First impression for every investor conversation

```
Read Fund_Overview_Pitch_Sheet.pdf and INVESTOR_REPORT.md in my selected folder.

Redesign the fund one-pager / pitch sheet as a polished single-page .docx that an investor can absorb in 60 seconds. It should answer:

1. What is this? (AI prediction market trading system)
2. How does it work? (3-sentence explanation a non-technical person gets)
3. What's the track record? (Key numbers: win rate, projected returns, risk metrics)
4. What makes this different? (NO-bias edge, multi-model ensemble, 24/7 automation)
5. What are the terms? (Minimums, fees, lock-up)
6. What's the next step? (How to invest)

Design principles:
- One page, scannable in under 60 seconds
- Lead with the single most impressive number
- Clean, professional layout — not cluttered
- Include a small equity curve chart description/placeholder
- Bottom: risk disclaimer in small but readable text
```

---

## Prompt 10: System Improvement Roadmap with ROI Ranking
**Priority:** P0 | **Impact:** Meta — ensures we work on the right things

```
Read STRATEGY_REPORT.md and INVESTOR_REPORT.md in my selected folder. Also read the research_dispatch/ directory to see what research prompts already exist.

Create a RANKED SYSTEM IMPROVEMENT ROADMAP as a .docx:

For each improvement on our list (and any new ones you identify), estimate:
1. Expected ARR impact (% improvement to returns)
2. Implementation effort (hours of Claude Code / research time)
3. ROI score = ARR impact / effort
4. Dependencies (what needs to happen first?)
5. Current status (from research_dispatch files)

Improvements to rank:
- Calibration correction (isotonic regression)
- Multi-model ensemble (Claude + GPT + Grok)
- NO-bias exploitation strategy
- Kelly criterion position sizing
- Market selection optimization
- Prompt engineering / A-B testing
- Backtest expansion (more markets, different time periods)
- Live trading switch (paper → real)
- Position deduplication
- Telegram daily digest
- Scaling analysis (how much capital before edge erodes?)

Output a prioritized table ranked by ROI score, with a "Do This Week" / "Do This Month" / "Do This Quarter" grouping. This becomes our operating plan.
```
