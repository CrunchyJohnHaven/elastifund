# Flywheel Control Plane

**Status:** implemented MVP
**Last Updated:** 2026-03-07

## Purpose

This document defines the operating model for a fully automated Elastifund flywheel. The live bot remains the execution engine, but a separate control plane decides:

- which strategy versions exist
- where each strategy is deployed
- whether a strategy is promoted, held, demoted, or killed
- what the next engineering and research tasks are
- which artifacts and reports should be published after each cycle

The control plane is designed to maximize research velocity without allowing self-modifying code to widen live risk silently.

## Design Principles

1. Live execution is isolated from research and code generation.
2. Every strategy version is immutable once registered.
3. Promotions are evidence-based and stage-bound.
4. Every cycle ends with explicit actions, not free-form notes.
5. The same evidence store powers automation, reporting, and human review.

## Lanes

The system treats strategy families as independent lanes:

- `slow_directional`: LLM-assisted longer-horizon forecasting
- `fast_flow`: wallet flow, maker microstructure, latency-sensitive logic
- `structural_arb`: deterministic or semi-deterministic structural violations

Each lane has a champion/challenger model:

- one champion may hold meaningful live capital
- multiple challengers may run in paper or shadow
- at most one challenger per lane may run in `micro_live`

## Environments

Every strategy version moves through the same ladder:

1. `sim`
2. `paper`
3. `shadow`
4. `micro_live`
5. `scaled_live`
6. `core_live`

The control plane does not skip stages. A version can be auto-promoted only within policy limits. Any move into meaningful live capital remains gated by risk policy and explicit evidence.

## Core Entities

### Strategy Version

Immutable record describing one deployable strategy artifact.

Required fields:

- `strategy_key`
- `version_label`
- `lane`
- `artifact_uri`
- `git_sha`
- `config`
- `status`

### Deployment

Represents a strategy version running in one environment.

Required fields:

- `strategy_version_id`
- `environment`
- `capital_cap_usd`
- `status`
- `started_at`

### Promotion Decision

Immutable audit record of a stage transition attempt.

Required fields:

- `strategy_version_id`
- `from_stage`
- `to_stage`
- `decision`
- `reason_code`
- `metrics`

### Finding

Structured lesson or regression captured from a cycle, benchmark lane, or peer import.

Required fields:

- `finding_key`
- `source_kind`
- `finding_type`
- `title`
- `summary`
- `evidence`

Why this exists:

- tasks tell agents what to do next
- findings tell agents what the system learned and why
- both need to be queryable if multiple autonomous workers are supposed to self-route safely

### Daily Snapshot

Environment-level scorecard used by automations, dashboards, and external reporting.

Required fields:

- `environment`
- `snapshot_date`
- `starting_bankroll`
- `ending_bankroll`
- `realized_pnl`
- `unrealized_pnl`
- `open_positions`
- `closed_trades`
- `win_rate`
- `fill_rate`
- `avg_slippage_bps`
- `rolling_brier`
- `rolling_ece`
- `max_drawdown_pct`
- `kill_events`

## Promotion Policy

The policy engine emits one of:

- `promote`
- `hold`
- `demote`
- `kill`

Hard kill conditions:

- negative realized EV with enough sample
- excessive drawdown
- fill rate collapse
- calibration drift
- kill-switch events

Promotion is conservative:

- `sim -> paper`: requires positive modeled edge and non-zero signal rate
- `paper -> shadow`: requires positive realized EV, acceptable drawdown, acceptable calibration
- `shadow -> micro_live`: requires positive realized EV, acceptable fill rate, acceptable slippage
- `micro_live -> scaled_live`: requires stable realized EV and no kill events
- `scaled_live -> core_live`: intentionally not auto-approved in the MVP

## Automation Outputs

Every flywheel cycle produces machine-readable outputs:

- `scorecard.json`
- `promotion_decisions.json`
- `tasks.md`
- `findings.json`
- `summary.md`

The contributor reputation and quadratic-funding layer that sits beside this control plane is documented in [Flywheel_Incentive_System.md](Flywheel_Incentive_System.md).

Allowed action verbs:

- `observe`
- `recommend`
- `deploy_to_paper`
- `promote`
- `demote`
- `kill`

Task rows now also carry routing metadata:

- `lane`
- `environment`
- `source_kind`
- `source_ref`
- optional structured `metadata`

## Benchmark Lane Reviews

The calibration autoresearch lane feeds this control plane through explicit review tasks, not silent code adoption. Each retained benchmark improvement or documented null result can be published as a flywheel task with the benchmark packet path attached.

That keeps the boundary clear:

- benchmark lanes may generate review work
- benchmark lanes may not auto-promote themselves into paper or live environments
- benchmark artifacts remain labeled as benchmark evidence until a separate replay, paper, or shadow evaluation exists

## Safety Boundary

The control plane may:

- register new strategy versions
- deploy to `sim`, `paper`, or `shadow`
- auto-promote to `micro_live` only when policy allows and capital cap stays within the exploration sleeve
- generate implementation tasks and reports
- register forked agent runtimes and track heartbeats
- queue hub commands such as `pause`, `resume`, `shutdown`, and `rotate_api_key`
- auto-pause an agent when runtime activity deviates beyond the anomaly threshold

The control plane may not:

- change risk limits beyond configured bounds
- move a strategy into `core_live`
- alter credentials
- disable kill switches
- spend capital outside predefined caps

## Agent Command Channel

Phase 10.1 adds a persisted hub-to-agent command queue.

Tables:

- `agent_runtimes`
- `agent_commands`

Operational flow:

1. the agent registers or refreshes its runtime identity
2. each snapshot or heartbeat updates the runtime record
3. the hub can queue `pause`, `resume`, `shutdown`, or `rotate_api_key`
4. the agent polls, applies the command, and acknowledges it

CLI entrypoints:

- `python -m data_layer flywheel-agent-register`
- `python -m data_layer flywheel-agent-heartbeat`
- `python -m data_layer flywheel-agent-command`
- `python -m data_layer flywheel-agent-poll`
- `python -m data_layer flywheel-agent-ack`

## Anomaly Guardrail

The MVP now includes an automatic pause rail based on expected activity.

- baseline window: at least `5` historical observations
- trigger: absolute deviation greater than `3σ`
- default metric: `closed_trades`
- optional override: `metrics.activity_metric` plus `metrics.activity_value`

When triggered, the control plane:

- marks the runtime `paused`
- stores the anomaly reason
- queues a `pause` command
- emits a high-priority guardrail task into the cycle artifacts

## Federated-Round Resilience

The peer-learning layer now has a local simulation harness for poisoned updates.

- aggregation method: Krum-style survivor selection followed by stake-weighted trimmed mean
- default simulation: `50` agents with `10%` malicious updates
- CLI entrypoint: `python -m data_layer flywheel-simulate-federation`

## Storage Model

The MVP uses the existing synchronous SQLAlchemy data layer as the control-plane store. This keeps the system simple and testable inside the current repo.

Longer-term target:

- `Postgres`: control plane and registry
- `ClickHouse`: event analytics and replays
- object store: artifacts and reports

## CLI Contract

The control plane is operated through `python -m data_layer flywheel-*` commands:

- `flywheel-init`
- `flywheel-bridge`
- `flywheel-cycle`
- `flywheel-scorecard`
- `flywheel-export-bulletin`
- `flywheel-import-bulletin`
- `flywheel-export-improvement`
- `flywheel-import-improvement`
- `flywheel-reputation-award`
- `flywheel-reputation-award-github`
- `flywheel-reputation-award-performance`
- `flywheel-reputation-leaderboard`
- `flywheel-funding-create-round`
- `flywheel-funding-submit-proposal`
- `flywheel-funding-vote`
- `flywheel-funding-tally`

Example:

```bash
python -m data_layer flywheel-bridge \
  --bot-db /path/to/bot.db \
  --strategy-key wallet-flow \
  --version-label wf-20260307 \
  --lane fast_flow \
  --environment paper \
  --capital-cap-usd 25 \
  --output /tmp/flywheel_payload.json

python -m data_layer flywheel-cycle \
  --input /tmp/flywheel_payload.json \
  --artifact-dir reports/flywheel

python -m data_layer flywheel-export-bulletin \
  --peer-name alpha-fork \
  --output /tmp/alpha_fork_bulletin.json

python -m data_layer flywheel-import-bulletin \
  --input /tmp/alpha_fork_bulletin.json
```

## Peer Learning

The control plane now supports two peer-sharing layers:

- bulletins for lightweight promote/kill findings
- improvement bundles for code, evidence, and claimed outcomes

Improvement bundles are documented in [Flywheel_Improvement_Exchange.md](Flywheel_Improvement_Exchange.md). They are safe by construction: imports create local review packets and tasks, but they do not auto-apply peer code or auto-promote peer ideas into live capital.

## Federation Model

Forks do not share live control. They share bulletins.

- A fork exports recent `promote` and `kill` findings as a bulletin artifact.
- A peer imports that bulletin and converts it into local review tasks.
- The receiving fork decides what to test locally; it never auto-trades on peer claims.

This preserves search-space sharing without allowing one autonomous company to steer another one's live capital.

The cycle command is deterministic and sequential:

1. ingest snapshot payloads
2. evaluate strategy promotions
3. write promotion decisions
4. generate tasks
5. emit report artifacts

## Exit Criteria For MVP

The MVP is complete when:

1. strategy versions, deployments, snapshots, and promotion decisions persist in the database
2. one command runs a full sequential cycle end-to-end
3. the cycle generates scorecards, tasks, and promotion decisions
4. tests cover schema, policy evaluation, end-to-end cycle behavior, and hub command delivery
5. anomaly guardrails can auto-pause a runtime from stored snapshot history
6. a local 50-agent poisoned-update simulation shows robust aggregation outperforming naive averaging
