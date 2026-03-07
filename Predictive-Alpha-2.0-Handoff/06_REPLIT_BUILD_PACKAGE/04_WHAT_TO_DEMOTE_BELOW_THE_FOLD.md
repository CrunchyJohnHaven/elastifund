# WHAT TO DEMOTE BELOW THE FOLD

Current elements that belong deeper on the site, not on the homepage or in the primary user flow.

---

## 1. "+6,007% ARR" HEADLINE

**What it is:** A calculated metric showing what annual return would be if we extrapolated from backtest to a year. ~6000% is eye-catching and makes people assume this is proven.

**Why it should move:**
- Backtests don't predict future returns
- 17 live trades = $0 P&L, so ARR is actually $0, not 6000%
- Leading with this makes the project look like marketing hype, not honest research
- It triggers skepticism: "If you made 6000%, why are you building a website?"

**Where it lives instead:**
- Research Archive page, in the "Strategy Comparison" section, explicitly labeled "Backtest P&L (historical only, not indicative of future returns)"
- Could be a single line: "Annualized backtest return (2004-2024, 532 markets): 6007% if extrapolated over one year, but backtests don't predict future performance."

**What replaces it on homepage:**
"68.5% win rate. +$276 P&L. Over 20 years. On 532 markets."

This is honest. It shows accuracy, not returns. It's in context (historical, multi-market). It doesn't promise anything.

---

## 2. MONTE CARLO FAN CHARTS

**What it is:** A visualization showing the distribution of possible outcomes (fans of lines radiating from a center). Looks impressive. Shows percentiles.

**Why it should move:**
- Homepage readers don't understand what Monte Carlo means
- A fan chart is pretty but doesn't convey actionable information
- It can look like a "crystal ball" prediction, which we're not doing
- It takes up valuable above-the-fold real estate

**Where it lives instead:**
- Evidence page, under "Monte Carlo Simulation" section
- Research Archive, with full explanation of methodology
- Interactive version on the Evidence page (if budget allows) so readers can adjust assumptions

**What replaces it on homepage:**
Text description: "In 75% of scenarios, the system would be profitable over 5 years. In 25% of scenarios, it breaks even or loses money. See Evidence for details."

This conveys the uncertainty without the chart.

---

## 3. CALIBRATION MAPS / PLATT PARAMETER DETAILS

**What it is:** Visualizations or tables showing how well predictions match reality at different confidence levels. Includes Platt scaling parameters, cross-validation results, etc.

**Why it should move:**
- Most readers don't know what Platt scaling is
- Calibration maps are technical, not compelling
- They don't answer the question "does this work?"
- They belong in technical documentation, not homepage

**Where it lives instead:**
- "How It Works" page, one paragraph explanation: "We use a technique called Platt scaling to make predictions honest. A 60% forecast is right 60% of the time, not 40%."
- Research Archive: full technical section with maps, parameters, and math
- GitHub: code and data for reproducing calibration

**What replaces it on homepage:**
One sentence: "Our predictions are calibrated to be honest about what we don't know."

---

## 4. STRATEGY COMPARISON TABLES (10 VARIANTS)

**What it is:** A detailed table showing performance of: baseline, no-calibration, no-routing, full-Kelly, no-anti-anchoring, no-velocity-optimization, etc.

Why it's currently prominent:
- Shows that the five-layer system is better than alternatives
- Looks scientific and rigorous

**Why it should move:**
- Homepage readers don't care about variant comparison
- Too much detail for an overview page
- Could confuse (why are there 10 variants? which one is running?)
- Tables are hard to scan on mobile

**Where it lives instead:**
- Evidence page: "Strategy Comparison" section, with brief explanation of why each variant is worse
- Research Archive: full performance table with all metrics

**What replaces it on homepage:**
One line: "Testing showed that the five-layer approach outperforms single-layer approaches."

Or nothing. Just don't mention variants.

---

## 5. ARCHITECTURE DIAGRAMS

**What it is:** A box-and-arrow diagram showing: GPT-4 → Anti-anchoring → Calibration → Sizing → Routing → Safety → Trade execution.

**Why it should move:**
- Readers want to know "does it work?" not "how is it built?"
- Diagrams are great for builders, not for first-time visitors
- Can look overly technical and scare away non-technical readers

**Where it lives instead:**
- "How It Works" page: simple 5-block diagram (no arrows, just labels: "Bias | Calibrate | Size | Route | Safety")
- Research Archive: full architecture diagram with detailed specs
- GitHub: code and documentation

**What replaces it on homepage:**
"The system has five layers: remove bias, calibrate, size positions, route by market type, and stop at circuit breakers."

---

## 6. KELLY FRACTION OPTIMIZATION DETAILS

**What it is:** Detailed math or tables showing: optimal Kelly fraction is 23.5%, we use 25%, here's the sensitivity analysis.

**Why it should move:**
- Kelly criterion is not understood by most readers
- Optimization details are not relevant to "does this work?"
- Belongs in research, not homepage

