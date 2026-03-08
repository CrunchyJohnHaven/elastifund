# LLM Context Manifest
**Version:** 2.0.0
**Last Updated:** 2026-03-08
**Owner:** JJ (Elastifund Principal)
**Purpose:** Defines the canonical root-level LLM context package and the naming standard for keeping it current.

---

## Root Standard

1. Canonical root context docs use stable names with no version suffixes.
2. Update canonical files in place instead of minting new root filenames.
3. Superseded root variants move to `archive/root-history/`.
4. Root should hold only active LLM handoff docs and repo-wide standards.
5. If a file is useful but not current, archive it. If it is current, keep the stable canonical name.

---

## Canonical Root Context Set

| File | Role | Update Trigger |
|------|------|----------------|
| `CLAUDE.md` | JJ persona, operating rules, coding standards | Process or governance changes |
| `COMMAND_NODE.md` | Full project state and architecture | Every flywheel cycle |
| `PROJECT_INSTRUCTIONS.md` | Quick-start execution context | Priority or operating-mode changes |
| `DEEP_RESEARCH_PROMPT.md` | Current deep-research prompt | New research focus |
| `DEEP_RESEARCH_OUTPUT.md` | Wide strategy taxonomy source document | New long-form research output |
| `JJ_ASSESSMENT_DISPATCH.md` | JJ prioritization and kill decisions | New assessment memo |
| `EDGE_DISCOVERY_SYSTEM.md` | Validation pipeline and kill rules | Pipeline changes |
| `FAST_TRADE_EDGE_ANALYSIS.md` | Auto-generated fast-trade report | After each pipeline run |
| `KARPATHY_AUTORESEARCH_REPORT.md` | `autoresearch` benchmark discipline and loop-design notes | When learning-loop design changes |
| `LLM_CONTEXT_MANIFEST.md` | This standard and package contract | When package rules change |

---

## Default Packages

### Coding / implementation
- `CLAUDE.md`
- `COMMAND_NODE.md`
- `PROJECT_INSTRUCTIONS.md`
- `EDGE_DISCOVERY_SYSTEM.md`
- `FAST_TRADE_EDGE_ANALYSIS.md`

### Deep research / strategy discovery
- Coding package above
- `DEEP_RESEARCH_PROMPT.md`
- `JJ_ASSESSMENT_DISPATCH.md`
- `DEEP_RESEARCH_OUTPUT.md` only when broad strategy ideation matters

### Loop design / benchmark discipline
- Relevant package above
- `KARPATHY_AUTORESEARCH_REPORT.md`

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
| `DISPATCH_INSTRUCTIONS.md` | One-off task dispatch, not baseline context |
| `PARALLEL_TASK_MANIFEST.md` | Execution artifact, not canonical baseline context |
| `research/imports/WEATHER_BRACKET_VALIDATION_REPORT.md` | Dead-end validation already absorbed into backlog and autopsy docs |
| `research/edge_backlog_ranked.md` | Useful reference, but attach selectively to avoid context bloat |
| `FLYWHEEL_STRATEGY.md` | Strategic background, not default handoff context |

---

## Pre-Launch Checklist

- [ ] Canonical filenames are still stable and versionless at root
- [ ] Root does not contain newly created superseded copies
- [ ] `COMMAND_NODE.md`, `PROJECT_INSTRUCTIONS.md`, and `CLAUDE.md` agree on current status
- [ ] `FAST_TRADE_EDGE_ANALYSIS.md` reflects the latest pipeline run before quoting it
- [ ] Research attachments are chosen intentionally, not by dumping root into context

---

*If the manifest is stale, the LLM context is stale.*
