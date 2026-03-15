# Replit Share Manifest - 2026-03-11

Status: canonical checklist
Last updated: 2026-03-11
Category: checklist
Canonical: yes
Purpose: define the exact files to hand to Replit and the standard outward naming convention

## Standard Naming Convention

When a file is handed to Replit, refer to it with this stable outward label format:

`REPLIT_SHARE_<NN>_<UPPER_SNAKE_PURPOSE>`

Rules:

- Keep `NN` zero-padded and ordered by dependency.
- Keep the outward label stable even if the canonical repo path changes later.
- Share canonical repo files, not ad hoc copies.
- Prefer one manifest plus canonical file paths over duplicate exported files.

## Share Set

| Outward label | Canonical repo file | Why Replit needs it |
|---|---|---|
| `REPLIT_SHARE_01_SITE_BUILD_CONTRACT` | `REPLIT_NEXT_BUILD.md` | master website build contract and route acceptance criteria |
| `REPLIT_SHARE_02_PUBLIC_HOMEPAGE` | `index.html` | current public homepage surface |
| `REPLIT_SHARE_03_ELASTIC_ROUTE` | `elastic/index.html` | employee-facing Elastic story |
| `REPLIT_SHARE_04_DEVELOP_ROUTE` | `develop/index.html` | public onboarding path |
| `REPLIT_SHARE_05_BUILD_ROUTE` | `build/index.html` | hidden internal onboarding packet |
| `REPLIT_SHARE_06_SHARED_SITE_LOGIC` | `site.js` | shared runtime binding and artifact hydration |
| `REPLIT_SHARE_07_SHARED_SITE_STYLE` | `site.css` | shared visual system |
| `REPLIT_SHARE_08_FORK_AND_RUN_DOC` | `docs/FORK_AND_RUN.md` | canonical repo boot path |
| `REPLIT_SHARE_09_EMPLOYEE_BUILD_DISPATCH` | `docs/ops/elastic_employee_build_dispatch_20260311.md` | internal onboarding execution plan |
| `REPLIT_SHARE_10_REPORTS_CONTRACT` | `reports/README.md` | machine-truth artifact contract for public surfaces |

## Hand-off Rule

If Replit needs context beyond the ten files above, add the next file to this manifest instead of inventing a one-off export name.
