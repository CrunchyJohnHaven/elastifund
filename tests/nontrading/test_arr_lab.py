from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nontrading.arr_lab import build_arr_lab, build_recurring_monitor_summary
from nontrading.offers.website_growth_audit import website_growth_audit_offer


def test_arr_lab_builds_forecast_and_ranked_experiments(tmp_path: Path) -> None:
    offer = website_growth_audit_offer()
    snapshot = {
        "funnel": {
            "qualified_accounts": 4,
            "proposals_sent": 1,
            "meetings_booked": 1,
        },
        "commercial": {
            "revenue_won_usd": 0.0,
            "gross_margin_usd": 0.0,
            "gross_margin_pct": None,
            "time_to_first_dollar_hours": None,
        },
        "fulfillment": {
            "delivered_jobs": 0,
            "monitor_runs_completed": 0,
        },
        "first_dollar_readiness": {
            "status": "setup_only",
        },
    }
    launch_summary = {
        "checkout_ready": False,
        "webhook_ready": False,
        "manual_close_ready": True,
        "fulfillment_ready": True,
        "launchable": False,
        "launch_mode": "manual_close_only",
        "blocking_reasons": [
            "checkout_surface_not_ready",
            "billing_webhook_not_ready",
        ],
        "paid_orders_seen": 0,
        "paid_revenue_usd": 0.0,
        "selected_prospects": 4,
        "curated_candidates": 6,
        "source_artifact": str(tmp_path / "launch_summary.json"),
    }
    bridge_payload = {
        "source_artifact": str(tmp_path / "launch_bridge.json"),
        "curated_candidates": 6,
        "prospects": [
            {
                "company_name": "Beacon Roofing",
                "fit_score": 83.0,
                "estimated_value_usd": 2350.0,
                "segment": "roofing",
                "city": "Austin",
                "state": "TX",
                "recommended_price_tier": {"label": "premium", "price_usd": 2500},
                "evidence": [{}, {}, {}],
            },
            {
                "company_name": "Pure Pest",
                "fit_score": 79.0,
                "estimated_value_usd": 1700.0,
                "segment": "pest_control",
                "city": "Denver",
                "state": "CO",
                "recommended_price_tier": {"label": "standard", "price_usd": 1500},
                "evidence": [{}, {}, {}],
            },
            {
                "company_name": "Metro Fence",
                "fit_score": 76.0,
                "estimated_value_usd": 1625.0,
                "segment": "fencing",
                "city": "Nashville",
                "state": "TN",
                "recommended_price_tier": {"label": "standard", "price_usd": 1500},
                "evidence": [{}, {}],
            },
            {
                "company_name": "Fast HVAC",
                "fit_score": 81.0,
                "estimated_value_usd": 2100.0,
                "segment": "hvac",
                "city": "Phoenix",
                "state": "AZ",
                "recommended_price_tier": {"label": "premium", "price_usd": 2500},
                "evidence": [{}, {}, {}, {}],
            },
        ],
    }
    cycle_reports = [
        {
            "qualified_accounts": 3,
            "proposals_sent": 1,
            "meetings_booked": 1,
            "outcomes_won": 1,
            "accounts_researched": 6,
            "outreach_sent": 3,
        },
        {
            "qualified_accounts": 3,
            "proposals_sent": 1,
            "meetings_booked": 1,
            "outcomes_won": 1,
            "accounts_researched": 5,
            "outreach_sent": 3,
        },
    ]
    recurring_monitor = build_recurring_monitor_summary(
        snapshot=snapshot,
        launch_summary=launch_summary,
        offer=offer,
        bridge_payload=bridge_payload,
        output_path=tmp_path / "nontrading_recurring_monitor" / "latest.json",
    )
    operations = {
        "deliverability_status": "green",
        "revenue_pipeline": {
            "latest_cycle_time_seconds": 95.0,
        },
    }

    arr_lab = build_arr_lab(
        snapshot=snapshot,
        operations=operations,
        launch_summary=launch_summary,
        offer=offer,
        launch_bridge_payload=bridge_payload,
        cycle_reports=cycle_reports,
        recurring_monitor_payload=recurring_monitor,
        output_path=tmp_path / "nontrading_arr_lab" / "latest.json",
    )

    assert arr_lab["schema_version"] == "nontrading_arr_lab.v1"
    assert arr_lab["summary"]["p05_net_cash_30d"] <= arr_lab["summary"]["p50_net_cash_30d"] <= arr_lab["summary"]["p95_net_cash_30d"]
    assert arr_lab["summary"]["p05_arr_usd"] <= arr_lab["summary"]["p50_arr_usd"] <= arr_lab["summary"]["p95_arr_usd"]
    assert arr_lab["inputs"]["prospect_pool"]["selected_prospects"] == 4
    assert arr_lab["inputs"]["prospect_pool"]["segment_mix"][0]["segment"] == "fencing"
    assert arr_lab["recommended_next_experiment"]["experiment_key"] in {
        "better_conversion_packet",
        "better_monitor_upsell",
    }
    assert arr_lab["allocator_metadata"]["recommended_experiment"] == arr_lab["recommended_next_experiment"]["experiment_key"]
    assert arr_lab["confidence"]["score"] > 0.0
