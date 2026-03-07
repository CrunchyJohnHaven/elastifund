# Elastifund

**An open-source AI trading system that exploits mispricings in prediction markets — and sends 20% of every dollar earned to veteran suicide prevention.**

---

## The Thesis

Prediction markets like Polymarket let people bet real money on real-world events. The price of each outcome *should* represent the crowd's best guess at the probability. But crowds are systematically wrong — they anchor on headlines, overweight favorites, and ignore base rates.

We built an AI system that thinks independently. It reads the question, reasons from first principles, and estimates the *true* probability — without seeing the market price, so it can't anchor on the crowd's mistakes.

When our AI disagrees with the market by enough, we trade. When the event resolves, the market pays out $1 or $0. If we're right more often than the market expects, we make money. Consistently.

## The Evidence

We backtested against 532 resolved Polymarket events. The system identified 372 trades.

| | |
|---|---|
| **Win rate** | **68.5%** (vs 50% random) |
| **NO-side win rate** | **70.2%** (exploiting favorite-longshot bias) |
| **Ruin probability** | **0%** across 10,000 Monte Carlo simulations |
| **Brier score** | **0.217** (well-calibrated probability estimates) |

The system is live now — paper trading 24/7 on a VPS in Frankfurt, 21 open positions across politics, sports, entertainment, and crypto markets. 436 cycles completed. 7,887 signals generated. Waiting for first batch of markets to resolve for live validation.

## How It Works

```
Every 5 minutes:

  1. SCAN      Pull 100 active markets from Polymarket
  2. ESTIMATE  Claude AI estimates true probability (anti-anchoring prompt)
  3. CALIBRATE Category-specific Platt scaling corrects for known AI biases
  4. DETECT    Compare calibrated estimate vs market price → find edge
  5. SIZE      Kelly criterion determines optimal bet size
  6. EXECUTE   Place order via Polymarket's CLOB (central limit order book)
  7. LEARN     Bayesian belief updating as new evidence arrives
```

The AI doesn't see the market price before estimating. This is critical — it prevents the AI from just agreeing with the crowd. It thinks independently, then we compare.

## What Makes This Different

**vs. "I'll just bet on stuff"** — We're systematic. Every trade has a measured edge, sized by Kelly criterion, risk-controlled by 6 safety layers. No gut feelings, no FOMO, no tilt.

**vs. Trading bots that use technical analysis** — We don't look at price charts. We reason about events: *what is the actual probability that Sweden qualifies for the World Cup?* Then we trade the gap between our answer and the market's.

**vs. Other AI approaches** — Our AI never sees the market price (anti-anchoring). We calibrate per category (politics =/= crypto =/= sports). We use LMSR pricing models to detect AMM inefficiencies. We update beliefs in real-time with Bayesian inference.

## The Stack

```
polymarket-bot/src/
  engine/loop.py          Main trading loop
  claude_analyzer.py      AI probability estimation (Claude Haiku)
  bayesian_signal.py      Sequential Bayesian belief updating (log-space)
  lmsr.py                 LMSR pricing + AMM inefficiency detection
  scanner.py              Polymarket Gamma API market scanner
  risk/sizing.py          Kelly criterion + time-aware dampener
  calibration/            Category-specific Platt scaling
  broker/                 CLOB execution (paper + live modes)
  safety.py               Kill switch, drawdown limits, exposure caps
  app/                    FastAPI monitoring dashboard (9 endpoints)

backtest/                 Strategy validation + Monte Carlo simulation
simulator/                Fill model + sensitivity analysis
research_dispatch/        90+ prioritized research tasks
```

98 tests. 0 regressions. Paper mode by default — no real money moves until you explicitly flip the switch.

## The Mission

**20% of all net trading profits go to veteran suicide prevention.** This is non-negotiable. It's the reason this project exists. The more the system earns, the more veterans get helped.

Organizations we support:
- [Veterans Crisis Line](https://www.veteranscrisisline.net/)
- [Stop Soldier Suicide](https://stopsoldiersuicide.org/)
- [22Until None](https://www.22untilnone.org/)

## Get Involved

We're looking for contributors who want to build something that matters.

**The deal is simple:**
1. You contribute — code, research, backtests, edge strategies, bug fixes
2. You can run your own instance of the system
3. 20% of your net trading profits go to veterans

That's the social contract. Not a legal obligation. A handshake between people who care.

### What You Can Work On

- **Edge research** — Find new categories or signals where AI beats the crowd
- **Model improvement** — Better prompts, ensemble methods, calibration tuning
- **Infrastructure** — Faster scanning, better execution, monitoring dashboards
- **Data science** — Backtest analysis, Monte Carlo simulation, portfolio optimization
- **Market expansion** — Kalshi integration, Metaculus, new platforms

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup instructions.

### Quick Start

```bash
git clone git@github.com:CrunchyJohnHaven/elastifund.git
cd elastifund/polymarket-bot
cp .env.example .env        # Edit with your API keys
pip install -e .             # Install dependencies
python -m pytest tests/ -v   # Verify everything works
python -m src.main           # Start paper trading
```

## Risks (We're Honest About These)

- **Regulatory** — CFTC is watching prediction markets. Polymarket could face restrictions.
- **Competition** — As more traders use AI, edges compress. We need to stay ahead.
- **Live vs backtest gap** — Backtests look great. Live results are unproven until markets resolve.
- **Scale limits** — At large sizes, our orders move the market. Edge shrinks with capital.

This is a science experiment with real money implications. We believe the hypothesis is strong. But we haven't proven it in live markets yet — that proof comes when the first batch of positions resolve.

## License

MIT — use it, fork it, improve it, run it. Just remember the mission.

---

Built by [John Bradley](https://github.com/CrunchyJohnHaven) and contributors.
