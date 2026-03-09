# CODEX TASK 02: Programmatic Threshold Sensitivity Sweep

## MACHINE TRUTH (2026-03-09)
- FAST_TRADE_EDGE_ANALYSIS.md shows: 0 markets at 0.15/0.05, 8 at 0.08/0.03, 8 at 0.05/0.02
- All 8 tradeable markets are BTC crypto candles
- The 0→8 jump at 0.08 needs programmatic validation
- Pipeline uses polymarket-bot/src/scanner.py for market discovery

## TASK
Create `scripts/threshold_sweep.py` that:
1. Calls the same market scanner used by jj_live.py (MarketScanner from polymarket_runtime)
2. For each threshold pair from (0.20, 0.10) down to (0.02, 0.01) in 0.01 steps:
   a. Count markets passing: price in 0.10-0.90, resolution < 48h, edge >= threshold
   b. Record market IDs, questions, categories, prices, estimated edges
3. Output a JSON report to `reports/threshold_sensitivity_sweep.json`:
   ```json
   {
     "generated_at": "ISO timestamp",
     "sweep_results": [
       {"yes_threshold": 0.20, "no_threshold": 0.10, "markets_passing": 0, "market_ids": []},
       {"yes_threshold": 0.19, "no_threshold": 0.09, "markets_passing": 0, "market_ids": []},
       ...
     ],
     "breakpoints": [
       {"threshold": 0.08, "markets_gained": 8, "categories": {"crypto": 8}}
     ]
   }
   ```
4. Also output a human-readable summary to stdout showing the step function
5. Identify exact breakpoint(s) where market count jumps

## CONSTRAINTS
- Must work WITHOUT API keys (use cached market data if available, or mock the scanner)
- If API keys needed, use ANTHROPIC_API_KEY from .env only for Claude calls
- Script must be runnable as: `python3 scripts/threshold_sweep.py`
- Add test: `tests/test_threshold_sweep.py` — test the sweep logic with mock data

## FILES
- `scripts/threshold_sweep.py` (CREATE)
- `tests/test_threshold_sweep.py` (CREATE)
- `reports/threshold_sensitivity_sweep.json` (GENERATED OUTPUT)

## SUCCESS CRITERIA
- Script runs without error
- JSON report generated with complete sweep data
- Breakpoint(s) identified programmatically
- `make test` passes including new test
