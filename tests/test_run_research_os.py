from __future__ import annotations

from scripts.run_research_os import _build_health_summary, _build_opportunity_exchange


def test_opportunity_exchange_includes_local_feedback_hints() -> None:
    local_feedback = {
        "mutation_hints": [
            {
                "lane": "alpaca",
                "venue": "alpaca",
                "severity": "high",
                "summary": "Alpaca produced no local candidates in the latest cycle.",
                "rationale": "Thresholds are too restrictive.",
            }
        ]
    }

    opps = _build_opportunity_exchange(
        snapshots={},
        lanes_raw={},
        sensorium=None,
        novelty_discovery=None,
        novel_edge=None,
        local_feedback=local_feedback,
    )

    assert any(opp.lane == "alpaca" and "no local candidates" in opp.description.lower() for opp in opps)


def test_health_summary_includes_local_feedback_counts() -> None:
    local_feedback = {
        "venues": {
            "alpaca": {"feedback_ready": True, "effective_mode": "paper"},
            "polymarket": {"feedback_ready": True, "effective_mode": "live"},
        }
    }

    health = _build_health_summary({}, local_feedback)

    assert health["local_feedback_loaded"] is True
    assert health["feedback_ready_venues"] == 2
    assert health["live_enabled_venues"] == ["polymarket"]
