# BTC5 Policy Autopromote Program

Status: active lane program
Last updated: 2026-03-11
Parent contract: `instance01_btc5_dual_autoresearch_contract.md`

## Purpose

Search BTC5 policy packages against the active market-model champion and autonomously update the live BTC5 package when a candidate is better and the machine safety gates are green.

## Mutable Surface

The mutable surface is one candidate package directory per experiment:

- `reports/autoresearch/btc5_policy/candidates/<candidate_policy>/`

The package directory may contain:

- `package.json`
- `strategy.env`

Only the package may change. The policy loop must not mutate live runner code directly.

Allowed mutation families:

- profile price caps
- delta caps
- session policy overrides
- package-level risk and routing settings already represented in JSON or env form

Forbidden mutations:

- `config/btc5_strategy.env`
- BTC5 live runner code
- rollout controller code during the search loop
- simulator scorer changes

## Immutable Evaluator

- Active simulator champion from the market-model lane
- Incumbent package truth from `reports/btc5_autoresearch/latest.json`
- Current probe truth from `reports/btc5_autoresearch_current_probe/latest.json`
- Runtime gate truth from `reports/runtime_truth_latest.json`
- Rollout truth from `reports/runtime/btc5/btc5_rollout_latest.json` when present
- Ledger: `reports/autoresearch/btc5_policy/results.jsonl`

Activation target:

- the controller writes the selected live package into `state/btc5_autoresearch.env`

The base file stays fixed:

- `config/btc5_strategy.env`

## Objective

`policy_loss = (-p05_30d_return_pct) + 0.25*(-median_30d_return_pct) + 2.0*loss_limit_hit_probability + 1.0*non_positive_path_probability + 0.05*p95_drawdown_pct`

Lower is better.

Required benchmark fields:

- `p05_30d_return_pct`
- `median_30d_return_pct`
- `loss_limit_hit_probability`
- `non_positive_path_probability`
- `p95_drawdown_pct`
- `fill_retention_ratio`

## Experiment Unit

One experiment is one candidate package scored against:

- the active simulator champion for the current epoch
- the current incumbent BTC5 package
- the current runtime safety snapshot

Every experiment must emit:

- one machine-readable evaluation packet
- one append-only ledger row
- one promotion decision

## Keep, Discard, Crash

- `keep`: valid evaluation packet, candidate beats incumbent `policy_loss` by at least `0.25`, improves median return, does not worsen p05 return, keeps `fill_retention_ratio >= 0.85`, and all non-posture safety interlocks are green
- `discard`: valid evaluation packet, but the candidate fails any benchmark gate or any non-posture safety interlock
- `crash`: invalid package, invalid evaluation packet, missing simulator champion, or failed rollback action

`launch_posture=blocked` is not a discard if the candidate otherwise qualifies. That case becomes a kept shadow champion with queued live activation.

## Promotion And Rollback

- If `launch_posture=clear`, a kept candidate is promoted live immediately.
- If `launch_posture!=clear`, a kept candidate becomes the shadow champion immediately and is queued for the first clear cycle.
- No human approval gate remains in steady state.
- Rollback is automatic on post-promotion underperformance or stale-health breach.
- Rollback restores the previous live package into `state/btc5_autoresearch.env` and appends a new ledger row.

## Safety Boundaries

- Safety interlocks are machine stops, not suggestions.
- A worse candidate can never overwrite the incumbent.
- The search loop cannot silently promote. Every promotion, queued activation, and rollback must leave an append-only audit record.
- Benchmark labels must stay separate from realized P and L labels.
