# ChatGPT Pro Context Packet: BTC5 Architecture Focus Repair

Generated from repo inspection on 2026-03-24 UTC / 2026-03-23 America/New_York.

This file is intentionally self-contained. Assume you have zero codebase access beyond what is embedded here.

Your job is not to give generic advice. Your job is to design the fix for the BTC5/autoresearch/live-deploy architecture so the system becomes a small, coherent, self-verifying loop instead of a sprawling collection of partially-coupled components.

Be brutally critical. Focus on architecture, control flow, truth surfaces, and deletion. Do not propose a broad rewrite of the whole repo unless you can justify why a smaller repair is impossible.

## The Ask

Design the minimal but complete architectural repair for this trading system with these goals:

1. The BTC5 live loop must actually close on itself.
2. Parameter mutations must be deployed, verified, kept, or reverted automatically.
3. There must be one authoritative answer to "is the system working?"
4. Skip filters must be measured as economic decisions, not treated as sacred.
5. Dead surfaces must be quarantined so future AI sessions stop drowning in irrelevant code.

The maintainer's thesis is: the core problem is not technical sophistication, it is architectural focus.

## Executive Truth

These are the most important verified facts from the current repo snapshot.

- There are two real trading entrypoints in code:
  - `bot/btc_5min_maker.py`
  - `bot/jj_live.py`
- The `bot/` tree currently contains 171 Python files.
- The `deploy/` directory currently contains 23 `.service` files.
- The `reports/` tree currently contains 24,185 files.
- The latest local BTC5 SQLite in this repo is `data/btc_5min_maker.db`.
- That local DB currently has 1,059 total `window_trades` rows, 23 `live_filled`, and 1,017 `skip_*` rows.
- The freshest remote probe says BTC5 has 1,399 total rows, 25 live-filled rows, and `live_filled_pnl_usd = -54.1415`.
- The runtime posture is still not greenlit for aggressive live trading:
  - `agent_run_mode = "live"`
  - `allow_order_submission = false`
  - launch posture is blocked
  - effective runtime profile is `shadow_fast_flow`
- On 2026-03-14 the system widened `BTC5_MAX_ABS_DELTA` from `0.0013` to `0.0040`.
- The current local base env and current local override env both now show `BTC5_MAX_ABS_DELTA=0.0040`.
- The autoresearch loop already does some real work:
  - evaluates candidates
  - writes an override env file
  - can restart the BTC5 service on promote
  - computes a fill-feedback summary
- But that loop still does not appear to enforce a real intervention-verification contract with automatic revert.

## Critical Timeline

You need this timeline because the repo contains multiple narratives from different dates.

- 2026-03-14:
  - BTC5 delta guardrails were widened from `0.0013` to `0.0040`.
  - The maintainer's earlier diagnosis at that time was effectively:
    - local BTC5 was mostly/all skips
    - the fill loop was starved
    - widening delta was directionally correct but not verified hard enough
- 2026-03-23 / 2026-03-24:
  - The local repo snapshot no longer shows zero fills.
  - It now shows some fills, but not enough to claim the architecture is healthy.
  - The current problems are now:
    - low fill share
    - negative recent filled PnL
    - local/remote drift
    - blocked launch posture
    - conflicting control planes
    - mutation feedback that measures but does not fully govern deployment/revert

Important nuance:

The earlier "302 rows, zero fills" diagnosis is historically useful, but as of 2026-03-24 it is no longer literally current in the checked-in local DB. The deeper architectural criticism still stands.

## What The Maintainer Believes But I Did Not Fully Re-Prove Here

Treat these as high-confidence operator claims, not machine-proven facts from this packet.

- Roughly 85 `bot/` modules are dead or unreachable from either live entrypoint.
- Roughly 66,000 lines of markdown describe systems that mostly do not run.
- Only about 5 services are operationally real.
- Most of the 24,185 `reports/` files are documentation/evidence exhaust, not active control-plane inputs.

These claims are plausible and directionally consistent with the repo, but they were not exhaustively proven in this packet.

## What Is Actually Running

### BTC5 service

`deploy/btc-5min-maker.service`:

