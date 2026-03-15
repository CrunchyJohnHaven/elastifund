# DEEP RESEARCH PROMPT — Combinatorial Arbitrage: Parallel Codex Execution Plan
**Date:** 2026-03-08
**Source Version:** v7.0
**Dispatch:** P3_26
**From:** JJ (Principal, Elastifund)
**Canonical Filename:** `research/deep_research_prompt.md`
**Supersedes:** archived prompt variants under `archive/root-history/prompts/`
**Execution Mode:** 4 parallel Codex instances + 1 ChatGPT Deep Research instance

---

## HOW TO USE THIS DOCUMENT

This prompt is designed to be pasted verbatim into OpenAI Codex. It defines **5 parallel workstreams**, each assigned to a separate instance. Each instance receives the same context package but a different task. Outputs are designed to be merged without conflict.

**Context Package (attach to ALL instances):**

| # | File | Purpose |
|---|------|---------|
| 1 | This file (research/deep_research_prompt.md) | The prompt — each instance reads only its assigned section |
| 2 | ResearchContext.md | Active session context and source-precedence contract |
| 3 | CLAUDE.md | Agent behavior rules and operating persona |
| 4 | COMMAND_NODE.md | Full system architecture, all signal sources, API details |
| 5 | PROJECT_INSTRUCTIONS.md | Sprint plan, risk parameters, infrastructure |
| 6 | docs/strategy/edge_discovery_system.md | Hypothesis testing pipeline |
| 7 | FAST_TRADE_EDGE_ANALYSIS.md | Current pipeline state (REJECT ALL) |
| 8 | research/deep_research_output.md | 100-strategy taxonomy, A-6 and B-1 source specs |
| 9 | research/jj_assessment_dispatch.md | JJ's prioritization and kill decisions |

**Launch instructions:** Create 5 Codex tasks. Each task gets the full context package above. Each task's prompt is: "Read research/deep_research_prompt.md. Execute INSTANCE [N] only. Ignore all other instance sections. Output your deliverables as specified."

---

## SHARED CONTEXT (All Instances Read This)

### What We Have
- Internal seed bankroll withheld from public docs
- Dublin VPS (AWS Lightsail eu-west-1), 5-10ms latency to CLOB (eu-west-2, London)
- Python 3.12, py-clob-client, signature_type=1 (POLY_PROXY — type 2 fails)
- 100% post-only maker execution (zero fees, rebate eligible)
- LLM analyzer: 71.2% win rate on 532 backtested markets, static Platt (A=0.5914, B=-0.3977)
- Service currently STOPPED — upgrading to add Signal Sources 5 and 6
- Zero live resolved trades. Zero real P&L.
- README currently claims 553 passing tests across the repo; refresh the exact count before repeating it externally
- Kill discipline: 9 fast-trade hypotheses rejected, 8 strategies permanently killed

### What We're Building
Two strategies share our top rank at 45% P(Works) — the highest honest probability in our entire 100-strategy taxonomy:

1. **A-6: Multi-Outcome Sum Violation Scanner** — When multi-outcome markets have YES prices summing to ≠ $1.00, buy the complete set (if sum < 1) or sell (if sum > 1) and redeem for guaranteed profit.
2. **B-1: LLM-Powered Combinatorial Dependency Graph** — When logically linked markets violate probability constraints (e.g., P(A) > P(B) when A⊂B), trade the mispricing.

Both validated by Saguillo et al. (arXiv:2508.03474, Aug 2025) — $40M in documented realized arbitrage profit on Polymarket across exactly these two types.

### Constraints Every Instance Must Respect
- Max position: $5/leg
- Max daily loss: $5
- Max open positions: 5
- Quarter-Kelly sizing
- Maker-only execution (post_only=true on all orders)
- Bankroll segmentation: $100 maker / $100 directional / $47 experimental
- signature_type=1 (POLY_PROXY) — type 2 FAILS
- Anti-anchoring: never show Claude the market price when estimating probability
- Category filters: skip sports, crypto, financial speculation

