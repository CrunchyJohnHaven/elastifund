# Session Handoff — 2026-03-15

**Last updated:** 2026-03-15 ~21:30 UTC
**Purpose:** Context for next Claude Code session or research agent picking up this work.

---

## 1. Live System State

Three bot instances running as systemd services:

| Service | Asset | DB | Status |
|---|---|---|---|
| `btc-5min-maker.service` | BTC/USDT | `data/btc_5min_maker.db` | Live, stage 1 |
| `eth-5min-maker.service` | ETH/USDT | `data/eth_5min_maker.db` | Live, stage 1 |
| `sol-5min-maker.service` | SOL/USDT | `data/sol_5min_maker.db` | Live, stage 1 |

All three use `bot/btc_5min_maker.py` with asset-specific env vars set in their `.service` files.

Verify with:
```
sudo systemctl status btc-5min-maker eth-5min-maker sol-5min-maker
journalctl -u btc-5min-maker -f --since "5 min ago"
```

---

## 2. Effective Live Config (BTC — master config, ETH/SOL inherit)

From `/proc/{pid}/environ` as of 2026-03-15 21:00 UTC:

```
BTC5_DIRECTIONAL_MODE=two_sided        # two_sided since 21:00 UTC (was down_only)
BTC5_MIN_BUY_PRICE=0.90                # raised from 0.42 on 2026-03-15
BTC5_DOWN_MAX_BUY_PRICE=0.95
BTC5_UP_MAX_BUY_PRICE=0.95             # raised from 0.52 on 2026-03-15
BTC5_MIN_DELTA=0.0001
BTC5_UP_MIN_DELTA=0.0001               # lowered from 0.0006
BTC5_TOXIC_FLOW_MIN_PRICE_EXEMPT=0.90  # H4-new fix
BTC5_MIDPOINT_KILL_ZONE_MIN_PRICE_EXEMPT=0.90  # H4-mid fix
BTC5_BANKROLL_USD=390
BTC5_MAX_TRADE_USD=10
BTC5_DAILY_LOSS_LIMIT_USD=25
```

Config files (gitignored, on VPS only):
- `config/btc5_strategy.env` — UP/DOWN_MAX_BUY_PRICE, MIN_DELTA, filter exemptions
- `state/btc5_capital_stage.env` — bankroll, stage, MIN_BUY_PRICE, DIRECTIONAL_MODE override
- `config/autoresearch_overrides.json` — runtime overrides (read by bot each window, NOT startup)

---

## 3. Evidence Base (All-Time BTC Fills)

10 total fills as of 2026-03-15 21:30 UTC:

| Date | Direction | Price | PnL | Won |
|---|---|---|---|---|
| 2026-03-14 20:14 | UP | 0.64 | -$5.00 | No |
| 2026-03-14 20:24 | UP | 0.74 | -$5.00 | No |
| 2026-03-14 20:29 | UP | 0.95 | +$0.26 | Yes |
| 2026-03-14 20:54 | DOWN | 0.98 | +$0.10 | Yes |
| 2026-03-14 20:59 | DOWN | 0.96 | +$0.21 | Yes |
| 2026-03-15 00:29 | DOWN | 0.85 | +$0.88 | Yes |
| 2026-03-15 00:59 | DOWN | 0.85 | +$1.38 | Yes |
| 2026-03-15 01:24 | DOWN | 0.86 | +$1.27 | Yes |
| 2026-03-15 21:14 | DOWN | 0.90 | +$0.87 | Yes |
| 2026-03-15 21:24 | UP | 0.90 | +$0.87 | Yes |

**Key pattern:**
- At price >= 0.90: 8/8 wins = 100% WR, +$5.84 net
- At price < 0.90: 0/2 wins = 0% WR, -$10.00 net
- DOWN at any valid price: 6/6 wins = 100%
- UP at 0.90+: 2/2 wins = 100%
- UP below 0.90: 0/2 wins = 0%

MIN_BUY_PRICE=0.90 is the clean cut. The momentum confirmation edge is symmetric across directions.

**Daily trajectory:**
- 2026-03-14: -$9.43 (pre-MIN_BUY=0.90 era, UP losses at 0.64/0.74)
- 2026-03-15: +$5.26 and counting

---

## 4. Skip Analysis (BTC, Last 24h)

| Status | Count | Root Cause |
|---|---|---|
| skip_directional_mode | 91 | 89 from down_only mode before 21:00 UTC switch; 2 residual |
| skip_bad_book | 61 | No ask (one-sided book, market near 100% certain) |
| skip_price_outside_guardrails | 54 | best_ask > 0.95 cap (market at 0.97-0.99) |
| skip_delta_too_small | 29 | Flat BTC (|delta| < 0.0001) |
| skip_size_too_small | 14 | Order price < MIN_BUY or size math below $5 min |
| live_filled | 5 | Actual trades |

The largest opportunity: `skip_bad_book` (61) and `skip_price_outside_guardrails` (54) together = 115 windows we cannot trade.

---

## 5. Bugs Found and Fixed This Session

### Bug 1: autoresearch_overrides.json with DIRECTIONAL_MODE="two_sided" blocks all windows

**Code location:** `bot/btc_5min_maker.py` line 2914-2947

The code does:
```python
ar_dir_mode = autoresearch_overrides.get("BTC5_DIRECTIONAL_MODE")
if ar_dir_mode:
    allowed_dir = ar_dir_mode.replace("_only", "").strip().upper()
    if allowed_dir and direction != allowed_dir:
        return skip_directional_mode
```

For `ar_dir_mode = "two_sided"`:
- `allowed_dir = "TWO_SIDED"` (non-empty, truthy)
- `direction != "TWO_SIDED"` is always True
- **All windows get `skip_directional_mode`**

