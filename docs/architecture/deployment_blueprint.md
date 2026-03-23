# Deployment Blueprint: Local Twin + Lightsail Execution Split

**Author:** JJ (autonomous)
**Date:** 2026-03-22
**Status:** DESIGN (not yet implemented)

---

## 0. Problem Statement

Local and VPS have drifted apart repeatedly. The wallet address bug (wrong `POLY_SAFE_ADDRESS` in `.env`) caused weeks of bad reconciliation data. Config divergence is undetectable until something breaks. There is no local shadow trading capability that mirrors the live execution path. The SSH key path contains parentheses and breaks shell expansion.

This blueprint defines a clean split: LOCAL is the brain (decides what to trade), LIGHTSAIL is the hands (executes orders). Neither pretends to do the other's job.

---

## 1. Architecture Split

### 1.1 Local Twin (Mac: `/Users/johnbradley/Desktop/Elastifund`)

**Role:** Intelligence, research, shadow execution, promotion gating, learning.

| Capability | Entry Script | Output Artifacts |
|---|---|---|
| Shadow BTC5 signals | `scripts/run_local_twin.py --lane btc5` | `reports/autoresearch/btc5_market/latest.json` |
| Weather shadow | `scripts/run_local_twin.py --lane weather` | `reports/parallel/instance04_weather_divergence_shadow.json` |
| Wallet reconciliation | `scripts/run_local_twin.py --lane truth` | `reports/canonical_operator_truth.json` |
| Fund health monitor | `scripts/run_local_twin.py --lane monitor` | `data/local_monitor_state.json` |
| Shadow runner (all modes) | `scripts/local_shadow_runner.py --mode all` | `reports/local_shadow/` |
| Shadow vs. live comparison | `scripts/compare_shadow_vs_live.py` | `reports/shadow_vs_live_comparison.json` |
| Kernel cycle (evidence-thesis-promotion-learning) | `scripts/run_kernel_cycle.py` | `reports/kernel/` |
| BTC5 autoresearch loop | `make btc5-autoresearch-local` | `reports/btc5_autoresearch_loop/latest.md` |
| Hypothesis lab | `make btc5-hypothesis-lab` | `reports/btc5_hypothesis_frontier/` |
| Promotion gate evaluation | `scripts/run_promotion_bundle.py` | `reports/promotion/` |
| Backtesting and replay | `scripts/replay_simulator.py` | `reports/replay/` |
| Intelligence harness | `scripts/run_intelligence_harness.py` | `reports/intelligence/` |

**Hard constraints on local:**
- `BTC5_DEPLOY_MODE=shadow` is FORCED in all local runners (see `run_local_twin.py` line 89).
- `KALSHI_WEATHER_MODE=paper` is FORCED for weather lanes (line 99).
- No `.env` variable can override these; they are set in the subprocess environment after `.env` is loaded.
- Local never calls `POST /order` on Polymarket CLOB or Kalshi exchange endpoints.

### 1.2 Lightsail VPS (Dublin: `ubuntu@34.244.34.108`)

**Role:** Low-latency execution, position management, emergency stop.

| Service | Unit File | Purpose |
|---|---|---|
| `jj-live.service` | `deploy/jj-live.service` | Main JJ trading loop. Scans markets, estimates probabilities, places maker orders. |
| `btc-5min-maker.service` | `deploy/btc-5min-maker.service` | BTC 5-minute maker (Instance 2). High-frequency crypto edge. |
| `btc5-autoresearch.timer` | `deploy/btc5-autoresearch.timer` | Periodic BTC5 parameter optimization on VPS. |
| `btc5-pnl-monitor.timer` | `deploy/btc5-pnl-monitor.timer` | P&L monitoring and Telegram alerts. |
| `kalshi-weather-trader.timer` | `deploy/kalshi-weather-trader.timer` | Kalshi weather contract execution. |
| `jj-improvement-loop.timer` | `deploy/jj-improvement-loop.timer` | 30-minute flywheel cycle on VPS. |

**Hard constraints on VPS:**
- VPS `.env` is NEVER uploaded from local. It is only edited in place via `scripts/clean_env_for_profile.sh`.
- VPS is the sole authority for order submission. If VPS and local disagree on a parameter, VPS wins for execution but local logs the disagreement.
- Emergency stop: `sudo systemctl stop jj-live btc-5min-maker` kills all trading immediately. No local override can prevent this.

