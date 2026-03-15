# Contributing to Elastifund

Elastifund is an open-source trading and revenue-automation lab. Contributions are welcome, but this repo holds a higher bar than a typical side project because it touches live-money workflows, public performance claims, and compliance-sensitive automation.

## Working Rules

- Be explicit about what is live, what is paper, what is backtest, and what is research.
- Do not commit secrets, wallet addresses, API credentials, or raw live trade data.
- Prefer measured evidence over theory. If a change affects signal quality, execution, or risk, include tests, data, or a clear validation path.
- Keep the public repo educational without leaking deploy-time edge settings or operational secrets.
- Treat kill switches, exposure caps, and compliance rails as product features, not obstacles.

## First Read

Before making large changes, read these:

1. `README.md`
2. `AGENTS.md`
3. `docs/PARALLEL_AGENT_WORKFLOW.md`
4. `docs/REPO_MAP.md`

If you only want the beginner-friendly boot path, use [docs/FORK_AND_RUN.md](docs/FORK_AND_RUN.md).

## Local Setup

Use one shared virtualenv from the repo root for day-to-day development:

```bash
python3 scripts/doctor.py
python3 -m venv .venv
source .venv/bin/activate
make bootstrap
python3 scripts/quickstart.py --prepare-only
make verify
```

This bootstrap covers the repo-root suites, `edge-backlog/tests`, simulator YAML support, and the runtime dependencies used by `polymarket-bot/tests`.

Do not editable-install `polymarket-bot/` into the shared env. That subproject publishes a top-level `src` package, so keeping it uninstalled avoids namespace collisions with the repo root while still letting you run its tests from inside `polymarket-bot/`.

If you want the full local stack:

```bash
docker compose up --build
```

## Testing Expectations

Run the narrowest relevant checks first, then the broader suite before opening a PR.

Common examples:

```bash
make hygiene
make test
make test-polymarket
python -m pytest data_layer/tests
python -m pytest orchestration/tests
python -m pytest hub/tests
python -m pytest edge-backlog/tests
python3 -m data_layer flywheel-cycle --input docs/examples/flywheel_cycle.sample.json --artifact-dir reports/flywheel/local-smoke --json
python3 -m nontrading.digital_products.main --run-once --source-file nontrading/tests/fixtures/sample_product_niches.json --top 3
```

If you skip a meaningful check, say so in the PR and explain why.

## Parallel Codex / Claude Code Work

This repo is intentionally organized so two coding agents can work in parallel, but only with explicit path ownership.

Recommended split:

- Codex: narrow implementation and test repair
- Claude Code: repo-wide synthesis, docs, dispatches, rollout packaging

Use [docs/PARALLEL_AGENT_WORKFLOW.md](docs/PARALLEL_AGENT_WORKFLOW.md) as the contract. If two agents need the same file, stop parallelizing and hand ownership to one of them.

## Contribution Lanes

Useful contributions include:

- bug fixes with tests
- execution-quality and risk-control improvements
- non-trading pipeline improvements with compliance guardrails intact
- reporting and documentation improvements
- reproducible backtests, simulations, or validation work
- research writeups that sharpen or kill a hypothesis

Negative results are valuable here. A clear failure with good methodology is better than a hand-wavy success claim.

## Pull Request Checklist

Before opening a PR:

- Keep the scope focused.
- Describe whether the change affects live trading, paper trading, backtesting, non-trading automation, hub infrastructure, or docs only.
- Add or update tests when behavior changes.
- Include evidence paths for strategy or risk changes.
- Confirm no secrets, raw live data, or unpublished live coefficients were added.
- Confirm every commit is signed off with `git commit -s`.

## Strategy And Risk Changes

Changes that touch trading logic, allocators, or safety rails need extra care:

- explain the hypothesis
- explain the failure mode
- show the validation path
- call out any changed thresholds, exposure limits, or kill conditions

Do not silently widen risk limits in the name of convenience.

## Research Submissions

Good research submissions usually include:

- the hypothesis
- the target market or lane
- why it might work
- how it was tested
- what survived or failed
- what the next gating decision should be

Writeups can live in `research/`, `docs/strategy/`, or `docs/ops/` depending on audience.

## Developer Certificate Of Origin

Every commit must be signed off under the Developer Certificate of Origin in [DCO.md](DCO.md).

Use Git’s sign-off flag:

```bash
git commit -s -m "Add hub API docs"
```

That appends a line like:

```text
Signed-off-by: Your Name <you@example.com>
```

Do this for every commit in the PR, not just the last one.

## Mission

Twenty percent of net profits are reserved for veteran suicide prevention. That commitment is part of the project’s identity, but it is not an extra legal term imposed on contributors.
