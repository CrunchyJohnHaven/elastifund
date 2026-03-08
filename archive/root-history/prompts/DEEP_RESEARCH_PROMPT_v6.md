# DEEP RESEARCH PROMPT v6.0 — Combinatorial Arb: GO/NO-GO Evidence
**Date:** 2026-03-07
**For:** ChatGPT Pro Deep Research / Claude Deep Research
**From:** JJ (Elastifund Principal)
**Focus:** A-6 (Multi-Outcome Sum Violation Scanner) + B-1 (LLM Combinatorial Dependency Graph)
**Dispatch:** #80

---

## WHAT THIS RESEARCH DECIDES

Two combinatorial arbitrage strategies rank #1 in our 100-strategy taxonomy at 45% P(Works) each. Before we write code, we need empirical data to make a GO/NO-GO build decision.

**If the data supports it:** Claude Code builds A-6 and B-1 (days 7-21 of our sprint). A separate implementation dispatch follows this research.

**If the data kills it:** We redirect engineering time to A-1 (information-advantaged market making) immediately.

**What this research is NOT:** An implementation specification. Do not produce pseudocode, system architecture, sprint plans, or deployment instructions. Produce DATA, EVIDENCE, and QUANTIFIED ESTIMATES. Tables, not code. Citations, not diagrams.

---

## ATTACHED CONTEXT FILES

| # | File | Instruction |
|---|------|-------------|
| 1 | `CLAUDE.md` | JJ persona, coding standards, current system state. Read for voice and constraints. |
| 2 | `COMMAND_NODE_v1.0.2.md` | Full technical architecture, 6 signal sources, API details. Understand what exists. |
| 3 | `ProjectInstructions.md` | Sprint plan, risk parameters, priority queue. Current execution context. |
| 4 | `EDGE_DISCOVERY_SYSTEM.md` | Hypothesis testing pipeline, kill rules. How we validate/reject strategies. |
| 5 | `FastTradeEdgeAnalysis.md` | Pipeline results (current: REJECT ALL). Where we actually are. |
| 6 | `JJ_ASSESSMENT_DISPATCH_v3.md` | Prioritization decisions, pre-rejected strategies. What's already decided. |

**Do NOT repeat information from these files.** Reference them by name. Your audience has them open.

**Note:** Previous versions of this prompt attached `DEEP_RESEARCH_OUTPUT_v3.md` (178KB, 100-strategy taxonomy). That file is excluded from this package. The relevant strategy specs are inlined below. The other 98 strategies are irrelevant to this research run.

---

## THE TWO STRATEGIES

These are excerpted from our 100-strategy evaluation (v3 research output, March 7, 2026).

### A-6: Multi-Outcome Sum Violation Scanner
Multi-outcome Polymarket markets (e.g., "Who will be the next PM?" with 10 candidates) should have all YES prices sum to $1.00. Due to independent pricing and variable liquidity, sums routinely drift to $0.95-$1.08. When sum < $1.00, buy all outcomes (guaranteed profit). When sum > $1.00, construct NO basket. Academic citation: Saguillo et al. (arXiv:2508.03474, Aug 2025) documented $40M in realized arbitrage profit from this exact type. Kill criterion: average executable spread < 1% after non-atomic execution risk. Honest P(Works): 45%.

### B-1: LLM Combinatorial Dependency Graph
Logical dependencies between markets (e.g., "Trump wins nomination" implies "Republican wins election") create arbitrage when probability constraints are violated (P(A) > P(B) when A subset of B). Use LLM to detect dependencies across all active markets, monitor for violations, execute multi-leg arb. Same IMDEA study: top 3 wallets earned $4.2M combined, primarily from combinatorial strategies. Kill criterion: <3 violations/week exceeding threshold, or LLM classification accuracy <80%. Honest P(Works): 45%.

---

## CURRENT SYSTEM STATE (March 7, 2026)

- **Capital:** $247.51 USDC (Polymarket) + $100 USD (Kalshi) = $347.51
- **Live trading:** ACTIVE on Dublin VPS. LLM analyzer placing maker orders.
- **Signal sources:** 6 operational (LLM Ensemble, Wallet Flow, LMSR, Cross-Platform Arb, VPIN/OFI, Lead-Lag)
- **Execution:** 100% post-only maker orders. Zero taker fees.
- **Latency:** Dublin VPS (eu-west-1) → CLOB (London, eu-west-2) = 5-10ms
- **All 12 taker-based strategy families:** REJECTED. Maker-only is the path forward.
- **Tests:** 345 passing

---

## RESEARCH TARGET 1: MULTI-OUTCOME MARKET EMPIRICS

These questions determine whether A-6 is viable at our scale. For each answer: provide a number, a confidence interval, and a source. If the source is your estimate, state the reasoning explicitly.

