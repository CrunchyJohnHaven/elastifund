"""Tests for bot/enhanced_pipeline.py

Covers all major behaviours:
- Pipeline initialization with all features enabled (via mocks)
- Pipeline initialization with all features disabled
- Scan with minimal inputs
- Early exit on conformal abstain
- Early exit on regime transition
- Early exit on toxic flow
- Full pipeline flow with all phases passing
- post_trade_update does not crash with or without components
- health_check reports correct component status
- create_pipeline factory with each mode
- Pipeline latency tracking
- Feature flag toggling post-init
- Graceful degradation when a component import fails

All external components are replaced with MagicMock stubs so the test
suite runs without the corresponding modules being present.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers: build a minimal stub for a not-yet-existing component module
# ---------------------------------------------------------------------------

def _make_stub_module(name: str) -> types.ModuleType:
    """Return a module object with a single class of the given name."""
    mod = types.ModuleType(name)
    cls = type(name, (), {})
    setattr(mod, name, cls)
    return mod


# ---------------------------------------------------------------------------
# Re-import guard: ensure the module is freshly imported in each test that
# patches sys.modules, otherwise cached imports bleed across tests.
# ---------------------------------------------------------------------------

def _fresh_import():
    """Import enhanced_pipeline from scratch, discarding any cached version."""
    for key in list(sys.modules.keys()):
        if "enhanced_pipeline" in key:
            del sys.modules[key]
    import importlib
    import bot.enhanced_pipeline as ep
    importlib.reload(ep)
    return ep


# ---------------------------------------------------------------------------
# Shared mock component factory
# ---------------------------------------------------------------------------

def _mock_reflexion(retrieve_return: str = "past context") -> MagicMock:
    m = MagicMock()
    m.retrieve.return_value = retrieve_return
    return m


def _mock_conformal(calibrate_return: float = 0.70,
                    interval_return: tuple = (0.60, 0.80),
                    decision: str = "BUY_YES") -> MagicMock:
    m = MagicMock()
    m.calibrate.return_value = calibrate_return
    m.predict_interval.return_value = interval_return
    return m


def _mock_regime(state: str = "stable") -> MagicMock:
    m = MagicMock()
    m.get_state.return_value = state
    return m


def _mock_hawkes(is_cascade: bool = False) -> MagicMock:
    m = MagicMock()
    m.is_cascade.return_value = is_cascade
    return m


def _mock_ensemble_tox(score: float = 0.10) -> MagicMock:
    m = MagicMock()
    m.score.return_value = score
    return m


def _mock_causal(signals: list | None = None) -> MagicMock:
    m = MagicMock()
    m.get_signals.return_value = signals or []
    return m


def _mock_rag(context: str = "dispatch context") -> MagicMock:
    m = MagicMock()
    m.query.return_value = context
    return m


def _mock_constraints(result: str = "allow",
                      violations: list | None = None,
                      position_size_usd: float = 5.0) -> MagicMock:
    m = MagicMock()
    m.check.return_value = {
        "result": result,
        "violations": violations or [],
        "position_size_usd": position_size_usd,
    }
    return m


# ---------------------------------------------------------------------------
# Fixture: pipeline with all real components replaced by mocks
# ---------------------------------------------------------------------------

@pytest.fixture()
def pipeline_all_mocked():
    """Return an EnhancedPipeline whose internal component slots are mocked."""
    from bot.enhanced_pipeline import EnhancedPipeline, PipelineConfig

    cfg = PipelineConfig(
        enable_reflexion=True,
        enable_conformal=True,
        enable_regime_detection=True,
        enable_hawkes=True,
        enable_ensemble_toxicity=True,
        enable_causal_leadlag=True,
        enable_research_rag=True,
        enable_constraints=True,
    )
    p = EnhancedPipeline(config=cfg)

    # Wire in mocks directly (bypass real imports)
    p._reflexion = _mock_reflexion()
    p._conformal = _mock_conformal()
    p._regime = _mock_regime("stable")
    p._hawkes = _mock_hawkes(False)
    p._ensemble_tox = _mock_ensemble_tox(0.10)
    p._causal = _mock_causal([{"confirming": True}])
    p._rag = _mock_rag()
    p._constraints = _mock_constraints("allow")
    p._initialized = True

    return p


# ---------------------------------------------------------------------------
# 1. Initialization with all features enabled (mocking components)
# ---------------------------------------------------------------------------

class TestInitializationAllEnabled:
    def test_initialize_returns_dict_for_all_components(self):
        from bot.enhanced_pipeline import EnhancedPipeline, PipelineConfig

        cfg = PipelineConfig()
        pipeline = EnhancedPipeline(config=cfg)

        # Patch all optional class-level imports to MagicMock
        import bot.enhanced_pipeline as ep
        original = {}
        stubs = [
            "ReflexionMemory", "ConformalCalibrator", "RegimeDetector",
            "HawkesOrderFlow", "EnsembleToxicity", "CausalLeadLag",
            "ResearchRAG", "ConstraintEnforcer",
        ]
        for name in stubs:
            original[name] = getattr(ep, name, None)
            setattr(ep, name, MagicMock(return_value=MagicMock()))

        try:
            result = pipeline.initialize()
        finally:
            for name, val in original.items():
                setattr(ep, name, val)

        assert isinstance(result, dict)
        for key in ("reflexion", "conformal", "regime_detection", "hawkes",
                    "ensemble_toxicity", "causal_leadlag", "research_rag", "constraints"):
            assert key in result

    def test_initialize_sets_initialized_flag(self):
        from bot.enhanced_pipeline import EnhancedPipeline, PipelineConfig

        p = EnhancedPipeline(config=PipelineConfig(
            enable_reflexion=False, enable_conformal=False,
            enable_regime_detection=False, enable_hawkes=False,
            enable_ensemble_toxicity=False, enable_causal_leadlag=False,
            enable_research_rag=False, enable_constraints=False,
        ))
        assert not p._initialized
        p.initialize()
        assert p._initialized


# ---------------------------------------------------------------------------
# 2. Initialization with all features disabled
# ---------------------------------------------------------------------------

class TestInitializationAllDisabled:
    def test_all_disabled_returns_false_for_each(self):
        from bot.enhanced_pipeline import EnhancedPipeline, PipelineConfig

        cfg = PipelineConfig(
            enable_reflexion=False,
            enable_conformal=False,
            enable_regime_detection=False,
            enable_hawkes=False,
            enable_ensemble_toxicity=False,
            enable_causal_leadlag=False,
            enable_research_rag=False,
            enable_constraints=False,
            enable_symbolic_alpha=False,
            enable_synergistic_signals=False,
            enable_parameter_evolution=False,
        )
        p = EnhancedPipeline(config=cfg)
        result = p.initialize()

        for v in result.values():
            assert v is False

    def test_all_disabled_pipeline_still_scans(self):
        from bot.enhanced_pipeline import EnhancedPipeline, PipelineConfig

        cfg = PipelineConfig(
            enable_reflexion=False, enable_conformal=False,
            enable_regime_detection=False, enable_hawkes=False,
            enable_ensemble_toxicity=False, enable_causal_leadlag=False,
            enable_research_rag=False, enable_constraints=False,
        )
        p = EnhancedPipeline(config=cfg)
        p.initialize()

        sig = p.scan(
            market_id="test-market",
            market_question="Will X happen?",
            raw_probability=0.80,
            market_price=0.50,
        )
        # With conformal disabled we use static Platt. Market price 0.50 is
        # well outside the interval around a calibrated ~0.67+ probability
        # → should produce BUY_YES or SKIP (not crash)
        assert sig.final_action in ("TRADE", "SKIP", "ESCALATE")


# ---------------------------------------------------------------------------
# 3. Scan with minimal inputs
# ---------------------------------------------------------------------------

class TestScanMinimalInputs:
    def test_scan_returns_pipeline_signal(self):
        from bot.enhanced_pipeline import EnhancedPipeline, PipelineConfig, PipelineSignal

        cfg = PipelineConfig(
            enable_reflexion=False, enable_conformal=False,
            enable_regime_detection=False, enable_hawkes=False,
            enable_ensemble_toxicity=False, enable_causal_leadlag=False,
            enable_research_rag=False, enable_constraints=False,
        )
        p = EnhancedPipeline(config=cfg)
        sig = p.scan("m1", "Will it rain?", 0.75, 0.40)

        assert isinstance(sig, PipelineSignal)
        assert sig.market_id == "m1"
        assert sig.market_question == "Will it rain?"
        assert sig.raw_probability == 0.75
        assert sig.market_price == 0.40

    def test_scan_latency_is_positive(self):
        from bot.enhanced_pipeline import EnhancedPipeline, PipelineConfig

        cfg = PipelineConfig(
            enable_reflexion=False, enable_conformal=False,
            enable_regime_detection=False, enable_hawkes=False,
            enable_ensemble_toxicity=False, enable_causal_leadlag=False,
            enable_research_rag=False, enable_constraints=False,
        )
        p = EnhancedPipeline(config=cfg)
        sig = p.scan("m2", "Question?", 0.70, 0.40)
        assert sig.pipeline_latency_ms > 0.0

    def test_scan_components_used_is_list(self):
        from bot.enhanced_pipeline import EnhancedPipeline, PipelineConfig

        cfg = PipelineConfig(
            enable_reflexion=False, enable_conformal=False,
            enable_regime_detection=False, enable_hawkes=False,
            enable_ensemble_toxicity=False, enable_causal_leadlag=False,
            enable_research_rag=False, enable_constraints=False,
        )
        p = EnhancedPipeline(config=cfg)
        sig = p.scan("m3", "Q?", 0.70, 0.40)
        assert isinstance(sig.components_used, list)


# ---------------------------------------------------------------------------
# 4. Early exit on conformal abstain
# ---------------------------------------------------------------------------

class TestEarlyExitConformalAbstain:
    def test_skip_when_market_price_inside_interval(self, pipeline_all_mocked):
        """Market price 0.70 inside interval (0.60, 0.80) → ABSTAIN."""
        p = pipeline_all_mocked
        # conformal mock returns calibrated=0.70, interval=(0.60, 0.80)
        p._conformal.calibrate.return_value = 0.70
        p._conformal.predict_interval.return_value = (0.60, 0.80)

        sig = p.scan("m-abs", "Q?", 0.70, 0.70)  # market_price inside interval

        assert sig.final_action == "SKIP"
        assert sig.skip_reason == "conformal_abstain"
        assert sig.conformal_decision == "ABSTAIN"

    def test_skip_when_edge_below_min(self, pipeline_all_mocked):
        """Calibrated prob=0.55, market price=0.52 → edge=0.03 < min_edge=0.05 → ABSTAIN."""
        p = pipeline_all_mocked
        p._conformal.calibrate.return_value = 0.55
        p._conformal.predict_interval.return_value = (0.40, 0.60)
        # market_price=0.54 is outside interval but edge < min_edge
        sig = p.scan("m-edge", "Q?", 0.55, 0.52)

        assert sig.final_action == "SKIP"
        assert sig.skip_reason == "conformal_abstain"

    def test_abstain_does_not_call_regime_detector(self, pipeline_all_mocked):
        """After conformal abstain, regime detector must not be queried."""
        p = pipeline_all_mocked
        p._conformal.calibrate.return_value = 0.50
        p._conformal.predict_interval.return_value = (0.40, 0.60)

        p.scan("m-no-regime", "Q?", 0.50, 0.50)

        p._regime.get_state.assert_not_called()


# ---------------------------------------------------------------------------
# 5. Early exit on regime transition
# ---------------------------------------------------------------------------

class TestEarlyExitRegimeTransition:
    def test_skip_when_regime_is_transition(self, pipeline_all_mocked):
        p = pipeline_all_mocked
        p._conformal.calibrate.return_value = 0.80
        p._conformal.predict_interval.return_value = (0.70, 0.90)
        p._regime.get_state.return_value = "transition"

        sig = p.scan("m-reg", "Q?", 0.80, 0.50)

        assert sig.final_action == "SKIP"
        assert sig.skip_reason == "regime_transition"
        assert sig.regime_state == "transition"
        assert not sig.regime_safe

    def test_regime_transition_does_not_call_toxicity(self, pipeline_all_mocked):
        p = pipeline_all_mocked
        p._conformal.calibrate.return_value = 0.80
        p._conformal.predict_interval.return_value = (0.70, 0.90)
        p._regime.get_state.return_value = "warmup"

        p.scan("m-warmup", "Q?", 0.80, 0.50)

        p._ensemble_tox.score.assert_not_called()


# ---------------------------------------------------------------------------
# 6. Early exit on toxic flow
# ---------------------------------------------------------------------------

class TestEarlyExitToxicFlow:
    def test_skip_on_high_ensemble_toxicity(self, pipeline_all_mocked):
        p = pipeline_all_mocked
        p._conformal.calibrate.return_value = 0.80
        p._conformal.predict_interval.return_value = (0.70, 0.90)
        p._regime.get_state.return_value = "stable"
        p._ensemble_tox.score.return_value = 0.90  # > threshold 0.65

        sig = p.scan("m-tox", "Q?", 0.80, 0.50)

        assert sig.final_action == "SKIP"
        assert sig.skip_reason == "toxic_flow"
        assert sig.is_toxic is True

    def test_skip_on_hawkes_cascade(self, pipeline_all_mocked):
        p = pipeline_all_mocked
        p._conformal.calibrate.return_value = 0.80
        p._conformal.predict_interval.return_value = (0.70, 0.90)
        p._regime.get_state.return_value = "stable"
        p._ensemble_tox.score.return_value = 0.10  # not toxic
        p._hawkes.is_cascade.return_value = True

        sig = p.scan("m-hawk", "Q?", 0.80, 0.50)

        assert sig.final_action == "SKIP"
        assert sig.skip_reason == "hawkes_cascade"
        assert sig.hawkes_cascade is True

    def test_toxic_flow_does_not_call_rag(self, pipeline_all_mocked):
        p = pipeline_all_mocked
        p._conformal.calibrate.return_value = 0.80
        p._conformal.predict_interval.return_value = (0.70, 0.90)
        p._regime.get_state.return_value = "stable"
        p._ensemble_tox.score.return_value = 0.95

        p.scan("m-no-rag", "Q?", 0.80, 0.50)

        p._rag.query.assert_not_called()


# ---------------------------------------------------------------------------
# 7. Full pipeline flow with all phases passing
# ---------------------------------------------------------------------------

class TestFullPipelineFlow:
    def test_trade_action_when_all_clear(self, pipeline_all_mocked):
        p = pipeline_all_mocked
        p._conformal.calibrate.return_value = 0.80
        p._conformal.predict_interval.return_value = (0.70, 0.90)
        p._regime.get_state.return_value = "stable"
        p._ensemble_tox.score.return_value = 0.10
        p._hawkes.is_cascade.return_value = False
        p._reflexion.retrieve.return_value = "good memory"
        p._rag.query.return_value = "dispatch info"
        p._constraints.check.return_value = {"result": "allow", "violations": [], "position_size_usd": 8.0}
        p._causal.get_signals.return_value = [{"confirming": True, "market": "btc"}]

        sig = p.scan(
            market_id="m-full",
            market_question="Will BTC rise?",
            raw_probability=0.80,
            market_price=0.50,
            recent_trades=[{"side": "buy", "size": 10}],
            multi_market_prices={"eth": [0.5, 0.6]},
            bankroll=500.0,
        )

        assert sig.final_action == "TRADE"
        assert sig.skip_reason == ""
        assert sig.conformal_decision in ("BUY_YES", "BUY_NO")
        assert sig.regime_state == "stable"
        assert sig.regime_safe is True
        assert sig.is_toxic is False
        assert sig.hawkes_cascade is False
        assert sig.reflexion_context == "good memory"
        assert sig.rag_context == "dispatch info"
        assert len(sig.causal_signals) == 1
        assert sig.constraint_result == "allow"
        assert sig.position_size_usd == 8.0
        assert 0.0 <= sig.confidence <= 1.0

    def test_all_components_appear_in_components_used(self, pipeline_all_mocked):
        p = pipeline_all_mocked
        p._conformal.calibrate.return_value = 0.80
        p._conformal.predict_interval.return_value = (0.70, 0.90)
        p._regime.get_state.return_value = "stable"
        p._ensemble_tox.score.return_value = 0.10
        p._hawkes.is_cascade.return_value = False
        p._constraints.check.return_value = {"result": "allow", "violations": [], "position_size_usd": 5.0}
        p._causal.get_signals.return_value = []

        sig = p.scan("m-all-comps", "Q?", 0.80, 0.50,
                     multi_market_prices={"x": [0.5, 0.6]})

        for comp in ("conformal", "regime_detection", "ensemble_toxicity",
                     "hawkes", "reflexion", "research_rag", "causal_leadlag", "constraints"):
            assert comp in sig.components_used, f"{comp} missing from components_used"

    def test_constraint_modify_adjusts_position_size(self, pipeline_all_mocked):
        p = pipeline_all_mocked
        p._conformal.calibrate.return_value = 0.80
        p._conformal.predict_interval.return_value = (0.70, 0.90)
        p._regime.get_state.return_value = "stable"
        p._ensemble_tox.score.return_value = 0.10
        p._hawkes.is_cascade.return_value = False
        p._constraints.check.return_value = {
            "result": "modify",
            "violations": ["size_reduced"],
            "position_size_usd": 2.0,
        }

        sig = p.scan("m-modify", "Q?", 0.80, 0.50)

        assert sig.final_action == "TRADE"
        assert sig.constraint_result == "modify"
        assert sig.position_size_usd == 2.0

    def test_constraint_block_skips_trade(self, pipeline_all_mocked):
        p = pipeline_all_mocked
        p._conformal.calibrate.return_value = 0.80
        p._conformal.predict_interval.return_value = (0.70, 0.90)
        p._regime.get_state.return_value = "stable"
        p._ensemble_tox.score.return_value = 0.10
        p._hawkes.is_cascade.return_value = False
        p._constraints.check.return_value = {
            "result": "block",
            "violations": ["daily_loss_limit"],
            "position_size_usd": 0.0,
        }

        sig = p.scan("m-blocked", "Q?", 0.80, 0.50)

        assert sig.final_action == "SKIP"
        assert sig.skip_reason == "constraint_block"

    def test_constraint_escalate_returns_escalate_action(self, pipeline_all_mocked):
        p = pipeline_all_mocked
        p._conformal.calibrate.return_value = 0.80
        p._conformal.predict_interval.return_value = (0.70, 0.90)
        p._regime.get_state.return_value = "stable"
        p._ensemble_tox.score.return_value = 0.10
        p._hawkes.is_cascade.return_value = False
        p._constraints.check.return_value = {
            "result": "escalate",
            "violations": ["unusual_market_size"],
            "position_size_usd": 10.0,
        }

        sig = p.scan("m-escalate", "Q?", 0.80, 0.50)

        assert sig.final_action == "ESCALATE"


# ---------------------------------------------------------------------------
# 8. post_trade_update — must not crash
# ---------------------------------------------------------------------------

class TestPostTradeUpdate:
    def test_does_not_crash_with_all_components(self, pipeline_all_mocked):
        p = pipeline_all_mocked
        # Should complete without raising
        p.post_trade_update(
            market_id="m1",
            market_question="Q?",
            predicted_prob=0.70,
            market_price=0.50,
            outcome=True,
            pnl=3.50,
            tags=["btc5", "down"],
        )

    def test_does_not_crash_with_no_components(self):
        from bot.enhanced_pipeline import EnhancedPipeline, PipelineConfig

        cfg = PipelineConfig(
            enable_reflexion=False, enable_conformal=False,
            enable_regime_detection=False, enable_hawkes=False,
            enable_ensemble_toxicity=False, enable_causal_leadlag=False,
            enable_research_rag=False, enable_constraints=False,
        )
        p = EnhancedPipeline(config=cfg)
        p.initialize()
        # Must not raise
        p.post_trade_update("m2", "Q2?", 0.6, 0.5, False, -2.0)

    def test_reflexion_store_called(self, pipeline_all_mocked):
        p = pipeline_all_mocked
        p.post_trade_update("m3", "Q3?", 0.75, 0.60, True, 5.0, tags=["tag1"])
        p._reflexion.store.assert_called_once()

    def test_conformal_update_called(self, pipeline_all_mocked):
        p = pipeline_all_mocked
        p.post_trade_update("m4", "Q4?", 0.80, 0.55, True, 4.0)
        p._conformal.update.assert_called_once()

    def test_regime_observe_called(self, pipeline_all_mocked):
        p = pipeline_all_mocked
        p.post_trade_update("m5", "Q5?", 0.70, 0.50, False, -1.5)
        p._regime.observe.assert_called_once_with(-1.5)

    def test_ensemble_tox_reward_called(self, pipeline_all_mocked):
        p = pipeline_all_mocked
        p.post_trade_update("m6", "Q6?", 0.65, 0.45, True, 2.0)
        p._ensemble_tox.reward.assert_called_once_with(2.0)

    def test_crashing_component_does_not_propagate(self, pipeline_all_mocked):
        p = pipeline_all_mocked
        p._reflexion.store.side_effect = RuntimeError("db crashed")
        # Must NOT raise
        p.post_trade_update("m7", "Q7?", 0.70, 0.50, True, 1.0)


# ---------------------------------------------------------------------------
# 9. health_check
# ---------------------------------------------------------------------------

class TestHealthCheck:
    def test_disabled_components_report_disabled(self):
        from bot.enhanced_pipeline import EnhancedPipeline, PipelineConfig

        cfg = PipelineConfig(
            enable_reflexion=False, enable_conformal=False,
            enable_regime_detection=False, enable_hawkes=False,
            enable_ensemble_toxicity=False, enable_causal_leadlag=False,
            enable_research_rag=False, enable_constraints=False,
        )
        p = EnhancedPipeline(config=cfg)
        p.initialize()
        health = p.health_check()

        for v in health.values():
            assert v == "disabled"

    def test_active_components_report_ok(self, pipeline_all_mocked):
        p = pipeline_all_mocked
        # Give each mock a health_check method returning True
        for attr in ("_reflexion", "_conformal", "_regime", "_hawkes",
                     "_ensemble_tox", "_causal", "_rag", "_constraints"):
            getattr(p, attr).health_check.return_value = True

        health = p.health_check()
        for key, val in health.items():
            assert val == "ok", f"Expected ok for {key}, got {val!r}"

    def test_failed_component_reports_error(self, pipeline_all_mocked):
        p = pipeline_all_mocked
        p._reflexion.health_check.side_effect = RuntimeError("connection refused")
        health = p.health_check()
        assert health["reflexion"].startswith("error:")

    def test_missing_import_reports_import_failed(self):
        from bot.enhanced_pipeline import EnhancedPipeline, PipelineConfig

        cfg = PipelineConfig(enable_reflexion=True)
        p = EnhancedPipeline(config=cfg)
        # Simulate failed import: component is None, flag still True
        p._reflexion = None
        p._initialized = True

        health = p.health_check()
        assert health["reflexion"] == "import_failed"


# ---------------------------------------------------------------------------
# 10. create_pipeline factory
# ---------------------------------------------------------------------------

class TestCreatePipelineFactory:
    @pytest.mark.parametrize("mode", ["full", "minimal", "btc5", "event"])
    def test_create_pipeline_returns_enhanced_pipeline(self, mode):
        from bot.enhanced_pipeline import EnhancedPipeline, create_pipeline

        p = create_pipeline(mode)
        assert isinstance(p, EnhancedPipeline)

    def test_minimal_mode_disables_most_components(self):
        from bot.enhanced_pipeline import create_pipeline

        p = create_pipeline("minimal")
        assert not p.config.enable_reflexion
        assert p.config.enable_conformal
        assert not p.config.enable_regime_detection
        assert not p.config.enable_hawkes
        assert not p.config.enable_ensemble_toxicity
        assert not p.config.enable_causal_leadlag
        assert not p.config.enable_research_rag
        assert p.config.enable_constraints

    def test_btc5_mode_disables_rag(self):
        from bot.enhanced_pipeline import create_pipeline

        p = create_pipeline("btc5")
        assert not p.config.enable_research_rag
        assert p.config.enable_hawkes
        assert p.config.enable_conformal

    def test_event_mode_disables_hawkes(self):
        from bot.enhanced_pipeline import create_pipeline

        p = create_pipeline("event")
        assert not p.config.enable_hawkes
        assert p.config.enable_research_rag
        assert p.config.enable_conformal

    def test_full_mode_enables_all_core_components(self):
        from bot.enhanced_pipeline import create_pipeline

        p = create_pipeline("full")
        assert p.config.enable_reflexion
        assert p.config.enable_conformal
        assert p.config.enable_regime_detection
        assert p.config.enable_hawkes
        assert p.config.enable_ensemble_toxicity
        assert p.config.enable_causal_leadlag
        assert p.config.enable_research_rag
        assert p.config.enable_constraints

    def test_unknown_mode_raises_value_error(self):
        from bot.enhanced_pipeline import create_pipeline

        with pytest.raises(ValueError, match="Unknown pipeline mode"):
            create_pipeline("nonexistent")


# ---------------------------------------------------------------------------
# 11. Latency tracking
# ---------------------------------------------------------------------------

class TestLatencyTracking:
    def test_latency_always_present_on_early_exit(self, pipeline_all_mocked):
        p = pipeline_all_mocked
        p._conformal.calibrate.return_value = 0.50
        p._conformal.predict_interval.return_value = (0.40, 0.60)

        # market_price inside interval → ABSTAIN early exit
        sig = p.scan("m-lat", "Q?", 0.50, 0.50)
        assert sig.pipeline_latency_ms >= 0.0

    def test_latency_always_present_on_full_flow(self, pipeline_all_mocked):
        p = pipeline_all_mocked
        p._conformal.calibrate.return_value = 0.80
        p._conformal.predict_interval.return_value = (0.70, 0.90)
        p._regime.get_state.return_value = "stable"
        p._ensemble_tox.score.return_value = 0.10
        p._hawkes.is_cascade.return_value = False
        p._constraints.check.return_value = {"result": "allow", "violations": [], "position_size_usd": 5.0}
        p._causal.get_signals.return_value = []

        sig = p.scan("m-lat2", "Q?", 0.80, 0.50)
        assert sig.pipeline_latency_ms >= 0.0


# ---------------------------------------------------------------------------
# 12. Feature flag toggling
# ---------------------------------------------------------------------------

class TestFeatureFlagToggling:
    def test_disabling_reflexion_after_init_skips_store(self, pipeline_all_mocked):
        p = pipeline_all_mocked
        p.config.enable_reflexion = False

        p.post_trade_update("m1", "Q?", 0.7, 0.5, True, 1.0)

        p._reflexion.store.assert_not_called()

    def test_disabling_conformal_uses_platt_fallback(self):
        """When conformal is disabled (no ConformalCalibrator), Platt fallback must run."""
        from bot.enhanced_pipeline import EnhancedPipeline, PipelineConfig

        cfg = PipelineConfig(
            enable_reflexion=False,
            enable_conformal=False,   # disabled
            enable_regime_detection=False,
            enable_hawkes=False,
            enable_ensemble_toxicity=False,
            enable_causal_leadlag=False,
            enable_research_rag=False,
            enable_constraints=False,
        )
        p = EnhancedPipeline(config=cfg)
        p.initialize()

        # High raw probability should calibrate down via static Platt
        sig = p.scan("m-platt", "Q?", 0.90, 0.50)

        # Platt A=0.5914 B=-0.3977 on raw=0.90 → calibrated ≈ 0.79
        # Market price 0.50 is outside [0.69, 0.89] → BUY_YES expected
        assert sig.calibrated_probability < 0.90  # Platt compresses overconfidence

    def test_disabling_regime_skips_regime_check(self, pipeline_all_mocked):
        p = pipeline_all_mocked
        p.config.enable_regime_detection = False
        p._conformal.calibrate.return_value = 0.80
        p._conformal.predict_interval.return_value = (0.70, 0.90)
        p._regime.get_state.return_value = "transition"  # would normally block

        p._ensemble_tox.score.return_value = 0.10
        p._hawkes.is_cascade.return_value = False
        p._constraints.check.return_value = {"result": "allow", "violations": [], "position_size_usd": 5.0}
        p._causal.get_signals.return_value = []

        sig = p.scan("m-no-regime", "Q?", 0.80, 0.50)

        # Regime detector disabled → transition state does NOT block
        p._regime.get_state.assert_not_called()
        assert sig.final_action == "TRADE"


# ---------------------------------------------------------------------------
# 13. Graceful degradation when component import fails
# ---------------------------------------------------------------------------

class TestGracefulDegradation:
    def test_none_reflexion_disables_flag_on_initialize(self):
        """If ReflexionMemory is None (import failed), enable_reflexion → False."""
        import bot.enhanced_pipeline as ep
        original = ep.ReflexionMemory
        try:
            ep.ReflexionMemory = None  # Simulate failed import

            from bot.enhanced_pipeline import EnhancedPipeline, PipelineConfig
            cfg = PipelineConfig(enable_reflexion=True)
            p = EnhancedPipeline(config=cfg)
            result = p.initialize()

            assert result["reflexion"] is False
            assert not p.config.enable_reflexion
        finally:
            ep.ReflexionMemory = original

    def test_none_conformal_uses_fallback_calibration(self):
        """If ConformalCalibrator is None, pipeline uses static Platt and still scans."""
        import bot.enhanced_pipeline as ep
        original = ep.ConformalCalibrator
        try:
            ep.ConformalCalibrator = None

            from bot.enhanced_pipeline import EnhancedPipeline, PipelineConfig
            cfg = PipelineConfig(
                enable_conformal=True,   # flag on, but module absent
                enable_reflexion=False, enable_regime_detection=False,
                enable_hawkes=False, enable_ensemble_toxicity=False,
                enable_causal_leadlag=False, enable_research_rag=False,
                enable_constraints=False,
            )
            p = EnhancedPipeline(config=cfg)
            p.initialize()

            sig = p.scan("m-fallback", "Q?", 0.80, 0.50)
            assert isinstance(sig.calibrated_probability, float)
        finally:
            ep.ConformalCalibrator = original

    def test_crashing_conformal_calibrate_falls_back(self, pipeline_all_mocked):
        """If ConformalCalibrator.calibrate raises, pipeline uses static Platt."""
        p = pipeline_all_mocked
        p._conformal.calibrate.side_effect = RuntimeError("model corrupted")
        p._conformal.predict_interval.side_effect = RuntimeError("model corrupted")

        # Should not raise; falls back to Platt
        sig = p.scan("m-crash-cal", "Q?", 0.80, 0.40)
        assert sig.calibrated_probability > 0.0  # Platt produced something

    def test_crashing_regime_detector_does_not_propagate(self, pipeline_all_mocked):
        p = pipeline_all_mocked
        p._conformal.calibrate.return_value = 0.80
        p._conformal.predict_interval.return_value = (0.70, 0.90)
        p._regime.get_state.side_effect = RuntimeError("state error")

        # Should not raise — defaults to stable=True
        p._ensemble_tox.score.return_value = 0.10
        p._hawkes.is_cascade.return_value = False
        p._constraints.check.return_value = {"result": "allow", "violations": [], "position_size_usd": 5.0}
        p._causal.get_signals.return_value = []

        sig = p.scan("m-crash-regime", "Q?", 0.80, 0.50)
        assert sig.final_action == "TRADE"  # Defaulted to stable

    def test_crashing_rag_returns_empty_context(self, pipeline_all_mocked):
        p = pipeline_all_mocked
        p._conformal.calibrate.return_value = 0.80
        p._conformal.predict_interval.return_value = (0.70, 0.90)
        p._regime.get_state.return_value = "stable"
        p._ensemble_tox.score.return_value = 0.10
        p._hawkes.is_cascade.return_value = False
        p._rag.query.side_effect = RuntimeError("rag index corrupt")
        p._constraints.check.return_value = {"result": "allow", "violations": [], "position_size_usd": 5.0}
        p._causal.get_signals.return_value = []

        sig = p.scan("m-crash-rag", "Q?", 0.80, 0.50)
        assert sig.rag_context == ""  # Fell back to empty string
        assert sig.final_action == "TRADE"


# ---------------------------------------------------------------------------
# 14. get_diagnostics
# ---------------------------------------------------------------------------

class TestGetDiagnostics:
    def test_diagnostics_contains_config_and_components(self, pipeline_all_mocked):
        p = pipeline_all_mocked
        diag = p.get_diagnostics()

        assert "initialized" in diag
        assert "config" in diag
        assert "components" in diag
        assert diag["initialized"] is True

    def test_diagnostics_component_status_when_disabled(self):
        from bot.enhanced_pipeline import EnhancedPipeline, PipelineConfig

        cfg = PipelineConfig(
            enable_reflexion=False, enable_conformal=False,
            enable_regime_detection=False, enable_hawkes=False,
            enable_ensemble_toxicity=False, enable_causal_leadlag=False,
            enable_research_rag=False, enable_constraints=False,
        )
        p = EnhancedPipeline(config=cfg)
        p.initialize()
        diag = p.get_diagnostics()

        for comp_diag in diag["components"].values():
            assert comp_diag.get("status") == "disabled"

    def test_diagnostics_uses_component_diagnostics_method(self, pipeline_all_mocked):
        p = pipeline_all_mocked
        p._reflexion.diagnostics.return_value = {"memory_count": 42}

        diag = p.get_diagnostics()
        assert diag["components"]["reflexion"]["memory_count"] == 42


# ---------------------------------------------------------------------------
# 15. PipelineConfig dataclass defaults
# ---------------------------------------------------------------------------

class TestPipelineConfigDefaults:
    def test_default_flags(self):
        from bot.enhanced_pipeline import PipelineConfig

        cfg = PipelineConfig()
        assert cfg.enable_reflexion is True
        assert cfg.enable_conformal is True
        assert cfg.enable_regime_detection is True
        assert cfg.enable_hawkes is True
        assert cfg.enable_ensemble_toxicity is True
        assert cfg.enable_causal_leadlag is True
        assert cfg.enable_research_rag is True
        assert cfg.enable_constraints is True
        # Optional components off by default
        assert cfg.enable_symbolic_alpha is False
        assert cfg.enable_synergistic_signals is False
        assert cfg.enable_parameter_evolution is False

    def test_default_thresholds(self):
        from bot.enhanced_pipeline import PipelineConfig

        cfg = PipelineConfig()
        assert cfg.conformal_alpha == 0.10
        assert cfg.ensemble_toxic_threshold == 0.65
        assert cfg.hawkes_cascade_threshold == 3.0
        assert cfg.min_edge == 0.05
