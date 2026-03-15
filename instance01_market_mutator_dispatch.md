# Instance 01 Market Mutator Dispatch

Status: delivered
Date: 2026-03-11
Project: BTC5 Dual Autoresearch

## Scope

- Replaced the evaluator-only BTC5 market lane with a mutation cycle runner in `scripts/run_btc5_market_model_autoresearch.py`.
- Kept the autonomous mutation surface constrained to `btc5_market_model_candidate.py`.
- Preserved the existing keep/discard/crash ledger and Karpathy-style chart contract.

## What Changed

- The market lane now reads the current champion, recent discards, recent crash packets, and the frozen manifest before each run.
- Each run generates one proposal candidate in a temp workspace, persists the candidate snapshot plus proposal JSON, benchmarks that proposal against the frozen market manifest, and only overwrites the canonical mutable surface when the proposal is kept.
- Proposal metadata is now append-only across the lane ledger, proposal packet, benchmark packet, latest summary, and champion registry.
- The mutable candidate file now exposes a structured `MUTATION_SURFACE` block so the runner can mutate only model hyperparameters inside the allowed file.

## Proposal Metadata

Every market run now records:

- `proposal_id`
- `parent_champion_id`
- `proposer_model`
- `proposer_tier`
- `estimated_llm_cost_usd`
- `mutation_summary`
- `mutation_type`
- `mutable_surface_sha256_before`
- `mutable_surface_sha256_after`

Per-run artifacts now include:

- proposal source snapshot: `reports/autoresearch/btc5_market/packets/experiment_XXXX_candidate.py`
- proposal context and metadata JSON: `reports/autoresearch/btc5_market/packets/experiment_XXXX_proposal.json`
- benchmark packet JSON and markdown: `reports/autoresearch/btc5_market/packets/experiment_XXXX.json|md`

## Tiering And Budget

- Default proposer tier: `heuristic_market_routine_v1`
- Escalated proposer tier: `heuristic_market_expensive_v1`
- Escalation triggers:
  - `10` consecutive discards
  - `24` hours without a keep
- Daily proposer budget contract: `$10/day`
- When the preferred tier would exceed the daily budget, the lane falls back to a zero-cost budget-safe proposer label instead of mutating the canonical surface blindly.

## Acceptance Notes

- A proposal cannot overwrite `btc5_market_model_candidate.py` without beating the incumbent loss frontier.
- Discards and crashes leave the canonical mutable surface unchanged.
- Kept champions now point policy replay at the persisted proposal snapshot, not a drifting future mutable file.
- The progress chart still renders from `reports/autoresearch/btc5_market/results.jsonl` without format changes to its keep/discard/crash grammar.

## Verification

- `python3 -m py_compile scripts/run_btc5_market_model_autoresearch.py btc5_market_model_candidate.py benchmarks/btc5_market/v1/benchmark.py tests/test_run_btc5_market_model_autoresearch.py`
- `python3 -m pytest tests/test_btc5_market_model_benchmark.py tests/test_run_btc5_market_model_autoresearch.py tests/test_render_btc5_market_model_progress.py`
- `python3 -m pytest tests/test_run_btc5_policy_autoresearch.py tests/test_btc5_dual_autoresearch_ops.py`
- `python3 -m pytest tests/test_btc5_dual_autoresearch_e2e_integration.py`

## Follow-On Boundary

- Instance 1 is complete.
- I did not start Instance 2, 3, or 4 code changes in this turn.
- The full 51-test autoresearch proof suite remains deferred to the wave where Instances 1 through 3 are all landed together, matching the stated test plan.
