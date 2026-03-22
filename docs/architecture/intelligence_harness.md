# End-to-End Intelligence Harness

**Purpose:** This document defines the acceptance gate for ALL self-improvement in Elastifund. No mutation — parameter tweak, new module, strategy addition, config change — touches live capital without passing this harness. The existing `scripts/intelligence_harness.py` provides the runtime scaffolding (replay scenarios, `IntelligenceMetrics`, `accepts_mutation`). This document specifies the exact replay corpus, metric thresholds, and pass/fail/crash rules that the harness enforces.

**Status:** Canonical specification. Updated 2026-03-22.

---

## 1. Replay Corpus

Every mutation must be replayed against these six historical incidents. The corpus covers the full failure taxonomy observed in production: winning conditions, concentration failure, stale data, configuration error, and directional loss.

### 1.1 March 11 BTC Winning Session

**Incident:** 47 BTC 5-min fills concentrated in the 03:00-06:00 ET window. 39 DOWN wins, 8 UP wins. Net +$136.86 on the day (best single day). DOWN-only P&L: +$52.80.

**Input events:**
- `btc5_rows`: 553
- `btc5_fill_count`: 47
- `btc5_skip_reasons`: `{skip_delta_too_large: 280, skip_shadow_only: 110, skip_toxic_order_flow: 90, skip_other: 26}`
- `finance_override.lanes.btc5_live_baseline.live_capital_usd`: 50.0
- `promotion_gate_override.gates.win_rate`: `{pass: true, value: 0.62, required: 0.55}`
- `promotion_gate_override.gates.profit_factor`: `{pass: true, value: 1.18, required: 1.1}`
- Time-of-day distribution: 85% of fills in 03:00-06:00 ET

**Expected decisions:**
- `cycle_decision`: `continue_live_trading_maintain_stage`
- `btc5_thesis_state`: `live_stage_1`
- System must NOT suppress the 03:00-06:00 ET window
- System must NOT switch to UP-only or random-direction mode
- Kelly sizing must produce position sizes between $3 and $10 given $247 bankroll and 0.25 Kelly fraction

**Acceptable outcomes:**
- Equal or better net P&L on the replay (tolerance: -5% from $136.86, so floor is $130.02)
- Fill count >= 40 (allowing minor filter changes to drop a few marginal trades)
- DOWN win rate >= 75% of fills (structural DOWN bias preserved)

**Failure condition:** Net P&L below $130.02, fill count below 35, or DOWN share of fills below 60%.

---

### 1.2 March 15 BTC Concentration Failure

**Incident:** 302 rows in local BTC5 DB, ALL skipped. Zero live fills. 54% `skip_delta_too_large`, 19% `skip_shadow_only`, 14% `skip_toxic_order_flow`. System was running but producing nothing. Promotion gate failed (3 of 6 criteria: WR 51.4%, PF 1.01, DD $236.68).

**Input events:**
- `btc5_rows`: 302
- `btc5_fill_count`: 0
- `btc5_skip_reasons`: `{skip_delta_too_large: 164, skip_shadow_only: 56, skip_toxic_order_flow: 42, skip_midpoint_kill_zone: 21, skip_price_outside_guardrails: 9, skip_bad_book: 3, skip_other: 7}`
- `finance_override.capital_expansion_only_hold`: true
- `promotion_gate_override.gates.win_rate`: `{pass: false, value: 0.514, required: 0.55}`
- `promotion_gate_override.gates.profit_factor`: `{pass: false, value: 1.01, required: 1.1}`
- `promotion_gate_override.gates.max_dd`: `{pass: false, value: 236.68}`

**Expected decisions:**
- `cycle_decision`: `continue_live_trading_with_warnings`
- `btc5_promotion_status`: `live_stage_1` (hold, do not scale)
- `capital_expansion_allowed`: false
- System must emit a warning about zero-fill condition
- System must NOT auto-promote to higher position sizing

**Acceptable outcomes:**
- Promotion gate remains FAIL (system does not relax criteria to force a pass)
- System flags the zero-fill anomaly explicitly
- No capital expansion triggered

