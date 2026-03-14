# BTC5 Hypothesis Frontier

This is the best walk-forward BTC5 hypothesis found on each local autoresearch cycle. The chart is percentage-only and tracks validated return estimates, not dollars at risk.

- Cycles tracked: `7` (loop total: `14` including probe-only cycles)
- Frontier P05 ARR: `4265134.28%`
- Frontier median ARR: `10924714.95%`
- Latest hypothesis: `hyp_down_d0.00015_up0.50_down0.51_hour_et_11`
- Latest direction: `DOWN`
- Latest session: `hour_et_11`
- Latest evidence band: `exploratory`
- Latest validation P05 ARR: `2311433.66%`
- Latest validation median ARR: `9625734.34%`
- Latest validation fills: `5`
- Latest generalization ratio: `42.9900`
- Evidence counts: exploratory `4`, candidate `1`, validated `2`
- Latest finished at: `2026-03-10T12:44:55.402965+00:00`

## Autoresearch v2 Enhancements (2026-03-14)

The autoresearch loop now includes v2 optimizations:

1. **Evidence-informed hypothesis seeding** — prior fill P&L by direction/session/delta bucket weights hypothesis generation toward winning combinations. DOWN-biased and open-ET hypotheses get boosted when those buckets show positive P&L.
2. **Hypothesis kill list** — hypotheses that fail after 12+ fills (win rate < 42%, cumulative PnL < -$3, or profit factor < 0.7) are auto-killed with 72h cooldown. Prevents wasting compute on known losers.
3. **Row-hash cycle skipping** — expensive Monte Carlo is skipped when the data hash hasn't changed since last cycle, reducing redundant compute during quiet periods.
4. **Adaptive Monte Carlo paths** — 800 paths when stale (fast cycle), 2000 normal, 3000 when fresh fills arrive (higher precision when it matters).
5. **Enhanced cadence control** — exponential backoff on consecutive no-evidence cycles (caps at 30 min), time-of-day awareness during US trading hours (14:00-21:00 UTC), and sub-minute acceleration on fresh fills.
