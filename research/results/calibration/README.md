# Calibration Lane Results

This directory stores append-only evidence for the calibration lane.

## Expected Files

- `results.tsv`: raw ledger of keep, discard, and crash outcomes
- `progress.tsv`: derived frontier view
- `progress.svg`: running-best graph
- `summary.md`: lane summary
- `packets/`: benchmark packets for individual runs

## Ground Rule

Calibration wins are benchmark wins on a frozen historical slice. They do **not** automatically imply paper, shadow, or live-trading promotion.

Use this directory as evidence storage, not as a shortcut to deployment claims.
