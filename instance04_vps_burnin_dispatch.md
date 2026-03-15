# Instance 04 — VPS Burn-In Dispatch

Status: active
Generated: 2026-03-11T20:00:00Z
Instance: 4 (Claude Code Sonnet 4.6)
Output artifact: `instance04_vps_burnin_dispatch.md`

---

## Objective

Run the real lane services overnight using the repo-tracked systemd units and the aggregate `refresh --write-morning-report` shim. Burn-in window: one full overnight interval, minimum 8 hours.

Acceptance: the system can self-iterate automatically overnight and produce a trustworthy morning answer. A live trading promotion is not required for green.

---

## Pre-Flight State (Snapshot: 2026-03-11T19:48 UTC)

### Lane Champions Before Burn-In

| Lane | Champion ID | Loss | Score | Updated |
|------|-------------|------|-------|---------|
| market | `empirical_backoff_v1` (hash `279bcae7…`) | 5.178301 | — | 2026-03-11T17:51:01Z |
| command_node | `baseline-command-node` (hash `1be6584a…`) | 0.0 | 100.0 | 2026-03-11T17:50:37Z |
| policy | `current_live_profile` | −54143.007 | — | 2026-03-11T19:48:35Z |

### Experiment Counts Before Burn-In

| Lane | Total Runs | Kept | Crashes |
|------|-----------|------|---------|
| market | 4 | 1 | 0 |
| command_node | 3 | 1 | 0 |
| policy | 1 | 0 | 0 |

### Service Audit Entries Before Burn-In

Lines in `reports/autoresearch/ops/service_audit.jsonl`: **3**
Last entry timestamp: `2026-03-11T19:48:39Z` (command_node run)

### Known Blocker (pre-burn-in)

- `stale_chart:research/btc5_arr_progress.svg` — policy lane degraded
- Finance gate: `hold_no_spend` — does NOT block benchmark lanes
- Command-node benchmark saturated at 100.0 — Instance 1 addressing via v3 suite

### Morning Report Before Burn-In

Path: `reports/autoresearch/morning/latest.json`
Generated at: `2026-03-11T19:48:41Z`
Overall service health: **degraded** (policy lane only)

---

## Deploy Sequence

### Step 1 — Sync Repo to VPS

The VPS bot directory is NOT a git checkout. Use the narrowest safe copy.

```bash
# Deploy the 8 service+timer unit files
VPS="ubuntu@52.208.155.0"
KEY="-i ~/Downloads/LightsailDefaultKey-eu-west-1.pem"
REMOTE_UNITS="/etc/systemd/system"
LOCAL_DEPLOY="./deploy"

# Copy service files
for f in \
  btc5-market-model-autoresearch.service \
  btc5-market-model-autoresearch.timer \
  btc5-command-node-autoresearch.service \
  btc5-command-node-autoresearch.timer \
  btc5-policy-autoresearch.service \
  btc5-policy-autoresearch.timer \
  btc5-autoresearch.service \
  btc5-autoresearch.timer \
  btc5-dual-autoresearch-morning.service \
  btc5-dual-autoresearch-morning.timer; do
  scp $KEY $LOCAL_DEPLOY/$f $VPS:/tmp/$f
  ssh $KEY $VPS "sudo mv /tmp/$f $REMOTE_UNITS/$f && sudo chmod 644 $REMOTE_UNITS/$f"
done
```

### Step 2 — Sync Scripts to VPS

```bash
# Sync the supervisor script
scp $KEY scripts/btc5_dual_autoresearch_ops.py $VPS:/home/ubuntu/polymarket-trading-bot/scripts/
scp $KEY scripts/run_btc5_market_model_autoresearch.py $VPS:/home/ubuntu/polymarket-trading-bot/scripts/
scp $KEY scripts/run_btc5_command_node_autoresearch.py $VPS:/home/ubuntu/polymarket-trading-bot/scripts/
scp $KEY scripts/run_btc5_policy_autoresearch.py $VPS:/home/ubuntu/polymarket-trading-bot/scripts/
```

