# DISPATCH 103: Shadow Lane Staging — Wallet-Flow + LMSR

**Date:** 2026-03-14
**Author:** JJ (Instance 9)
**Status:** STAGED FOR SHADOW VALIDATION
**Priority:** P1

## Objective

Stage the wallet-flow detector (Signal Source #2) and LMSR Bayesian engine (Signal Source #3) for shadow validation against BTC5 live fills. Neither lane places real orders — they log hypothetical trades and P&L for head-to-head comparison.

## What Was Built

### 1. Shadow Runner (`bot/shadow_runner.py`)
Unified shadow-mode runner for both signal lanes:
- `ShadowDB`: SQLite persistence for all shadow signals with dedup, resolution tracking, and P&L aggregation
- `ShadowSignal` dataclass: captures lane, market, direction, edge, confidence, hypothetical size
- Lane scanners: pluggable `_run_wallet_flow_scan()` and `_run_lmsr_scan()` functions
- Continuous mode: polls at configurable interval (default 30s)
- CLI: `--lane wallet_flow|lmsr`, `--continuous`, `--once`, `--status`
- Hypothetical sizing: quarter-Kelly capped at $5/trade (configurable via `SHADOW_MAX_TRADE_USD`)

### 2. Systemd Service Files
- `deploy/wallet-flow-shadow.service` — runs wallet-flow scanner continuously
- `deploy/lmsr-shadow.service` — runs LMSR scanner continuously
- Both follow existing service patterns from `deploy/btc-5min-maker.service`
- Restart on failure with 60s backoff

### 3. Comparison Framework (`scripts/compare_shadow_vs_live.py`)
Produces head-to-head reports comparing shadow lanes vs BTC5 live:
- Reads `data/shadow_signals.db` and `data/btc_5min_maker.db`
- Computes per-lane: signal count, win rate, P&L, avg edge, avg confidence
- Market overlap analysis: which markets each lane sees vs BTC5
- Rankings by P&L
- Output: `reports/shadow_vs_live_comparison.json` + `.md`
- Filterable by `--since` date

### 4. Test Coverage
- `tests/test_shadow_runner.py`: 20 tests — DB CRUD, dedup, resolution, sizing, lane registration
- `tests/test_lmsr_engine.py`: 42 tests — LMSR math, Bayesian updater, Kelly sizing, engine lifecycle
- `tests/test_compare_shadow.py`: 4 tests — report generation, markdown formatting
- **Total: 66 new tests, all passing**

## Lane Assessment

### Wallet-Flow Detector (`bot/wallet_flow_detector.py`)
**Current state:** Fully implemented. Has WalletScorer, FlowMonitor, ConsensusDetector, and engine integration via `get_signals_for_engine()`. Smart wallet bootstrap requires pre-built `data/smart_wallets.json`.

**What's missing for shadow:**
- Bootstrap data (`data/smart_wallets.json`) may not exist on VPS. Run `python bot/wallet_flow_detector.py --build-scores` first.
- Depends on `data-api.polymarket.com/trades` endpoint — rate limits may apply.
- Conflict resolution logic already implemented (suppresses conflicting signals).

**Shadow readiness:** HIGH — all code exists, just needs bootstrap data and a running service.

### LMSR Engine (`bot/lmsr_engine.py`)
**Current state:** Fully implemented. Has LMSR cost/price functions, Bayesian posterior updater, Kelly sizing, and single/batch signal generation. 828ms target cycle time.

**What's missing for shadow:**
- No persistent state between restarts (in-memory only). Shadow DB compensates by recording all signals.
- Fetches from `gamma-api.polymarket.com/markets` — needs active markets to scan.
- Signal threshold (5% divergence) may need tuning based on shadow results.

**Shadow readiness:** HIGH — self-contained, no bootstrap needed.

## Deployment Steps

```bash
# 1. Deploy shadow runner to VPS
scp bot/shadow_runner.py ubuntu@34.244.34.108:/home/ubuntu/polymarket-trading-bot/bot/
scp deploy/wallet-flow-shadow.service deploy/lmsr-shadow.service ubuntu@34.244.34.108:/tmp/

# 2. On VPS: install services
sudo cp /tmp/wallet-flow-shadow.service /tmp/lmsr-shadow.service /etc/systemd/system/
sudo systemctl daemon-reload

# 3. Bootstrap wallet-flow data (if not exists)
cd /home/ubuntu/polymarket-trading-bot
python3 bot/wallet_flow_detector.py --build-scores

# 4. Start shadow services
sudo systemctl enable --now wallet-flow-shadow.service
sudo systemctl enable --now lmsr-shadow.service

# 5. Monitor
journalctl -u wallet-flow-shadow -f --no-pager
journalctl -u lmsr-shadow -f --no-pager

# 6. After 24h+, run comparison
python3 scripts/compare_shadow_vs_live.py --since 2026-03-14
```

## Promotion Criteria

A shadow lane earns promotion to live trading when:
1. **Minimum signals:** 50+ shadow signals recorded
2. **Win rate:** > 55% on resolved signals
3. **Hypothetical P&L:** Positive cumulative
4. **Profit factor:** > 1.2 (gross wins / gross losses)
5. **Overlap quality:** At least 30% overlap with BTC5 market universe
6. **No worse than BTC5:** Win rate and P&L rank within 20% of BTC5 live performance

## Risk Notes

- Shadow mode places zero orders and risks zero capital.
- The only cost is API rate limiting from additional polling.
- Shadow DB grows at ~1 row per signal (typically < 100/day per lane).
- Services can be stopped at any time with no side effects.
