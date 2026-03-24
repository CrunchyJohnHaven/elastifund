"""Resolution-risk scoring for objective-rule tail trades."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


_SUBJECTIVE_TERMS = (
    "considered",
    "widely reported",
    "generally accepted",
    "best efforts",
    "spirit of the market",
    "clarification",
    "editorial discretion",
    "officially recognized",
)


@dataclass(frozen=True)
class ResolutionRiskProfile:
    venue: str
    objective_rules: bool
    has_named_source: bool
    flagged_terms: tuple[str, ...]
    estimated_hours_to_cash: float
    dispute_risk_score: float
    clarification_risk_score: float
    total_risk_score: float
    blockers: tuple[str, ...] = field(default_factory=tuple)


def find_subjective_terms(text: str) -> tuple[str, ...]:
    lowered = str(text or "").lower()
    return tuple(term for term in _SUBJECTIVE_TERMS if term in lowered)


def estimate_resolution_risk(
    *,
    venue: str,
    rules_text: str,
    settlement_source: str | None = None,
    objective_rules: bool | None = None,
) -> ResolutionRiskProfile:
    """Estimate venue-level rule and settlement risk for tail strategies."""
    normalized_venue = str(venue or "").strip().lower()
    flagged_terms = find_subjective_terms(rules_text)
    source_present = bool(str(settlement_source or "").strip())
    objective = bool(objective_rules) if objective_rules is not None else not flagged_terms

    if normalized_venue == "polymarket":
        base_hours = 2.0
        base_dispute = 0.12
        base_clarification = 0.08
    elif normalized_venue == "kalshi":
        base_hours = 3.0
        base_dispute = 0.04
        base_clarification = 0.03
    else:
        base_hours = 6.0
        base_dispute = 0.08
        base_clarification = 0.06

    dispute_risk = base_dispute + (0.10 if not objective else 0.0)
    clarification_risk = base_clarification + min(0.25, 0.05 * len(flagged_terms))
    if not source_present:
        clarification_risk += 0.12

    blockers: list[str] = []
    if not objective:
        blockers.append("subjective_rules")
    if not source_present:
        blockers.append("missing_settlement_source")

    total = min(1.0, dispute_risk + clarification_risk)
    estimated_hours = base_hours + (24.0 if normalized_venue == "polymarket" and blockers else 0.0)
    return ResolutionRiskProfile(
        venue=normalized_venue,
        objective_rules=objective,
        has_named_source=source_present,
        flagged_terms=flagged_terms,
        estimated_hours_to_cash=estimated_hours,
        dispute_risk_score=round(dispute_risk, 4),
        clarification_risk_score=round(clarification_risk, 4),
        total_risk_score=round(total, 4),
        blockers=tuple(blockers),
    )

