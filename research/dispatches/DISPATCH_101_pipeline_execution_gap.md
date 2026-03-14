# DISPATCH 101: Pipeline-Execution Gap Analysis

**Date:** 2026-03-14
**Author:** JJ (autonomous agent)
**Status:** COMPLETE
**Priority:** P1 (operational clarity)

## The Problem

FAST_TRADE_EDGE_ANALYSIS.md says **REJECT ALL** (last run 2026-03-09T01:34:49Z, now 5+ days stale). Meanwhile, the BTC 5-minute maker service has:
- 128 closed contracts
- 75/53 W/L (58.6% win rate)
- +$131.52 realized P&L
- 1.49 profit factor

These two systems give contradictory signals about whether Elastifund has a tradeable edge. This dispatch explains why and what to do about it.

## Root Cause: Two Completely Separate Systems

The edge scan pipeline and the BTC5 maker are **architecturally decoupled**. They share no code, no data, no decision logic. They are different programs solving different problems.

### System 1: Edge Scan Pipeline (FAST_TRADE_EDGE_ANALYSIS.md)

**Entry point:** `bot/edge_scan_report.py` -> `generate_edge_scan_report()`

**What it does:**
1. Fetches recent trades from `data-api.polymarket.com/trades`
2. Hydrates market metadata from `gamma-api.polymarket.com/markets`
3. Filters to open markets under 24h resolution
4. Runs Platt-calibrated threshold analysis (YES: 15%, NO: 5%)
5. Scans wallet-flow, LMSR, cross-platform arb, A-6, VPIN lanes
6. Joins candidates and applies kill rules
7. Recommends: restart, stay_paused, or recalibrate

**What it evaluates:** General Polymarket markets (politics, weather, economic, crypto, sports). It looks for LLM-estimated probability edges against market prices. The scan universe is broad (~7,050 markets across 500 events).

**Why it says REJECT ALL:**
- Current thresholds (YES: 15%, NO: 5%) leave **0 markets** passing the category gate in the BTC fast-market universe
- Aggressive thresholds expand to 6 markets, but all 9 tested strategy families failed kill rules
- The strategies it tests (Residual Horizon, Time-of-Day, Wallet Flow Momentum, etc.) are LLM-probability strategies, not price-delta strategies
- It has no mechanism to evaluate the BTC5 maker's actual trading logic

**Key limitation:** The scan requires LLM probability estimates to compute edge. The BTC5 maker does not use LLM estimates at all. It uses Binance spot price delta vs candle open. These are fundamentally different signal types.

### System 2: BTC 5-Minute Maker (`bot/btc_5min_maker.py`)

**Entry point:** `bot/btc_5min_maker.py` -> standalone asyncio service

**What it does:**
1. Waits until T-10 seconds before each 5-minute candle close
2. Compares current Binance BTC spot price to the candle open
3. If |price delta| >= configured threshold, selects UP or DOWN outcome
4. Places a post-only maker BUY order on the predicted outcome token
5. Cancels unfilled orders at T-2 seconds
6. Records every decision in SQLite (`data/btc_5min_maker.db`)

**What it evaluates:** Exclusively BTC 5-minute candle markets on Polymarket. One market type, one timeframe, one signal: is BTC going up or down relative to candle open?

**Why it's profitable:**
- Maker-only execution (0% fees vs ~1.5-3.15% taker fees)
- Very short resolution windows (5 minutes) limit exposure time
- Price-delta signal is objective, no LLM estimation needed
- Autoresearch loop tunes thresholds (delta, direction, hour) based on fill data

## The Gap Is By Design (But Needs Documentation)

The two systems were never intended to share logic. The edge scan pipeline evaluates whether broad LLM-probability trading is viable. The BTC5 maker is a specialized microstructure strategy that bypasses the LLM pipeline entirely.

**This is correct architecture.** A general-purpose scan should not govern a specialized maker strategy. However, the gap creates operational confusion:

1. **CLAUDE.md and COMMAND_NODE.md reference both as if they're one system.** They're not.
2. **FAST_TRADE_EDGE_ANALYSIS.md is treated as the canonical "should we trade?" signal.** But it only answers "should we trade LLM-probability strategies?" The BTC5 maker answers its own question independently.
3. **The "REJECT ALL" headline creates false alarm.** It reads like "nothing works" when the actual P&L is +$131.52.

## Recommendations

### R1: Rename the Relationship (Documentation)
FAST_TRADE_EDGE_ANALYSIS.md should explicitly state:
> "This report evaluates the LLM-probability trading pipeline only. The BTC 5-minute maker service operates independently with its own edge validation (see `reports/btc5_promotion_gate.json`)."

### R2: Add BTC5 Status Section to FAST_TRADE_EDGE_ANALYSIS.md
Add a new section "## Independent Trading Lanes" that cross-references BTC5 performance data without trying to evaluate it through the LLM pipeline's kill rules.

### R3: Separate Stage Gates
The BTC5 maker should have its own promotion/kill criteria:
- **Promote gate:** 50+ closed trades, win rate > 55%, profit factor > 1.2, positive cumulative P&L
- **Kill gate:** 20+ consecutive losses, profit factor < 0.8, cumulative P&L < -$50
- These gates are evaluated against `data/btc_5min_maker.db`, not `data/edge_discovery.db`

### R4: Run Edge Scan on VPS for Freshness
The edge scan is 5+ days stale because it requires API access to Polymarket (blocked from sandbox). Set up a cron job on VPS:
```bash
# Every 6 hours
0 */6 * * * cd /home/ubuntu/polymarket-trading-bot && python bot/edge_scan_report.py --output reports/
```

### R5: Do Not Merge the Systems
The BTC5 maker's edge comes from speed and microstructure, not from probability estimation. Forcing it through the LLM pipeline would degrade it. Keep them separate. Document the separation clearly.

## Architecture Diagram

```
                    EDGE SCAN PIPELINE                    BTC5 MAKER
                    ==================                    ==========

Source:             Gamma API + Trade API                  Binance spot price
Signal:             LLM probability vs market price        Price delta vs candle open
Timeframe:          Any market < 24h                       5-minute BTC candles only
Kill rules:         kill_rules.py battery                  Autoresearch loop (guardrails)
Output:             FAST_TRADE_EDGE_ANALYSIS.md            data/btc_5min_maker.db
Execution:          jj_live.py (main loop)                 btc_5min_maker.py (standalone)
Current status:     REJECT ALL (stale)                     +$131.52 realized (128 trades)
```

## Files Referenced

| File | Role |
|------|------|
| `bot/edge_scan_report.py` | Edge scan pipeline entry point (generates JSON reports) |
| `scripts/run_kill_battery.py` | Kill battery runner (generates FAST_TRADE_EDGE_ANALYSIS.md) |
| `scripts/run_edge_collector.py` | Market data collector daemon (feeds edge_discovery.db) |
| `bot/btc_5min_maker.py` | BTC5 maker service (independent, standalone) |
| `FAST_TRADE_EDGE_ANALYSIS.md` | LLM pipeline status report (does NOT cover BTC5) |

## Conclusion

The "REJECT ALL" signal is honest for the LLM pipeline. It is irrelevant for the BTC5 maker. The operational confusion comes from treating one report as the canonical answer for the entire fund. Fix the documentation, not the architecture.
