# Instance 3 — Operator Packet
**Generated:** 2026-03-10T21:20Z
**Status:** `hold_repair_storage — shadow_staged_wednesday_queued`
**Instance:** Claude Code / Sonnet (Instance 3 — Micro-live lane activation)

---

## VERDICT: Disk repair first. Shadow only after service restarts. Wednesday 09:00 ET is the micro-live probe window.

---

## Gate Assessment

| Gate | Required | Current | Result |
|------|----------|---------|--------|
| VPS disk not full | yes | FULL (No space left on device) | **FAIL — BLOCKER** |
| Service running | yes | stopped (inactive) | FAIL |
| Instance 2 blockers ≤ `confirmation_stale` | yes | Multiple structural blockers | FAIL |
| Trailing 12 net positive | yes | -$8.55 | FAIL |
| Trailing 40 net positive | yes | -$24.09 | FAIL |
| Session window active | yes | 16:20 ET (outside 9-11) | FAIL |
| Runtime package loaded | yes | false | FAIL |
| Deployment confidence | ≥ medium | low (0.49) | FAIL |

**Conclusion:** Live activation is not permitted. Shadow activation is also blocked until disk is repaired and service restarts safely.

---

## Step 1: Free VPS Disk Space (BLOCKER — Do This Now)

```bash
# Check disk state
ssh ubuntu@52.208.155.0 'df -h / && du -sh /home/ubuntu/polymarket-trading-bot/logs/* 2>/dev/null | sort -rh | head -20'

# Vacuum journal logs (largest typical blocker)
ssh ubuntu@52.208.155.0 'sudo journalctl --vacuum-size=200M'

# Clean apt cache
ssh ubuntu@52.208.155.0 'sudo apt-get clean'

# Remove old bot logs (>7 days)
ssh ubuntu@52.208.155.0 'find /home/ubuntu/polymarket-trading-bot -name "*.log" -mtime +7 -delete 2>/dev/null; df -h /'
```

**Retry cadence:** +10 min if still blocked.

---

## Step 2: Restart Service in Shadow Mode (After Disk Is Clear)

```bash
ssh ubuntu@52.208.155.0 'sudo systemctl start btc-5min-maker && sudo systemctl status btc-5min-maker'
```

**Shadow config** (tighter guardrails — updated from previous cycle):
```
BTC5_DEPLOY_MODE=shadow_probe
BTC5_PAPER_TRADING=true
BTC5_CAPITAL_STAGE=1
BTC5_MAX_TRADE_USD=10
BTC5_DAILY_LOSS_LIMIT_USD=250
BTC5_MAX_ABS_DELTA=0.00005      ← TIGHTER (was 0.00015)
BTC5_UP_MAX_BUY_PRICE=0.48      ← TIGHTER (was 0.51)
BTC5_DOWN_MAX_BUY_PRICE=0.51
```

**Why tighter guardrails:** Instance 2 protocol — recent 5/12/20/40 windows all negative. Default to tighter always-on guardrail package until evidence recovers. Delta band compressed 3x. UP ceiling lowered.

**Expected result:** Service enters shadow mode, begins accumulating fills against open_et session policy (ET hours 9, 10, 11) with tighter guardrails.

---

## Step 3: Wednesday Micro-Live Window — March 11, 2026, 9:00–11:59 AM ET

### Gate Check — Wednesday 08:00 AM ET (1 hour before window)

```bash
cd /home/ubuntu/polymarket-trading-bot
python3 scripts/run_btc5_autoresearch_cycle.py
# Then verify:
# - trailing_12.net_positive = true
# - service_state = running
# - deployment_confidence.confidence_label >= medium
```

### GO Conditions (ALL must be true at 08:00 ET Wednesday):
1. `vps_storage_not_blocked = true`
2. `service_state = running`
3. `trailing_12.net_positive = true` (require at least one clean shadow session overnight)
4. `package_class` in `[promote, neutral]` — not suppress
5. Finance gate allows at minimum shadow execution

