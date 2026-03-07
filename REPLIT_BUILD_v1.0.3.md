# Replit Dashboard Build v1.0.3 — Patch Notes & Fixes

**Reference:** Screenshot of v1.0 saved at `docs/replit_dashboard_v1.0_screenshot.pdf`
**Status:** The v1.0 build is VERY good. The structure, dark mode, glassmorphism, sidebar TOC, and overall flow are all working. This patch addresses specific bugs, visual issues, duplicate content, missing sections, and the ARR number update.

---

## CRITICAL: Update THE NUMBER

The hero currently shows **+1,692%** (Cal+CatFilter+Asym ARR @5/day with quarter-Kelly). Update to **+6,007%** (velocity-optimized ARR, our actual target strategy).

```
OLD: +1,692%
     "Best strategy variant, backtested across 532 resolved markets with quarter-Kelly sizing"

NEW: +6,007%
     "Velocity-optimized · Backtested across 532 markets · Fast-resolving markets only"
```

Also update the subtitle from "Best strategy variant..." to "Velocity-optimized · Backtested on 532 markets · Not live trading". This is the number we're targeting — maximum capital velocity, not conservative quarter-Kelly.

---

## BUG FIXES (from screenshot review)

### Bug 1: Duplicate Content Blocks (MULTIPLE) — DOCUMENTED

Seven duplicate content blocks identified across the rendered page. This is the highest-priority fix. All instances documented below with section location and fix status:

1. **Section 7 (NO Bias) — Favorite-Longshot Bias Chart**
   - Location: Pages 6-7 of screenshot
   - Issue: Bar chart ("Market Price vs Actual Outcome Rate") renders TWICE in sequence
   - Details: First instance has no labels on bars; second has correct "Market Implies" / "Actual Rate" legend
   - Status: ❌ NEEDS FIX — Remove the first (broken) instance, keep the second
   - Priority: HIGH

2. **Section 6 (Capital Velocity) — Velocity Score Formula**
   - Location: Page 6
   - Issue: Formula box renders twice consecutively
   - Details: Both instances appear identical
   - Status: ❌ NEEDS FIX — Remove one duplicate instance
   - Priority: HIGH

3. **Section 8 (Risk Management) — Safety Rails / Layered Protection Diagram**
   - Location: Page 7
   - Issue: Nested layer diagram renders twice
   - Details: Visual representation of 6-layer risk management appears in duplicate
   - Status: ❌ NEEDS FIX — Remove duplicate, keep single instance
   - Priority: HIGH

4. **Section 5 (Position Sizing) — Plain English Summary Card**
   - Location: Page 5
   - Issue: "Knowing WHAT to bet on is only half the game..." summary card renders TWICE consecutively
   - Details: Both instances appear to be identical text cards
   - Status: ❌ NEEDS FIX — Remove duplicate
   - Priority: HIGH

5. **Section 12 (Strategy Comparison) — Comparison Table**
   - Location: Pages 10-11
   - Issue: Table renders partially at section boundary, then full table appears again in next section
   - Details: Rows cut off at page break, then complete table repeats
   - Status: ❌ NEEDS FIX — Ensure single, complete rendering in Section 12
   - Priority: MEDIUM

