# Elastifund Website Update Checklist
Generated: 2026-03-07 from Replit screenshot review

## CRITICAL UPDATES (Stale/Wrong Info)

### Section 13: Agent Architecture
- [ ] **Server location**: "DigitalOcean Frankfurt" → "AWS Lightsail Dublin (eu-west-1)"
- [ ] **Cost**: "~$10/month" → "~$5/month" (Lightsail pricing)
- [ ] **Scan interval**: "5 minutes" → "3 minutes" (SCAN_INTERVAL=180s)

### Section 0 (Hero): Stats
- [ ] **Markets Tested**: 412 → 532 (current backtest size)
- [ ] **Win Rate**: 53.0% → update to reflect production strategy (71.2% for Cal+CatFilter+Asym)
- [ ] Consider adding "Paper Trades: XX" live counter

### Section 5: Position Sizing
- [ ] Kelly multiplier: website says "Quarter-Kelly" in some places, actual code uses Half-Kelly (0.50)
- [ ] Per-trade cap: website says "$5 max per trade" (safety rails) and "$1/trade" (Week 1), but code has $15 max
- [ ] Reconcile these — the code reflects Phase 2+ parameters

### Section 9: Risk Management
- [ ] Daily loss limit: "$10 daily" → "$25 daily" (current JJ_MAX_DAILY_LOSS_USD)
- [ ] Per-trade cap: "$5 max per trade" → "$15" (current MAX_POSITION_USD)
- [ ] Exposure cap: "80%" → "90%" (current MAX_EXPOSURE_PCT)

### Section 11: Roadmap
- [ ] "Live Trading Validation" — mark as "In Progress" (paper trading active on Dublin)
- [ ] Add: "Paper trading live since Mar 7, 2026"

## NICE-TO-HAVE UPDATES

### New section: Elastic solved the operator blind spot
- [ ] Add a short "Why Elastic is load-bearing" section, not a sponsor badge
- [ ] Show that the bot now writes three concrete artifacts:
  - agent heartbeat to `elastifund-agents`
  - per-cycle risk/P&L telemetry to `elastifund-metrics`
  - order snapshots to `elastifund-trades`
- [ ] Add one Kibana screenshot that shows the bot heartbeat and one that shows recent trade docs
- [ ] Add one sentence that explains the practical win: we stopped relying on local logs and SQLite alone to know whether the bot was healthy
- [ ] Add one sentence that explains the architectural win: the trading bot is now a spoke in the same Elastic-backed control plane as the rest of Elastifund

### Suggested Replit copy
- [ ] "Elastic gave us a shared operator view. The bot now publishes heartbeats, cycle metrics, and trade snapshots into the same backbone we use for the wider Elastifund control plane."
- [ ] "What it solved for us was operational blindness: before this, the truth lived in one VPS log file and one local database; now it is queryable in Kibana."
- [ ] "This is why Elastic is part of the product architecture, not just the tooling list."

### Section 17: Sponsors & Partners
- [ ] DigitalOcean → AWS Lightsail (if listing infrastructure partners)
- [ ] Consider adding "Claude Code" as a development tool

### General
- [ ] Add a "Live Status" badge or section showing paper trading is active
- [ ] Add real-time paper trade count from Dublin VPS
- [ ] Consider a "Paper Trading Dashboard" link

## WEBSITE TECH
- Hosted on Replit
- Dark theme, single-page scrolling design
- 18 sections with table of contents
- Well-structured with charts, tables, and interactive elements

## WHAT'S CORRECT (No changes needed)
- Platt calibration explanation without publishing the live coefficients ✅
- Category routing tiers ✅
- Research papers section ✅
- Veteran impact section ✅
- Strategy comparison table ✅
- Monte Carlo simulation ✅
- Competitive landscape ✅
- Disclaimer ✅
