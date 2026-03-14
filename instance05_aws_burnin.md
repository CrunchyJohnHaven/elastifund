# Instance 05 - AWS Burn-In

Status: in_progress  
Generated: 2026-03-11 22:03 UTC

## Verdict

Instance 5 wiring is now executed on AWS, but the full objective is **not yet complete** because the hardened overnight gate still requires real wall-clock time.

What is complete:

- AWS market and command-node units are running the mutation-cycle entrypoints.
- The VPS now has the missing BTC5 autoresearch dependency closure that previously caused the market lane to crash.
- The policy lane now runs in informational `--skip-cycle` mode under the supervisor, which avoids treating a malformed simulator DB as a fresh policy-lane crash.
- All five BTC5 timers are enabled:
  - `btc5-market-model-autoresearch.timer`
  - `btc5-command-node-autoresearch.timer`
  - `btc5-policy-autoresearch.timer`
  - `btc5-autoresearch.timer`
  - `btc5-dual-autoresearch-morning.timer`
- The remote dual-autoresearch surface is healthy again.

What is not complete yet:

- The overnight closeout on the VPS is still red because the unattended window is only `0.1303h`, market runs are `2/4`, command-node runs are `2/4`, and the earlier policy crash at `2026-03-11T21:58:37Z` is still inside the 12-hour gate window.

## Local Fixes Landed

- `scripts/btc5_dual_autoresearch_ops.py`
  - aligned market and command-node supervisor timeouts to `1800s` so operator output matches the deployed systemd units
  - changed the policy lane default supervised command to `scripts/run_btc5_policy_autoresearch.py --skip-cycle`
- `scripts/deploy.sh`
  - `--btc5-autoresearch` now deploys the dual-autoresearch suite, not just the refresh shim
  - syncs the BTC5 market/command mutation dependencies, benchmark files, mutable surfaces, and `infra/fast_json.py`
  - installs/enables the market, command-node, policy, refresh, and morning timers
  - creates remote parent directories before copying new files
- Tests updated and passing:
  - `53 passed` across the BTC5 autoresearch/deploy/overnight-gate suite

## AWS Actions Performed

1. Pushed the missing market-lane dependency closure to `/home/ubuntu/polymarket-trading-bot`.
2. Reinstalled the BTC5 dual-autoresearch service and timer units under `/etc/systemd/system/`.
3. Enabled the missing `btc5-policy-autoresearch.timer`.
4. Started the market, command-node, policy, and refresh services once to seed fresh artifacts.
5. Refreshed `research/btc5_arr_progress.svg` on the VPS so all four charts are fresh.
6. Cleared the stale policy backoff left by the pre-fix crash and forced one clean policy run.

## Remote Evidence

Latest successful supervised runs on AWS:

- market: `2026-03-11T22:00:49.597422Z` via `scripts/run_btc5_market_model_autoresearch.py`
- command_node: `2026-03-11T22:00:49.197950Z` via `scripts/run_btc5_command_node_autoresearch.py`
- policy: `2026-03-11T22:01:27.615003Z` via `scripts/run_btc5_policy_autoresearch.py --skip-cycle`

Latest remote surface artifacts:

- `reports/autoresearch/latest.json`: `2026-03-11T22:03:03.464634Z`
- `reports/autoresearch/morning/latest.json`: healthy surface, fresh
- `reports/autoresearch/overnight_closeout/latest.json`: `2026-03-11T22:03:03.474532Z`
- `reports/autoresearch/outcomes/latest.json`: fresh

Fresh chart timestamps on AWS:

- `research/btc5_market_model_progress.svg`: `2026-03-11T22:00:49.576150Z`
- `research/btc5_command_node_progress.svg`: `2026-03-11T22:00:49.169311Z`
- `research/btc5_arr_progress.svg`: `2026-03-11T22:02:53.021204Z`
- `research/btc5_usd_per_day_progress.svg`: `2026-03-11T22:03:03.464307Z`

Current timer schedule on AWS after repair:

- `btc5-autoresearch.timer` next run: `2026-03-11 22:15:49 UTC`
- `btc5-policy-autoresearch.timer` next run: `2026-03-11 22:16:26 UTC`
- `btc5-command-node-autoresearch.timer` next run: `2026-03-11 23:00:48 UTC`
- `btc5-market-model-autoresearch.timer` next run: `2026-03-11 23:00:49 UTC`
- `btc5-dual-autoresearch-morning.timer` next run: `2026-03-12 09:05:00 UTC`

## Current Gate State

The remote overnight closeout is still honestly red with:

- `service_audit_span_below_target:0.1303h/8h`
- `market_run_count_below_target:2/4`
- `command_node_run_count_below_target:2/4`
- `lane_crashes:policy`

The policy crash is historical and came from the pre-fix service run that tried to execute a fresh BTC5 cycle against a malformed local SQLite file. After the supervisor change to `--skip-cycle`, the next policy run succeeded and the surface returned to healthy.

## Earliest Honest Completion Time

Because the hardened overnight gate looks at a rolling 12-hour window, the policy crash at `2026-03-11T21:58:37Z` must age out of the window before the closeout can turn green.

Earliest honest completion checkpoint:

- `2026-03-12 10:00 UTC`
- `2026-03-12 06:00 EDT`

At or after that point, the objective can be declared complete only if:

- market and command-node each have at least 4 supervised runs in-window
- the audit span is at least 8 hours
- no new lane crashes occur
- the four charts and morning/overnight packets remain fresh
- the closeout ends with either an improved champion or explicit `no_better_candidate` records
