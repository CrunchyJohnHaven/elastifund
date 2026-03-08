# Flywheel Incentive System

**Status:** implemented MVP  
**Last Updated:** 2026-03-07

## Purpose

This is the Phase 9 incentive layer for Elastifund's flywheel. It is intentionally utility-only:

- no pooled-return promises
- no token issuance
- no automatic profit sharing

The system rewards useful work and verified performance with reputation points, then uses those points for bounded governance and feature prioritization.

## Core Objects

1. Contributor profiles  
   Persistent records keyed by `contributor_key`, with reputation totals, category breakdowns, tier, unlocks, and voice-credit budget.

2. Reputation events  
   Immutable point deltas tied to evidence. Supported categories:
   - `code_contribution`
   - `strategy_performance`
   - `bug_report`
   - `documentation`
   - `peer_review`

3. Funding rounds  
   Quadratic-funding rounds with a USD matching pool, proposals, and voice-credit allocations.

4. Funding proposals  
   Concrete build requests such as new agent templates, dashboards, or research tooling.

## How Points Are Awarded

- GitHub-style contribution scoring:
  based on merged PRs, files changed, lines changed, issues linked, and review resolution.
- Verified strategy performance:
  based on the latest stored flywheel snapshot and promotion decision.
- Manual or automated awards:
  for peer review, bug reports, or other contribution evidence.

All awards are stored as immutable `reputation_events`. Contributor totals are recomputed from those events, not edited directly.

## Unlocks

Current unlocks are deliberately simple:

- `leaderboard_bronze` at 50 points
- `leaderboard_silver` at 150 points
- `leaderboard_gold` at 300 points
- `governance_voting` at 100 points
- `priority_agent_templates` at 250 points plus 100 code points

The system also derives contributor tiers:

- `seed`
- `contributor`
- `builder`
- `operator`
- `steward`

## Quadratic Funding

Each contributor gets a bounded voice-credit budget derived from reputation:

```text
voice_credit_budget = clamp(sqrt(reputation_points) * 4, 10, 100)
```

Each proposal's score is:

```text
quadratic_score = (sum(sqrt(voice_credits_i)))^2
matching_units = max(quadratic_score - direct_voice_credits, 0)
```

The matching pool is then split in proportion to `matching_units`, which means broad support beats concentrated support.

## CLI

Award a manual event:

```bash
python -m data_layer flywheel-reputation-award \
  --contributor-key alice \
  --display-name "Alice" \
  --event-type documentation \
  --points 55 \
  --source-kind manual \
  --source-ref docs-landing-page
```

Award GitHub-style contribution points:

```bash
python -m data_layer flywheel-reputation-award-github \
  --contributor-key alice \
  --github-handle alice-dev \
  --contribution-type code_contribution \
  --merged-prs 2 \
  --files-changed 8 \
  --lines-changed 600 \
  --source-ref https://github.com/org/repo/pull/42
```

Award verified strategy-performance points:

```bash
python -m data_layer flywheel-reputation-award-performance \
  --contributor-key jj \
  --strategy-key wallet-flow \
  --version-label wf-20260307
```

Show the leaderboard:

```bash
python -m data_layer flywheel-reputation-leaderboard --limit 20
```

Run a funding round:

```bash
python -m data_layer flywheel-funding-create-round \
  --round-key phase9 \
  --title "Phase 9 Incentives" \
  --matching-pool-usd 1000

python -m data_layer flywheel-funding-submit-proposal \
  --round-key phase9 \
  --proposal-key shared-hub \
  --title "Shared Knowledge Hub" \
  --description "Ship the stake-weighted knowledge hub dashboards."

python -m data_layer flywheel-funding-vote \
  --round-key phase9 \
  --proposal-key shared-hub \
  --contributor-key alice \
  --voice-credits 6

python -m data_layer flywheel-funding-tally --round-key phase9 --close-round
```

## Safety Notes

- Reputation is utility-only and does not represent ownership.
- Voice-credit budgets are capped to avoid whale capture.
- Verified performance awards rely on stored flywheel evidence, not unverifiable claims.
- The funding mechanism prioritizes what the community should build next, not who receives trading profits.
