# Codex Dispatch Index — March 9, 2026

**Source truth:** COMMAND_NODE.md v2.8.0 | PROJECT_INSTRUCTIONS.md v3.8.0
**Machine state:** 305 cycles, 0 live trades, 0% realized current system ARR, REJECT ALL, 1,278 tests green

---

## Recommended Dispatch Order

| Order | Instance | File | Dependencies | Est. Duration | Priority |
|-------|----------|------|-------------|---------------|----------|
| 1 | #4 VPS Deploy & Manifest Fix | INSTANCE_4_VPS_DEPLOYMENT.md | None (unblocks dry-runs) | 15 min | CRITICAL |
| 2 | #6 Data Pipeline Refresh | INSTANCE_6_DATA_PIPELINE.md | None | 10 min | HIGH |
| 3 | #1 Edge Scanner | INSTANCE_1_EDGE_SCANNER.md | None (benefits from #6 fresh data) | 15 min | HIGH |
| 4 | #7 JJ-N Foundations | INSTANCE_7_JJN_FOUNDATIONS.md | None | 30 min | HIGH |
| 5 | #8 Governance Scaffold | INSTANCE_8_GOVERNANCE_SCAFFOLD.md | None | 25 min | MEDIUM |
| 6 | #2 Website Build | INSTANCE_2_REPLIT_WEBSITE.md | Best after #1 + #7 (for fresh numbers + JJ-N content) | 20 min | MEDIUM |
| 7 | #5 GitHub Velocity | INSTANCE_5_GITHUB_VELOCITY.md | Best after #3 + #7 (for updated metrics) | 10 min | MEDIUM |
| 8 | #3 Command Node Sync | INSTANCE_3_COMMAND_NODE.md | LAST — reads handoffs from all others | 15 min | CRITICAL (final) |

---

## Parallel Groups

**Group A (dispatch immediately, no dependencies):**
- Instance #4 — VPS Deploy & Manifest Fix
- Instance #6 — Data Pipeline Refresh
- Instance #7 — JJ-N Foundations
- Instance #8 — Governance Scaffold

**Group B (dispatch after Group A, or in parallel if acceptable):**
- Instance #1 — Edge Scanner (benefits from #6 data but can run independently)
- Instance #2 — Website Build (benefits from #1 + #7 results)
- Instance #5 — GitHub Velocity (benefits from updated metrics)

**Group C (dispatch last):**
- Instance #3 — Command Node Sync (reads all handoff artifacts, writes v2.9.0)

---

## File Ownership Boundaries

| Instance | Owns (read-write) | Reads (read-only) |
|----------|-------------------|-------------------|
| #1 Edge Scanner | bot/, execution/, strategies/, signals/, reports/ | PROJECT_INSTRUCTIONS, CLAUDE.md, edge_backlog |
| #2 Website | index.html, REPLIT_NEXT_BUILD.md, website sources | CLAUDE.md, README, FAST_TRADE, vision docs |
| #3 Command Node | COMMAND_NODE, PROJECT_INSTRUCTIONS, CLAUDE.md (state), docs/, README, AGENTS, REPO_MAP | reports/, all handoff artifacts |
| #4 VPS Deploy | deploy/, config/, Makefile (deploy), .github/workflows/, reports/deploy_* | CLAUDE.md, bot/ (read mode) |
| #5 GitHub Velocity | .github/, improvement_velocity.*, README (charts section), nontrading/ | CLAUDE.md, velocity_maker_strategy, edge_backlog |
| #6 Data Pipeline | src/, backtest/, data/, data_layer/, reports/, FAST_TRADE_EDGE_ANALYSIS.md | PROJECT_INSTRUCTIONS, edge_discovery_system |
| #7 JJ-N Foundations | nontrading/, tests/nontrading/, infra/ (non-trading templates) | vision docs, COMMAND_NODE (architecture sections) |
| #8 Governance | docs/numbered/ (new), scripts/lint_messaging.py, docs/REPO_MAP.md | COMMAND_NODE, vision docs, CLAUDE.md, PROJECT_INSTRUCTIONS, diary/ |

---

## Today's Mission Per Instance

| Instance | Specific March 9 Mission |
|----------|-------------------------|
| #1 | Determine if lowering thresholds to 0.08/0.03 unlocks any tradeable markets. Answer: "How many trades does aggressive unlock?" |
| #2 | Get the website aligned with vision messaging. Homepage hero must say "self-improving agentic OS." Add JJ-N section. Stub new routes. |
| #3 | Read all handoff artifacts from instances 1-8 and produce COMMAND_NODE v2.9.0 with every number reconciled. |
| #4 | Fix the blocked_safe.yaml→.json manifest mismatch. Confirm service mode. Get the dry-run passing. |
| #5 | Push to GitHub. Generate velocity chart with 1,278 tests, 305 cycles, 131 strategies. Include JJ-N status. |
| #6 | Pull fresh Polymarket data. Run threshold sensitivity. Answer: "Is the market universe any different from the last REJECT ALL?" |
| #7 | Build Phase 0 JJ-N: CRM schema, opportunity registry, five engine stubs, approval gates, telemetry. Target 25+ new tests. |
| #8 | Create all 13 numbered root documents with substantive content from existing sources. Build messaging lint. |

---

## Handoff Contract

Every instance MUST produce a handoff block at completion:

```
INSTANCE #N HANDOFF
---
Files changed: [list]
Commands run: [list]
Key findings: [1-3 sentences]
Numbers that moved: [before→after]
Unverified: [anything next cycle should check]
Next instance can edit these files: [yes/no per file]
```

Instance #3 (Command Node Sync) reads all handoff blocks and reconciles them into COMMAND_NODE v2.9.0.