**1.1 Market supply.** How many multi-outcome markets (>2 outcomes) are currently active on Polymarket? Break down by outcome count: 3-5 outcomes, 6-10, 11-20, 20+. How many new multi-outcome markets are created per week?

**1.2 Sum violation frequency.** What percentage of multi-outcome markets have |sum(YES_prices) - 1.00| > 3% at any given snapshot? How many qualifying violations occur per day? Per week?

**1.3 Violation magnitude distribution.** When sum violations occur, what is the median size? p75? p90? p99? Is the distribution fat-tailed (a few large violations) or narrow (many small ones)?

**1.4 Correction speed.** How quickly do sum violations self-correct? Seconds (need WebSocket), minutes (need 1-min polling), hours (our 5-min REST polling is adequate), days (easy)?

**1.5 Spread width on thin outcomes.** For low-probability outcomes in multi-outcome markets (e.g., "Candidate Z" at 2%), what is the typical bid-ask spread? A 3% sum violation means nothing if each leg has a 5% spread.

**1.6 Maker fill rate on thin outcomes.** At best-ask minus one tick ($0.01), what fill rate should we expect for $5 maker orders on thin multi-outcome legs? Are we competitive in these books or too small to get filled?

**1.7 Minimum profitable violation threshold.** Given sequential (non-atomic) execution of N legs, price movement between legs, and realistic fill rates — what is the minimum sum violation that yields positive expected profit? Show the calculation.

**1.8 Position merging economics.** When holding YES on all outcomes, merge/redeem yields $1.00. What are current Polygon gas costs for the merge/redeem transaction? At what position size (per outcome) does merging become gas-positive?

**1.9 Seasonal/event patterns.** Do sum violations cluster around specific events (elections, breaking news) or are they uniformly distributed? Is there a time-of-day pattern?

---

## RESEARCH TARGET 2: INTER-MARKET DEPENDENCY EMPIRICS

These questions determine whether B-1 is viable.

**2.1 Dependent pair count.** How many logically dependent market pairs exist on Polymarket right now? Estimate by type: implication (A implies B), mutual exclusion, subset, complementary. Estimate by category: political primaries vs general, sub-events vs parent events, geographic vs national.

**2.2 Probability violation frequency.** Among genuinely dependent pairs, how often does the probability constraint get violated by >2%? >5%? Per day? Per week?

**2.3 LLM classification benchmarks.** Has anyone benchmarked LLM dependency detection on prediction market question pairs? If not, what is the closest proxy benchmark? What accuracy can we realistically expect from Claude Haiku ($0.001/call) vs GPT-4.1-mini vs Llama 3.3?

**2.4 Combinatorial explosion management.** With 300+ active markets, there are ~45,000 possible pairs. What pre-filtering heuristics reduce this to a manageable set? Category matching? Keyword overlap? Resolution date proximity?

**2.5 IMDEA cross-reference.** The Saguillo et al. study reported 7,000+ markets with combinatorial mispricings. What was their false positive rate? What fraction of detected violations were profitably tradeable after execution costs?

**2.6 Pair stability.** Once a dependency is identified, how often does it become stale (market resolves, terms change, new candidates)? What is the expected shelf life of a dependency edge?

---

## RESEARCH TARGET 3: NON-ATOMIC EXECUTION RISK

This is the make-or-break risk for both strategies. Polymarket's CLOB does not support atomic multi-leg orders. Legs execute sequentially, and prices move between them.

**3.1 Price movement rate.** What is the average absolute price movement per second on Polymarket multi-outcome markets? Per 100ms? Distinguish high-volume (>$100K daily volume) vs low-volume (<$10K daily volume) markets.

**3.2 Leg completion time.** If placing N maker orders sequentially via REST API, what is the expected total time from first to last order? Include Polymarket CLOB processing latency and any artificial delays they've introduced. Via WebSocket?

**3.3 Capture rate formula.** Given violation size V, number of legs N, price movement rate M, per-leg fill probability F, and partial fill penalty P — derive or cite a formula for expected capture rate (realized profit / theoretical profit). Provide worked examples for N=5, N=10.

**3.4 Partial fill downside.** For A-6 with 5 outcomes: if 3 legs fill and 2 don't, what is the maximum loss? Is the loss bounded by position size or can it be worse? What about for B-1 with 2 legs where only 1 fills?

**3.5 Relevant literature.** What does equity/options market microstructure literature say about non-atomic multi-leg execution? Find results from:
- Cartea, Jaimungal, Penalva (2015) or similar textbooks
- Any DEX/AMM multi-leg execution papers (2024-2026)
- Blockchain CLOB-specific execution risk analysis