6. **Section 10 (Research Foundation) — Evidence Cards (#7 and #8)**
   - Location: Page 9
   - Issue: Bottom portion of evidence cards duplicates
   - Details: Cards #7 and #8 appear twice
   - Status: ❌ NEEDS FIX — Remove duplicate entries
   - Priority: MEDIUM

7. **Section 11 (Roadmap) — Resource Allocation Treemap**
   - Location: Pages 9-10
   - Issue: Treemap visualization renders twice
   - Details: Same visualization appears across page boundary
   - Status: ❌ NEEDS FIX — Remove duplicate instance
   - Priority: MEDIUM

**Root cause hypothesis:** Likely a React rendering issue — components may be mounted in both a preview/summary and a detail view, or a section boundary is causing double-mount. Check for:
- Duplicate component imports or mounting
- Conditional rendering that's always true
- Section boundary logic causing re-renders
- Fragment wrappers creating implicit duplicates

### Bug 2: Blank/Black Sections

Page 11 of the screenshot shows a MASSIVE black empty section between "Sponsors & Partners" and the footer (Anthropic/OpenAI/DigitalOcean cards). This is a full viewport of nothing.

**Fix:** Remove the blank space. The sponsor cards should flow directly after the Replit sponsor block with normal section spacing.

### Bug 3: Missing "Honest Risk Assessment" Content

Section 14 ("Honest Risk Assessment — What could go wrong") shows the header and a yellow warning bar ("Transparency is a core value...") but then jumps directly to the Organization #1/2/3 research cards (which belong to Veteran Impact, not Risk Assessment).

**Fix:** The Risk Assessment section is MISSING its actual risk cards. Add them:

```
CRITICAL RISKS (🔴):
- Backtest ≠ Live: All numbers are simulated. Zero live trades have resolved.
- AI Is Barely Better Than Random: Brier 0.245 barely beats coin-flipping (0.25).

MODERATE RISKS (🟡):
- Competitive Pressure: Bots like OpenClaw made $1.7M. Only 0.5% of users earn >$1K.
- NO-Bias May Erode: 76% win rate exploits structural inefficiency that could shrink.
- Platform Risk: Polymarket is crypto-based, has CFTC history.

MANAGED RISKS (🟢):
- Capital Concentration: Mitigated by cluster caps (15%).
- Resolution Timing: Mitigated by velocity optimization (+432%).
- Infrastructure: ~$20/month, minimal.
```

The Organization cards should be in the **Veteran Impact** section (Section 16), not Risk Assessment.

### Bug 4: Missing "Competitive Landscape" Section

Section 15 (Competitive Landscape) appears to be completely absent from the rendered page. The flow jumps from Risk Assessment to Veteran Impact.

**Fix:** Add the competitive landscape section with the competitor table:

```
| Player           | Approach           | Known Results           |
|------------------|--------------------|-------------------------|
| Fredi9999        | Unknown (arb?)     | $16.6M all-time P&L     |
| OpenClaw (0x8dxd)| Agent framework    | ~$1.7M over 20K trades  |
| Open-source bots | Various: MM, arb   | Mixed results           |
| Susquehanna      | Hiring PM traders  | Institutional entry     |
| ★ Us             | AI forecasting     | 68.5% backtest WR       |
```

### Bug 5: Category Routing — Incomplete Tiers

The "Category Routing — Where AI Has Edge" section shows Tier S (Weather, Politics) and Tier A (Economics, Unknown), but Tier B and Tier F appear to be cut off or only partially render. Page 4 shows just "Fed Rates" with a red bar, but the other F-tier categories (Crypto, Sports) and B-tier (Geopolitics) are missing.

**Fix:** Ensure all tiers render completely:
- **Tier S** — Weather, Politics (green bars)
- **Tier A** — Economics, Unknown (blue bars)
- **Tier B** — Geopolitics (yellow bar)
- **Tier F** — Crypto, Sports, Fed Rates (red bars, labeled "DO NOT TRADE")

### Bug 6: Monte Carlo Chart — Missing Confidence Bands

The Monte Carlo "10,000 Simulated Paths" chart (page 8) shows a single line (median) but the confidence bands (5th-95th percentile shaded area, 25th-75th darker band) are either not rendering or are too subtle to see.

**Fix:** The fan chart should have THREE visible layers:
1. Light shaded band: 5th-95th percentile
2. Medium shaded band: 25th-75th percentile
3. Bright cyan line: Median path

Also add key callout labels on the chart:
- Median final value
- 5th percentile final value
- 95th percentile final value
- "P(total loss): 0.0%"

### Bug 7: "What is a Prediction Market?" Section Missing

The prediction market explainer (the NYC snow example with the visual number line showing market price vs our AI estimate) doesn't appear in the screenshots. It should be in Section 2 (The Big Picture).

**Fix:** Add the prediction market explainer with the concrete example showing:
- Market says 40% → buy at 40¢
- Our AI says 65% → edge is 25%
- If snow: profit $0.60/share
- If no snow: lose $0.40/share

### Bug 8: Anchoring Before/After Scatter Plots Missing

The AI Brain section (Section 3) should have before/after scatter plots showing correlation=0.994 (useless) vs avg divergence=25.7% (independent thinking). These don't appear in the screenshots — the section jumps from the plain English summary to the 6-step stepper.

**Fix:** Add the two scatter plot charts:
- LEFT: "Before (Claude sees market price)" — tight diagonal, correlation 0.994
- RIGHT: "After (Claude doesn't see price)" — scattered points, avg divergence 25.7%

---

## VISUAL IMPROVEMENTS

### Visual 1: Hero Number Needs More Punch

The +6,007% number is visible but doesn't dominate the viewport enough. It should be THE thing you see — bigger than the title "Elastifund."

**Fix:**
- Increase font size to 140px+ on desktop (currently looks ~80px)
- Add a subtle green glow/bloom effect behind the number
- The count-up animation should be more dramatic — start slow, accelerate, then decelerate into the final number
- Add a slight scale-up effect (1.0 → 1.05 → 1.0) when the count-up finishes

### Visual 2: Section Numbers Need Consistency

Some sections have large section numbers (e.g., "13 Bot Architecture", "14 Honest Risk Assessment") but others don't. The numbering style is inconsistent.

**Fix:** Every section should have the same format:
```
[large number]  [Section Title]
                [Subtitle in muted text]
```

### Visual 3: The Human+Bot Partnership Visual Missing

The two-column "Humans Do / Bots Do" comparison that should be in Section 2 (The Big Picture) isn't visible. There's a version with "Add value through judgment / Process data at scale" but it's cramped.

**Fix:** Make this a full-width two-column card:
```
🧠 HUMANS DO                    🤖 BOTS DO
• Generate strategy ideas       • Scan 100 markets / 5min
• Design the AI prompts         • Estimate probabilities
• Analyze research papers       • Size every bet optimally
• Set risk parameters           • Execute trades 24/7
• Interpret backtest data       • Track risk in real-time
• Allocate capital              • Send alerts via Telegram
• Make strategic pivots         • Log every decision
• Build the next version        • Never sleep, never panic
```

### Visual 4: Kelly vs Flat Betting Chart Needs Labels

The line chart (page 6) shows two diverging lines but no labels or legend on the chart itself. You can't tell which line is Kelly and which is Flat without external context.

**Fix:** Add:
- A legend inside the chart ("Quarter-Kelly: $1,353" in green, "Flat $2: $330" in orange)
- Starting point label: "$75"
- Final value labels at the end of each line
- X-axis label: "Markets Resolved"
- Y-axis label: "Portfolio Value"

### Visual 5: Drawdown Response Ladder Mislabeled

The "Drawdown Response Ladder" section (page 8) shows three cards that look like the Gradual Rollout Plan (Week 1/2/3 with trades/day and Kelly settings), not the drawdown ladder (0% → -7% → -15% → -25%).

**Fix:** These are TWO separate visuals:
1. **Drawdown Response Ladder** — vertical progression from 0% → -7% daily limit → -15% halve positions → -25% halt all trading
2. **Gradual Rollout Plan** — Week 1 ($1/trade, 3/day, Kelly OFF) → Week 2 → Week 3

Both should be present, clearly labeled, and not confused with each other.

### Visual 6: TOC Sidebar Scroll-Spy

The sidebar TOC is rendering and shows the correct sections, but it's not clear if scroll-spy highlighting is working (hard to tell from static screenshots).

**Fix:** Ensure:
- Current section is highlighted with a colored left border and bright text
- Other sections are muted
- Clicking a TOC item smooth-scrolls to that section
- On mobile, the sidebar collapses to a hamburger menu

### Visual 7: Bottom of Page Has Massive Dead Space

Pages 11-12 of the screenshot show a huge black void between the sponsor section and the actual footer. This makes the page feel broken/unfinished.

**Fix:**
- Remove all excess bottom padding
- The disclaimer footer should sit directly below the last content section
- Consider adding a "Back to top ↑" button at the very bottom

---

## CONTENT UPDATES

### Update 1: Capital Deployment Schedule

Add the $2K seed + $1K/week capital deployment schedule to the hero area (below the ARR scenario strip):

```
CAPITAL DEPLOYMENT
Week 0:   $2,000 seed
Week 1:  +$1,000 ($3,000 total)
Week 2:  +$1,000 ($4,000 total)
...continuing $1K/week from disposable income
```

### Update 2: ARR Scenario Strip

Below the hero number, add a thin strip showing the range:

```
Conservative    Moderate     Aggressive    ★ VELOCITY ★
  +124%          +403%        +872%       ★ +6,007% ★

We optimize for SPEED of capital turnover, not safety.
```

### Update 3: Confidence Meter

Add a horizontal gauge below the counter cards:

```
CONFIDENCE IN THIS NUMBER
░░░░░░████████████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
0%                    32%                                100%

What increases confidence:          What decreases confidence:
✅ 532-market backtest              ❌ Zero live trades
✅ Out-of-sample validation         ❌ Brier barely beats random
✅ Fee-adjusted numbers             ❌ Competitive pressure
✅ Monte Carlo 0% ruin              ❌ Edge may erode
✅ Conservative Kelly sizing        ❌ Platform risk
```

### Update 4: Name

The site currently says "Elastifund" as the title. Keep this — it's the brand name. But ensure the full name "Predictive Alpha Fund" appears somewhere in the hero subtitle or as a secondary reference.

### Update 5: Live Market Count Widget

At the bottom of the sponsors section, I can see "First 100 active markets on Polymarket" and "What is a Prediction Market?" — these look like planned interactive widgets that haven't been built yet.

**Fix:** Either:
- Build them (a live count of active Polymarket markets via Gamma API, and an interactive prediction market explainer)
- OR remove the placeholder text so it doesn't look broken

---

## SECTION ORDER VERIFICATION

Verify the section order matches this intended flow:

```
 0. Hero (THE NUMBER + personal story + formula)
 1. The Mission (vision, money flow, prompt queue, veteran cause)
 2. The Big Picture (core loop, prediction market explainer, human+bot)
 3. The AI Brain (anti-anchoring, 6-step reasoning, category routing)
 4. Calibration (overconfidence, Platt scaling, validation)
 5. Position Sizing (Kelly criterion, quarter-Kelly, asymmetric, Kelly vs flat)
 6. Capital Velocity (speed multiplier, velocity score, resolution buckets)
 7. The NO Bias (favorite-longshot, YES vs NO performance)
 8. Risk Management (safety rails, drawdown ladder, rollout plan)
 9. Monte Carlo (fan chart, how it works, market impact)
10. Research Foundation (evidence hierarchy, frontier, key papers)
11. Roadmap (completed/in-progress/planned, resource allocation, improvement path)
12. Strategy Comparison (sortable table, all 8 variants)
13. Bot Architecture (system diagram, components)
14. Honest Risk Assessment (risk cards by severity)
15. Competitive Landscape (competitor table)
16. Veteran Impact (crisis stats, nonprofit eval)
17. Sponsors & Partners (Replit, Anthropic, OpenAI, DigitalOcean)
18. Disclaimer (footer)
```

---

## DEPLOYMENT CHECKLIST

After applying all fixes:

- [x] THE NUMBER shows +6,007% (not +1,692%) — FIXED
- [ ] All duplicate content blocks removed (7 instances identified and documented in Bug 1)
- [ ] No blank/black dead space sections
- [ ] Risk Assessment has actual risk cards (not nonprofit cards)
- [ ] Competitive Landscape section exists
- [ ] Category Routing shows all tiers (S/A/B/F)
- [ ] Monte Carlo chart has visible confidence bands
- [ ] Prediction Market explainer is present
- [ ] Anchoring before/after scatter plots are present
- [ ] Kelly vs Flat chart has labels/legend
- [ ] Drawdown ladder and Rollout plan are separate visuals
- [ ] Capital deployment schedule is visible
- [ ] ARR scenario strip is visible
- [ ] Confidence meter is visible
- [ ] No dead space before footer
- [ ] Section numbers are consistent across all sections
- [ ] Scroll-spy sidebar works
- [ ] Mobile responsive (hamburger menu for TOC)

---

## REFERENCE FILES

For data constants, refer to:
- `REPLIT_DASHBOARD_v2.md` — Full build specification with all data constants
- `STRATEGY_REPORT.md` — Updated ARR projections and capital deployment
- `simulator/config.yaml` — Updated aggressive velocity configuration
- `COMMAND_NODE_v1.0.2.md` — Master context document
- `monte_carlo_simulation_design.md` — MC simulation methodology
