# Agent Template

This directory is the scaffold for future Elastifund spoke agents.

Use it when you want a new agent process that can:

- load the shared `.env` contract cleanly
- talk to the hub gateway
- heartbeat into the registry
- adopt the same operational defaults as the rest of the repo

## What Belongs Here

- shared agent bootstrapping code
- environment parsing for agent identity and hub connectivity
- default heartbeat and retry behavior
- topic subscription defaults for future message-bus consumers

## What Does Not Belong Here

- strategy-specific trading logic
- one-off experiments
- duplicate copies of code that should live under `shared/` or `hub/`

## Expected Next Steps

1. Add a reusable `ElastifundAgent` base class.
2. Add registration and heartbeat reporting.
3. Split specialized agents into trading and non-trading subclasses.

## Related Docs

- [README.md](../../README.md)
- [docs/FORK_AND_RUN.md](../../docs/FORK_AND_RUN.md)
- [docs/PARALLEL_AGENT_WORKFLOW.md](../../docs/PARALLEL_AGENT_WORKFLOW.md)