### Step 3 — Enable and Start All Timers

```bash
ssh $KEY $VPS "sudo systemctl daemon-reload && \
  sudo systemctl enable btc5-market-model-autoresearch.timer \
                        btc5-command-node-autoresearch.timer \
                        btc5-policy-autoresearch.timer \
                        btc5-autoresearch.timer \
                        btc5-dual-autoresearch-morning.timer && \
  sudo systemctl start  btc5-market-model-autoresearch.timer \
                        btc5-command-node-autoresearch.timer \
                        btc5-policy-autoresearch.timer \
                        btc5-autoresearch.timer \
                        btc5-dual-autoresearch-morning.timer"
```

### Step 4 — Verify Timer Status

```bash
ssh $KEY $VPS "sudo systemctl list-timers --all | grep btc5"
```

Expected output shows 5 active timers with `NextElapse` times populated.

### Step 5 — Verify Lane Directories Exist

```bash
ssh $KEY $VPS "mkdir -p \
  /home/ubuntu/polymarket-trading-bot/reports/autoresearch/btc5_market/packets \
  /home/ubuntu/polymarket-trading-bot/reports/autoresearch/command_node/runs \
  /home/ubuntu/polymarket-trading-bot/reports/autoresearch/btc5_policy/runs \
  /home/ubuntu/polymarket-trading-bot/reports/autoresearch/morning \
  /home/ubuntu/polymarket-trading-bot/reports/autoresearch/overnight_closeout \
  /home/ubuntu/polymarket-trading-bot/reports/autoresearch/ops \
  /home/ubuntu/polymarket-trading-bot/state"
```

---

## Burn-In Window Definition

| Parameter | Value |
|-----------|-------|
| Window | Overnight, minimum 8 hours |
| Start | After Step 4 completes (timers active) |
| End | 09:05 UTC (morning report fires) or 8h mark, whichever comes first |
| Market lane cadence | Every 60 min → 8+ runs expected |
| Command-node cadence | Every 60 min → 8+ runs expected |
| Policy cadence | Every 15 min → 32+ runs expected |
| Refresh shim cadence | Every 15 min → 32+ runs expected |
| Morning report | Daily at 09:05 UTC via `btc5-dual-autoresearch-morning.timer` |

Minimum evidence threshold after 8 hours:
- `service_audit.jsonl` must have grown by ≥ 8 lines from the pre-burn-in count of 3
- At least 1 fresh market artifact (younger than 90 min at time of check)
- At least 1 fresh command-node artifact (younger than 90 min at time of check)
- Zero crashes in service audit (all `returncode: 0`)

---

## Evidence Collection

### After Burn-In — Check Commands

Run these from the local machine after the overnight window:

```bash
VPS="ubuntu@52.208.155.0"
KEY="-i ~/Downloads/LightsailDefaultKey-eu-west-1.pem"

# 1. Pull fresh artifacts
scp $KEY $VPS:/home/ubuntu/polymarket-trading-bot/reports/autoresearch/morning/latest.json \
  reports/autoresearch/morning/latest.json
scp $KEY $VPS:/home/ubuntu/polymarket-trading-bot/reports/autoresearch/btc5_market/latest.json \
  reports/autoresearch/btc5_market/latest.json
scp $KEY $VPS:/home/ubuntu/polymarket-trading-bot/reports/autoresearch/command_node/latest.json \
  reports/autoresearch/command_node/latest.json
scp $KEY $VPS:/home/ubuntu/polymarket-trading-bot/reports/autoresearch/ops/service_audit.jsonl \
  reports/autoresearch/ops/service_audit.jsonl
scp $KEY $VPS:/home/ubuntu/polymarket-trading-bot/reports/autoresearch/overnight_closeout/latest.json \
  reports/autoresearch/overnight_closeout/latest.json 2>/dev/null || echo "no closeout yet"

# 2. Check service audit line count
wc -l reports/autoresearch/ops/service_audit.jsonl

# 3. Check market champion
python3 -c "
import json
d = json.load(open('reports/autoresearch/btc5_market/latest.json'))
c = d['champion']
print('Market champion:', c.get('candidate_model_name'), 'loss:', c.get('loss'), 'experiments:', d['counts'])
"

# 4. Check command-node champion
python3 -c "
import json
d = json.load(open('reports/autoresearch/command_node/latest.json'))
c = d['champion']
print('Command-node champion:', c.get('candidate_label'), 'score:', c.get('total_score'), 'exp_id:', d.get('latest_experiment_id'))
"

# 5. Check morning report generated time
python3 -c "
import json
d = json.load(open('reports/autoresearch/morning/latest.json'))
print('Morning generated_at:', d['generated_at'])
print('Service health:', d['service_health']['overall_status'])
print('Experiments 24h:', d['experiments_run']['total'])
print('Crashes 24h:', len(d['crashes']))
"

# 6. Check journal for any crash evidence
ssh $KEY $VPS "sudo journalctl -u btc5-market-model-autoresearch.service --since '8 hours ago' --no-pager | tail -20"
ssh $KEY $VPS "sudo journalctl -u btc5-command-node-autoresearch.service --since '8 hours ago' --no-pager | tail -20"
```

