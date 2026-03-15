# Tests Surface Map

| Metadata | Value |
|---|---|
| Canonical scope | `tests/`, root `conftest.py`, `pytest.ini` |
| Role | Cross-package integration/unit regression and operator smoke coverage |
| Last updated | 2026-03-11 |

## Naming Convention

- Python tests use `test_<subject>.py`.
- Root non-trading contract tests use `test_<subject>_contract.py` when a package-local test of the same subject exists under `nontrading/tests/`.
- Shared fixtures live under `tests/fixtures/` when consumed by this root suite.
- Package-local fixtures stay in each package's own `*/tests/fixtures/`.

## Fixture Ownership

| Fixture path | Owner | Used by |
|---|---|---|
| `tests/fixtures/openclaw/diagnostics.jsonl` | root `tests/` suite | `tests/nontrading/test_public_report.py` |
| `nontrading/tests/fixtures/` | `nontrading/tests` suite | nontrading package tests |

## Non-Trading Boundary

- `nontrading/tests/` is the package-local test lane for internal module behavior.
- `tests/nontrading/` is the root integration lane for cross-surface contracts and report expectations.
- Root non-trading contract files use `_contract` suffix to avoid filename collisions with package-local tests.

## Marker Taxonomy

- `unit`: package-local tests inside `*/tests/` package lanes.
- `integration`: root `tests/` cross-module integration tests.
- `contract`: contract tests, including `tests/nontrading/` and explicit contract checks.
- `smoke`: fast operator readiness checks.
- `live_coupled`: opt-in tests gated by `ELASTIFUND_ENABLE_JJ_LIVE_SUITE=1`.

Collection applies these markers automatically by path in root [conftest.py](/Users/johnbradley/Desktop/Elastifund/conftest.py).

## Narrow Test Entrypoints

| Subsystem | Narrowest command |
|---|---|
| Root nontrading integration | `pytest -q tests/nontrading` |
| Finance control-plane contract | `pytest -q tests/nontrading/test_finance_control_plane.py` |
| Nontrading smoke wrapper | `pytest -q tests/test_nontrading_smoke.py` |
| Fixture ownership contract | `pytest -q tests/test_fixture_ownership_contract.py` |
| Trading execution surface (root suite) | `pytest -q tests/test_*execution*.py` |
| Runtime/posture reporting (build/gates) | `pytest -q tests/test_remote_cycle_status_build_and_gates.py` |
| Runtime/posture reporting (write/metrics) | `pytest -q tests/test_remote_cycle_status_write_metrics_and_snapshot.py` |
| Runtime/posture reporting (write/contracts) | `pytest -q tests/test_remote_cycle_status_write_runtime_contracts.py` |
| Runtime/posture reporting (render/bridge) | `pytest -q tests/test_remote_cycle_status_render_bridge.py` |
| BTC 5m maker suite (primitives) | `pytest -q bot/tests/test_btc_5min_maker_primitives.py` |
| BTC 5m maker suite (process core) | `pytest -q bot/tests/test_btc_5min_maker_process_window_core.py` |
| BTC 5m maker suite (process guardrails) | `pytest -q bot/tests/test_btc_5min_maker_process_window_guardrails.py` |
| BTC 5m maker suite (reporting) | `pytest -q bot/tests/test_btc_5min_maker_reporting.py` |
| Scale comparison (core) | `pytest -q backtest/tests/test_scale_comparison_core.py` |
| Scale comparison (wallet flow) | `pytest -q backtest/tests/test_scale_comparison_wallet_flow.py` |
| Scale comparison (signal enrichment) | `pytest -q backtest/tests/test_scale_comparison_signal_enrichment.py` |
| Script wrappers with test hooks | `pytest -q tests/test_*script*.py` |
| JJ live coupled tests (opt-in) | `ELASTIFUND_ENABLE_JJ_LIVE_SUITE=1 pytest -q tests/test_jj_live_combinatorial.py tests/test_jj_live_sum_violation.py` |
| Unit marker shard | `make test-unit` |
| Integration marker shard | `make test-integration` |
| Contract marker shard | `make test-contract` |
| Full verification matrix (main/nightly/manual parity) | `make verify-full-matrix` |

## Discovery Rules

- Use `pytest --collect-only -q <path>` to confirm target scope before full runs.
- Prefer path-scoped commands over keyword selection to avoid accidental broad collection.
- Keep new tests in the closest package lane unless they validate cross-package behavior.
- Fixture references should use `tests/fixtures/...` or `nontrading/tests/fixtures/...` paths and resolve to exactly one owned lane.
- Root nontrading tests that overlap package-local subjects must use `_contract` suffix (enforced by `tests/test_fixture_ownership_contract.py`).
