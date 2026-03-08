# Context Package Manifest — Deep Research Runs
**Version:** 1.1.0
**Last Updated:** 2026-03-07
**Owner:** JJ (Elastifund Principal)
**Purpose:** Defines EXACTLY which files to attach to each Deep Research run.

---

## THE RULE

Every Deep Research run gets EXACTLY the documents listed below. Extra documents dilute context. Missing documents waste researcher time on rediscovery.

**Before launching:** check this manifest.
**After any state change:** update this manifest.

---

## CURRENT PACKAGE (v1.1.0 — Combinatorial Arb GO/NO-GO)

### TIER 1: ALWAYS INCLUDE (Core Context)

| # | File | Actual Size | Content Summary | Update Trigger |
|---|------|-------------|-----------------|----------------|
| 1 | `DEEP_RESEARCH_PROMPT_v6.md` | 14KB | **THE PROMPT.** Research questions for A-6/B-1 GO/NO-GO. | Every new research focus |
| 2 | `CLAUDE.md` | 9KB | JJ persona, coding standards, current state. | Process changes only |
| 3 | `ProjectInstructions.md` | 14KB | Sprint plan, risk parameters, architecture summary, priority queue. | When priorities change |
| 4 | `docs/REPO_MAP.md` | 5KB | Canonical repo map, directory ownership, and coding-session entrypoints. | When repo layout changes |
| 5 | `EDGE_DISCOVERY_SYSTEM.md` | 8KB | Kill rules, hypothesis testing pipeline, validation criteria. | When pipeline changes |
| 6 | `FastTradeEdgeAnalysis.md` | 7KB | Current pipeline results (REJECT ALL). Reality check. | After every pipeline run |

### TIER 2: FOCUS-SPECIFIC

| # | File | Actual Size | Why Needed | Remove When |
|---|------|-------------|------------|-------------|
| 7 | `JJ_ASSESSMENT_DISPATCH_v3.md` | 7KB | Prioritization decisions, pre-rejected strategies, execution timeline. Prevents researcher from recommending dead strategies. | When new assessment supersedes it |

### TOTAL: 7 FILES, ~64KB

---

## KEY CHANGE FROM v1.0.0

**Dropped `DEEP_RESEARCH_OUTPUT_v3.md` (178KB).** The v1.0.0 manifest listed this at "~50KB" — the actual size is 178KB (~45K tokens). Only ~600 words of it (A-6 and B-1 strategy specs) are relevant to the current research run. Those specs are now inlined directly into the v6 prompt. This single change cuts the context package by 61% (290KB down to 104KB) with zero information loss for this task.

---

## DOCUMENTS EXPLICITLY EXCLUDED

| File | Why Excluded |
|------|-------------|
| `DEEP_RESEARCH_OUTPUT_v3.md` | 178KB. Relevant content (A-6/B-1 specs) inlined into v6 prompt. The other 98 strategies are noise for this run. |
| legacy `DEEP_RESEARCH_PROMPT` versions (v1-v5) | All superseded by v6. |
| `DISPATCH_INSTRUCTIONS.md` | One-time dispatch tasks. Not research context. |
| legacy Replit dashboard spec | Website spec. Include only for website-focused research. |
| `WEATHER_BRACKET_VALIDATION_REPORT.md` | NO-GO verdict already reflected in backlog. Dead end. |
| `FLYWHEEL_STRATEGY.md` | Strategy/process background. `ProjectInstructions.md` plus `docs/REPO_MAP.md` are the leaner context set for coding and research runs. |
| legacy `SystemIntel` handoff doc | Superseded by v3 research output. |
| `RESEARCH_REQUEST_v1.0.1.md` | Superseded by v6 prompt. |
| `research/edge_backlog_ranked.md` | 130+ lines. Relevant portions summarized in prompt and JJ Assessment. |
| `requirements.txt` | Build dependency list. Irrelevant to research. |
| `research/RTDS_MAKER_EDGE_IMPLEMENTATION.md` | Relevant to market-making research (Variant B), not combinatorial arb. |
| `research/LatencyEdgeResearch.md` | Latency context already summarized in `ProjectInstructions.md`. |

