# BTC5 Market-Model Program

Status: active lane program
Last updated: 2026-03-11
Parent contract: `instance01_btc5_dual_autoresearch_contract.md`

## Purpose

Improve the BTC5 simulator and evaluator against a frozen benchmark epoch. This lane is about benchmark fidelity, not direct live-profit claims.

## Mutable Surface

- `btc5_market_model_candidate.py`

Only this file may be mutated inside the lane.

Allowed mutation families:

- feature interaction changes inside the candidate
- fill-model changes inside the candidate
- replay heuristics inside the candidate
- calibration or error-model changes inside the candidate
- deterministic refactors that preserve the evaluator contract

Forbidden mutations:

- `benchmarks/btc5_market/v1/manifest.json`
- the market scorer
- the market chart renderer
- ledger schema changes during the epoch
- live BTC5 runner code

## Immutable Evaluator

- Manifest: `benchmarks/btc5_market/v1/manifest.json`
- Ledger: `reports/autoresearch/btc5_market/results.jsonl`
- Public chart: `research/btc5_market_model_progress.svg`
- Truth inputs:
  - `reports/btc5_correlation_lab/latest.json`
  - `reports/runtime_truth_latest.json`
  - `data/btc_5min_maker.db` when present

The evaluator, manifest, dataset freeze, objective formula, and chart grammar are read-only for the full epoch.

## Objective

`simulator_loss = 0.40*pnl_window_mae_pct + 0.25*fill_rate_mae_pct + 0.20*side_brier + 0.15*p95_drawdown_mae_pct`

Lower is better.

## Experiment Unit

One experiment is one deterministic run of `btc5_market_model_candidate.py` against the frozen epoch benchmark with the fixed seed set from the manifest.

Every experiment must emit:

- one machine-readable result packet
- one append-only ledger row
- one keep, discard, or crash decision

## Keep, Discard, Crash

- `keep`: valid result packet and strictly lower `simulator_loss` than the current epoch frontier
- `discard`: valid result packet but no improvement over the current epoch frontier
- `crash`: candidate failure, evaluator failure, invalid packet, or fixed-seed replay mismatch

## Champion Rules

- The active market-model champion stays fixed for the full 24-hour epoch.
- A kept candidate becomes the pending frontier only.
- At the epoch boundary, the best kept candidate is rerun once on the same frozen harness.
- If that confirmation rerun matches, the candidate becomes the next epoch champion.
- If no kept candidate exists, or confirmation fails, carry the old champion forward.

## Safety Boundaries

- Do not let the evaluator mutate its own benchmark inside an epoch.
- Do not patch `config/btc5_strategy.env`, `state/btc5_autoresearch.env`, or live BTC5 runner code from this lane.
- Do not label a simulator benchmark win as a live BTC5 profit claim.
- Cached rows are valid fallback input when the DB is absent. DB-only enrichments are allowed only when the DB is present.
