# Revenue Audit Surface (`nontrading/revenue_audit`)

This package owns the Website Growth Audit checkout and fulfillment surfaces.

## Responsibility Boundary

- Prospect discovery and issue detection.
- Offer-scoped checkout payload construction.
- Stripe checkout session and webhook handling.
- Fulfillment status progression and recurring-monitor enrollment.
- Launch readiness and launch-batch summary artifacts.

## Canonical States

- **Manual-close-ready**: prospect selection, talk tracks, and approval routing work without requiring hosted checkout.
- **Automated-checkout-ready**: checkout routes, provider secrets, webhook verification, and fulfillment pipeline pass readiness checks.

## Entrypoints

- Imported by `nontrading/pipeline.py` and scripts under `scripts/`.
- Primary runtime integration is via service classes in `service.py` and `fulfillment.py`.
