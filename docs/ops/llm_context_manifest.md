# LLM Context Manifest
**Version:** 2.0.0
**Last Updated:** 2026-03-08
**Owner:** JJ (Elastifund Principal)
**Purpose:** Defines the canonical LLM context package and the naming standard for keeping it current.

---

## Context Standard

1. Canonical entrypoint docs use stable names with no version suffixes.
2. Update canonical files in place instead of minting new root or near-root variants.
3. Superseded handoff variants move to `archive/root-history/`.
4. Root should hold only active session entrypoints, repo-wide standards, and compatibility files.
5. If a file is useful but not current, archive it. If it is current, keep the stable canonical path.

---

## Canonical Context Set

| File | Role | Update Trigger |
|------|------|----------------|
| `CLAUDE.md` | JJ persona, operating rules, coding standards | Process or governance changes |
| `COMMAND_NODE.md` | Full project state and architecture | Every flywheel cycle |
| `PROJECT_INSTRUCTIONS.md` | Quick-start execution context | Priority or operating-mode changes |
| `research/deep_research_prompt.md` | Current deep-research prompt | New research focus |
| `research/deep_research_output.md` | Wide strategy taxonomy source document | New long-form research output |
| `research/jj_assessment_dispatch.md` | JJ prioritization and kill decisions | New assessment memo |
| `docs/strategy/edge_discovery_system.md` | Validation pipeline and kill rules | Pipeline changes |
| `FAST_TRADE_EDGE_ANALYSIS.md` | Auto-generated fast-trade report | After each pipeline run |
| `research/karpathy_autoresearch_report.md` | `autoresearch` benchmark discipline and loop-design notes | When learning-loop design changes |
| `docs/ops/llm_context_manifest.md` | This standard and package contract | When package rules change |

---

## Default Packages

### Coding / implementation
- `CLAUDE.md`
- `COMMAND_NODE.md`
- `PROJECT_INSTRUCTIONS.md`
- `docs/strategy/edge_discovery_system.md`
- `FAST_TRADE_EDGE_ANALYSIS.md`

### Deep research / strategy discovery
- Coding package above
- `research/deep_research_prompt.md`
- `research/jj_assessment_dispatch.md`
- `research/deep_research_output.md` only when broad strategy ideation matters

### Loop design / benchmark discipline
- Relevant package above
- `research/karpathy_autoresearch_report.md`

---

## Archived Root History

| Path | Contents |
|------|----------|
| `archive/root-history/prompts/` | Superseded deep research prompt versions |
| `archive/root-history/requests/` | Superseded research request versions |
| `archive/root-history/dashboards/` | Replit dashboards and one-off root dashboards |
| `archive/root-history/` | Other retired root context files |
| `archive/imports/` | Imported binary docs and scratch source material |

---

## Excluded From Default LLM Context

| File or Path | Why Excluded |
|--------------|--------------|
| `archive/root-history/` | Historical only; not active context |
| `docs/ops/dispatch_instructions.md` | One-off task dispatch, not baseline context |
| `docs/ops/parallel_task_manifest.md` | Execution artifact, not canonical baseline context |
| `research/imports/WEATHER_BRACKET_VALIDATION_REPORT.md` | Dead-end validation already absorbed into backlog and autopsy docs |
| `research/edge_backlog_ranked.md` | Useful reference, but attach selectively to avoid context bloat |
| `docs/strategy/flywheel_strategy.md` | Strategic background, not default handoff context |

---

## Pre-Launch Checklist

- [ ] Canonical filenames and paths are still stable and versionless where intended
- [ ] Root is still limited to entrypoints, standards, and compatibility files
- [ ] `docs/` and `research/` do not contain newly created superseded copies
- [ ] `COMMAND_NODE.md`, `PROJECT_INSTRUCTIONS.md`, and `CLAUDE.md` agree on current status
- [ ] `FAST_TRADE_EDGE_ANALYSIS.md` reflects the latest pipeline run before quoting it
- [ ] Research attachments are chosen intentionally, not by dumping the repo root into context

---

*If the manifest is stale, the LLM context is stale.*
