# Instance 04 — AWS Burn-In and Visibility Dispatch

Status: active
Generated: 2026-03-11
Instance: 4 (Claude Code Sonnet 4.6)
Output artifact: `instance04_aws_burnin_dispatch.md`

---

## Objective

Repoint the AWS services from evaluator-only lane runs to the mutation-cycle runners delivered by Instances 1 and 2. Run one real unattended burn-in on the AWS instance, minimum 8 hours wall-clock. The system must wake up with either improved champions or explicit `no_better_candidate` records and honest green status under the hardened overnight gate.

---

## Pre-Conditions (Instance Dependencies)

This dispatch depends on three upstream deliverables. Record their merge status before starting the deploy sequence.

| Instance | Deliverable | Required For | Status |
|----------|-------------|-------------|--------|
| Instance 1 | `scripts/run_btc5_market_model_mutation_cycle.py` + proposer metadata in market ledger | Market service repoint | [ ] |
| Instance 2 | `scripts/run_btc5_command_node_mutation_cycle.py` + v4 benchmark + proposer metadata in command-node ledger | Command-node service repoint | [ ] |
| Instance 3 | `btc5_usd_per_day_progress.svg` renderer + `reports/autoresearch/outcomes/latest.json` + hardened overnight gate | Four-chart requirement + closeout | [ ] |

**If Instance 1 or 2 has not merged at burn-in start:** run the existing evaluator-only services and note the mutation-runner dependency explicitly in the burn-in report. The burn-in is still valid—it just tests the evaluator loop and records the pre-condition gap.

**If Instance 3 has not merged at burn-in start:** USD/day and ARR outcome charts are waived from the four-chart requirement. The overnight closeout criterion is adjusted to evaluator-only overnight gate.

---

## Service Repoint: What Changes

### Current Service ExecStart (evaluator-only)

```
# btc5-market-model-autoresearch.service
ExecStart=... python3 scripts/btc5_dual_autoresearch_ops.py run-lane --lane market --write-morning-report

# btc5-command-node-autoresearch.service
ExecStart=... python3 scripts/btc5_dual_autoresearch_ops.py run-lane --lane command_node --write-morning-report
```

### Target Service ExecStart (mutation-cycle runners)

```
# btc5-market-model-autoresearch.service (post-Instance-1)
ExecStart=... python3 scripts/run_btc5_market_model_mutation_cycle.py

# btc5-command-node-autoresearch.service (post-Instance-2)
ExecStart=... python3 scripts/run_btc5_command_node_mutation_cycle.py
```

### Updated Service Files

The updated service files include:
1. Longer `TimeoutStartSec` to accommodate proposer LLM call (1800s instead of 900s)
2. `PYTHONPATH` unchanged
3. `SyslogIdentifier` unchanged (keeps journalctl queries backward-compatible)
4. The refresh shim (`btc5-autoresearch.service`) is unchanged — it renders charts from the ledger and does not propose

#### Updated `deploy/btc5-market-model-autoresearch.service`

```ini
[Unit]
Description=BTC5 Market-Model Mutation Cycle
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=ubuntu
WorkingDirectory=/home/ubuntu/polymarket-trading-bot
ExecStart=/bin/bash -lc 'mkdir -p state reports/autoresearch && \
  export PYTHONPATH=/home/ubuntu/polymarket-trading-bot:/home/ubuntu/polymarket-trading-bot/bot:/home/ubuntu/polymarket-trading-bot/polymarket-bot && \
  /usr/bin/python3 scripts/run_btc5_market_model_mutation_cycle.py'
Restart=on-failure
RestartSec=60
TimeoutStartSec=1800
StandardOutput=journal
StandardError=journal
SyslogIdentifier=btc5marketautoresearch
```

#### Updated `deploy/btc5-command-node-autoresearch.service`

```ini
[Unit]
Description=BTC5 Command-Node Mutation Cycle
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=ubuntu
WorkingDirectory=/home/ubuntu/polymarket-trading-bot
ExecStart=/bin/bash -lc 'mkdir -p state reports/autoresearch && \
  export PYTHONPATH=/home/ubuntu/polymarket-trading-bot:/home/ubuntu/polymarket-trading-bot/bot:/home/ubuntu/polymarket-trading-bot/polymarket-bot && \
  /usr/bin/python3 scripts/run_btc5_command_node_mutation_cycle.py'
Restart=on-failure
RestartSec=60
TimeoutStartSec=1800
StandardOutput=journal
StandardError=journal
SyslogIdentifier=btc5commandnodeautoresearch
```

