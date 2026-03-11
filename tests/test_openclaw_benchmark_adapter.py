import json

from inventory.metrics.evidence_plane import COMPARISON_ONLY_MODE
from inventory.systems.openclaw.adapter import (
    OPENCLAW_AUDITED_COMMIT,
    build_openclaw_benchmark_packet,
    load_jsonl_events,
    load_outcome_comparisons,
)


def test_build_openclaw_benchmark_packet_rolls_up_operational_metrics() -> None:
    packet = build_openclaw_benchmark_packet(
        run_id="openclaw-cycle3-comparison-only",
        diagnostics_events=[
            {"ts": 1_000, "type": "message.processed", "outcome": "completed", "durationMs": 400},
            {"ts": 2_000, "type": "message.processed", "outcome": "completed", "durationMs": 600},
            {"ts": 3_000, "type": "message.processed", "outcome": "error", "durationMs": 800},
            {"ts": 1_500, "type": "model.usage", "costUsd": 0.01, "durationMs": 350},
            {"ts": 2_500, "type": "model.usage", "costUsd": 0.05, "durationMs": 750},
            {"ts": 1_800, "type": "webhook.processed", "durationMs": 40},
            {"ts": 1_900, "type": "queue.lane.enqueue", "queueSize": 4},
            {"ts": 3_100, "type": "diagnostic.heartbeat", "active": 2, "waiting": 1, "queued": 3},
        ],
        outcome_comparisons=[
            {
                "case_id": "landing-page-cta",
                "elastifund_value": {"issues_found": 3},
                "openclaw_value": {"issues_found": 2},
                "winner": "elastifund",
                "notes": "OpenClaw missed one stale CTA.",
            }
        ],
        source_artifacts=["reports/openclaw/raw/diagnostics.jsonl"],
    )

    assert packet.comparison_mode == COMPARISON_ONLY_MODE
    assert packet.allocator_eligible is False
    assert packet.upstream_commit == OPENCLAW_AUDITED_COMMIT
    assert packet.telemetry.decision_count == 3
    assert packet.telemetry.completed_decision_count == 2
    assert packet.telemetry.error_decision_count == 1
    assert packet.telemetry.avg_cycle_time_ms == 600.0
    assert packet.telemetry.p95_cycle_time_ms == 800.0
    assert packet.telemetry.total_cost_usd == 0.06
    assert packet.telemetry.max_lane_queue_size == 4
    assert packet.isolation.wallet_access == "none"
    assert packet.isolation.shared_state_access == "none"
    assert packet.outcome_comparisons[0].winner == "reference"
    assert packet.outcome_comparisons[0].comparison_system_id == "openclaw"


def test_loaders_support_jsonl_and_json_payloads(tmp_path) -> None:
    diagnostics_path = tmp_path / "diagnostics.jsonl"
    diagnostics_path.write_text(
        "\n".join(
            [
                json.dumps({"ts": 1, "type": "message.processed", "outcome": "completed"}),
                json.dumps({"ts": 2, "type": "model.usage", "costUsd": 0.01}),
            ]
        )
        + "\n"
    )
    comparisons_path = tmp_path / "comparisons.json"
    comparisons_path.write_text(
        json.dumps(
            {
                "comparisons": [
                    {
                        "case_id": "case-1",
                        "reference_value": "yes",
                        "comparison_value": "no",
                        "winner": "comparison",
                    }
                ]
            }
        )
    )

    diagnostics_rows = load_jsonl_events(diagnostics_path)
    comparison_rows = load_outcome_comparisons(comparisons_path)

    assert len(diagnostics_rows) == 2
    assert diagnostics_rows[0]["type"] == "message.processed"
    assert comparison_rows[0]["winner"] == "comparison"