---

## COMPANION DISPATCHES

The Deep Research prompt is one half of a two-document system:

| Document | Tool | Contains | Triggered By |
|----------|------|----------|--------------|
| `DEEP_RESEARCH_PROMPT_v6.md` | ChatGPT Deep Research / Claude Deep Research | Empirical questions, academic paper search, competitive intelligence | Always — this runs first |
| Implementation dispatch (to be created) | Claude Code / Codex | Pseudocode, API endpoints, state machines, sprint plan, integration spec | Only if Deep Research returns GO |

v5 combined both jobs in one prompt. This degraded output quality because Deep Research tools produce mediocre code specs but excellent empirical research. v6 separates concerns.

---

## STALENESS ALERTS

Check these fields before every launch. If any are stale, update the source file first.

| File | Field to Check | Current Value | Stale If |
|------|---------------|---------------|----------|
| `CLAUDE.md` | Current State section date | 2026-03-07 | More than 5 days old |
| `ProjectInstructions.md` | Signal source count | 6 (as of Cycle 2) | New module added without updating |
| `ProjectInstructions.md` | Strategy status table | 6 deployed / 5 building / 10 rejected / 30 pipeline | After any strategy status change |
| `ProjectInstructions.md` | Priority Queue | P0-P4 queue from v3 research | After priority reassessment |
| `docs/REPO_MAP.md` | Canonical doc list / directory layout | Current monorepo map | After any new top-level workflow doc or major layout change |
| `FastTradeEdgeAnalysis.md` | Last Updated timestamp | 2026-03-07T17:34:01+00:00 | More than 24h since last pipeline run |
| `JJ_ASSESSMENT_DISPATCH_v3.md` | Dispatch assessed | DEEP_RESEARCH_OUTPUT_v3.md | After new research output |

**Known staleness (as of this manifest version):**
- Any remaining `COMMAND_NODE` references are stale. `ProjectInstructions.md` plus `docs/REPO_MAP.md` are now the canonical lightweight context set.

---

## FUTURE PACKAGE VARIANTS

When research focus shifts, swap TIER 2 docs. TIER 1 stays constant.

### Variant B: Market Making (A-1 IAMM)
TIER 2:
- `research/RTDS_MAKER_EDGE_IMPLEMENTATION.md`
- `research/market_making_fees_competitive_landscape_deep_research.md`
- `research/velocity_maker_strategy.md`

### Variant C: LLM Calibration (D-1 through D-12)
TIER 2:
- `research/calibration_2_0_plan.md`
- `research/superforecaster_methods_llm_playbook.md`

### Variant D: Cross-Platform Arb (B-2, B-6, B-10)
TIER 2:
- `research/LatencyEdgeResearch.md`
- Kalshi integration notes
- Cross-platform arb scanner output

---

## CHECKLIST: PRE-LAUNCH VERIFICATION

- [ ] All TIER 1 file dates are within 5 days of launch date
- [ ] TIER 2 files match current research focus
- [ ] Prompt state data matches reality (capital, signal source count, live trading status)
- [ ] ProjectInstructions strategy counts match edge_backlog_ranked.md
- [ ] FastTradeEdgeAnalysis reflects latest pipeline run
- [ ] No excluded files accidentally included
- [ ] Total attachment count is 7 (or <=10 if TIER 2 expanded)
- [ ] Total package size < 120KB (ChatGPT handles this well; >200KB degrades quality)

---

## WHEN TO UPDATE THIS MANIFEST

1. **New flywheel cycle** — Update ProjectInstructions, FastTradeEdgeAnalysis, staleness table
2. **Research focus shifts** — New prompt version, swap TIER 2 documents
3. **Major code changes** — Update ProjectInstructions and `docs/REPO_MAP.md` if signal sources or layout changed
4. **New research dispatch** — Add to TIER 2 if relevant, remove when consumed
5. **Strategy status change** — Verify ProjectInstructions strategy counts
6. **Live performance data available** — Add performance summary to TIER 1 or TIER 2

---

*If the manifest is stale, the research runs are stale. Update this first.*