---

## Pre-Flight State (Record Before Deploy)

Run these locally before starting the deploy:

```bash
VPS="ubuntu@52.208.155.0"
KEY="-i ~/Downloads/LightsailDefaultKey-eu-west-1.pem"

# Current service audit line count (baseline)
ssh $KEY $VPS "wc -l /home/ubuntu/polymarket-trading-bot/reports/autoresearch/ops/service_audit.jsonl 2>/dev/null || echo 0"

# Current market champion
ssh $KEY $VPS "python3 -c \"
import json, pathlib
p = pathlib.Path('/home/ubuntu/polymarket-trading-bot/reports/autoresearch/btc5_market/champion.json')
if p.exists():
    d = json.loads(p.read_text())
    print('Market champion:', d.get('candidate_model_name'), 'loss:', d.get('loss'))
else:
    print('No champion yet')
\""

# Current command-node champion
ssh $KEY $VPS "python3 -c \"
import json, pathlib
p = pathlib.Path('/home/ubuntu/polymarket-trading-bot/reports/autoresearch/command_node/champion.json')
if p.exists():
    d = json.loads(p.read_text())
    print('Command-node champion:', d.get('candidate_label'), 'score:', d.get('total_score'))
else:
    print('No champion yet')
\""

# Current ledger counts
ssh $KEY $VPS "wc -l \
  /home/ubuntu/polymarket-trading-bot/reports/autoresearch/btc5_market/results.jsonl \
  /home/ubuntu/polymarket-trading-bot/reports/autoresearch/command_node/results.jsonl 2>/dev/null || echo 'no ledgers'"
```

Record the pre-flight values in the burn-in report under "State Before Burn-In".

---

## Deploy Sequence

### Step 0 — Verify Instance 1, 2, 3 Scripts Are Present

```bash
# Check mutation runners exist locally before syncing
ls -la scripts/run_btc5_market_model_mutation_cycle.py
ls -la scripts/run_btc5_command_node_mutation_cycle.py
ls -la scripts/render_btc5_usd_per_day_progress.py  # Instance 3

# If any are missing, note which and proceed with evaluator-only fallback
```

### Step 1 — Update Service Files Locally

If Instance 1 has merged, overwrite the service file:

```bash
cat > deploy/btc5-market-model-autoresearch.service << 'EOF'
[Unit]
Description=BTC5 Market-Model Mutation Cycle
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=ubuntu
WorkingDirectory=/home/ubuntu/polymarket-trading-bot
ExecStart=/bin/bash -lc 'mkdir -p state reports/autoresearch && export PYTHONPATH=/home/ubuntu/polymarket-trading-bot:/home/ubuntu/polymarket-trading-bot/bot:/home/ubuntu/polymarket-trading-bot/polymarket-bot && /usr/bin/python3 scripts/run_btc5_market_model_mutation_cycle.py'
Restart=on-failure
RestartSec=60
TimeoutStartSec=1800
StandardOutput=journal
StandardError=journal
SyslogIdentifier=btc5marketautoresearch
EOF
```

If Instance 2 has merged:

```bash
cat > deploy/btc5-command-node-autoresearch.service << 'EOF'
[Unit]
Description=BTC5 Command-Node Mutation Cycle
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=ubuntu
WorkingDirectory=/home/ubuntu/polymarket-trading-bot
ExecStart=/bin/bash -lc 'mkdir -p state reports/autoresearch && export PYTHONPATH=/home/ubuntu/polymarket-trading-bot:/home/ubuntu/polymarket-trading-bot/bot:/home/ubuntu/polymarket-trading-bot/polymarket-bot && /usr/bin/python3 scripts/run_btc5_command_node_mutation_cycle.py'
Restart=on-failure
RestartSec=60
TimeoutStartSec=1800
StandardOutput=journal
StandardError=journal
SyslogIdentifier=btc5commandnodeautoresearch
EOF
```

### Step 2 — Sync Scripts to VPS

