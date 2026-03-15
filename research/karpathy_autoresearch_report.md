# Karpathy Autoresearch Pattern Review for Elastifund

**Date:** 2026-03-08
**Author:** Codex
**Status:** additive repo analysis and implementation note

## Executive Summary

Elastifund already shares the spirit of `autoresearch`: fixed loops, explicit kill rules, public failure logs, and a belief that the compounding asset is the research system rather than any single trade. The gap is that `autoresearch` is much tighter as an optimization machine. It has one mutable code surface, one immutable harness, one fixed time budget, one scalar objective, one append-only experiment ledger, and one visual progress artifact. That tightness is the part worth importing.

The main recommendation is not to copy Karpathy's setup onto the whole repo at once. That would be too broad and would mix live execution, data drift, and changing research criteria into one noisy loop. Instead, Elastifund should adopt the `autoresearch` pattern lane by lane, starting with the cleanest benchmarkable surface: forecasting and calibration quality on a frozen resolved-market slice, then expanding to strategy ranking and finally execution-quality research.

An `autoresearch`-style progress export is now part of this repo via `scripts/render_autoresearch_progress.py`. It reads `reports/run_*_metrics.json` artifacts and emits:

- `research/autoresearch_progress.tsv`
- `research/autoresearch_progress.svg`
- `research/autoresearch_velocity.tsv`
- `research/autoresearch_velocity.svg`

That gives Elastifund the same keep/discard visual grammar, using the current top-hypothesis composite score as an interim metric until a stricter benchmark metric is frozen.

On the current artifact set, the graph shows 18 recorded runs and only 1 kept high-water mark. That is not a failure of the graph. It is evidence that Elastifund needs a tighter benchmark contract if it wants autonomous iteration to produce a visible frontier of improvement.

The new velocity export makes the next question explicit: how fast is the frontier moving, and is that rate itself rising or flattening. On the current proxy artifact set, the answer is flat after the initial baseline, which is useful evidence in its own right.

![Autoresearch-style progress](research/autoresearch_progress.svg)

![Autoresearch improvement velocity](research/autoresearch_velocity.svg)

## Source Bundle for Deep Research

External `autoresearch` files worth handing to deeper research directly:

- Repo: <https://github.com/karpathy/autoresearch>
- README: <https://github.com/karpathy/autoresearch/blob/master/README.md>
- Agent contract: <https://github.com/karpathy/autoresearch/blob/master/program.md>
- Mutable training file: <https://github.com/karpathy/autoresearch/blob/master/train.py>
- Immutable prep/eval harness: <https://github.com/karpathy/autoresearch/blob/master/prepare.py>
- Progress artifact: <https://github.com/karpathy/autoresearch/blob/master/progress.png>

Local Elastifund files that best map to those ideas:

- Research loop: `src/research_loop.py`
- Hypothesis gates and ranking: `src/hypothesis_manager.py`
- Artifact generation: `src/reporting.py`
- Hypothesis registry: `src/edge_registry.py`
- Flywheel scorecards: `flywheel/reporting.py`
- Live execution lane: `bot/jj_live.py`
- Public architecture framing: `docs/ARCHITECTURE.md`
- Performance framing: `docs/PERFORMANCE.md`
- Research log: `docs/RESEARCH_LOG.md`
- Benchmark methodology: `docs/website/benchmark-methodology.md`
- Calibration lane: `bot/adaptive_platt.py`, `src/confidence_calibration.py`, `docs/strategy/llm_probability_calibration_background.md`

## What `autoresearch` Actually Is

`autoresearch` is not "let an LLM code forever." It is a sharply bounded hill-climber:

1. `prepare.py` is effectively read-only and defines the fixed setup, data preparation, and evaluation contract.
2. `train.py` is the only code surface the agent is meant to mutate.
3. `program.md` is the human-authored operating system for the research org.
4. Every experiment gets the same 5-minute wall-clock budget.
5. Every run is judged on one scalar objective: `val_bpb`.
6. Every run is recorded in `results.tsv` as `keep`, `discard`, or `crash`.
7. Progress is visible as a running-best graph, not just a pile of logs.

That combination matters because it removes ambiguity. The agent never has to ask:

- which file should I touch?
- what counts as success?
- how much compute am I allowed to burn?
- should I keep this change or revert it?