```ini
[Service]
EnvironmentFile=-/home/ubuntu/polymarket-trading-bot/config/btc5_strategy.env
EnvironmentFile=-/home/ubuntu/polymarket-trading-bot/state/btc5_autoresearch.env
EnvironmentFile=-/home/ubuntu/polymarket-trading-bot/state/btc5_capital_stage.env
EnvironmentFile=/home/ubuntu/polymarket-trading-bot/.env
ExecStart=/usr/bin/python3 bot/btc_5min_maker.py --continuous --live
```

Implication:

- Env precedence is implicit and file-order based.
- Later files win.
- The live BTC5 process loads:
  1. base strategy env
  2. autoresearch override env
  3. capital stage env
  4. `.env`

### BTC5 autoresearch service

`deploy/btc5-autoresearch.service`:

```ini
[Service]
ExecStart=/bin/bash -lc 'mkdir -p state reports/btc5_autoresearch reports/btc5_autoresearch_current_probe && export PYTHONPATH=/home/ubuntu/polymarket-trading-bot:/home/ubuntu/polymarket-trading-bot/bot:/home/ubuntu/polymarket-trading-bot/polymarket-bot && /usr/bin/python3 scripts/run_btc5_autoresearch_cycle_core.py --db-path data/btc_5min_maker.db --strategy-env config/btc5_strategy.env --override-env state/btc5_autoresearch.env --report-dir reports/btc5_autoresearch --current-probe-latest reports/btc5_autoresearch_current_probe/latest.json --semantic-dedup-index reports/btc5_autoresearch/semantic_dedup_index.json --cycles-jsonl reports/autoresearch_cycles.jsonl --fill-feedback-state state/btc5_autoresearch_feedback_state.json --restart-on-promote'
```

`deploy/btc5-autoresearch.timer`:

```ini
[Timer]
OnBootSec=15min
OnUnitActiveSec=3h
Persistent=true
Unit=btc5-autoresearch.service
```

Implication:

- The core loop runs every 3 hours.
- It can write overrides and restart the live BTC5 service.
- This is already close to end-to-end autonomy, but the contract is incomplete.

### JJ live

There is a separate live runtime surface in `bot/jj_live.py`, and the freshest remote service status artifact only explicitly reports `jj-live.service` as running.

`reports/remote_service_status.json`:

```json
{
  "checked_at": "2026-03-24T00:38:55.473137+00:00",
  "service_name": "jj-live.service",
  "status": "running",
  "systemctl_state": "active"
}
```

But the runtime reconciliation artifact separately says the BTC5 service is running while launch posture is blocked.

## Current Machine-Truth Snapshot

### Remote cycle / runtime truth

From `reports/remote_cycle_status.json` and `reports/runtime_truth_latest.json`:

```json
{
  "accounting_reconciliation": {
    "btc_5min_maker_counts": {
      "latest_live_filled_at": "2026-03-23T19:10:02.544220+00:00",
      "live_filled_pnl_usd": -54.1415,
      "live_filled_rows": 25,
      "total_rows": 1399
    },
    "drift_detected": true,
    "local_ledger_counts": {
      "open_positions": 0,
      "closed_positions": 0
    },
    "remote_wallet_counts": {
      "open_positions": 5,
      "closed_positions": 50,
      "live_orders": 1
    }
  },
  "agent_run_mode": "live",
  "allow_order_submission": false
}
```

### Public runtime snapshot

From `reports/public_runtime_snapshot.json`:

```json
{
  "btc5_daily_pnl": {
    "et_day_fill_count": 5,
    "et_day_realized_pnl_usd": -22.3994,
    "rolling_24h_fill_count": 5,
    "rolling_24h_realized_pnl_usd": -22.3994
  },
  "btc5_stage_readiness": {
    "allowed_stage": 0,
    "baseline_live_allowed": false,
    "can_trade_now": false,
    "stage_1_blockers": [
      "btc5_forecast_not_promote_high",
      "trailing_12_live_filled_not_positive",
      "insufficient_trailing_12_live_fills",
      "selected_runtime_package_not_promote",
      "selected_runtime_package_confidence_below_medium",
      "selected_runtime_package_generalization_below_0.70",
      "accounting_reconciliation_drift",
      "local_ledger_drift_vs_remote_wallet",
      "confirmation_coverage_insufficient"
    ]
  }
}
```

