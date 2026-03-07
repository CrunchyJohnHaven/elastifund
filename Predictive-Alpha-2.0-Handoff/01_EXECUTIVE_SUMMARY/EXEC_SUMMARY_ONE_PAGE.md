# Executive Summary: One Page

## What Is Predictive Alpha?

An AI-powered automated trading system for Polymarket prediction markets. Uses Claude to estimate true event probabilities, compares against market prices, trades when gaps are found. All profits fund veteran suicide prevention.

## The Hypothesis

**Prediction market crowds misprice events systematically.** Claude's probability estimates are better than crowd prices. Trade the gaps. Make money.

## What We've Built

| Component | Status | Evidence |
|-----------|--------|----------|
| Claude probability analyzer (anti-anchoring) | ✓ Deployed | [Implemented system component] |
| Calibration engine (Platt scaling) | ✓ Deployed | [Historical backtest, out-of-sample validated] |
| Kelly sizing + NO-bias | ✓ Deployed | [Implemented system component] |
| Category routing | ✓ Deployed | [Implemented system component] |
| Paper trading on VPS | ✓ Live | [Live-tested, 2 cycles, 17 trades] |
| Safety rails (6 layers) | ✓ Deployed | [Implemented system component] |
| Backtest engine (532 markets) | ✓ Done | [Historical backtest] |
| Multi-model ensemble | ✗ Skeleton only | [Planned] |

## The Evidence

**Historical Backtest (532 markets, out-of-sample validated):**
- Win rate: 68.5% (after calibration)
- P&L: +$276 simulated on 372 trades (after 2% Polymarket fees)
- Brier Score: 0.2451 (vs. 0.25 for random)
- Risk of ruin: 0% (across 10K Monte Carlo simulations)

**Live Trading (current, paper testing):**
- 2 cycles completed (March 4-6, 2026)
- 17 trades entered
- $68 deployed
- Realized P&L: $0 (awaiting market resolutions)
- Execution: 100% success rate, 0 errors

**Critical Note:** All performance metrics except the live trades are [historical backtest] or [simulation]. Zero real-money trades have resolved yet. We need 50+ resolved trades for statistical significance.

## What This Proves vs. Doesn't

✓ **Proven:**
- Claude generates usable probability estimates
- Platt scaling improves calibration on unseen data
- Backtest shows >50% win rate over 532 markets
- System executes without operational errors
- Polymarket API is functional and exploitable

✗ **Not Proven:**
- Live trading will match backtested returns
- Edge persists when other teams also use Claude
- System scales to $100K+ capital
- Regulatory environment remains stable
- Claude is the optimal model for this task

## The Business

**Capital Model:**
- Start: $75 seed
- Weekly addition: $1,000 as trades resolve and compound
- Costs: ~$20/month VPS + Claude API calls

**Revenue:** Profit from winning trades

**Impact:** 100% of profits fund veteran suicide prevention

## What's Next (Priority Order)

1. **Accumulate 50+ live resolved trades** (2-4 weeks) [Live-tested] — Need statistical significance
2. **Evaluate GPT-4 and Grok** (2 weeks) [Planned] — Which model is better?
3. **Add multi-model ensemble** (3 weeks) [Planned] — Combine Claude + best alternatives
4. **Implement live calibration drift monitoring** (2 weeks) [Planned] — Catch model decay early
5. **Build agentic RAG web search** (3 weeks) [Planned] — Enhance Claude's context
6. **Scale capital if live results are positive** (ongoing) [Planned] — Grow $68 → $1K+ deployed

## The Risks

| Risk | Severity | Likelihood | Mitigation |
|------|----------|-----------|-----------|
| Regulatory shutdown (CFTC, states) | Existential | 30-40% | Monitor regulatory news, build on Kalshi/Metaculus backup |
| Claude edge disappears (others use Claude) | Existential | 50%+ | Test GPT/Grok now, build ensemble |
| Live performance ≠ backtest | High | 60-70% | Run 50+ live trades, monitor calibration drift |
| Market impact at scale | High | 70%+ | Route through multiple accounts, cap position sizes |
| Calibration drift | Medium | 60%+ | Implement live drift monitoring |
| Competition increases, edge narrows | High | 80%+ | Expect 6-month window before major compression |

## The Reasonable Verdict

**This system has real promise but is not yet proven.**

The backtest evidence is strong. The operational system works. But until we have 50+ live resolved trades, we're trading on theory and simulation. The next 2-4 weeks will either validate or falsify the core hypothesis.

**Regulatory risk is real.** Polymarket faces CFTC interest and state litigation. Build with that in mind.

**Competition is real.** Other teams have made tens of millions on prediction markets. Our edge is narrow and will compress.

**Build accordingly.** Optimize for fast learning, rapid iteration, and pivot-readiness. The next 90 days matter.

---

**Read next:** `EXEC_SUMMARY_DETAILED.md` for deeper dive, or `02_CURRENT_SYSTEM/SYSTEM_OVERVIEW.md` for architecture →
