# CODEX MASTER PLAN — Elastifund March 2026

**Generated:** 2026-03-09
**Author:** JJ (Principal Agent)
**Purpose:** Single-source planning document for all Codex instances to validate the current strategy, fix the VPS deployment blocker, and complete every remaining task to reach first paper trades.

---

## SITUATION REPORT (Machine Truth)

The numbers do not lie, and they are embarrassing.

| Metric | Value | Assessment |
|--------|-------|------------|
| Cycles completed | 314 | The bot has run 314 times and found nothing to trade |
| Trades executed | 0 | Zero. Not one. |
| Capital deployed | $0 of $347.51 | 100% idle capital |
| Pipeline verdict | REJECT ALL | 75 markets scanned, all rejected |
| Service status | STOPPED | VPS service inactive since 01:28 UTC |
| Test suite | 1,395 passing | Green across all surfaces |
| Code modules | 46 bot/*.py files | Syntax-clean, zero TODO/FIXME |
| Strategy backlog | 131 tracked | 7 deployed, 6 building, 118 pipeline/rejected |

**Diagnosis:** We built a $0 trading firm with 65,000 lines of infrastructure. The code is excellent. The tests are comprehensive. The documentation is meticulous. And we have never made a single trade.

The root cause is a compound gate failure:
1. Signal thresholds too conservative (0.15/0.05) — zero markets pass
2. Category gate blocking all tradeable markets (crypto priority = 0, but all fast markets are BTC)
3. Service stopped on VPS — cannot collect data even if thresholds were fixed
4. No calibration data — cannot validate strategies without closed trades

**The fix is deployed but not running.** Commit `26e344c` added `paper_aggressive.json` which lowers thresholds to 0.08/0.03, unlocks crypto to priority 2, and keeps paper mode ON. This is sitting in GitHub. The VPS hit an import error on first attempt.

---

## CRITICAL PATH (Ordered by Dependency)

### BLOCKER 0: VPS Import Error

**Status:** BLOCKING DEPLOYMENT
**Error:** `ModuleNotFoundError: No module named 'bot.polymarket_runtime'`
**Root Cause:** John ran `python3 jj_live.py` from root, but the file doesn't exist at root — only `bot/jj_live.py` exists. The error traceback references `jj_live.py line 80`, but our current `bot/jj_live.py` has the import at line 145, confirming the VPS is running a stale root-level copy.

**Fix — Commands for John to run on VPS:**

```bash
# SSH to VPS
ssh -i ~/Downloads/LightsailDefaultKey-eu-west-1.pem ubuntu@52.208.155.0

# Confirm git pull got latest
cd /home/ubuntu/polymarket-trading-bot/
git pull origin main

# Verify bot/polymarket_runtime.py exists
ls -la bot/polymarket_runtime.py
# Should show the file (committed in 838e91e)

# Remove stale root-level jj_live.py if it exists
ls -la jj_live.py 2>/dev/null && echo "STALE COPY EXISTS — removing" && rm jj_live.py

# Set the runtime profile
grep -q 'JJ_RUNTIME_PROFILE' .env && sed -i 's/^JJ_RUNTIME_PROFILE=.*/JJ_RUNTIME_PROFILE=paper_aggressive/' .env || echo 'JJ_RUNTIME_PROFILE=paper_aggressive' >> .env

# Verify profile loads
python3 -c "
import sys; sys.path.insert(0, '.')
from config.runtime_profile import load_runtime_profile
p = load_runtime_profile('paper_aggressive')
print(f'Profile: paper_aggressive')
print(f'YES threshold: {p.signal_thresholds.yes_threshold}')
print(f'NO threshold: {p.signal_thresholds.no_threshold}')
print(f'Crypto priority: {p.market_filters.category_priorities.get(\"crypto\", \"MISSING\")}')
print(f'Paper mode: {p.mode.paper_trading}')
print(f'Order submission: {p.mode.allow_order_submission}')
print(f'Execution mode: {p.mode.execution_mode}')
"

