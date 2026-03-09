# Execute Instance #6 — Data Pull & Pipeline Refresh

You are an autonomous Codex instance for the Elastifund trading system. Execute every step below without human intervention. Report findings, commit code, and produce the handoff artifact.

---

## STATE SNAPSHOT (Injected 2026-03-09 v2.8.0)

- Pipeline status: REJECT ALL (all hypotheses failed kill rules or expectancy tests)
- Last pipeline run: 2026-03-09T01:05:57+00:00
- Markets observed: 74 total (29×15-min, 38×5-min, 7×4-hour)
- Trade records: 2,850
- Unique wallets: 1,591
- Platt calibration: A=0.5914, B=-0.3977 (532-market fit)
- Edge thresholds: YES=0.15, NO=0.05 (now env-var configurable)
- Strategies validated: 0 | Candidates: 0
- A-6: 563 allowed neg-risk events, 57 qualified, 0 executable below 0.95
- B-1: 0 deterministic template pairs in first 1,000 allowed markets
- Wallet-flow: ready (80 scored wallets, fast_flow_restart_ready=true)
- Tests: 1,278 total verified

---

## OBJECTIVE

Pull fresh market data, evaluate current opportunities against current, aggressive, and wide-open thresholds, and produce an updated `FAST_TRADE_EDGE_ANALYSIS.md`. The key question: does lowering thresholds unlock any real trades?

## YOU OWN

`src/`, `backtest/`, `data/`, `data_layer/`, `reports/`, `FAST_TRADE_EDGE_ANALYSIS.md`

## DO NOT TOUCH

`bot/` (except reading signal configs), `docs/`, website files, `CLAUDE.md`, `COMMAND_NODE.md`

## STEPS

1. Read `PROJECT_INSTRUCTIONS.md` Section 3 for current signal architecture and data sources.

2. Read `docs/strategy/edge_discovery_system.md` for the hypothesis testing pipeline architecture.

3. Pull fresh Polymarket data:
   ```bash
   mkdir -p data/pulls/$(date +%Y%m%dT%H%M%S)
   curl -s "https://gamma-api.polymarket.com/events?closed=false&limit=500" > data/pulls/$(date +%Y%m%dT%H%M%S)/gamma_events.json
   ```

4. Analyze the fresh data — for each market compute:
   - Resolution time (hours from now)
   - YES price
   - Category classification
   - Whether it passes current filters (price 0.10-0.90, resolution <48h, category priority >=1)

5. **Threshold sensitivity analysis** — this is the key deliverable:

   For each market that passes basic filters (price window + resolution), compute:
   - What LLM raw probability is required to trigger a YES trade at current thresholds (YES=0.15)?
   - What LLM raw probability is required at aggressive thresholds (YES=0.08)?
   - What LLM raw probability is required at wide-open thresholds (YES=0.05)?
   - How many markets become theoretically tradeable at each threshold?

   The Platt calibration formula is:
   ```python
   calibrated = 1 / (1 + exp(-(A * log(p/(1-p)) + B)))
   # where A=0.5914, B=-0.3977
   # YES trade fires when: calibrated - market_price >= YES_THRESHOLD
   # NO trade fires when: market_price - calibrated >= NO_THRESHOLD (when calibrated < market_price)
   ```

6. Run the A-6 sum-violation scanner if available:
   ```bash
   python3 -c "
   try:
       from bot.a6_sum_scanner import scan_neg_risk_events
       result = scan_neg_risk_events()
       print(f'A-6 scan: {result}')
   except Exception as e:
       print(f'A-6 scan unavailable: {e}')
   "
   ```

7. Check if `src/reporting.py` exists and can generate the report:
   ```bash
   python3 src/reporting.py 2>&1 || echo "reporting.py failed — generate manually"
   ```

8. Update `FAST_TRADE_EDGE_ANALYSIS.md` with:
   ```markdown
   # Fast Trade Edge Analysis
   **Last Updated:** <ISO timestamp>
   **System Status:** <running|paused>
   **Data Window:** <fresh pull timestamp>
   **Instance Version:** 2.8.0

   ## Data Coverage
   - Active markets pulled: N
   - Markets resolving <24h: N
   - Markets resolving <48h: N
   - Markets in price window (0.10-0.90): N
   - Markets in allowed categories: N

   ## Threshold Sensitivity
   | Threshold Profile | YES | NO | Markets Theoretically Tradeable |
   |---|---|---|---|
   | Current (conservative) | 0.15 | 0.05 | N |
   | Aggressive | 0.08 | 0.03 | N |
   | Wide open | 0.05 | 0.02 | N |

   ## Current Recommendation
   <REJECT ALL | TRADE WITH AGGRESSIVE THRESHOLDS | specific recommendations>

   Reasoning: <evidence-based>

   ## VALIDATED EDGES (p < 0.01, n > 300)
   <list or "None currently validated">

   ## CANDIDATE EDGES (p < 0.05, n > 100)
   <list or "No candidates meet thresholds">

   ## Market Universe Snapshot
   | Category | Count | Avg YES Price | <24h Resolution |
   |---|---|---|---|
   | politics | N | 0.XX | N |
   | weather | N | 0.XX | N |
   | economic | N | 0.XX | N |
   | crypto | N | 0.XX | N |
   | sports | N | 0.XX | N |
   | other | N | 0.XX | N |

   ## A-6 Structural Scan
   <results or "0 executable constructions">

   ## Wallet-Flow Status
   Ready: 80 scored wallets, fast_flow_restart_ready=true
   ```

9. Write detailed results to `reports/pipeline_refresh_<timestamp>.json`:
   ```json
   {
     "timestamp": "<ISO>",
     "instance_version": "2.8.0",
     "markets_pulled": N,
     "markets_under_24h": N,
     "markets_under_48h": N,
     "markets_in_price_window": N,
     "markets_in_allowed_categories": N,
     "threshold_sensitivity": {
       "current": {"yes": 0.15, "no": 0.05, "tradeable": N},
       "aggressive": {"yes": 0.08, "no": 0.03, "tradeable": N},
       "wide_open": {"yes": 0.05, "no": 0.02, "tradeable": N}
     },
     "category_breakdown": {"politics": N, "weather": N, "economic": N, "crypto": N, "sports": N, "other": N},
     "a6_scan": {"allowed_events": 563, "qualified": 57, "executable": N},
     "wallet_flow": {"ready": true, "scored_wallets": 80},
     "calibration_params": {"A": 0.5914, "B": -0.3977},
     "recommendation": "...",
     "new_viable_strategies": []
   }
   ```

10. Run tests to verify nothing broke:
    ```bash
    python3 -m pytest tests/ -x -q --tb=short
    ```

## VERIFICATION

```bash
python3 -m pytest tests/ -x -q
head -5 FAST_TRADE_EDGE_ANALYSIS.md  # Timestamp is current
ls data/pulls/  # Fresh directory exists
ls reports/pipeline_refresh_*.json  # Handoff artifact exists
```

## HANDOFF

```
INSTANCE #6 HANDOFF
---
Files changed: [list]
Commands run: [list]
Key findings: [1-3 sentences — especially: how many markets become tradeable at aggressive thresholds?]
Numbers that moved: [before→after]
Unverified: [anything next cycle should check]
Next instance can edit these files: [yes/no per file]
```
