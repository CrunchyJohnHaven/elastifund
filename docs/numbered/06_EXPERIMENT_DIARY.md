# 06 Experiment Diary
Version: 1.1.0
Date: 2026-03-14
Source: `docs/diary/*.md`, `research/edge_backlog_ranked.md`, `COMMAND_NODE.md`, `PROJECT_INSTRUCTIONS.md`
Purpose: Provide the canonical chronological record of major experiments, outcomes, and lessons.
Related docs: `03_METRICS_AND_LEADERBOARDS.md`, `04_TRADING_WORKERS.md`, `05_NON_TRADING_WORKERS.md`, `07_FORECASTS_AND_CHECKPOINTS.md`

## How To Read This Diary

The detailed narrative lives in `docs/diary/`.
This document is the chronological index that pulls the important milestones into one operating manual.
It should record wins, misses, and directional changes with equal honesty.

## Chronological Summary

| Date | Topic | Outcome | Why it mattered |
|---|---|---|---|
| 2026-02-15 | Project inception | Started the repo around LLM forecasting and prediction markets | Established the first hypothesis and anti-anchoring focus |
| 2026-02-20 | First backtest on 532 markets | Mixed signal; promising win rate but weak calibration | Revealed that raw probability estimates were not enough |
| 2026-02-22 | Calibration breakthrough | Strong improvement from Platt scaling | Turned calibration into a first-class discipline |
| 2026-02-24 | Kelly sizing work | Position sizing mattered more than expected | Shifted focus from signal alone to signal plus sizing |
| 2026-02-28 | Four signal sources complete | System expanded beyond one estimator | Established the multi-signal architecture |
| 2026-03-01 | Dublin VPS live infrastructure | Remote operating posture became real | Created the basis for paper and later live runtime |
| 2026-03-02 | Edge discovery pipeline | Kill rules became explicit | Reduced the temptation to keep weak ideas alive |
| 2026-03-04 | Cross-platform arb pass | Viable low-risk lane identified | Strengthened the structural and execution focus |
| 2026-03-05 | Calibration discovery write-up | Reinforced anti-anchoring and calibration discipline | Improved public narrative and internal priorities |
| 2026-03-06 | Twelve strategies rejected | Bulk rejection event | Proved the system would kill bad ideas instead of rationalizing them |
| 2026-03-06 | Nine strategies rejected in one day | Another high-friction failure day | Reinforced signal-count and post-cost discipline |
| 2026-03-07 | Day-one live wall | Launch blocked by speed versus edge mismatch | Forced the architecture pivot to multi-speed signals |
| 2026-03-07 | Flywheel formalized | Documentation and research loop tightened | Made the repo itself part of the product |
| 2026-03-07 | Weather bracket failure, latency win | One weather lane rejected, infra insight retained | Showed that failure and useful infra learning can coexist |
| 2026-03-13 | A-6 and B-1 structural alpha killed | Zero evidence after 5-day kill-watch (0/563 neg-risk events, 0/1000+ markets) | Proved that theoretically elegant strategies can have zero practical density. Engineering reallocated to BTC5 and Kalshi. |
| 2026-03-14 | BTC5 guardrail triple-blocker fix | Three simultaneous blockers diagnosed: delta too tight, UP shadow-only, min_buy_price too high | Root cause analysis on zero-fill periods produces more value than speculative new strategies. |

## Durable Lessons

### Calibration Is A Real Lever

The diary repeatedly shows that better calibration improves decision quality more reliably than many prompt tweaks.
That is why calibration remains part of the canonical trading architecture.

### Position Sizing Is Not Secondary

Kelly-related work showed that sizing can matter as much as signal quality.
That changed both execution policy and how signal confidence is interpreted.

### Kill Rules Protect The Project

March 6 was important because rejection became visible and systematic.
The project stopped pretending every coded strategy deserved more patience.

### Market Selection Matters

The March 7 launch wall made a structural point:
the challenge is not only forecasting.
It is matching the right signal family to the right market speed.

### Documentation Is Part Of The Flywheel

The March 7 flywheel work made publishing a first-class deliverable.
A cycle is not done when code lands.
A cycle is done when the evidence and public story are updated too.

## Current Open Threads

The diary now points to three active lines of inquiry:

- collect the first closed trades needed for live calibration evidence
- clear or kill A-6 with maker-fill and settlement data
- prove one non-trading revenue loop that is narrow enough to measure honestly

## Maintenance Rule

Add to this diary when a milestone changes architecture, evidence standards, promotion posture, or the public story.
Do not use it for every trivial code diff.
Use it to preserve the reasoning trail that future contributors actually need.

Last verified: 2026-03-09 against `docs/diary/`, `research/edge_backlog_ranked.md`, and `PROJECT_INSTRUCTIONS.md`.
Next review: 2026-06-09.