Elastifund already has more sophistication than `autoresearch`, but it is more ambiguous as a self-improving system.

## Where Elastifund Already Matches the Pattern

### 1. Research is already formalized as a loop

`src/research_loop.py` already does the high-level orchestration: collect data, build features, run hypotheses, backtest, stress costs, rank results, and write artifacts. That is structurally aligned with Karpathy's framing.

### 2. The repo already values failure logs

`docs/RESEARCH_LOG.md`, `research/what_doesnt_work_diary_v1.md`, and the report artifacts in `reports/` already treat rejected ideas as first-class evidence. This is philosophically very close to `autoresearch`.

### 3. The flywheel already separates promotion from experimentation

`docs/ops/Flywheel_Control_Plane.md` and `flywheel/reporting.py` define promotion ladders, policy boundaries, and machine-readable outputs. This is a stronger safety model than `autoresearch`, especially because Elastifund has live-capital implications.

### 4. Some lanes already have clean objective candidates

The forecasting and calibration lane is especially promising because Brier score, calibration error, and held-out validation are naturally benchmarkable. `bot/adaptive_platt.py` and `docs/strategy/llm_probability_calibration_background.md` are the clearest local analogues to Karpathy's fixed `val_bpb` target.

## What Elastifund Would Gain from Karpathy's Coding Patterns

### 1. A single benchmark objective per lane

Right now Elastifund mixes many metrics at once:

- EV
- win rate
- p-value
- calibration error
- drawdown
- promotion status
- recommendation strings

That is appropriate for portfolio governance, but it is suboptimal for autonomous iteration. Karpathy's pattern works because the agent is climbing one hill, not six.

For Elastifund, the right move is to define one scalar objective for each autonomous lane:

- Forecast/calibration lane: held-out Brier score or Brier plus ECE penalty.
- Strategy-ranking lane: fixed-dataset composite score with frozen weights and frozen cost assumptions.
- Execution-quality lane: fill-adjusted realized edge on a fixed replay dataset.

Without that, the loop will keep generating artifacts without creating a clean improvement frontier.

### 2. A much smaller mutable code surface

`autoresearch` improves quickly because the agent edits one file. Elastifund currently spreads research behavior across:

- `src/strategies/`
- `src/hypothesis_explorer.py`
- `src/hypothesis_manager.py`
- `bot/ensemble_estimator.py`
- `bot/adaptive_platt.py`
- `signals/`
- `strategies/`
- runtime and ops files

That breadth is powerful for humans, but noisy for autonomous hill-climbing. The improvement pattern to import is:

- freeze the harness
- pick one mutable locus
- force all experiments through the same evaluator

Recommended first mutable locus:

- `bot/adaptive_platt.py` for calibration search, or
- one isolated strategy module in `src/strategies/` for maker-only backtest iteration

Do not start by letting an agent mutate the entire live trading stack.

### 3. A genuinely immutable harness

Elastifund has a research harness, but it is not fully immutable in the `autoresearch` sense. Data windows, registries, thresholds, scoring weights, and artifact logic can all move together. That makes it harder to know whether the system improved or whether the ruler changed.

The Karpathy pattern suggests creating a frozen benchmark package:

- fixed resolved-market slice
- fixed cost assumptions
- fixed train/validation split
- fixed reporting schema
- fixed objective function

This would make each autonomous cycle comparable across days and across branches.

### 4. Keep/discard semantics at the commit level

Elastifund writes excellent reports, but it does not yet make the core research decision as explicit as `keep`, `discard`, or `crash` on each experiment. Karpathy's pattern forces version control to reflect the hill-climbing decision.

That would improve this repo in two ways:

- faster rollback discipline
- a clearer audit trail for why a change stayed

For Elastifund, the right adaptation is:

- branch per benchmark lane or per flywheel cycle
- append-only result ledger
- revert non-improving benchmark mutations in that lane

This should be done only for benchmark lanes, not for the whole repo.

### 5. A single human-authored research contract

`program.md` is one of the strongest ideas in `autoresearch`. It separates:

- the mutable research subject
- the immutable evaluator
- the human's strategy for how the agent should behave

Elastifund currently spreads this contract across `README.md`, `CLAUDE.md`, `PROJECT_INSTRUCTIONS.md`, `COMMAND_NODE.md`, architecture docs, ops docs, diary notes, and prompt files. That makes context rich but diffuse.

