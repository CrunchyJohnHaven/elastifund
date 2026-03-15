# LLM Context Manifest

Status: canonical index
Version: 3.0.0
Last updated: 2026-03-11
Category: canonical index
Canonical: yes
Purpose: define active LLM context surfaces and separate them from historical prompt/dispatch artifacts

## Active Canonical Surfaces

| File | Purpose |
|---|---|
| `CLAUDE.md` | Agent behavior contract |
| `COMMAND_NODE.md` | Active session context and source-precedence contract |
| `PROJECT_INSTRUCTIONS.md` | Current operator priorities |
| `AGENTS.md` | Machine-first entrypoint and guardrails |
| `docs/REPO_MAP.md` | Path ownership and routing |
| `docs/ops/CODEX_PLANNING_PROMPT.md` | Reusable planning prompt template |
| `docs/numbered/08_PROMPT_LIBRARY.md` | Prompt-governance rules |

## Historical (Non-Canonical) Prompt/Plan Artifacts

| File | Handling rule |
|---|---|
| `CODEX_DISPATCH.md` | Historical snapshot only; do not use for active planning |
| `CODEX_MASTER_PLAN.md` | Historical snapshot only; do not use for active planning |
| `docs/ops/dispatch_instructions.md` | Historical snapshot only; do not use for active planning |

## Context Pack Selection

### Focused implementation
- `AGENTS.md`
- `docs/REPO_MAP.md`
- `COMMAND_NODE.md`
- Task-owned path docs only

### Orchestration and synthesis
- `CLAUDE.md`
- `COMMAND_NODE.md` (as session packet)
- `PROJECT_INSTRUCTIONS.md`

### Prompt and workflow cleanup
- `COMMAND_NODE.md`
- `docs/ops/CODEX_PLANNING_PROMPT.md`
- `docs/numbered/08_PROMPT_LIBRARY.md`

## Naming Contract

- `*_PROMPT*.md`: reusable templates
- `*Context*.md`: active context packets
- `*DISPATCH*.md`: situational dispatch artifacts
- `*PLAN*.md`: cycle/scenario plans

Do not mix these roles in a single file.

## Maintenance Checklist

- Verify active/historical labels are still accurate
- Keep `CLAUDE.md` behavior-only
- Keep runtime posture in machine artifacts and `COMMAND_NODE.md`
- Pointerize dated plan/dispatch files instead of treating them as canonical
