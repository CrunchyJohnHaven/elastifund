# Deprecation Candidates (Preparation)

_Generated from `scripts/deprecation_catalog.json` via `python3 scripts/render_deprecation_candidates.py --write`._

This file tracks wrappers that could be deprecated in a future wave after reference migration.

## Reference-Proof Command

```bash
rg -n "scripts/deploy\.sh|scripts/deploy_ws\.sh|scripts/btc5_status\.sh|scripts/install_bridge_cron\.sh|scripts/install_jj_health_cron\.sh|scripts/vps_setup\.sh" docs tests deploy scripts Makefile README.md AGENTS.md PROJECT_INSTRUCTIONS.md
```

## Current Blockers

| Script | Reference count | External refs | Why not removed now |
|---|---:|---:|---|
| `scripts/deploy.sh` | 28 | 12 | Active in docs, tests, and scripts; compatibility deploy lane still used |
| `scripts/deploy_ws.sh` | 10 | 1 | Referenced by ops docs and script surfaces |
| `scripts/btc5_status.sh` | 7 | 0 | Referenced by BTC5 rollout/deploy flows |
| `scripts/install_bridge_cron.sh` | 3 | 0 | Active operational helper |
| `scripts/install_jj_health_cron.sh` | 2 | 0 | Canonical install path for health-monitor cron |
| `scripts/vps_setup.sh` | 5 | 0 | Manual bootstrap helper still discoverable |

## Completed In This Wave

| Script | Action | Proof |
|---|---|---|
| `scripts/install_flywheel_cron.sh` | Deleted | Had zero external references before deletion. |

## Exit Criteria For Future Deletion

1. Migrate references in docs/tests/deploy units to the canonical replacement command.
2. Run the reference-proof command and confirm count is 0 for the candidate.
3. Delete wrapper and update scripts catalogs plus regenerated indexes.
