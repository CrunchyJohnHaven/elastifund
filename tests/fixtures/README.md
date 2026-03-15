# Root Test Fixtures

This directory contains static fixtures owned by the root `tests/` suite.

## Rules

- Keep fixture files deterministic and small.
- Reference fixtures via repo-relative paths when output contracts expect path strings.
- Do not duplicate fixtures that already exist under package-local `*/tests/fixtures/` unless the root suite needs an isolated copy.
- Keep relative fixture names unique across `tests/fixtures/` and `nontrading/tests/fixtures/`; this is enforced by `tests/test_fixture_ownership_contract.py`.

## Current Fixtures

- `openclaw/diagnostics.jsonl`: benchmark diagnostics fixture consumed by `tests/nontrading/test_public_report.py`.