# Expected output:
# Profile: paper_aggressive
# YES threshold: 0.08
# NO threshold: 0.03
# Crypto priority: 2
# Paper mode: True
# Order submission: False
# Execution mode: shadow

# Restart via systemd (which has correct PYTHONPATH)
sudo systemctl restart jj-live.service

# Verify running
sudo systemctl status jj-live.service --no-pager

# Watch for first signals
sudo journalctl -u jj-live.service -f --no-pager
```

**Why systemd works but direct python doesn't:** The service unit at `/etc/systemd/system/jj-live.service` sets `PYTHONPATH=/home/ubuntu/polymarket-trading-bot:/home/ubuntu/polymarket-trading-bot/bot:/home/ubuntu/polymarket-trading-bot/polymarket-bot`. This ensures both `from bot.polymarket_runtime` and `from polymarket_runtime` resolve correctly. Running `python3 jj_live.py` directly from root has no PYTHONPATH set.

**Success criteria:** `systemctl status jj-live.service` shows `active (running)` and `journalctl` shows `Profile: paper_aggressive` in the first few log lines.

---

### TASK 1: Validate paper_aggressive Profile End-to-End

**Objective:** Confirm the profile produces trade signals within 20 minutes of service restart.

**What the profile changes:**
| Setting | blocked_safe | paper_aggressive | Impact |
|---------|-------------|-----------------|--------|
| YES threshold | 0.15 | 0.08 | Pipeline shows 0→8 markets become tradeable |
| NO threshold | 0.05 | 0.03 | Proportional reduction |
| Crypto priority | 0 (blocked) | 2 (enabled) | All 8 tradeable markets are BTC crypto |
| Min category priority | 1 | 0 | Opens all categories |
| Sports priority | 0 | 1 | Fee asymmetry edge (3.5x cheaper than crypto) |
| Execution mode | blocked | shadow | Logs trades without submitting to CLOB |
| Launch gate | blocked | none | No gate — paper mode IS the safety rail |
| Order submission | false | false | PAPER ONLY — no real orders |
| Scan interval | 300s | 120s | 2× faster scan for fast markets |
| Kelly fraction | 0.125 | 0.25 | Quarter-Kelly as designed |

**Validation steps (automated, in-cycle):**
1. Service loads `paper_aggressive` profile (check logs for `"Profile: paper_aggressive"`)
2. Scan runs every 120 seconds (not 300)
3. Crypto markets are accepted (BTC 5min/15min/4h candles)
4. At least one signal fires at 0.08/0.03 thresholds within 10-20 minutes
5. Paper trades logged to `paper_trades.json` and `jj_state.json`
6. NO real orders submitted (`allow_order_submission=false`)

**If no signal in 30 minutes:** The market conditions may have shifted since the threshold sensitivity analysis. Check if any BTC candle market is in the 0.10-0.90 price window. If none are, the system is working correctly — there's nothing to trade. Wait for the next candle rotation.

---

### TASK 2: Threshold Sensitivity Validation

**Objective:** Confirm the 0.08/0.03 thresholds are the right operating point.

**Background:** FAST_TRADE_EDGE_ANALYSIS.md shows:
- At 0.15/0.05 (current conservative): 0 tradeable markets
- At 0.08/0.03 (paper_aggressive): 8 tradeable markets
- At 0.05/0.02 (wide open): 8 tradeable markets (same 8 — no incremental gain)

The jump from 0 to 8 happens at 0.08. Below that, no new markets appear until you go extremely wide. This means 0.08 is not arbitrary — it's the natural breakpoint where BTC candle markets clear the edge threshold.

**Validation Codex instance should:**

```python
# Run threshold sweep programmatically
# For each threshold pair from 0.20 down to 0.02:
#   1. Count markets passing edge filter
#   2. Record which markets pass and their estimated edges
#   3. Identify the exact threshold where each market enters/exits
#   4. Plot the step function

