# LLM Ensemble Probability Estimator — Implementation Spec v1.0

**Date:** March 7, 2026 | **Status:** Ready for Claude Code implementation
**Replaces:** Single Claude Haiku analyzer on VPS
**Target deploy:** Week 2 (March 10-16), after VPS migration to Dublin

---

## 1. Architecture Overview

```
Market Question
      │
      ▼
┌─────────────────────────────┐
│   Category Router           │  ← Skip crypto/sports (priority 0)
│   (from local analyzer)     │     Route politics/weather/economic
└──────────┬──────────────────┘
           │
    ┌──────┼──────┐──────┐
    ▼      ▼      ▼      ▼
┌──────┐┌──────┐┌──────┐┌──────┐
│Groq  ││Groq  ││Claude││GPT-4o│   4 independent agents
│Llama ││Qwen3 ││Haiku ││Mini  │   No market price shown (anti-anchoring)
│3.3   ││32B   ││      ││      │   Base-rate-first prompt
│70B   ││      ││      ││      │
└──┬───┘└──┬───┘└──┬───┘└──┬───┘
   │       │       │       │
   ▼       ▼       ▼       ▼
┌─────────────────────────────┐
│   Trimmed Mean Aggregation  │  ← Drop highest & lowest, average rest
│   + Outlier Detection       │     Flag if spread > 0.25
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│   Platt Scaling Calibration │  ← A=0.5914, B=-0.3977
│   (per-domain when enough   │     calibrated = sigmoid(A*logit(raw)+B)
│    data accumulates)        │
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│   Bridgewater Blending      │  ← 67% market price / 33% AI forecast
│   + Taker Fee Subtraction   │     net_edge = |blended - market| - fee
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│   Signal Output             │  ← direction, edge, confidence, consensus
│   + Kelly Sizing            │     Consensus score: % models agreeing
└─────────────────────────────┘
```

---

## 2. Model Selection

| Model | Provider | Cost | Speed | Purpose | Daily Limit (Free) |
|-------|----------|------|-------|---------|-------------------|
| Llama 3.3 70B Versatile | Groq | $0 (free tier) | ~394 TPS | Primary workhorse | 1,000 req/day |
| Llama 3.1 8B Instant | Groq | $0 (free tier) | Very fast | Fast screening + diversity | 14,400 req/day |
| Claude Haiku 3.5 | Anthropic | ~$0.002/call | Medium | Anthropic reasoning style | Pay-as-you-go |
| GPT-4o Mini | OpenAI | ~$0.001/call | Fast | OpenAI perspective | Pay-as-you-go |

**Also available on Groq free tier (swap in as needed):**
- Llama 4 Maverick 17B (1,000 req/day) — newer Llama 4 reasoning
- Llama 4 Scout 17B (1,000 req/day) — newer Llama 4 reasoning
- Qwen QwQ 32B (model ID: `qwen-qwq-32b`) — if available, provides Alibaba training data diversity

**Why these 4:** Diversity across model families is the key driver of ensemble benefit (Schoenegger et al. 2024). Three providers (Meta/Llama via Groq, Anthropic/Claude, OpenAI/GPT) provide maximum diversity. The two Groq models are free, keeping costs minimal. Llama 3.1 8B has 14,400 req/day — usable as a pre-screen filter (run all markets through 8B first, only escalate to full ensemble for promising ones).

**Daily capacity:** At 50 markets/day × 4 models = 200 calls. Groq free tier: Llama 3.3 at 1,000/day + Llama 3.1 8B at 14,400/day (both sufficient). Claude Haiku at ~$0.002/call × 50 = $0.10/day. GPT-4o Mini at ~$0.001/call × 50 = $0.05/day. **Total: ~$4.50/month.**

**Screening optimization:** Use Llama 3.1 8B (14,400/day) to pre-screen all 100 markets. Only run the full 4-model ensemble on markets where 8B finds edge > 3%. This cuts ensemble cost by ~60% while maintaining signal quality on the markets that matter.