### Coding Standards
- Python 3.12. Dataclasses for signals and state. SQLite for persistence. logging module.
- New modules go in `bot/` with naming convention `bot/{module_name}.py`
- Tests go in `bot/tests/test_{module_name}.py`
- Follow patterns from `bot/jj_live.py` and `bot/constraint_arb_engine.py`
- All strategies implement a common interface: `scan() -> List[Signal]`, `execute(signal) -> Order`, `check_kill() -> bool`

---

## INSTANCE 1: SUM VIOLATION SCANNER (A-6) — COMPLETE DEPLOYABLE CODE

**Your task:** Write the complete, production-ready Python implementation of the multi-outcome sum violation scanner. This is not pseudocode. This is not a spec. This is code that will be committed to the repository and deployed to the Dublin VPS.

### Files You Produce

1. **`bot/sum_violation_scanner_v2.py`** — The scanner (replaces the existing 15KB draft in bot/sum_violation_scanner.py)
2. **`bot/sum_violation_executor.py`** — Multi-leg order placement and lifecycle management
3. **`bot/position_merger.py`** — Merge complete position sets and redeem for $1.00
4. **`bot/tests/test_sum_violation_v2.py`** — Full test suite

### Technical Requirements

**Market Discovery:**
- Hit `https://gamma-api.polymarket.com/markets?closed=false&limit=100&offset={n}` to paginate all active markets
- Filter for markets where `outcomes` array has >2 elements (multi-outcome)
- Extract `clobTokenIds` for each outcome — these are the token IDs for CLOB API calls
- Handle pagination (Gamma returns max 100 per page)
- Cache market metadata (slug, question, outcomes, token IDs) — refresh every 15 minutes
- Document: how many multi-outcome markets are typically active? (We need this number)

