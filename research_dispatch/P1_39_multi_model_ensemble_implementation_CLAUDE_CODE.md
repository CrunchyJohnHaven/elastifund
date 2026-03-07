# P1-39: Multi-Model Ensemble Implementation (Claude + GPT + Grok)
**Tool:** CLAUDE_CODE
**Status:** READY
**Priority:** P1 — Academic evidence is the strongest of any improvement. Halawi et al. (2024) showed "LLM crowd" matches human crowd accuracy.
**Expected ARR Impact:** +20-40% (model-bias averaging is proven technique)
**Dependencies:** Requires OpenAI and xAI API keys

## Background
This builds on P0-02 (ensemble architecture spec) and P1-31 (Bridgewater ensemble approach). The academic evidence is overwhelming:
- Halawi et al. (2024): Ensemble of LLM prompts statistically equivalent to human crowd aggregate
- Bridgewater AIA (2025): LLM + market consensus outperforms either alone
- TMLR (2025): All LLMs have model-specific calibration errors that average out in ensemble

Our single-model Claude Haiku has Brier 0.239. An ensemble of 3 models with independent errors should theoretically achieve Brier < 0.18.

## Task

1. **Build model clients for all three models:**
   ```python
   class ModelClient(ABC):
       @abstractmethod
       def estimate_probability(self, question: str, context: str = "") -> dict:
           """Returns {probability: float, confidence: str, reasoning: str}"""

   class ClaudeClient(ModelClient):
       # Already exists in claude_analyzer.py — extract and wrap
       model = "claude-3-5-haiku-20241022"
       cost_per_call ≈ $0.005

   class GPTClient(ModelClient):
       model = "gpt-4o-mini"
       cost_per_call ≈ $0.003

   class GrokClient(ModelClient):
       # xAI API (api.x.ai)
       model = "grok-2"
       cost_per_call ≈ $0.010
   ```

2. **Use the SAME anti-anchoring prompt across all models.** Do NOT show market price to any model. The prompt from claude_analyzer.py (base-rate-first, explicit debiasing) should be adapted to each model's format but contain the same instructions.

3. **Implement aggregation methods (backtest all, pick best):**
   ```python
   class EnsembleAggregator:
       def simple_average(self, estimates: list[float]) -> float:
           """Robust baseline — start here."""
           return sum(estimates) / len(estimates)

       def weighted_by_brier(self, estimates: list[float], brier_scores: list[float]) -> float:
           """Weight inversely by historical Brier score."""
           weights = [1/bs for bs in brier_scores]
           return sum(e*w for e,w in zip(estimates, weights)) / sum(weights)

       def median(self, estimates: list[float]) -> float:
           """Robust to single-model outliers."""
           return sorted(estimates)[len(estimates)//2]

       def disagreement(self, estimates: list[float]) -> float:
           """Spread metric — high disagreement = low confidence = smaller position."""
           return max(estimates) - min(estimates)
   ```

4. **Two-stage pipeline (Bridgewater approach from P1-31):**
   - Stage 1: Each model estimates independently (no market price)
   - Stage 2: Aggregate model estimates → apply calibration → combine with market price using optimal weight

5. **Parallel API calls:** All three model queries fire simultaneously (asyncio) to minimize latency. Timeout after 15 seconds per model. If one model fails, fall back to 2-model ensemble.

6. **Cost management:**
   - 3 models × ~$0.006 avg = $0.018 per market analysis
   - At 20 markets/cycle, 288 cycles/day = 5,760 analyses/day = ~$104/day (too expensive!)
   - SOLUTION: Use ensemble only for trades that pass initial Claude-only screen
   - Flow: Claude Haiku screens all markets → only markets with >5% edge get full ensemble → ensemble decides final trade
   - This reduces ensemble calls to ~50-100/day = $1-2/day

7. **Backtest the ensemble:**
   - Use cached Claude estimates from 532-market dataset
   - Query GPT-4o-mini and Grok on the same 532 questions (one-time cost: ~$10)
   - Compare single-model vs ensemble Brier scores and win rates
   - Select optimal aggregation method

## API Setup
User needs to provide:
- OpenAI API key (for GPT-4o-mini): https://platform.openai.com/api-keys
- xAI API key (for Grok): https://console.x.ai/

Add to `.env`:
```
OPENAI_API_KEY=sk-...
XAI_API_KEY=xai-...
```

## Files to Create/Modify
- NEW: `src/ensemble.py` — EnsembleEstimator, ModelClient implementations
- NEW: `src/gpt_client.py` — GPT-4o-mini client
- NEW: `src/grok_client.py` — Grok client
- MODIFY: `src/claude_analyzer.py` — extract into ClaudeClient interface
- MODIFY: improvement_loop.py — add ensemble decision layer

## Expected Outcome
- 3-model ensemble operational in paper trading
- Backtest showing Brier score < 0.18 (vs current 0.239)
- Win rate improvement from 65% to 70%+
- Disagreement metric used as confidence signal (high disagreement → skip or reduce position)
