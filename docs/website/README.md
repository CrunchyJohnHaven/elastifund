# Website Docs

- Status: Active index
- Last reviewed: 2026-03-11
- Scope: website copy source docs, educational pages, and strategy autopsies

## Current State (30 seconds)

`docs/website/` is active and split into three content groups:

- learning pages for public education
- benchmark methodology surfaces
- strategy autopsy writeups under `autopsies/`

## Inventory By Group

### Active pages

| File | Class | Status |
|---|---|---|
| `autonomous-market-operators.md` | background research | active |
| `benchmark-methodology.md` | canonical runbook/spec | active |
| `prediction-markets-101.md` | background research | active |
| `how-ai-forecasts.md` | background research | active |
| `what-is-edge.md` | background research | active |

### Autopsies

| File | Class | Status |
|---|---|---|
| `autopsies/R2-volatility-regime-mismatch.md` | historical briefing | active reference |
| `autopsies/R4-chainlink-basis-lag.md` | historical briefing | active reference |
| `autopsies/R10-noaa-weather-bracket.md` | historical briefing | active reference |

## Naming Convention

- New top-level docs: lowercase kebab-case.
- Autopsies: `R<number>-short-kebab-case.md` to preserve strategy ID visibility.
- Use an explicit status line near the top of each doc.

## Draft Handling

If a doc becomes one-off or pitch-only, move it to a local `archive/` subtree and leave a pointer only when references exist.