**Escalation tier (optional, Phase 2):** For high-edge signals (>15%) or high-value markets (>$100K volume), run a 5th "supervisor" call using Claude Sonnet ($3/$15 per M tokens) that reads all 4 rationales and produces a reconciled forecast. Cost: ~$0.05/call × ~10 escalations/day = $15/month.

---

## 3. Prompt Design

All models receive the **same prompt template** (adapted from the local analyzer's research-backed design). The market price is NEVER shown to any model.

```python
ENSEMBLE_PROMPT = """Estimate the probability that this event resolves YES.

Question: {question}
{context_section}
{news_section}

Step 1: What is the historical base rate for events like this? (What fraction of similar events in the past resolved YES?)
Step 2: What specific evidence adjusts the probability up or down from the base rate?
Step 3: Give your final estimate.

IMPORTANT CALIBRATION NOTE: Language models have a documented tendency to overestimate YES probabilities by 20-30%. When you feel 70-80% confident in YES, the true rate is closer to 50-55%. Adjust your estimate downward accordingly.

Respond in this exact format:
PROBABILITY: <number between 0.01 and 0.99>
CONFIDENCE: <low, medium, or high>
REASONING: <1-2 sentences>"""
```

**Parsing:** Same regex parser as local analyzer — extract PROBABILITY, CONFIDENCE, REASONING lines. Fall back to 0.5 if parsing fails (don't use market price as default — that introduces anchoring through the back door).

---

## 4. Aggregation Pipeline

### Step 1: Collect Estimates

```python
estimates = []  # List of (probability, confidence, model_name, reasoning)
for model in ensemble_models:
    result = await model.analyze(question, context)
    estimates.append(result)
```

### Step 2: Trimmed Mean

```python
def trimmed_mean(probabilities: list[float]) -> float:
    """Drop highest and lowest, average the rest.

    With 4 models: drops 1 highest + 1 lowest, averages remaining 2.
    With 5+ models: drops top/bottom 20%.
    """
    sorted_probs = sorted(probabilities)
    n = len(sorted_probs)
    if n <= 2:
        return sum(sorted_probs) / n
    trim = max(1, n // 5)  # 20% trim
    trimmed = sorted_probs[trim:-trim] if trim > 0 else sorted_probs
    return sum(trimmed) / len(trimmed)
```

### Step 3: Consensus Score

```python
def consensus_score(probabilities: list[float], threshold: float = 0.5) -> float:
    """What fraction of models agree on the direction (YES vs NO)?

    Returns 0.0-1.0. Higher = stronger agreement.
    """
    above = sum(1 for p in probabilities if p > threshold)
    return max(above, len(probabilities) - above) / len(probabilities)
```

### Step 4: Outlier Detection

```python
def detect_outliers(probabilities: list[float]) -> dict:
    """Flag if any model disagrees strongly with the consensus."""
    mean = sum(probabilities) / len(probabilities)
    spread = max(probabilities) - min(probabilities)
    return {
        "spread": spread,
        "high_disagreement": spread > 0.25,  # Flag if models disagree by >25pp
        "outlier_models": [
            (i, p) for i, p in enumerate(probabilities)
            if abs(p - mean) > 0.20
        ],
    }
```

### Step 5: Platt Calibration

```python
# Same constants from local analyzer
PLATT_A = 0.5914
PLATT_B = -0.3977

def calibrate(raw_prob: float) -> float:
    """Apply Platt scaling. 90% → 71%, 80% → 60%, 70% → 53%."""
    import math
    raw_prob = max(0.001, min(0.999, raw_prob))
    logit = math.log(raw_prob / (1 - raw_prob))
    scaled = PLATT_A * logit + PLATT_B
    scaled = max(-30, min(30, scaled))
    return max(0.01, min(0.99, 1.0 / (1.0 + math.exp(-scaled))))
```

### Step 6: Bridgewater Blending

```python
def blend_with_market(ai_forecast: float, market_price: float,
                       ai_weight: float = 0.33) -> float:
    """Blend AI forecast with market price.

    Bridgewater AIA finding: 67% market / 33% AI optimal.
    Even when AI trails market in accuracy, it contains independent info.
    """
    return (1 - ai_weight) * market_price + ai_weight * ai_forecast
```

### Step 7: Edge Calculation + Signal

```python
def compute_signal(blended_prob: float, market_price: float,
                   category: str, consensus: float) -> dict:
    """Compute final trading signal with fee awareness."""
    raw_edge = blended_prob - market_price

    # Taker fee (from local analyzer)
    TAKER_FEE_RATES = {"crypto": 0.025, "sports": 0.007, "default": 0.0}
    rate = TAKER_FEE_RATES.get(category, 0.0)
    buy_price = market_price if raw_edge > 0 else (1 - market_price)
    taker_fee = buy_price * (1 - buy_price) * rate

    net_edge = abs(raw_edge) - taker_fee

    # Asymmetric thresholds (from local analyzer)
    YES_THRESHOLD = 0.15  # Higher bar (56% historical win rate)
    NO_THRESHOLD = 0.05   # Lower bar (76% historical win rate)

    # Require consensus >= 0.75 (3/4 models agree on direction)
    if consensus < 0.75:
        return {"direction": "hold", "edge": 0.0, "reason": "low_consensus"}

    if raw_edge > 0 and net_edge >= YES_THRESHOLD:
        return {"direction": "buy_yes", "edge": net_edge}
    elif raw_edge < 0 and net_edge >= NO_THRESHOLD:
        return {"direction": "buy_no", "edge": net_edge}
    else:
        return {"direction": "hold", "edge": net_edge}
```

---

## 5. Implementation Plan (for Claude Code session)

### File: `src/ensemble.py` (~300 lines)

```python
"""LLM Ensemble Probability Estimator.

Replaces single-model Claude Haiku analysis with 4-model ensemble:
Groq Llama 3.3 70B, Groq Qwen3 32B, Claude Haiku, GPT-4o Mini.

Uses trimmed mean aggregation, Platt calibration, Bridgewater blending.
"""

import asyncio
import os
import math
import time
from dataclasses import dataclass
from typing import Optional

# Model adapters
class GroqAdapter:
    """Calls Groq API (free tier). Supports Llama + Qwen models."""
    def __init__(self, model: str, api_key: str = None):
        self.model = model
        self.api_key = api_key or os.getenv("GROQ_API_KEY", "")
        self.base_url = "https://api.groq.com/openai/v1"

    async def analyze(self, prompt: str) -> dict:
        """Call Groq API with OpenAI-compatible endpoint."""
        import aiohttp
        headers = {"Authorization": f"Bearer {self.api_key}",
                   "Content-Type": "application/json"}
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 300,
            "temperature": 0.3,  # Low temp for calibrated estimates
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{self.base_url}/chat/completions",
                                     headers=headers, json=payload) as resp:
                data = await resp.json()
                return data["choices"][0]["message"]["content"]

class ClaudeAdapter:
    """Calls Anthropic Claude API."""
    # ... (reuse existing Anthropic client pattern from local analyzer)

class OpenAIAdapter:
    """Calls OpenAI API for GPT-4o Mini."""
    # ... (standard OpenAI chat completions)

class EnsembleAnalyzer:
    """Main ensemble class. Drop-in replacement for ClaudeAnalyzer."""

    def __init__(self):
        self.screener = GroqAdapter("llama-3.1-8b-instant")  # 14,400/day, pre-screen
        self.models = [
            GroqAdapter("llama-3.3-70b-versatile"),   # 1,000/day
            self.screener,                             # Also in ensemble
            ClaudeAdapter("claude-haiku-4-5-20241022"),
            OpenAIAdapter("gpt-4o-mini"),
        ]

    async def analyze_market(self, question, market_price, context=""):
        # 1. Build prompt (no market price)
        # 2. Fan out to all models concurrently
        # 3. Parse responses
        # 4. Trimmed mean
        # 5. Consensus check
        # 6. Platt calibration
        # 7. Bridgewater blend
        # 8. Edge + signal
        pass
```

### New environment variables needed:

```bash
# Add to .env on Dublin VPS
GROQ_API_KEY=gsk_...          # Get from console.groq.com (free, no card)
OPENAI_API_KEY=sk-...         # Get from platform.openai.com
# Existing: ANTHROPIC_API_KEY already set
```

### Dependencies to add:

```bash
pip install aiohttp  # For async HTTP calls to Groq/OpenAI
# groq and openai packages NOT needed — using raw HTTP for simplicity
```

### Integration with jj_live.py:

```python
# In jj_live.py, replace:
#   from src.claude_analyzer import ClaudeAnalyzer
#   analyzer = ClaudeAnalyzer(...)
# With:
from src.ensemble import EnsembleAnalyzer
analyzer = EnsembleAnalyzer()

# The EnsembleAnalyzer.analyze_market() returns the same dict format
# as the local ClaudeAnalyzer — drop-in compatible.
```

---

## 6. Logging & Monitoring

Each ensemble call logs:

```json
{
    "question": "Will Trump win 2028?",
    "models": {
        "llama-3.3-70b": {"prob": 0.65, "confidence": "high", "latency_ms": 340},
        "qwen3-32b": {"prob": 0.58, "confidence": "medium", "latency_ms": 280},
        "claude-haiku": {"prob": 0.72, "confidence": "high", "latency_ms": 520},
        "gpt-4o-mini": {"prob": 0.61, "confidence": "medium", "latency_ms": 310}
    },
    "trimmed_mean": 0.63,
    "consensus": 1.0,
    "spread": 0.14,
    "calibrated": 0.54,
    "blended": 0.52,
    "market_price": 0.50,
    "net_edge": 0.02,
    "direction": "hold",
    "total_latency_ms": 520
}
```

Store in SQLite for monthly Platt recalibration once markets resolve.

---

## 7. Cost Projection

| Component | Monthly Cost |
|-----------|-------------|
| Groq Llama 3.3 70B (free tier) | $0 |
| Groq Qwen3 32B (free tier) | $0 |
| Claude Haiku (50 calls/day × 30 days) | ~$3.00 |
| GPT-4o Mini (50 calls/day × 30 days) | ~$1.50 |
| **Total** | **~$4.50/month** |

With supervisor escalation (Phase 2): add ~$15/month for Claude Sonnet on high-confidence signals.

---

## 8. Rollout Plan

**Phase 1 (Week 2, March 10-16):** Deploy 2-model ensemble (Groq Llama 3.3 + Claude Haiku). This requires only adding the Groq adapter and aggregation logic. No new API keys beyond Groq free tier signup.

**Phase 2 (Week 3):** Add Qwen3 32B + GPT-4o Mini for full 4-model ensemble. Add consensus gating (require 75%+ agreement).

**Phase 3 (Week 4+):** Add supervisor escalation tier. Begin collecting resolved market data for per-domain Platt recalibration.

---

## 9. Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Groq free tier gets removed or rate-limited harder | Fall back to Claude Haiku solo (already working). Groq paid tier is cheap ($0.59/$0.79 per M tokens). |
| Model responses are too slow for 3-min cycle | All 4 models called concurrently (asyncio.gather). Max latency = slowest model (~1-2 seconds). 3-min cycle has 178 seconds of headroom. |
| Models disagree wildly (spread > 0.25) | High-disagreement flag → reduce position size or skip. Log for analysis. |
| Groq returns rate limit errors (429) | Exponential backoff with 3 retries. If persistent, degrade gracefully (run 3 models instead of 4). |
| Ensemble is overfit to same training data | 3 different model families (Meta, Alibaba, Anthropic/OpenAI) ensures training data diversity. |

---

*This spec is ready for a Claude Code session to implement. Drop into session with: "Read ~/Desktop/elastifund/docs/strategy/llm_ensemble_build_spec.md and implement src/ensemble.py on the Dublin VPS."*
