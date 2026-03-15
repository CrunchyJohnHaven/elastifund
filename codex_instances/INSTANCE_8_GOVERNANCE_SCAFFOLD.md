# Execute Instance #8 — Numbered Docs & Governance Scaffold

You are an autonomous Codex instance for the Elastifund trading system. Execute every step below without human intervention. Report findings, commit code, and produce the handoff artifact.

---

## STATE SNAPSHOT (Injected 2026-03-09 v2.8.0)

- Numbered root documents: 0 of 13 created
- Governance plan: defined in COMMAND_NODE.md (files 00-12)
- Vision docs: `research/elastic_vision_document.md`, `research/platform_vision_document.md`
- Current admin files: COMMAND_NODE.md (v2.8.0), PROJECT_INSTRUCTIONS.md (v3.8.0), CLAUDE.md, AGENTS.md, README.md
- Messaging system: approved/forbidden language defined but not enforced as a lint check
- Tests: 1,278 total verified
- Strategies: 131 tracked, 0 live trades, 305 cycles
- Current system ARR: 0% realized
- Product definition: "open, self-improving agentic OS for real economic work"
- Worker families: trading + non-trading (JJ-N)

### NUMBERED DOCUMENTS SPEC (from COMMAND_NODE.md)

| File | Purpose |
|---|---|
| `00_MISSION_AND_PRINCIPLES.md` | Why the project exists, what it optimizes, and what it will not do |
| `01_EXECUTIVE_SUMMARY.md` | Plain-language explanation for non-technical readers and leadership |
| `02_ARCHITECTURE.md` | System map, data flow, layers, and design constraints |
| `03_METRICS_AND_LEADERBOARDS.md` | Definitions for all public graphs and scorecards |
| `04_TRADING_WORKERS.md` | Trading system overview, policies, risk boundaries, paper vs live |
| `05_NON_TRADING_WORKERS.md` | Revenue-worker strategy, workflows, evaluation, and rollout |
| `06_EXPERIMENT_DIARY.md` | Chronological change log of experiments, outcomes, and lessons |
| `07_FORECASTS_AND_CHECKPOINTS.md` | Current forecasts, expected milestones, and confidence changes |
| `08_PROMPT_LIBRARY.md` | Canonical prompts, prompt variants, and prompt-review process |
| `09_GOVERNANCE_AND_SAFETY.md` | Autonomy levels, approvals, security, compliance, and incident policy |
| `10_OPERATIONS_RUNBOOK.md` | How to run the system, recover failures, and update components |
| `11_PUBLIC_MESSAGING.md` | Approved copy blocks for the site, GitHub, and outreach |
| `12_MANAGED_SERVICE_BOUNDARY.md` | What stays open source and what is offered as hosted infrastructure |

---

## OBJECTIVE

Create all 13 numbered root documents with substantive initial content drawn from existing canonical sources. Create a messaging lint script. These documents create narrative stability and make it possible for any agent or contributor to know where truth lives.

## YOU OWN

`docs/numbered/` (new directory), messaging lint scripts, `docs/REPO_MAP.md` (update only)

## DO NOT TOUCH

`bot/`, `src/`, `deploy/`, website files, `CLAUDE.md`, `COMMAND_NODE.md`, `PROJECT_INSTRUCTIONS.md` (these are read-only inputs)

## STEPS

1. Read `COMMAND_NODE.md` in full — extract content for each numbered document.

2. Read `research/elastic_vision_document.md` — extract mission, principles, messaging, governance, managed service boundary.

3. Read `research/platform_vision_document.md` — extract architecture, metrics, contribution flywheel, compliance.

4. Read `CLAUDE.md` — extract coding standards, open source guardrails, JJ persona.

5. Read `PROJECT_INSTRUCTIONS.md` — extract signal architecture, operator reference, machine snapshot.

6. Read `docs/diary/` entries for experiment diary content.

7. Read `research/edge_backlog_ranked.md` for strategy status to populate 04_TRADING_WORKERS.

8. Create the directory:
   ```bash
   mkdir -p docs/numbered
   ```

9. **Create each document** by extracting and reorganizing content from existing sources. Each document MUST:
   - Have a header with document number, title, version (1.0.0), date, and "Source: <which files contributed>"
   - Contain substantive content (not just stubs) — minimum 50 lines per document
   - Use approved messaging language only
   - Cross-reference other numbered documents by number
   - End with a "Last verified" timestamp and "Next review" date

   Priority order (write these first, they're most useful immediately):
   - `00_MISSION_AND_PRINCIPLES.md` — From vision docs: why this exists, what it optimizes, what it refuses to do, the veteran mission, the dual mission
   - `02_ARCHITECTURE.md` — From COMMAND_NODE Section 2: six-layer master architecture, signal sources, data stores, Elastic integration
   - `04_TRADING_WORKERS.md` — From PROJECT_INSTRUCTIONS Section 3 + edge_backlog: all 7 signal sources, kill rules, risk boundaries, current pipeline status
   - `05_NON_TRADING_WORKERS.md` — From vision docs: five-engine model, opportunity scoring, JJ-N rollout plan, Phase 0 deliverables
   - `09_GOVERNANCE_AND_SAFETY.md` — From CLAUDE.md: escalation rules, approval classes, open source guardrails, what stays private
   - `11_PUBLIC_MESSAGING.md` — From COMMAND_NODE messaging section: approved/forbidden language, hero copy, /elastic copy

   Then write the remaining seven documents.

10. **Create messaging lint script** at `scripts/lint_messaging.py`:
    ```python
    """Lint all public-facing files for approved/forbidden messaging terminology."""
    import sys, re, glob

    FORBIDDEN = [
        "self-modifying binary",
        "remove the human from the loop",
        "agent swarm that makes money",
        "fully autonomous",
        "no human oversight",
        "uncontrolled",
    ]

    APPROVED = [
        "self-improving",
        "policy-governed autonomy",
        "agentic work",
        "economic work",
        "evidence",
        "benchmarks",
        "paper mode by default",
    ]

    PUBLIC_FILES = [
        "README.md",
        "index.html",
        "docs/numbered/01_EXECUTIVE_SUMMARY.md",
        "docs/numbered/11_PUBLIC_MESSAGING.md",
    ]

    def lint():
        errors = []
        for pattern in PUBLIC_FILES + glob.glob("docs/numbered/*.md"):
            try:
                with open(pattern) as f:
                    content = f.read().lower()
                for term in FORBIDDEN:
                    if term.lower() in content:
                        errors.append(f"FORBIDDEN term '{term}' found in {pattern}")
            except FileNotFoundError:
                pass

        if errors:
            for e in errors:
                print(f"ERROR: {e}", file=sys.stderr)
            return 1
        print(f"Messaging lint passed: {len(PUBLIC_FILES)} files checked, 0 violations")
        return 0

    if __name__ == "__main__":
        sys.exit(lint())
    ```

11. Run the messaging lint:
    ```bash
    python3 scripts/lint_messaging.py
    ```

12. Update `docs/REPO_MAP.md` to include the new `docs/numbered/` directory with all 13 files listed.

13. Run all tests to ensure nothing broke:
    ```bash
    python3 -m pytest tests/ -x -q --tb=short
    ```

14. Produce handoff artifact at `reports/governance_scaffold_<timestamp>.json`:
    ```json
    {
      "timestamp": "<ISO>",
      "instance_version": "2.8.0",
      "documents_created": 13,
      "documents_list": ["00_MISSION_AND_PRINCIPLES.md", "01_EXECUTIVE_SUMMARY.md", ...],
      "total_lines_written": N,
      "messaging_lint_result": "pass|fail",
      "forbidden_terms_found": 0,
      "cross_references_valid": true,
      "source_files_read": ["COMMAND_NODE.md", "elastic_vision_document.md", "platform_vision_document.md", "CLAUDE.md", "PROJECT_INSTRUCTIONS.md"],
      "repo_map_updated": true,
      "next_actions": ["Add numbered docs to CI lint", "Wire into website /docs route", "Schedule quarterly review cycle"]
    }
    ```

## VERIFICATION

```bash
python3 -m pytest tests/ -x -q --tb=short
# Verify all 13 files exist
ls docs/numbered/*.md | wc -l  # Should be 13
# Verify messaging compliance
python3 scripts/lint_messaging.py
# Verify no empty files
for f in docs/numbered/*.md; do
  lines=$(wc -l < "$f")
  if [ "$lines" -lt 50 ]; then echo "WARNING: $f has only $lines lines"; fi
done
```

## HANDOFF

```
INSTANCE #8 HANDOFF
---
Files created: [list all 13 + lint script]
Total lines written: N
Messaging lint: [pass|fail]
Cross-references: [valid/invalid]
Source files used: [list]
Repo map updated: [yes/no]
Unverified: [anything next cycle should check]
Next instance can edit these files: [yes/no per file]
```