### 1.3 Authority Boundary

```
+-------------------------------------------------------+
|  LOCAL TWIN (Mac)                                      |
|                                                        |
|  DECIDES:                                              |
|    - Which strategies are promoted (promotion gate)    |
|    - What parameters to deploy (Kelly, thresholds)     |
|    - Which hours to trade (time-of-day filter)         |
|    - Which direction bias to use (DOWN-only, etc.)     |
|    - Whether to scale position size (stage gate)       |
|                                                        |
|  PRODUCES:                                             |
|    - config/runtime_profiles/*.json                    |
|    - config/btc5_strategy.env                          |
|    - state/btc5_autoresearch.env                       |
|    - state/btc5_capital_stage.env                      |
|                                                        |
+-------------------+-----------------------------------+
                    | deploy.sh (SCP)
                    v
+-------------------------------------------------------+
|  LIGHTSAIL VPS (Dublin)                                |
|                                                        |
|  DECIDES:                                              |
|    - Order timing (when to submit within a candle)     |
|    - Order placement (price, post-only retry ticks)    |
|    - Order cancellation (fill timeout, cross detect)   |
|    - Position exit (profit target, loss limit per fill)|
|    - Emergency stop (service restart, circuit breaker) |
|                                                        |
|  PRODUCES:                                             |
|    - data/btc_5min_maker.db (trade log)                |
|    - data/jj_trades.db (main bot trade log)            |
|    - jj_state.json (runtime state)                     |
|    - journalctl logs (systemd)                         |
|                                                        |
+-------------------------------------------------------+
```

---

## 2. Artifact Mirroring Rules

### 2.1 Local --> VPS (via `deploy.sh` SCP)

These artifacts flow from local to VPS on every deploy:

| Artifact | Path | Content |
|---|---|---|
| Bot code | `bot/*.py` | All Python modules in bot/ |
| Kalshi code | `kalshi/*.py` | Kalshi trading modules |
| Config loader | `config/__init__.py`, `config/runtime_profile.py` | Runtime profile system |
| Runtime profiles | `config/runtime_profiles/*.json` | All profile definitions |
| Strategy env | `config/btc5_strategy.env` | BTC5 parameter overrides |
| Autoresearch state | `state/btc5_autoresearch.env` | Current hypothesis parameters |
| Capital stage | `state/btc5_capital_stage.env` | Current position size stage |
| Polymarket-bot code | `polymarket-bot/src/**/*.py` | Scanner, analyzer, telegram, time_utils |
| Scripts | `scripts/*.py`, `scripts/*.sh` | Operational scripts |
| Deploy assets | `deploy/*.service`, `deploy/*.timer` | systemd unit files |
| Data files | `data/wallet_scores.db`, `data/smart_wallets.json` | Reference data |

### 2.2 VPS --> Local (NEW: fill reporting)

These artifacts flow from VPS to local. **Currently missing -- must be built.**

| Artifact | VPS Path | Local Path | Transport | Frequency |
|---|---|---|---|---|
| BTC5 trade log | `data/btc_5min_maker.db` | `data/vps_btc_5min_maker.db` | rsync over SSH | Every 5 minutes |
| Main trade log | `data/jj_trades.db` | `data/vps_jj_trades.db` | rsync over SSH | Every 5 minutes |
| JJ runtime state | `jj_state.json` | `data/vps_jj_state.json` | rsync over SSH | Every 5 minutes |
| Service status | (systemctl query) | `reports/remote_service_status.json` | SSH command | On deploy |
| BTC5 autoresearch output | `reports/btc5_autoresearch_loop/` | `reports/vps_btc5_autoresearch/` | rsync over SSH | Every 30 minutes |

**Naming convention:** VPS-originated artifacts land in the same directory structure but with a `vps_` prefix to prevent overwriting local artifacts.

### 2.3 NEVER Sync

| File | Reason |
|---|---|
| `.env` | Contains API keys, wallet addresses, platform credentials. Local and VPS have legitimately different values (e.g., `LIGHTSAIL_KEY` exists only locally). |
| `*.pem` / SSH keys | Private key material. |
| `data/shadow_signals.db` | Local-only shadow data. Would corrupt VPS state. |
| `reports/local_shadow/` | Local-only shadow outputs. |
| `logs/` | Host-specific log files. |
| `.git/` | Each host maintains its own git state. |

