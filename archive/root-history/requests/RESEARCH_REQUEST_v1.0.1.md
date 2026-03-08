# RESEARCH REQUEST v1.0.1 — Discover a New Trading Edge

**Date:** 2026-03-07  
**Owner:** John Bradley  
**Project:** Elastifund  
**Primary Goal:** Identify a *previously undiscovered, implementable, and testable* algorithmic trading advantage that can outperform the current strategy stack.

---

## 1) Mission
Find at least one edge source that is **not already a core component** of our live architecture and that has a credible path to materially improving expected returns.

Target outcome:
- New edge candidate with estimated **net uplift >= +20% relative to current base-case expectancy**, or
- New edge candidate with **lower drawdown and equal return**, improving risk-adjusted performance.

No hand-wavy ideas. Every claim must map to a measurable signal, data source, and backtest protocol.

---

## 2) Current Strategy Baseline (What We Already Do)
Our current stack already includes:
- LLM probability estimation (anti-anchoring prompt discipline)
- Platt-style calibration and thresholding
- Category routing (prioritize politics/weather/economic, deprioritize crypto/sports for pure forecasting)
- Fee-aware edge gating
- Kelly-based sizing + safety rails
- Ensemble support and Bayesian/LMSR components in codebase

**Implication:** Incremental prompt tweaks are unlikely to create a durable moat by themselves.

---

## 3) Thoughtful Evaluation of Current Strategy
### What is strong
- Better-than-random calibrated forecasting pipeline exists.
- Risk controls and execution guardrails are present.
- Category-specific logic and fee awareness prevent obvious unprofitable trades.

### Where current strategy is fragile
- Many current edges are increasingly known/crowded.
- Heavy dependence on probability estimation quality; limited non-forecast alpha.
- Potential edge decay from copyability and platform adaptation.
- Limited explicit regime detection and adaptive policy switching.

### Strategic conclusion
The next major advantage should likely come from **structural alpha** (market microstructure, cross-market constraints, latency-of-information, or execution asymmetry), not only better text reasoning.

---

## 4) What Counts as “Previously Undiscovered”
A candidate edge qualifies only if all are true:
1. Not already implemented as a first-class production signal in this repo.
2. Not a generic rebrand of known favorites-longshot or simple sentiment edge.
3. Backtest design includes out-of-sample testing and realistic fees/slippage assumptions.
4. Has identifiable data pipeline and deployment path in <= 2 weeks engineering effort.

---

## 5) Research Workstreams (Prioritized)
### P0: Structural Alpha Discovery
1. **Cross-market consistency arbitrage**
   - Detect incoherence across linked markets (mutually exclusive/collectively exhaustive outcomes, conditional chains).
2. **Resolution-rule asymmetry exploitation**
   - Identify recurring pricing errors caused by misunderstood resolution criteria.
3. **Information-latency edge map**
   - Measure which public data sources lead market repricing by minutes/hours.

### P1: Microstructure and Execution Alpha
4. **Queue-position/fill-probability edge**
   - Quote placement policy maximizing expected value net fill risk.
5. **Regime-aware execution policy**
   - Dynamic maker/taker switch based on spread, volatility, and urgency.
6. **Order-book state features beyond midpoint**
   - Short-horizon predictive features from depth imbalance and cancel/replace flow.

### P2: Forecasting Enhancements with Real Differentiation
7. **Domain-specialist model routing**
   - Route by market type/event topology, not one-model-fits-all.
8. **Uncertainty-aware abstention**
   - Trade only when uncertainty-adjusted edge exceeds threshold.
9. **Event-graph forecasting**
   - Encode causal dependencies between related markets/events.

### P3: Portfolio-Level Alpha
10. **Correlation-aware sizing and capital allocation**
   - Position sizing with dependency graph, not independent-bet Kelly assumptions.

---

## 6) Validation Protocol (Required)
For each candidate edge, produce:
- Signal definition (mathematical or algorithmic)
- Data inputs and provenance
- Feature leakage analysis
- Backtest methodology:
  - Train/validation/test splits by time
  - Fee/slippage/partial-fill assumptions
  - Sensitivity and stress scenarios
- Metrics:
  - Win rate, expected value/trade, Sharpe, max drawdown, turnover, capacity
  - Decay analysis over rolling windows
- Failure modes and attack surface

Minimum acceptance bar for promotion to build queue:
- Out-of-sample positive expectancy after costs
- No single-period dependence (not one lucky regime)
- Clear implementation plan with milestone estimate

---

## 7) Best LLM Recommendation for This Research
### Recommended primary model: **Claude (latest high-reasoning tier, e.g., Opus-class if available)**
Why:
- Strong long-context synthesis for multi-document technical research.
- High-quality structured reasoning and decomposition for hypothesis generation.
- Consistent at producing implementation-grade plans (not just summaries).

### Operational recommendation
Use a **two-model process** even if one model leads:
1. Primary research generation with Claude.
2. Independent adversarial critique with ChatGPT (latest reasoning/deep-research mode).

Rationale: edge research benefits from disagreement. Single-model confidence is a known failure mode.

---

## 8) Output Format for Each Finding
Use this exact block:

```markdown
## Finding: <name>
- Edge class:
- Why it is likely underexploited:
- Data required:
- Signal logic:
- Expected impact (net of costs):
- Backtest design:
- Implementation complexity (S/M/L):
- Risks / failure modes:
- Go/No-Go recommendation:
```

Also include a ranked shortlist:
- **Top 3 build-now candidates**
- **Top 3 monitor-only candidates**
- **Top 3 rejected candidates** with explicit rejection reasons

---

## 9) Guardrails
- Do not claim guaranteed returns.
- Do not present unvalidated assumptions as proven edges.
- Treat any “massive returns” language as an aspiration, not an expected baseline.
- Prefer robustness and repeatability over headline CAGR.

---

## 10) Final Deliverable
Produce a single research report with:
1. Executive summary
2. Current strategy vs proposed edge comparison
3. Ranked edge opportunities
4. Validation evidence quality assessment
5. 14-day implementation sprint plan for the top candidate

---

*v1.0.1 updates v1.0.0 by narrowing scope from broad research to explicit discovery of a novel, testable, and potentially durable algorithmic advantage, with a concrete model recommendation and evaluation against current strategy.*
