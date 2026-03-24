"""Tests for kill propagation system."""

import tempfile
from pathlib import Path

from src.experiment_registry import ExperimentEntry, ExperimentRegistry, ExperimentState
from src.kill_propagation import (
    CounterHypothesis,
    KillPropagator,
    generate_counter_hypotheses,
)
from src.negative_results import NegativeResultsLibrary


def _make_system(family_threshold: int = 3):
    """Create a complete test system with registry and negative results library."""
    tmpdir = tempfile.mkdtemp()
    nr_path = Path(tmpdir) / "negative.db"
    exp_path = Path(tmpdir) / "experiments.db"
    nr_lib = NegativeResultsLibrary(nr_path, family_kill_threshold=family_threshold)
    exp_reg = ExperimentRegistry(exp_path)
    propagator = KillPropagator(nr_lib, exp_reg)
    return propagator, nr_lib, exp_reg


class TestGenerateCounterHypotheses:
    def test_known_kill_rule(self):
        counters = generate_counter_hypotheses(
            kill_rule="negative_expectancy",
            kill_details="EV = -0.02",
            family="btc5",
        )
        assert len(counters) >= 2
        assert all(isinstance(c, CounterHypothesis) for c in counters)
        assert all(c.addresses_kill_rule == "negative_expectancy" for c in counters)
        # Family prefix applied
        assert all("btc5:" in c.name for c in counters)

    def test_unknown_kill_rule_gets_generic(self):
        counters = generate_counter_hypotheses(
            kill_rule="cosmic_ray_interference",
            kill_details="Bit flip in FPGA",
            family="",
        )
        assert len(counters) == 1
        assert "post-mortem" in counters[0].name.lower()

    def test_all_known_rules_produce_counters(self):
        known_rules = [
            "negative_expectancy",
            "poor_calibration",
            "regime_decay",
            "parameter_instability",
            "leakage",
            "insufficient_sample",
            "concentrated_edge",
            "execution_slippage",
            "sim_live_divergence",
        ]
        for rule in known_rules:
            counters = generate_counter_hypotheses(rule, "details", "family")
            assert len(counters) >= 1, f"No counters for {rule}"

    def test_no_family_prefix_when_empty(self):
        counters = generate_counter_hypotheses("leakage", "details", "")
        for c in counters:
            assert not c.name.startswith(":")