### 2.4 Sync Transport

**Primary:** `deploy.sh` uses SCP for local-to-VPS. This is a file copy, not a git checkout. The VPS has no git repo.

**Fill reporting (to build):** A new script `scripts/fetch_vps_fills.sh` will rsync trade databases and state files from VPS to local. This runs on a launchd timer locally.

**Config propagation:** `deploy.sh --clean-env --profile <name>` edits the VPS `.env` in place using `scripts/clean_env_for_profile.sh`. Strategy env files (`config/btc5_strategy.env`, `state/*.env`) are SCP'd as regular files and loaded via `EnvironmentFile=` directives in systemd units.

---

## 3. Freshness SLAs

| Data Class | SLA | Mechanism | Detection |
|---|---|---|---|
| **Code** | VPS within 1 commit of local `main` | `deploy.sh` after every meaningful code change | `scripts/fetch_vps_fills.sh` checks VPS file hashes against local |
| **Config (profiles)** | Propagated within 5 minutes of local change | `deploy.sh --clean-env --profile <name> --restart` | Profile mismatch logged by VPS on startup (printed in deploy verify step) |
| **Config (strategy env)** | Propagated within 5 minutes | SCP of `config/btc5_strategy.env` + service restart | Telegram alert if VPS loads stale env |
| **Market data** | Local twin sees live prices within 30 seconds | `local_shadow_runner.py` polls Polymarket/Kalshi APIs directly from Mac | Staleness counter in `data/local_monitor_state.json` |
| **Trade data** | VPS fills reach local within 60 seconds | `fetch_vps_fills.sh` rsync (5-min timer), Telegram instant notification | Comparison: `compare_shadow_vs_live.py` detects gaps |
| **Wallet state** | Reconciliation every hour | `run_local_twin.py --lane truth` on launchd timer | `canonical_operator_truth.json` `last_reconciled_at` field |

### 3.1 Staleness Detection Protocol

Each freshness SLA has a corresponding staleness check:

```
staleness = now_utc - artifact.last_updated_at
if staleness > SLA_threshold:
    send_telegram_alert(f"STALE: {artifact.name} is {staleness} old, SLA is {SLA_threshold}")
    log to reports/freshness_violations.jsonl
```

The local monitor (`scripts/local_monitor.py`) already tracks fund health. Extend it to track artifact freshness for all five SLA categories.

---

## 4. Service and Timer Map

### 4.1 VPS Services (systemd)

| Unit | Type | Schedule | Restart Policy |
|---|---|---|---|
| `jj-live.service` | `simple` | Continuous (`--continuous`) | `Restart=always`, `RestartSec=30` |
| `btc-5min-maker.service` | `simple` | Continuous (`--continuous --live`) | `Restart=on-failure`, `RestartSec=30` |
| `btc5-autoresearch.timer` | Timer | Periodic (every 5 min) | One-shot service |
| `btc5-pnl-monitor.timer` | Timer | Periodic (every 5 min) | One-shot service |
| `kalshi-weather-trader.timer` | Timer | Periodic (every 5 min) | One-shot service |
| `jj-improvement-loop.timer` | Timer | Periodic (every 30 min) | One-shot service |
| `wallet-reconciler.timer` | Timer | **TO BUILD**: every 60 min | One-shot service |

### 4.2 Local Services (launchd)

Existing launchd plists in `deploy/launchd/`:

| Plist | Script | Purpose | Schedule |
|---|---|---|---|
| `com.elastifund.local-shadow-runner` | `scripts/local_shadow_runner.py --mode all --interval 300` | Shadow BTC5 + sensorium + reconcile | KeepAlive, 5-min loop |
| `com.elastifund.btc5-local-improvement-search` | `scripts/run_btc5_local_improvement_search.py` | BTC5 parameter search | KeepAlive |
| `com.elastifund.canonical-truth-writer` | `scripts/canonical_truth_writer.py` | Wallet truth reconciliation | KeepAlive |
| `com.elastifund.evidence-bundle` | `scripts/evidence_bundle.py` | Evidence layer aggregation | KeepAlive |
| `com.elastifund.kernel-cycle` | `scripts/run_kernel_cycle.py` | Full kernel loop | KeepAlive |
| `com.elastifund.learning-bundle` | `scripts/learning_bundle.py` | Post-trade learning | KeepAlive |
| `com.elastifund.promotion-bundle` | `scripts/run_promotion_bundle.py` | Promotion gate evaluation | KeepAlive |
| `com.elastifund.thesis-bundle` | `scripts/thesis_bundle.py` | Thesis generation | KeepAlive |
| `com.elastifund.weather-shadow-continuous` | `scripts/weather_shadow_continuous.py` | Continuous weather shadow | KeepAlive |
| `com.elastifund.weather-shadow-lane` | (weather shadow lane) | Weather divergence detection | KeepAlive |