**Fix:** Remove `BTC5_DIRECTIONAL_MODE` from `config/autoresearch_overrides.json` when using two_sided mode. Control two_sided via `state/btc5_capital_stage.env` which sets the env var (but note: env var does NOT directly control this code path — only the overrides JSON does). When DIRECTIONAL_MODE is absent from the JSON, the filter is skipped = two_sided behavior.

**The code needs a proper fix:** Add a guard `if ar_dir_mode and ar_dir_mode != "two_sided":` at line 2914. This is a latent bug that will recur whenever autoresearch promotes a "two_sided" hypothesis.

### Bug 2: down_only mode during BTC UP trend = zero fills for hours

2+ hours of zero fills because BTC was in strong UP trend (UP tokens at 0.97-0.99) while we were in down_only mode. Fix: switch to two_sided mode. DOWN losses were all at 0.64/0.74 (below MIN_BUY=0.90), so there was no valid reason for down_only.

---

## 6. Crontab (Current)

```
1-56/5 * * * *    scripts/backfill_resolutions.py
4,34 * * * *      scripts/build_frontier.py
0 */2 * * *       bot/autoresearch_loop.py    (every 2h, was 6h)
0 0 * * *         scripts/backup_db.sh
0 */3 * * *       scripts/rebuild_critfiles.py
30 */2 * * *      scripts/autoresearch_deploy.py  (30min after autoresearch)
```

---

## 7. GitHub Branch Structure

- `origin/master`: Our live trading branch (THIS one). Commits: 441850e, 28f9f83.
- `origin/main`: Public/docs-focused branch with 177 commits not in master. Has `enable_spread_capture` feature. MISSING our: multi-asset slug support, toxic flow exemption, midpoint exemption, compute_strategy_fingerprint.
- `cursor/*` branches: Feature work from Cursor IDE sessions (Kalshi, wallet flow, LLM slow trading, regression tests).

**DO NOT merge `origin/main` into `master` without a careful diff review.** Main is missing our critical H4-new, H4-mid, and multi-asset changes.

What should happen next:
1. PR our `master` commits into `main` to unify them
2. Then use `main` as the primary branch going forward

---

## 8. Autoresearch System

**autoresearch_loop.py** generates hypotheses every 2h. Recent output in `data/autoresearch_results.json`.

**autoresearch_deploy.py** (new — Session 8) validates each hypothesis with replay simulator, deploys if >10% improvement. Logs to `data/autoresearch_deploy_log.json`.

**Known gaps in autoresearch:**
- Only generates direction/delta/hours hypotheses — never generates filter bypass params
- Shadow evaluator uses stale data (pre-0.90 floor era fills contaminate baselines)
- The autoresearch_overrides.json "two_sided" bug will recur if autoresearch promotes it

**Replay simulator baseline** (as of 2026-03-15): `{"total_fills": 27, "win_rate": 0.963, "total_pnl": 7.62}` at MIN_BUY_PRICE=0.90, direction=down_only, historical data.

---

## 9. Priority Next Actions

**P0 — Fix the code bug:**
File: `bot/btc_5min_maker.py` line 2914
Change: `if ar_dir_mode:` → `if ar_dir_mode and ar_dir_mode != "two_sided":`
This prevents autoresearch from accidentally promoting "two_sided" and killing all windows.

**P1 — ETH/SOL accumulation:**
ETH and SOL bots have 5 windows each (all processed since 20:01 UTC today). They need fills to advance past stage 1 probe evaluation. Watch for first fills — they confirm multi-asset slug resolution is working.

**P2 — Investigate skip_bad_book (61 windows/day):**
These are windows where the target token has no asks (market at near-100% certainty for that direction). Options:
a) Check complementary token price — if UP has no asks at 0.99, DOWN token might be at 0.01 (cheap, high-potential-payoff contrarian bet).
b) Accept as unactionable (market too certain to enter).

**P3 — Investigate skip_price_outside_guardrails at 0.97-0.99 (54 windows/day):**
Should we raise cap to 0.97? Risk: payoff at 0.97 = $0.03 per dollar risked. Even at 100% WR, tiny profit. At 0.97 you risk $0.97 to win $0.03. With $10 max: $0.31 profit. Not worth it.

**P4 — Replay at MIN_BUY=0.85:**
Historical fills at 0.85/0.86 were DOWN wins with +$0.88 to +$1.38 (bigger payoffs). Run `scripts/replay_simulator.py` with MIN_BUY_PRICE=0.85 to see if 0.85-0.89 range adds value without hurting WR.

**P5 — Stage gate advancement:**
All 3 bots stuck at stage 1 with `stage_gate_reason: "insufficient_trailing_12_live_fills"`. Need 12 recent fills to advance to stage 2 (which raises max trade from $10 to $15). BTC has 5 qualifying fills (all from 2026-03-15). Need 7 more.

**P6 — Autoresearch loop improvements:**
Add filter bypass param generation to autoresearch so it can tune TOXIC_FLOW_MIN_PRICE_EXEMPT and MIDPOINT_KILL_ZONE_MIN_PRICE_EXEMPT automatically.

---

## 10. Financial Context

- Bankroll: $390
- Current daily rate: ~$5.26/day (5 fills, $1.05 avg)
- Target: $12/day (from Session 8 dispatch)
- Path to target: 12 fills/day at same avg → need 2.4x fill rate
  - Fix stage gate (unlock stage 2 sizing) → $0/fill increase but more fills
  - ETH + SOL proving their edge → 3x assets × same fill rate = 3x fills
  - Kelly sizing at N≥50 → larger positions

The binding constraint is fill rate, not win rate. Win rate is excellent (100% at 0.90+). Fill rate is ~5/day on BTC alone. Need ETH and SOL contributing.
