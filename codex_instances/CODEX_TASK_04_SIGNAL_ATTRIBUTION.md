# CODEX TASK 04: Signal Source Attribution Tracking

## MACHINE TRUTH (2026-03-09)
- 6 signal sources: LLM (#1), wallet flow (#2), LMSR (#3), cross-platform arb (#4), VPIN/OFI (#5), lead-lag (#6)
- Wallet flow: 80 scored wallets, ready but paused — will activate with crypto unlocked
- VPS log showed: "No smart wallet scores found. Run --build-scores first."
- Cross-platform arb crashed: "asyncio.run() cannot be called from a running event loop"
- Need per-source tracking to evaluate which signals produce profitable trades

## TASK
1. Read `bot/jj_live.py` signal collection section (search for "SIGNAL:" log entries, around lines 3600-4200)
2. Verify that paper/live trade logs in `jj_state.json` include the signal source
3. If signal source is NOT already tracked per trade, add it:
   - Each trade entry in jj_state.json should include `"signal_sources": ["llm", "wallet_flow"]`
   - Each trade should also include `"signal_metadata": {"llm_prob": 0.65, "wallet_consensus": 0.72}`
4. Create `scripts/signal_attribution_report.py`:
   - Reads jj_state.json (or jj_trades.db)
   - Groups trades by signal source
   - Calculates per-source: count, win rate, avg edge, total P&L
   - Outputs `reports/signal_attribution.json`
5. Fix the asyncio bug in cross-platform arb:
   - `bot/jj_live.py` line ~4174: `asyncio.run()` called inside async context
   - Fix: use `await` instead, or `asyncio.get_event_loop().run_until_complete()`
   - Or: wrap in `nest_asyncio` if the loop is already running

## FILES
- `bot/jj_live.py` (MODIFY — add signal_sources to trade records if missing, fix asyncio bug)
- `scripts/signal_attribution_report.py` (CREATE)
- `tests/test_signal_attribution.py` (CREATE)

## CONSTRAINTS
- Do NOT change signal logic — only add tracking metadata
- Do NOT break existing jj_state.json format (add fields, don't rename/remove)
- The asyncio fix must not break the main event loop
- `make test` must pass

## SUCCESS CRITERIA
- Trade records include signal source attribution
- Attribution report script works on sample data
- asyncio error in cross-platform arb fixed
- `make test` passes
