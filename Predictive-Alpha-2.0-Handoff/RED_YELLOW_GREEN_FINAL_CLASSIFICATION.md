# RED / YELLOW / GREEN FINAL CLASSIFICATION

## Overview

This document provides a simple visual classification of every claim we've made about Predictive Alpha 2.0.

**RED** = Keep entirely off homepage and investor materials. Appendix only, with heavy disclaimers.
**YELLOW** = Okay deeper on the website or in detailed investor documents, but ONLY with caveats and context.
**GREEN** = Safe for homepage. Honest and defensible.

---

## THE COLOR MATRIX

| # | Claim | Color | Visibility | Reasoning | Homepage Language |
|----|-------|-------|------------|-----------|-------------------|
| 1 | 532 markets backtested | 🟢 **GREEN** | Homepage | Factual, verifiable, cool | "We've tested our model on 532 historical markets" |
| 2 | 68.5% calibrated win rate (OOS) | 🟡 **YELLOW** | Deeper pages only | True but only 1 test period; can be misunderstood | With caveat: "...in historical backtests on 2024 data" |
| 3 | 70.2% NO win rate | 🔴 **RED** | Appendix/research only | Cherry-picked category; overfitting signal | Reframe: "Better on underdogs, aligns with academic research" |
| 4 | +$276 simulated P&L | 🔴 **RED** | Research appendix | No slippage; midpoint-only pricing | Don't advertise (belongs in technical details) |
| 5 | Platt scaling Brier 0.239→0.2451 | 🔴 **RED** | Research appendix | Barely beats random (0.25); don't tout mediocrity | Don't mention publicly |
| 6 | 0% ruin probability (Monte Carlo) | 🔴 **RED** | KILL IMMEDIATELY | False confidence; assumes away real risks | Never mention again |
| 7 | +6,007% ARR | 🔴 **RED** | KILL IMMEDIATELY | Snake oil math; violates every real assumption | Remove from all materials |
| 8 | +124% to +872% ARR range | 🔴 **RED** | KILL IMMEDIATELY | Meaningless range; proves uncertainty | Remove from all materials |
| 9 | Quarter-Kelly +309% outperformance | 🔴 **RED** | Research appendix | Confuses leverage with edge | Reframe as "position sizing, not strategy" |
| 10 | Anti-anchoring +25.7% edge divergence | 🔴 **RED** | Research appendix | Feature importance on same data used for training | Don't mention to non-technical audience |
| 11 | Category routing improves win rate | 🟡 **YELLOW** | Deeper pages with caveat | True but assumes category strength persists | With: "...in historical backtests; we validate live" |
| 12 | NO-bias exploits favorite-longshot | 🟡 **YELLOW** | Deeper pages with context | Academic finding (known, not proprietary); fits narrative | With: "...well-documented bias; we're exploiting known misprice" |
| 13 | Weather arbitrage structural edge | 🔴 **RED** | Research roadmap only | Completely untested; vaporware | Remove from claims; put on roadmap |
| 14 | Multi-model ensemble improves accuracy | 🔴 **RED** | Research roadmap only | Skeleton code only; unvalidated | Remove from claims; put on roadmap |
| 15 | Paper trading running on VPS | 🟢 **GREEN** | Homepage | Live, real money, 17 trades | "Testing with real trades on Polymarket" |
| 16 | Safety rails operational (6 types) | 🟢 **GREEN** | Homepage | Actually deployed; important feature | "We built 6 safeguards to prevent large losses" |
| 17 | 42 research dispatch prompts | 🟡 **YELLOW** | "Our approach" section only | True but implementation detail; avoid overselling | "42 automated research tasks to iterate improvements" |
| 18 | Agentic RAG, market-making, cross-platform | 🔴 **RED** | Roadmap/future only | Purely aspirational; no code or timeline | Move to "Future Research" section |
| 19 | Profits fund veteran suicide prevention | 🟡 **YELLOW** | Deeper pages with caveat | True commitment but no profits yet | With: "...once/if we generate profits" (explicit) |
| 20 | $75 seed + $1,000/week deployment | 🟢 **GREEN** | Homepage | Verifiable, shows skin in game | "Seed-funded operation reinvesting ~$1,000/week" |

---

## VISUAL SUMMARY

### GREEN CLAIMS (Safe for Homepage)
✓ 532 markets backtested
✓ Paper trading on VPS (17 trades, real money)
✓ Safety rails operational (6 types)
✓ $75 seed + $1,000/week reinvestment

**Total: 4 claims** — These are your homepage foundation.

---

### YELLOW CLAIMS (Deeper Site, With Caveats)
~ 68.5% calibrated win rate (with "historical backtest" caveat)
~ 70.2% NO win rate (reframed as academic pattern exploitation)
~ Category routing (with "validated live" caveat)
~ NO-bias academic finding (with "known pattern" context)
~ 42 research prompts (brief mention, not emphasizing)
~ Veteran charity (with "once we profit" caveat)