**Failure condition:** Promotion gate flips to PASS, or capital expansion is allowed, or zero-fill condition goes undetected.

---

### 1.3 Stale/Fallback Discovery

**Incident:** `FAST_TRADE_EDGE_ANALYSIS.md` was 73+ hours stale (last run 01:34 UTC March 9, checked March 12). Pipeline said REJECT ALL. Execution layer was decoupled and continued trading regardless. System had no mechanism to flag or suppress stale-data-driven decisions.

**Input events:**
- `btc5_rows`: 0
- `btc5_fill_count`: 0
- `stale_fallback_used`: true
- `weather_candidate_count`: 0
- `weather_arr_confidence`: 0.30
- All evidence sources stale (simulated by empty btc5 data and zero candidates)

**Expected decisions:**
- `cycle_decision`: `continue_live_trading_with_warnings`
- `expected_stale_fallback`: true
- System must flag staleness explicitly in cycle output
- System must NOT trust stale pipeline verdicts for position sizing
- System must reduce confidence on any signals derived from stale data by at least 50%

**Acceptable outcomes:**
- Stale fallback flag set to true in output
- Any trade decisions made with stale data are marked as degraded-confidence
- No new positions opened based solely on stale evidence

**Failure condition:** System uses stale data at full confidence, or stale_fallback_used is false when data is actually stale.

---

### 1.4 Wallet/Runtime Contradiction (Wrong Address)

**Incident:** `.env` had `POLY_SAFE_ADDRESS` set to EOA signer (`0x28C5AedA...`) instead of proxy wallet (`0xb2fef31c...`). Every reconciliation queried the wrong address. Local ledger showed $0 while wallet held $390.90. Drift went undetected for days.

**Input events:**
- Simulated reconciliation with wrong address returns: `{total_value: 0.0, open_positions: 0, closed_positions: 0}`
- Actual wallet state (ground truth): `{total_value: 390.90, open_positions: 5, closed_positions: 50}`
- Discrepancy: 100% of value missing

**Expected decisions:**
- System must detect the contradiction: zero reported value but known prior deposits ($247.51)
- System must flag a reconciliation anomaly when reported balance drops below 50% of last known balance without corresponding trade losses
- System must NOT use the zero-balance reading for Kelly sizing (would produce $0 positions)
- System must halt or degrade to shadow-only if reconciliation fails sanity check

**Acceptable outcomes:**
- Anomaly flag raised within the same cycle that detects the contradiction
- Trading continues in degraded mode (reduced sizing or shadow-only) until reconciliation resolves
- Alert generated for human review

**Failure condition:** System accepts zero-balance as truth and either (a) stops trading when it should continue or (b) continues at full size with nonsense bankroll data.

---

### 1.5 DOWN-Only Mode Losses (March 22)

**Incident:** System bought DOWN at 48-55 cents on two BTC 5-min markets. Both lost. This tests whether the system correctly handles losses in its strongest mode (DOWN bias was net +$52.80 historically) without overcorrecting.

**Input events:**
- Two BTC 5-min markets:
  - Market A: bought DOWN at $0.52, resolved NO (loss of $0.52 per share)
  - Market B: bought DOWN at $0.48, resolved NO (loss of $0.48 per share)
- Position size: $5 each
- Prior DOWN track record: 107W/99L, +$52.80 net
- Current wallet: ~$390

**Expected decisions:**
- System must NOT abandon DOWN bias after two losses (sample too small to override 206 prior observations)
- System must NOT double position size to "make up" losses
- System must update the running DOWN win rate (107W+0 / 99L+2 = 51.4% from 51.9%) but not trigger a mode change
- Kelly fraction recalculation must reflect the slightly lower edge but remain positive

**Acceptable outcomes:**
- DOWN bias maintained
- Position sizing stays at $5 (no revenge trading)
- Running metrics updated correctly
- No mode change unless cumulative DOWN win rate drops below 50.5% (which two losses would not cause)

**Failure condition:** System switches to UP-only, increases position size, or abandons the DOWN thesis based on two data points.

---

### 1.6 New Module Integration (Smoke Test)

