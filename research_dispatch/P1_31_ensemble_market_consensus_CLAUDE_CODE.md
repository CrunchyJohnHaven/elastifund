# P1-31: LLM + Market Consensus Ensemble (Bridgewater Approach)
**Tool:** CLAUDE_CODE
**Status:** READY
**Expected ARR Impact:** +15-30% (proven by Bridgewater AIA research)

## Background (from P0-26 research)
Bridgewater's AIA Forecaster (Nov 2025) found that:
- AIA alone underperformed liquid market consensus
- But **AIA + market consensus ensemble OUTPERFORMED consensus alone**
- This proves LLMs contribute additive, diversifying information even when they lose head-to-head
- GPT-4.5 copies market forecasts with 0.994 correlation when given them — so DON'T give market price for estimation, but DO use it for final ensemble

## Task
Build a two-stage pipeline:
1. **Stage 1 (current):** Claude estimates probability WITHOUT seeing market price (anti-anchoring)
2. **Stage 2 (new):** Combine Claude's calibrated estimate with market price using weighted average

```python
class EnsembleDecision:
    def combine(self, claude_calibrated: float, market_price: float,
                claude_weight: float = 0.3) -> float:
        """Combine Claude estimate with market consensus.

        Default weight 0.3 for Claude based on Brier score ratio:
        Market consensus is typically more accurate, so it gets higher weight.
        But Claude adds diversifying info that improves ensemble.
        """
        ensemble = claude_weight * claude_calibrated + (1 - claude_weight) * market_price
        return ensemble

    def compute_signal(self, ensemble_prob: float, market_price: float) -> dict:
        """Signal is based on ensemble vs market, not Claude vs market."""
        edge = ensemble_prob - market_price
        # Only trade when ensemble disagrees with market
        return {"edge": edge, "direction": "buy_yes" if edge > 0 else "buy_no"}
```

## Implementation Steps
1. Add `ensemble_weight` parameter to ClaudeAnalyzer config
2. After calibration, combine with market price
3. Compute edge as ensemble_prob - market_price
4. Backtest on 532 markets with various claude_weight values (0.1, 0.2, 0.3, 0.4, 0.5)
5. Select optimal weight by minimizing Brier score

## Expected Outcome
- Lower Brier score than either Claude-only or market-only
- More conservative position-taking (fewer false signals)
- Better risk-adjusted returns
