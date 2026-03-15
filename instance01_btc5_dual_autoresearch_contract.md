# Instance 01 BTC5 Dual Autoresearch Contract

Status: canonical lane contract for the BTC5 dual-autoresearch build
Last updated: 2026-03-11
Scope: BTC5 only

## Source Precedence

When facts conflict, use this order:

1. `reports/runtime_truth_latest.json` for launch posture, runtime mode, service health, artifact freshness, and gate state
2. `reports/btc5_correlation_lab/latest.json` for current BTC5 replay surface, feature availability, and historical edge context
3. `reports/agent_workflow_mining/summary.json` for command-node workflow patterns and repeated handoff structure
4. This contract plus the three lane program files:
   - `btc5_market_model.md`
   - `btc5_policy_autopromote.md`
   - `btc5_command_node.md`

Machine-truth artifacts beat prose. Benchmark progress is benchmark progress. Do not restate benchmark loss improvements as realized live P and L.

## Lane Summary

| Lane | Mutable surface | Immutable evaluator inside the epoch | Scalar loss | Keep means | Active champion may roll |
|---|---|---|---|---|---|
| BTC5 market-model autoresearch | `btc5_market_model_candidate.py` | `benchmarks/btc5_market/v1/manifest.json`, fixed scorer, fixed renderer | `simulator_loss` | new best loss on the frozen epoch benchmark | only at epoch boundary |
| BTC5 policy autoresearch | one candidate package directory under `reports/autoresearch/btc5_policy/candidates/<candidate_policy>/` | active market-model champion, fixed policy scorer, fixed activation gates | `policy_loss` | candidate becomes new policy champion, either live or shadow | any cycle, subject to gates |
| BTC5 command-node autoresearch | `btc5_command_node.md` | `benchmarks/command_node_btc5/v1/tasks.jsonl`, fixed scorer, fixed renderer | `agent_loss` | new best loss on the frozen task suite | only at epoch boundary |

## Shared Rules

### Scope And Hard Boundaries

- BTC5 is the only in-scope live lane for v1.
- The command-node lane applies only to the BTC5 command node. It does not get to rewrite repo-wide behavior contracts.
- No lane may invent new benchmark metrics, change benchmark labels, or convert benchmark wins into live-profit claims.
- Hard safety interlocks remain mandatory: service health, artifact freshness, kill rules, reserve and cap policy, and posture coherence.

### Epoch Contract

- One benchmark epoch lasts exactly 24 hours.
- Every frozen benchmark package must carry:
  - `epoch_id`
  - `epoch_started_at_utc`
  - `epoch_expires_at_utc`
- `epoch_expires_at_utc` must equal `epoch_started_at_utc + 24h`.
- Once an epoch manifest or task suite is written, it is immutable until `epoch_expires_at_utc`.
- Market-model and command-node experiments may discover better candidates during the epoch, but those candidates are pending frontiers only.
- The active market-model champion and the active command-node champion remain fixed for the full epoch.
- At the first cycle after `epoch_expires_at_utc`, the controller may roll the active champion only by:
  1. selecting the best kept candidate from the ending epoch,
  2. rerunning it once on the same frozen harness with the same fixed seeds,
  3. confirming the rerun produces the same decision packet,
  4. promoting it to the next epoch champion.
- If there is no kept candidate, or the confirmation rerun fails, carry the previous champion forward into the next epoch.

### Outcome Semantics

- `keep`: valid evaluation packet plus a strictly better scalar loss than the current frontier for that lane
- `discard`: valid evaluation packet that does not beat the current frontier
- `crash`: the candidate, evaluator, or result packet is invalid, missing, non-deterministic, or throws before a valid scalar loss is produced

Every experiment cycle must append one row to its ledger. A null-result cycle is still a row.

## Common Artifact Contract

| Surface | Contract |
|---|---|
| Market benchmark manifest | `benchmarks/btc5_market/v1/manifest.json` freezes windows, seeds, features, objective, and epoch metadata |
| Command-node task suite | `benchmarks/command_node_btc5/v1/tasks.jsonl` freezes the BTC5 planning tasks for the epoch |
| Market ledger | `reports/autoresearch/btc5_market/results.jsonl` is append-only |
| Policy ledger | `reports/autoresearch/btc5_policy/results.jsonl` is append-only |
| Command-node ledger | `reports/autoresearch/command_node/results.jsonl` is append-only |
| Market public chart | `research/btc5_market_model_progress.svg` |
| Command-node public chart | `research/btc5_command_node_progress.svg` |
| Morning packet | `reports/autoresearch/morning/latest.md` summarizes the last overnight cycle |

