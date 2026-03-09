# CODEX DISPATCH: Maker Velocity Full Capital Deployment

**Date:** 2026-03-09
**Priority:** IMMEDIATE — all tasks must complete within 60 minutes
**Capital:** $227.38 available cash on Polymarket ($245.65 portfolio, 3 open positions ~$18)
**Objective:** Deploy all available capital into maker-velocity trades on fast-resolving markets

---

## OVERVIEW

We are switching from the `blocked_safe` profile to `maker_velocity_live` on the Dublin VPS. This deploys real maker orders across crypto, politics, weather, and economic markets with <24h resolution. The profile, bot config, and BTC 5-min maker have already been updated. What remains is:

1. A market scanner to identify the BEST trades right now
2. A pre-flight validation script to verify everything works before deploy
3. A systemd unit for the BTC 5-min bot (it currently has none)
4. Update CLAUDE.md current state to reflect the mode switch

Each Codex instance below is self-contained. They can run in parallel.

---

## INSTANCE 1: Live Market Scanner — Find Best Trades Right Now

**Files to read first:**
- `bot/jj_live.py` (lines 1-100 for config, lines 700-900 for market scanning logic)
- `bot/ensemble_estimator.py` (probability estimation)
- `bot/maker_velocity_blitz.py` (velocity scoring and allocation)
- `config/runtime_profiles/maker_velocity_live.json` (active profile)
- `FAST_TRADE_EDGE_ANALYSIS.md` (current pipeline output)

**Task:** Create `scripts/scan_live_markets_now.py` — a standalone script that:

1. Pulls all active markets from Polymarket Gamma API (`https://gamma-api.polymarket.com/markets?active=true&limit=500`)
2. Filters to markets resolving within 24 hours (`end_date_iso` or `resolution_date` within 24h of now)
3. Filters to allowed categories: politics (priority 3), weather (3), economic (2), crypto (3), financial_speculation (1), geopolitical (1). Reject sports, fed_rates, unknown.
4. For each passing market, fetches the CLOB order book (`https://clob.polymarket.com/book?token_id={token_id}`)
5. Calculates the spread (best_ask - best_bid) and liquidity (sum of bid/ask depth at top 3 levels)
6. Ranks markets by **velocity score**: `estimated_edge / resolution_hours` where `estimated_edge = abs(0.50 - yes_price)` as a naive proxy (markets priced far from 50% have higher implied edge for the side closer to 0 or 1)
7. Outputs a JSON report to `reports/live_market_scan.json` with the top 30 markets ranked by velocity score, including: market question, slug, category, YES price, NO price, spread, liquidity depth, resolution date, hours to resolution, velocity score, recommended side (YES if price < 0.50, NO if price > 0.50), recommended order price (best_bid + 1 tick for YES, or best_bid + 1 tick for NO side)

**Constraints:**
- Pure Python 3.12, use `aiohttp` for HTTP
- No API keys needed (Gamma API and CLOB book endpoint are public)
- Must handle pagination (Gamma API returns max 100 per page, use `offset` parameter)
- Must handle markets with missing/malformed data gracefully
- Tick size is $0.01 on Polymarket CLOB
- Price range filter: only include markets where YES is between 0.05 and 0.95

**Output format:**
```json
{
  "scan_timestamp": "2026-03-09T...",
  "total_markets_scanned": 7050,
  "markets_passing_filters": 42,
  "top_markets": [
    {
      "question": "...",
      "slug": "...",
      "condition_id": "...",
      "tokens": [{"token_id": "...", "outcome": "YES"}, ...],
      "category": "politics",
      "yes_price": 0.35,
      "no_price": 0.65,
      "spread": 0.02,
      "bid_depth_usd": 150.0,
      "ask_depth_usd": 200.0,
      "resolution_date": "2026-03-10T00:00:00Z",
      "hours_to_resolution": 12.5,
      "velocity_score": 0.012,
      "recommended_side": "YES",
      "recommended_price": 0.36,
      "recommended_shares": 13.89,
      "recommended_notional_usd": 5.0
    }
  ]
}
```

