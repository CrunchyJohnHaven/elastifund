# Elastic Stack Integration

This is the master guide for the Elastic layer in Elastifund.
It is both an operator guide and a public-messaging reference for the parts of the system that depend on Search AI, system memory, observability, evaluation, and workflow automation.

Elastic is not positioned here as a dashboard add-on.
It is the shared substrate that helps trading workers, JJ-N, and the publishing loop stay searchable, observable, and evidence-backed.

## Public-Safe Summary

These statements are safe to reuse in `README.md`, `/elastic/`, and related public docs:

- Elastic is the shared substrate for system memory, evaluation, observability, workflow automation, and publishing in Elastifund.
- Trading workers and JJ-N remain separate proof lanes, but both write into the same evidence layer.
- Public routes read sanitized checked-in artifacts and checked-in docs; they do not use direct browser access to private Elastic data in this pass.
- The default contribution posture is paper mode, explicit proof labels, and governed approvals.

## Why Elastic Fits Agentic AI In This Repo

The core problem in Elastifund is not just model selection.
The harder problem is keeping agent behavior grounded in durable context, measured outcomes, and operator-visible evidence.

Trading is the first proof lane because it provides fast feedback and hard outcomes.
It is not the whole product.
The broader opportunity is a self-improving operating system for many kinds of economic work, including non-trading workflows that more Elastic employees can reason about and improve directly.

Elastic fits that problem in five ways:

| Capability | Why it matters here |
|---|---|
| Search AI and context engineering | Agents need retrieval over prompts, reports, notes, outcomes, and telemetry instead of relying on short-lived local context. |
| System memory | Trading and non-trading workers need a shared history of artifacts, traces, decisions, and outcomes that can be searched later. |
| Agent observability | Operators need logs, metrics, traces, costs, and prompt-response visibility to understand where a worker is helping or degrading. |
| Evaluation | Promotion, pause, and blocked-claim decisions need evidence tied to outcomes, not blended dashboard sentiment. |
| Workflow automation | Recurring tasks, approvals, retries, and publishing loops need deterministic state and traceability. |

This framing aligns with Elastic's current public product language around the Search AI Platform, Agent Builder, LLM and agentic AI observability, and Workflow tools.

## What Elastic Does In Elastifund Today

The current repo story is deliberately concrete:

- Searchable artifacts: runtime snapshots, reports, prompts, notes, and public docs are treated as evidence surfaces that can be indexed, searched, and exported.
- Telemetry and traces: the bot emits JSON logs, latency events, and APM-compatible traces so operators can reconstruct the signal-to-order path.
- Operator dashboards: Kibana is the operator surface for signal quality, kill rules, order-book health, and runtime review.
- ML and anomaly hooks: Elastic ML is the planned and partially wired surface for abnormal VPIN, OFI, spread, signal-confidence drift, and kill-rule frequency.
- Publishing loop: the website, README, and route docs read sanitized checked-in artifacts so the public story stays tied to operator evidence without exposing private browser access.

This means Elastic is visible in two planes at once:

1. the operator plane, where raw telemetry, traces, and dashboards live
2. the public plane, where sanitized checked-in artifacts and docs summarize what is safe to publish

## Architecture Overview

```text
Market data, research inputs, CRM inputs, and runtime events
        |
        v
Trading workers + JJ-N + finance control plane
        |
        v
Elastic-backed evidence layer
  |--> searchable artifacts and notes
  |--> logs, metrics, traces, and costs
  |--> dashboards and anomaly jobs
  `--> evaluation and workflow state
        |
        v
Checked-in reports and public-safe artifacts
        |
        +--> README.md
        +--> /live/
        +--> /elastic/
        `--> numbered docs and public route copy
```

The key boundary is simple:
public routes read exports and checked-in artifacts, not the private operator plane directly.

## What The Shared Evidence Layer Enables

### Trading Workers

Trading workers generate signal state, latency, order-book context, fill outcomes, guardrail events, and promotion evidence.
Elastic gives those events a searchable trail instead of leaving them trapped in local logs.

### JJ-N

JJ-N generates prospect notes, sequence state, approval checkpoints, proposal artifacts, and outcome labels.
Those artifacts belong in the same memory and observability substrate even though their proof board is separate from trading.

### Publishing And Evaluation

The repo's public surfaces need freshness labels, blocked-claim language, source artifacts, and reviewable proof.
Elastic helps keep the underlying evidence searchable while checked-in artifacts provide the public-safe export layer.

## Public Messaging Guardrails

These rules keep `README.md`, `/elastic/`, and related docs aligned:

- Do not imply Elastic has endorsed or adopted this repo unless that is explicitly public and sourced.
- Do not imply the browser is reading private Elasticsearch or Kibana data directly.
- Do not use fake screenshots. Use real checked-in exports or clearly label diagrams as conceptual.
- Keep trading performance claims tied to checked-in artifacts such as `improvement_velocity.json` and runtime reports.
- Keep trading, forecasts, and JJ-N readiness as separate proof surfaces.
- Keep the tone calm, technical, and paper-mode safe.

