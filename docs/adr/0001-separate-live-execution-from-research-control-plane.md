# ADR 0001: Separate Live Execution from Research and Control-Plane Automation

- Status: Accepted
- Date: 2026-03-07

## Context

Elastifund combines live-money trading code with an aggressive research flywheel and early control-plane automation. Those are different risk classes.

The repo already reflects that split:

- `bot/` and `polymarket-bot/` hold execution-facing logic
- `flywheel/`, `data_layer/`, and `docs/ops/Flywheel_Control_Plane.md` define strategy lifecycle management and peer-learning workflows
- `docs/examples/flywheel_cycle.sample.json` shows that evidence is passed as artifacts rather than by directly mutating the live bot

If the same loop both experiments and trades, self-modifying behavior can widen risk silently.

## Decision

Keep live execution isolated from research and control-plane automation.

That means:

- strategy versions are immutable once registered
- flywheel cycles recommend promotions, demotions, and tasks, but do not rewrite live trading code in place
- live deployment remains gated by explicit stage transitions and risk policy

## Consequences

Positive:

- safer experimentation around live capital
- clearer audit trail for why a strategy changed state
- easier demos because the platform can show self-improvement without pretending to be fully autonomous

Negative:

- more plumbing between evidence stores and execution services
- slower promotion velocity than a fully self-modifying system

## Follow-up

Future hub services should preserve this boundary. Knowledge sharing can influence what gets tested next, but not directly force capital allocation or live order placement.
