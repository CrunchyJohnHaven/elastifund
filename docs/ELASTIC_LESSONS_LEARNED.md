# Elastic Lessons Learned

This file is the public log for what the Elastic integration teaches us. It is meant to stay honest. If a dashboard is noisy, if APM is less useful than expected, or if anomaly jobs produce junk before warm-up, write that down here.

## How To Use This Document

Add a short entry whenever the Elastic layer changes a decision, reveals a blind spot, or fails to deliver what we expected. Link to the supporting artifact when possible:

- Kibana dashboard export
- screenshot or saved object
- trace or latency panel
- incident or post-mortem
- code path that changed because of the finding

## Entry Template

```markdown
## [Date] — [Short title]

### What we expected

### What Elastic showed us

### Why it mattered

### What changed in the bot or in operations

### What did not work

### Evidence
- dashboard:
- trace:
- logs:
- code:
```

## Expected Learnings

These are hypotheses, not claims. They are here so we can later compare expectation to reality.

### 1. We expect to discover which signal sources degrade fastest

The six primary signal sources do not all fail the same way. The working expectation is that Elastic will make source-by-source drift visible earlier than manual review or notebook analysis.

What to watch:

- confidence falling while act-on rate stays flat
- source-specific calibration drift
- a sudden increase in `reason_skipped`
- divergence between signal quality and realized fills

### 2. We expect APM to reveal that LLM calls dominate the latency budget

The current hypothesis is that external model calls, not internal Python logic, are the largest contributor to end-to-end signal latency on slow markets.

What to watch:

- `llm_response_ms` versus local compute spans
- time spent in the full signal evaluation transaction
- whether debate rounds or multi-model ensemble calls are the main offenders

### 3. We expect ML anomaly detection to catch at least one event our static rules miss within the first week

This is the most ambitious claim in the integration. It needs evidence, not optimism.

What to watch:

- VPIN spikes that tighten sizing before a fill-quality deterioration event
- spread anomalies that justify pausing a market even when hard kill thresholds are not breached
- signal confidence drift that surfaces before humans would have noticed it

## First Empty Entries

## 2026-03-08 — Baseline before live Elastic history

### What we expected

Elastic should give us one operator surface for signals, trades, kills, order book state, and latency.

### What Elastic showed us

No production history yet. This is the baseline entry before dashboards and anomaly jobs have enough data to be judged.

### Why it mattered

Starting with an explicit baseline prevents us from rewriting history after the first useful dashboard or false alarm.

### What changed in the bot or in operations

The repo now has a dedicated documentation surface for the Elastic integration, Replit deployment guidance, and a public lessons-learned log.

### What did not work

Nothing to evaluate yet. The integration still needs runtime data.

### Evidence
- dashboard: `docs/ELASTIC_INTEGRATION.md`
- code: `bot/elastic_client.py`, `bot/apm_setup.py`, `bot/elastic_ml_setup.py`

## 2026-03-08 — Questions we need the first week to answer

### What we expected

The first week should tell us whether this stack is load-bearing or just more moving parts.

### What Elastic showed us

Pending.

### Why it mattered

If the answer is "nice screenshots, little decision value," we should say that plainly and trim the integration.

### What changed in the bot or in operations

Pending.

### What did not work

Pending.

### Evidence
- dashboard:
- trace:
- logs:
- code:
