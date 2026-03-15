# Maker Velocity Blitz Playbook

**Date:** March 9, 2026  
**Scope:** Polymarket maker-only fast BTC lane (5m/15m first)  
**Capital Objective:** deploy 95% of Polymarket bankroll within 60 minutes while preserving maker-only execution.

## A) Architecture And Control Loop

### Canonical Runtime Truth Order
1. `reports/remote_cycle_status.json`
2. `reports/remote_service_status.json`
3. `jj_state.json`

If these disagree, resolve using that precedence and block launch until a fresh pull is completed.

### Cadences
- `10s`: quote refresh loop (cancel/replace ladder, post-only only)
- `30s`: ranking/allocation loop (wallet-flow primary, LMSR tie-breaker)
- `5m`: risk/state reconciliation loop (deployment %, drift, kill checks)

### Lane Rules
- Enabled: `wallet_flow`, `lmsr`, `fast_flow_only=true`
- Disabled for hour-0 routing: A-6 and B-1 live promotion paths
- Venue: Polymarket only
- Order type: post-only maker orders only

### Deterministic Rank Function
`score = edge * fill_prob * velocity_multiplier * wallet_confidence * toxicity_penalty`

Implemented in: `bot/maker_velocity_blitz.py` via `compute_signal_score`.

### Hour-0 Capital Policy
- Reserve cash: 5%
- Deploy target: 95% of bankroll
- Initial per-market cap: 20% of bankroll
- Rebalance every 30s cycle
- Quote ladder: 3 levels
- Cancel/replace cadence: 10s, 15s, 20s
- Toxicity response: pull quotes and re-enter after cooldown

## B) LLM Agent Prompts

Use these exact prompts for role-specialized agents.

### Market Selector
```text
You are the market selector for maker-velocity execution.
Input contracts: MarketSnapshot[], WalletConsensusSignal[].
Score each market using score = edge * fill_prob * velocity_multiplier * wallet_confidence * toxicity_penalty.
Return ranked markets, top 5 only, with explicit score values and no prose.
Reject markets where resolution_hours > 24, liquidity_usd < 100, or toxicity > 0.75.
Output JSON only.
```

### Quote Planner
```text
You are the quote planner for post-only execution.
Input contracts: ranked WalletConsensusSignal, MarketSnapshot, bankroll.
Allocate 95% of bankroll with 5% reserve and 20% per-market cap.
Build 3-level laddered QuoteIntent entries per market, post_only=true, replace_after_seconds in [10,15,20].
No taker orders. Output JSON only.
```

### Risk Sentinel
```text
You are the risk sentinel.
Input contracts: InventoryState, FillEvent[], RiskEvent[].
Trigger:
- de-risk if deployment_pct > 98 and maker_fill_rate < 0.15
- pause-new-orders if toxicity event is active
- cancel-all if service drift or launch gate conflict appears
Return machine booleans and reasons only.
```

### Incident Responder
```text
You are the incident responder.
Given blocked_reasons and latest runtime artifacts, select one state: de-risk, pause-new-orders, cancel-all.
Prefer the minimum disruptive safe state.
Return JSON:
{state, required_actions[], reopen_conditions[]}
No narrative output.
```

## C) Next-Hour Runbook

1. Pull fresh runtime artifacts:
```bash
./scripts/bridge.sh --pull-only
python3 scripts/write_remote_cycle_status.py
```

2. Run machine launch gate:
```bash
python3 scripts/maker_velocity_blitz.py launch-check \
  --repo-root . \
  --output reports/maker_velocity_launch_gate.json
```

3. Emit contract schemas:
```bash
python3 scripts/maker_velocity_blitz.py emit-contracts \
  --output reports/maker_velocity_contracts.json
```

4. Build hour-0 plan from prepared signal + market snapshots:
```bash
python3 scripts/maker_velocity_blitz.py build-hour0-plan \
  --signals-json reports/hour0_wallet_signals.json \
  --markets-json reports/hour0_markets.json \
  --bankroll-usd 250.0 \
  --output reports/maker_velocity_hour0_plan.json
```

5. Validate launch readiness:
- `launch_go=true`
- no blocked reasons
- `all_quotes_valid=true`

6. Start execution loop in maker-only fast-flow mode using the generated plan.

## D) Failure Modes And Automatic Fallback States

### `de-risk`
- Trigger: low maker fill rate with high deployment, inventory skew spike
- Action: shrink per-market cap by half; keep existing maker quotes only on top 2 scores

### `pause-new-orders`
- Trigger: toxicity breach, stale pull, or wallet bootstrap degradation
- Action: stop new QuoteIntent creation; maintain or cancel existing quotes per cooldown logic

### `cancel-all`
- Trigger: service state conflict, launch gate conflict, or drift un-reconciled
- Action: cancel all resting quotes, freeze routing, require fresh pull + clean launch-check before resuming

## E) KPI Pack For First 60 Minutes

Track and publish to `reports/`:
- `deployment_pct` (target >= 90%)
- `maker_fill_rate`
- `fill_count`
- `inventory_skew_usd`
- `blocked_reasons` count
- `all_quotes_valid` boolean

Use `bot/maker_velocity_blitz.py` `deployment_kpis(...)` for deterministic KPI computation.

## Machine Contracts

Required contract names:
- `MarketSnapshot`
- `WalletConsensusSignal`
- `QuoteIntent`
- `FillEvent`
- `InventoryState`
- `RiskEvent`

Schema artifact path:
- `reports/maker_velocity_contracts.json`

Runtime validation helper:
- `validate_contract_payload(contract_name, payload)` in `bot/maker_velocity_blitz.py`