### NO-GO Action:
Gates don't clear → keep shadow, retry **Thursday March 12, 09:00 ET**. No forced launch with negative short windows.

---

## Live Probe Parameters (If Gates Clear Wednesday 09:00 ET)

```
Package:         tighter_guardrail_overlay (open_et session)
Session:         open_et — ET hours 9, 10, 11
Max delta:       ±0.00005  (3x tighter than previous)
UP max buy:      0.48      (lowered ceiling — DOWN bias stronger)
DOWN max buy:    0.51
Max trade USD:   $5 (probe size — do NOT scale up during first window)
Max fills:       2 in the first window
TTL:             2026-03-11T12:00 ET
```

### Rollback Triggers (any one fires → kill live, revert to shadow):
- First fill loss exceeds $5
- Two consecutive negative fills
- Three order failures in the window
- Trailing 5 turns negative after a positive entry
- Service error or crash

---

## BTC5 Package State

| Metric | Value |
|--------|-------|
| Best package | `open_et grid_d0.00015_up0.51_down0.51` |
| Shadow guardrails (adopted) | `open_et grid_d0.00005_up0.48_down0.51` |
| Package confidence | medium |
| Promoted | False |
| Trailing 5 P&L | -$4.38 |
| Trailing 12 P&L | -$8.55 |
| Trailing 40 P&L | -$24.09 |
| Trailing 120 P&L | **+$91.49** |
| All-time fills | 138 |
| All-time P&L | +$85.30 |
| Session policy | ET hours 9, 10, 11 |

The 120-fill window is solidly positive. The recent cluster is negative. Tighter guardrails protect capital while the cluster fades. Need trailing_12 to turn positive before micro-live.

---

## Guardrail Change Rationale

Previous cycle used `max_abs_delta=0.00015`. This cycle adopts `max_abs_delta=0.00005` and `up_max_buy_price=0.48`.

**Why:** Instance 2 dispatch protocol explicitly states: "Because recent 5/12/20/40 windows are negative, default to the tighter guardrail package for shadow until evidence improves." Runtime truth independently recommends the same tighter values. This is not a speculation — both the autoresearch probe and the dispatch protocol converge on tighter guardrails.

**Trade-off:** Tighter delta band means fewer fills per session. That's acceptable — quality over quantity while the cluster is negative.

---

## A-6 / B-1

**Hold. No action.** Both at zero. Kill at March 14 deadline. No compute spent.

---

## Retry Schedule

| Event | Time |
|-------|------|
| Disk repair (John) | Now — ASAP |
| Service restart (shadow) | After disk clear, +10m retry |
| Shadow fill check | +6h from restart |
| Wednesday gate check | Wed March 11, 08:00 ET |
| Wednesday micro-live probe | Wed March 11, 09:00 ET (conditional) |
| Thursday fallback | Thu March 12, 09:00 ET |
| A-6/B-1 kill deadline | March 14, 2026 |

---

## Required Outputs (Machine-Readable)

```json
{
  "candidate_delta_arr_bps": 0,
  "expected_improvement_velocity_delta": "+1 blocker per step: disk repair → restart → shadow pass → trailing_12 positive → Wednesday probe",
  "arr_confidence_score": 0.15,
  "block_reasons": [
    "vps_storage_full_service_restart_unsafe",
    "service_stopped",
    "trailing_12_live_filled_not_positive",
    "trailing_40_live_filled_not_positive",
    "btc5_forecast_not_promote_high",
    "runtime_package_load_pending",
    "confirmation_coverage_missing",
    "session_window_closed_until_wednesday_0900_et"
  ],
  "finance_gate_pass": "shadow_only",
  "one_next_cycle_action": "Free VPS disk. Restart btc-5min-maker in shadow mode with tighter guardrails (delta=0.00005, up_max=0.48, down_max=0.51). Gate-check trailing_12 at Wednesday 08:00 ET. Activate micro-live probe only if all gates clear."
}
```
