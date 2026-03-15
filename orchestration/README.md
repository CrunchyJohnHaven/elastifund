# orchestration

## Responsibility
- Owns allocation and routing logic before persistence/API publication.
- Defines canonical candidate/routing/lifecycle contracts and allocator primitives.
- Persists allocator outcomes via `AllocatorStore` in this package.

## Canonical Objects
- `candidate`: venue-agnostic opportunity record (`CandidateRecord`).
- `route_decision`: allocator acceptance/rejection decision (`RouteDecision`).
- `lifecycle_event`: state transition for routed trades (`TradeLifecycleEvent`).
- `attribution`: closed-trade attribution record (`ClosedTradeAttribution`).

## Boundary Contract
- `orchestration/` computes and validates decisions.
- `data_layer/` stores control-plane records.
- `flywheel/` converts snapshots into policy decisions and tasks.
- `hub/` serves those records over HTTP.

## Naming Rule
- Use `candidate`, `route_decision`, and `lifecycle` terms here.
- Reserve `snapshot` and `promotion_decision` terms for `data_layer/` + `flywheel/` policy flows.