```bash
VPS="ubuntu@52.208.155.0"
KEY="-i ~/Downloads/LightsailDefaultKey-eu-west-1.pem"
REMOTE_BOT="/home/ubuntu/polymarket-trading-bot"

# Core supervisor (always sync)
scp $KEY scripts/btc5_dual_autoresearch_ops.py $VPS:$REMOTE_BOT/scripts/

# Mutation runners (sync if merged)
[ -f scripts/run_btc5_market_model_mutation_cycle.py ] && \
  scp $KEY scripts/run_btc5_market_model_mutation_cycle.py $VPS:$REMOTE_BOT/scripts/

[ -f scripts/run_btc5_command_node_mutation_cycle.py ] && \
  scp $KEY scripts/run_btc5_command_node_mutation_cycle.py $VPS:$REMOTE_BOT/scripts/

# Evaluator runners (always sync as fallback)
scp $KEY scripts/run_btc5_market_model_autoresearch.py $VPS:$REMOTE_BOT/scripts/
scp $KEY scripts/run_btc5_command_node_autoresearch.py $VPS:$REMOTE_BOT/scripts/
scp $KEY scripts/run_btc5_policy_autoresearch.py $VPS:$REMOTE_BOT/scripts/

# Instance 3 outcome renderers (sync if merged)
[ -f scripts/render_btc5_usd_per_day_progress.py ] && \
  scp $KEY scripts/render_btc5_usd_per_day_progress.py $VPS:$REMOTE_BOT/scripts/

[ -f scripts/render_btc5_arr_progress.py ] && \
  scp $KEY scripts/render_btc5_arr_progress.py $VPS:$REMOTE_BOT/scripts/

# Benchmark modules (sync if Instance 1/2 added new benchmark dirs)
[ -d benchmarks/command_node_btc5 ] && \
  rsync -av --exclude='__pycache__' benchmarks/command_node_btc5/ \
    $VPS:$REMOTE_BOT/benchmarks/command_node_btc5/ -e "ssh $KEY"

[ -d benchmarks/btc5_market ] && \
  rsync -av --exclude='__pycache__' benchmarks/btc5_market/ \
    $VPS:$REMOTE_BOT/benchmarks/btc5_market/ -e "ssh $KEY"
```

### Step 3 — Sync Service Files to VPS

```bash
REMOTE_UNITS="/etc/systemd/system"

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
  scp $KEY deploy/$f $VPS:/tmp/$f
  ssh $KEY $VPS "sudo mv /tmp/$f $REMOTE_UNITS/$f && sudo chmod 644 $REMOTE_UNITS/$f"
done
```

### Step 4 — Create Required Directories on VPS

```bash
ssh $KEY $VPS "mkdir -p \
  $REMOTE_BOT/reports/autoresearch/btc5_market/packets \
  $REMOTE_BOT/reports/autoresearch/command_node/runs \
  $REMOTE_BOT/reports/autoresearch/btc5_policy/runs \
  $REMOTE_BOT/reports/autoresearch/morning \
  $REMOTE_BOT/reports/autoresearch/overnight_closeout \
  $REMOTE_BOT/reports/autoresearch/ops \
  $REMOTE_BOT/reports/autoresearch/outcomes \
  $REMOTE_BOT/research \
  $REMOTE_BOT/state"
```

### Step 5 — Reload Systemd and Enable All Timers

```bash
ssh $KEY $VPS "sudo systemctl daemon-reload && \
  sudo systemctl enable \
    btc5-market-model-autoresearch.timer \
    btc5-command-node-autoresearch.timer \
    btc5-policy-autoresearch.timer \
    btc5-autoresearch.timer \
    btc5-dual-autoresearch-morning.timer && \
  sudo systemctl start \
    btc5-market-model-autoresearch.timer \
    btc5-command-node-autoresearch.timer \
    btc5-policy-autoresearch.timer \
    btc5-autoresearch.timer \
    btc5-dual-autoresearch-morning.timer"
```

### Step 6 — Verify Timers Active

```bash
ssh $KEY $VPS "sudo systemctl list-timers --all | grep btc5"
```

Expected: 5 timers, all with populated `NextElapse` times and `PASSED` status for first fire.

### Step 7 — Trigger One Immediate Run Per Lane (Smoke Test)

