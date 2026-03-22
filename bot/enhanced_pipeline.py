#!/usr/bin/env python3
"""
Enhanced Trading Pipeline — Unified Orchestration Layer
========================================================
Wires together reflexion memory, conformal calibration, regime detection,
Hawkes order flow, ensemble toxicity, causal lead-lag, research RAG, and
constraint enforcement into a single scan-cycle pipeline.

Each component is imported with a try/except guard. When an import fails
the corresponding feature flag is automatically disabled and a warning is
emitted. This means the pipeline works even against a partially-built repo.

Architecture overview (per scan cycle):
  Phase 1 — CALIBRATE  : Conformal calibration → prediction interval → bet/abstain
  Phase 2 — REGIME     : Regime detector → safe/transition gate
  Phase 3 — TOXICITY   : Ensemble toxicity + Hawkes cascade gate
  Phase 4 — ENRICH     : Reflexion retrieval + RAG dispatch retrieval
  Phase 5 — CAUSAL     : Cross-market causal lead-lag signals
  Phase 6 — CONSTRAIN  : Position-level constraint enforcement
  Phase 7 — DECIDE     : Aggregate → final action + confidence score

Author: JJ (autonomous)
Date: 2026-03-21
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("JJ.enhanced_pipeline")

# ---------------------------------------------------------------------------
# Optional component imports — all guarded with None fallback
# ---------------------------------------------------------------------------

try:
    from bot.reflexion_memory import ReflexionMemory
except ImportError:
    ReflexionMemory = None  # type: ignore[assignment,misc]

try:
    from bot.conformal_calibration import ConformalCalibrator
except ImportError:
    ConformalCalibrator = None  # type: ignore[assignment,misc]

try:
    from bot.regime_detector import RegimeDetector
except ImportError:
    RegimeDetector = None  # type: ignore[assignment,misc]

try:
    from bot.hawkes_order_flow import HawkesOrderFlow
except ImportError:
    HawkesOrderFlow = None  # type: ignore[assignment,misc]

try:
    from bot.ensemble_toxicity import EnsembleToxicity
except ImportError:
    EnsembleToxicity = None  # type: ignore[assignment,misc]

try:
    from bot.causal_leadlag import CausalLeadLag
except ImportError:
    CausalLeadLag = None  # type: ignore[assignment,misc]

try:
    from bot.research_rag import ResearchRAG
except ImportError:
    ResearchRAG = None  # type: ignore[assignment,misc]

try:
    from bot.constraint_enforcer import ConstraintEnforcer
except ImportError:
    ConstraintEnforcer = None  # type: ignore[assignment,misc]

try:
    from bot.symbolic_alpha import SymbolicAlpha
except ImportError:
    SymbolicAlpha = None  # type: ignore[assignment,misc]

try:
    from bot.synergistic_signals import SynergisticSignals
except ImportError:
    SynergisticSignals = None  # type: ignore[assignment,misc]

try:
    from bot.parameter_evolution import ParameterEvolution
except ImportError:
    ParameterEvolution = None  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class PipelineConfig:
    """Configuration for the enhanced pipeline.

    Feature flags enable/disable each component independently.
    When a component module is missing at import time the corresponding
    flag is automatically set to False by EnhancedPipeline.initialize().
    """

    # Feature flags
    enable_reflexion: bool = True
    enable_conformal: bool = True
    enable_regime_detection: bool = True
    enable_hawkes: bool = True
    enable_ensemble_toxicity: bool = True
    enable_causal_leadlag: bool = True
    enable_research_rag: bool = True
    enable_constraints: bool = True
    enable_symbolic_alpha: bool = False      # Requires pre-fitted model
    enable_synergistic_signals: bool = False  # Requires pre-fitted model
    enable_parameter_evolution: bool = False  # Runs offline, not per-cycle

    # Paths
    reflexion_db_path: str = "reflexion_memory.db"
    research_dispatch_dir: str = "research/dispatches"
    rag_cache_path: str = ".rag_cache"

    # Thresholds
    conformal_alpha: float = 0.10          # 90% coverage
    regime_hazard_rate: float = 0.02       # 1/50 expected run length
    hawkes_cascade_threshold: float = 3.0
    ensemble_toxic_threshold: float = 0.65
    min_edge: float = 0.05


@dataclass
class PipelineSignal:
    """Output of the enhanced pipeline for one market scan."""

    market_id: str
    market_question: str

    # Raw inputs
    raw_probability: float
    market_price: float

    # Phase 1: Calibration
    calibrated_probability: float
    conformal_interval: tuple[float, float]
    conformal_decision: str                 # "BUY_YES", "BUY_NO", "ABSTAIN"

    # Phase 2: Regime
    regime_state: str                       # "stable", "transition", "warmup"
    regime_safe: bool

    # Phase 3: Toxicity
    ensemble_toxicity_score: float
    is_toxic: bool
    hawkes_cascade: bool

    # Phase 4: Context enrichment
    reflexion_context: str
    rag_context: str

    # Phase 5: Causal signals
    causal_signals: list[dict]

    # Phase 6: Constraint check
    constraint_result: str                  # "allow", "block", "modify", "escalate"
    constraint_violations: list[str]

    # Final decision
    final_action: str                       # "TRADE", "SKIP", "ESCALATE"
    skip_reason: str
    position_size_usd: float
    confidence: float

    # Metadata
    pipeline_latency_ms: float
    components_used: list[str]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _platt_calibrate(raw: float) -> float:
    """Static Platt calibration fallback (A=0.5914, B=-0.3977)."""
    import math
    import os

    a = float(os.environ.get("PLATT_A", "0.5914"))
    b = float(os.environ.get("PLATT_B", "-0.3977"))
    try:
        log_odds = math.log(raw / (1.0 - raw))
        return 1.0 / (1.0 + math.exp(-(a * log_odds + b)))
    except (ValueError, ZeroDivisionError):
        return max(0.01, min(0.99, raw))


def _conformal_interval(prob: float, alpha: float) -> tuple[float, float]:
    """Symmetric conformal prediction interval around calibrated probability.

    This is a lightweight approximation. When ConformalCalibrator is
    available it replaces this. Width grows with alpha (miscoverage).
    """
    half_width = alpha * 0.5 + 0.05
    lower = max(0.01, prob - half_width)
    upper = min(0.99, prob + half_width)
    return (lower, upper)


def _conformal_decision(prob: float, interval: tuple[float, float],
                        market_price: float, min_edge: float) -> str:
    """Derive bet direction from calibrated probability and prediction interval.

    Returns "BUY_YES", "BUY_NO", or "ABSTAIN".
    ABSTAIN when:
    - market_price is inside the prediction interval (no clear edge)
    - calibrated edge < min_edge
    """
    lower, upper = interval
    # If market price is within the interval we cannot assert a clear direction
    if lower <= market_price <= upper:
        return "ABSTAIN"
    edge_yes = prob - market_price
    edge_no = (1.0 - market_price) - (1.0 - prob)
    if edge_yes >= min_edge:
        return "BUY_YES"
    if edge_no >= min_edge:
        return "BUY_NO"
    return "ABSTAIN"


def _compute_confidence(calibrated_prob: float, market_price: float,
                        regime_safe: bool, is_toxic: bool,
                        causal_signals: list[dict]) -> float:
    """Aggregate confidence score in [0, 1].

    Base: absolute edge vs market price, clipped to [0, 0.5].
    Boosts: +0.1 if regime safe, +0.05 per causal confirming signal.
    Penalties: -0.3 if toxic flow, -0.2 if regime not safe.
    """
    raw_edge = abs(calibrated_prob - market_price)
    base = min(raw_edge * 2.0, 0.5)

    if regime_safe:
        base += 0.10
    else:
        base -= 0.20

    if is_toxic:
        base -= 0.30

    for sig in causal_signals:
        if sig.get("confirming", False):
            base += 0.05

    return max(0.0, min(1.0, base))


def _kelly_size(prob: float, price: float, bankroll: float,
                kelly_fraction: float = 0.25, max_position: float = 50.0) -> float:
    """Quarter-Kelly position size with hard cap."""
    if price <= 0.0 or price >= 1.0:
        return 0.0
    # Fractional Kelly: f = kelly_fraction * (p - q) / (1 - p_win)
    # For binary prediction market: f = kelly_fraction * (p - price) / (1 - price)
    edge = prob - price
    if edge <= 0:
        return 0.0
    f = kelly_fraction * edge / (1.0 - price)
    return min(bankroll * f, max_position)


# ---------------------------------------------------------------------------
# Main pipeline class
# ---------------------------------------------------------------------------

class EnhancedPipeline:
    """Unified enhanced trading pipeline.

    Composes all advanced components into a deterministic scan → signal flow.
    Components that cannot be imported are disabled automatically.
    """

    def __init__(self, config: PipelineConfig | None = None) -> None:
        self.config = config or PipelineConfig()
        self._reflexion: Any = None
        self._conformal: Any = None
        self._regime: Any = None
        self._hawkes: Any = None
        self._ensemble_tox: Any = None
        self._causal: Any = None
        self._rag: Any = None
        self._constraints: Any = None
        self._symbolic: Any = None
        self._synergistic: Any = None
        self._param_evo: Any = None
        self._initialized = False

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def initialize(self) -> dict[str, bool]:
        """Initialize all enabled components.

        Returns mapping of component_name → initialized_successfully.
        When a component class is None (import failed) the corresponding
        feature flag is disabled and False is recorded.
        """
        cfg = self.config
        results: dict[str, bool] = {}

        # --- Reflexion Memory ---
        if cfg.enable_reflexion:
            if ReflexionMemory is None:
                logger.warning("ReflexionMemory not available; disabling reflexion")
                cfg.enable_reflexion = False
                results["reflexion"] = False
            else:
                try:
                    self._reflexion = ReflexionMemory(db_path=cfg.reflexion_db_path)
                    results["reflexion"] = True
                except Exception as exc:
                    logger.warning("ReflexionMemory init failed: %s", exc)
                    cfg.enable_reflexion = False
                    results["reflexion"] = False
        else:
            results["reflexion"] = False

        # --- Conformal Calibrator ---
        if cfg.enable_conformal:
            if ConformalCalibrator is None:
                logger.warning("ConformalCalibrator not available; using static Platt fallback")
                cfg.enable_conformal = False
                results["conformal"] = False
            else:
                try:
                    self._conformal = ConformalCalibrator(alpha=cfg.conformal_alpha)
                    results["conformal"] = True
                except Exception as exc:
                    logger.warning("ConformalCalibrator init failed: %s", exc)
                    cfg.enable_conformal = False
                    results["conformal"] = False
        else:
            results["conformal"] = False

        # --- Regime Detector ---
        if cfg.enable_regime_detection:
            if RegimeDetector is None:
                logger.warning("RegimeDetector not available; disabling regime detection")
                cfg.enable_regime_detection = False
                results["regime_detection"] = False
            else:
                try:
                    self._regime = RegimeDetector(hazard_rate=cfg.regime_hazard_rate)
                    results["regime_detection"] = True
                except Exception as exc:
                    logger.warning("RegimeDetector init failed: %s", exc)
                    cfg.enable_regime_detection = False
                    results["regime_detection"] = False
        else:
            results["regime_detection"] = False

        # --- Hawkes Order Flow ---
        if cfg.enable_hawkes:
            if HawkesOrderFlow is None:
                logger.warning("HawkesOrderFlow not available; disabling Hawkes")
                cfg.enable_hawkes = False
                results["hawkes"] = False
            else:
                try:
                    self._hawkes = HawkesOrderFlow(
                        cascade_threshold=cfg.hawkes_cascade_threshold
                    )
                    results["hawkes"] = True
                except Exception as exc:
                    logger.warning("HawkesOrderFlow init failed: %s", exc)
                    cfg.enable_hawkes = False
                    results["hawkes"] = False
        else:
            results["hawkes"] = False

        # --- Ensemble Toxicity ---
        if cfg.enable_ensemble_toxicity:
            if EnsembleToxicity is None:
                logger.warning("EnsembleToxicity not available; disabling ensemble toxicity")
                cfg.enable_ensemble_toxicity = False
                results["ensemble_toxicity"] = False
            else:
                try:
                    self._ensemble_tox = EnsembleToxicity(
                        toxic_threshold=cfg.ensemble_toxic_threshold
                    )
                    results["ensemble_toxicity"] = True
                except Exception as exc:
                    logger.warning("EnsembleToxicity init failed: %s", exc)
                    cfg.enable_ensemble_toxicity = False
                    results["ensemble_toxicity"] = False
        else:
            results["ensemble_toxicity"] = False

        # --- Causal Lead-Lag ---
        if cfg.enable_causal_leadlag:
            if CausalLeadLag is None:
                logger.warning("CausalLeadLag not available; disabling causal lead-lag")
                cfg.enable_causal_leadlag = False
                results["causal_leadlag"] = False
            else:
                try:
                    self._causal = CausalLeadLag()
                    results["causal_leadlag"] = True
                except Exception as exc:
                    logger.warning("CausalLeadLag init failed: %s", exc)
                    cfg.enable_causal_leadlag = False
                    results["causal_leadlag"] = False
        else:
            results["causal_leadlag"] = False

        # --- Research RAG ---
        if cfg.enable_research_rag:
            if ResearchRAG is None:
                logger.warning("ResearchRAG not available; disabling RAG")
                cfg.enable_research_rag = False
                results["research_rag"] = False
            else:
                try:
                    self._rag = ResearchRAG(
                        dispatch_dir=cfg.research_dispatch_dir,
                        cache_path=cfg.rag_cache_path,
                    )
                    results["research_rag"] = True
                except Exception as exc:
                    logger.warning("ResearchRAG init failed: %s", exc)
                    cfg.enable_research_rag = False
                    results["research_rag"] = False
        else:
            results["research_rag"] = False

        # --- Constraint Enforcer ---
        if cfg.enable_constraints:
            if ConstraintEnforcer is None:
                logger.warning("ConstraintEnforcer not available; disabling constraint enforcement")
                cfg.enable_constraints = False
                results["constraints"] = False
            else:
                try:
                    self._constraints = ConstraintEnforcer()
                    results["constraints"] = True
                except Exception as exc:
                    logger.warning("ConstraintEnforcer init failed: %s", exc)
                    cfg.enable_constraints = False
                    results["constraints"] = False
        else:
            results["constraints"] = False

        # --- Symbolic Alpha (optional, requires pre-fitted model) ---
        if cfg.enable_symbolic_alpha:
            if SymbolicAlpha is None:
                logger.warning("SymbolicAlpha not available; disabling symbolic alpha")
                cfg.enable_symbolic_alpha = False
                results["symbolic_alpha"] = False
            else:
                try:
                    self._symbolic = SymbolicAlpha()
                    results["symbolic_alpha"] = True
                except Exception as exc:
                    logger.warning("SymbolicAlpha init failed: %s", exc)
                    cfg.enable_symbolic_alpha = False
                    results["symbolic_alpha"] = False
        else:
            results["symbolic_alpha"] = False

        # --- Synergistic Signals (optional, requires pre-fitted model) ---
        if cfg.enable_synergistic_signals:
            if SynergisticSignals is None:
                logger.warning("SynergisticSignals not available; disabling synergistic signals")
                cfg.enable_synergistic_signals = False
                results["synergistic_signals"] = False
            else:
                try:
                    self._synergistic = SynergisticSignals()
                    results["synergistic_signals"] = True
                except Exception as exc:
                    logger.warning("SynergisticSignals init failed: %s", exc)
                    cfg.enable_synergistic_signals = False
                    results["synergistic_signals"] = False
        else:
            results["synergistic_signals"] = False

        # --- Parameter Evolution (offline only) ---
        if cfg.enable_parameter_evolution:
            if ParameterEvolution is None:
                logger.warning("ParameterEvolution not available; disabling parameter evolution")
                cfg.enable_parameter_evolution = False
                results["parameter_evolution"] = False
            else:
                try:
                    self._param_evo = ParameterEvolution()
                    results["parameter_evolution"] = True
                except Exception as exc:
                    logger.warning("ParameterEvolution init failed: %s", exc)
                    cfg.enable_parameter_evolution = False
                    results["parameter_evolution"] = False
        else:
            results["parameter_evolution"] = False

        self._initialized = True
        enabled_count = sum(1 for v in results.values() if v)
        logger.info(
            "EnhancedPipeline initialized: %d/%d components active",
            enabled_count,
            len(results),
        )
        return results

    # ------------------------------------------------------------------
    # Main scan cycle
    # ------------------------------------------------------------------

    def scan(
        self,
        market_id: str,
        market_question: str,
        raw_probability: float,
        market_price: float,
        recent_trades: list | None = None,
        trade_pnl_history: list[float] | None = None,
        multi_market_prices: dict[str, list[float]] | None = None,
        bankroll: float = 1000.0,
        daily_pnl: float = 0.0,
        open_positions: int = 0,
    ) -> PipelineSignal:
        """Run the full enhanced pipeline for one market.

        Early-exit pattern: critical phase failures set final_action=SKIP
        and return immediately without running downstream phases.
        """
        if not self._initialized:
            self.initialize()

        t_start = time.monotonic()
        cfg = self.config
        components_used: list[str] = []
        recent_trades = recent_trades or []
        trade_pnl_history = trade_pnl_history or []
        multi_market_prices = multi_market_prices or {}

        # ------------------------------------------------------------------
        # Phase 1 — CALIBRATE
        # ------------------------------------------------------------------
        if cfg.enable_conformal and self._conformal is not None:
            components_used.append("conformal")
            try:
                calibrated_prob = self._conformal.calibrate(raw_probability)
                interval = self._conformal.predict_interval(raw_probability)
            except Exception as exc:
                logger.warning("ConformalCalibrator.calibrate failed: %s", exc)
                calibrated_prob = _platt_calibrate(raw_probability)
                interval = _conformal_interval(calibrated_prob, cfg.conformal_alpha)
        else:
            calibrated_prob = _platt_calibrate(raw_probability)
            interval = _conformal_interval(calibrated_prob, cfg.conformal_alpha)

        conformal_decision = _conformal_decision(
            calibrated_prob, interval, market_price, cfg.min_edge
        )

        if conformal_decision == "ABSTAIN":
            latency_ms = (time.monotonic() - t_start) * 1000.0
            logger.debug(
                "market=%s SKIP conformal_abstain (prob=%.3f price=%.3f interval=%s)",
                market_id,
                calibrated_prob,
                market_price,
                interval,
            )
            return PipelineSignal(
                market_id=market_id,
                market_question=market_question,
                raw_probability=raw_probability,
                market_price=market_price,
                calibrated_probability=calibrated_prob,
                conformal_interval=interval,
                conformal_decision=conformal_decision,
                regime_state="unknown",
                regime_safe=False,
                ensemble_toxicity_score=0.0,
                is_toxic=False,
                hawkes_cascade=False,
                reflexion_context="",
                rag_context="",
                causal_signals=[],
                constraint_result="block",
                constraint_violations=["conformal_abstain"],
                final_action="SKIP",
                skip_reason="conformal_abstain",
                position_size_usd=0.0,
                confidence=0.0,
                pipeline_latency_ms=latency_ms,
                components_used=components_used,
            )

        # ------------------------------------------------------------------
        # Phase 2 — REGIME CHECK
        # ------------------------------------------------------------------
        regime_state = "stable"
        regime_safe = True

        if cfg.enable_regime_detection and self._regime is not None:
            components_used.append("regime_detection")
            try:
                regime_result = self._regime.get_state()
                # Normalize: accept str or object with .state attribute
                if isinstance(regime_result, str):
                    regime_state = regime_result
                elif hasattr(regime_result, "state"):
                    regime_state = str(regime_result.state)
                else:
                    regime_state = str(regime_result)
                regime_safe = regime_state == "stable"
            except Exception as exc:
                logger.warning("RegimeDetector.get_state failed: %s", exc)

        if not regime_safe:
            latency_ms = (time.monotonic() - t_start) * 1000.0
            logger.debug("market=%s SKIP regime_transition (state=%s)", market_id, regime_state)
            return PipelineSignal(
                market_id=market_id,
                market_question=market_question,
                raw_probability=raw_probability,
                market_price=market_price,
                calibrated_probability=calibrated_prob,
                conformal_interval=interval,
                conformal_decision=conformal_decision,
                regime_state=regime_state,
                regime_safe=False,
                ensemble_toxicity_score=0.0,
                is_toxic=False,
                hawkes_cascade=False,
                reflexion_context="",
                rag_context="",
                causal_signals=[],
                constraint_result="block",
                constraint_violations=["regime_transition"],
                final_action="SKIP",
                skip_reason="regime_transition",
                position_size_usd=0.0,
                confidence=0.0,
                pipeline_latency_ms=latency_ms,
                components_used=components_used,
            )

        # ------------------------------------------------------------------
        # Phase 3 — TOXICITY
        # ------------------------------------------------------------------
        ensemble_toxicity_score = 0.0
        is_toxic = False
        hawkes_cascade = False

        if cfg.enable_ensemble_toxicity and self._ensemble_tox is not None:
            components_used.append("ensemble_toxicity")
            try:
                tox_result = self._ensemble_tox.score(recent_trades)
                if isinstance(tox_result, (int, float)):
                    ensemble_toxicity_score = float(tox_result)
                elif hasattr(tox_result, "score"):
                    ensemble_toxicity_score = float(tox_result.score)
                is_toxic = ensemble_toxicity_score >= cfg.ensemble_toxic_threshold
            except Exception as exc:
                logger.warning("EnsembleToxicity.score failed: %s", exc)

        if cfg.enable_hawkes and self._hawkes is not None:
            components_used.append("hawkes")
            try:
                hawkes_result = self._hawkes.is_cascade(recent_trades)
                if isinstance(hawkes_result, bool):
                    hawkes_cascade = hawkes_result
                elif hasattr(hawkes_result, "is_cascade"):
                    hawkes_cascade = bool(hawkes_result.is_cascade)
                else:
                    hawkes_cascade = bool(hawkes_result)
            except Exception as exc:
                logger.warning("HawkesOrderFlow.is_cascade failed: %s", exc)

        if is_toxic or hawkes_cascade:
            latency_ms = (time.monotonic() - t_start) * 1000.0
            reason = "toxic_flow" if is_toxic else "hawkes_cascade"
            logger.debug(
                "market=%s SKIP %s (tox=%.3f hawkes=%s)",
                market_id,
                reason,
                ensemble_toxicity_score,
                hawkes_cascade,
            )
            return PipelineSignal(
                market_id=market_id,
                market_question=market_question,
                raw_probability=raw_probability,
                market_price=market_price,
                calibrated_probability=calibrated_prob,
                conformal_interval=interval,
                conformal_decision=conformal_decision,
                regime_state=regime_state,
                regime_safe=regime_safe,
                ensemble_toxicity_score=ensemble_toxicity_score,
                is_toxic=is_toxic,
                hawkes_cascade=hawkes_cascade,
                reflexion_context="",
                rag_context="",
                causal_signals=[],
                constraint_result="block",
                constraint_violations=[reason],
                final_action="SKIP",
                skip_reason=reason,
                position_size_usd=0.0,
                confidence=0.0,
                pipeline_latency_ms=latency_ms,
                components_used=components_used,
            )

        # ------------------------------------------------------------------
        # Phase 4 — CONTEXT ENRICHMENT
        # ------------------------------------------------------------------
        reflexion_context = ""
        rag_context = ""

        if cfg.enable_reflexion and self._reflexion is not None:
            components_used.append("reflexion")
            try:
                reflexion_context = self._reflexion.retrieve(market_question)
                if not isinstance(reflexion_context, str):
                    reflexion_context = str(reflexion_context)
            except Exception as exc:
                logger.warning("ReflexionMemory.retrieve failed: %s", exc)
                reflexion_context = ""

        if cfg.enable_research_rag and self._rag is not None:
            components_used.append("research_rag")
            try:
                rag_context = self._rag.query(market_question)
                if not isinstance(rag_context, str):
                    rag_context = str(rag_context)
            except Exception as exc:
                logger.warning("ResearchRAG.query failed: %s", exc)
                rag_context = ""

        # ------------------------------------------------------------------
        # Phase 5 — CAUSAL SIGNALS
        # ------------------------------------------------------------------
        causal_signals: list[dict] = []

        if cfg.enable_causal_leadlag and self._causal is not None and multi_market_prices:
            components_used.append("causal_leadlag")
            try:
                raw_signals = self._causal.get_signals(
                    market_id=market_id,
                    prices=multi_market_prices,
                )
                if isinstance(raw_signals, list):
                    causal_signals = raw_signals
                else:
                    causal_signals = list(raw_signals)
            except Exception as exc:
                logger.warning("CausalLeadLag.get_signals failed: %s", exc)

        # ------------------------------------------------------------------
        # Phase 6 — CONSTRAINT CHECK
        # ------------------------------------------------------------------
        constraint_result = "allow"
        constraint_violations: list[str] = []
        position_size_usd = _kelly_size(
            calibrated_prob, market_price, bankroll, kelly_fraction=0.25
        )

        if cfg.enable_constraints and self._constraints is not None:
            components_used.append("constraints")
            try:
                check = self._constraints.check(
                    market_id=market_id,
                    position_size_usd=position_size_usd,
                    bankroll=bankroll,
                    daily_pnl=daily_pnl,
                    open_positions=open_positions,
                )
                if isinstance(check, dict):
                    constraint_result = check.get("result", "allow")
                    constraint_violations = check.get("violations", [])
                    # Enforcer may modify position size down
                    if "position_size_usd" in check:
                        position_size_usd = float(check["position_size_usd"])
                elif hasattr(check, "result"):
                    constraint_result = str(check.result)
                    constraint_violations = list(getattr(check, "violations", []))
                    if hasattr(check, "position_size_usd"):
                        position_size_usd = float(check.position_size_usd)
                else:
                    constraint_result = str(check)
            except Exception as exc:
                logger.warning("ConstraintEnforcer.check failed: %s", exc)

        if constraint_result == "block":
            latency_ms = (time.monotonic() - t_start) * 1000.0
            logger.debug(
                "market=%s SKIP constraint_block violations=%s",
                market_id,
                constraint_violations,
            )
            return PipelineSignal(
                market_id=market_id,
                market_question=market_question,
                raw_probability=raw_probability,
                market_price=market_price,
                calibrated_probability=calibrated_prob,
                conformal_interval=interval,
                conformal_decision=conformal_decision,
                regime_state=regime_state,
                regime_safe=regime_safe,
                ensemble_toxicity_score=ensemble_toxicity_score,
                is_toxic=is_toxic,
                hawkes_cascade=hawkes_cascade,
                reflexion_context=reflexion_context,
                rag_context=rag_context,
                causal_signals=causal_signals,
                constraint_result=constraint_result,
                constraint_violations=constraint_violations,
                final_action="SKIP",
                skip_reason="constraint_block",
                position_size_usd=0.0,
                pipeline_latency_ms=(time.monotonic() - t_start) * 1000.0,
                confidence=0.0,
                components_used=components_used,
            )

        if constraint_result == "escalate":
            latency_ms = (time.monotonic() - t_start) * 1000.0
            logger.info("market=%s ESCALATE constraint_escalate", market_id)
            return PipelineSignal(
                market_id=market_id,
                market_question=market_question,
                raw_probability=raw_probability,
                market_price=market_price,
                calibrated_probability=calibrated_prob,
                conformal_interval=interval,
                conformal_decision=conformal_decision,
                regime_state=regime_state,
                regime_safe=regime_safe,
                ensemble_toxicity_score=ensemble_toxicity_score,
                is_toxic=is_toxic,
                hawkes_cascade=hawkes_cascade,
                reflexion_context=reflexion_context,
                rag_context=rag_context,
                causal_signals=causal_signals,
                constraint_result=constraint_result,
                constraint_violations=constraint_violations,
                final_action="ESCALATE",
                skip_reason="",
                position_size_usd=position_size_usd,
                pipeline_latency_ms=latency_ms,
                confidence=0.0,
                components_used=components_used,
            )

        # ------------------------------------------------------------------
        # Phase 7 — FINAL DECISION
        # ------------------------------------------------------------------
        confidence = _compute_confidence(
            calibrated_prob, market_price, regime_safe, is_toxic, causal_signals
        )

        latency_ms = (time.monotonic() - t_start) * 1000.0
        logger.info(
            "market=%s TRADE decision=%s size=%.2f conf=%.3f latency=%.1fms",
            market_id,
            conformal_decision,
            position_size_usd,
            confidence,
            latency_ms,
        )

        return PipelineSignal(
            market_id=market_id,
            market_question=market_question,
            raw_probability=raw_probability,
            market_price=market_price,
            calibrated_probability=calibrated_prob,
            conformal_interval=interval,
            conformal_decision=conformal_decision,
            regime_state=regime_state,
            regime_safe=regime_safe,
            ensemble_toxicity_score=ensemble_toxicity_score,
            is_toxic=is_toxic,
            hawkes_cascade=hawkes_cascade,
            reflexion_context=reflexion_context,
            rag_context=rag_context,
            causal_signals=causal_signals,
            constraint_result=constraint_result,
            constraint_violations=constraint_violations,
            final_action="TRADE",
            skip_reason="",
            position_size_usd=position_size_usd,
            confidence=confidence,
            pipeline_latency_ms=latency_ms,
            components_used=components_used,
        )

    # ------------------------------------------------------------------
    # Post-trade learning update
    # ------------------------------------------------------------------

    def post_trade_update(
        self,
        market_id: str,
        market_question: str,
        predicted_prob: float,
        market_price: float,
        outcome: bool,
        pnl: float,
        tags: list[str] | None = None,
    ) -> None:
        """Called after a trade resolves.

        1. Store reflexion with outcome and P&L.
        2. Feed residual to conformal calibrator.
        3. Update regime detector with P&L observation.
        4. Update ensemble toxicity reward model.

        All failures are caught and logged — this must never crash the caller.
        """
        tags = tags or []

        if self.config.enable_reflexion and self._reflexion is not None:
            try:
                self._reflexion.store(
                    market_id=market_id,
                    question=market_question,
                    predicted_prob=predicted_prob,
                    outcome=outcome,
                    pnl=pnl,
                    tags=tags,
                )
            except Exception as exc:
                logger.warning("ReflexionMemory.store failed: %s", exc)

        if self.config.enable_conformal and self._conformal is not None:
            try:
                residual = float(outcome) - predicted_prob
                self._conformal.update(residual)
            except Exception as exc:
                logger.warning("ConformalCalibrator.update failed: %s", exc)

        if self.config.enable_regime_detection and self._regime is not None:
            try:
                self._regime.observe(pnl)
            except Exception as exc:
                logger.warning("RegimeDetector.observe failed: %s", exc)

        if self.config.enable_ensemble_toxicity and self._ensemble_tox is not None:
            try:
                self._ensemble_tox.reward(pnl)
            except Exception as exc:
                logger.warning("EnsembleToxicity.reward failed: %s", exc)

        logger.debug(
            "post_trade_update market=%s outcome=%s pnl=%.4f",
            market_id,
            outcome,
            pnl,
        )

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def get_diagnostics(self) -> dict:
        """Return diagnostic info from all components."""
        diag: dict = {
            "initialized": self._initialized,
            "config": {
                "enable_reflexion": self.config.enable_reflexion,
                "enable_conformal": self.config.enable_conformal,
                "enable_regime_detection": self.config.enable_regime_detection,
                "enable_hawkes": self.config.enable_hawkes,
                "enable_ensemble_toxicity": self.config.enable_ensemble_toxicity,
                "enable_causal_leadlag": self.config.enable_causal_leadlag,
                "enable_research_rag": self.config.enable_research_rag,
                "enable_constraints": self.config.enable_constraints,
            },
            "components": {},
        }

        components = [
            ("reflexion", self._reflexion),
            ("conformal", self._conformal),
            ("regime", self._regime),
            ("hawkes", self._hawkes),
            ("ensemble_toxicity", self._ensemble_tox),
            ("causal_leadlag", self._causal),
            ("research_rag", self._rag),
            ("constraints", self._constraints),
        ]

        for name, obj in components:
            if obj is None:
                diag["components"][name] = {"status": "disabled"}
            else:
                try:
                    if hasattr(obj, "diagnostics"):
                        diag["components"][name] = obj.diagnostics()
                    elif hasattr(obj, "get_diagnostics"):
                        diag["components"][name] = obj.get_diagnostics()
                    else:
                        diag["components"][name] = {"status": "active", "type": type(obj).__name__}
                except Exception as exc:
                    diag["components"][name] = {"status": "error", "error": str(exc)}

        return diag

    def health_check(self) -> dict[str, str]:
        """Check that all enabled components are functional.

        Returns {component: "ok" | error_message}.
        """
        results: dict[str, str] = {}

        checks = [
            ("reflexion", self.config.enable_reflexion, self._reflexion),
            ("conformal", self.config.enable_conformal, self._conformal),
            ("regime_detection", self.config.enable_regime_detection, self._regime),
            ("hawkes", self.config.enable_hawkes, self._hawkes),
            ("ensemble_toxicity", self.config.enable_ensemble_toxicity, self._ensemble_tox),
            ("causal_leadlag", self.config.enable_causal_leadlag, self._causal),
            ("research_rag", self.config.enable_research_rag, self._rag),
            ("constraints", self.config.enable_constraints, self._constraints),
        ]

        for name, enabled, obj in checks:
            if not enabled:
                results[name] = "disabled"
                continue
            if obj is None:
                results[name] = "import_failed"
                continue
            try:
                if hasattr(obj, "health_check"):
                    status = obj.health_check()
                    results[name] = "ok" if status else "unhealthy"
                elif hasattr(obj, "ping"):
                    obj.ping()
                    results[name] = "ok"
                else:
                    # Assume alive if the object exists and was initialized
                    results[name] = "ok"
            except Exception as exc:
                results[name] = f"error: {exc}"

        return results


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_pipeline(mode: str = "full") -> EnhancedPipeline:
    """Create an EnhancedPipeline with preset configurations.

    Modes
    -----
    full      All components enabled. Use for event-market scans with ample data.
    minimal   Only conformal calibration + constraints. Lowest latency.
    btc5      Optimised for BTC 5-min markets. Drops RAG (dispatch context irrelevant
              for 5-min windows). All other components active.
    event     Optimised for event markets. Drops Hawkes (not meaningful for low-frequency
              event flow). All other components active.
    """
    if mode == "full":
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

    elif mode == "minimal":
        cfg = PipelineConfig(
            enable_reflexion=False,
            enable_conformal=True,
            enable_regime_detection=False,
            enable_hawkes=False,
            enable_ensemble_toxicity=False,
            enable_causal_leadlag=False,
            enable_research_rag=False,
            enable_constraints=True,
        )

    elif mode == "btc5":
        cfg = PipelineConfig(
            enable_reflexion=True,
            enable_conformal=True,
            enable_regime_detection=True,
            enable_hawkes=True,
            enable_ensemble_toxicity=True,
            enable_causal_leadlag=True,
            enable_research_rag=False,  # Dispatch RAG not useful for 5-min candles
            enable_constraints=True,
        )

    elif mode == "event":
        cfg = PipelineConfig(
            enable_reflexion=True,
            enable_conformal=True,
            enable_regime_detection=True,
            enable_hawkes=False,  # Event markets lack intraday order-flow cascade signal
            enable_ensemble_toxicity=True,
            enable_causal_leadlag=True,
            enable_research_rag=True,
            enable_constraints=True,
        )

    else:
        raise ValueError(
            f"Unknown pipeline mode: {mode!r}. Valid modes: full, minimal, btc5, event"
        )

    pipeline = EnhancedPipeline(config=cfg)
    logger.info("create_pipeline mode=%s", mode)
    return pipeline