**Incident:** Synthetic scenario for testing module additions. A new module is proposed (e.g., a new signal source). The harness must verify that adding it does not break existing pipeline phases 1-7 or degrade existing replay outcomes.

**Input events:**
- Standard March 11 winning session inputs (scenario 1.1)
- `proposed_mutations`: one mutation adding a hypothetical signal source with feature flag `enable_new_signal: true`
- Mutation claims to add 0.02 edge improvement

**Expected decisions:**
- All existing replay scenarios (1.1 through 1.5) still pass their acceptance criteria
- New module does not increase pipeline latency by more than 50ms per scan
- New module does not alter decisions on existing scenarios unless the alteration produces equal or better outcomes
- If the new module cannot be imported, the pipeline degrades gracefully (feature flag auto-disabled, warning logged)

**Acceptable outcomes:**
- All five prior scenarios pass unchanged
- Pipeline latency stays under 200ms per scan
- Graceful degradation confirmed if module import fails

**Failure condition:** Any prior scenario fails, pipeline latency exceeds 200ms, or import failure causes a crash instead of graceful degradation.

---

## 2. Required Metrics and Thresholds

Each metric has a concrete threshold. These are measured after running the full replay corpus plus any available live data. The existing `IntelligenceMetrics` dataclass in `scripts/intelligence_harness.py` tracks these; the thresholds below are the acceptance criteria.

| Metric | Definition | Target | Hard Fail |
|--------|-----------|--------|-----------|
| `validated_edge_discovery_velocity` | New validated edges per week (edges that pass promotion gate with WR > 55%, PF > 1.1, and 50+ closed trades) | >= 1 per week | < 0.5 per week for 2 consecutive weeks |
| `false_promotion_rate` | Strategies promoted to live that later failed kill rules or lost money in first 50 trades, divided by total promotions | < 20% | > 35% |
| `stale_fallback_rate` | Decisions made using data older than 6 hours as a fraction of total decisions in the measurement window | < 5% | > 15% |
| `concentration_incident_count` | Events where a single asset class or direction exceeds 60% of total open position value in a rolling 24h window | 0 per month | > 2 per month |
| `attribution_coverage` | Percentage of realized P&L (both wins and losses) that can be traced to a specific named edge or strategy | > 90% | < 70% |
| `execution_quality_score` | `fill_rate * (avg_fill_price / expected_price)` where fill_rate = fills / (fills + skips) and expected_price is mid-market at signal time | > 0.70 | < 0.40 |
| `unresolved_capital_trapped` | Dollar value of positions held past their expected resolution date as a fraction of total wallet value | < 10% | > 25% |

### Metric Measurement Rules

- **Measurement window:** Rolling 7 days for live metrics; full corpus for replay metrics.
- **Baseline:** The metric values computed from the current production system (before mutation) serve as the baseline. Stored in `reports/intelligence_baseline.json`.
- **Staleness:** If live data is unavailable, replay-only metrics are used. The `stale_fallback_rate` metric itself must be computed from live data when available; replay-only computation is noted as degraded.
- **Bootstrap:** On first run (no baseline exists), the harness runs all six replay scenarios, computes metrics, and writes that as the initial baseline. No mutation can be accepted until the baseline exists.

---

## 3. Pass/Fail Rules

### 3.1 PASS (Mutation Accepted)

A mutation PASSES if and only if ALL of the following hold:

1. **Replay parity:** All six replay scenarios produce outcomes that meet or exceed their acceptable-outcome criteria (defined in Section 1).
2. **No metric degradation beyond tolerance:** No metric in Section 2 degrades by more than 10% relative to the baseline. Specifically:
   - `validated_edge_discovery_velocity`: `after >= baseline * 0.90`
   - `false_promotion_rate`: `after <= baseline + 0.02` (absolute, not relative)
   - `stale_fallback_rate`: `after <= baseline + 0.005`
   - `concentration_incident_count`: `after <= baseline + 0` (zero tolerance for new incidents)
   - `attribution_coverage`: `after >= baseline * 0.90`
   - `execution_quality_score`: `after >= baseline * 0.90`
   - `unresolved_capital_trapped`: `after <= baseline + 0.02`
