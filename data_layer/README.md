# data_layer

## Responsibility
- Owns durable persistence contracts for control-plane state.
- Defines SQLAlchemy schema, migrations, CRUD primitives, and CLI entrypoints.
- Does not own orchestration policy, routing logic, or hub HTTP API semantics.

## Canonical Objects
- `cycle`: one control-plane run (`flywheel_cycles`).
- `snapshot`: one environment/state measurement for a deployment (`daily_snapshots`).
- `decision`: one promotion/demotion/hold/kill decision (`promotion_decisions`).
- `finding`: one structured lesson/regression signal (`flywheel_findings`).
- `task`: one explicit next action (`flywheel_tasks`).

## Boundary With Neighbor Packages
- `orchestration/`: computes allocation and routing decisions; persists via this package.
- `flywheel/`: runs policy cycles and emits findings/tasks; persists via this package.
- `hub/`: exposes read/write control-plane APIs backed by this package.

## Operator Entrypoint
- `python -m data_layer --help`
- `python3 -m data_layer flywheel-naming-check`