**Total: 6 claims** — These can appear in deeper materials (research, investor deck) with explicit caveats.

---

### RED CLAIMS (Keep Off Marketing)
✗ 70.2% NO win rate (specific category overfitting)
✗ +$276 simulated P&L (no slippage modeling)
✗ Platt scaling 0.239→0.2451 (barely beats random)
✗ 0% ruin probability (false confidence)
✗ +6,007% ARR (snake oil math)
✗ +124% to +872% ARR range (meaningless)
✗ Quarter-Kelly +309% (leverage, not edge)
✗ Anti-anchoring +25.7% (data leakage)
✗ Weather arbitrage edge (untested)
✗ Multi-model ensemble (skeleton only)
✗ Agentic RAG, market-making (vaporware)

**Total: 11 claims** — These belong in research notebooks, not marketing materials.

---

## HOMEPAGE HIERARCHY (GREEN + YELLOW with Caveats)

### Above the Fold (Hero Section)
1. **Headline claim**: "Building prediction market trading systems"
2. **Subheading**: "Testing with real money. Showing real results. Being honest about uncertainty."
3. **Honesty box** (pick one version from HONESTY_BOX_COPY.md)

### Section 1: "What We Built"
- 532 markets backtested ✓ GREEN
- 6 safety systems ✓ GREEN
- 42 research tasks ~ YELLOW (brief mention)
- Paper trading 17 trades ✓ GREEN

### Section 2: "Early Results"
- Real trades: 17 placed, $68 deployed ✓ GREEN
- Markets resolved: 0 (waiting) ✓ GREEN
- Realized P&L: $0 (too early to judge) ✓ GREEN
- Status: Proof-of-concept phase ✓ GREEN

### Section 3: "What Backtests Show"
- 68.5% accuracy on historical test data ~ YELLOW (with caveat: "historical ≠ future")
- Better on underdog ("No") predictions ~ YELLOW (with caveat: "well-documented academic pattern")
- Strategy: category routing ~ YELLOW (with caveat: "validated in backtests; live validation underway")

### Section 4: "What We Know We Don't Know"
- All projections are theoretical ✓ HONEST
- Win rates will drift from backtests ✓ HONEST
- Edge may decay as competition learns ✓ HONEST
- Regulatory environment is uncertain ✓ HONEST
- Model may overfit to 2024 data ✓ HONEST

### Section 5: "What's Next"
- Live validation (50+ resolved trades) ✓ GREEN
- Multi-platform expansion ✓ GREEN
- Slippage & fee modeling ✓ GREEN
- Alternative data sources ✓ GREEN (research in progress)
- Roadmap items (agentic, multi-model, market-making) ~ YELLOW (explicitly mark as "future research")

### Section 6: "Commitment"
- Seed-funded operation ✓ GREEN
- Reinvesting ~$1,000/week ✓ GREEN
- Future veteran charity ~ YELLOW (with "once we profit")

---

## WHAT TO KILL IMMEDIATELY

These should be removed from ALL materials (including internal):

1. **"+6,007% ARR"** — Delete. Replace with "We're researching prediction markets; early backtests suggest upside but we don't project returns yet."

2. **"0% Ruin Probability"** — Delete. Replace with "We monitor drawdowns and have circuit breakers. Max historical backtest drawdown was X%."

3. **"+124% to +872% Range"** — Delete. Ranges this wide mean "we don't know." Either give one conservative number or don't give a number.

4. **"70.2% NO Win Rate" (as featured claim)** — Delete from marketing. Move to appendix if at all. Reframe as "we exploit underdogs being underpriced (known academic pattern)."

5. **"Proprietary Edge"** — Delete. You don't have one. Favorite-longshot bias is 60 years old. What you have is disciplined execution.

6. **"Beat the Market"** — Delete. Polymarket is a niche, not "the market." You're not beating equities or forex. You're trading small prediction markets.

---

## UPDATED HOMEPAGE LAYOUT MOCKUP

```
┌─────────────────────────────────────────────────────────────────┐
│                     PREDICTIVE ALPHA 2.0                        │
│   Testing Prediction Market Trading with Real Money             │
│                                                                 │
│  [Honesty Box: Pick one version from HONESTY_BOX_COPY.md]      │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ WHAT WE BUILT                                                   │
│ • 532 historical markets tested                                 │
│ • 6 safety systems (max-loss, position limits, circuit breakers)│
│ • 42 research tasks for continuous improvement                  │
│ • Paper trading with real money on Polymarket                   │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ EARLY RESULTS (Paper Trading)                                   │
│ • 17 trades placed | $68 deployed | $0 resolved P&L             │
│ • Waiting for market resolution (statistical validation in      │
│   progress; need 50+ resolved markets for confidence)           │
│ • What we've learned so far: [link to research notes]           │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ WHAT BACKTESTS SHOW                                             │
│ • 68.5% accuracy on historical test data (2024)                 │
│ • Better performance on underdogs ("No" predictions)            │
│   - This aligns with 60+ years of academic research on          │
│     favorite-longshot bias; it's a known market pattern         │
│ • Caveat: Backtests assume midpoint pricing & no slippage;      │
│   real trading costs more                                       │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ WHAT WE'RE DOING NEXT                                           │
│ • Validate strategy on 50+ live resolved markets                │
│ • Model realistic slippage & fees                               │
│ • Expand to alternative platforms (Manifold, Kalshi)            │
│ • Research alternative data sources (weather, sentiment)        │
│ • [Roadmap: Agentic research, multi-model ensemble]             │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ OUR COMMITMENT                                                  │
│ • Seed-funded (~$75) + reinvesting ~$1,000/week                 │
│ • We're putting our own money down                              │
│ • Future profits → veteran suicide prevention support           │
│ • Details & risk assessment: [links to full materials]          │
└─────────────────────────────────────────────────────────────────┘
```

