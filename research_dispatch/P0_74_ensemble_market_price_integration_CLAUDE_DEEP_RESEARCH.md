# P0-74: Ensemble + Market Price Integration — Bridgewater Method
**Tool:** CLAUDE_DEEP_RESEARCH
**Status:** READY
**Priority:** P0 — Bridgewater's AIA Forecaster proved that LLM + market consensus beats both alone. This is the final stage of our prediction pipeline.
**Expected ARR Impact:** +15–30% (combining model estimate with market price = highest-quality final signal)

## Prompt (paste into Claude.ai with Deep Research enabled)

```
Deep research on combining LLM probability estimates with prediction market prices for optimal forecasting:

CONTEXT:
I have a prediction market trading system with:
- LLM ensemble (Claude + GPT + Grok) producing calibrated probability estimates
- Polymarket market prices (crowd consensus)
- Currently: LLM estimates blind (no market price shown), calibrated via Platt scaling, then compared to market price to find edge

KEY FINDING (Bridgewater 2025):
Bridgewater's AIA Forecaster showed that combining the LLM estimate with market consensus outperforms either alone. But HOW they combine them matters enormously.

RESEARCH QUESTIONS:

1. BRIDGEWATER'S EXACT METHODOLOGY:
   - The Alur et al. (2025) paper — what was their exact combination method?
   - Did they use weighted average? Bayesian update? Something else?
   - What weights did they use? Were weights dynamic?
   - Did they reveal the market price to the LLM, or combine post-hoc?
   - What Brier score did the combined system achieve vs LLM-only vs market-only?

2. COMBINATION METHODS (theoretical + empirical):
   Compare ALL methods for combining a model estimate p_model with a market price p_market:

   a. Simple average: p_combined = (p_model + p_market) / 2
   b. Weighted average: p_combined = w*p_model + (1-w)*p_market
      - What should w be? How to learn it?
      - Should w depend on: confidence level? category? time to resolution? market liquidity?
   c. Logarithmic pool: log(p_combined) = w*log(p_model) + (1-w)*log(p_market) (normalized)
      - When is this better than linear average?
   d. Bayesian update: use market price as prior, LLM estimate as likelihood (or vice versa)
      - Which direction is better: LLM prior + market update, or market prior + LLM update?
   e. Extremizing: after combination, push toward 0 or 1 by some factor
      - Satopää et al. (2014) showed extremizing improves aggregated forecasts
      - What extremization factor is optimal?
   f. Probing: only trade when LLM and market disagree by >X%
      - This is our current approach (edge threshold). Is it optimal?
      - Should the threshold vary by confidence or category?

   For each: cite papers, expected Brier improvement, failure modes.

3. ANTI-ANCHORING CONCERNS:
   Currently we HIDE the market price from the LLM to prevent anchoring.
   - Is this always optimal?
   - Scenario A: LLM estimates blind, then we combine post-hoc
   - Scenario B: LLM sees market price and adjusts
   - Scenario C: LLM estimates blind, then sees market price and gives a second estimate
   - Which scenario produces the best calibration? Cite evidence.
   - Key concern: if the LLM sees the price, it may just say "market is probably right" (deference bias)

4. INFORMATION-THEORETIC PERSPECTIVE:
   - The market price already aggregates thousands of traders' information
   - The LLM has training data + (with RAG) real-time web search
   - When is the LLM likely to have DIFFERENT information from the market?
     - Breaking news not yet priced in (information speed edge)
     - Base rate knowledge that retail traders ignore (structural edge)
     - Complex reasoning about resolution criteria (resolution rule edge)
     - Weather/economic data (data edge)
   - When is the market likely to be MORE informed than the LLM?
     - Insider information
     - Real-time events the LLM can't observe
     - Markets with deep liquidity and sophisticated participants

5. DYNAMIC WEIGHTING:
   Should the combination weight change based on context?
   - Market liquidity: thin markets = more weight to LLM (less informed market)
   - Time to resolution: near-term = more weight to market (market has fresher info)
   - Category: politics = more weight to LLM (our best category); crypto = more weight to market
   - Volatility: high-volatility markets = more weight to LLM (market overreacts)
   - Ensemble agreement: when all 3 models agree = more weight to LLM; when they disagree = more weight to market

6. IMPLEMENTATION ARCHITECTURE:
   Where exactly in the pipeline should combination happen?

   Current pipeline:
   1. Claude estimates blind → raw_p
   2. Calibrate via Platt → cal_p
   3. Compare cal_p vs market_price → edge = cal_p - market_price
   4. If |edge| > threshold → trade

   Proposed (Bridgewater-style):
   1. Ensemble estimates blind → ensemble_p
   2. Calibrate via Platt → cal_p
   3. Combine cal_p with market_price → combined_p
   4. What edge metric do we use now? combined_p vs...what? The market price is already in combined_p.
   5. Do we need a different trading signal when using combination?

7. BACKTESTING COMBINATION METHODS:
   How to validate which combination works best:
   - Use our 532-market dataset
   - For each method: compute combined estimate, compare to outcome, measure Brier
   - Key metric: does the combined estimate have lower Brier than LLM-only AND market-only?
   - Secondary metric: does the combined estimate improve trading P&L?
   - Careful: don't overfit the combination weights to the backtest data

8. WHAT THE LITERATURE SAYS:
   Comprehensive survey of papers on combining model forecasts with market prices:
   - Satopää et al. (2014) — extremized aggregation
   - Ungar et al. (2012) — IARPA ACE tournament methods
   - Tetlock (2015) — superforecasting team aggregation
   - Baron et al. (2014) — two-stage combination
   - Any papers specific to combining LLMs with prediction markets (2024-2026)?

OUTPUT:
- Ranked comparison of combination methods with expected Brier improvement
- Recommended implementation (exact formula)
- Dynamic weighting rules (when to trust LLM more vs market more)
- Pipeline architecture diagram
- Backtest validation methodology
```

## Expected Outcome
- Exact formula for combining LLM ensemble estimate with market price
- Dynamic weighting rules based on context (liquidity, category, time)
- Comparison showing combined approach beats both LLM-only and market-only
- Implementation spec ready for Claude Code

## SOP
Store results in `research/ensemble_market_price_integration_deep_research.md`. Feed into P1-31 (Claude Code implementation). Update COMMAND_NODE.md with combination methodology.