class TestKillPropagator:
    def test_basic_kill_propagation(self):
        prop, nr_lib, exp_reg = _make_system()

        result = prop.propagate_kill(
            experiment_id="exp_001",
            hypothesis_name="BTC momentum v1",
            hypothesis_id="hyp_001",
            family="btc5",
            kill_rule="negative_expectancy",
            kill_details="EV = -0.02",
            what_failed="Momentum signal",
            why_it_failed="Costs exceed edge",
            what_was_learned="Need maker-only",
        )

        assert result.killed_experiment_id == "exp_001"
        assert result.kill_rule == "negative_expectancy"
        assert result.family_kill_count == 1
        assert result.family_vetoed is False
        assert len(result.counter_hypotheses) >= 1

        # Verify recorded in negative results
        nr = nr_lib.get(result.negative_result_id)
        assert nr is not None
        assert nr.kill_rule == "negative_expectancy"

    def test_family_veto_on_threshold(self):
        prop, nr_lib, exp_reg = _make_system(family_threshold=2)

        # Register experiments in the family
        exp_reg.register(ExperimentEntry(
            experiment_id="exp_001", hypothesis_id="hyp_001", family="btc5",
        ))
        exp_reg.register(ExperimentEntry(
            experiment_id="exp_002", hypothesis_id="hyp_002", family="btc5",
        ))
        exp_reg.register(ExperimentEntry(
            experiment_id="exp_003", hypothesis_id="hyp_003", family="btc5",
        ))

        # Kill #1
        prop.propagate_kill(
            experiment_id="exp_001", hypothesis_name="v1", hypothesis_id="hyp_001",
            family="btc5", kill_rule="regime_decay", kill_details="Decaying",
        )
        # Retire exp_001 in registry
        exp_reg.retire("exp_001", reason="killed")

        # Kill #2 -- should trigger family veto
        result = prop.propagate_kill(
            experiment_id="exp_002", hypothesis_name="v2", hypothesis_id="hyp_002",
            family="btc5", kill_rule="leakage", kill_details="Data leak",
        )

        assert result.family_vetoed is True
        assert result.family_kill_count == 2
        # exp_003 should have been auto-retired
        assert "exp_003" in result.deprioritized_experiments

        exp3 = exp_reg.get("exp_003")
        assert exp3.state == ExperimentState.RETIRED

    def test_no_deprioritize_without_registry(self):
        tmpdir = tempfile.mkdtemp()
        nr_lib = NegativeResultsLibrary(Path(tmpdir) / "nr.db", family_kill_threshold=1)
        prop = KillPropagator(nr_lib, experiment_registry=None)

        result = prop.propagate_kill(
            experiment_id="exp_001", hypothesis_name="test", hypothesis_id="hyp_001",
            family="btc5", kill_rule="leakage", kill_details="details",
        )
        # Should not crash without registry
        assert result.deprioritized_experiments == []

    def test_research_context_generation(self):
        prop, nr_lib, exp_reg = _make_system(family_threshold=2)

        # Create enough kills to veto
        prop.propagate_kill(
            experiment_id="exp_001", hypothesis_name="v1", hypothesis_id="hyp_001",
            family="btc5", kill_rule="regime_decay", kill_details="Decaying",
            what_was_learned="Regime-dependent",
        )
        prop.propagate_kill(
            experiment_id="exp_002", hypothesis_name="v2", hypothesis_id="hyp_002",
            family="btc5", kill_rule="leakage", kill_details="Leak",
            what_was_learned="Check data carefully",
        )

        ctx = prop.research_context()
        assert "VETOED STRATEGY FAMILIES" in ctx
        assert "btc5" in ctx
        assert "COMMON KILL RULES" in ctx

    def test_research_context_empty(self):
        prop, _, _ = _make_system()
        ctx = prop.research_context()
        assert ctx == ""

    def test_metrics_at_kill_persisted(self):
        prop, nr_lib, _ = _make_system()
        metrics = {"sharpe": 0.3, "win_rate": 0.48, "max_dd": 0.15}
        result = prop.propagate_kill(
            experiment_id="exp_001", hypothesis_name="test", hypothesis_id="hyp_001",
            family="btc5", kill_rule="negative_expectancy", kill_details="bad",
            metrics_at_kill=metrics,
        )
        nr = nr_lib.get(result.negative_result_id)
        assert nr.metrics_at_kill["sharpe"] == 0.3

    def test_live_experiments_not_deprioritized(self):
        """Live experiments should not be auto-retired by family veto."""
        prop, nr_lib, exp_reg = _make_system(family_threshold=2)

        # Register one experiment that's already live
        live_exp = ExperimentEntry(
            experiment_id="exp_live", hypothesis_id="hyp_live", family="btc5",
        )
        exp_reg.register(live_exp)
        # Force to live state through proper transitions
        for target in [
            ExperimentState.SCOPED, ExperimentState.IMPLEMENTED,
            ExperimentState.BACKTESTED, ExperimentState.VALIDATED,
            ExperimentState.SHADOW, ExperimentState.PAPER,
            ExperimentState.MICRO_LIVE, ExperimentState.LIVE,
        ]:
            exp_reg.transition("exp_live", target)

        # Register an idea-stage experiment
        exp_reg.register(ExperimentEntry(
            experiment_id="exp_idea", hypothesis_id="hyp_idea", family="btc5",
        ))

        # Trigger veto
        prop.propagate_kill(
            experiment_id="exp_k1", hypothesis_name="v1", hypothesis_id="hyp_k1",
            family="btc5", kill_rule="leakage", kill_details="d1",
        )
        result = prop.propagate_kill(
            experiment_id="exp_k2", hypothesis_name="v2", hypothesis_id="hyp_k2",
            family="btc5", kill_rule="leakage", kill_details="d2",
        )

        # Live experiment should NOT be deprioritized
        assert "exp_live" not in result.deprioritized_experiments
        # Idea experiment should be deprioritized
        assert "exp_idea" in result.deprioritized_experiments