### Runtime reconciliation

From `reports/runtime/reconciliation/runtime_mode_reconciliation_20260324T003905Z.md`:

```text
- Service state: running
- Effective runtime profile: shadow_fast_flow
- Agent run mode: live
- Execution mode: shadow
- Paper trading: True
- Allow order submission: False
- Launch posture: blocked
- Service running while launch blocked: yes
- btc-5min-maker.service is running while launch posture remains blocked
```

Implication:

- There is no single, clean control plane.
- The system has at least two conflicting truths:
  - a running BTC5 live service
  - a blocked overall launch posture
- This is exactly the kind of architectural ambiguity that makes "is it working?" impossible to answer quickly.

## Current Config Surfaces

### Base strategy env

`config/btc5_strategy.env`:

```env
BTC5_MAX_ABS_DELTA=0.0040
BTC5_UP_MAX_BUY_PRICE=0.52
BTC5_DOWN_MAX_BUY_PRICE=0.53
BTC5_MIN_BUY_PRICE=0.42
BTC5_PROBE_MAX_ABS_DELTA=0.0040
BTC5_PROBE_UP_MAX_BUY_PRICE=0.52
BTC5_PROBE_DOWN_MAX_BUY_PRICE=0.53

BTC5_HOUR_FILTER_ENABLED=false
BTC5_SUPPRESS_HOURS_ET=0,1,2,8,9
BTC5_BOOST_HOURS_ET=3,4,5,6,12,13,14,15,16,17,18,19

BTC5_DIRECTION_FILTER_ENABLED=false
BTC5_DIRECTION_MODE=both
BTC5_DOWN_BIAS_THRESHOLD=0.60

BTC5_EDGE_TRACKER_CYCLE_INTERVAL=100
```

### Autoresearch override env

`state/btc5_autoresearch.env`:

```env
# generated_at=2026-03-14T16:30:00.000000+00:00
# candidate=instance13_guardrail_fix_delta_widen_prices_fix
# reason=delta_0.0013_still_skipping_widen_to_0.0040_fix_price_caps
BTC5_MAX_ABS_DELTA=0.0040
BTC5_UP_MAX_BUY_PRICE=0.52
BTC5_DOWN_MAX_BUY_PRICE=0.53
BTC5_PROBE_MAX_ABS_DELTA=0.0040
BTC5_PROBE_UP_MAX_BUY_PRICE=0.52
BTC5_PROBE_DOWN_MAX_BUY_PRICE=0.53
BTC5_SESSION_OVERRIDES_JSON=[]
BTC5_SESSION_POLICY_JSON=[]
BTC5_MIN_BUY_PRICE=0.42
BTC5_MIN_DELTA=0.00010
BTC5_UP_LIVE_MODE=live_enabled
BTC5_ENFORCE_LT049_SKIP_BASELINE=0
```

### Capital stage env

`state/btc5_capital_stage.env`:

```env
BTC5_DEPLOY_MODE=live_stage1
BTC5_PAPER_TRADING=false
BTC5_CAPITAL_STAGE=1
BTC5_BANKROLL_USD=390
BTC5_RISK_FRACTION=0.02
BTC5_MAX_TRADE_USD=10
BTC5_STAGE2_MAX_TRADE_USD=15
BTC5_STAGE3_MAX_TRADE_USD=20
BTC5_MIN_TRADE_USD=5
BTC5_DAILY_LOSS_LIMIT_USD=5
BTC5_MIN_BUY_PRICE=0.48
BTC5_BOOTSTRAP_LIVE_OVERRIDE=true
```

Important contradiction:

- `config/btc5_strategy.env` says `BTC5_MIN_BUY_PRICE=0.42`
- `state/btc5_capital_stage.env` later sets `BTC5_MIN_BUY_PRICE=0.48`
- Service file order means the later stage env wins unless `.env` overrides it again
- This is a concrete example of why the env chain is too implicit