---

## Required Evidence After Burn-In

The burn-in report must document each of the following fields:

### Artifact Freshness

| Artifact | Path | Required Freshness | Pass/Fail |
|----------|------|--------------------|-----------|
| Market latest | `reports/autoresearch/btc5_market/latest.json` | < 90 min old | TBD |
| Command-node latest | `reports/autoresearch/command_node/latest.json` | < 90 min old | TBD |
| Morning packet | `reports/autoresearch/morning/latest.json` | Generated after burn-in start | TBD |
| Overnight closeout | `reports/autoresearch/overnight_closeout/latest.json` | Written by Instance 3 script | TBD |

### Service Audit Growth

| Metric | Pre Burn-In | Post Burn-In | Delta | Pass (≥ 8) |
|--------|-------------|--------------|-------|------------|
| `service_audit.jsonl` lines | 3 | TBD | TBD | TBD |

### Champion Delta

| Lane | Champion Before | Champion After | Changed | Improved |
|------|-----------------|----------------|---------|----------|
| market | `empirical_backoff_v1` (loss 5.178301) | TBD | TBD | TBD |
| command_node | `baseline-command-node` (score 100.0) | TBD | TBD | TBD |
| policy | `current_live_profile` | TBD | TBD | TBD |

### Crash Report

| Lane | Crash Count During Window | Pass (= 0) |
|------|--------------------------|------------|
| market | TBD | TBD |
| command_node | TBD | TBD |
| policy | TBD | TBD |

---

## Burn-In Acceptance Criteria

### Green (Objective Achieved)

All of the following must be true:

1. `reports/autoresearch/btc5_market/latest.json` is fresh (generated during burn-in window)
2. `reports/autoresearch/command_node/latest.json` is fresh (generated during burn-in window)
3. `reports/autoresearch/morning/latest.json` is fresh (generated after burn-in start)
4. `reports/autoresearch/ops/service_audit.jsonl` grew by ≥ 8 lines
5. Zero crashes recorded in service audit during window
6. Overnight closeout packet written (by Instance 3 infrastructure) OR explicitly noted as blocked by Instance 3 dependency
7. At least one of: improved market champion OR improved command-node champion OR explicit null-result record per lane

### Yellow (Partial — Requires Operator Decision)

- Market or command-node fresh but not both
- Service audit grew by < 8 lines (cadence degraded)
- Policy lane degraded or stale (acceptable if benchmark lanes healthy)
- Overnight closeout missing due to Instance 3 not yet merged

### Red (Objective Not Met)

Any of:
- Neither market nor command-node artifact is fresh
- Any lane crashed (non-zero returncode in service audit)
- Morning report not generated
- Service audit did not grow (no supervised runs occurred)

---

## Blockers and Known Pre-Conditions

### Instance 1 Dependency