## Core Components

| Component | Role In Elastifund |
|---|---|
| Elasticsearch | Search, storage, and evidence layer for signals, trades, notes, artifacts, logs, traces, and ML results. |
| Kibana | Operator surface for dashboards, Discover queries, saved searches, and anomaly review. |
| Filebeat | Ships ECS-style JSON logs from `/var/log/elastifund/` into Elasticsearch without coupling bot liveness to delivery. |
| APM Server | Accepts traces and spans from Python services so latency and failure points are visible by function, API call, and workflow step. |
| Elastic ML jobs | Detect abnormal VPIN, OFI, spread, signal confidence drift, and kill-rule frequency so the system can tighten posture earlier. |

## Setup Guide

The integration is intentionally simple to start up.
The goal is a local, single-node observability stack that can run on one VPS or a strong laptop without changing worker behavior.

1. Install Docker Engine or Docker Desktop and confirm both `docker` and `docker compose` work.
2. Review the Elastic infra files:
   - `infra/docker-compose.elastic.yml`
   - `infra/filebeat.yml`
   - `infra/apm-server.yml`
   - `infra/index_templates/`
3. Start the stack from the repo root:

```bash
bash infra/setup.sh
```

4. Wait for the health loop in `infra/setup.sh` to report that Elasticsearch is healthy.
5. Open Kibana at `http://127.0.0.1:5601`.
6. Pull the generated `elastic` password from the Docker logs, then store it outside the repo or in `.env`.
7. Set the worker-side environment variables when you want telemetry enabled:

```bash
ES_ENABLED=true
ES_HOST=127.0.0.1
ES_PORT=9200
ES_USER=elastic
ES_PASSWORD=...
APM_SERVER_URL=http://127.0.0.1:8200
APM_SERVICE_NAME=elastifund-bot
```

8. Start the bot or worker in paper or live mode as usual. The integration is designed so runtime behavior is unchanged if Elasticsearch is unavailable.
9. Import dashboards with `bot/elastic_dashboards.py` or Kibana Saved Objects once assets exist under `infra/kibana_dashboards/`.
10. Verify data flow in Kibana Discover by checking the four core indices:
   - `elastifund-trades`
   - `elastifund-signals`
   - `elastifund-kills`
   - `elastifund-orderbook`

## Operator Views

These are the main operator surfaces the Elastic layer is meant to support:

### Trading Overview

Use this to answer one question quickly: is the trading path behaving cleanly?
It should surface execution pace, realized hit rate, fill speed, and PnL drift without forcing the operator into raw documents first.

### Signal Quality

This is the truth surface for the core signal sources plus the anomaly lane.
It should answer which sources are confident, which sources are accurate, and which sources are being filtered out before capital is committed.

### Kill Rule Monitor

This is the safety surface.
Use it to understand whether the bot is approaching a forced pause, drifting into degraded behavior, or repeatedly tripping one protection rail.

### Orderbook Health

This is the market microstructure surface.
It is most useful on fast markets where maker-only execution depends on spread regime, queue health, and toxic-flow conditions.

### APM Overview

Use this to identify bottlenecks in the critical path.
If latency expands, this is where you determine whether the time was lost in LLM calls, exchange APIs, database writes, or internal orchestration.

### ML And Anomaly Review

This is the review surface for the anomaly consumer.
It should make clear when the system is reducing size, pausing markets, or flagging signal confidence drift because the distribution changed.

## Employee Contribution Path

For an Elastic employee or contributor, the recommended path is:

1. Read `/elastic/` for the high-level narrative.
2. Read `/live/` to inspect sanitized checked-in artifacts.
3. Use `README.md` or `docs/FORK_AND_RUN.md` for the repo run path.
4. Start in paper mode and inspect the evidence surfaces before proposing behavioral changes.

This keeps the project understandable without requiring private cluster access, live exchange keys, or access to a personal trading host.

## Performance Impact And Failure Behavior

The integration is built to fail soft:

- Elasticsearch writes are asynchronous bulk writes with bounded flush intervals, not synchronous per-event blocking calls.
- Calls into Elasticsearch or APM should be wrapped so a stack outage becomes an observability incident, not a worker crash.
- `ES_ENABLED` defaults to false, so the path is a no-op unless explicitly enabled.
- Filebeat decouples log shipping from worker execution.
- Elastic supports observability and evaluation; it does not replace the existing safety rails or the repo's checked-in source-of-truth docs.

## Known Limitations

- Elastic ML jobs need warm-up time and enough history to become useful.
- A single-node Elasticsearch deployment is appropriate for development and small-scale operator use, not for high-availability claims.
- Public routes are not live Elastic browsers in this pass. They are sanitized checked-in views over exported evidence.
- If log paths, credentials, or exporters are wrong, workers should continue to run, but dashboards and public exports will go stale. Treat stale observability as an operator incident.
