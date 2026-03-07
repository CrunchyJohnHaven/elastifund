# P1-12: OpenAI GPT Integration for Ensemble
**Tool:** CLAUDE_CODE
**Status:** READY
**Expected ARR Impact:** +10-15% (ensemble diversification)

## Task
1. Build GPT-4o-mini client using OpenAI API
2. Use same anti-anchoring prompt as Claude
3. Cache results same way (sha256 key)
4. Backtest GPT-4o-mini alone on 532 markets
5. Compare to Claude Haiku alone
6. Build ensemble (Claude + GPT average)
7. Backtest ensemble vs individuals
8. GPT-4o-mini is ~$0.15/MTok input, $0.60/MTok output (cheaper than Haiku)

## Architecture
```python
class GPTEstimator:
    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def estimate(self, question: str, description: str = "") -> dict:
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=200,
            messages=[{"role": "user", "content": PROMPT.format(...)}],
        )
        return self._parse(response.choices[0].message.content)
```