Instance 1 delivers `command_node_btc5/v3` benchmark suite with acceptance threshold < 95.0 for the current baseline. Until v3 merges:
- Command-node lane will continue scoring 100.0 (saturated)
- Burn-in can still proceed; null-result on command-node is acceptable
- The burn-in report must note whether v3 was active during the window

### Instance 2 Dependency

Instance 2 fixes champion extraction and removes `btc5_arr_progress.svg` as a blocker for benchmark-lane health. Until merged:
- Policy lane will remain "degraded" in morning report due to stale chart
- Burn-in report must note this blocker is a reporting artifact, not a benchmark-lane failure

### Instance 3 Dependency

Instance 3 delivers the `overnight_closeout` infrastructure. Until merged:
- The `reports/autoresearch/overnight_closeout/latest.json` artifact will not exist
- Burn-in acceptance criterion 6 is conditionally waived if Instance 3 has not merged
- The burn-in report must note this explicitly

### Pre-Conditions for Green Without Dependencies

The burn-in can achieve green on market and command-node lanes regardless of Instances 1, 2, or 3, provided:
- Lane services run and do not crash
- Service audit grows by ≥ 8 lines
- Market and command-node artifacts are fresh after the window

---

## Failure Triage

If any lane fails, the burn-in report must name:

1. **Exact blocker** — what went wrong (import error, missing artifact, misconfigured path, etc.)
2. **Exact service** — which systemd unit failed (`btc5-market-model-autoresearch.service`, etc.)
3. **Exact artifact path** — which output file is missing or stale
4. **Journal evidence** — the tail of `journalctl -u <service>` showing the error
5. **Remediation** — what change is required before a second burn-in

Do not use vague status descriptions ("something failed", "not working"). Name the exact exception and the exact file.

---

## Final Burn-In Report Template

After collecting evidence, write to `instance04_overnight_burnin_report.md`:

```markdown
# BTC5 Overnight Burn-In Report

Generated: <ISO timestamp>
Burn-in window: <start> → <end> (<hours>h)
Objective achieved: yes / no / partial

## Artifact Freshness
- Market latest: <generated_at> — fresh / stale
- Command-node latest: <generated_at> — fresh / stale
- Morning packet: <generated_at>
- Overnight closeout: <exists: yes/no> <reason if missing>

## Service Audit
- Lines before: 3
- Lines after: <N>
- Delta: <N-3>
- Pass: yes / no

## Champion Delta
| Lane | Before | After | Changed | Improved |
|------|--------|-------|---------|----------|
| market | empirical_backoff_v1 / 5.178301 | <id> / <loss> | yes/no | yes/no/null-result |
| command_node | baseline-command-node / 100.0 | <label> / <score> | yes/no | yes/no/null-result |
| policy | current_live_profile | <id> | yes/no | yes/no/null-result |

## Crash Report
- Market crashes: 0 / <N with journal evidence>
- Command-node crashes: 0 / <N>
- Policy crashes: 0 / <N>

## Dependency Notes
- Instance 1 (v3 benchmark): merged / not yet merged
- Instance 2 (champion extraction fix): merged / not yet merged
- Instance 3 (overnight closeout): merged / not yet merged

## Verdict
<GREEN / YELLOW / RED>

Reason: <one-sentence specific explanation>

## Blockers (if RED or YELLOW)
<List each blocker with exact service, artifact path, and journal tail>
```

---

## Quality Checklist

- [ ] Lane services run from the repo-tracked systemd units (no manual invocations substituted)
- [ ] The audit trail shows repeated supervised runs (≥ 8 service_audit.jsonl entries added during window)
- [ ] Morning and overnight closeout artifacts are fresh after the run
- [ ] The final burn-in report states clearly whether the objective is achieved
- [ ] Any failure names the exact blocker, service, artifact path, and journal evidence
- [ ] Champion delta is recorded per lane (improvement or explicit null-result)
- [ ] Benchmark-lane health is not confused with live trading posture
- [ ] v3 command-node benchmark status is noted (Instance 1 dependency)
- [ ] `btc5_arr_progress.svg` stale-chart blocker is labeled as a reporting artifact, not a lane failure
