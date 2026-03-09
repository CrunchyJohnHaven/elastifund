from __future__ import annotations

import pytest

from nontrading.models import Opportunity
from nontrading.opportunity_registry import (
    CRITERION_WEIGHTS,
    OpportunityRegistry,
    OpportunityScoreInput,
)


def make_score_input(**overrides: float) -> OpportunityScoreInput:
    values = {
        "time_to_first_dollar": 0.9,
        "gross_margin": 0.8,
        "automation_fraction": 0.7,
        "data_exhaust": 0.6,
        "compliance_simplicity": 0.95,
        "capital_required": 0.85,
        "sales_cycle_length": 0.75,
    }
    values.update(overrides)
    return OpportunityScoreInput(**values)


def test_weights_sum_to_one() -> None:
    assert round(sum(CRITERION_WEIGHTS.values()), 5) == 1.0


def test_scores_weighted_phase0_rubric() -> None:
    registry = OpportunityRegistry()

    assessment = registry.score(make_score_input())

    assert assessment.total_score == 79.0
    assert assessment.weighted_breakdown["time_to_first_dollar"] == 22.5
    assert assessment.decision == "advance"


def test_threshold_can_hold_opportunity_in_research() -> None:
    registry = OpportunityRegistry(threshold=80.0)

    assessment = registry.score(make_score_input())

    assert assessment.decision == "research_only"
    assert assessment.threshold == 80.0


def test_invalid_criterion_value_raises() -> None:
    registry = OpportunityRegistry()

    with pytest.raises(ValueError, match="gross_margin"):
        registry.score(make_score_input(gross_margin=1.1))


def test_rank_orders_highest_score_first() -> None:
    registry = OpportunityRegistry()

    ranked = registry.rank(
        [
            ("slower", make_score_input(time_to_first_dollar=0.4)),
            ("best", make_score_input()),
            ("middling", make_score_input(automation_fraction=0.5, sales_cycle_length=0.5)),
        ]
    )

    assert [name for name, _ in ranked] == ["best", "middling", "slower"]


def test_apply_writes_score_and_decision_metadata() -> None:
    registry = OpportunityRegistry()
    opportunity = Opportunity(account_id=1, name="Construction outreach")

    scored = registry.apply(opportunity, make_score_input())

    assert scored.score == 79.0
    assert scored.score_breakdown["gross_margin"] == 16.0
    assert scored.metadata["registry_decision"] == "advance"
