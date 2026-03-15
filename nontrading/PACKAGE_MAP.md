# Nontrading Package Map

| Path | Role | Operator entrypoint | Status |
|---|---|---|---|
| `nontrading/main.py` | Revenue lane CLI runner | `python -m nontrading` | Canonical |
| `nontrading/pipeline.py` | Five-stage revenue pipeline orchestration | imported by `nontrading/main.py` | Canonical |
| `nontrading/finance/main.py` | Finance control-plane CLI | `python -m nontrading.finance` | Canonical |
| `nontrading/revenue_audit/` | Checkout, webhook, and fulfillment contracts | package API + scripts | Canonical |
| `nontrading/offers/` | Offer definitions (price, delivery, terms) | imported by pipeline/revenue_audit | Canonical |
| `nontrading/campaigns/` | Campaign sequencing and template selection | imported by pipeline | Canonical |
| `nontrading/email/` | Rendering, provider adapters, and sending abstractions | imported by pipeline | Canonical |
| `nontrading/digital_products/main.py` | Digital-products discovery CLI | `python -m nontrading.digital_products` | Canonical |
| `nontrading/digital_products/` | Niche discovery + optional CRM sync | package API + CLI | Canonical |
| `nontrading/importers/csv_import.py` | Lead import utility | `python -m nontrading.importers.csv_import` | Canonical |
| `nontrading/approval.py` | Unified approval gate implementation | imported across lane | Canonical |
| `nontrading/approval_gate.py` | Re-export shim for legacy imports | none | Compatibility shim |
| `nontrading/engines/` | Stage-level engine implementations | imported by pipeline and tests | Canonical (with compatibility methods) |
| `nontrading/arr_lab.py` | ARR and recurring-monitor reporting helpers | scripts/report generation | Canonical reporting |
| `nontrading/first_dollar.py` | First-dollar readiness and scoreboard helpers | scripts/report generation | Canonical reporting |

## Naming Conventions

- Python modules remain `snake_case`.
- Offer/runtime naming keeps `website_growth_audit` as the canonical slug surface.
- Launch-mode naming is canonicalized to `manual_close_only` and `approval_queue_only` where applicable.

## Placement Rule For New Code

- Put revenue workflow runtime changes under `nontrading/` root modules and `nontrading/revenue_audit/`.
- Put finance policy and execution changes only under `nontrading/finance/`.
- Put research-only commercialization scoring/discovery under `nontrading/digital_products/`.
- Add compatibility shims only when import breakage would occur; otherwise prefer one canonical module.
