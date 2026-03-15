# Elastifund.io Foundation

This document captures the first infrastructure slice for the broader Elastifund.io architecture.

## Honest framing

The platform is designed around supervised automation, not magical autonomy. In March 2026 the realistic claim is:

- prediction-market execution can be partially automated
- digital product generation can be partially automated
- shared learning infrastructure can improve selection and monitoring
- human oversight is still required for capital, compliance, and quality control

## Additive monorepo scaffold

The repo now includes four top-level lanes for the dual-agent platform:

- `hub/` for central coordination services
- `agent/` for forkable spoke templates
- `shared/` for common Python helpers and topology definitions
- `deploy/` for Docker Compose support assets and starter Kubernetes manifests

This scaffold does not replace the current live trading system. It creates a clean path to layer the hub-and-spoke platform on top of the existing codebase.

## Local hub stack

The root `docker-compose.yml` brings up:

- Elasticsearch with security and API-key support enabled
- a one-shot setup container that sets the `kibana_system` password
- Kibana
- Kafka in KRaft mode
- Redis
- a FastAPI gateway for hub topology, health, and API-key minting

## What this instance does not claim

This foundation does not yet include:

- Elastic-backed agent registration and heartbeat indexing
- federated learning rounds
- strategy embeddings or vector search
- capital allocation logic
- trading or Etsy execution against the hub

What exists today:

- one shared FastAPI gateway surface for benchmark APIs plus agent registration and heartbeats
- filesystem-backed registry state for local bootstrap flows

Those capabilities are enough for local coordination, but not yet the final Elastic-native hub.
