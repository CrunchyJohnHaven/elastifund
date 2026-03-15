# Cross-Asset Cascade Lane — Operator Reference

Status: canonical runbook
Last updated: 2026-03-11
Category: canonical runbook
Canonical: yes
Runtime stage: shadow_replay (Stage 0)

## Purpose

The cross-asset cascade lane trades Polymarket follower assets (ETH, SOL, XRP, DOGE) when
BTC makes a statistically significant first-90-seconds move. The lane is designed to run
completely shadow until it passes a staged rollout ladder controlled by Instance 6.

BTC5 is the baseline lane and MUST remain running and profitable for any cross-asset
promotion to proceed. Cross-asset work must not mutate BTC5 live execution behavior.

---

## Rollout Ladder

| Stage | Name                        | Notional cap | Live? |
|-------|-----------------------------|-------------|-------|
| 0     | shadow_replay               | $0          | No    |
| 1     | shadow_live_intents         | $0          | No    |
| 2     | single_follower_micro_live  | $5/trade    | Yes   |
| 3     | two_asset_basket            | $5/trade    | Yes   |
| 4     | four_asset_basket           | $5/trade    | Yes   |

Promotion criteria per stage are enforced in `scripts/instance6_rollout_controller.py`.

---

## Canonical Artifact Paths

All artifacts use `reports/<domain>/latest.json`. Timestamped snapshots are written alongside.

| Artifact                          | Path                                               | Freshness |
|-----------------------------------|----------------------------------------------------|-----------|
| Data-plane health                 | `reports/data_plane_health/latest.json`            | 60s       |
| Market registry                   | `reports/market_registry/latest.json`              | 60s       |
| Cross-asset cascade signal        | `reports/cross_asset_cascade/latest.json`          | 120s      |
| Cross-asset Monte Carlo           | `reports/cross_asset_mc/latest.json`               | 360s      |
| Wallet reconciliation             | `reports/wallet_reconciliation/latest.json`        | 900s      |
| Instance 1 data-plane dispatch    | `reports/instance1_data_plane/latest.json`         | 3600s     |
| Instance 2 BTC5 baseline          | `reports/instance2_btc5_baseline/latest.json`      | 3600s     |
| Instance 3 vendor/backfill        | `reports/instance3_vendor_backfill/latest.json`    | 3600s     |
| Instance 4 market registry        | `reports/instance4_registry/latest.json`           | 3600s     |
| Instance 5 cascade + MC           | `reports/instance5_cascade_mc/latest.json`         | 3600s     |
| Instance 6 rollout control        | `reports/instance6_rollout_control/latest.json`    | —         |
| Instance 6 rollout control mirror | `reports/rollout_control/latest.json`              | —         |

**Compatibility mirrors** (one cycle only, then deprecated):
- `reports/parallel/instance1_multi_asset_data_plane_latest.json` → superseded by `instance1_data_plane`
- `reports/parallel/instance03_cross_asset_vendor_dispatch.json` → superseded by `instance3_vendor_backfill`
- `reports/instance4_artifact.json` → superseded by `instance4_registry`

Instance 2 is also the canonical BTC5 baseline truth source for the control plane:

- `baseline_contract.v1` separates `baseline_live_ok`, `stage_upgrade_blocked`, and `treasury_expansion_blocked`
- `baseline_guard.v1` publishes allowed actions for `observe_only`, `research_auto`, `safe_build_auto`, `gated_build_auto`, and `deploy_recommend`
- stale promotion artifacts must produce hold/repair retry timing and may not silently disable the live BTC5 baseline

---

## Shared Path Helper

`infra/cross_asset_artifact_paths.py` provides `CrossAssetArtifactPaths.for_repo(repo_root)`.
Use `resolve_first_existing(candidates)` when consuming a candidate tuple (canonical, compat).
All consumers should import from this module instead of hard-coding paths.

---

## Blocker Classes

The rollout controller emits exactly one of these prefix types per block entry:

| Prefix                      | Meaning                                                   |
|-----------------------------|-----------------------------------------------------------|
| `missing_artifact:<name>`   | Artifact file does not exist at canonical path            |
| `stale_artifact:<name>`     | Artifact exists but older than freshness threshold        |
| `stale_finance_inputs:<name>` | Finance or remote-cycle artifact stale; hold + retry 5m |
| `no_follower_universe`      | Registry has zero live follower rows with candle history  |
| `negative_signal_quality:<asset>` | win_rate < 55% or post_cost_ev ≤ 0 for asset       |
| `wallet_reconciliation_not_ready:<detail>` | wallet truth precision below floor or phantom opens remain |

