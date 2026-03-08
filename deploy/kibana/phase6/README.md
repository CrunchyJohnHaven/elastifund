# Phase 6 Kibana Pack

This directory packages the markdown-first Kibana artifacts for the Elastifund monitoring and leaderboard layer.

## Contents

| File | Purpose |
|---|---|
| `phase6_dashboard_model.json` | normalized source model built from the control-plane and benchmark data |
| `phase6_dashboards.json` | rendered dashboard specs |
| `phase6_saved_objects.ndjson` | Kibana saved-object import pack |
| `phase6_canvas_workpad.json` | executive workpad/page spec |
| `phase6_alert_rules.json` | repo-side alert definitions and current evaluations |

## Regenerate

```bash
python3 -m data_layer flywheel-kibana-pack --output-dir deploy/kibana/phase6
```

## Import Workflow

1. Import `phase6_saved_objects.ndjson` in Kibana Saved Objects.
2. Rebuild the Canvas workpad from `phase6_canvas_workpad.json` if you want the executive deck.
3. Translate `phase6_alert_rules.json` into live Kibana rules after the target Elastic indices exist.

## Caveats

- The dashboards are markdown-first because the repo does not yet store raw Elastic Lens/TSVB exports.
- The Canvas artifact is a deterministic page spec, not a direct Kibana export.
- The alert file evaluates the rules against repo state; it is not a POST-ready Kibana payload.
- Non-trading revenue is operational-state only until a billing ledger lands in the repo.