3. **No new concentration incidents:** The mutation does not introduce any scenario where single-direction or single-asset exposure exceeds 60% of position value.
4. **Pipeline integrity:** `EnhancedPipeline.scan()` completes in < 200ms for all replay inputs. All 7 phases execute or gracefully degrade. No unhandled exceptions.
5. **Test suite green:** `make test` passes. No regressions in the existing 1,397+ tests.

### 3.2 FAIL (Mutation Rejected, Graceful)

A mutation FAILS if ANY of the following hold:

1. **Replay regression:** Any replay scenario produces a worse outcome than its acceptance criteria. Example: March 11 replay net P&L drops below $130.02.
2. **Metric degradation beyond 20%:** Any metric degrades by more than 20% relative to baseline. This is the hard-fail boundary:
   - `validated_edge_discovery_velocity`: `after < baseline * 0.80`
   - `false_promotion_rate`: `after > baseline + 0.04`
   - `stale_fallback_rate`: `after > baseline + 0.01`
   - `attribution_coverage`: `after < baseline * 0.80`
   - `execution_quality_score`: `after < baseline * 0.80`
3. **Promotion gate bypass:** The mutation causes a promotion gate to flip from FAIL to PASS without the underlying data supporting the change (as in scenario 1.2).
4. **Stale data accepted at full confidence:** The mutation removes or weakens staleness detection (as in scenario 1.3).

**On FAIL:** Log the failure to `reports/mutation_rejections.jsonl` with timestamp, mutation description, which scenarios failed, which metrics degraded, and the delta. Revert the mutation. Do not deploy.

### 3.3 CRASH (Unexpected Failure Mode)

A mutation CRASHES if ANY of the following hold:

1. **New failure mode:** The mutation produces a behavior not covered by any of the six replay scenarios. Examples: a new skip reason not in the known taxonomy, an unhandled exception type, a state transition not in the kernel's state machine.
2. **Pipeline structural failure:** `EnhancedPipeline.scan()` throws an unhandled exception, returns None, or takes longer than 5 seconds on any replay input.
3. **Data integrity violation:** The mutation produces outputs where internal accounting is inconsistent. Examples: reported P&L does not match sum of individual trades, position count does not match open positions, Kelly sizing produces negative values.
4. **Reconciliation evasion:** The mutation removes, weakens, or bypasses the reconciliation sanity check that catches wallet/runtime contradictions (scenario 1.4).
5. **Test suite failure:** `make test` fails with errors (not just warnings).

**On CRASH:** Immediately halt the self-improvement loop. Write crash report to `reports/mutation_crashes.jsonl` with full stack trace, mutation description, and the novel failure mode. Alert John via Telegram (`src/telegram.py`). Do not revert automatically (the crash may indicate a deeper issue that requires investigation). System continues running on the pre-mutation codebase.

---

## 4. Keep/Discard/Crash Decision Matrix

```
Mutation submitted
    |
    v
Run all 6 replay scenarios with mutation applied
    |
    v
Compute post-mutation IntelligenceMetrics
    |
    v
Compare to baseline (reports/intelligence_baseline.json)
    |
    +---> All scenarios pass + metrics within 10% tolerance + no new incidents
    |         |
    |         v
    |       KEEP
    |         - Deploy mutation to live
    |         - Update baseline: reports/intelligence_baseline.json
    |         - Log acceptance: reports/mutation_acceptances.jsonl
    |         - Commit mutation to git with tag "harness-accepted-{timestamp}"
    |
    +---> Any scenario fails OR any metric degrades >20%
    |         |
    |         v
    |       DISCARD
    |         - Revert mutation (git checkout)
    |         - Log rejection: reports/mutation_rejections.jsonl
    |         - Do not deploy
    |         - Baseline unchanged
    |         - System continues on pre-mutation code
    |
    +---> Unhandled exception OR new failure mode OR data integrity violation
              |
              v
            CRASH
              - Halt self-improvement loop
              - Log crash: reports/mutation_crashes.jsonl
              - Alert John via Telegram
              - System continues on pre-mutation code
              - Manual investigation required before loop resumes
```

