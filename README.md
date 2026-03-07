# Elastifund

AI-powered prediction market trading system. Uses Claude, GPT, and Grok to find mispricings on Polymarket, then trades them with Kelly-optimal sizing.

**20% of all net profits go to veteran suicide prevention. Non-negotiable.**

---

## How It Works

1. **Scan** — Pulls active markets from Polymarket's Gamma API
2. **Estimate** — Claude (+ ensemble) estimates true probability independent of market price
3. **Detect Edge** — Compares AI estimate vs market. If divergence exceeds threshold, it's a trade
4. **Size** — Kelly criterion with time-aware dampening (never full Kelly on short-duration markets)
5. **Execute** — Places orders via Polymarket CLOB. Paper mode by default, live mode opt-in
6. **Learn** — Bayesian belief updating as new evidence arrives. Category-specific calibration

## Performance (Backtest)

| Metric | Value |
|--------|-------|
| Markets tested | 532 |
| Win rate | 68.5% |
| NO-side win rate | 70.2% |
| Ruin probability | 0% (10K Monte Carlo sims) |
| Brier score | 0.217 |

Live validation in progress. Paper trading on DigitalOcean VPS, 24/7.

## Architecture

```
polymarket-bot/
  src/
    engine/           Trading loop (configurable interval)
    claude_analyzer.py AI probability estimation
    bayesian_signal.py Sequential Bayesian belief updating (log-space)
    lmsr.py           LMSR pricing model for AMM inefficiency detection
    scanner.py        Gamma API market scanner
    risk/sizing.py    Kelly criterion + time-aware dampener
    calibration/      Category-specific Platt scaling
    broker/           CLOB execution (paper + live)
    safety.py         Kill switch, drawdown limits, exposure caps
    app/              FastAPI dashboard (9 endpoints)
  backtest/           Strategy validation + Monte Carlo
  simulator/          Fill model + sensitivity analysis
  data_layer/         SQLAlchemy data infrastructure
  tests/              98 tests, 0 regressions
```

## Quick Start

```bash
# Clone
git clone git@github.com:CrunchyJohnHaven/elastifund.git
cd elastifund/polymarket-bot

# Set up environment
cp .env.example .env
# Edit .env with your API keys (paper mode works without Polymarket keys)

# Install
pip install -r requirements.txt  # or: pip install -e .

# Run (paper mode)
python -m src.main

# Run tests
python -m pytest tests/ -v
```

## Key Modules

| Module | What It Does |
|--------|-------------|
| `lmsr.py` | LMSR cost function, softmax pricing, AMM inefficiency detection |
| `bayesian_signal.py` | Log-space sequential Bayesian updating with evidence decay |
| `risk/sizing.py` | Kelly sizing with 6-tier time dampener (5min markets capped at 5% Kelly) |
| `calibration/` | Category + directional Platt scaling (YES-side: 82% calibrated accuracy) |
| `engine/loop.py` | Main loop: scan, estimate, detect edge, size, execute, learn |

## Risk Controls (6 Layers)

1. Kill switch (DB-backed, API-controllable)
2. Max position USD
3. Max orders/hour rate limiting
4. Max daily drawdown (auto-triggers kill switch)
5. Stale price guard
6. Volatility pause

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to get involved.

**The deal:** You contribute code and research. You run your own instance. 20% of your net trading profits go to veteran suicide prevention. That's the social contract.

## License

MIT

---

Built by [John Bradley](https://github.com/CrunchyJohnHaven) and collaborators.
