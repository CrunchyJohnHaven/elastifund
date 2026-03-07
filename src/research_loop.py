"""Continuous research loop orchestrating collection, testing, and reporting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from pathlib import Path
import re
import threading
import time
from typing import Any

from .backtest import Backtester, walk_forward_model_competition
from .config import AppConfig
from .data_pipeline import DataPipeline
from .edge_registry import build_registry
from .feature_engineering import FeatureEngineer
from .hypothesis_explorer import FlowHypothesisExplorer
from .hypothesis_manager import HypothesisEvaluation, HypothesisManager
from .reporting import ReportWriter
from .shadow_tracker import SignalShadowTracker
from .strategies.ml_scanner import MLFeatureDiscoveryStrategy
from .strategies.base import BacktestResult, Signal


@dataclass
class CycleResult:
    timestamp: int
    recommendation: str
    top_hypothesis: str | None
    evaluations: list[HypothesisEvaluation]


class ResearchLoop:
    """Top-level engine for periodic edge discovery cycles."""

    def __init__(self, config: AppConfig, logger: logging.Logger | None = None):
        self.config = config
        self.logger = logger or logging.getLogger(__name__)

        self.pipeline = DataPipeline(config, logger=self.logger)
        self.features = FeatureEngineer(config.system.db_path)
        self.backtester = Backtester(config.backtest)
        self.manager = HypothesisManager(config.research)
        self.reporter = ReportWriter(config)
        self.flow_explorer = FlowHypothesisExplorer(config.backtest)
        self.shadow_tracker = SignalShadowTracker(config.system.db_path)
        self.ml_scanner = MLFeatureDiscoveryStrategy()

        self._last_ml_ts: int = 0

    def run_cycle(self, run_ml: bool = False, collect_data: bool = True) -> CycleResult:
        now = int(time.time())
        self.logger.info("Research cycle start: %s", datetime.fromtimestamp(now, tz=timezone.utc).isoformat())

        if collect_data:
            self.pipeline.collect_once()
        bundle = self.features.build_feature_bundle()
        self.backtester.set_trade_tape(bundle.trades)
        self.shadow_tracker.resolve(bundle.resolutions, self.backtester)

        registry = build_registry(self.config)
        evaluations: list[HypothesisEvaluation] = []
        result_by_key: dict[str, BacktestResult] = {}

        for hypothesis in registry:
            strategy = hypothesis.constructor()
            signals = strategy.generate_signals(
                market_data=bundle.markets,
                price_data=bundle.btc_prices,
                trade_data=bundle.trades,
                features=bundle.features,
            )
            signals = self._dedupe_signals(signals)
            self.shadow_tracker.record_signals(
                signal_group="registry",
                signal_key=hypothesis.key,
                signal_label=hypothesis.name,
                signals=signals,
            )

            result = strategy.backtest(signals, bundle.resolutions, self.backtester)
            stress = self.backtester.stress_costs(signals, bundle.resolutions)

            perturbation_stability = self._parameter_perturbation_stability(strategy, bundle, bundle.resolutions)

            evaluation = self.manager.evaluate(
                key=hypothesis.key,
                name=hypothesis.name,
                result=result,
                stress=stress,
                simplicity=hypothesis.simplicity,
                perturbation_stability=perturbation_stability,
            )

            result_by_key[hypothesis.key] = result
            evaluations.append(evaluation)

        self.shadow_tracker.resolve(bundle.resolutions, self.backtester)

        ranked = self.manager.rank(evaluations)
        recommendation, reason = self.manager.recommendation(ranked)

        model_competition = walk_forward_model_competition(
            bundle.features,
            model_seed=self.config.models.mc_seed,
            mc_paths=min(self.config.models.mc_default_paths, 2000),
        )
        hypothesis_exploration = self.flow_explorer.run(
            bundle.features,
            bundle.resolutions,
            trades=bundle.trades,
            shadow_tracker=self.shadow_tracker,
        )
        self.shadow_tracker.resolve(bundle.resolutions, self.backtester)

        registry_shadow = self.shadow_tracker.summaries_to_dict(self.shadow_tracker.summaries("registry"))
        for item in evaluations:
            if item.key in registry_shadow:
                item.metrics["shadow"] = registry_shadow[item.key]

        ml_candidates = []
        if run_ml:
            known_features = {
                "yes_price",
                "btc_return_since_open",
                "realized_vol_1h",
                "inner_up_bias",
                "wallet_up_bias",
                "prev_window_return",
                "book_imbalance",
                "trade_flow_imbalance",
                "basis_lag_score",
                "time_remaining_sec",
                "hour_utc",
                "weekday",
            }
            ml_candidates = self.ml_scanner.discover(bundle.features, known_features)
            self._last_ml_ts = now

        data_coverage = self._build_data_coverage(bundle)
        reality_check = {
            "slippage_assumption": self.config.backtest.slippage_taker,
            "spread_assumption": self.config.backtest.default_spread,
            "maker_fill_assumption": self.config.backtest.maker_fill_rate,
            "maker_fill_model": self.backtester._model_name(self.config.backtest),
            "confidence_calibration": (
                "sequential_bayes_isotonic"
                if self.config.backtest.confidence_calibration_enabled
                else "none"
            ),
            "execution_delay": self.config.backtest.execution_delay_seconds,
            "data_quality_issues": self._quality_issues(),
            "edge_fake_risks": [
                "data leakage from timestamp alignment",
                "execution delay underestimation",
                "selection bias from low-liquidity windows",
                "regime instability",
            ],
        }

        next_actions = self._next_actions(ranked, result_by_key, hypothesis_exploration)
        change_log = [
            "Ran collector + feature refresh + full strategy competition cycle.",
            "Updated hypothesis rankings with kill-rule evaluation and cost stress tests.",
            "Executed informed-flow convergence variant explorer with maker-fill sensitivity checks.",
            "Enabled strict trade-through maker fill validation from observed trade tape where available.",
            "Applied sequential confidence calibration in backtest scoring and diagnostics.",
            "Regenerated analysis markdown and run-specific artifacts.",
        ]

        self.reporter.write_run_artifacts(
            run_ts=now,
            data_coverage=data_coverage,
            evaluations=ranked,
            result_by_key=result_by_key,
            model_competition=model_competition,
            ml_candidates=ml_candidates,
            hypothesis_exploration=hypothesis_exploration,
            reality_check=reality_check,
            next_actions=next_actions,
            change_log=change_log,
            recommendation=recommendation,
            reasoning=reason,
        )

        top_name = ranked[0].name if ranked else None
        self.logger.info("Research cycle complete. Recommendation=%s Top=%s", recommendation, top_name)

        return CycleResult(timestamp=now, recommendation=recommendation, top_hypothesis=top_name, evaluations=ranked)

    @staticmethod
    def _dedupe_signals(signals: list[Signal]) -> list[Signal]:
        seen: set[tuple[str, int, str]] = set()
        out: list[Signal] = []
        for signal in sorted(signals, key=lambda s: (s.condition_id, s.timestamp_ts)):
            key = (signal.condition_id, signal.timestamp_ts, signal.side)
            if key in seen:
                continue
            seen.add(key)
            out.append(signal)
        return out

    def _parameter_perturbation_stability(self, strategy: Any, bundle: Any, resolutions: dict[str, str]) -> float:
        base_signals = strategy.generate_signals(bundle.markets, bundle.btc_prices, bundle.trades, bundle.features)
        base_result = strategy.backtest(self._dedupe_signals(base_signals), resolutions, self.backtester)

        if not hasattr(strategy, "threshold"):
            return 0.7 if base_result.signals > 0 else 0.4

        original = getattr(strategy, "threshold")
        try:
            setattr(strategy, "threshold", original * 0.9)
            lo = strategy.backtest(
                self._dedupe_signals(strategy.generate_signals(bundle.markets, bundle.btc_prices, bundle.trades, bundle.features)),
                resolutions,
                self.backtester,
            )
            setattr(strategy, "threshold", original * 1.1)
            hi = strategy.backtest(
                self._dedupe_signals(strategy.generate_signals(bundle.markets, bundle.btc_prices, bundle.trades, bundle.features)),
                resolutions,
                self.backtester,
            )
        finally:
            setattr(strategy, "threshold", original)

        base = max(abs(base_result.ev_taker), 1e-6)
        delta = abs(lo.ev_taker - hi.ev_taker) / base
        return max(0.0, min(1.0, 1.0 - min(delta, 1.0)))

    def _quality_issues(self) -> list[str]:
        path = Path(self.config.system.db_path)
        if not path.exists():
            return ["database missing"]

        import sqlite3

        with sqlite3.connect(path) as conn:
            rows = conn.execute(
                "SELECT event_type FROM data_quality_events ORDER BY id DESC LIMIT 5"
            ).fetchall()
        return [row[0] for row in rows] if rows else []

    @staticmethod
    def _build_data_coverage(bundle: Any) -> dict[str, Any]:
        markets_15m = [m for m in bundle.markets if m.get("timeframe") == "15m"]
        markets_5m = [m for m in bundle.markets if m.get("timeframe") == "5m"]
        markets_4h = [m for m in bundle.markets if m.get("timeframe") == "4h"]

        resolved_15m = sum(1 for m in markets_15m if m.get("final_resolution") in ("UP", "DOWN"))
        data_start = None
        data_end = None
        if bundle.btc_prices:
            data_start = datetime.fromtimestamp(int(bundle.btc_prices[0]["timestamp_ts"]), tz=timezone.utc).isoformat()
            data_end = datetime.fromtimestamp(int(bundle.btc_prices[-1]["timestamp_ts"]), tz=timezone.utc).isoformat()

        return {
            "markets_15m": len(markets_15m),
            "resolved_15m": resolved_15m,
            "markets_5m": len(markets_5m),
            "markets_4h": len(markets_4h),
            "btc_points": len(bundle.btc_prices),
            "trade_records": len(bundle.trades),
            "unique_wallets": len({t.get("wallet") for t in bundle.trades if t.get("wallet")}),
            "data_start": data_start,
            "data_end": data_end,
        }

    def _next_actions(
        self,
        ranked: list[HypothesisEvaluation],
        results: dict[str, BacktestResult],
        exploration: dict[str, Any] | None = None,
    ) -> list[str]:
        actions: list[str] = []
        if not ranked:
            return ["Collect more data before model retraining."]

        top = ranked[0]
        top_result = results.get(top.key)
        if top_result and top_result.signals < 100:
            actions.append("Increase data collection horizon to reach >=100 signals for top strategy.")
        if top_result and top_result.ev_taker <= 0:
            actions.append("Tighten entry thresholds or drop low-confidence signals for top strategy.")
        if top_result and top_result.calibration_error > 0.15:
            if self.config.backtest.confidence_calibration_enabled:
                actions.append("Retune confidence calibration bins/prior and re-evaluate top strategy calibration drift.")
            else:
                actions.append("Apply explicit probability calibration layer on top strategy outputs.")
        if top_result and self.backtester._model_name(self.config.backtest) == "trade_through":
            coverage_note = next((n for n in top_result.notes if n.startswith("Trade-through tape coverage:")), "")
            match = re.search(r"(\d+)\s*/\s*(\d+)", coverage_note)
            if match:
                covered = int(match.group(1))
                total = max(1, int(match.group(2)))
                coverage_ratio = covered / total
                if coverage_ratio < 0.7:
                    actions.append("Improve trade tape completeness for strict trade-through fill validation (target >=70% coverage).")
        if exploration:
            verdict = str(exploration.get("verdict") or "")
            if verdict == "REJECT_ALL_VARIANTS":
                actions.append(
                    "Continue paper-only data collection for informed-flow convergence; no variant has cleared strict maker-only gates."
                )
            elif verdict == "CONTINUE_DATA_COLLECTION":
                actions.append(
                    "Promote top informed-flow convergence variant to focused shadow tracking until it clears signal-count and p-value gates."
                )
            elif verdict == "PAPER_TEST_CANDIDATE":
                actions.append(
                    "Run paper trading on the top informed-flow convergence variant with 1/16 Kelly cap and daily stop-loss discipline."
                )
        actions.append("Run ML scanner on next 6-hour interval for new feature proposals.")
        return actions

    def run_forever(self, stop_event: threading.Event) -> None:
        interval = max(60, self.config.research.run_interval_minutes * 60)
        ml_interval = max(3600, self.config.research.ml_interval_hours * 3600)

        while not stop_event.is_set():
            now = int(time.time())
            run_ml = now - self._last_ml_ts >= ml_interval
            try:
                self.run_cycle(run_ml=run_ml, collect_data=False)
            except Exception as exc:
                self.logger.exception("Research cycle failure: %s", exc)

            stop_event.wait(interval)
