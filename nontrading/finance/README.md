# Finance Control Plane (`nontrading/finance`)

This package is the personal CFO/treasury lane for Elastifund.

## Canonical Entrypoint

```bash
python -m nontrading.finance sync
python -m nontrading.finance audit
python -m nontrading.finance allocate
python -m nontrading.finance execute --mode shadow
```

## Responsibility Boundary

- `main.py`: operator CLI commands and report emission.
- `store.py`: finance SQLite truth store.
- `policy.py`: rollout-gate and policy evaluation.
- `allocator.py`: recommendation scoring and budget allocation plan.
- `executor.py`: policy-gated action execution.
- `connectors/`: source adapters for imports and runtime context.

## Safety Notes

- This path is treasury-sensitive.
- Keep behavior aligned with finance policy knobs in `.env` and operator docs.
- Do not widen autonomy beyond configured caps/whitelist rules.