---

## FOR INVESTOR MEETINGS

### What to Show (Confident)
- The 4 GREEN claims (backtests, live trading, safety, funding)
- Honest metrics (17 trades, $0 resolved, 2 cycles)
- Failure modes list (shows you've thought about what can go wrong)
- Post-mortems and learnings (shows rigor)

### What to HIDE (or heavily caveat)
- ALL RED claims (they'll be skeptical anyway)
- ARR projections (they'll ask "where's the proof?")
- Monte Carlo simulations (they know it's garbage-in-garbage-out)
- Any claim that sounds too good to be true (because it is)

### What to EMPHASIZE
- Honesty and transparency (these are rare in trading)
- Edge decay awareness (shows you know markets)
- Failure modes catalog (shows risk management thinking)
- Live validation plan (shows discipline)
- Capital efficiency (bootstrapping, not burning investor money)

---

## FOR SOCIAL MEDIA / PR

### Shareable Claims (GREEN)
- "We've tested our model on 532 prediction markets"
- "Building 6 safety systems to prevent large losses"
- "Paper trading with real money on Polymarket"
- "Reinvesting seed capital for early validation"

### NOT Shareable (Don't post these)
- Any return projection (+6,007%, +124-872%)
- "0% ruin probability" (sounds like snake oil)
- "Proprietary edge" (you don't have one)
- "Beat the market" (overselling)

### Story Angle (Honest & Compelling)
"We're rebuilding trading from first principles: no hype, just honest testing. We have no profits yet. All our claims are based on backtests, which lie. So we're validating with real trades on real markets with real money. Progress: 17 trades, $0 profit. Come back in 6 months."

---

## FINAL DECISION TREE: Can We Say This?

**If a claim is not on GREEN list, ask:**

1. Have we tested this in live trading?
   - If NO → It's RED (unless it's clearly aspirational like "roadmap")

2. Is it based on a single test period (2024 only)?
   - If YES → It's at best YELLOW, not GREEN

3. Does it assume no slippage, no fees, or perfect execution?
   - If YES → It's RED

4. Would a skeptic in an adversarial meeting challenge it?
   - If YES → It's YELLOW at best (needs caveat)

5. Is it a number that sounds too good?
   - If YES (e.g., +6,007%) → It's RED

6. Does it rely on Monte Carlo or simulation?
   - If YES → It's RED unless clearly labeled as simulation

7. Is there a real-world precedent of this being wrong?
   - If YES → It's RED or YELLOW (needs caveat)

8. Would we defend this on a podcast with a skeptical host?
   - If NO → It's RED

9. Is it based on something we actually built and tested?
   - If YES → It's GREEN or YELLOW
   - If NO → It's RED

10. Can we point to actual evidence (trades, code, logs)?
    - If NO → It's RED

---

## FINAL CHECKLIST BEFORE PUBLISHING

- [ ] No GREEN claim is overstated
- [ ] All YELLOW claims have visible caveats
- [ ] All RED claims are completely removed from homepage
- [ ] Honesty box is prominent (not buried)
- [ ] Caveats are understandable (not jargon)
- [ ] Skeptic would find it fair (honest test)
- [ ] We can defend every claim on a podcast
- [ ] We've removed all return projections (except in appendix with disclaimers)
- [ ] We've removed "0% ruin" and "proprietary edge"
- [ ] Early results are highlighted (17 trades, $0 realized, waiting for validation)

---

## SUMMARY: THE THREE BUCKETS

**GREEN (Homepage Safe)**
- 4 defensible, verified claims
- Can be challenged and we win
- Based on real implementation or simple facts
- No return projections
- No false confidence

**YELLOW (Deeper Site, With Caveats)**
- 6 claims that are true but need context
- Every one must have a caveat sentence visible
- Belong in investor decks or research sections
- Not on homepage unless with major disclaimer

**RED (Kill Immediately)**
- 11 claims based on backtests, simulations, or assumptions
- No place in marketing materials
- Belong in research appendix only
- Would trigger skeptical pushback

**The goal: Build credibility by being honest. You'll attract better investors, partners, and team members.**