## The Current Mutation / Deploy Path

### Core autoresearch writes only the override env

From `scripts/run_btc5_autoresearch_cycle_core.py`:

```python
def _write_override_env(path: Path, *, best_target: dict[str, Any], decision: dict[str, Any]) -> None:
    existing_values = _load_env_file(path)
    write_text_atomic(
        path,
        render_strategy_env(
            best_target,
            {
                "generated_at": _now_utc().isoformat(),
                "reason": decision.get("reason"),
                "current_min_buy_price": existing_values.get("BTC5_MIN_BUY_PRICE")
                or os.environ.get("BTC5_MIN_BUY_PRICE"),
            },
        ),
        encoding="utf-8",
    )
```

### Core autoresearch can restart the service

```python
def _restart_service(service_name: str) -> dict[str, Any]:
    result = subprocess.run(
        ["sudo", "systemctl", "restart", service_name],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    active = subprocess.run(
        ["sudo", "systemctl", "is-active", service_name],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    return {
        "restart_returncode": result.returncode,
        "service_state": (active.stdout or "").strip(),
    }
```

### Promotion path in the core loop

```python
restart_result: dict[str, Any] | None = None
if decision["action"] == "promote" and best_candidate is not None:
    _write_override_env(
        args.override_env,
        best_target=best_candidate,
        decision=decision,
    )
    if args.restart_on_promote:
        restart_result = _restart_service(str(args.service_name))
```

### But runtime-load verification is weak

```python
def _runtime_load_status(...):
    override_values = _load_env_file(override_env_path)
    session_policy_records = len(_runtime_session_policy_from_env(override_values))
    return {
        "override_env_written": bool(override_values),
        "override_env_path": str(override_env_path),
        "session_policy_records": session_policy_records,
        "base_env_changed": False,
        "service_restart_requested": bool(...),
        "service_restart_state": str((restart_result or {}).get("service_state") or "").strip() or None,
    }
```

This is not the same as verifying that:

- the process loaded the intended params
- the service is healthy after restart
- fills improved post-mutation
- the mutation beat the prior config over a measured window

### There is also a second promotion path that writes the base env

From `scripts/btc5_autoresearch_autopush.py`:

```python
env_text = render_strategy_env(best_candidate, ...)
args.base_env.write_text(env_text)
...
git add ...
git commit ...
git push ...
```

This means there are two mutation surfaces:

1. core cycle writes `state/btc5_autoresearch.env`
2. autopush helper writes `config/btc5_strategy.env`

That is architectural confusion, not robustness.

## The Current Feedback Loop: Better Than The Narrative, But Still Not Closed

The core cycle already computes a post-cycle feedback summary.

From `scripts/run_btc5_autoresearch_cycle_core.py`:

```python
def _fill_feedback_summary(...):
    state = _load_fill_feedback_state(feedback_state_path)
    fill_rows, total_rows, diagnostics = _db_window_rows_since(db_path, state)
    actual = _actual_metrics_from_fill_rows(fill_rows, total_rows=total_rows)
    predicted = _prediction_metrics_from_candidate(...)

    metric_deltas = {}
    for key in ("fill_rate", "direction_accuracy", "pnl_per_fill"):
        ...
        metric_deltas[key] = round(float(actual_value) - float(predicted_value), 6)

    ...
    for metric_name, default_sigma in sigma_defaults.items():
        ...
        if abs(float(delta)) > (2.0 * sigma):
            adjustment_flags.append(...)

    feedback_summary = {
        "actual_metrics": actual,
        "predicted_metrics": predicted,
        "metric_deltas": metric_deltas,
        "parameter_adjustment_flags": adjustment_flags,
        "needs_parameter_adjustment": bool(adjustment_flags),
        "db_diagnostics": diagnostics,
    }
```

This is important:

- The loop already measures actual vs predicted fill outcomes.
- It already has a state file concept.
- It already computes `needs_parameter_adjustment`.

But what it does not appear to do:

- it does not auto-revert a bad promoted config
- it does not keep a formal "mutate -> deploy -> observe next N cycles -> decide keep/revert" contract
- it does not appear to pin a promoted config to a required post-promotion verification window
- it does not appear to block further mutation churn until the prior mutation is actually judged

Also note:

- The local file `state/btc5_autoresearch_feedback_state.json` does not currently exist in this repo snapshot, so the loop will initialize state on demand.

## BTC5 Live Stage Logic

From `bot/btc_5min_maker.py`:

```python
def _configured_live_stage(self) -> int:
    stage = self.cfg.capital_stage
    if stage in LIVE_STAGE_IDS:
        return int(stage)
    return 1
```

and:

```python
def _capital_stage_controls(self, *, today_pnl: float) -> dict[str, Any]:
    desired_stage = self._configured_live_stage()
    ...
    highest_ready_stage = 1
    if stage2_gates:
        highest_ready_stage = 2
    if stage3_gates:
        highest_ready_stage = 3
```

Implication:

- This surface defaults to stage 1, not stage 0.
- It does not naturally encode "do not trade at all" as the first-class fallback.
- That design choice matters when the wider runtime says launch posture is blocked.

## JJ Runtime Guard

`jj_live.py` has a separate runtime truth guard:

```python
def _evaluate_runtime_truth_guard(self) -> dict[str, Any]:
    ...
    posture_green = launch_posture in {"clear", "green", "unblocked"}
    paper_green = paper_trading is False
    mode_green = agent_run_mode in {"micro_live", "live"}
    submit_green = order_submit_enabled is True
    greenlight = posture_green and paper_green and mode_green and submit_green
    ...

def _refresh_runtime_truth_guard(self) -> None:
    ...
    if not guard.get("greenlight", False):
        self.allow_order_submission = False
```

Implication:

- `jj_live` is trying to enforce a global truth guard.
- BTC5 has its own separate live service and stage logic.
- This is another sign that the system lacks one authoritative live-trading control plane.

## Skip-Filter Surface

### Literal skip statuses in code

A direct parse of `bot/btc_5min_maker.py` found 22 literal `skip_*` order statuses:

```text
skip_adaptive_direction_suppressed
skip_bad_book
skip_below_min_shares
skip_daily_loss_limit
skip_delta_too_large
skip_delta_too_small
skip_direction_suppressed
skip_down_mid_bucket_experiment
skip_excluded_price_bucket
skip_inventory_contract_cap
skip_loss_cluster_suppressed
skip_market_not_found
skip_missing_price
skip_no_book
skip_price_bucket_floor
skip_price_outside_guardrails
skip_probe_confirmation_mismatch
skip_probe_confirmation_pending
skip_shadow_only_direction
skip_size_too_small
skip_suppressed_hour
skip_token_not_found
```

### What the current local DB actually shows

Local DB query on `data/btc_5min_maker.db`:

```sql
select order_status, count(*) c
from window_trades
group by order_status
order by c desc;
```

Top statuses:

```text
skip_price_outside_guardrails      240   22.7%
skip_delta_too_large               182   17.2%
skip_bad_book                      151   14.3%
skip_probe_confirmation_mismatch   132   12.5%
skip_delta_too_small               116   11.0%
skip_toxic_order_flow               56    5.3%
skip_shadow_only_direction          56    5.3%
skip_probe_confirmation_pending     29    2.7%
skip_adaptive_direction_suppressed  26    2.5%
skip_midpoint_kill_zone             25    2.4%
live_filled                         23    2.2%
live_order_failed                   12    1.1%
live_cancelled_unfilled              6    0.6%
```

Important notes:

- Only 13 skip statuses have appeared in the current local DB.
- The biggest killers are not just delta:
  - `skip_price_outside_guardrails` is larger than `skip_delta_too_large`
- Current local live fill share is about 2.2%.
- Current local DB also shows:
  - `max(updated_at)` for `live_filled` = `2026-03-23T19:10:02.544220+00:00`
  - 11 positive fills out of 23 resolved local live fills
  - local filled PnL total about `-56.785432`

### Counterfactual pattern already exists for some filters

The time-of-day filter explicitly says it logs counterfactuals:

```python
# --- Configurable time-of-day suppression (with counterfactual logging) ---
if _hour_status == "suppressed":
    row = {
        ...
        "order_status": "skip_suppressed_hour",
        "hour_filter_status": "suppressed",
    }
    _persist(row)
    logger.info(
        "HOUR FILTER: ET hour %02d suppressed, direction=%s delta=%.6f (counterfactual logged)",
        ...
    )
```

The direction filter also persists filtered rows with a filter status:

```python
if self.cfg.direction_filter_enabled and direction in {"UP", "DOWN"}:
    ...
    if dir_filter in {"suppressed", "biased_block"}:
        row = {
            ...
            "order_status": f"skip_direction_mode_{dir_filter}",
            "direction_filter_status": dir_filter,
        }
        _persist(row)
```

But current local DB snapshot shows:

- `hour_filter_status`: all `NULL`
- `direction_filter_status`: all `NULL`

That matches the current base env where both filters are disabled by default.

Implication:

- The repo already contains the beginnings of the "counterfactual filter economics" pattern.
- That pattern is not yet generalized across the older skip surfaces.

## Current DB Schema Reality

The `window_trades` table schema includes:

```sql
window_start_ts
window_end_ts
slug
decision_ts
direction
open_price
current_price
delta
book_imbalance
token_id
best_bid
best_ask
order_price
trade_size_usd
shares
order_id
order_status
filled
reason
decision_reason_tags
risk_mode
edge_tier
sizing_reason_tags
size_adjustment_tags
loss_cluster_suppressed
session_policy_name
effective_stage
wallet_copy
wallet_count
wallet_notional
realized_pnl_usd
resolved_side
won
pnl_usd
created_at
updated_at
hour_filter_status
direction_filter_status
...
```

Important implication:

- There is no dedicated `skip_reason` column.
- Skip semantics are currently spread across:
  - `order_status`
  - `reason`
  - `decision_reason_tags`
  - filter-specific status columns
- If you want durable filter economics, you probably need a more structured decision ledger or a normalized skip-event schema.

## The Simulation / Research Surface Is Also Architecturally Split

This is not the primary ask, but it matters because the live loop is still being "optimized" by conflicting simulation surfaces.

I ran both official simulator entrypoints locally:

```text
python3 -m simulator.run_baseline
-> 602 trades
-> total PnL = -1988.06
-> final capital = 11.94
-> return = -99.4%

python3 -m simulator.run_sim run --config simulator/config.yaml
-> 1260 trades
-> total PnL = +3724.36
-> final capital = 5724.36
-> return = +186.2%
```

Why they disagree:

- `simulator/engine.py` uses a hard-coded calibration map.
- `simulator/simulator.py` uses raw Claude probabilities.
- Both sweep a synthetic fixed price grid `[0.20, 0.30, ..., 0.80]`.
- Both resolve trades immediately against known outcomes.
- `src/maker_fill_model.py` contains a more realistic queue-aware maker fill model, but `simulator/fill_model.py` still uses a toy exponential fill-probability model.

This means the repo still does not have one authoritative simulator that matches the live fill assumptions.

You do not need to solve all of simulation to answer this prompt, but your architecture should not make this split worse.

## Existing Health / Telegram Primitives You Can Reuse

There is already Telegram and health infrastructure in the repo.

### Simple bash heartbeat + Telegram

`scripts/health_check.sh`:

```bash
send_alert() {
    local token="${TELEGRAM_BOT_TOKEN:-${TELEGRAM_TOKEN:-}}"
    local chat_id="${TELEGRAM_CHAT_ID:-}"
    if [ -n "$token" ] && [ -n "$chat_id" ] && command -v curl >/dev/null 2>&1; then
        curl -fsS -X POST "https://api.telegram.org/bot${token}/sendMessage" ...
    fi
}
```

### Python health monitor helpers

`bot/health_monitor.py` already has:

- `build_telegram_sender()`
- `restart_service(...)`
- `run_health_check(...)`

Example:

```python
def build_telegram_sender() -> Callable[[str], bool] | None:
    ...

def restart_service(*, service_name: str, use_sudo: bool = False) -> dict[str, Any]:
    ...

def run_health_check(...):
    ...
```

Implication:

- You do not need to invent Telegram or service-restart plumbing from scratch.
- You should probably design around these existing primitives unless you can justify replacing them.

## The Real Architectural Failures

This section is the heart of the problem.

### 1. No single source of truth for live state

Today the truth is scattered across:

- local SQLite
- remote SQLite probe
- wallet API probe
- runtime truth JSON
- remote cycle status JSON
- public runtime snapshot
- runtime reconciliation markdown
- env files
- systemd service state

These surfaces disagree.

The biggest example:

- runtime says launch posture is blocked and order submission is false
- BTC5 service is still running live
- local ledger says 0 open / 0 closed
- remote wallet says 5 open / 50 closed

### 2. The mutation path is not singular

There are multiple ways to change runtime behavior:

- base env
- override env
- stage env
- `.env`
- autoresearch core
- autopush helper
- service restarts

That means a mutation is not one atomic object. It is a rumor moving through a file chain.

### 3. The loop measures, but does not fully govern

The current loop already computes:

- actual fill rate
- actual direction accuracy
- actual pnl per fill
- delta vs predicted
- sigma-based divergence flags

But it does not yet appear to do the strongest thing:

- define a promoted mutation
- lock it in as the active experiment
- wait N windows
- compare pre-vs-post
- keep or auto-revert
- page a human only on failure / ambiguity

### 4. The health system is too heartbeat-centric

The repo has health tooling, but it is centered on process heartbeat / staleness, not on the five questions the maintainer actually wants:

1. Is the bot running?
2. When was the last fill?
3. What is the rolling win rate over the last 50 fills?
4. What parameters are currently deployed?
5. Does deployed config match the latest autoresearch recommendation?

### 5. Skip logic is encoded as a gauntlet, not an economic portfolio of filters

Right now filters are mostly binary gates.

What is missing is a system that says:

- this filter blocked 132 trades
- if those trades had gone through, estimated EV would have been X
- actual prevented loss was Y
- net value of this filter over the last 500 windows = Y - X
- therefore keep, soften, or kill the filter

### 6. The control plane still privileges addition over subtraction

This repo has many more modules, services, artifacts, and narratives than are needed to run BTC5.

Even if the exact "85 dead modules" number is off, the structural problem is real:

- more surfaces are being added than retired
- AI sessions have to wade through too much irrelevant code
- architecture keeps accreting without a pruning contract

## Useful Design Constraints

When you propose the fix, work within these constraints unless you have a very strong reason not to.

- Do not assume a full platform rewrite is acceptable.
- The fastest path should fix BTC5 first.
- The VPS already uses `systemd`.
- Telegram already exists.
- SQLite already exists and is acceptable for this lane.
- Atomic file writes already exist via `infra.fast_json.write_text_atomic`.
- The system already tolerates env-file-based config.
- The human wants a loop that becomes autonomous end-to-end, with the human reviewing summaries, not manually deploying every mutation.
- The maintainer cares more about architectural coherence than preserving every experiment.

## My Recommendation For The Scope Of The Fix

You are free to disagree, but the likely right scope is:

1. Do not rewrite the entire repo.
2. Build one authoritative BTC5 control loop.
3. Make one state contract for:
   - deployed config
   - active experiment
   - post-promotion verification window
   - last known health
4. Generalize counterfactual filter accounting.
5. Add an explicit prune/archive mechanism for dead modules and services.
6. Defer broader simulator unification if needed, but make sure your design does not depend on contradictory sim surfaces.

## What I Want You To Produce

Return a design document, not generic advice.

Your answer must contain:

1. A blunt diagnosis of the current architecture.
2. A target-state architecture for the BTC5 lane only.
3. The exact control-loop sequence for:
   - observe
   - propose mutation
   - deploy mutation
   - verify mutation
   - keep/revert
   - alert human
4. A single-source-of-truth design.
5. A filter-economics design:
   - schema
   - metrics
   - decision rules
   - auto-disable / manual-review policy