**Tests:** Create `tests/test_scan_live_markets.py` with unit tests for the filtering, scoring, and ranking logic using mock API responses.

**Validation:** Run the script at the end: `python scripts/scan_live_markets_now.py` and verify the JSON report is generated.

---

## INSTANCE 2: Pre-Flight Validation Script

**Files to read first:**
- `config/runtime_profile.py` (profile loading)
- `config/runtime_profiles/maker_velocity_live.json`
- `bot/runtime_profile.py` (bundle interface)
- `bot/jj_live.py` (lines 400-620 for config loading, lines 2900-2940 for JJLiveBot.__init__)
- `bot/execution_readiness.py` (existing readiness checks)
- `scripts/deploy.sh` (deployment flow)

**Task:** Create `scripts/preflight_maker_velocity.py` — a comprehensive pre-flight check that validates everything needed before deploying `maker_velocity_live`:

1. **Profile loads correctly**: Load `maker_velocity_live` profile via `config.runtime_profile.load_runtime_profile(profile_name="maker_velocity_live")`. Verify all fields parse. Print key config: paper_trading, allow_order_submission, execution_mode, crypto priority, max_position_usd, daily_loss_usd, kelly_fraction, max_open_positions, scan_interval, max_resolution_hours.

2. **Environment variables present**: Check that these env vars exist (from .env or environment): `POLY_PRIVATE_KEY` or `POLYMARKET_PK`, `POLY_SAFE_ADDRESS` or `POLYMARKET_FUNDER`, `ANTHROPIC_API_KEY` (for LLM signals). Don't print values — just confirm present/missing.

3. **Python imports work**: Verify these imports succeed:
   - `from bot.jj_live import JJLiveBot`
   - `from bot.ensemble_estimator import EnsembleEstimator`
   - `from bot.vpin_toxicity import VPINDetector`
   - `from bot.ws_trade_stream import TradeStreamManager`
   - `from bot.maker_velocity_blitz import evaluate_blitz_launch_ready`
   - `from bot.btc_5min_maker import BTC5MinMakerBot, MakerConfig`

4. **Syntax check all bot files**: `py_compile.compile()` every `bot/*.py` file.

5. **Profile contract validation**: Assert that:
   - `paper_trading == False`
   - `allow_order_submission == True`
   - `category_priorities["crypto"] >= 1`
   - `max_position_usd >= 5.0`
   - `kelly_fraction > 0`
   - `max_resolution_hours <= 48`
   - `scan_interval_seconds <= 60`

6. **Network connectivity** (optional, skip if no env vars): Try a GET to `https://gamma-api.polymarket.com/markets?limit=1` and verify 200 response.

7. **Print summary**: GREEN/RED status for each check, overall GO/NO-GO determination.

**Output:** Both human-readable console output and `reports/preflight_maker_velocity.json` with structured results.

**Tests:** Create `tests/test_preflight_maker_velocity.py` with tests for the validation logic (mock the imports and env checks).

---

## INSTANCE 3: BTC 5-Min Bot Systemd Service

**Files to read first:**
- `bot/btc_5min_maker.py` (entry point, CLI args)
- `deploy/jj-improvement-loop.service` (example systemd unit)
- `deploy/kalshi-weather-trader.service` (another example)
- `scripts/deploy.sh` (how files get to VPS)

**Task:** Create the systemd service file and deployment support for the BTC 5-min maker bot:

1. **Create `deploy/btc-5min-maker.service`:**
```ini
[Unit]
Description=BTC 5-Minute Maker Bot (Instance 2)
After=network-online.target
Wants=network-online.target
# Don't conflict with jj-live — they run independently
# but share the same Polymarket account

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/polymarket-trading-bot
Environment=PYTHONPATH=/home/ubuntu/polymarket-trading-bot:/home/ubuntu/polymarket-trading-bot/bot:/home/ubuntu/polymarket-trading-bot/polymarket-bot
EnvironmentFile=/home/ubuntu/polymarket-trading-bot/.env
ExecStart=/home/ubuntu/polymarket-trading-bot/venv/bin/python3 bot/btc_5min_maker.py --continuous --live --verbose
Restart=on-failure
RestartSec=30
StandardOutput=journal
StandardError=journal
SyslogIdentifier=btc5maker

[Install]
WantedBy=multi-user.target
```

2. **Update `scripts/deploy.sh`** to also sync `deploy/btc-5min-maker.service` and optionally install + start it. Add a `--btc5` flag that, when present:
   - Copies `deploy/btc-5min-maker.service` to `/etc/systemd/system/` on VPS
   - Runs `systemctl daemon-reload`
   - Starts the service
   - Shows status

3. **Create `scripts/btc5_status.sh`** — a quick status check script:
```bash
#!/usr/bin/env bash
# Check BTC 5-min maker bot status on VPS
SSH_KEY="${LIGHTSAIL_KEY:-$HOME/.ssh/lightsail.pem}"
VPS="${VPS_USER:-ubuntu}@${VPS_IP:?Set VPS_IP}"
ssh -i "$SSH_KEY" "$VPS" "
  echo '=== Service Status ==='
  sudo systemctl is-active btc-5min-maker.service 2>/dev/null || echo 'not installed'
  echo
  echo '=== Last 20 Log Lines ==='
  sudo journalctl -u btc-5min-maker.service -n 20 --no-pager 2>/dev/null || echo 'no logs'
  echo
  echo '=== SQLite Summary ==='
  cd /home/ubuntu/polymarket-trading-bot
  source venv/bin/activate
  export PYTHONPATH='/home/ubuntu/polymarket-trading-bot:/home/ubuntu/polymarket-trading-bot/bot:/home/ubuntu/polymarket-trading-bot/polymarket-bot'
  python3 bot/btc_5min_maker.py --status 2>/dev/null || echo 'status unavailable'
"
```

**Tests:** Create `tests/test_btc5min_service.py` that:
- Validates the .service file parses correctly (check required keys exist)
- Validates the ExecStart command references the correct Python file
- Validates WorkingDirectory and EnvironmentFile paths are consistent

---

## INSTANCE 4: CLAUDE.md State Update + Deploy Manifest

**Files to read first:**
- `CLAUDE.md` (current state section, lines marked "Current State")
- `DEPLOY_MAKER_VELOCITY.md` (deployment instructions)
- `config/runtime_profiles/maker_velocity_live.json`
- `COMMAND_NODE.md` (look for "Current State" section)

**Task:** Update the canonical state documents to reflect the maker velocity deployment:

1. **Update `CLAUDE.md` Current State section:**
   - Capital: $245.65 Polymarket ($227.38 available) + $100 Kalshi = $345.65 total
   - Live trading: MAKER VELOCITY LIVE — `maker_velocity_live` profile deployed
   - Paper trades: Historical (pre-deployment)
   - Live config: $10/position, uncapped daily loss, 0.25 Kelly, 30 max positions, 30s scan, 24h max resolution
   - Execution mode: 100% Post-Only maker orders (unchanged)
   - Category gates: crypto=3 (UNLOCKED), politics=3, weather=3, economic=2
   - A6/B1: DISABLED (kill watch still active, deadline March 14)
   - BTC 5-min maker: Instance 2, $5/trade, uncapped daily, running as separate service
   - Data target: 100 resolved trades in 7 days — ACTIVE COLLECTION
   - Structural gates: Superseded by maker velocity deployment
   - Next action: Monitor fill rates, win rates, and VPIN accuracy. First data review at 50 resolved trades.

2. **Update `COMMAND_NODE.md`** with the same state changes (find the "Current State" or equivalent section).

