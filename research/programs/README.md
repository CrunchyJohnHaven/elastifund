# Research Programs

Lane-local research programs are Elastifund's equivalent of `program.md` in
Karpathy's `autoresearch` repo.

Each program defines:

- the one benchmark lane being optimized
- the one mutable surface the agent may change
- the immutable evaluator and dataset contract
- the keep/discard/crash decision rule
- the safety boundary between research and live execution

Start with the calibration lane. Add new lane programs only when the benchmark
surface is frozen enough to make experiment-to-experiment comparisons honest.