**3.6 IMDEA study execution methods.** How did the top arb wallets actually execute? Simultaneous multi-leg posting? Sequential with hedging? Accept-and-pray? What was their observed capture rate?

---

## RESEARCH TARGET 4: ACADEMIC FOUNDATION

### 4A: Verify and Deep-Dive the Primary Citation

**CRITICAL:** The citation "Saguillo et al., arXiv:2508.03474, Aug 2025" was generated by an LLM in our v3 research output. **Verify that this paper actually exists.** If it does not exist under this exact citation, search for the actual IMDEA/Carlos III prediction market arbitrage study. Report:
- Exact title, authors, and correct citation
- Whether the $40M figure is real or was hallucinated/distorted
- If the paper doesn't exist, what IS the best empirical study on Polymarket arbitrage?

If the paper does exist, go deep:
- Exact methodology for detecting and measuring arbitrage opportunities
- Distribution of arb sizes: median, p90, p99 profit per event
- Time-to-correction after violation detection
- Number of competing bots and their market share of captures
- Did they separately quantify market-rebalancing (A-6) vs combinatorial (B-1)?
- Data collection period and any changes on Polymarket since then

### 4B: Related Academic Work

Search specifically for:
- Dutch book detection in prediction markets (any date, focus on computational methods)
- MECE constraint enforcement on multi-outcome platforms
- Blockchain prediction market microstructure (2024-2026 only)
- Polymarket-specific arbitrage research beyond the IMDEA study
- Multi-leg execution risk in decentralized exchanges (DEX literature, AMM vs CLOB comparison)
- Conformal prediction applied to capture rate uncertainty — can conformal bands on the capture rate distribution inform position sizing?

For each paper found: one-paragraph summary, relevance to A-6/B-1, and a quantitative takeaway if applicable.

---

## RESEARCH TARGET 5: COMPETITIVE LANDSCAPE

**5.1 Current bot activity.** Are multi-outcome sum violations being captured within seconds (fast bot competition, A-6 may be too slow) or persisting for hours (opportunity exists)?

**5.2 Known competitors.** List public tools, open-source bots, or documented traders focused on Polymarket combinatorial arb. What execution infrastructure do they use? What capital scale?

**5.3 Post-fee-change viability.** Polymarket added taker fees (Feb-Mar 2026) and random latency delays to curb bots. How have these changes affected arb profitability specifically for multi-outcome strategies? Are maker orders (which we use) exempt from both changes?

**5.4 Scale disadvantage.** At $5/leg with $247 total capital, are we too small to compete? What is the minimum viable capital for multi-outcome arb? Is there a sweet spot where you're large enough to get fills but small enough to avoid impacting prices?

**5.5 Alpha decay trajectory.** Is there evidence that combinatorial arb opportunities are shrinking as more bots enter? Compare opportunity frequency in 2024 vs 2025 vs 2026 if data available.

---

## OUTPUT FORMAT

```
## Executive Summary (500 words max)
  - GO/NO-GO recommendation for A-6 with confidence level
  - GO/NO-GO recommendation for B-1 with confidence level
  - Top 3 findings that most affect the build decision
  - Critical unknowns that remain after research

## Research Target 1: Multi-Outcome Market Empirics
  - Answer each question (1.1-1.9) with: number, confidence interval, source

## Research Target 2: Inter-Market Dependency Empirics
  - Answer each question (2.1-2.6) with same format

## Research Target 3: Non-Atomic Execution Risk
  - Quantified models or simulation results
  - Literature citations with specific results

## Research Target 4: Academic Foundation
  - 4A: Citation verification result (exists/doesn't exist, correct citation)
  - 4A: Paper deep-dive (if exists)
  - 4B: Related papers table with one-line relevance

## Research Target 5: Competitive Landscape
  - Current state assessment
  - Implications for a $347 capital entrant

## Appendix: Complete Source List
  - Every URL, paper, and dataset referenced
```

**Format rules:**
- Tables > prose for every empirical answer
- Every estimate must include: value, confidence interval, and source
- Flag explicitly: "DATA (from [source])" vs "ESTIMATE (based on [reasoning])"
- No pseudocode, no system architecture, no sprint plans
- If you cannot find data on a question, say so explicitly and provide your best estimate with stated assumptions

---

## COMPANION DOCUMENT NOTE

The implementation specification (API endpoints, pseudocode, state machines, sprint plan) that was in DEEP_RESEARCH_PROMPT_v5 has been extracted into a separate Claude Code dispatch. That dispatch is triggered only IF this research returns a GO decision. Deep Research finds facts; Claude Code writes code. These are different jobs.

---

*This prompt supersedes DEEP_RESEARCH_PROMPT_v5.md. File as Dispatch #80.*