```bash
# Fire one run immediately to confirm no import errors before the overnight window
ssh $KEY $VPS "sudo systemctl start btc5-market-model-autoresearch.service"
sleep 10
ssh $KEY $VPS "sudo journalctl -u btc5-market-model-autoresearch.service --since '1 min ago' --no-pager | tail -10"

ssh $KEY $VPS "sudo systemctl start btc5-command-node-autoresearch.service"
sleep 10
ssh $KEY $VPS "sudo journalctl -u btc5-command-node-autoresearch.service --since '1 min ago' --no-pager | tail -10"
```

If either smoke test exits nonzero, **stop** and triage before starting the overnight window.

---

## Burn-In Window Definition

| Parameter | Value |
|-----------|-------|
| Window | Minimum 8 hours wall-clock |
| Start | After Step 7 smoke test passes |
| End | 09:05 UTC next morning (morning report fires) |
| Market mutation cadence | Every 60 min → ≥ 8 runs expected |
| Command-node mutation cadence | Every 60 min → ≥ 8 runs expected |
| Policy cadence | Every 15 min → ≥ 32 runs expected |
| Refresh shim cadence | Every 15 min (renders charts from ledger) |
| Morning report | Daily 09:05 UTC via `btc5-dual-autoresearch-morning.timer` |

Minimum audit trail after 8 hours:
- `service_audit.jsonl` must have ≥ 8 new lines from the pre-flight baseline
- At least 4 market runs in-window (matching Instance 3 hardened gate)
- At least 4 command-node runs in-window
- Each lane run must show proposer activity in the ledger if mutation runner is active

---

## Evidence Collection After Burn-In

