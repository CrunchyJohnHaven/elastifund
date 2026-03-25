# Research Index

Purpose: make `research/` legible for both operators and LLM contributors without spelunking.

## Active Dispatches

Primary lane: [`research/dispatches/README.md`](dispatches/README.md)

Current active dispatch packet set:
- `research/dispatches/DISPATCH_097_competitive_inventory_benchmark_blueprint.md`
- `research/dispatches/DISPATCH_098_JJN_PARALLEL_INSTANCE_PLAN.md`
- `research/dispatches/DISPATCH_099_CLAUDE_CODE_btc_truth_surface_sync.md`
- `research/dispatches/DISPATCH_100_BTC5_VELOCITY_PARALLEL_PLAN.md`
- `research/dispatches/DISPATCH_101_DEEP_RESEARCH_INGESTION_20260311.md`
- `research/dispatches/DISPATCH_102_BTC5_truth_plumbing_and_execution_confidence.md`
- `research/dispatches/DISPATCH_113_HISTORICAL_DATA_PIPELINE_INGESTION.md`

## Current Assessment

Canonical assessment and current-state surfaces:
- `research/edge_backlog_ranked.md` (current ranked backlog + strategy posture)
- `research/jj_assessment_dispatch.md` (principal execution priorities)
- `research/btc5_arr_summary.md` (ARR status summary)
- `research/btc5_hypothesis_frontier_summary.md` (frontier summary)
- `research/high_frequency_substrate_phase2_blueprint_2026-03-11.md` (current structural-alpha build posture)

## Backlog And Ranking

- `research/edge_backlog_ranked.md` is canonical.
- Dispatch-level backlog inputs remain in `research/dispatches/` under `P0_`, `P1_`, `P2_`, and `P3_` prefixes.

## Autopsies

- `research/what_doesnt_work_diary_v1.md`

## Imported Research

- `research/imports/` holds third-party or external ingest material.
- `research/imports/deep_research_report_2026-03-23_btc5_probability_model.md` records the March 23 BTC5 probability-model and fill-conditioned maker-execution ingest.
- `research/imports/deep_research_report_2026-03-23_historical_data_pipeline.md` records the March 23 multi-venue historical-data pipeline ingest for Polymarket, Kalshi, and Alpaca.
- `research/deep_research_packets/` holds structured handoff/context packets.

## Unexecuted Prompt Lane

- Active legacy path: `research/UNEXECUTED_DEEP_RESEARCH_PROMPTS/`
- Note: on default macOS filesystems, the lowercase variant resolves to the same directory.

## History Pointers

- `research/history/README.md`
- `research/history/2026_q1_velocity_cleanup_wave1/README.md`

## Naming Conventions

- Canonical current-state files use lowercase `snake_case` where practical.
- Older mixed-case filenames remain as compatibility pointer stubs.
- Active dispatch files use `DISPATCH_<id>_<slug>.md` with one unique ID per file.
- Legacy dispatch files (`P0_`, `P1_`, `P2_`, `P3_`) are retained for historical traceability.
- Historical one-off plans and superseded deep-research handoffs belong under `research/history/`.

## Verification Helpers

- Run `python3 research/check_dispatch_ids.py` to enforce unique canonical `DISPATCH_<id>` values.
- Run `python3 research/check_pointer_stubs.py` to validate pointer files and canonical targets.