# Expected result: step function with a cliff at ~0.08-0.10
# If the cliff is elsewhere, update paper_aggressive.json accordingly
```

**File to create:** `reports/threshold_sensitivity_sweep.json`
**File to update:** `FAST_TRADE_EDGE_ANALYSIS.md` with sweep results

---

### TASK 3: Category Gate Audit

**Objective:** Verify that enabling crypto doesn't expose the system to degenerate markets.

**Risk:** Crypto prediction markets on Polymarket include both reasonable (BTC above $X by date Y) and degenerate (meme coin pump timing) markets. The category filter exists for a reason.

**Validation steps:**
1. Pull all markets currently categorized as "crypto" from Polymarket API
2. For each: classify as (a) BTC price candle, (b) ETH price candle, (c) altcoin/meme, (d) other
3. Verify that the 8 markets identified by the threshold sweep are all BTC candles
4. If any altcoin/meme markets pass: add a sub-category filter or tighten back

**Acceptance criteria:** The 8 tradeable markets are all BTC price candles with clear resolution mechanics (e.g., "BTC above $65K at 4PM UTC"). No meme coins. No vague resolution criteria.

**File to create:** `reports/crypto_category_audit.json`

---

### TASK 4: Paper Trade Collection Pipeline

**Objective:** Accumulate 100 paper trades for calibration data within 7-14 days.

**What "calibration data" means:**
Each paper trade records:
- Market ID and question text
- Entry price (CLOB mid at signal time)
- Signal direction (YES/NO) and estimated edge
- Kelly-sized position amount
- Signal source(s) that triggered
- Resolution outcome (when market resolves)
- P&L (paper)

This data feeds directly into:
1. **Platt calibration curve update** — Is the LLM still overconfident? By how much?
2. **Kill rule evaluation** — Which signals are profitable? Which should be killed?
3. **Category filter tuning** — Are crypto trades profitable? Sports?
4. **Threshold optimization** — Should we tighten or loosen 0.08/0.03?

**Expected throughput:**
- 8 tradeable markets × signals every 120s scan
- Assume ~20% signal rate per scan (not every market triggers every cycle)
- ~8 × 0.20 = 1.6 signals per scan
- 720 scans per day (120s interval × 24h)
- ~1,152 potential signals per day, but most are repeat signals on the same market
- Realistic: 5-15 unique paper trades per day (new signal on new market or new candle)
- 100 trades in 7-20 days depending on market churn

**Monitoring (daily check):**
```bash
# On VPS: count paper trades
python3 -c "
import json
with open('jj_state.json') as f:
    state = json.load(f)
