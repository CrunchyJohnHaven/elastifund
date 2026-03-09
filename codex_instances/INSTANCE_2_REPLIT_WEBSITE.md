# Execute Instance #2 — Replit Website Build

You are an autonomous Codex instance for the Elastifund trading system. Execute every step below without human intervention. Report findings, commit code, and produce the handoff artifact.

---

## STATE SNAPSHOT (Injected 2026-03-09)

- Capital: $347.51 total ($247.51 Polymarket + $100 Kalshi)
- Strategies: 131 tracked (7 deployed, 6 building, 2 structural alpha, 10 rejected, 8 pre-rejected, 1 re-evaluating, 97 research)
- Tests: 353 passing locally; 1,256 total across all suites
- Dispatches: 95 in `research/dispatches/`
- Signal sources: 7 (LLM, LMSR, WalletFlow, VPIN/OFI, LeadLag, ElasticML, NO-Bias planned)
- Service: `jj-live.service` running but 0 trades — drift state
- Pipeline: REJECT ALL
- Edge thresholds: Now env-var configurable (JJ_YES_THRESHOLD, JJ_NO_THRESHOLD)
- Cycle: 2 — Machine Truth Reconciliation

---

## OBJECTIVE

Improve the Replit website (https://elastifund.replit.app) with fresh data, corrected metrics, and any new content. The website is currently a single static `index.html` (2,212 lines, dark terminal aesthetic).

## YOU OWN

`index.html`, `REPLIT_NEXT_BUILD.md`, any website source files

## DO NOT TOUCH

`bot/`, `execution/`, `strategies/`, `signals/`, `src/`, `tests/`

## STEPS

1. Read `REPLIT_NEXT_BUILD.md` for the full build spec. Note what the current site does well, what it lacks, and target architecture.

2. Read `CLAUDE.md` "Current State" for live numbers:
   - Capital: $347.51
   - Cycle: 2
   - Strategies: 131 total (7 deployed, 6 building, 2 structural, 10 rejected, 8 pre-rejected, 1 re-evaluating, 97 research)
   - Tests: 353 local / 1,256 total verified
   - Dispatches: 95
   - Signal sources: 7
   - Live trades: 0

3. Read `README.md` for public-facing metrics. Ensure website matches.

4. Read `FAST_TRADE_EDGE_ANALYSIS.md` for latest pipeline results to surface.

5. Read `research/edge_backlog_ranked.md` for updated strategy counts by status.

6. Read the latest `docs/diary/` entry for new build diary content.

7. In `index.html`, correct ALL stale metrics:
   - Strategy count → 131
   - Test count → 1,256 total verified
   - Dispatch count → 95
   - Signal sources → 7
   - Capital → $347.51
   - Win rate → 71.2% calibrated (NO-only: 76.2%)
   - Daily loss cap → $5
   - Position size → $5
   - Server → Dublin VPS (AWS Lightsail eu-west-1)

8. Add any new strategy encyclopedia entries. Check for D-*, B-*, SA-*, RE-*, R-* entries in `research/edge_backlog_ranked.md` that aren't on the site yet:
   - SA-1: A-6 Guaranteed Dollar Scanner
   - SA-2: B-1 Templated Dependency Engine
   - RE1: Chainlink vs Binance Basis Lag (MAKER-ONLY re-evaluation)

9. Add latest build diary entry if one exists that isn't published.

10. Add a "System Status" section showing:
    - Service: Running (drift — 0 trades in 298 cycles)
    - Pipeline: REJECT ALL
    - Edge thresholds: Now configurable via env vars
    - Next milestone: First live trade

11. Update the site footer timestamp to now.

12. If `reports/edge_scan_*.json` exists from Instance #1, surface the opportunity count and market selection summary (no specific trade details — this is a public site).

## VERIFICATION

- Site loads without console errors
- All metric values match CLAUDE.md current state
- No broken links
- Strategy counts match edge_backlog_ranked.md

## HANDOFF

```
INSTANCE #2 HANDOFF
---
Files changed: [list]
Commands run: [list]
Key findings: [1-3 sentences]
Numbers that moved: [before→after for each metric corrected]
Unverified: [anything next cycle should check]
Next instance can edit these files: [yes/no per file]
```