```bash
VPS="ubuntu@52.208.155.0"
KEY="-i ~/Downloads/LightsailDefaultKey-eu-west-1.pem"
REMOTE_BOT="/home/ubuntu/polymarket-trading-bot"

# 1. Pull all artifacts
scp $KEY $VPS:$REMOTE_BOT/reports/autoresearch/morning/latest.json \
  reports/autoresearch/morning/latest.json

scp $KEY $VPS:$REMOTE_BOT/reports/autoresearch/overnight_closeout/latest.json \
  reports/autoresearch/overnight_closeout/latest.json 2>/dev/null || echo "no closeout yet"

scp $KEY $VPS:$REMOTE_BOT/reports/autoresearch/btc5_market/latest.json \
  reports/autoresearch/btc5_market/latest.json

scp $KEY $VPS:$REMOTE_BOT/reports/autoresearch/command_node/latest.json \
  reports/autoresearch/command_node/latest.json

scp $KEY $VPS:$REMOTE_BOT/reports/autoresearch/ops/service_audit.jsonl \
  reports/autoresearch/ops/service_audit.jsonl

scp $KEY $VPS:$REMOTE_BOT/reports/autoresearch/btc5_market/results.jsonl \
  reports/autoresearch/btc5_market/results.jsonl 2>/dev/null || true

scp $KEY $VPS:$REMOTE_BOT/reports/autoresearch/command_node/results.jsonl \
  reports/autoresearch/command_node/results.jsonl 2>/dev/null || true

# Outcome artifacts (Instance 3)
scp $KEY $VPS:$REMOTE_BOT/reports/autoresearch/outcomes/latest.json \
  reports/autoresearch/outcomes/latest.json 2>/dev/null || echo "no outcomes artifact"

# Charts
scp $KEY $VPS:$REMOTE_BOT/research/btc5_market_model_progress.svg \
  research/btc5_market_model_progress.svg 2>/dev/null || true

scp $KEY $VPS:$REMOTE_BOT/research/btc5_command_node_progress.svg \
  research/btc5_command_node_progress.svg 2>/dev/null || true

scp $KEY $VPS:$REMOTE_BOT/research/btc5_arr_progress.svg \
  research/btc5_arr_progress.svg 2>/dev/null || true

scp $KEY $VPS:$REMOTE_BOT/research/btc5_usd_per_day_progress.svg \
  research/btc5_usd_per_day_progress.svg 2>/dev/null || true


# 2. Count service audit lines
echo "=== SERVICE AUDIT LINE COUNT ==="
wc -l reports/autoresearch/ops/service_audit.jsonl

# 3. Check for proposer activity in ledgers (mutation runner proof)
echo "=== PROPOSER ACTIVITY IN MARKET LEDGER ==="
python3 -c "
import json, pathlib
p = pathlib.Path('reports/autoresearch/btc5_market/results.jsonl')
if not p.exists():
    print('no ledger')
else:
    lines = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    proposer_runs = [l for l in lines if l.get('proposal_id') or l.get('proposer_model')]
    print(f'Total records: {len(lines)}, Proposer records: {len(proposer_runs)}')
    if proposer_runs:
        last = proposer_runs[-1]
        print('Last proposer:', last.get('proposer_model'), 'mutation_type:', last.get('mutation_type'), 'kept:', last.get('keep'))
"

echo "=== PROPOSER ACTIVITY IN COMMAND-NODE LEDGER ==="
python3 -c "
import json, pathlib
p = pathlib.Path('reports/autoresearch/command_node/results.jsonl')
if not p.exists():
    print('no ledger')
else:
    lines = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    proposer_runs = [l for l in lines if l.get('proposal_id') or l.get('proposer_model')]
    print(f'Total records: {len(lines)}, Proposer records: {len(proposer_runs)}')
    if proposer_runs:
        last = proposer_runs[-1]
        print('Last proposer:', last.get('proposer_model'), 'mutation_type:', last.get('mutation_type'), 'kept:', last.get('keep'))
"

# 4. Market champion after burn-in
echo "=== MARKET CHAMPION ==="
python3 -c "
import json
d = json.load(open('reports/autoresearch/btc5_market/latest.json'))
c = d.get('champion', {})
print('Champion:', c.get('candidate_model_name'), 'loss:', c.get('loss'))
print('Experiments:', d.get('counts'))
"

# 5. Command-node champion after burn-in
echo "=== COMMAND-NODE CHAMPION ==="
python3 -c "
import json
d = json.load(open('reports/autoresearch/command_node/latest.json'))
c = d.get('champion', {})
print('Champion:', c.get('candidate_label'), 'score:', c.get('total_score'))
print('Latest experiment id:', d.get('latest_experiment_id'))
"

# 6. Morning packet health
echo "=== MORNING PACKET ==="
python3 -c "
import json
d = json.load(open('reports/autoresearch/morning/latest.json'))
print('Generated at:', d['generated_at'])
print('Service health:', d['service_health']['overall_status'])
print('Market in-window runs:', d.get('experiments_run', {}).get('market', 0))
print('Command-node in-window runs:', d.get('experiments_run', {}).get('command_node', 0))
print('Crashes:', len(d.get('crashes', [])))
"

# 7. Outcome surfaces (Instance 3)
echo "=== OUTCOME SURFACES ==="
python3 -c "
import json, pathlib
p = pathlib.Path('reports/autoresearch/outcomes/latest.json')
if p.exists():
    d = json.loads(p.read_text())
    print('Expected USD/day:', d.get('expected_usd_per_day'))
    print('Expected fills/day:', d.get('expected_fills_per_day'))
    print('ARR estimate:', d.get('arr_estimate_pct'))
    print('Generated at:', d.get('generated_at'))
else:
    print('outcomes artifact missing (Instance 3 dependency)')
"

# 8. Chart freshness
echo "=== CHART FRESHNESS ==="
ls -la \
  research/btc5_market_model_progress.svg \
  research/btc5_command_node_progress.svg \
  research/btc5_arr_progress.svg \
  research/btc5_usd_per_day_progress.svg 2>/dev/null

# 9. Journal crash check
echo "=== MARKET JOURNAL (last 20 lines) ==="
ssh $KEY $VPS "sudo journalctl -u btc5-market-model-autoresearch.service --since '9 hours ago' --no-pager | tail -20"

echo "=== COMMAND-NODE JOURNAL (last 20 lines) ==="
ssh $KEY $VPS "sudo journalctl -u btc5-command-node-autoresearch.service --since '9 hours ago' --no-pager | tail -20"

# 10. Check no_better_candidate records (valid null-result proof)
echo "=== NULL-RESULT RECORDS ==="
python3 -c "
import json, pathlib
for label, path in [('market', 'reports/autoresearch/btc5_market/results.jsonl'),
                    ('command_node', 'reports/autoresearch/command_node/results.jsonl')]:
    p = pathlib.Path(path)
    if not p.exists():
        print(label, ': no ledger')
        continue
    lines = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    null_results = [l for l in lines if l.get('result') == 'no_better_candidate' or l.get('discard_reason') == 'no_improvement']
    print(label, ': null-result records =', len(null_results))
"
```