---

## 5. Implementation Notes

### 5.1 Integration with Existing Code

The runtime scaffolding already exists in `scripts/intelligence_harness.py`:
- `ReplayScenario` dataclass and four pre-built gauntlets (`ALL_GAUNTLETS`)
- `IntelligenceMetrics` with `is_better_than()` comparison
- `run_replay_gauntlet()` wired to `scripts/run_instance11_weather_harness_integration.py`
- `compute_intelligence_metrics()` reading from BTC5 DB
- `accepts_mutation()` gate function

What needs to be added:
1. **Scenarios 1.4 and 1.5** (wallet contradiction and DOWN-only losses) are not yet in `ALL_GAUNTLETS`. Add `gauntlet_wallet_contradiction()` and `gauntlet_down_only_losses()`.
2. **Scenario 1.6** (new module smoke test) needs a parameterized gauntlet that accepts a mutation payload and re-runs scenarios 1.1-1.5 with the mutation applied.
3. **Baseline persistence:** Write/read `reports/intelligence_baseline.json` on first run and after each KEEP.
4. **Crash detection:** Wrap `run_replay_gauntlet()` in a try/except that catches novel exceptions and classifies them as CRASH.
5. **JSONL logging:** `reports/mutation_acceptances.jsonl`, `reports/mutation_rejections.jsonl`, `reports/mutation_crashes.jsonl`.
6. **Telegram alerting on CRASH:** Import `src.telegram.send_message` and fire on crash events.

### 5.2 Running the Harness

```bash
# Full harness run (all scenarios, compute metrics, compare to baseline)
python scripts/intelligence_harness.py --run-all

# Test a specific mutation before deploying
python scripts/intelligence_harness.py --test-mutation path/to/mutation.patch

# Update baseline after a confirmed KEEP
python scripts/intelligence_harness.py --update-baseline

# View current baseline
cat reports/intelligence_baseline.json
```

### 5.3 Automation Hook

The harness should be invoked automatically by any self-improvement loop (parameter evolution, autoresearch, module addition). The call site is:

```python
from scripts.intelligence_harness import (
    ALL_GAUNTLETS, run_replay_gauntlet, compute_intelligence_metrics,
    accepts_mutation, IntelligenceMetrics,
)

# 1. Run baseline
baseline_results = [run_replay_gauntlet(g) for g in ALL_GAUNTLETS]
baseline_metrics = compute_intelligence_metrics(baseline_results)

# 2. Apply mutation, run again
# ... apply mutation ...
after_results = [run_replay_gauntlet(g) for g in ALL_GAUNTLETS]
after_metrics = compute_intelligence_metrics(after_results)

# 3. Gate
if accepts_mutation(baseline_metrics, after_metrics):
    # KEEP — deploy
else:
    # DISCARD — revert
```

### 5.4 Non-Negotiable Constraints

- The harness itself is immutable during a self-improvement cycle. A mutation cannot modify the harness, the replay corpus, or the metric thresholds. Harness changes require a separate, manually approved commit.
- The replay corpus grows monotonically. New incidents are added; old ones are never removed. Every production failure becomes a new replay scenario.
- Metric thresholds can only be tightened, never loosened, without explicit approval from John.
- The baseline is versioned. Every KEEP writes a new baseline with a timestamp. The full history is preserved in the JSONL logs.

---

## 6. Corpus Growth Protocol

When a new production incident occurs:

1. Document the incident: input events, actual decisions, what went wrong.
2. Define expected decisions and acceptable outcomes (what the system should have done).
3. Add a new `gauntlet_*()` function to `scripts/intelligence_harness.py`.
4. Append to `ALL_GAUNTLETS`.
5. Re-run the harness to confirm the current system passes or fails the new scenario. If it fails, that failure is the baseline (the system does not yet handle this case). Future mutations that fix the failure will show improvement.
6. Commit the new scenario. This commit does not require harness approval (it is a harness change, not a mutation).

The corpus is the system's institutional memory. Every mistake the system has ever made is permanently encoded as a test it must pass forever.
