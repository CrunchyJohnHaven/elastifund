# Revenue Audit Fulfillment Runbook

Use this when a real Website Growth Audit payment has landed and JJ-N needs to move from `paid_order_seen` to `first_dollar_observed` without manual DB edits.

## Operator Flow

1. Confirm the order is paid and queued.

```bash
python3 - <<'PY'
from pathlib import Path
from nontrading.revenue_audit.store import RevenueAuditStore

db_path = Path("data/revenue_agent.db")
order_id = "replace-with-order-id"
order = RevenueAuditStore(db_path).get_order(order_id)
print({
    "order_id": order.order_id,
    "status": order.status,
    "fulfillment_status": order.fulfillment_status,
    "paid_at": order.paid_at,
})
PY
```

Expected: `status=paid` and `fulfillment_status=queued`.

2. Fulfill the order, generate the delivery packet, generate the baseline monitor delta, and regenerate the public report plus sidecars.

```bash
python3 scripts/run_revenue_audit_fulfillment_flow.py \
  --db-path data/revenue_agent.db \
  --order-id replace-with-order-id
```

Default outputs land under `reports/nontrading/operations/<order-id>/`.

3. Verify the final machine-readable surfaces.

Check:
- `reports/nontrading/operations/<order-id>/nontrading_public_report.json`
- `reports/nontrading/operations/<order-id>/nontrading_launch_summary.json`
- `reports/nontrading/operations/<order-id>/nontrading_first_dollar_status.json`
- `reports/nontrading/operations/<order-id>/summary.json`

Expected final state:
- `headline.claim_status=actual_revenue_recorded`
- `first_dollar_readiness.status=first_dollar_observed`
- `fulfillment.delivered_jobs >= 1`
- `fulfillment.monitor_runs_completed >= 1`

## Deterministic Drill

This repo now has a focused drill proving the exact transition sequence:

```bash
pytest -q nontrading/tests/test_fulfillment.py tests/nontrading/test_fulfillment_public_report.py
```

That drill verifies:
- paid webhook only yields `paid_order_seen`
- fulfillment creates the revenue evidence flip to `first_dollar_observed`
- delivery artifacts and monitor artifacts are counted in the regenerated public report