---

## Required Visible Outputs After Burn-In

All four charts must exist with file timestamps inside the burn-in window:

| Chart | Path | Generated By |
|-------|------|-------------|
| Market-model Karpathy chart | `research/btc5_market_model_progress.svg` | refresh shim (`btc5-autoresearch.service`) |
| Command-node Karpathy chart | `research/btc5_command_node_progress.svg` | refresh shim |
| ARR outcome chart | `research/btc5_arr_progress.svg` | Instance 3 renderer |
| USD/day outcome chart | `research/btc5_usd_per_day_progress.svg` | Instance 3 renderer |

Plus:

| Artifact | Path | Required |
|----------|------|----------|
| Fresh morning packet | `reports/autoresearch/morning/latest.json` | mandatory |
| Fresh overnight closeout | `reports/autoresearch/overnight_closeout/latest.json` | mandatory (waived if Instance 3 not merged) |
| Growing service audit | `reports/autoresearch/ops/service_audit.jsonl` | mandatory |
| Market ledger growth | `reports/autoresearch/btc5_market/results.jsonl` | mandatory |
| Command-node ledger growth | `reports/autoresearch/command_node/results.jsonl` | mandatory |
| Outcome summary JSON | `reports/autoresearch/outcomes/latest.json` | mandatory (waived if Instance 3 not merged) |

---

## Proposer Metadata Audit Contract

Each proposer+evaluator run in the market or command-node ledger must carry the following fields (from Instance 1/2 deliverables). If these fields are absent, the audit trail is evaluator-only and the burn-in report must note it.

```json
{
  "proposal_id": "string — unique per proposal",
  "parent_champion_id": "string — sha or label of champion being challenged",
  "proposer_model": "string — e.g. claude-haiku-4-5 or claude-sonnet-4-6",
  "estimated_llm_cost_usd": 0.001,
  "mutation_summary": "string — brief description of what was changed",
  "mutation_type": "string — e.g. threshold_adjust, feature_add, regime_override",
  "keep": true,
  "result": "keep | no_better_candidate"
}
```

Escalation metadata (if applicable):

```json
{
  "escalation_reason": "10_consecutive_discards | 24h_without_keep",
  "escalated_proposer_model": "claude-opus-4-6"
}
```

---

## Burn-In Acceptance Criteria

### Green (Objective Achieved) — Binary

All of the following must be true:

1. `service_audit.jsonl` has grown by ≥ 8 lines from pre-flight baseline
2. At least 4 market lane runs recorded in-window
3. At least 4 command-node lane runs recorded in-window
4. `reports/autoresearch/morning/latest.json` generated after burn-in start
5. Zero lane crashes (all service audit entries show `returncode: 0`)
6. One of the following is true per lane:
   - market champion improved (lower loss than pre-flight)
   - OR market ledger contains ≥ 1 explicit `no_better_candidate` record from a proposer run
7. One of the following is true per lane:
   - command-node champion improved (higher score than pre-flight, with v4 suite < 95 baseline)
   - OR command-node ledger contains ≥ 1 explicit `no_better_candidate` record

Optional but expected (if Instance 3 merged):

8. `reports/autoresearch/overnight_closeout/latest.json` generated and gate status is either `green` or `null_result_honest`
9. `reports/autoresearch/outcomes/latest.json` present with `expected_usd_per_day` and `arr_estimate_pct`
10. All four charts present and fresh

### Red (Objective Not Met)

Any of:
- No market or command-node lane ran (zero new service audit entries for either lane)
- Any lane crash during the window
- Morning packet not generated
- Neither improved champion nor `no_better_candidate` record exists for either lane

---

## Failure Triage Protocol

If any criterion fails, the burn-in report must name:

1. **Exact blocker** — exception type, missing file path, bad import, etc.
2. **Exact service** — which systemd unit failed
3. **Exact artifact path** — what file is missing or stale
4. **Journal evidence** — `journalctl -u <service>` tail showing the error
5. **Remediation step** — smallest change needed before a second burn-in attempt

Do not write "something failed". Name the exact exception and file.

