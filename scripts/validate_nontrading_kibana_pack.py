#!/usr/bin/env python3
"""Validate that the non-trading Kibana pack exposes the required ops surfaces."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from data_layer import database
from flywheel.kibana_pack import (
    DEFAULT_AUDIT_OPS_PATH,
    DEFAULT_B1_TEMPLATE_AUDIT_PATH,
    DEFAULT_GUARANTEED_DOLLAR_AUDIT_PATH,
    DEFAULT_RESEARCH_METRICS_GLOB,
    DEFAULT_REVENUE_DB_PATH,
    build_phase6_dashboard_pack,
)
from orchestration.store import DEFAULT_DB_PATH as DEFAULT_ALLOCATOR_DB_PATH

REQUIRED_DASHBOARDS = {
    "Audit Engine Performance",
    "Prospect Pipeline",
    "Checkout Funnel",
    "Fulfillment Status",
    "Refunds and Churn",
    "Allocator Decisions",
    "Knowledge-Pack Activity",
}

REQUIRED_ALERTS = {
    "checkout-webhook-failures",
    "fulfillment-stalls",
    "refund-spikes",
    "complaint-spikes",
    "missing-worker-activity",
    "negative-roi-regime",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-url", help="Optional control-plane DB URL (defaults to an isolated in-memory DB)")
    parser.add_argument("--allocator-db", default=str(DEFAULT_ALLOCATOR_DB_PATH))
    parser.add_argument("--revenue-db", default=str(DEFAULT_REVENUE_DB_PATH))
    parser.add_argument("--guaranteed-dollar-audit", default=str(DEFAULT_GUARANTEED_DOLLAR_AUDIT_PATH))
    parser.add_argument("--b1-template-audit", default=str(DEFAULT_B1_TEMPLATE_AUDIT_PATH))
    parser.add_argument("--research-metrics-glob", default=DEFAULT_RESEARCH_METRICS_GLOB)
    parser.add_argument("--audit-ops", default=str(DEFAULT_AUDIT_OPS_PATH))
    args = parser.parse_args(argv)

    database.reset_engine()
    engine = database.get_engine(args.db_url or "sqlite:///:memory:")
    database.init_db(engine)
    session = database.get_session_factory(engine)()
    try:
        pack = build_phase6_dashboard_pack(
            session,
            allocator_db_path=args.allocator_db,
            revenue_db_path=args.revenue_db,
            guaranteed_dollar_audit_path=args.guaranteed_dollar_audit,
            b1_template_audit_path=args.b1_template_audit,
            research_metrics_glob=args.research_metrics_glob,
            audit_ops_path=args.audit_ops,
        )
    finally:
        session.close()
        database.reset_engine()

    dashboard_titles = {row["title"] for row in pack["dashboards"]}
    alert_ids = {row["id"] for row in pack["alert_rules"]["rules"]}
    missing_dashboards = sorted(REQUIRED_DASHBOARDS - dashboard_titles)
    missing_alerts = sorted(REQUIRED_ALERTS - alert_ids)
    result = {
        "ok": not missing_dashboards and not missing_alerts,
        "dashboards": len(pack["dashboards"]),
        "alert_rules": len(pack["alert_rules"]["rules"]),
        "missing_dashboards": missing_dashboards,
        "missing_alerts": missing_alerts,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
