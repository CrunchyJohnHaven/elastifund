# DEEP RESEARCH PROMPT v5.0 — Combinatorial Arbitrage Implementation Deep Dive
**Date:** 2026-03-07
**For:** ChatGPT Pro Deep Research / Claude Deep Research / Codex
**From:** Elastifund (John Bradley, principal architect)
**Niche Focus:** Multi-Outcome Sum Violation Scanning (A-6) + LLM-Powered Combinatorial Dependency Graph (B-1)
**Sprint Target:** Days 7-21 of the 60-day execution plan

---

## WHY THIS NICHE, WHY NOW

We have evaluated 100 strategies across 9 categories. Two strategies share the top rank at 45% P(Works) — the highest honest probability in our entire taxonomy. Both are in the **combinatorial arbitrage** family. Both are empirically validated: the IMDEA/Carlos III study (Saguillo et al., arXiv:2508.03474, Aug 2025) documented **$40M in realized arbitrage profit** on Polymarket across exactly these two types:

1. **Market-rebalancing arbitrage** (A-6): When multi-outcome markets have YES prices that sum to ≠ $1.00
2. **Combinatorial arbitrage** (B-1): When logically linked markets violate probability constraints (e.g., P(A) > P(B) when A⊂B)

These are our highest-conviction build targets. Everything else waits.

**What we need from this research:** Not more strategy ideas. Not broader surveys. We need **implementation-grade technical specifications** for building and deploying these two systems on Polymarket with $247 USDC capital, maker-only execution, and a Dublin VPS at 5-10ms latency to the CLOB (which is hosted on AWS eu-west-2, London).

---

## SYSTEM CONTEXT (Read These Attached Files)

You have been provided with these context documents:

| Document | What It Contains | Why You Need It |
|----------|-----------------|-----------------|
| `CLAUDE.md` | JJ persona, prime directive, coding standards, current state | Your operating instructions and voice |
| `COMMAND_NODE_v1.0.2.md` | Full technical system architecture, all 4 signal sources, bot code structure | How the existing system works — build ON this |
| `ProjectInstructions.md` | Quick-start context, priority queue, infrastructure details | Current sprint plan and parameters |
| `EDGE_DISCOVERY_SYSTEM.md` | Hypothesis testing pipeline architecture | How we test and kill strategies |
| `FastTradeEdgeAnalysis.md` | Current pipeline results (all REJECT) | Grounding — this is where we are |
| `DEEP_RESEARCH_OUTPUT_v3.md` | 100 strategies with rankings, the source material for A-6 and B-1 specs | The research foundation you're building on |

**Do NOT repeat information already in those documents.** Build on top of them. Reference them by name. Your audience (Claude Code, Cowork, Codex) will have those files open.

---

## RESEARCH TASK: COMBINATORIAL ARBITRAGE IMPLEMENTATION SPECIFICATION

### Part 1: Multi-Outcome Sum Violation Scanner (A-6)

Provide a **complete, deployable technical specification** for a system that:

1. **Discovers all multi-outcome markets** on Polymarket via the Gamma API (`https://gamma-api.polymarket.com/markets`). Document the exact API call, response schema, and filtering logic for markets with >2 outcomes.

2. **Monitors YES price sums in real-time.** For each multi-outcome market, fetch best-ask prices for all outcome tokens via the CLOB API. Compute `sum(YES_prices)`. Flag when `sum < 0.97` (buy opportunity) or `sum > 1.03` (sell opportunity). Document the exact CLOB API calls needed — we know that some token IDs return 404 (noted in EDGE_DISCOVERY_SYSTEM.md). How do we handle this?

