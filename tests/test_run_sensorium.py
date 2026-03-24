from __future__ import annotations

import scripts.run_sensorium as sensorium


def test_extract_local_live_observations_summarises_modes_and_blockers() -> None:
    payload = {
        "generated_at": "2026-03-23T12:00:00+00:00",
        "venues": {
            "alpaca": {
                "effective_mode": "live",
                "feedback_loop_ready": True,
                "blockers": [],
            },
            "kalshi": {
                "effective_mode": "paper",
                "feedback_loop_ready": True,
                "blockers": ["kalshi_auth_missing_or_placeholder"],
            },
        },
    }

    observations = sensorium._extract_local_live_observations(payload)
    obs_ids = {row["obs_id"]: row for row in observations}

    assert obs_ids["local_live:alpaca:mode"]["signal"] == "positive"
    assert obs_ids["local_live:kalshi:mode"]["signal"] == "negative"
    assert obs_ids["local_live:kalshi:blocker_count"]["value"] == 1.0
    assert obs_ids["local_live:venue_live_count"]["value"] == 1.0
    assert obs_ids["local_live:feedback_ready_count"]["value"] == 2.0


def test_extract_local_feedback_observations_surfaces_cross_venue_metrics() -> None:
    payload = {
        "generated_at": "2026-03-23T12:00:00+00:00",
        "mutation_hints": [{"hint_id": "polymarket:live_gate_blocked"}],
        "venues": {
            "alpaca": {
                "feedback_ready": True,
                "recent_activity_count_24h": 3,
                "candidate_count": 2,
                "hints": [],
            },
            "kalshi": {
                "feedback_ready": True,
                "recent_activity_count_24h": 1,
                "settlement_match_rate": 0.75,
                "hints": [{"hint_id": "kalshi:settlement_reconciliation_incomplete"}],
            },
            "polymarket": {
                "feedback_ready": True,
                "recent_activity_count_24h": 12,
                "resolved_rows": 14,
                "trailing_12_live_filled_pnl_usd": 4.2,
                "hints": [],
            },
        },
    }

    observations = sensorium._extract_local_feedback_observations(payload)
    obs_ids = {row["obs_id"]: row for row in observations}

    assert obs_ids["local_feedback:alpaca:candidate_count"]["signal"] == "positive"
    assert obs_ids["local_feedback:kalshi:settlement_match_rate"]["signal"] == "negative"
    assert obs_ids["local_feedback:polymarket:trailing_12_pnl_usd"]["signal"] == "positive"
    assert obs_ids["local_feedback:feedback_ready_count"]["value"] == 3.0
    assert obs_ids["local_feedback:mutation_hint_count"]["value"] == 1.0