3. **Create `reports/deployment_manifest_maker_velocity.json`:**
```json
{
  "deployment_id": "maker_velocity_live_20260309",
  "profile": "maker_velocity_live",
  "deployed_at": "2026-03-09T...",
  "capital_available_usd": 227.38,
  "capital_total_usd": 345.65,
  "platforms": {
    "polymarket": {
      "available_usd": 227.38,
      "portfolio_usd": 245.65,
      "open_positions": 3,
      "profile": "maker_velocity_live",
      "execution_mode": "post_only_maker"
    },
    "kalshi": {
      "available_usd": 100.00,
      "profile": "separate_weather_instance"
    }
  },
  "risk_parameters": {
    "max_position_usd": 10.0,
    "daily_loss_cap_usd": "uncapped",
    "kelly_fraction": 0.25,
    "max_open_positions": 30,
    "max_resolution_hours": 24.0,
    "min_edge": 0.03
  },
  "instances": {
    "jj_live": {
      "profile": "maker_velocity_live",
      "categories": ["politics", "weather", "economic", "crypto", "geopolitical", "financial_speculation"],
      "scan_interval_seconds": 30
    },
    "btc_5min_maker": {
      "service": "btc-5min-maker.service",
      "trade_size_usd": 5.0,
      "daily_loss_cap_usd": "uncapped",
      "windows_per_day": 288
    }
  },
  "data_collection_target": {
    "trades": 100,
    "timeline_days": 7,
    "first_review_at_trades": 50
  }
}
```

**Tests:** Verify CLAUDE.md and COMMAND_NODE.md parse without errors. Verify the manifest JSON is valid.

---

## DEPLOYMENT SEQUENCE (After All Instances Complete)

This is what John runs manually after Codex instances finish:

```bash
# 1. Run pre-flight
python scripts/preflight_maker_velocity.py

# 2. Scan live markets (see what's tradeable right now)
python scripts/scan_live_markets_now.py
cat reports/live_market_scan.json | python3 -m json.tool | head -60

# 3. Deploy to VPS (one command)
./scripts/deploy.sh --clean-env --profile maker_velocity_live --restart

# 4. Deploy BTC 5-min bot
./scripts/deploy.sh --btc5

# 5. Verify both services running
ssh -i "$SSH_KEY" "$VPS" "sudo systemctl is-active jj-live.service btc-5min-maker.service"

# 6. Watch first cycle
ssh -i "$SSH_KEY" "$VPS" "sudo journalctl -u jj-live.service -f --no-pager"
```

---

## WHAT CODEX CANNOT DO (John Must Do Manually)

- SSH to Dublin VPS (no SSH keys in Codex environment)
- Run `deploy.sh` (requires VPS_IP, SSH key)
- Verify Polymarket balance (requires browser or API key)
- Monitor live trading (requires VPS access)
- Make risk decisions about live capital

---

## SUCCESS CRITERIA

All four instances pass their tests. The pre-flight script outputs GO. The market scanner finds >0 tradeable markets. The systemd service file is valid. CLAUDE.md reflects the new state. John can deploy with a single `deploy.sh` command.

---

## EXISTING POSITIONS (Do Not Liquidate)

From portfolio screenshot (2026-03-09):

| Market | Side | Avg | Now | Shares | Value | P&L |
|--------|------|-----|-----|--------|-------|-----|
| Aziz Akhannouch out as Morocco PM | No 11¢ | 11¢ | 16.7¢ | 46.5 | $7.77 | +$2.65 (51.82%) |
| US strikes Yemen by March 31 | Yes 36¢ | 36¢ | 43.3¢ | 13.7 | $5.95 | +$1.00 (20.28%) |
| Bank of Russia no change | Yes 38¢ | 38¢ | 34¢ | 13.2 | $4.47 | -$0.53 (10.53%) |

These are already placed maker positions. Leave them. Deploy new capital ($227.38) into additional positions.

---

*End of Codex Dispatch. Four instances, parallel execution, one-hour completion target.*