Common failure modes to check first:

| Failure | Likely Cause | Check |
|---------|-------------|-------|
| ImportError on mutation runner | Instance 1/2 module not synced | Check PYTHONPATH; verify script synced in Step 2 |
| Missing benchmark manifest | `benchmarks/btc5_market/v1/manifest.json` not on VPS | Sync benchmarks dir |
| No proposer runs in ledger | Mutation runner calling evaluator-only fallback | Check if mutation runner script exists on VPS |
| `service_audit.jsonl` not growing | Timer not enabled or firewall issue | Check `systemctl list-timers --all` |
| USD/day chart missing | Instance 3 not merged | Record dependency gap; waive chart requirement |
| Morning report `no_runs` | Services ran but produced no artifacts | Check per-lane timeout; increase TimeoutStartSec |

---

## Final Burn-In Report

After evidence collection, write to `instance04_overnight_burnin_report.md`:

```markdown
# BTC5 Overnight Burn-In Report — Mutation-Cycle Edition

Generated: <ISO timestamp>
Burn-in window: <start UTC> → <end UTC> (<hours>h)
Objective achieved: yes / no / partial

## Instance Dependencies at Burn-In Start
- Instance 1 (market mutation runner): merged / not merged
- Instance 2 (command-node mutation runner + v4 benchmark): merged / not merged
- Instance 3 (outcome surfaces + hardened gate): merged / not merged

## State Before Burn-In
- Service audit lines: <N>
- Market champion: <id> / loss <X>
- Command-node champion: <label> / score <X>
- Market ledger entries: <N>
- Command-node ledger entries: <N>

## Audit Trail After Burn-In
- Service audit lines: <N>
- New lines added: <N - baseline>
- Pass (≥ 8): yes / no
- Market runs in-window: <N> / Pass (≥ 4): yes / no
- Command-node runs in-window: <N> / Pass (≥ 4): yes / no

## Proposer Activity
- Market proposer records: <N> (mutation runner active: yes / no)
- Command-node proposer records: <N> (mutation runner active: yes / no)
- Last market proposer: <model> / mutation_type: <type> / result: <keep|discard>
- Last command-node proposer: <model> / mutation_type: <type> / result: <keep|discard>

## Champion Delta
| Lane | Before | After | Changed | Improved |
|------|--------|-------|---------|----------|
| market | <id> / <loss> | <id> / <loss> | yes/no | yes/no/null_result |
| command_node | <label> / <score> | <label> / <score> | yes/no | yes/no/null_result |

## Chart Freshness
- Market Karpathy chart: <mtime> — fresh / stale / missing
- Command-node Karpathy chart: <mtime> — fresh / stale / missing
- ARR outcome chart: <mtime> — fresh / stale / missing (Instance 3: merged/not)
- USD/day outcome chart: <mtime> — fresh / stale / missing (Instance 3: merged/not)

## Outcome Surfaces (Instance 3)
- Expected USD/day: <value> / missing
- Expected fills/day: <value> / missing
- ARR estimate: <pct> / missing
- Overnight closeout gate: <green|null_result_honest|yellow|red> / missing

## Crash Report
- Market crashes: 0 / <N with journal evidence>
- Command-node crashes: 0 / <N>
- Policy crashes: 0 / <N>

## Verdict
<GREEN / YELLOW / RED>

Reason: <one sentence>

## Blockers (if RED or YELLOW)
<List each blocker with exact service, artifact path, journal tail>
```

---

## Quality Checklist

- [ ] AWS services visibly running mutation loops (not just evaluators) — proposer records in ledger
- [ ] Audit trail shows repeated unattended proposer + evaluator activity (≥ 8 new lines)
- [ ] All four charts present and fresh after burn-in (or dependency gap documented)
- [ ] Final closeout explicitly states whether full objective is achieved
- [ ] Champion delta recorded per lane (improvement or explicit `no_better_candidate`)
- [ ] Benchmark-lane health not confused with live trading posture
- [ ] `TimeoutStartSec=1800` in updated service files to accommodate proposer LLM call
- [ ] Smoke test (Step 7) passed before the overnight window started
- [ ] Pre-flight state documented (baseline for service audit and champion comparison)
- [ ] Instance 1, 2, 3 merge status recorded at top of burn-in report