**To build:**

| Plist | Script | Purpose | Schedule |
|---|---|---|---|
| `com.elastifund.fetch-vps-fills` | `scripts/fetch_vps_fills.sh` | rsync trade DBs from VPS | Every 5 minutes |
| `com.elastifund.freshness-monitor` | `scripts/freshness_monitor.py` | Check all SLA thresholds, alert on violations | Every 5 minutes |

### 4.3 Service Discovery

Services do not discover each other directly. They communicate through shared artifacts on the filesystem:

- **VPS services** read `.env` and `config/` files. They write to `data/` and `reports/`.
- **Local services** read `.env` and `config/` files. They write to `reports/` and `data/`.
- **Cross-host communication** happens only through: (a) `deploy.sh` SCP (local-to-VPS), (b) `fetch_vps_fills.sh` rsync (VPS-to-local), (c) Telegram notifications (both directions to John's phone).

There is no RPC, no message queue, no shared database. This is intentional. The failure mode of a missing file is "stale data" not "system crash."

### 4.4 Health Checks and Alerting

| Check | Location | Frequency | Alert Channel |
|---|---|---|---|
| `systemctl is-active jj-live` | VPS | On deploy + on manual SSH | deploy.sh stdout |
| `systemctl is-active btc-5min-maker` | VPS | On deploy | deploy.sh stdout |
| BTC5 P&L breach | VPS | Every 5 min (`btc5-pnl-monitor`) | Telegram |
| Wallet balance change | Local | Every 60 min (truth lane) | Telegram |
| Service down | VPS | `RestartSec=30` auto-restart | journalctl (no proactive alert yet) |
| Freshness SLA violation | Local | Every 5 min (freshness monitor) | Telegram |

**Gap:** There is no proactive Telegram alert when a VPS service fails to restart. The `Restart=always` policy handles transient failures, but a persistent crash (e.g., missing dependency) will silently restart-loop. The freshness monitor will catch this indirectly (stale trade data), but a direct systemd failure alert should be added to the VPS improvement loop.

---

## 5. Local-vs-Remote Authority Boundaries

### 5.1 LOCAL Has Authority Over

| Domain | Mechanism | Examples |
|---|---|---|
| Strategy selection | Promotion gate in `run_promotion_bundle.py` | "BTC5 DOWN-only passes gate; UP mode does not" |
| Parameter optimization | Autoresearch loop, hypothesis lab | Kelly fraction, time-of-day filter hours, direction bias |
| Promotion decisions | Stage gate evaluation (DISPATCH_102 pattern) | "Hold at $5/trade; do not scale to $10" |
| Research direction | Kernel cycle, novelty discovery | "Investigate VPIN gating next" |
| Config generation | Profile JSON + strategy env files | `config/runtime_profiles/maker_velocity_live.json` |
| Deploy timing | Human (John) runs `deploy.sh` | "Deploy after hypothesis lab completes" |

### 5.2 VPS Has Authority Over

| Domain | Mechanism | Examples |
|---|---|---|
| Order execution | `bot/btc_5min_maker.py` runtime logic | Post-only retry ticks, cross detection |
| Position management | `bot/jj_live.py` continuous loop | Open position count, resolution tracking |
| Emergency stop | `systemctl stop` or daily loss circuit breaker | Stop all trading if daily P&L breaches limit |
| Fill/skip decisions | BTC5 delta, toxicity, regime filters at execution time | "skip_delta_too_large" at current volatility |
| Runtime state | `jj_state.json`, `data/btc_5min_maker.db` | VPS state is authoritative for what actually happened |

### 5.3 Shared Authority (Requires Both)

| Domain | Local Role | VPS Role | Conflict Resolution |
|---|---|---|---|
| Risk parameters | Local proposes new Kelly/position size | VPS applies on next restart | If VPS `.env` disagrees with deployed config, the `clean_env_for_profile.sh` script overwrites VPS `.env` values on deploy. Profile in `.env` is authoritative post-deploy. |
| Time-of-day filter | Local generates filter hours from hypothesis lab | VPS applies via `BTC5_SUPPRESS_HOURS_ET` env var | Deployed env file wins. Local cannot change VPS behavior without a deploy. |
| Capital stage | Local evaluates promotion gate | VPS reads `state/btc5_capital_stage.env` | File is SCP'd on deploy. No runtime hot-reload; requires service restart. |

### 5.4 Config Disagreement Detection

On every deploy, the verify step (lines 339-357 of `deploy.sh`) prints the active profile, thresholds, paper mode, and execution mode from the VPS. Local should capture this output and compare against the intended profile.

**New: post-deploy config hash check.**

After deploy, compute a hash of the deployed config files on VPS and compare against local:

```bash
# In deploy.sh, after sync completes:
REMOTE_HASH=$("${SSH_CMD[@]}" "$VPS" "cd $BOT_DIR && cat config/runtime_profiles/*.json config/btc5_strategy.env state/*.env 2>/dev/null | sha256sum | cut -d' ' -f1")
LOCAL_HASH=$(cat config/runtime_profiles/*.json config/btc5_strategy.env state/*.env 2>/dev/null | sha256sum | cut -d' ' -f1)
if [ "$REMOTE_HASH" != "$LOCAL_HASH" ]; then
    echo "  WARNING: Config hash mismatch after deploy"
    echo "    Local:  $LOCAL_HASH"
    echo "    Remote: $REMOTE_HASH"
fi
```

---

## 6. Operational Rollout Order

### Step 1: Fix deploy.sh SSH key path

**Problem:** The SSH key at `~/Downloads/LightsailDefaultKey-eu-west-1 (1).pem` has parentheses in the filename. The `.env` currently points to `LIGHTSAIL_KEY=/Users/johnbradley/.ssh/lightsail_new.pem`.

**Fix:**
```bash
# Create a symlink with a clean name (idempotent)
ln -sf "$HOME/Downloads/LightsailDefaultKey-eu-west-1 (1).pem" \
       "$HOME/.ssh/lightsail_new.pem"
chmod 600 "$HOME/.ssh/lightsail_new.pem"
```

**Verification:** `ssh -i ~/.ssh/lightsail_new.pem ubuntu@34.244.34.108 'hostname'` should print the VPS hostname.

**Status:** `.env` already has `LIGHTSAIL_KEY=/Users/johnbradley/.ssh/lightsail_new.pem`. The symlink just needs to exist and point to the actual key file.

### Step 2: Add VPS-to-local fill reporting

**Build:** `scripts/fetch_vps_fills.sh`

```bash
#!/usr/bin/env bash
# Fetch trade databases and state from VPS to local.
# Runs on a 5-minute launchd timer.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
source <(grep -E '^(LIGHTSAIL_KEY|VPS_USER|VPS_IP)=' "$PROJECT_DIR/.env" || true)

SSH_KEY="${LIGHTSAIL_KEY:-$HOME/.ssh/lightsail_new.pem}"
VPS="${VPS_USER:-ubuntu}@${VPS_IP:?}"
BOT_DIR="/home/ubuntu/polymarket-trading-bot"

rsync -az -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=no" \
    "$VPS:$BOT_DIR/data/btc_5min_maker.db" \
    "$PROJECT_DIR/data/vps_btc_5min_maker.db"

rsync -az -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=no" \
    "$VPS:$BOT_DIR/data/jj_trades.db" \
    "$PROJECT_DIR/data/vps_jj_trades.db" 2>/dev/null || true

rsync -az -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=no" \
    "$VPS:$BOT_DIR/jj_state.json" \
    "$PROJECT_DIR/data/vps_jj_state.json" 2>/dev/null || true

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] VPS fills fetched"
```

**Launchd plist:** `deploy/launchd/com.elastifund.fetch-vps-fills.plist` running every 300 seconds.

**Install:**
```bash
cp deploy/launchd/com.elastifund.fetch-vps-fills.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.elastifund.fetch-vps-fills.plist
```

### Step 3: Set up local shadow trader

**Already exists.** The infrastructure is built:
- `scripts/run_local_twin.py` orchestrates all shadow lanes.
- `scripts/local_shadow_runner.py` runs BTC5/sensorium/reconcile in shadow mode.
- `deploy/launchd/com.elastifund.local-shadow-runner.plist` is the launchd unit.

**Remaining work:**
1. Install the launchd plist if not already loaded: `launchctl load ~/Library/LaunchAgents/com.elastifund.local-shadow-runner.plist`
2. Verify shadow signals are being written to `reports/local_shadow/`.
3. Wire `compare_shadow_vs_live.py` to consume both `data/vps_btc_5min_maker.db` (from Step 2) and `data/shadow_signals.db` (from local shadow runner).

### Step 4: Add freshness monitoring

**Build:** `scripts/freshness_monitor.py`

Checks all five SLA categories:

| Check | Source Artifact | SLA |
|---|---|---|
| Code freshness | Hash comparison of `bot/*.py` local vs VPS | Deploy within 1 hour of code change on main |
| Config freshness | `reports/remote_service_status.json` | Profile match within 5 minutes of deploy |
| Market data freshness | `data/local_monitor_state.json` | Prices within 30 seconds |
| Trade data freshness | `data/vps_btc_5min_maker.db` mtime | Updated within 60 seconds of VPS fill |
| Wallet freshness | `reports/canonical_operator_truth.json` | Reconciled within 60 minutes |

On violation: write to `reports/freshness_violations.jsonl` and send Telegram alert.

**Launchd plist:** `deploy/launchd/com.elastifund.freshness-monitor.plist` running every 300 seconds.

### Step 5: Enable intelligence harness as deployment gate

**Build:** Add a pre-deploy check to `deploy.sh`:

```bash
# Before syncing files, run the intelligence harness gate
if [ -f "$PROJECT_DIR/reports/intelligence/gate_result.json" ]; then
    GATE=$(python3 -c "
import json, sys
from datetime import datetime, timezone, timedelta
r = json.load(open('$PROJECT_DIR/reports/intelligence/gate_result.json'))
age = (datetime.now(timezone.utc) - datetime.fromisoformat(r['timestamp'])).total_seconds()
if age > 3600:
    print('STALE')
elif r.get('gate') == 'PASS':
    print('PASS')
else:
    print('FAIL')
")
    if [ "$GATE" = "FAIL" ]; then
        echo "  BLOCKED: Intelligence harness gate FAILED. Fix issues before deploying."
        echo "  Run: python3 scripts/run_intelligence_harness.py"
        exit 1
    elif [ "$GATE" = "STALE" ]; then
        echo "  WARNING: Intelligence harness result is >1h old. Consider re-running."
    fi
fi
```

This is advisory initially (warning only for stale results) and blocking only when the gate explicitly fails. A missing gate file does not block deployment -- that would prevent bootstrapping.

---

## 7. Invariants (Things That Must Always Be True)

1. **Local never submits real orders.** Every local runner forces `BTC5_DEPLOY_MODE=shadow` or `KALSHI_WEATHER_MODE=paper` in the subprocess environment, regardless of what `.env` says.

2. **VPS `.env` is never uploaded from local.** The `deploy.sh` script explicitly does not SCP `.env`. Config changes go through `clean_env_for_profile.sh` which edits the remote `.env` in place.

3. **VPS state is authoritative for what happened.** If `data/vps_btc_5min_maker.db` disagrees with `data/btc_5min_maker.db` (local shadow), the VPS database represents reality.

4. **Local config is authoritative for what should happen.** Profile JSONs, strategy envs, and capital stage files are generated locally and deployed to VPS. The VPS does not generate its own config.

5. **No parameter change is invisible.** Every deploy prints the active profile and thresholds. The post-deploy hash check detects config drift. The freshness monitor catches stale configs.

6. **Telegram is the out-of-band alert channel.** Both local and VPS can send Telegram messages. This is the only cross-host communication channel besides SSH/SCP.

---

## 8. File Manifest: What Exists vs. What To Build

### Exists and Works

| File | Status |
|---|---|
| `scripts/deploy.sh` | Working. 435 lines. Handles code sync, profile clean, service restart, BTC5/Kalshi/loop/monitor setup. |
| `scripts/run_local_twin.py` | Working. Orchestrates shadow lanes (btc5, weather, monitor, truth, sensorium, kernel, novelty, architecture_alpha, promotion, kimi). |
| `scripts/local_shadow_runner.py` | Working. Shadow BTC5 + sensorium + reconcile. |
| `scripts/compare_shadow_vs_live.py` | Working. Reads shadow_signals.db and btc_5min_maker.db. |
| `scripts/local_monitor.py` | Working. Fund health via Polymarket API. |
| `scripts/canonical_truth_writer.py` | Working. Wallet truth reconciliation. |
| `deploy/jj-live.service` | Working. Main bot systemd unit. |
| `deploy/btc-5min-maker.service` | Working. BTC5 systemd unit with env layering. |
| `deploy/launchd/com.elastifund.local-shadow-runner.plist` | Exists. Needs install verification. |
| 9 other launchd plists | Exist in `deploy/launchd/`. Need install verification. |

### Must Build

| File | Purpose | Priority |
|---|---|---|
| `scripts/fetch_vps_fills.sh` | rsync VPS trade DBs to local | P0 (blocks shadow-vs-live comparison) |
| `deploy/launchd/com.elastifund.fetch-vps-fills.plist` | launchd timer for fill fetch | P0 |
| `scripts/freshness_monitor.py` | SLA violation detection + Telegram alert | P1 |
| `deploy/launchd/com.elastifund.freshness-monitor.plist` | launchd timer for freshness checks | P1 |
| `deploy/wallet-reconciler.service` + `.timer` | VPS-side hourly wallet reconciliation | P2 |
| Post-deploy config hash check (in deploy.sh) | Detect config drift immediately | P1 |
| Intelligence harness gate (in deploy.sh) | Block bad deploys | P2 |

---

## 9. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| SSH key path breaks again | Medium | Deploy fails silently | Symlink at stable path; deploy.sh checks key exists before proceeding (already does, line 132) |
| `.env` drift between local and VPS | High (has happened) | Wrong wallet address, bad data for weeks | Post-deploy hash check; freshness monitor; `.env` NEVER synced automatically |
| Local shadow diverges from VPS execution | Medium | Shadow results are meaningless | `compare_shadow_vs_live.py` run after every fill batch; divergence triggers alert |
| VPS service crash-loops undetected | Medium | Trading stops, opportunity cost | Freshness monitor catches stale trade data within 5 minutes; direct systemd failure alert is a P2 build item |
| Config change deployed without restart | Medium | VPS runs stale parameters | `deploy.sh --restart` is the standard command; add explicit warning if `--clean-env` is used without `--restart` |
| rsync of trade DB corrupts in-flight writes | Low | Missing or partial fill records | rsync uses temp files + atomic rename by default; SQLite WAL mode handles concurrent reads; worst case is a 5-minute delay in next sync |

---

## 10. Summary: One Sentence Per Section

1. **Architecture Split:** Local is the brain, VPS is the hands, and neither pretends to be the other.
2. **Artifact Mirroring:** Code and config flow local-to-VPS via SCP; fills and state flow VPS-to-local via rsync; `.env` never crosses the boundary.
3. **Freshness SLAs:** Code within 1 commit, config within 5 minutes, prices within 30 seconds, fills within 60 seconds, wallet within 1 hour.
4. **Service Map:** VPS runs 6+ systemd units for execution; local runs 10+ launchd agents for intelligence; they share artifacts on disk, not RPC.
5. **Authority Boundaries:** Local decides what to trade and at what size; VPS decides how and when to execute; risk parameter changes require a deploy (both hosts involved).
6. **Rollout Order:** Fix SSH key symlink, build fill reporting, verify shadow trader, add freshness monitoring, gate deploys on intelligence harness.

## 11. Staged Deployment Order

Use this order when moving proof-carrying modules toward live capital:

1. Local twin shadow
2. Lightsail truth writers + event tape
3. Strike desk in shadow
4. Promotion manager enforcement
5. Seed-live Resolution Sniper
6. Whale Copy
7. Neg-Risk

The local twin remains the replay and mutation environment. Lightsail remains the only live executor. Anything that cannot survive the intelligence harness stays out of the live path.