---

## Services

| Service file                          | Description                         |
|---------------------------------------|-------------------------------------|
| `deploy/btc-5min-maker.service`       | BTC5 baseline (must stay running)   |
| Instance 1 data-plane runner          | `scripts/run_instance1_data_plane.py` |
| Instance 4 market registry runner    | `scripts/run_pm_fast_market_registry.py` |
| Instance 5 cascade + MC runner       | `scripts/run_cross_asset_history_dispatch.py` |
| Instance 6 rollout controller        | `scripts/instance6_rollout_controller.py` |
| Finance dispatch                     | `scripts/run_instance6_rollout_finance_dispatch.py` |

---

## Stage Gates

### Stage 0 → Stage 1 (shadow_live_intents)
- `cross_asset_cascade/latest.json` exists and fresh
- `cross_asset_mc/latest.json` exists and fresh
- `market_registry/latest.json` exists and fresh

### Stage 1 → Stage 2 (single_follower_micro_live)
- ≥2 consecutive positive-intent cycles (shadow_intended_notional_usd > 0)
- BTC5 baseline healthy and running
  Use `reports/instance2_btc5_baseline/latest.json` first. Treat `baseline_contract.baseline_status=baseline_live_ok` as the controlling baseline signal.
- `wallet_reconciliation/latest.json` exists and is fresh
- snapshot_precision ≥ 99%
- classification_precision ≥ 95%
- zero phantom local open trades
- Finance gate passes
- At least one follower has win_rate ≥ 55% and post_cost_ev > 0

### Stage 2 → Stage 3 (two_asset_basket)
- Active follower: ≥50 cumulative candle-sets
- win_rate ≥ 55%, post_cost_ev > 0, not auto-killed
- Finance gate passes
- A second follower also passes thresholds

### Stage 3 → Stage 4 (four_asset_basket)
- Both active followers pass win_rate and EV thresholds
- No correlation collapse
- All 4 followers pass thresholds
- Finance gate passes

---

## Rollback Triggers

These conditions cause automatic demotion or rollback:

| Condition                    | Action                                          |
|------------------------------|-------------------------------------------------|
| MC tail breach or drawdown stress breach | Rollback to Stage 0                |
| Correlation collapse in Stage 3+ | Demote to Stage 1 (shadow_live_intents)    |
| BTC5 baseline not running    | Demote to Stage 0 (shadow_replay)              |
| Active follower auto-killed  | Demote to Stage 1                              |
| Stale artifacts in live stage | Demote to Stage 1                             |
| Finance artifacts stale      | Hold/repair with 5-min retry ETA               |

---

## Finance Gating

| Cap                          | Default  | Env override                           |
|------------------------------|----------|----------------------------------------|
| Single-action cap            | $250     | `JJ_FINANCE_SINGLE_ACTION_CAP_USD`     |
| Monthly new commitment cap   | $1000    | `JJ_FINANCE_MONTHLY_NEW_COMMITMENT_CAP_USD` |
| Cash reserve floor           | 1 month  | —                                      |

CoinAPI subscription ($79/month) is **queued, not auto-executed**. Finance gate must be fresh
and explicitly green at runtime before the queue entry is promoted to executed.

---

## Required Outputs (Instance 6 Output Contract)

Every run of `scripts/instance6_rollout_controller.py` emits these six fields in the packet:

```json
{
  "candidate_delta_arr_bps": 100,
  "expected_improvement_velocity_delta": 0.20,
  "arr_confidence_score": 0.90,
  "block_reasons": ["stale_finance_inputs:finance_latest"],
  "finance_gate_pass": true,
  "one_next_cycle_action": "repair: refresh_finance_latest_within_5min"
}
```

---

## One-Cycle Validation Steps

After each cross-asset dispatch cycle:

1. Run `python3 scripts/instance6_rollout_controller.py --dry-run` — confirm no new blockers
2. Run `pytest tests/test_instance6_rollout_controller.py tests/test_instance6_rollout_finance_dispatch.py -q`
3. Verify `reports/instance6_rollout_control/latest.json` and `reports/rollout_control/latest.json` are in sync
4. Confirm `block_reasons` contains only classified prefixes (no bare strings)
5. If finance artifacts are stale, run `scripts/run_instance6_rollout_finance_dispatch.py` to refresh
6. If wallet truth is missing or below the precision floors, run `python3 scripts/reconcile_polymarket_wallet.py`

---

## Next Cycle Action

**Current:** Run one full shadow cycle and regenerate the unified operator packet once
Instances 4 and 5 have written live registry and cascade artifacts.
