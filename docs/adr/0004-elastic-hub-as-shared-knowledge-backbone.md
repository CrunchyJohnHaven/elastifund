# ADR 0004: Use Elastic Stack as the Shared Knowledge and Observability Backbone

- Status: Proposed
- Date: 2026-03-07

## Context

The long-term Elastifund.io architecture needs one shared layer for:

- searchable strategy metadata
- time-series metrics
- vector similarity
- dashboards
- anomaly detection
- distributed observability

The repo now includes the first scaffold for that direction:

- `docker-compose.yml`
- `hub/app/main.py`
- `shared/python/elastifund_shared/topology.py`
- `docs/ELASTIFUND_IO_FOUNDATION.md`

## Decision

Use Elastic Stack as the central hub for shared knowledge, observability, and operator-facing visualization.

Planned responsibilities:

- Elasticsearch for strategy, knowledge, and metrics storage
- Kibana and Canvas for dashboards and executive views
- Elastic APM and related telemetry for distributed agent observability
- Elastic ML and vector capabilities for anomaly detection and semantic matching

The hub shares metadata, telemetry, and bounded knowledge artifacts. Exact model parameters, entry logic, and account-level sizing remain local to each spoke.

## Consequences

Positive:

- a unified platform story for search, analytics, observability, and ML
- less integration drag than stitching together several separate products
- a stronger internal pitch to Elastic leadership because every product line is load-bearing

Negative:

- more cluster operations work than the current SQLite-first MVP
- the repo will need stricter schema and lifecycle discipline as hub usage grows

## Follow-up

This ADR becomes fully accepted only after agent registration, shared telemetry ingestion, and real hub-backed dashboards are wired into the running system rather than just the scaffold.