**Where it lives instead:**
- "How It Works" page: one sentence "We use a quarter-Kelly position sizing approach to balance growth and safety."
- Research Archive: full Kelly criterion derivation, sensitivity analysis, why quarter-Kelly was chosen

**What replaces it on homepage:**
"We size positions carefully to balance return and ruin risk."

---

## 7. BRIER SCORE DETAILS

**What it is:** A detailed explanation of Brier score (mean squared error of probabilities), how ours compares to baseline, statistical significance tests.

**Why it should move:**
- Brier score is a technical metric
- "12% better than random" sounds boring compared to "68.5% win rate"
- Needs statistical explanation
- Not a key differentiator

**Where it lives instead:**
- Evidence page: one paragraph "Our predictions are about 12% more accurate than random baseline (Brier score: 0.22 vs. 0.25)."
- Research Archive: full technical section on accuracy metrics

**What replaces it on homepage:**
Nothing. Win rate is clearer. "68.5% correct predictions" is more intuitive than Brier scores.

---

## 8. LIVE TRADING PERFORMANCE DASHBOARD (real-time metrics)

**What it is:** A live panel showing: trades entered today, current P&L, win streak, drawdown %, etc. Updates in real time.

**Why it should move:**
- 17 trades is too small a sample. Daily updates will be noise.
- "Realized P&L: $0" is honest but not exciting
- Tempts people to check obsessively (bad for perception)
- Could look like we're trying to convince with real-time metrics (marketing tactic)

**Where it lives instead:**
- Separate "Live Trading" page (if we have live returns to show) with monthly updates, not daily
- Eventually, when we have 100+ trades, a performance table with meaningful statistics
- GitHub: raw trade data for anyone to analyze

**What replaces it on homepage:**
One sentence: "Live trading is underway. 17 trades entered. Results pending."

Or just don't mention live trading on the homepage. Save it for Evidence page.

---

## 9. RESEARCH DISPATCH QUEUE

**What it is:** A real-time list of which markets the system is actively forecasting, what confidence levels it assigned, what trades are pending execution.

**Why it should move:**
- Operational details, not relevant to "does this work?"
- Could leak strategic information to competitors
- Tempts obsessive monitoring
- Changes too rapidly to be useful on a homepage

**Where it lives instead:**
- GitHub: raw dispatch logs for transparency
- Monitoring dashboard (internal): real-time feed for operators
- Not on the public website

**What replaces it:**
Nothing. Just remove it.

---

## 10. COMPETITOR ANALYSIS DETAILS

**What it is:** A detailed comparison of our system vs. other market prediction systems (crypto bots, hedge fund quant systems, retail prediction platforms).

**Why it should move:**
- Makes us look defensive ("we need to prove we're better")
- Competitors are building the same thing, so comparison is temporary
- Could look like we're obsessing over competition (bad signal)
- If we list competitors, readers just follow them instead

**Where it lives instead:**
- Research Archive: one section "Competitive Landscape" with honest assessment
- GitHub issues: "Known alternatives" discussion for builders

**What replaces it on homepage:**
Nothing. Definitely don't start with "We're better than X."

---

## SUMMARY: WHAT SHOULD BE ABOVE THE FOLD

**Homepage should show:**

1. **Plain-English thesis** (one sentence)
2. **Backtest result** (68.5% win rate, context)
3. **What we built** (five layers, simple description)
4. **What we know and don't know** (the honest part)
5. **The mission** (veteran suicide prevention)
6. **Roadmap** (what's next)
7. **How to learn more** (choose your depth)

**Everything else goes below or to other pages.**

---

## VISUAL STYLE FOR ABOVE-THE-FOLD CONTENT

**Good:**
- Text-first design
- Honest numbers with caveats
- Simple diagrams (not architecture diagrams)
- Links to deeper content

**Bad:**
- Monte Carlo charts
- Real-time dashboards
- Strategy comparison tables
- Competitor comparisons
- Terminal screenshots
- Oversized ARR numbers

---

## IMPLEMENTATION CHECKLIST

- [ ] Remove "+6,007% ARR" from homepage
- [ ] Remove Monte Carlo fan chart from above fold (move to Evidence)
- [ ] Simplify calibration discussion (one sentence on homepage)
- [ ] Move strategy comparison table to Evidence page
- [ ] Replace architecture diagram with 5-block simple layout
- [ ] Remove Kelly optimization details from homepage copy
- [ ] Remove Brier score from primary narrative
- [ ] Don't build live dashboard for public site
- [ ] Don't expose dispatch queue on public site
- [ ] Don't start with competitor analysis

---

## WHY THIS MATTERS

Above-the-fold real estate is scarce. Every element that appears there competes for attention. Elements that are technical, detail-oriented, or marketing-like (especially live dashboards and sky-high ARR numbers) send the signal: "This is either too complex or too much hype."

By demoting these elements and replacing them with plain-English, honest explanations, we signal: "This is real research. We know what we don't know. You can trust us to be truthful."

That's the goal.

