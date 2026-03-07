# P1-29: Evaluate Foresight-32B (Fine-Tuned Forecasting Model)
**Tool:** CLAUDE_DEEP_RESEARCH
**Status:** READY
**Expected ARR Impact:** +20-40% (potentially replaces Claude Haiku for estimation)

## Background (from P0-26 research)
Lightning Rod Labs' Foresight-32B achieved remarkable results:
- Fine-tuned Qwen3-32B specifically for prediction market forecasting
- **Brier score: 0.190** on 1,265 Polymarket questions
- **ECE: 0.062** (excellent calibration — far better than our 0.239)
- Outperformed ALL frontier models (GPT-4.5, Claude, etc.) at 10-100× smaller
- Uses RL fine-tuning with Brier score rewards

Our Claude Haiku: Brier 0.239, ECE terrible. Foresight-32B: Brier 0.190, ECE 0.062.

## Research Questions
1. Is Foresight-32B available via API? What's the cost per query?
2. Can we self-host a 32B model on our DigitalOcean VPS? GPU requirements?
3. What's the architecture — can we replicate the RL fine-tuning approach on our own data?
4. How does it handle different market categories (politics, weather, crypto)?
5. What's Lightning Rod Labs — are they open-sourcing the model weights?
6. Are there other fine-tuned forecasting models we should evaluate?
7. Could we fine-tune our own model using our 532+ resolved market dataset?

## Prompt for Deep Research
```
Research Lightning Rod Labs' Foresight-32B model for prediction market forecasting:
1. Is it publicly available? API access? Open-source weights?
2. Detailed architecture: What RL reward function? What training data?
3. Benchmarks vs frontier models (GPT-4.5, Claude Sonnet, o3) on prediction market tasks
4. Self-hosting requirements for a 32B parameter model (GPU memory, inference cost)
5. Similar fine-tuned forecasting models in the space
6. Feasibility of RL fine-tuning a smaller model (7B-13B) on Polymarket resolution data
7. Cost comparison: Claude Haiku API vs self-hosted 32B model at 1,000 queries/day
```

## Expected Outcome
- Decision: switch to Foresight-32B, add to ensemble, or fine-tune our own
- If self-hosting viable: deployment spec for VPS or cloud GPU