Recommended addition:

- `research/programs/calibration_lane.md`
- `research/programs/strategy_lane.md`

Each should define:

- in-scope files
- out-of-scope files
- benchmark command
- metric to optimize
- what counts as keep/discard/crash
- safety boundaries

This is the cleanest way to import Karpathy's "research org code" idea without destabilizing the rest of the repo.

### 6. A visible improvement frontier

The `progress.png` graph in `autoresearch` is deceptively important. It turns dozens of experiments into one glanceable answer:

- are we actually improving?
- how often do changes help?
- what ideas became new high-water marks?

Elastifund had the logs but not the same visual frontier. That gap is now partially closed with `scripts/render_autoresearch_progress.py`, which renders the same keep/discard/running-best pattern for current run artifacts and now derives a second velocity view from the same ledger.

Important caveat: the current graph uses top-hypothesis composite score from `reports/run_*_metrics.json`. That is useful as a visualization, but it is still an interim proxy. The long-term graph should switch to a frozen benchmark objective.

## Best First Lane to Apply This Pattern

The best first target is the forecast and calibration lane, not live execution.

Why this lane is best:

- It already has natural scalar objectives: Brier, ECE, log loss.
- It can be evaluated on a frozen resolved dataset.
- It avoids live fill noise, queue-position randomness, and venue drift.
- It is already documented as a major leverage point in this repo.

Recommended starting surface:

- freeze benchmark data from the resolved-market calibration corpus
- make `bot/adaptive_platt.py` the mutable file for the lane
- keep data extraction and evaluation immutable
- record each variant in a `results.tsv`
- render `progress.svg` after every benchmark batch

Only after this works should the pattern expand to:

1. strategy scoring on a frozen replay dataset
2. maker execution quality on a replay or shadow dataset
3. broader control-plane mutation

## Where the Pattern Does **Not** Transfer Cleanly

Some parts of `autoresearch` should not be copied literally.

### 1. Whole-repo self-modification

That is fine for a toy training loop. It is wrong for a repo that contains:

- live trading logic
- capital allocation logic
- deployment tooling
- public docs used as evidence artifacts

Elastifund needs lane isolation, not repo-wide mutation.

### 2. One metric for the entire business

`val_bpb` works for a model-training demo. Elastifund spans forecasting, market structure, execution, and operational reliability. It needs one metric per lane, not one metric for the whole company.

### 3. Ignoring operational safety

`autoresearch` can tolerate crashes as a normal part of the loop. Elastifund needs stronger guardrails because some branches of the system can affect live capital or public claims. The flywheel policy documents are correct to be stricter here.

## Concrete Repo Improvements Recommended

### Immediate

1. Keep the new `autoresearch`-style graph in the repo and refresh it after benchmarkable research runs.
2. Add lane-specific `program.md` equivalents so the next deep-research pass gets one clear contract per lane.
3. Freeze a benchmark v1 for the calibration lane and treat its evaluator as immutable.

### Next

1. Add a lane-local `results.tsv` with `keep`, `discard`, `crash`.
2. Gate benchmark mutations on whether they beat the running best on the frozen benchmark.
3. Add branch naming conventions for benchmark runs.

### Later

1. Promote the progress graph into the website or public benchmark section.
2. Add separate graphs for calibration, strategy ranking, and execution quality.
3. Feed the result ledgers into the flywheel control plane so promotion decisions inherit benchmark history automatically.

## Suggested Repo Attribution

Recommended README-level wording:

> Inspired by Andrej Karpathy's brilliant work as always, especially the `autoresearch` pattern of fixed-budget autonomous iteration against a single benchmark.

That keeps the attribution explicit without implying that Elastifund is a copy of `autoresearch`.

## Bottom Line

The most valuable lesson from `autoresearch` is not that AI agents should write more code. It is that autonomous improvement gets real only when the search space is constrained, the benchmark is frozen, the outcome is scalar, and every experiment is logged against a running best.

Elastifund already has the ambition, the loop mentality, and the evidence culture. What it can still gain from Karpathy's coding pattern is sharper experimental geometry:

- one lane at a time
- one metric at a time
- one mutable surface at a time
- one graph that shows whether the machine is genuinely getting better
