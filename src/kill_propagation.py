"""Kill propagation: when a strategy dies, the consequences ripple.

When a strategy is killed:
1. Record the kill reason in the negative-results library
2. Generate counter-hypotheses that address the kill reason
3. Auto-deprioritize all variants in the same family
4. Update the research prompt context to exclude dead ends
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import time

from .hypothesis_card import HypothesisCard, ProofStatus
from .negative_results import NegativeResult, NegativeResultsLibrary
from .experiment_registry import ExperimentRegistry, ExperimentState


@dataclass
class CounterHypothesis:
    """A hypothesis generated to address a specific kill reason."""
    name: str
    addresses_kill_rule: str
    addresses_failure: str
    proposed_mechanism: str
    priority: float = 0.5
    generated_at: float = field(default_factory=time.time)


@dataclass
class KillPropagationResult:
    """Result of propagating a kill through the system."""
    killed_experiment_id: str
    killed_hypothesis_name: str
    family: str
    kill_rule: str
    negative_result_id: str
    family_kill_count: int
    family_vetoed: bool
    deprioritized_experiments: list[str] = field(default_factory=list)
    counter_hypotheses: list[CounterHypothesis] = field(default_factory=list)
    dead_end_context: str = ""


# ---------------------------------------------------------------------------
# Counter-hypothesis generation templates
# ---------------------------------------------------------------------------

KILL_RULE_COUNTER_TEMPLATES: dict[str, list[dict[str, str]]] = {
    "negative_expectancy": [
        {
            "name": "Cost reduction variant",
            "mechanism": "Same signal but with maker-only execution to eliminate taker fees",
        },
        {
            "name": "Higher threshold variant",
            "mechanism": "Same signal but only trade when edge estimate exceeds 2x cost",
        },
    ],
    "poor_calibration": [
        {
            "name": "Recalibrated variant",
            "mechanism": "Apply Platt scaling or isotonic regression to probability estimates",
        },
        {
            "name": "Ensemble calibration",
            "mechanism": "Blend multiple probability estimators to reduce individual calibration error",
        },
    ],
    "regime_decay": [
        {
            "name": "Regime-filtered variant",
            "mechanism": "Only trade during detected favorable regimes, sit out unfavorable ones",
        },
        {
            "name": "Adaptive parameter variant",
            "mechanism": "Use rolling parameter estimation to adapt to regime changes",
        },
    ],
    "parameter_instability": [
        {
            "name": "Simplified variant",
            "mechanism": "Reduce parameter count to minimum viable; fewer params means more stable",
        },
        {
            "name": "Ensemble parameter variant",
            "mechanism": "Average across parameter grid rather than optimizing to single point",
        },
    ],
    "leakage": [
        {
            "name": "Strict temporal variant",
            "mechanism": "Enforce point-in-time data with no future information leakage",
        },
    ],
    "insufficient_sample": [
        {
            "name": "Extended universe variant",
            "mechanism": "Expand to additional markets/instruments to increase sample size",
        },
    ],
    "concentrated_edge": [
        {
            "name": "Diversified variant",
            "mechanism": "Apply across broader universe rather than single instrument",
        },
    ],
    "execution_slippage": [
        {
            "name": "Passive execution variant",
            "mechanism": "Switch to limit orders with patience; accept lower fill rate for better prices",
        },
    ],
    "sim_live_divergence": [
        {
            "name": "Realistic simulator variant",
            "mechanism": "Rebuild simulator with actual fill data, latency measurements, and queue position modeling",
        },
    ],
}


def generate_counter_hypotheses(
    kill_rule: str,
    kill_details: str,
    family: str,
) -> list[CounterHypothesis]:
    """Generate counter-hypotheses based on the kill reason.

    Uses templates for known kill rules and generates a generic counter
    for unknown rules.
    """
    templates = KILL_RULE_COUNTER_TEMPLATES.get(kill_rule, [])

    counters: list[CounterHypothesis] = []
    for template in templates:
        counters.append(
            CounterHypothesis(
                name=f"{family}:{template['name']}" if family else template["name"],
                addresses_kill_rule=kill_rule,
                addresses_failure=kill_details,
                proposed_mechanism=template["mechanism"],
            )
        )

    # Always generate a generic "investigate further" counter
    if not counters:
        counters.append(
            CounterHypothesis(
                name=f"{family}:post-mortem investigation" if family else "post-mortem investigation",
                addresses_kill_rule=kill_rule,
                addresses_failure=kill_details,
                proposed_mechanism=f"Investigate root cause of {kill_rule}: {kill_details}",
                priority=0.3,
            )
        )

    return counters


class KillPropagator:
    """Orchestrates kill propagation across the system.

    When a strategy is killed, this class:
    1. Records the kill in the negative-results library
    2. Generates counter-hypotheses
    3. Deprioritizes family variants in the experiment registry
    4. Builds updated research context excluding dead ends
    """

    def __init__(
        self,
        negative_results: NegativeResultsLibrary,
        experiment_registry: ExperimentRegistry | None = None,
    ):
        self.negative_results = negative_results
        self.experiment_registry = experiment_registry

    def propagate_kill(
        self,
        experiment_id: str,
        hypothesis_name: str,
        hypothesis_id: str,
        family: str,
        kill_rule: str,
        kill_details: str,
        what_failed: str = "",
        why_it_failed: str = "",
        what_was_learned: str = "",
        metrics_at_kill: dict[str, Any] | None = None,
    ) -> KillPropagationResult:
        """Execute the full kill propagation chain.

        Returns a KillPropagationResult summarizing all actions taken.
        """
        # 1. Record in negative-results library
        result_id = f"nr_{experiment_id}_{int(time.time())}"
        counter_hyps = generate_counter_hypotheses(kill_rule, kill_details, family)

        negative_result = NegativeResult(
            result_id=result_id,
            hypothesis_id=hypothesis_id,
            hypothesis_name=hypothesis_name,
            family=family,
            kill_rule=kill_rule,
            kill_details=kill_details,
            what_failed=what_failed or hypothesis_name,
            why_it_failed=why_it_failed or kill_details,
            what_was_learned=what_was_learned,
            counter_hypotheses=[c.name for c in counter_hyps],
            metrics_at_kill=metrics_at_kill or {},
        )
        self.negative_results.record(negative_result)

        # 2. Get family kill count and veto status
        family_kills = self.negative_results.family_kill_count(family) if family else 0
        family_vetoed = self.negative_results.is_family_vetoed(family) if family else False

        # 3. Deprioritize family variants in experiment registry
        deprioritized: list[str] = []
        if family_vetoed and self.experiment_registry and family:
            family_experiments = self.experiment_registry.list_by_family(family)
            for exp in family_experiments:
                # Retire any experiment that hasn't reached live yet
                if exp.state not in (ExperimentState.LIVE, ExperimentState.RETIRED):
                    if exp.experiment_id != experiment_id:
                        try:
                            self.experiment_registry.retire(
                                exp.experiment_id,
                                reason=f"Auto-veto: family '{family}' has {family_kills} kills (threshold: {self.negative_results.family_kill_threshold})",
                                reviewer="kill_propagator",
                            )
                            deprioritized.append(exp.experiment_id)
                        except Exception:
                            pass  # already retired or other issue

        # 4. Build dead-end context for research prompts
        dead_end_context = self.negative_results.dead_end_context()

        return KillPropagationResult(
            killed_experiment_id=experiment_id,
            killed_hypothesis_name=hypothesis_name,
            family=family,
            kill_rule=kill_rule,
            negative_result_id=result_id,
            family_kill_count=family_kills,
            family_vetoed=family_vetoed,
            deprioritized_experiments=deprioritized,
            counter_hypotheses=counter_hyps,
            dead_end_context=dead_end_context,
        )

    def research_context(self) -> str:
        """Generate the full research context string for prompt injection.

        Includes vetoed families, common kill rules, and lessons learned.
        """
        parts: list[str] = []

        # Dead-end context
        dead_ends = self.negative_results.dead_end_context()
        if dead_ends:
            parts.append(dead_ends)

        # Kill rule summary
        rule_summary = self.negative_results.kill_rule_summary()
        if rule_summary:
            parts.append("\nCOMMON KILL RULES (by frequency):")
            for rule, count in rule_summary.items():
                parts.append(f"  - {rule}: {count} kills")

        return "\n".join(parts) if parts else ""
