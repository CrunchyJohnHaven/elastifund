# Local Twin Entrypoints

**Role:** Reference
**Canonical landing page:** [docs/architecture/README.md](../architecture/README.md)

Local shadow execution against live APIs. No live orders submitted from the Mac.
Lightsail remains the primary execution host; this twin is for testing, debugging,
and running mutation loops against real data.

---

## Quick Start

```bash
cd /Users/johnbradley/Desktop/Elastifund

# Run all lanes once
python3 scripts/run_local_twin.py

# Continuous daemon (btc5 + weather + truth), 5-min cycles
python3 scripts/run_local_twin.py --daemon

# Skip VPS SSH in monitor lane
python3 scripts/run_local_twin.py --no-ssh

# Revenue-first strike factory
python3 scripts/run_local_twin.py --lane strike_factory
```

---

## Individual Lanes

### BTC5 Improvement Search (shadow)

Runs market and command_node mutation lanes against the local policy frontier.
Forced to `BTC5_DEPLOY_MODE=shadow` — writes autoresearch artifacts, no orders.

```bash
python3 scripts/run_local_twin.py --lane btc5

# or directly:
BTC5_DEPLOY_MODE=shadow python3 scripts/run_btc5_local_improvement_search.py \
  --lanes market,command_node --repo-root .
```

Output: `reports/autoresearch/btc5_market/latest.json`, `reports/autoresearch/command_node/latest.json`

---

### Weather Shadow Lane (Instance 4)

Pulls NWS forecasts + Kalshi markets, detects divergence, writes shadow artifact.
Forced to `KALSHI_WEATHER_MODE=paper` — no live Kalshi orders.

```bash
python3 scripts/run_local_twin.py --lane weather

# or directly:
KALSHI_WEATHER_MODE=paper python3 scripts/run_instance4_weather_shadow_lane.py
```

Output: `reports/parallel/instance04_weather_divergence_shadow.json`

---

### Fund Health Monitor

Single-snapshot fund health report from Polymarket data API + optional VPS SSH.

```bash
python3 scripts/run_local_twin.py --lane monitor

# Skip VPS SSH (works without lightsail key):
python3 scripts/run_local_twin.py --lane monitor --no-ssh

# or directly:
python3 scripts/local_monitor.py --once --no-ssh
```

Output: `data/local_monitor_state.json`

---

### Canonical Truth Reconciliation

Fresh Polymarket API pull reconciled with local runtime artifacts. Produces the
authoritative operator packet: mode, exposure, control posture.

```bash
python3 scripts/run_local_twin.py --lane truth

# Print without writing:
python3 scripts/canonical_truth_writer.py --check-only

# or directly:
python3 scripts/canonical_truth_writer.py
```

Output: `reports/canonical_operator_truth.json`, `reports/wallet_live_snapshot_latest.json`, `data/finance_imports/account_polymarket.csv`

### Strike Factory

Revenue-first deterministic queue, event tape, and promotion snapshot.

```bash
python3 scripts/run_local_twin.py --lane strike_factory
python3 scripts/run_strike_factory.py
```

Output: `reports/strike_factory/latest.json`, `reports/strike_factory/latest.md`

---

---

## Kernel and Self-Improvement Lanes

### Kernel Cycle (shadow)

Runs the full Evidence → Thesis → Promotion → Learning pipeline locally in shadow mode.

```bash
python3 scripts/run_local_twin.py --lane kernel

# Dry-run (assess only, no subprocess calls):
python3 scripts/run_kernel_cycle.py --dry-run

# Check current kernel state:
cat reports/kernel/kernel_state.json | python3 -m json.tool
```

Output: `reports/kernel/kernel_state.json`, `reports/kernel/cycle_log.jsonl`

---

### Sensorium (evidence aggregator)

Aggregates wallet, weather, BTC5, and mode signals into the evidence bundle.

```bash
python3 scripts/run_local_twin.py --lane sensorium

# or directly:
python3 scripts/run_sensorium.py
```

Output: `reports/parallel/instance01_sensorium_latest.json`, `reports/evidence_bundle.json`

---

### Novelty Discovery

Converts sensorium observations into novel_discovery and novel_edge artifacts.
Only uses fallback when sensorium is absent or stale.

```bash
python3 scripts/run_local_twin.py --lane novelty
```

Output: `reports/parallel/novelty_discovery.json`, `reports/parallel/novel_edge.json`

---

### Architecture Alpha

Mines constitution candidates from research_os, thesis_candidates, and kernel state.

```bash
python3 scripts/run_local_twin.py --lane architecture_alpha
python3 scripts/run_architecture_alpha.py --dry-run  # no writes
```

Output: `reports/architecture_alpha/latest.json`, `reports/architecture_alpha/history.jsonl`

---

### Promotion Bundle

Merges opportunity_exchange + capital_lab + counterfactual into one promotion decision per thesis.

```bash
python3 scripts/run_local_twin.py --lane promotion
python3 scripts/run_promotion_bundle.py --dry-run
```

