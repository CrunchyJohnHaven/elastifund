from __future__ import annotations

import json
from pathlib import Path

from orchestration.candidate_contract import (
    LifecycleState,
    ThesisFamily,
    compute_route_score,
    is_valid_lifecycle_transition,
    load_candidate_records,
    normalize_candidate_record,
    simulate_closed_trade_flywheel,
)
from scripts.run_allocator_contract_dispatch import build_reports


def test_route_score_keeps_narrative_inactive_when_fields_absent() -> None:
    baseline_score, baseline_terms = compute_route_score(
        {
            "fee_adjusted_edge": 0.08,
            "fill_probability": 0.6,
            "toxicity": 0.2,
            "wallet_consensus_score": 0.7,
            "lmsr_gap": 0.1,
            "vpin": 0.15,
            "ofi": 0.2,
            "spread_bps": 8,
            "data_quality_flags": [],
        }
    )
    narrative_score, narrative_terms = compute_route_score(
        {
            "fee_adjusted_edge": 0.08,
            "fill_probability": 0.6,
            "toxicity": 0.2,
            "wallet_consensus_score": 0.7,
            "lmsr_gap": 0.1,
            "vpin": 0.15,
            "ofi": 0.2,
            "spread_bps": 8,
            "narrative_heat": 0.8,
            "yes_crowding": 0.7,
            "base_rate_gap": -0.3,
            "no_bias_prior": 0.9,
            "data_quality_flags": [],
        }
    )

    assert baseline_terms["narrative_term"] == 0.0
    assert narrative_terms["narrative_term"] > 0.0
    assert narrative_score > baseline_score


def test_normalize_candidate_record_uses_hints_and_defaults() -> None:
    record = normalize_candidate_record(
        {
            "id": "mkt-123",
            "title": "BTC above 90k by noon?",
            "best_yes": 0.41,
            "fair_probability": 0.52,
            "expected_maker_fill_probability": 0.45,
            "vpin": 0.2,
        },
        venue_hint="polymarket",
        thesis_hint=ThesisFamily.WALLET_FLOW,
    )

    assert record.venue == "polymarket"
    assert record.market_id == "mkt-123"
    assert record.thesis_family is ThesisFamily.WALLET_FLOW
    assert record.market_probability == 0.41
    assert record.fair_probability == 0.52
    assert record.fill_probability == 0.45


def test_lifecycle_transition_contract_is_strict() -> None:
    assert is_valid_lifecycle_transition(LifecycleState.DISCOVERED, LifecycleState.ROUTED)
    assert is_valid_lifecycle_transition(LifecycleState.ROUTED, LifecycleState.RESTING)
    assert is_valid_lifecycle_transition(LifecycleState.RESTING, LifecycleState.FILLED)
    assert is_valid_lifecycle_transition(LifecycleState.FILLED, LifecycleState.RESOLVED)
    assert is_valid_lifecycle_transition(LifecycleState.RESOLVED, LifecycleState.ATTRIBUTED)
    assert not is_valid_lifecycle_transition(LifecycleState.DISCOVERED, LifecycleState.FILLED)
    assert not is_valid_lifecycle_transition(LifecycleState.EXPIRED, LifecycleState.RESOLVED)


def test_simulate_closed_trade_flywheel_outputs_attribution() -> None:
    candidate = normalize_candidate_record(
        {
            "market_id": "pm-btc-15m",
            "title": "BTC 15m up?",
            "fair_probability": 0.61,
            "market_probability": 0.47,
            "fee_adjusted_edge": 0.14,
            "fill_probability": 0.9,
            "toxicity": 0.1,
            "wallet_consensus_score": 0.8,
            "lmsr_gap": 0.15,
            "ofi": 0.4,
            "vpin": 0.1,
            "spread_bps": 6,
        },
        venue_hint="polymarket",
        thesis_hint=ThesisFamily.WALLET_FLOW,
    )
    payload = simulate_closed_trade_flywheel([candidate], seed=7)

    assert payload["candidates_considered"] == 1
    assert payload["route_decision_summary"]["accepted"] == 1
    assert payload["lifecycle_transitions_valid"] is True
    assert payload["summary"]["total_closed_trades"] >= 1
    assert payload["closed_trade_density_per_hour"] > 0


def test_dispatch_build_reports_writes_required_artifacts(tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    poly_path = reports_dir / "poly_fastlane_candidates_20260309T120000Z.json"
    kalshi_path = reports_dir / "kalshi_intraday_surface_20260309T120100Z.json"
    poly_path.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "market_id": "poly-1",
                        "title": "BTC 5m up?",
                        "fair_probability": 0.57,
                        "market_probability": 0.48,
                        "fee_adjusted_edge": 0.09,
                        "fill_probability": 0.75,
                        "toxicity": 0.2,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    kalshi_path.write_text(
        json.dumps(
            [
                {
                    "market_id": "kalshi-1",
                    "title": "BTC hourly above strike?",
                    "best_yes": 0.46,
                    "fair_probability": 0.5,
                    "fee_adjusted_edge": 0.04,
                    "fill_probability": 0.35,
                    "toxicity": 0.15,
                }
            ]
        ),
        encoding="utf-8",
    )

    contract_path, flywheel_path = build_reports(
        reports_dir=reports_dir,
        polymarket_input=None,
        kalshi_input=None,
        horizon_hours=24,
        seed=11,
    )

    assert contract_path.exists()
    assert flywheel_path.exists()
    contract_payload = json.loads(contract_path.read_text(encoding="utf-8"))
    flywheel_payload = json.loads(flywheel_path.read_text(encoding="utf-8"))
    assert contract_payload["candidate_counts"]["total"] == 2
    assert flywheel_payload["candidates_considered"] == 2
    assert "closed_trade_density_per_hour" in flywheel_payload
    assert flywheel_payload["input_diagnostics"]["parse_errors"] == []


def test_load_candidate_records_handles_missing_inputs(tmp_path: Path) -> None:
    records, diagnostics = load_candidate_records(reports_dir=tmp_path)
    assert records == []
    assert diagnostics["candidate_count"] == 0
    assert diagnostics["polymarket_source"] is None
    assert diagnostics["kalshi_source"] is None

