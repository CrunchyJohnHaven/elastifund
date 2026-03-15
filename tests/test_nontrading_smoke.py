from __future__ import annotations

from scripts.nontrading_smoke import format_smoke_summary, run_smoke


def test_run_smoke_exercises_both_nontrading_lanes() -> None:
    result = run_smoke()

    assert result["revenue_agent"]["campaigns"] == 1
    assert result["revenue_agent"]["leads"] == 6
    assert result["revenue_agent"]["sent"] == 3
    assert result["revenue_agent"]["filtered"] == 3
    assert result["revenue_agent"]["pipeline_status"] == "completed"
    assert result["revenue_agent"]["pipeline_outreach_sent"] == 0
    assert result["revenue_agent"]["pipeline_messages"] == 3
    assert result["revenue_agent"]["recipients"] == [
        "info@usbiz.com",
        "owner@optedin-us.com",
        "sales@vendor.example.com",
    ]

    assert result["digital_products"]["ranked"] == 5
    assert result["digital_products"]["top_title"] == "ADHD Planner System"
    assert result["digital_products"]["vector_dims"] == 768


def test_format_smoke_summary_is_operator_readable() -> None:
    summary = format_smoke_summary(
        {
            "revenue_agent": {
                "campaigns": 1,
                "leads": 6,
                "deliverability_status": "green",
                "sent": 3,
                "filtered": 3,
                "suppressed": 0,
                "pipeline_status": "completed",
                "pipeline_outreach_sent": 0,
                "pipeline_messages": 3,
                "recipients": ["info@usbiz.com"],
            },
            "digital_products": {
                "ranked": 5,
                "top_title": "ADHD Planner System",
                "top_score": 37.8,
                "elastic_index": "elastifund-knowledge",
                "vector_dims": 768,
            },
        }
    )

    assert "nontrading smoke ok" in summary
    assert "revenue_agent campaigns=1 leads=6 sent=3 filtered=3 pipeline_status=completed" in summary
    assert "digital_products ranked=5 top_title=ADHD Planner System" in summary