3. **Executes sequential multi-leg maker orders.** When a sum violation is detected:
   - Calculate profit per set: `1.00 - sum(YES_prices)` (for sum < 1.00 case)
   - Place simultaneous maker orders for all outcomes
   - Handle partial fills (what if 3 of 5 legs fill but 2 don't?)
   - Implement rollback logic (unwind partial positions if the arb collapses)
   - Use `signature_type=1` (POLY_PROXY) — type 2 fails (documented in ProjectInstructions.md)
   - All orders post-only (zero fees + rebate eligibility)

4. **Manages non-atomic execution risk.** The IMDEA study identified this as the primary risk. Between placing leg 1 and leg N, prices move. Quantify:
   - What is the average price movement per second on Polymarket multi-outcome markets?
   - What fill rate can we expect for maker orders at best-ask minus 1 tick?
   - What is the expected capture rate (% of theoretical profit actually realized) given sequential execution?
   - At what sum violation threshold does the expected capture rate exceed zero after execution risk?

5. **Position merging for capital efficiency.** When we hold YES positions on all outcomes of a market, we can merge and redeem for $1.00. Document:
   - The merge/redeem API call on Polymarket (the `poly_merger` open-source module does this)
   - Gas costs on Polygon for merge transactions
   - Minimum position size where merge is gas-positive

**Deliverable for Part 1:** Complete pseudocode (Python-style) for the scanner, executor, and position merger. Include exact API endpoints, request/response schemas, error handling for CLOB 404s, and a state machine for the multi-leg order lifecycle.

---

### Part 2: LLM-Powered Combinatorial Dependency Graph (B-1)

Provide a **complete technical specification** for a system that:

1. **Builds a dependency graph across all active Polymarket markets.** Using Claude Haiku (cheapest, ~$0.001/classification), classify every pair of markets in the same category by their logical relationship:
   - `A_implies_B` (if A happens, B must happen)
   - `B_implies_A`
   - `mutually_exclusive` (A and B cannot both happen)
   - `subset` (A is a subset of B's outcome space)
   - `independent` (no logical relationship)
   - `complementary` (A + B should sum to ~1.0)

   Document:
   - The exact prompt for Haiku that achieves >80% classification accuracy
   - How to handle the combinatorial explosion (N markets → N² pairs — how to prune)
   - Category-based pre-filtering to reduce pair count
   - Caching strategy (most relationships don't change — only new markets need classification)
   - Expected API cost for initial graph build and incremental updates

2. **Monitors for probability constraint violations in real-time.** For each edge in the dependency graph:
   - If `A_implies_B`: check `price(A) ≤ price(B)`. If `price(A) > price(B) + threshold`, signal.
   - If `mutually_exclusive`: check `price(A) + price(B) ≤ 1.00`. If sum > 1.00 + threshold, signal.
   - If `subset`: check `price(subset) ≤ price(superset)`. Signal on violation.
   - If `complementary`: check `price(A) + price(B) ≈ 1.00`. Signal on large deviation.

   What threshold makes sense given:
   - Maker order execution (zero fee, but fill uncertainty)
   - Typical spread width on Polymarket (document this — we need empirical data)
   - The non-atomic execution risk of multi-leg positions

3. **Executes multi-leg arbitrage positions.** When a violation is detected:
   - Determine which legs to trade (buy underpriced, sell overpriced)
   - Place maker orders on both legs simultaneously
   - Track fill status on each leg independently
   - Compute and enforce maximum loss if only one leg fills (the worst case)
   - Position sizing: Kelly on the expected profit, capped at $5/leg (our current max position)

4. **Validates LLM dependency classifications.** How do we know the LLM's dependency classification is correct? Design a validation pipeline:
   - Manual spot-check on 50 random pairs (ground truth)
   - Cross-reference with resolved market outcomes (if A_implies_B and A resolved YES, did B resolve YES?)
   - Track false positive rate (LLM says dependent, but markets are actually independent)
   - What false positive rate is acceptable before the system produces more losses than gains?

**Deliverable for Part 2:** Complete pseudocode for the dependency classifier, graph builder, violation monitor, and multi-leg executor. Include the exact Haiku prompt, API costs, expected graph size, and a worked example with real Polymarket markets.

---

### Part 3: Combined System Architecture

Show how A-6 and B-1 integrate into our existing system (documented in COMMAND_NODE_v1.0.2.md):

1. **Where do they fit in the signal source hierarchy?** Currently we have 4 signal sources (LLM Analyzer, Wallet Flow, LMSR Engine, Cross-Platform Arb). These become Signal Source 5 (Sum Violation) and Signal Source 6 (Combinatorial Arb). How do they interact with the Confirmation Layer?

2. **Data flow architecture.** Both systems need:
   - Gamma API market discovery (existing — scanner.py)
   - CLOB price feeds (existing for REST, needs WebSocket for real-time)
   - Order placement (existing — jj_live.py)
   - Position tracking (existing — jj_state.json)

   What NEW infrastructure do they need? Be specific. File names, database tables, WebSocket subscriptions.

3. **Risk management integration.** How do these strategies interact with:
   - Daily loss limit ($5)
   - Maximum open positions (5)
   - Maximum position size ($5)
   - Quarter-Kelly sizing (is Kelly even the right framework for arb?)
   - The bankroll segmentation plan ($100 maker / $100 directional / $47 experimental)

4. **Monitoring and kill criteria.** Define the exact metrics we track and the exact thresholds that trigger a kill:
   - A-6: Kill if average capture rate < 50% of theoretical over 20 events, OR < 1 qualifying event/week over 4 weeks
   - B-1: Kill if LLM classification accuracy < 80% on 50 validated pairs, OR < 3 violations/week exceeding threshold
   - Both: Kill if cumulative P&L is negative after 30 days

---

### Part 4: Empirical Questions We Need Answered

The biggest gap in our knowledge is **empirical data about Polymarket multi-outcome markets.** Answer these with actual data or well-grounded estimates:

1. **How many multi-outcome markets are active on Polymarket at any given time?** (Markets with >2 outcomes)
2. **What is the typical sum deviation for multi-outcome markets?** (How often does sum ≠ 1.00 by >3%?)
3. **What is the average spread width on multi-outcome market outcomes?** (The thin tail outcomes like "Candidate Z at 2%" — what's the bid-ask?)
4. **What is the fill rate for maker orders at best-ask on these thin outcomes?**
5. **How many logically dependent market pairs exist?** (e.g., "Trump wins nomination" implies "Republican wins election")
6. **How quickly do sum violations correct?** (Minutes? Hours? Days? — this determines whether REST polling every 5 min is fast enough or we need WebSocket)
7. **What is the minimum profitable violation size given sequential execution risk?**
8. **How did the top arb wallets in the IMDEA study actually execute?** (Simultaneous multi-leg? Sequential? Partially hedged?)
9. **What is the current state of bot competition on multi-outcome arb?** (Are the violations being captured within seconds, or do they persist for hours?)

If you cannot find hard data, provide your best estimates with confidence intervals and cite the reasoning.

---

### Part 5: 14-Day Implementation Sprint Plan

Produce a day-by-day sprint plan for building and deploying A-6 and B-1:

- Days 1-3: Sum violation scanner (A-6) — market discovery, price monitoring, basic alerting
- Days 4-5: Sum violation executor — multi-leg order placement, partial fill handling
- Days 6-8: Dependency graph (B-1) — LLM classifier, graph construction, validation
- Days 9-10: Violation monitor — real-time constraint checking, signal generation
- Days 11-12: Integration — wire into jj_live.py confirmation layer, risk management
- Days 13-14: Paper trading — run both systems on live data, track theoretical P&L

For each day: specify what code gets written, what tests get added, what data gets collected, and what the go/no-go criterion is for proceeding to the next day.

---

### Part 6: Academic Foundation Deep Dive

Go deeper than v3 on the academic evidence. Specifically:

1. **Saguillo et al. (arXiv:2508.03474):** What was their exact methodology? How did they measure the $40M? What was the distribution of arb sizes (median, p90, p99)? What was the time-to-correction? What was the competitive landscape (how many bots were capturing these)?

2. **Are there other academic papers on prediction market combinatorial arbitrage?** Search specifically for:
   - Papers on Dutch book detection in prediction markets
   - Papers on MECE constraint enforcement
   - Papers on multi-outcome market microstructure
   - Any Polymarket-specific or blockchain prediction market arbitrage research from 2024-2026

3. **What does the market microstructure literature say about non-atomic multi-leg execution risk?** This is the key risk for both strategies. Find relevant results from equity/options market making literature that apply.

4. **Conformal prediction for arb sizing:** Can conformal prediction intervals (strategy D-2 in our taxonomy) be applied to arb strategies to size based on capture rate uncertainty?

---

## OUTPUT FORMAT

Structure your response as follows:

```
## Executive Summary (500 words max)
## Part 1: Sum Violation Scanner — Full Technical Spec
## Part 2: Dependency Graph — Full Technical Spec
## Part 3: Combined System Architecture
## Part 4: Empirical Answers
## Part 5: 14-Day Sprint Plan
## Part 6: Academic Foundation
## Appendix A: Complete Pseudocode Listings
## Appendix B: API Reference (Exact Endpoints, Schemas, Error Codes)
## Appendix C: Risk Register (Every Failure Mode, Probability, Mitigation)
```

**Length:** As long as it needs to be. This is an implementation specification, not an overview. We will hand this directly to Claude Code and Codex for execution. Pseudocode should be close enough to real Python that an engineer can translate it in hours, not days.

**Tone:** Direct, technical, honest about uncertainties. No hedging with "could potentially" — state your best estimate and your confidence level. Flag where you're guessing vs where you have data.

**Audience:** Claude Code and Cowork instances that have our full codebase context. They know what `jj_live.py` looks like. They know what `scanner.py` does. They know `signature_type=1` and why type 2 fails. Write for that audience.

---

## ELASTIFUND VISION (Context for Positioning)

We are not building a trading bot website. We are building the world's most rigorous public operating system for agentic trading. Elastifund is a research laboratory, an execution system, and an educational platform combined into one public artifact. The trading engine is the laboratory. The research process is the product. The website is the proof.

John designs the infrastructure: risk limits, research standards, system architecture, deployment process, and evaluation rules. The AI agent operates inside that infrastructure: scanning markets, generating forecasts, sizing positions, selecting strategies, placing orders, and managing risk within hard constraints.

The system mandate is: maximize risk-adjusted returns within defined safety boundaries. The safety rails (daily loss limits, position caps, category filters, Kelly sizing) exist for good reason.

**Current state:** $247.51 USDC on Polymarket + $100 USD on Kalshi = $347.51 total. 12 strategy families tested, all rejected (taker-based). Universal post-only maker enforcement deployed. VPIN toxicity module built. 532 resolved backtested markets at 71.2% win rate. Zero live trades. The next live trades will be the LLM analyzer at $0.50/position (TIER 1, days 1-3), followed by the combinatorial arb system you're designing (TIER 2-3, days 7-21).

---

*This prompt supersedes DEEP_RESEARCH_PROMPT_v4.md and RESEARCH_REQUEST_v1.0.1.md. File as Dispatch P3_25.*