6. A health contract that answers the five operator questions every 30 minutes.
7. A file-level implementation plan using the existing file paths in this packet.
8. A deletion / archive plan for dead modules, services, and docs.
9. A rollout plan with stages:
   - first 24 hours
   - first 3 days
   - first 2 weeks
10. Acceptance criteria that are measurable.

## Output Format I Want From You

Use this exact structure:

1. `Current Failure Mode`
2. `Target BTC5 Control Plane`
3. `Single Source Of Truth Contract`
4. `Mutation Verification And Auto-Revert Design`
5. `Filter Economics Design`
6. `Health Check And Telegram Design`
7. `What To Delete Or Archive`
8. `File-Level Implementation Plan`
9. `Rollout Plan`
10. `Acceptance Criteria`
11. `Risks And Non-Goals`

## Additional Guidance

- Be specific about which existing files should be modified versus replaced.
- Prefer reusing existing health / Telegram / restart primitives.
- Prefer one new authoritative artifact over many new reports.
- Prefer one explicit state machine over multiple implicit env chains.
- Tell us what should become read-only, what should become generated, and what should be deleted.
- If you think the current split between `jj_live` and `btc_5min_maker` is fundamentally wrong, say so clearly.
- If you think BTC5 should temporarily ignore most of the wider repo and become its own small bounded subsystem, say so clearly.

## Appendix A: Key File Map

- `bot/btc_5min_maker.py`
  - the actual BTC5 live bot
  - owns skip decisions, sizing, fills, stage controls
- `bot/jj_live.py`
  - separate live runtime with its own truth guard
- `config/btc5_strategy.env`
  - base BTC5 strategy config
- `state/btc5_autoresearch.env`
  - autoresearch override env
- `state/btc5_capital_stage.env`
  - live capital stage settings
- `deploy/btc-5min-maker.service`
  - BTC5 live service
- `deploy/btc5-autoresearch.service`
  - BTC5 autoresearch service
- `deploy/btc5-autoresearch.timer`
  - 3-hour timer
- `scripts/run_btc5_autoresearch_cycle_core.py`
  - real autoresearch core
- `scripts/btc5_autoresearch_autopush.py`
  - alternate promotion path that writes base env and pushes to git
- `bot/health_monitor.py`
  - reusable Telegram + health primitives
- `scripts/health_check.sh`
  - reusable bash heartbeat + Telegram alert primitive
- `reports/runtime_truth_latest.json`
  - latest runtime truth snapshot
- `reports/public_runtime_snapshot.json`
  - public-facing runtime summary
- `reports/remote_cycle_status.json`
  - wallet/probe/runtime truth surface
- `reports/runtime/reconciliation/runtime_mode_reconciliation_20260324T003905Z.md`
  - explicit drift and posture reconciliation

## Appendix B: Raw Query Results

Local DB existence and counts:

```text
data/btc_5min_maker.db exists = True

select count(*) from window_trades
-> 1059

select count(*) from window_trades where lower(coalesce(order_status,''))='live_filled'
-> 23

select count(*) from window_trades where lower(coalesce(order_status,'')) like 'skip%' or lower(coalesce(order_status,''))='skipped'
-> 1017
```

Observed skip statuses in local DB:

```text
unique_skip_statuses = 13
skip_price_outside_guardrails
skip_delta_too_large
skip_bad_book
skip_probe_confirmation_mismatch
skip_delta_too_small
skip_toxic_order_flow
skip_shadow_only_direction
skip_probe_confirmation_pending
skip_adaptive_direction_suppressed
skip_midpoint_kill_zone
skip_directional_mode
skip_size_too_small
skip_price_bucket_floor
```

Recent local fill facts:

```text
max(updated_at) where order_status='live_filled'
-> 2026-03-23T19:10:02.544220+00:00

positive_fills / resolved_local_live_fills
-> 11 / 23

sum(pnl_usd) for local live_filled
-> -56.785432
```

## Appendix C: The Maintainer's Core Complaint In One Sentence

The system can mutate itself, but it still does not reliably prove that a mutation made the live trading loop better, and it is buried under too many competing surfaces to know quickly what is real.