print(f'Total paper trades: {state.get(\"total_trades\", 0)}')
print(f'Cycles completed: {state.get(\"cycles_completed\", 0)}')
print(f'Open positions: {len(state.get(\"open_positions\", []))}')
"
```

---

### TASK 5: A-6 Structural Alpha — Unblock or Kill

**Status:** BLOCKED — 0 executable opportunities below 0.95 cost gate in 563 allowed neg-risk events.

**The honest assessment:** A-6 (guaranteed-dollar arbitrage via sum violations in neg-risk event groups) is the most theoretically elegant strategy in the backlog. It's also the one with zero empirical evidence of profitability. The scanner works. The executor works. The kill rules work. But the market doesn't provide opportunities.

**Decision framework for Codex:**
1. Run A-6 scanner in shadow mode with paper_aggressive profile
2. Log every candidate found, even those above 0.95 gate
3. After 7 days: if zero candidates below 0.97 (relaxed gate), kill A-6 and reallocate engineering effort
4. If candidates appear: validate maker fill rates on candidate legs

**Kill criteria:**
- Zero candidates below 0.97 after 7 days of continuous scanning → KILL
- Candidates found but maker fill rate < 30% → KILL (can't execute)
- Candidates found, fills achieved, but net P&L negative after fees → KILL

**Files:**
- `reports/arb_empirical_snapshot.json` — A-6 scan results (update continuously)
- `research/edge_backlog_ranked.md` — Update A-6 status after 7-day window

---

### TASK 6: B-1 Dependency Engine — Unblock or Kill

**Status:** BLOCKED — 0 deterministic template pairs in first 1,000 allowed markets.

**Same honest assessment as A-6:** Theoretically sound (if A implies B and B is cheaper than A's implication, buy B). Practically, the market doesn't present these opportunities in the allowed market set.

**Decision framework:**
1. Run B-1 template scanner in shadow mode
2. Log every candidate pair, even marginal ones
3. After 7 days: if zero pairs with implication strength > 0.5, kill B-1

**Kill criteria:**
- Zero viable pairs after 7 days → KILL
- Pairs found but classification accuracy < 80% on manual review → KILL
- Pairs found, trades taken, but edge < fees → KILL

---

### TASK 7: Wallet Flow Signal Validation

**Status:** READY — 80 scored wallets, fast_flow_restart_ready=true, but edge scan says stay_paused.

**Why it's paused:** The wallet flow detector has wallets scored but no markets to apply them to (threshold gate was blocking everything). With paper_aggressive unlocking 8 markets, wallet flow should now generate signals.

**Validation:**
1. With paper_aggressive active, wallet flow should fire on BTC candle markets
2. Track wallet-flow-sourced signals separately from LLM-sourced signals
3. After 50 signals: compare hit rate of wallet-flow vs LLM-only
4. If wallet flow adds >2% accuracy: keep. If not: demote to tiebreaker only.

---

### TASK 8: Deploy Script Hardening

**Objective:** Make `scripts/deploy.sh` robust enough that the import error John hit cannot recur.

**Current bug:** `deploy.sh` line 89-91 copies `bot/jj_live.py` to the repo root on VPS:
```bash
scp $SSH_OPTS -q "$PROJECT_DIR/bot/jj_live.py" "$VPS:$BOT_DIR/jj_live.py"
```
This creates a stale root-level copy that gets out of sync with `bot/jj_live.py`. The systemd service correctly runs `python3 bot/jj_live.py`, but if anyone runs `python3 jj_live.py` directly, they get the stale copy.

**Fix:**
1. Remove the root-copy step from deploy.sh
2. Add a post-deploy check that removes any root-level `jj_live.py` on VPS
3. Add PYTHONPATH export to deploy.sh verification step
4. Add import verification: `python3 -c "from bot.polymarket_runtime import ClaudeAnalyzer; print('OK')"`

**File to modify:** `scripts/deploy.sh`

---

### TASK 9: Monitoring and Alerting

**Objective:** Know immediately when something breaks or when the first trade fires.

**Current state:** Telegram alerts exist but require the service to be running. No external monitoring.

**Required:**
1. Telegram alert on service restart (already implemented)
2. Telegram alert on first paper trade (already implemented)
3. Telegram alert on kill rule trigger (already implemented)
4. **NEW:** Health check — if service hasn't completed a cycle in 10 minutes, alert
5. **NEW:** Daily summary — paper trade count, signal count, error count

**Implementation:** Add to `bot/jj_live.py` or create `bot/health_monitor.py`:
```python
# Heartbeat check
HEARTBEAT_FILE = "data/heartbeat.json"
# Write timestamp after each cycle
# External cron checks if timestamp > 10 min old

