# Parallel Agent Workflow

This is the recommended way to use Codex and Claude Code together on Elastifund without stepping on the same files.

| Metadata | Value |
|---|---|
| Canonical file | `docs/PARALLEL_AGENT_WORKFLOW.md` |
| Role | Parallel ownership and handoff contract |
| Start Here path | `README.md` -> `docs/FORK_AND_RUN.md` |
| Operator packet | `COMMAND_NODE.md` |
| Last updated | 2026-03-11 |

## Root Cross-Reference (Canonical)

| Need | Canonical file |
|---|---|
| Start Here | `docs/FORK_AND_RUN.md` |
| Operator packet | `COMMAND_NODE.md` |
| Operator policy | `PROJECT_INSTRUCTIONS.md` |
| Machine workflow guardrails | `AGENTS.md` |
| Contribution rules | `CONTRIBUTING.md` |

## The Goal

Parallel work should increase throughput, not create merge archaeology. The repo is large enough for true parallelism, but only if ownership is explicit.

Before splitting work, load `AGENTS.md` for file ownership and `COMMAND_NODE.md` for active context and source precedence.

## Best Split

| Role | Best at | Typical Elastifund lanes |
|---|---|---|
| Codex | focused implementation, test repair, targeted refactors | `bot/`, `execution/`, `strategies/`, `signals/`, `nontrading/finance/`, isolated bug fixes |
| Claude Code | repo reconnaissance, large-context synthesis, documentation, rollout coordination | `docs/`, `research/`, `deploy/`, `hub/`, finance-policy packaging |

Use the split that matches the work, not the branding. If Claude Code is already holding the implementation context for one subsystem, let it keep that lane. The important part is one owner per file.

## Default Pattern

1. One agent maps the problem and splits it by directory or deliverable.
2. Codex takes the narrowest code path with the highest chance of deterministic progress.
3. Claude Code takes the broader doc, ops, or multi-file synthesis lane.
4. One agent closes the loop by running verification and producing the final summary.

## Safe Parallel Boundaries

Good splits:

- Codex: `bot/` execution fix
- Claude Code: `docs/` update + release notes

- Codex: `polymarket-bot/src/` regression fix
- Claude Code: root onboarding docs and `docs/api/`

- Codex: `nontrading/` implementation or test repair
- Claude Code: launch/status docs and rollout packaging

- Codex: `nontrading/finance/` truth layer, allocator, or executor work
- Claude Code: `docs/ops/finance_control_plane.md`, metrics contract, and rollout brief

- Codex: `signals/` or `strategies/` implementation
- Claude Code: `research/dispatches/` and evidence write-up

Bad splits:

- both agents editing the same `README.md`
- both agents splitting `nontrading/finance/` and its policy docs without explicit file ownership
- both agents touching the same strategy module
- one agent changing runtime behavior while the other rewrites tests for the same path

## Handoff Contract

Every handoff should include:

- what changed
- which files were touched
- which commands were run
- what remains unverified
- whether the next agent can edit the same files or should stay out

Short beats vague. A six-line handoff is enough if it is precise.

## Sync Points

Use these as the standard checkpoints:

```bash
make hygiene
make test
make test-polymarket
```

If the task is narrow, run the narrow test first, then the broader suite before pushing.

## Branch Strategy

If both agents are working in the same workspace:

- use one shared branch
- assign file ownership explicitly
- avoid simultaneous edits in the same path

If the agents are working in separate clones or forks:

- one branch per workstream
- merge only after the verification owner reruns the shared checks

## Recommended Task Bundles

| Codex bundle | Claude Code bundle |
|---|---|
| fix failing tests in `bot/` | rewrite root onboarding docs |
| patch `polymarket-bot/src/` regressions | refresh API/deploy docs |
| push `nontrading/` toward a runnable milestone | refine launch docs and status reporting |
| implement the finance truth / allocator / executor path | lock the finance policy contract and operator docs |
| implement one strategy or signal lane | dispatch planning and research packaging |
| tighten small scripts and make targets | contributor guidance and release packaging |

## Definition Of Done

A parallel pass is done when:

- the touched files have a single coherent story
- the verification commands pass
- the repo docs point new contributors to the right path
- another agent can enter cold and understand what changed without reverse-engineering the whole tree
