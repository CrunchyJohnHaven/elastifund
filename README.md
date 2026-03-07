# Elastifund

**An open-source, agent-run trading system. The AI makes every decision. I build the machine. 20% of all profits go to veteran suicide prevention.**

---

## What This Is

Elastifund is not a trading bot. It's a **research engine** that systematically discovers, tests, and documents trading strategies on prediction markets (Polymarket, Kalshi). The system runs autonomously — AI agents make all trading decisions. The human (John Bradley) builds the infrastructure, runs the research flywheel, and publishes every result openly.

This is also the most comprehensive open-source resource on agentic trading systems in existence. We document everything: what we built, what we tested, what worked, and — more importantly — what didn't. The diary of failures maps the territory of prediction market trading in a way nobody has done publicly before.

**Website:** [johnbradleytrading.com](https://johnbradleytrading.com) (coming soon)

## Current Status (March 7, 2026)

| | |
|---|---|
| **Capital deployed** | $347.51 ($247.51 Polymarket USDC + $100 Kalshi USD) |
| **Strategies catalogued** | 131 (7 deployed, 8 building, 10 rejected, 8 pre-rejected, 98 pipeline) |
| **Tests passing** | 223 (19 test files across bot/tests/ and tests/) |
| **Bot modules** | 27 Python modules in bot/ |
| **Signal sources** | 4 active + 2 building (A-6 guaranteed-dollar arb, B-1 templated dependency arb) |
| **Research dispatches** | 82 original investigations |
| **Backtest win rate** | 68.5% on 532 resolved markets |
| **Live validated P&L** | $0.00 (pre-revenue, building structural alpha pipeline) |

## How the Agent Thinks

```
Every 3 minutes, the system:

  1. SCAN       100+ active markets from Polymarket
  2. FILTER     Skip categories where AI has no edge (crypto, sports)
  3. SEARCH     Web search for recent context (agentic RAG)
  4. ESTIMATE   3 LLMs estimate probability independently (Claude + GPT + Groq)
               The AI never sees the market price. This prevents anchoring.
  5. CALIBRATE  Platt scaling corrects for known LLM overconfidence
  6. COMPARE    Calibrated estimate vs market price — is there an edge?
  7. SIZE       Kelly criterion determines optimal bet (quarter-Kelly, conservative)
  8. CONFIRM    If 2+ signal sources agree, boost confidence
  9. EXECUTE    Place maker order (0% fees) on Polymarket CLOB
```

## The Research Flywheel

This is not "build a bot and hope." It's a systematic, repeating research cycle:

```
┌────────────┐     ┌────────────┐     ┌────────────┐
│  RESEARCH  │────►│ IMPLEMENT  │────►│    TEST     │
│  Generate  │     │ Code top   │     │ Run through │
│  hypotheses│     │ strategies │     │ kill rules  │
└────────────┘     └────────────┘     └────────────┘
      ▲                                      │
      │                                      ▼
┌────────────┐     ┌────────────┐     ┌────────────┐
│   REPEAT   │◄────│  PUBLISH   │◄────│   RECORD   │
│  Feed into │     │ GitHub +   │     │ Document   │
│  next cycle│     │ website    │     │ everything │
└────────────┘     └────────────┘     └────────────┘
```

**Each 3-5 day cycle:** Generate 10-100 strategy hypotheses, implement the top 3-5, run them through the edge discovery pipeline (83 features, 10 strategy modules, 6 model types, automated kill rules), record every result (pass or fail), publish to GitHub and the website, and feed findings into the next research prompt.

After 10 cycles, we've tested 50+ strategies. After 20, we've mapped the entire territory of what works and what doesn't in AI prediction market trading — in public, with code.

## What We've Proven

- **LLM anti-anchoring works.** Hiding the market price from the AI and asking it to estimate independently produces calibrated probability estimates (Brier 0.217).
- **NO-side structural edge.** YES contracts are systematically overpriced. NO-side win rate: 70.2% across 532 markets (cf. jbecker.dev 72.1M trade analysis).
- **Calibration matters.** Raw LLM confidence at 90% is really ~71%. Platt scaling corrects this.
- **Makers win, takers lose.** +1.12% excess return for makers, -1.12% for takers across 72.1M Polymarket trades.

## What We've Honestly Failed At

- **All 10 tested strategies rejected.** 0% survival rate through the kill battery. Every rejection documented with specific numbers in [research/what_doesnt_work_diary_v1.md](research/what_doesnt_work_diary_v1.md).
- **Taker fees kill 60% of strategies.** 1.56% taker fee at 50/50 odds makes speed-based and most statistical strategies unviable. Maker-only (0% fees + 20% rebate) is the only viable execution path.
- **Signal sparsity kills 25%.** Most strategies produce 0-30 signals/month. You need 100+ for preliminary validation.
- **Kalshi weather rounding killed.** 27-35% accuracy on 4-bracket markets (chance is 25%). Edge too small.
- **ML feature discovery: zero surviving features.** 83-feature pipeline found nothing that survived walk-forward validation.
- **No validated live P&L yet.** Everything is backtest or shadow-tracking. We say this plainly.

These failures are not embarrassments — they are the most valuable content in the repo. They map the territory. See the full [failure diary](research/what_doesnt_work_diary_v1.md) for details.

## The Stack

```
bot/                         27 modules, 223 tests
├── jj_live.py              Autonomous trading loop + 6-source confirmation layer
├── llm_ensemble.py          Multi-model estimation (Claude + GPT + Groq) + agentic RAG
├── wallet_flow_detector.py  Smart wallet consensus signals
├── lmsr_engine.py           Bayesian pricing + market inefficiency detection
├── cross_platform_arb.py    Polymarket vs Kalshi arbitrage scanner
├── constraint_arb_engine.py Resolution-normalized structural arb engine
├── a6_executor.py           Multi-leg state machine + deterministic rollback
├── execution_readiness.py   Feed/restart/one-leg-loss gating for structural alpha
├── dependency_graph.py      B-1 implication/exclusion graph pipeline
├── b1_template_engine.py    Deterministic B-1 template families + compatibility matrices
├── relation_classifier.py   LLM relation classification with caching
├── ws_trade_stream.py       WebSocket CLOB feed + VPIN + OFI
├── vpin_toxicity.py         Flow toxicity detection (informed trading gate)
├── kill_rules.py            6 automated rejection criteria
├── lead_lag_engine.py       Granger causality + semantic verification
└── tests/                   223 unit + integration tests

polymarket-bot/src/
├── claude_analyzer.py       Single-model LLM estimation + Platt calibration
├── scanner.py               Gamma API market discovery
├── ensemble.py              Multi-model framework
├── safety.py                Kill switch, drawdown limits, exposure caps
├── risk/                    Kelly sizing, risk management
├── broker/                  Paper + live execution
├── calibration/             Category-specific Platt scaling
└── app/                     FastAPI monitoring dashboard

src/                         Edge Discovery Pipeline
├── data_pipeline.py         Market data collection (83 features)
├── strategies/              10 hypothesis families
├── models/                  6 competing model types
├── backtest.py              Walk-forward validation + kill rules
└── reporting.py             Auto-generated strategy reports

backtest/                    Backtesting + Monte Carlo simulation
simulator/                   Fill model + sensitivity analysis
research/                    74+ research dispatches + strategy docs
```

## The Mission

**20% of all net trading profits go to veteran suicide prevention.** Non-negotiable.

- [Veterans Crisis Line](https://www.veteranscrisisline.net/)
- [Stop Soldier Suicide](https://stopsoldiersuicide.org/)
- [22Until None](https://www.22untilnone.org/)

## Get Involved

We're building this in public because the open-source approach makes the system better. Contributors get scrutiny, collaboration, and credibility that a closed system can't match.

**What you can work on:**
- **Edge research** — Find strategies where AI beats the crowd. We have 100 hypotheses queued.
- **Model improvement** — Better prompts, ensemble methods, calibration techniques
- **Infrastructure** — Faster scanning, better execution, monitoring, dashboards
- **Data science** — Backtest analysis, Monte Carlo, portfolio optimization
- **Market expansion** — Kalshi, Metaculus, new platforms
- **Education** — Write explanations that make this accessible to beginners

### Quick Start

```bash
git clone git@github.com:CrunchyJohnHaven/elastifund.git
cd elastifund/polymarket-bot
cp .env.example .env        # Edit with your API keys
pip install -e .             # Install dependencies
python -m pytest tests/ -v   # Verify (345 tests should pass)
python -m src.main           # Start paper trading
```

### The Social Contract

You contribute. You can run your own instance. 20% of your trading profits go to veterans. Not a legal obligation — a handshake between people who care about building something that matters.

## Risks (We're Honest)

- **Competition:** Jump Trading, Susquehanna, Jane Street have dedicated prediction market teams. We're a lean operation competing on methodology, not capital.
- **Efficiency:** Only 7.6% of Polymarket wallets are profitable. The base rate is brutal.
- **Regulatory:** CFTC oversight of prediction markets is evolving.
- **Live vs backtest:** Backtests look great. Live results are unproven.
- **Scale:** At large sizes, orders move the market. Edge shrinks with capital.

This is a science experiment with real money at stake. We think the research methodology is sound. But we document our honest uncertainty alongside our confident results.

## Key Documents

| Document | Purpose |
|----------|---------|
| [FLYWHEEL_STRATEGY.md](FLYWHEEL_STRATEGY.md) | The master project strategy — how the research cycle works |
| [COMMAND_NODE_v1.1.0.md](COMMAND_NODE_v1.1.0.md) | Single source of truth for all system state (paste into AI sessions) |
| [research/edge_backlog_ranked.md](research/edge_backlog_ranked.md) | 131 strategies ranked, tracked, and updated every cycle |
| [research/what_doesnt_work_diary_v1.md](research/what_doesnt_work_diary_v1.md) | Comprehensive failure documentation — the most valuable doc in the repo |
| [EDGE_DISCOVERY_SYSTEM.md](EDGE_DISCOVERY_SYSTEM.md) | Technical spec for the automated edge research pipeline |
| [FastTradeEdgeAnalysis.md](FastTradeEdgeAnalysis.md) | Auto-generated status of all tested strategies |
| [ProjectInstructions.md](ProjectInstructions.md) | Quick-start guide for AI coding sessions |

## License

MIT — use it, fork it, improve it, run it. Just remember the mission.

---

Built by [John Bradley](https://github.com/CrunchyJohnHaven). The AI makes the trades. I build the machine.