# Daily summary (at 00:00 UTC)
# Count today's signals, trades, errors from jj_state.json
# Send Telegram summary
```

---

### TASK 10: Documentation Freeze

**Objective:** Stop generating documentation until we have trades to document.

**The uncomfortable truth:** We have 95 dispatch files, 13 governance documents, 2 vision documents, a command node, project instructions, a flywheel strategy doc, and a repo map. We also have 0 trades.

**Policy until 100 paper trades are collected:**
- NO new dispatch files
- NO updates to governance docs (00-12)
- NO updates to vision documents
- COMMAND_NODE.md updates ONLY for machine truth changes (trade count, service status)
- FAST_TRADE_EDGE_ANALYSIS.md updates ONLY from pipeline runs
- edge_backlog_ranked.md updates ONLY for strategy promotions/kills
- All engineering effort goes to Tasks 1-9

**Exception:** If a Codex instance discovers something that changes the trading strategy (new edge, new failure mode), that gets documented in the experiment diary (06_EXPERIMENT_DIARY.md) and nowhere else until post-trade review.

---

## CODEX INSTANCE ASSIGNMENTS

### Instance 1: VPS Deploy & Validate (CRITICAL PATH)
**Priority:** P0 — Nothing else matters until the bot is running
**Tasks:** Blocker 0, Task 1, Task 8
**Deliverables:**
- Fix deploy.sh to remove stale root copy
- Verify paper_aggressive profile loads on VPS
- Confirm service running and scanning
- First paper trade signal logged

**Machine truth to inject:**
```
Current state: 314 cycles, 0 trades, service STOPPED.
Commit 26e344c has paper_aggressive.json (0.08/0.03, crypto=2).
VPS hit ModuleNotFoundError because stale root jj_live.py exists.
The fix: delete root jj_live.py, use systemctl restart (has PYTHONPATH set).
deploy.sh line 89-91 creates the stale copy — remove that step.
```

### Instance 2: Threshold & Category Validation
**Priority:** P1 — Validates the paper_aggressive operating point
**Tasks:** Task 2, Task 3
**Deliverables:**
- `reports/threshold_sensitivity_sweep.json`
- `reports/crypto_category_audit.json`
- Updated FAST_TRADE_EDGE_ANALYSIS.md with sweep
- Confirm/deny that 0.08 is the right threshold

**Machine truth to inject:**
```
Threshold sensitivity shows 0→8 jump at 0.08. All 8 are BTC crypto.
Need to validate: (a) 0.08 is the natural breakpoint, (b) crypto markets are legit BTC candles.
If any meme coin markets pass the filter, tighten category sub-filter.
```

### Instance 3: Signal Source Audit
**Priority:** P1 — Validates which signals produce paper trades
**Tasks:** Task 7 (wallet flow), signal source tracking
**Deliverables:**
- Signal attribution tracking in paper trade logs
- Wallet flow vs LLM accuracy comparison after 50 signals
- Recommendation: keep/demote/kill each signal source

**Machine truth to inject:**
```
6 signal sources: LLM, wallet flow, LMSR, cross-plat arb, VPIN/OFI, lead-lag.
Wallet flow: 80 scored wallets, ready but paused (no markets until now).
With paper_aggressive: crypto markets unlocked, wallet flow should activate.
Track each signal source separately for kill-rule evaluation.
```

### Instance 4: Structural Alpha Decision (A-6 + B-1)
**Priority:** P2 — These are either golden or dead weight
**Tasks:** Task 5, Task 6
**Deliverables:**
- 7-day shadow scan results for A-6 and B-1
- Kill/continue decision for each with data
- Updated edge_backlog_ranked.md

**Machine truth to inject:**
```
A-6: 563 allowed events, 57 live-surface, 0 executable below 0.95 gate. Code works; market doesn't cooperate.
B-1: 0 deterministic pairs in 1,000 markets. Same diagnosis.
Both run in shadow mode under paper_aggressive. 7-day observation window.
Kill criteria are defined. No sentiment — data decides.
```

### Instance 5: Monitoring & Health Checks
**Priority:** P2 — Prevents silent failures
**Tasks:** Task 9
**Deliverables:**
- Heartbeat monitoring (cycle completion check)
- Daily summary Telegram message
- Health check cron job
- Service recovery automation

**Machine truth to inject:**
```
Telegram alerts exist for trades and kill rules but not for service health.
Bot ran 314 cycles with zero output — we didn't notice for hours.
Need: heartbeat check (10min timeout), daily summary, auto-restart on crash.
```

### Instance 6: Test Suite Maintenance
**Priority:** P3 — Keep the green baseline
**Tasks:** Verify all 1,395 tests still pass after paper_aggressive changes, add tests for new profile
**Deliverables:**
- `make test` passes (956+22 root)
- `make test-polymarket` passes (374)
- `make test-nontrading` passes (39)
- New test: `test_paper_aggressive_profile.py` — validates profile loading, threshold values, category gates

**Machine truth to inject:**
```
Current baseline: 1,395 tests green (956+22+374+39+4 extras).
paper_aggressive.json committed in 26e344c.
test_runtime_profile.py exists — extend it for paper_aggressive specific checks.
No test should mock the profile — load the actual JSON and validate fields.
```

---

## ESCALATION TO LIVE TRADING

This section is FOR REFERENCE ONLY. No Codex instance should execute any of this without John's explicit approval.

### Phase 1: Paper (Current — paper_aggressive)
- Duration: 7-14 days
- Goal: 100 paper trades, calibration data
- Risk: Zero (no real money)
- Exit criteria: 100 trades logged, calibration curve updated, kill rules evaluated

### Phase 2: Shadow Live
- Create `live_aggressive.json` — copy paper_aggressive, set `allow_order_submission: true`, keep `execution_mode: "shadow"`
- Bot submits real orders but in shadow mode (orders go to CLOB but are immediately cancelled)
- Goal: Validate order mechanics, fill rates, fee calculations
- Duration: 3-5 days
- Risk: Negligible (orders cancelled immediately)
- Exit criteria: 50 shadow fills, fill rate > 30%, fee calculations match expectations

### Phase 3: Live Production
- Create `live_production.json` — set `paper_trading: false`, `execution_mode: "shadow"` (keep shadow for logging)
- Bot places and holds real orders with real money
- Conservative limits: $5/position, 5 max open, $5 daily loss
- Duration: 30 days minimum
- Risk: $5/day max ($150 max over 30 days, 43% of capital)
- Exit criteria: Positive expectancy over 30 trades, Sharpe > 0.5 annualized

### Phase 4: Scale
- Increase position sizes based on Kelly and bankroll growth
- Add Kalshi ($100 capital)
- Expand categories based on calibration data
- Target: Self-sustaining fund that grows capital autonomously

**John approves each phase transition. This is a spending-real-money escalation.**

---

## RISK CONTROLS (Unchanged, Non-Negotiable)

These apply across ALL phases and ALL profiles:

| Control | Value | Rationale |
|---------|-------|-----------|
| Max position | $5 | <2% of capital per trade |
| Daily loss cap | $5 | Survive 50 consecutive losing days |
| Max open positions | 5 | $25 max exposure (7% of capital) |
| Kelly fraction | 0.25 | Quarter-Kelly (conservative) |
| Order type | Post-only maker | 0% fees + rebates vs 1.5-3.15% taker |
| Max resolution | 48h | Fast markets only (reduce lockup risk) |
| Kill rules | ALL ACTIVE | Semantic decay, toxicity, cost stress, calibration |
| Anti-anchoring | Market price hidden from LLM | Prevents price anchoring bias |
| Platt calibration | Static curve (90%→71%, 80%→60%) | Reduces overconfidence |

---

## WHAT SUCCESS LOOKS LIKE

### 7 Days From Now
- Service running continuously on Dublin VPS
- paper_aggressive profile active
- 30-50 paper trades logged
- First calibration data available
- At least one signal source showing positive expectancy

### 14 Days From Now
- 100 paper trades logged
- Calibration curve updated with real data
- Kill decisions made on A-6 and B-1
- Wallet flow signal value quantified
- Ready for Phase 2 (shadow live) decision

### 30 Days From Now
- Phase 2 complete (shadow fills validated)
- Phase 3 started (live production with real capital)
- First real P&L recorded
- Experiment diary updated with actual results, not projections

---

## FINAL NOTE

Every line of code in this repo was written to make trades. Not to write documentation about making trades. Not to plan to plan to make trades. The plan is now simple:

1. Fix the VPS import error (10 minutes of John's time)
2. Restart the service with paper_aggressive profile
3. Wait for paper trades to accumulate
4. Let the data decide what works

Stop building infrastructure. Start collecting evidence.