**Price Monitoring:**
- For each multi-outcome market, fetch best-ask for every outcome token via CLOB REST: `GET https://clob.polymarket.com/book?token_id={id}`
- Compute `sum_yes = sum(best_ask for each outcome)`
- Compute `sum_no = sum(best_bid for each outcome)` (for sell-side opportunities)
- Flag when `sum_yes < 0.97` (buy all YES, redeem for $1.00) or `sum_yes > 1.03` (sell opportunity)
- Handle CLOB 404s gracefully — some token IDs return 404 (documented in docs/strategy/edge_discovery_system.md). Skip the market, log the error, retry on next cycle.
- Polling interval: every 60 seconds for REST. (WebSocket upgrade is Instance 3's job.)

**Execution (the hard part):**
When a sum violation is detected with expected profit > threshold:
```
theoretical_profit = 1.00 - sum_yes  (for buy case)
execution_risk_haircut = 0.40  (conservative: assume 40% of legs may not fill at target price)
expected_profit = theoretical_profit * (1 - execution_risk_haircut)
```
If `expected_profit > 0.01` (1 cent minimum):
1. Calculate order size per leg: `min($5, bankroll / num_outcomes)` — respect $5/leg cap
2. Place post_only maker orders on ALL outcomes simultaneously (parallel async requests)
3. Use `signature_type=1` (POLY_PROXY)
4. Track fill status per leg independently
5. After 60 seconds, check fills:
   - All legs filled → proceed to merge and redeem
   - Partial fill → evaluate: if remaining legs still sum < 1.00, keep waiting. If prices have moved and arb is gone, cancel unfilled legs.
   - No fills → cancel all, log opportunity missed

**Partial Fill Handling (critical):**
- If 3 of 5 legs fill but 2 don't, we're holding an incomplete set
- Options: (a) wait for fills at worse price, (b) cancel and hold the partial position as directional, (c) sell the filled positions at market
- Implement option (a) with a time limit of 5 minutes, then fall back to (c)
- Track worst-case loss for any partial fill state: `max_loss = sum(filled_positions * (1 - current_price))`
- If `max_loss > $2` (40% of daily limit), force-close the position

**Position Merging:**
- When all outcomes of a market are held with equal quantity, call the merge/redeem contract
- Use the `poly_merger` pattern: approve CTF contract, call mergePositions(), receive USDC
- Gas costs on Polygon: estimate 0.01 MATIC per merge (~$0.005). Minimum profitable position: where profit > gas cost.
- Net P&L per completed arb = theoretical_profit * position_size - gas_cost

**State Machine:**
```
IDLE → VIOLATION_DETECTED → ORDERS_PLACED → MONITORING_FILLS →
  → ALL_FILLED → MERGING → REDEEMED → IDLE
  → PARTIAL_FILL → WAITING → FORCE_CLOSE → IDLE
  → NO_FILLS → CANCELLED → IDLE
```
Persist state to SQLite table `sum_violation_positions`.

**Kill Criteria (hardcoded):**
- Kill if average capture rate < 50% of theoretical over 20 completed arb cycles
- Kill if < 1 qualifying violation per week over 4 consecutive weeks
- Kill if cumulative P&L negative after 30 days
- Kill if partial fill rate > 60% (execution risk too high)

**Output format:** Complete Python files, ready for `git add`. Include docstrings, type hints, logging. Follow the patterns in `bot/jj_live.py` for async HTTP calls and state management.

---

## INSTANCE 2: DEPENDENCY GRAPH ARBITRAGE (B-1) — COMPLETE DEPLOYABLE CODE

**Your task:** Write the complete, production-ready Python implementation of the LLM-powered combinatorial dependency graph and its arbitrage executor. This builds on `bot/constraint_arb_engine.py` (71KB, already exists) but you are writing the clean, deployable version.

### Files You Produce

1. **`bot/dependency_classifier.py`** — LLM-based market pair classification
2. **`bot/dependency_graph.py`** — Graph construction, storage, querying
3. **`bot/constraint_violation_monitor.py`** — Real-time constraint checking
4. **`bot/constraint_arb_executor.py`** — Multi-leg arb execution for constraint violations
5. **`bot/tests/test_dependency_graph.py`** — Full test suite

### Technical Requirements

**Pair Classification with Claude Haiku:**
Use Claude Haiku (`claude-haiku-4-5-20251001`) at ~$0.001/classification. The exact prompt:

```
You are classifying the logical relationship between two prediction markets.

Market A: "{question_a}"
Outcomes A: {outcomes_a}

Market B: "{question_b}"
Outcomes B: {outcomes_b}

Classify their relationship as exactly ONE of:
- A_IMPLIES_B: If A resolves YES, B must resolve YES
- B_IMPLIES_A: If B resolves YES, A must resolve YES
- MUTUALLY_EXCLUSIVE: A and B cannot both resolve YES
- SUBSET: A's YES outcome is a strict subset of B's YES outcome space
- COMPLEMENTARY: A and B should sum to approximately 1.0
- INDEPENDENT: No logical dependency

Respond with ONLY the classification label, nothing else.
```

**Combinatorial Explosion Management:**
- N active markets → N*(N-1)/2 pairs. At 500 markets, that's 124,750 pairs.
- Pre-filter: only classify pairs within the same category (politics, sports, crypto, etc.)
- Pre-filter: only classify pairs with overlapping keywords in their questions (simple TF-IDF or keyword match)
- Expected reduction: 500 markets → ~2,000 candidate pairs after filtering
- At $0.001/pair: initial build costs $2.00. Incremental: ~$0.10/day for new markets.
- Cache ALL classifications in SQLite table `dependency_edges`. Only reclassify when a new market is created.
- TTL: Never expire (market questions don't change). Delete edge when either market resolves.

**Graph Storage Schema:**
```sql
CREATE TABLE dependency_edges (
    market_a_id TEXT,
    market_b_id TEXT,
    relationship TEXT,  -- A_IMPLIES_B, B_IMPLIES_A, MUTUALLY_EXCLUSIVE, SUBSET, COMPLEMENTARY
    confidence REAL,    -- LLM confidence (if extractable) or 1.0
    classified_at TEXT,  -- ISO timestamp
    validated BOOLEAN DEFAULT FALSE,
    validation_result TEXT,  -- CORRECT, INCORRECT, UNKNOWN
    PRIMARY KEY (market_a_id, market_b_id)
);
```

**Constraint Violation Detection:**
For each non-INDEPENDENT edge, fetch current prices and check:

| Relationship | Constraint | Violation Signal |
|-------------|-----------|-----------------|
| A_IMPLIES_B | price(A) ≤ price(B) | price(A) > price(B) + 0.03 |
| B_IMPLIES_A | price(B) ≤ price(A) | price(B) > price(A) + 0.03 |
| MUTUALLY_EXCLUSIVE | price(A) + price(B) ≤ 1.00 | price(A) + price(B) > 1.03 |
| SUBSET | price(subset) ≤ price(superset) | price(subset) > price(superset) + 0.03 |
| COMPLEMENTARY | price(A) + price(B) ≈ 1.00 | |price(A) + price(B) - 1.00| > 0.05 |

The 0.03 threshold is a starting point. It must exceed the round-trip execution cost. With maker-only execution (zero fees), the cost is the bid-ask spread. Typical Polymarket spread: 1-3 cents on liquid markets, 5-15 cents on thin markets. The threshold should be `max(0.03, estimated_spread * 2)`.

**Execution:**
When a violation is detected:
1. Determine legs: buy the underpriced side, sell the overpriced side
2. Calculate expected profit: `violation_size - estimated_execution_cost`
3. Position sizing: quarter-Kelly on the expected profit, capped at $5/leg
4. Place post_only maker orders on both legs (parallel async)
5. Track fills independently
6. Worst-case analysis: if only one leg fills, what's the max loss? If max_loss > $2, don't enter.
7. Time limit: 5 minutes for both legs to fill. If one fills and the other doesn't after 5 min, hold the filled position as a directional bet (it was underpriced, so this should be positive EV).

**Validation Pipeline:**
Build in a self-checking mechanism:
1. After initial graph construction, randomly sample 50 edges
2. Present each to Claude Sonnet (not Haiku) with chain-of-thought reasoning for a second opinion
3. If Sonnet disagrees with Haiku on >20% of samples, the Haiku prompt needs revision
4. Track resolution-based validation: when markets resolve, check if the dependency held (if A_IMPLIES_B and A=YES, did B=YES?)
5. Log false positive rate. If >15% of "dependent" pairs turn out to be independent on resolution, the classifier is unreliable.

**Kill Criteria:**
- Kill if LLM classification accuracy < 80% on 50 validated pairs
- Kill if < 3 qualifying violations per week exceeding threshold over 4 weeks
- Kill if cumulative P&L negative after 30 days
- Kill if false positive rate on dependency classification > 15%

**Output format:** Complete Python files. Same standards as Instance 1.

---

## INSTANCE 3: INTEGRATION, RISK MANAGEMENT, AND WEBSOCKET INFRASTRUCTURE

**Your task:** Write the integration layer that wires Instances 1 and 2 into the existing system. You also build the WebSocket infrastructure that both scanners need for real-time price feeds.

### Files You Produce

1. **`bot/ws_market_feed.py`** — WebSocket client for real-time CLOB price updates
2. **`bot/arb_signal_router.py`** — Routes A-6 and B-1 signals into jj_live.py's confirmation layer
3. **`bot/arb_risk_manager.py`** — Arb-specific risk management (not the same as directional risk)
4. **`bot/tests/test_integration.py`** — Integration tests
5. **`INTEGRATION_SPEC.md`** — Architecture document showing data flow

### Technical Requirements

**WebSocket Market Feed:**
- Connect to Polymarket CLOB WebSocket (wss://ws-subscriptions-clob.polymarket.com/ws/market)
- Subscribe to order book updates for all monitored multi-outcome markets AND all dependency-graph market pairs
- Parse messages into standardized `PriceUpdate(token_id, best_bid, best_ask, timestamp)` dataclass
- Maintain in-memory order book snapshot per token
- Reconnection logic: exponential backoff, max 5 retries, then fall back to REST polling
- Heartbeat: ping every 30 seconds, reconnect on pong timeout
- Feed price updates to both the sum violation scanner and the constraint violation monitor

**Signal Router:**
Currently jj_live.py has 4 signal sources feeding into a confirmation layer that requires 2+ sources to agree for boosted confidence. A-6 and B-1 become Signal Sources 5 and 6. But here's the design question:

Arb signals are fundamentally different from directional signals. A directional signal says "this market is mispriced — buy NO." An arb signal says "these N markets collectively violate a constraint — execute this specific multi-leg trade." The confirmation layer logic doesn't apply the same way.

**Design decision (implement this):**
- Arb signals (A-6, B-1) bypass the confirmation layer. They are self-confirming — the violation IS the signal.
- Arb signals go directly to their own executor (sum_violation_executor or constraint_arb_executor)
- Arb signals still respect the risk manager (daily loss limit, position count limit)
- If an arb signal and a directional signal point at the same market, the arb signal takes priority (it has structural edge, not probabilistic edge)

**Arb-Specific Risk Management:**
Arbitrage risk is different from directional risk:
- No Kelly sizing needed for perfect arbs (A-6 with all legs filled is riskless). Position size = max affordable.
- Kelly IS needed for imperfect arbs (B-1 where one leg might not fill). Size based on P(both legs fill) * expected profit.
- Arb positions should have a SEPARATE risk budget from directional positions:
  - $100 allocated to arb strategies (from the maker bucket)
  - $100 allocated to directional strategies
  - $47 experimental
- Daily loss limit for arb: $3 (separate from the $5 total — arb losses are execution failures, not signal failures)
- Max concurrent arb positions: 3 (each may be multi-leg)

Write the risk manager as a class that:
```python
class ArbRiskManager:
    def can_enter(self, signal: ArbSignal) -> bool: ...
    def record_entry(self, position: ArbPosition) -> None: ...
    def record_exit(self, position: ArbPosition, pnl: float) -> None: ...
    def daily_pnl(self) -> float: ...
    def open_positions(self) -> int: ...
    def check_kill(self) -> bool: ...
```

**Integration with jj_live.py:**
Don't modify jj_live.py directly (it's 125KB and fragile). Instead:
- Create `arb_signal_router.py` that jj_live.py imports
- The router exposes `async def scan_arb_opportunities() -> List[ArbSignal]`
- jj_live.py calls this in its main loop alongside existing signal sources
- The router internally calls sum_violation_scanner.scan() and constraint_violation_monitor.scan()
- Signals that pass risk checks are forwarded to the appropriate executor

**Output format:** Complete Python files + INTEGRATION_SPEC.md architecture document.

---

## INSTANCE 4: EMPIRICAL RESEARCH + ACADEMIC DEEP DIVE + KILL CRITERIA CALIBRATION

**Your task:** This is the research instance. No code. Your job is to answer the empirical questions that Instances 1-3 need to make correct implementation decisions, AND to do the academic literature deep dive.

### Deliverable: `COMBINATORIAL_ARB_RESEARCH_v1.md`

### Part A: Empirical Questions (Answer with data or grounded estimates)

For each answer: state your confidence level (1-5), cite your source, and flag whether this is measured data vs. estimate.

1. **How many multi-outcome markets are active on Polymarket right now?** (Markets with >2 outcomes.) Go to gamma-api.polymarket.com/markets and count. Give the exact number, not an estimate.

2. **What is the distribution of sum deviations?** For each multi-outcome market, compute sum(YES_best_ask). What percentage deviate by >1%? >3%? >5%? How often do deviations >3% occur per day?

3. **What is the average bid-ask spread on multi-outcome market outcomes?** Separate by liquidity tier: >$100K volume, $10K-$100K, <$10K. The thin-tail outcomes (2-5% probability) are what matter for A-6 — what are their spreads?

4. **What is the maker fill rate?** For post_only orders placed at best_ask, what percentage fill within 60 seconds? Within 5 minutes? This is the single most important number for the entire strategy. If fill rate is <20%, A-6 is dead.

5. **How many logically dependent market pairs exist?** Manually classify 20 pairs from active political markets. What percentage are actually dependent? Extrapolate to the full market set.

6. **How quickly do sum violations correct?** If a multi-outcome market has sum(YES) = 0.95, how long until it returns to ~1.00? Minutes? Hours? Days? This determines whether 60-second REST polling is fast enough.

7. **What is the competitive landscape for multi-outcome arb bots?** The IMDEA study identified specific wallets. Are they still active? How fast do they capture violations? Can we see their transaction patterns on Polygonscan?

8. **What is the minimum profitable violation size?** Given: (a) sequential execution over ~5 seconds per leg, (b) maker-only orders with uncertain fill, (c) Polygon gas for merge (~$0.005), (d) price movement during execution. What violation threshold makes the expected value positive?

9. **What is the actual Polygon gas cost for a CTF merge operation in March 2026?** Check recent transactions on the Polymarket CTF contract.

10. **What is our actual latency?** Dublin (eu-west-1) to CLOB (eu-west-2, London). Measure or estimate the round-trip REST API latency and WebSocket message latency.

### Part B: Academic Deep Dive

**Required readings (find and analyze these):**

1. **Saguillo et al. (arXiv:2508.03474, Aug 2025):**
   - Exact methodology for measuring the $40M
   - Distribution of arb sizes (median, p90, p99)
   - Time-to-correction data
   - Competitive landscape (how many bots, how concentrated was the $40M across wallets?)
   - What fraction of violations were actually captured vs. expired?

2. **Dutch book detection in prediction markets:**
   - Search for papers on automated Dutch book detection (de Finetti's theorem applied to prediction markets)
   - Any work on MECE constraint enforcement in multi-outcome settings
   - Hanson's LMSR work — does the LMSR mechanism prevent sum violations by design, and does the CLOB mechanism NOT prevent them?

3. **Non-atomic multi-leg execution risk:**
   - This is our biggest risk. What does the options market-making literature say about sequential leg execution?
   - Relevant terms: "leg risk," "execution risk in spread trading," "multi-leg order management"
   - What techniques do options market makers use to manage partial fills on spreads?

4. **Prediction market microstructure (2024-2026):**
   - Any academic work specifically on Polymarket order book dynamics
   - Blockchain prediction market arbitrage research
   - The Polymarket CLOB is relatively new (2023-2024) — has anyone studied its microstructure?

5. **Conformal prediction for arb sizing:**
   - Can conformal prediction intervals (strategy D-2 in our taxonomy) be applied to size arb positions based on capture rate uncertainty?
   - How would you construct a conformal set for "probability that all N legs fill within T seconds"?

### Part C: Kill Criteria Calibration

Based on Parts A and B, recommend calibrated kill criteria for both strategies:

For A-6:
- Minimum violation frequency to sustain the strategy (events/week)
- Minimum capture rate to be profitable (% of theoretical profit realized)
- Maximum partial fill rate before the strategy is net-negative
- Sample size needed for statistical confidence that the strategy works or doesn't

For B-1:
- Minimum classification accuracy for the dependency graph to be useful
- Minimum violation frequency
- Maximum acceptable false positive rate on dependency classification
- How many resolution cycles needed to validate the graph?

**Output format:** A single comprehensive markdown document. Be direct, cite everything, flag confidence levels. This document will be read by the code instances (1-3) to calibrate their implementations.

---

## INSTANCE 5: CHATGPT PRO DEEP RESEARCH (Not Codex — Run in ChatGPT)

**Your task:** This runs on ChatGPT Pro's Deep Research mode, which has web browsing. The Codex instances cannot browse the web. You fill the empirical gaps they can't.

### Deliverable: `MARKET_EMPIRICAL_DATA_v1.md`

### What You Search For

1. **Live Polymarket multi-outcome market data:**
   - Go to polymarket.com and find all currently active multi-outcome markets
   - For each, record: market question, number of outcomes, approximate YES prices for each outcome, sum of YES prices
   - Flag any markets where sum deviates by >2%

2. **Polymarket CLOB API documentation:**
   - Find the current official documentation for the CLOB REST API and WebSocket API
   - Document exact endpoints, authentication requirements, rate limits, WebSocket subscription format
   - Specifically: the order placement endpoint, the book endpoint, and the WebSocket market subscription
   - Check if there's a multi-leg order API or if we must place legs sequentially

3. **IMDEA/Carlos III study (Saguillo et al.):**
   - Find the full paper on arXiv (2508.03474)
   - Extract: methodology, key statistics on arb size distribution, time-to-correction, bot wallet analysis
   - If the paper has supplementary data or code, find it

4. **Current state of Polymarket arb bots:**
   - Search for any blog posts, tweets, or forum discussions about arb bots on Polymarket (2025-2026)
   - What tools/frameworks are people using?
   - Is there a known "arb gap" that retail traders have exploited?
   - Any evidence of professional market makers running multi-outcome arb?

5. **Polygon gas costs (March 2026):**
   - Current MATIC/POL price
   - Typical gas cost for a CTF merge operation (check Polygonscan for recent Polymarket CTF transactions)
   - Any Polygon network congestion issues?

6. **Polymarket CTF merge contract:**
   - Find the contract address and ABI for the Conditional Token Framework merge function
   - Document the exact function signature and parameters
   - Any known issues or gotchas?

7. **py-clob-client documentation:**
   - Current version and API reference
   - Does it support WebSocket subscriptions natively?
   - Does it support post_only orders?
   - Does it have multi-leg order support?

8. **Competitor analysis:**
   - Search for open-source Polymarket arbitrage bots on GitHub
   - What approaches are they using?
   - How sophisticated are they?
   - Any that specifically target multi-outcome sum violations?

### Output Format
For each item: state what you found, provide the URL, extract the key data points, and flag what you couldn't find. This document feeds directly into Instances 1-4 to fill their knowledge gaps.

---

## POST-EXECUTION: MERGE PROTOCOL

After all 5 instances complete:

1. **Instance 4 (research) and Instance 5 (empirical data) complete first.** Their outputs inform parameter choices in Instances 1-3.
2. **Review empirical answers.** If fill rate < 20% or multi-outcome markets < 10, A-6 may be dead on arrival. If dependent market pairs < 20, B-1 may not have enough targets. Decide whether to proceed before reviewing code.
3. **Review Instance 3 (integration spec) for architectural decisions.** Does the arb-bypass-confirmation-layer design make sense? Does the separate risk budget work?
4. **Review Instances 1 and 2 (code) against the calibrated parameters from Instance 4.** Are the thresholds, timeouts, and kill criteria consistent with the empirical data?
5. **Merge code into a feature branch.** Run existing test suite (345 tests must still pass). Run new tests. Deploy to VPS for paper trading.

Target: 48 hours from launch to paper trading.

---

## WHAT SUCCESS LOOKS LIKE

In 14 days:
- Sum violation scanner running live, detecting violations (even if none are profitable)
- Dependency graph built for all active political markets, validated on 50 pairs
- At least 5 completed arb cycles OR a confident kill decision with documented evidence
- Research document answering all 10 empirical questions with data, not guesses
- All new code tested, documented, and deployed

In 30 days:
- Live P&L data from arb strategies (positive or negative — we need the data)
- Calibrated kill criteria based on real fill rates and real violation frequencies
- Go/no-go decision on scaling arb capital from $100 to $200

**Every day without live data is a day we learn nothing.**

---

*Filed as Dispatch P3_26. Supersedes the archived pre-canonical prompt set.*
*— JJ*
