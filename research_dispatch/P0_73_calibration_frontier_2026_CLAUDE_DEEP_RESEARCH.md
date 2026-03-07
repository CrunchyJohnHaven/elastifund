# P0-73: LLM Calibration Frontier — What's Working in 2026
**Tool:** CLAUDE_DEEP_RESEARCH
**Status:** READY
**Priority:** P0 — Our Brier score (0.245 OOS) is the single biggest constraint on ARR. Need to know the frontier.
**Expected ARR Impact:** +20–50% (calibration improvement directly multiplies returns)

## Prompt (paste into Claude.ai with Deep Research enabled)

```
Deep research on the current state-of-the-art in LLM probability calibration for prediction and forecasting, as of early 2026:

CONTEXT:
I'm building a prediction market trading system using LLMs (Claude, GPT, Grok). My current best calibration achieves:
- Brier score: 0.245 (out-of-sample, Platt scaling)
- ECE: ~0.08
- Win rate: 68.5% on binary prediction markets
- Frontier target: Brier 0.075–0.10 (system + market price integration)

I've already implemented: Platt scaling (logistic regression in logit space), asymmetric thresholds (YES 15% / NO 5%), category routing, confidence-weighted sizing. These got me from Brier 0.286 (raw) to 0.245 (calibrated).

I need to close the gap from 0.245 → 0.10. What's available RIGHT NOW?

RESEARCH QUESTIONS:

1. STATE OF THE ART (March 2026):
   What are the best published Brier scores / ECE for LLM forecasting systems?
   - Lightning Rod Labs' Foresight-32B: claimed ECE 0.062 via RL fine-tuning. Is there more detail?
   - Bridgewater's AIA Forecaster: claimed to match superforecasters. Exact numbers?
   - ForecastBench (Karger 2025): what were the top system scores?
   - Any new papers since November 2025 on LLM calibration?
   - What's the current human superforecaster Brier benchmark on Polymarket-style questions?

   For each system, what calibration technique did they use?

2. CALIBRATION TECHNIQUES BEYOND PLATT SCALING:
   I've implemented Platt scaling. What else exists?

   a. Temperature scaling with learned temperature per category
   b. Isotonic regression (I know about this — when does it beat Platt?)
   c. Beta calibration (Kull et al.)
   d. Venn-Abers predictors
   e. Conformal calibration
   f. Calibration via RL fine-tuning (Foresight-32B approach)
   g. Mixture of calibrators
   h. Calibration via verbalized uncertainty (asking the LLM "how confident are you?")
   i. Any novel techniques published 2025-2026?

   For each: expected Brier improvement over Platt, data requirements, implementation complexity, and citations.

3. MULTI-MODEL CALIBRATION:
   When ensembling Claude + GPT + Grok:
   - Should calibration happen BEFORE or AFTER aggregation?
   - Calibrate each model individually, then average? Or average raw, then calibrate?
   - Does the ensemble itself need calibration? (meta-calibration)
   - What aggregation method works best with post-hoc calibration?
     - Simple average
     - Weighted by inverse Brier
     - Logarithmic pool
     - Beta-Transformed Linear Pool (BTLP)
   - Cite papers comparing these approaches.

4. MARKET PRICE INTEGRATION (Bridgewater Approach):
   Bridgewater found that combining LLM estimate with market consensus beats both alone.
   - Exactly how should LLM estimate and market price be combined?
   - Weighted average? (what weights?)
   - Bayesian update? (LLM as prior, market as likelihood?)
   - Signal-dependent weighting? (more weight to LLM when market is thin?)
   - Does showing the market price to the LLM (post-estimation) help or hurt?
   - Cite the exact Bridgewater methodology if available.

5. CALIBRATION ON SMALL DATASETS:
   I have 532 resolved markets. This is small.
   - What's the minimum dataset size for reliable Platt scaling?
   - For isotonic regression?
   - Should I use cross-validation folds instead of a single train/test split?
   - Leave-one-out cross-validation: practical for my dataset size?
   - Bayesian calibration methods for small data?
   - Transfer calibration from a larger dataset (e.g., calibrate on Metaculus questions, transfer to Polymarket)?

6. ONLINE CALIBRATION (LIVE UPDATING):
   As new markets resolve, how should I update calibration?
   - Full refit every N trades?
   - Exponential moving average Platt parameters?
   - Online logistic regression?
   - CUSUM / change-point detection for calibration drift?
   - What's the optimal refit frequency given my trade volume (~5/day, ~150/month)?

7. CATEGORY-SPECIFIC vs GLOBAL CALIBRATION:
   I'm about to implement category-specific Platt parameters.
   - When is category-specific better than global?
   - How many samples per category are needed?
   - Hierarchical calibration: use global as prior, category-specific as update?
   - Has anyone published on domain-specific calibration for LLM forecasters?

8. KNOWN CALIBRATION FAILURE MODES:
   What makes calibration fail?
   - Distribution shift (training data ≠ live data)
   - Temporal non-stationarity (calibration changes over time)
   - LLM model updates (Anthropic changes Claude → calibration invalidated)
   - Category composition shift (more political markets → old calibration is wrong)
   - How to detect each failure mode? What are the best monitoring metrics?

9. PRACTICAL BRIER TARGETS:
   Given my system architecture (LLM probability estimation + Platt calibration + ensemble + RAG + market price integration):
   - What Brier score should I realistically target?
   - What's the theoretical floor for a system like this?
   - Is 0.10 achievable without fine-tuning? With fine-tuning?
   - What Brier score would make this system competitive with Polymarket's best automated traders?

10. IMPLEMENTATION PRIORITY:
    Given I have Platt scaling already working:
    - What's the single highest-impact calibration improvement I should make next?
    - In what order should I implement the remaining techniques?
    - Are there any techniques I should SKIP (not worth the complexity)?

OUTPUT FORMAT:
- For each technique: expected Brier improvement, implementation effort, data requirements, and citations
- Ranked priority list: what to implement and in what order
- A "calibration roadmap" from my current 0.245 → target 0.10 with intermediate milestones
```

## Expected Outcome
- Comprehensive survey of calibration techniques with Brier improvement estimates
- Ranked implementation priority list
- Clear roadmap: 0.245 → 0.18 → 0.14 → 0.10 with specific techniques at each step
- Data requirements for each technique (do we have enough data?)
- Failure modes and monitoring strategies

## SOP
Store results in `research/calibration_frontier_2026_deep_research.md`. Update `research/calibration_2_0_plan.md` with new techniques. Update COMMAND_NODE.md. Feed implementation priorities into Claude Code dispatch queue.