Output: `reports/promotion_bundle.json`, `reports/promotion_bundle_history.jsonl`

---

### Kimi/Moonshot Learning

Failure clustering and candidate triage via Kimi API. Requires MOONSHOT_API_KEY in .env.

```bash
python3 scripts/run_local_twin.py --lane kimi

# Check activation status:
cat reports/autoresearch/providers/moonshot/latest.json
```

Output: `reports/autoresearch/providers/moonshot/latest.json`, `history.jsonl`

---

### Intelligence Harness (acceptance gate)

Runs four synthetic scenarios + historical replay regression. Gate pass = self-improvement changes are safe.

```bash
python3 scripts/run_local_twin.py --lane harness
python3 scripts/run_intelligence_harness.py --verbose
```

Output: `reports/intelligence_harness/latest.json`

---

## LaunchAgent Daemons (macOS)

Two daemons are available for standing local operation.

### Install all local daemons

```bash
# BTC5 local improvement search (existing, 60s)
cp deploy/launchd/com.elastifund.btc5-local-improvement-search.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.elastifund.btc5-local-improvement-search.plist

# Self-improvement kernel cycle (every 5 min — main orchestrator)
cp deploy/launchd/com.elastifund.kernel-cycle.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.elastifund.kernel-cycle.plist

# Weather shadow lane (hourly)
cp deploy/launchd/com.elastifund.weather-shadow-lane.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.elastifund.weather-shadow-lane.plist

# Canonical truth writer (every 30 min)
cp deploy/launchd/com.elastifund.canonical-truth-writer.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.elastifund.canonical-truth-writer.plist
```

### Manage daemons

```bash
# Check status
launchctl list | grep elastifund

# View logs
tail -f logs/kernel_cycle.launchd.log
tail -f logs/btc5_local_improvement_search.launchd.log
tail -f logs/weather_shadow_lane.launchd.log
tail -f logs/canonical_truth_writer.launchd.log

# Stop a daemon
launchctl unload ~/Library/LaunchAgents/com.elastifund.canonical-truth-writer.plist

# Restart a daemon
launchctl unload ~/Library/LaunchAgents/com.elastifund.weather-shadow-lane.plist
launchctl load   ~/Library/LaunchAgents/com.elastifund.weather-shadow-lane.plist
```

---

## Artifact Paths (mirror Lightsail)

| Artifact | Path | Lane |
|---|---|---|
| Kernel state | `reports/kernel/kernel_state.json` | kernel |
| Kernel cycle log | `reports/kernel/cycle_log.jsonl` | kernel |
| Evidence bundle | `reports/evidence_bundle.json` | sensorium/kernel |
| Sensorium | `reports/parallel/instance01_sensorium_latest.json` | sensorium |
| Thesis bundle | `reports/thesis_bundle.json` | kernel |
| Thesis candidates | `reports/autoresearch/thesis_candidates.json` | kernel |
| Promotion bundle | `reports/promotion_bundle.json` | promotion |
| Learning bundle | `reports/learning_bundle.json` | kernel |
| Research OS | `reports/autoresearch/research_os/latest.json` | kernel |
| Novelty discovery | `reports/parallel/novelty_discovery.json` | novelty |
| Novel edge | `reports/parallel/novel_edge.json` | novelty |
| Architecture alpha | `reports/architecture_alpha/latest.json` | architecture_alpha |
| Kimi output | `reports/autoresearch/providers/moonshot/latest.json` | kimi |
| Intelligence harness | `reports/intelligence_harness/latest.json` | harness |
| BTC5 market model | `reports/autoresearch/btc5_market/latest.json` | btc5 |
| BTC5 command node | `reports/autoresearch/command_node/latest.json` | btc5 |
| Weather shadow | `reports/parallel/instance04_weather_divergence_shadow.json` | weather |
| Canonical operator truth | `reports/canonical_operator_truth.json` | truth |
| Account balance CSV | `data/finance_imports/account_polymarket.csv` | truth |
| Monitor state | `data/local_monitor_state.json` | monitor |

---

## Safety Properties

- `BTC5_DEPLOY_MODE=shadow` is injected by the twin orchestrator for BTC5 — the btc5_5min_maker never submits live orders when launched from `run_local_twin.py`.
- `KALSHI_WEATHER_MODE=paper` is injected for the weather lane.
- `canonical_truth_writer.py` is read-only against the Polymarket data API (public endpoint, no auth required). It never places orders.
- `local_monitor.py --no-ssh` skips VPS SSH entirely; useful when `~/.ssh/lightsail_new.pem` is absent.

---

## SSH Key Fix (needed for VPS lanes)

If the SSH key has parentheses in the filename (a common macOS download rename):

```bash
ln -sf "$HOME/Downloads/LightsailDefaultKey-eu-west-1 (1).pem" "$HOME/.ssh/lightsail_new.pem"
chmod 600 "$HOME/.ssh/lightsail_new.pem"
```

Then test:

```bash
python3 scripts/run_local_twin.py --lane monitor  # without --no-ssh
```
