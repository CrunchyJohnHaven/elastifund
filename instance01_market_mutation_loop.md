# Instance 01 Market Mutation Loop

Status: complete
Date: 2026-03-11
Project: BTC5 Karpathy-style autoresearch finish line

## Outcome

The BTC5 market lane already had the required mutation-cycle implementation in the worktree, so this pass validated it against the Instance 1 acceptance contract and left the lane intact.

## What Is Landed

- `scripts/run_btc5_market_model_autoresearch.py` runs a full proposer-plus-evaluator cycle against frozen `benchmarks/btc5_market/v1/manifest.json`.
- The only mutable market surface remains `btc5_market_model_candidate.py`.
- Each cycle loads the current champion plus recent discards and crashes, proposes one candidate in a temp workspace, benchmarks that proposal, and overwrites the canonical mutable surface only on a keep.
- Proposal metadata is persisted through the proposal JSON, benchmark packet, latest summary, champion registry, and append-only ledger:
  - `proposal_id`
  - `parent_champion_id`
  - `proposer_model`
  - `estimated_llm_cost_usd`
  - `mutation_summary`
  - `mutation_type`
- `scripts/run_btc5_market_model_mutation_cycle.py` exists as the stable AWS-safe entrypoint for one supervised market mutation cycle.

## Acceptance Notes

- Keep-only overwrite is enforced. Discards and crashes leave `btc5_market_model_candidate.py` unchanged.
- The market ledger remains append-only at `reports/autoresearch/btc5_market/results.jsonl`.
- Null-result nights remain explicit via discard records instead of silent success.
- The Karpathy chart contract remains unchanged at `research/btc5_market_model_progress.svg`.

## Verification

```bash
pytest -q tests/test_btc5_market_model_benchmark.py tests/test_run_btc5_market_model_autoresearch.py tests/test_render_btc5_market_model_progress.py
```

Result: `6 passed in 0.77s`

## Follow-On Boundary

- Instance 1 is ready for the shared budget, outcome-surface, and overnight-gate work handled in later instances.
- No additional market-lane code changes were required in this pass beyond validation and handoff.