## BTC5 Market-Model Lane

### Purpose

Improve the BTC5 simulator and evaluator itself against a frozen benchmark epoch without letting the evaluator mutate its own ruler.

### Mutable Surface

- One file only: `btc5_market_model_candidate.py`

The mutable file may change model logic, feature interactions, replay heuristics, and fill estimation logic that live inside the candidate implementation. It may not change the benchmark manifest, scorer, renderer, or ledger schema during the epoch.

### Immutable Benchmark Contract

`benchmarks/btc5_market/v1/manifest.json` must freeze these fields:

- `benchmark_id`
- `version`
- `epoch_id`
- `epoch_started_at_utc`
- `epoch_expires_at_utc`
- `objective_name`
- `objective_formula`
- `seed_values`
- `window_source`
- `window_count`
- `feature_columns`
- `cached_artifact_paths`
- `db_enrichment_paths`
- `mutable_surface`
- `immutable_runner_paths`

Data sourcing rules for the market benchmark:

- Start from current BTC5 machine-truth artifacts and the local BTC5 DB or cache.
- Use cached rows when the DB is absent.
- Add DB-only enrichments when the DB is present.
- `reports/btc5_correlation_lab/latest.json` is the first replay-surface truth document.
- `data/btc_5min_maker.db` is the preferred local enrichment source when available.

### Scalar Objective

`simulator_loss = 0.40*pnl_window_mae_pct + 0.25*fill_rate_mae_pct + 0.20*side_brier + 0.15*p95_drawdown_mae_pct`

Lower is better.

### Keep, Discard, Crash

- `keep`: candidate run finishes, emits a valid loss packet, and `simulator_loss` is strictly lower than the current epoch frontier
- `discard`: candidate run finishes and emits a valid loss packet, but `simulator_loss` is not lower than the current epoch frontier
- `crash`: import failure, runtime exception, missing manifest field, invalid loss packet, or fixed-seed replay mismatch

### Ledger Contract

`reports/autoresearch/btc5_market/results.jsonl` must append rows with at least:

- `experiment_id`
- `epoch_id`
- `candidate_hash`
- `status`
- `loss`
- `keep`
- `champion_id`
- `artifact_paths`

`champion_id` is the active champion used for the experiment. It does not change inside the epoch.

### Champion Rollover

- The market-model loop may maintain a pending best candidate during the epoch.
- The policy lane must keep using the active market-model champion for the whole epoch.
- At the epoch boundary, the best kept candidate becomes the next active market-model champion only after the confirmation rerun passes.

## BTC5 Policy Lane

### Purpose

Search BTC5 policy packages against the active market-model champion and autonomously replace the live BTC5 package when the candidate is actually better and the machine safety gates are green.

### Mutable Surface

The mutable surface is one candidate package directory per experiment:

- `reports/autoresearch/btc5_policy/candidates/<candidate_policy>/`

That package directory is the only thing the search loop may mutate. The package may contain:

- `package.json`
- `strategy.env`

`package.json` must be the canonical description. `strategy.env` is the runtime render target. The policy loop must never edit live runner code directly.

The minimum `package.json` shape is:

- `candidate_policy`
- `generated_at`
- `runtime_package`
- `runtime_package.profile`
- `runtime_package.session_policy`
- `source_artifacts`

### Immutable Evaluator Contract

The policy evaluator is fixed for the cycle and uses:

- the active market-model champion from the market lane
- the incumbent BTC5 package from `reports/btc5_autoresearch/latest.json`
- the current probe from `reports/btc5_autoresearch_current_probe/latest.json`
- runtime gate truth from `reports/runtime_truth_latest.json`
- rollout state from `reports/runtime/btc5/btc5_rollout_latest.json` when present

Activation rules:

- `config/btc5_strategy.env` stays the immutable base policy package
- `state/btc5_autoresearch.env` is the activation target written by the controller
- the search loop may select and stage packages, but it may not patch live code

### Scalar Objective

`policy_loss = (-p05_30d_return_pct) + 0.25*(-median_30d_return_pct) + 2.0*loss_limit_hit_probability + 1.0*non_positive_path_probability + 0.05*p95_drawdown_pct`

Lower is better.

The policy ledger must use these exact field names:

- `p05_30d_return_pct`
- `median_30d_return_pct`
- `loss_limit_hit_probability`
- `non_positive_path_probability`
- `p95_drawdown_pct`
- `fill_retention_ratio`

Do not reuse ARR names for this benchmark.

### Promotion Rule

A candidate may replace the incumbent policy champion only if all of these are true:

1. it beats incumbent `policy_loss` by at least `0.25`
2. it improves `median_30d_return_pct`
3. it does not worsen `p05_30d_return_pct`
4. it keeps `fill_retention_ratio >= 0.85`
5. all non-posture safety interlocks are green

Non-posture safety interlocks are:

- service health
- artifact freshness
- kill rules
- reserve-floor policy
- action-cap and commitment-cap policy
- posture coherence

If `launch_posture != clear`, and checks 1 through 5 pass, the controller must:

- update the shadow policy champion immediately
- queue live activation automatically for the first clear cycle

No human approval step remains once the controller is proven.

### Keep, Discard, Crash

- `keep`: valid evaluation packet, all benchmark gates pass, and all non-posture safety interlocks pass
- `discard`: valid evaluation packet, but the candidate fails any benchmark gate or any non-posture safety interlock
- `crash`: invalid package, missing simulator champion, failed evaluation, invalid decision packet, or failed rollback action

`launch_posture=blocked` by itself is not a discard if the candidate otherwise qualifies. That case is a kept shadow champion with queued live activation.

### Ledger Contract

`reports/autoresearch/btc5_policy/results.jsonl` must append rows with at least:

- `candidate_policy`
- `simulator_champion_id`
- `loss`
- `promotion_state`
- `safety_gate_snapshot`
- `artifact_paths`

`promotion_state` must use one of these values:

- `discarded`
- `shadow_queued`
- `live_promoted`
- `rolled_back`
- `crash`

`safety_gate_snapshot` must at least capture:

- `launch_posture`
- `execution_mode`
- `service_health`
- `artifact_freshness`
- `kill_rules_green`
- `reserve_policy_green`
- `cap_policy_green`
- `posture_coherent`

### Rollback Contract

- The controller must keep the previous live package as the rollback target.
- Rollback is automatic on post-promotion underperformance or stale-health breach.
- Rollback restores the previous live package to `state/btc5_autoresearch.env`.
- Rollback must append a new row to the policy ledger. It does not rewrite history.

## BTC5 Command-Node Lane

### Purpose

Improve the BTC5 command-node planning agent on a frozen task suite derived from historical BTC5 dispatches and workflow-mined handoffs.

### Mutable Surface

- One file only: `btc5_command_node.md`

The command-node lane may change only that file. It may not change the task suite, scorer, chart renderer, or repo-wide root behavior contracts inside the epoch.

### Immutable Benchmark Contract

`benchmarks/command_node_btc5/v1/tasks.jsonl` is the frozen task suite for the epoch.

Each task row must define:

- `task_id`
- `epoch_id`
- `source_paths`
- `input_context_paths`
- `expected_model_selection`
- `expected_dependency_order`
- `expected_output_paths`
- `required_checklist_items`
- `judge_reference`

The task suite is sourced from:

- historical BTC5 dispatches
- `COMMAND_NODE.md`
- `reports/agent_workflow_mining/summary.json`

### Scalar Objective

`agent_loss = 100 - total_score`

Where:

- `total_score = 30 source/path correctness + 25 dependency correctness + 25 dispatch completeness + 20 judge clarity`

Lower is better.

All four subscores must be machine-computable from the frozen task suite and scorer.

### Keep, Discard, Crash

- `keep`: candidate prompt file finishes evaluation and produces a strictly lower `agent_loss` than the current epoch frontier
- `discard`: candidate prompt file finishes evaluation, but `agent_loss` is not lower than the current epoch frontier
- `crash`: missing task-suite fields, invalid scorer output, prompt parsing failure, or any evaluation failure that prevents a valid scalar loss

### Ledger Contract

`reports/autoresearch/command_node/results.jsonl` must append rows with at least:

- `prompt_hash`
- `task_suite_id`
- `loss`
- `subscores`
- `keep`
- `artifact_paths`

The active command-node champion stays fixed for the whole epoch and rolls only at the next epoch boundary after the confirmation rerun.

## Public Chart Contract

Only two public charts are required in this wave:

- `research/btc5_market_model_progress.svg`
- `research/btc5_command_node_progress.svg`

Both charts must use the same visual grammar:

- gray discarded points
- green kept points
- green running-best step line
- angled annotations on kept improvements
- x-axis labeled experiment number
- y-axis labeled with lane-specific loss text and the words `lower is better`

Required y-axis labels:

- `BTC5 market-model loss (lower is better)`
- `BTC5 command-node loss (lower is better)`

## Definition Of Done For Instance 1

- every lane has exactly one mutable surface
- every lane has one scalar loss and explicit keep, discard, and crash rules
- epoch freeze and champion-roll rules are unambiguous
- policy live promotion stays autonomous after bootstrap
- machine safety interlocks remain mandatory
