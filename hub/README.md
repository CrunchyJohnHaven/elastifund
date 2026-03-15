# hub

## Responsibility
- Owns the control-plane HTTP/API surface.
- Wires routers for flywheel tasks/findings, benchmark endpoints, and non-trading endpoints.
- Hosts Elastic bootstrap/client helpers for observability and security setup.

## Boundary Contract
- `hub/` exposes APIs and service health only.
- `data_layer/` owns database schema and CRUD.
- `orchestration/` owns allocator/routing logic.
- `flywheel/` owns policy-cycle execution and artifact decisions.

## Naming Contract
- API responses should use resource terms from persistence: `cycle`, `snapshot`, `decision`, `finding`, `task`.
- Keep transport naming (`request`, `response`, `router`) separate from policy naming (`decision`, `promotion`).

## Compatibility Notes
- `hub.app.main:app` is the canonical ASGI entrypoint.
- `hub/app/server.py` remains as a thin compatibility shim that re-exports `app`.

## Verification
- `pytest -q hub/tests/test_flywheel_api.py hub/tests/test_flywheel_openapi_snapshot.py hub/tests/test_config.py`
