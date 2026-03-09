# Execute Instance #1 — Edge Scanner & Trade Deployment

You are an autonomous Codex instance for the Elastifund trading system. Execute every step below without human intervention. Report findings, commit code, and produce the handoff artifact.

---

## STATE SNAPSHOT (Injected 2026-03-09 v2.8.0)

- Capital: $247.51 Polymarket (USDC) + $100 Kalshi (USD) = $347.51 total
- Live trades executed: 0 (305 cycles completed, zero trades placed)
- Service: `jj-live.service` `active` at `2026-03-09T01:06:09Z` — treat as drift until mode confirmed
- Fast-trade pipeline: REJECT ALL across 74 observed markets (29×15m, 38×5m, 7×4h)
- Execution mode: 100% Post-Only maker orders
- Live config: $5/position, 5 max open, $5 daily loss cap, 0.25 Kelly
- Edge thresholds: YES=0.15, NO=0.05 (env-var configurable: `JJ_YES_THRESHOLD`, `JJ_NO_THRESHOLD`)
- Platt calibration: A=0.5914, B=-0.3977
- A-6 gate: 0 executable constructions below 0.95 (563 allowed neg-risk events, 57 qualified)
- B-1 gate: 0 deterministic template pairs in first 1,000 allowed markets
- Wallet-flow: ready with 80 scored wallets, `fast_flow_restart_ready=true`
- Tests: 1,278 total verified (871+22 root, 374 polymarket, 11 non-trading)
- Deploy blocker: release manifest expects `config/runtime_profiles/blocked_safe.yaml` but file is `.json`

---

## OBJECTIVE

Find the highest-edge, shortest-duration (<24h resolution) opportunities available right now on Polymarket and Kalshi. Determine whether lowering thresholds unlocks actionable trades. Produce a concrete restart recommendation.

## YOU OWN

`bot/`, `execution/`, `strategies/`, `signals/`, `reports/`

## DO NOT TOUCH

`docs/`, `research/`, `deploy/`, website files, `CLAUDE.md`, `COMMAND_NODE.md`, `PROJECT_INSTRUCTIONS.md`

## STEPS

1. Read `PROJECT_INSTRUCTIONS.md` Section 3 for current signal architecture. Note which signals are DEPLOYED vs BUILDING vs GATED.

2. Read `CLAUDE.md` "Current State" for exact capital, position limits, daily loss cap, Kelly fraction, and execution mode. Confirm: $247.51 Poly, $100 Kalshi, $5/position, 0.25 Kelly, post-only maker.

3. Read `research/edge_backlog_ranked.md`. Identify strategies tagged ready-to-deploy or building that target <24h markets. The 7 deployed strategies are: LLM Probability, Asymmetric Thresholds, Category Routing, Fee-Aware Gating, Quarter-Kelly, Velocity Scoring, Universal Post-Only.

4. Read `research/velocity_maker_strategy.md` for velocity benchmarks (72% win rate on <24h, 6007% ARR maker-only).

5. Pull current Polymarket markets:
   ```bash
   curl -s "https://gamma-api.polymarket.com/events?closed=false&limit=100" > /tmp/gamma_markets.json
   ```
   Filter for `end_date` within 24 hours of now. Count how many survive. Rank by liquidity and spread.

6. For each surviving market, compute the edge that the LLM would need to produce at:
   - Current thresholds: YES=0.15, NO=0.05
   - Aggressive thresholds: YES=0.08, NO=0.03
   - Wide open: YES=0.05, NO=0.02
   Report: how many MORE markets become tradeable at each step?

7. Run the A-6 guaranteed-dollar scanner:
   ```python
   python3 -c "from bot.a6_sum_scanner import scan_neg_risk_events; print(scan_neg_risk_events())"
   ```
   Log any combo where cheapest construction < $0.95.

8. Check Kalshi: read `bot/cross_platform_arb.py` for matching logic. If Kalshi API credentials exist in `.env`, pull available markets and run cross-platform arb detection.

9. For every viable opportunity: compute Kelly size (quarter-Kelly, capped at $5), verify maker-only execution path, verify kill rules pass (`bot/kill_rules.py`).

10. Produce the handoff artifact at `reports/edge_scan_<timestamp>.json`:
    ```json
    {
      "timestamp": "<ISO>",
      "instance_version": "2.8.0",
      "markets_pulled": N,
      "markets_under_24h": N,
      "markets_in_price_window": N,
      "markets_in_allowed_categories": N,
      "viable_at_current_thresholds": N,
      "viable_at_aggressive_thresholds": N,
      "viable_at_wide_open": N,
      "threshold_sensitivity": {
        "current": {"yes": 0.15, "no": 0.05},
        "aggressive": {"yes": 0.08, "no": 0.03},
        "wide_open": {"yes": 0.05, "no": 0.02}
      },
      "a6_scan_result": {"allowed_events": 563, "qualified": 57, "executable": N},
      "b1_scan_result": {"template_pairs": N},
      "cross_platform_arb": {"kalshi_markets": N, "matches": N, "arb_opportunities": N},
      "wallet_flow_status": {"ready": true, "scored_wallets": 80},
      "markets": [...],
      "capital_available": 247.51,
      "recommended_action": "restart-with-aggressive-thresholds | stay-paused | restart-current"
    }
    ```

11. If you find >= 3 viable opportunities at aggressive thresholds: recommend restart with `JJ_YES_THRESHOLD=0.08 JJ_NO_THRESHOLD=0.03 JJ_MIN_CATEGORY_PRIORITY=0` in VPS `.env`.

## VERIFICATION

```bash
python3 -m pytest tests/ -x -q --tb=short
python3 -c "from bot.jj_live import TradingBot; print('import ok')"
cat reports/edge_scan_*.json | python3 -m json.tool > /dev/null && echo "JSON valid"
```

## HANDOFF

```
INSTANCE #1 HANDOFF
---
Files changed: [list]
Commands run: [list]
Key findings: [1-3 sentences]
Numbers that moved: [before→after]
Unverified: [anything next cycle should check]
Next instance can edit these files: [yes/no per file]
```
