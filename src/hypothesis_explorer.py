"""Variant explorer for the next fast-market hypothesis."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any

from .backtest import Backtester
from .config import BacktestConfig
from .shadow_tracker import SignalShadowTracker
from .strategies.base import BacktestResult, Signal
from .strategies.informed_flow_convergence import InformedFlowConvergenceStrategy


@dataclass
class FlowVariantSpec:
    key: str
    label: str
    early_window_sec: int
    min_wallets: int
    min_wallet_trades: int
    min_consensus_bias: float
    min_wallet_quality: float
    min_fair_gap: float
    flow_logit_scale: float


@dataclass
class FlowVariantResult:
    key: str
    label: str
    score: float
    gate_status: str
    gate_failures: list[str]
    metrics: dict[str, Any]
    maker_fill_sensitivity: dict[str, float]


class FlowHypothesisExplorer:
    """Search parameter variants for informed-flow convergence edge quality."""

    hypothesis_name = "Early Informed-Flow Convergence + Stale Price Filter (Maker-Only)"

    def __init__(self, backtest_cfg: BacktestConfig):
        self.backtest_cfg = backtest_cfg

        # Strict validation ladder for this hypothesis family.
        self.min_signals = 25
        self.max_p_value = 0.25
        self.max_calibration_error = 0.20
        self.min_ev_maker = 0.0
        self.min_low_fill_ev = 0.0

    def run(
        self,
        features: list[dict[str, Any]],
        resolutions: dict[str, str],
        trades: list[dict[str, Any]] | None = None,
        shadow_tracker: SignalShadowTracker | None = None,
    ) -> dict[str, Any]:
        variants = self._variant_specs()
        base_backtester = Backtester(replace(self.backtest_cfg))
        base_backtester.set_trade_tape(trades or [])
        diagnostics = self._diagnostics(features)
        results: list[FlowVariantResult] = []

        for spec in variants:
            strategy = InformedFlowConvergenceStrategy(
                early_window_sec=spec.early_window_sec,
                min_wallets=spec.min_wallets,
                min_wallet_trades=spec.min_wallet_trades,
                min_consensus_bias=spec.min_consensus_bias,
                min_wallet_quality=spec.min_wallet_quality,
                min_fair_gap=spec.min_fair_gap,
                flow_logit_scale=spec.flow_logit_scale,
            )
            raw_signals = strategy.generate_signals([], [], [], features)
            signals = self._dedupe_signals(raw_signals)
            if shadow_tracker is not None:
                shadow_tracker.record_signals(
                    signal_group="flow_variant",
                    signal_key=spec.key,
                    signal_label=spec.label,
                    signals=signals,
                )
            raw_signal_count = len(signals)
            result = strategy.backtest(signals, resolutions, base_backtester)
            maker_sensitivity = self._maker_fill_sensitivity(signals, resolutions, trades or [])
            fallback_ratio = 0.0
            if signals:
                fallback_ratio = sum(
                    1 for signal in signals if bool(signal.metadata.get("wallet_signal_fallback"))
                ) / len(signals)
            gate_status, gate_failures = self._gate_variant(
                result,
                maker_sensitivity,
                fallback_ratio,
                raw_signal_count,
            )
            score = self._score_variant(result, maker_sensitivity, gate_status, fallback_ratio)

            results.append(
                FlowVariantResult(
                    key=spec.key,
                    label=spec.label,
                    score=score,
                    gate_status=gate_status,
                    gate_failures=gate_failures,
                    metrics=self._metric_payload(result, fallback_ratio, raw_signal_count),
                    maker_fill_sensitivity=maker_sensitivity,
                )
            )

        ranked = sorted(results, key=lambda item: item.score, reverse=True)
        shadow_by_key: dict[str, dict[str, Any]] = {}
        if shadow_tracker is not None:
            summaries = shadow_tracker.summaries("flow_variant")
            shadow_by_key = shadow_tracker.summaries_to_dict(summaries)

        for item in ranked:
            shadow = shadow_by_key.get(item.key)
            if shadow:
                item.metrics["shadow"] = shadow

        passing = [item for item in ranked if item.gate_status == "pass"]
        best = ranked[0] if ranked else None

        verdict = "REJECT_ALL_VARIANTS"
        summary = "No variant survives strict maker-only pass criteria."
        if diagnostics["rows_with_wallet_signal"] == 0:
            summary = "No wallet-convergence feature rows available yet; continue collecting data."
        if passing:
            verdict = "PAPER_TEST_CANDIDATE"
            summary = (
                f"{len(passing)} variant(s) passed strict gates. "
                f"Best candidate: {passing[0].label}."
            )
        elif best is not None and best.gate_status == "watch":
            verdict = "CONTINUE_DATA_COLLECTION"
            summary = (
                f"Best variant is close but not validated yet ({best.label}). "
                "Keep in paper mode while increasing resolved sample."
            )

        return {
            "hypothesis": self.hypothesis_name,
            "verdict": verdict,
            "summary": summary,
            "pass_thresholds": {
                "min_signals": self.min_signals,
                "max_p_value": self.max_p_value,
                "max_calibration_error": self.max_calibration_error,
                "min_ev_maker": self.min_ev_maker,
                "min_low_fill_ev": self.min_low_fill_ev,
            },
            "tested_variants": len(ranked),
            "passing_variants": len(passing),
            "best_variant_key": best.key if best else None,
            "best_variant_label": best.label if best else None,
            "diagnostics": diagnostics,
            "shadow_tracking": shadow_by_key,
            "variants": [asdict(item) for item in ranked],
        }

    def _variant_specs(self) -> list[FlowVariantSpec]:
        return [
            FlowVariantSpec("flow_v1", "Balanced", 180, 3, 20, 0.10, 0.56, 0.04, 2.2),
            FlowVariantSpec("flow_v2", "Fast/Strict Consensus", 120, 3, 24, 0.14, 0.57, 0.05, 2.4),
            FlowVariantSpec("flow_v3", "Fast/Low Threshold", 120, 2, 18, 0.10, 0.56, 0.035, 2.0),
            FlowVariantSpec("flow_v4", "High Quality Wallets", 180, 3, 24, 0.12, 0.60, 0.05, 2.3),
            FlowVariantSpec("flow_v5", "More Signals", 240, 2, 16, 0.09, 0.55, 0.03, 2.0),
            FlowVariantSpec("flow_v6", "Conservative Gap", 180, 3, 20, 0.12, 0.58, 0.06, 2.6),
            FlowVariantSpec("flow_v7", "Ultra-Early", 90, 2, 14, 0.10, 0.55, 0.04, 2.1),
            FlowVariantSpec("flow_v8", "Quality + Gap", 150, 3, 22, 0.12, 0.59, 0.055, 2.5),
            FlowVariantSpec("flow_v9", "Bootstrap Cohort", 1200, 1, 2, 0.06, 0.50, 0.03, 1.8),
            FlowVariantSpec("flow_v10", "Bootstrap Fast", 900, 1, 2, 0.06, 0.50, 0.025, 1.7),
        ]

    @staticmethod
    def _diagnostics(features: list[dict[str, Any]]) -> dict[str, Any]:
        rows_15m = [row for row in features if row.get("timeframe") == "15m"]
        wallet_rows = [row for row in rows_15m if float(row.get("wallet_signal_trades") or 0.0) > 0.0]
        trade_rows = [row for row in rows_15m if float(row.get("trade_count_60s") or 0.0) > 0.0]
        fallback_rows = [row for row in wallet_rows if float(row.get("wallet_signal_fallback") or 0.0) > 0.5]
        avg_wallet_trades = 0.0
        if wallet_rows:
            avg_wallet_trades = sum(float(row.get("wallet_signal_trades") or 0.0) for row in wallet_rows) / len(wallet_rows)
        return {
            "rows_15m": len(rows_15m),
            "rows_with_trade_flow": len(trade_rows),
            "rows_with_wallet_signal": len(wallet_rows),
            "rows_with_wallet_fallback_signal": len(fallback_rows),
            "avg_wallet_signal_trades": avg_wallet_trades,
        }

    @staticmethod
    def _metric_payload(result: BacktestResult, fallback_ratio: float, raw_signal_count: int) -> dict[str, Any]:
        return {
            "raw_signals": raw_signal_count,
            "signals": result.signals,
            "wins": result.wins,
            "win_rate": result.win_rate,
            "ev_maker": result.ev_maker,
            "ev_taker": result.ev_taker,
            "p_value": result.p_value,
            "calibration_error": result.calibration_error,
            "sharpe": result.sharpe,
            "max_drawdown": result.max_drawdown,
            "regime_decay": result.regime_decay,
            "fallback_ratio": fallback_ratio,
        }

    def _maker_fill_sensitivity(
        self,
        signals: list[Signal],
        resolutions: dict[str, str],
        trades: list[dict[str, Any]],
    ) -> dict[str, float]:
        fill_rates = sorted(
            {
                float(self.backtest_cfg.maker_fill_rate),
                *[float(rate) for rate in self.backtest_cfg.maker_fill_rate_sensitivity],
            }
        )
        output: dict[str, float] = {}
        for rate in fill_rates:
            cfg = replace(self.backtest_cfg, maker_fill_rate=rate)
            backtester = Backtester(cfg)
            backtester.set_trade_tape(trades)
            result = backtester.evaluate("flow_fill_sensitivity", signals, resolutions)
            output[f"maker_fill_{rate:.2f}"] = result.ev_maker
        return output

    def _gate_variant(
        self,
        result: BacktestResult,
        maker_sensitivity: dict[str, float],
        fallback_ratio: float,
        raw_signal_count: int,
    ) -> tuple[str, list[str]]:
        failures: list[str] = []

        if result.signals == 0 and raw_signal_count > 0:
            watch_failures = ["no_resolved_outcomes_for_generated_signals"]
            if fallback_ratio > 0.60:
                watch_failures.append("excess_fallback_signals")
            return "watch", watch_failures

        if result.signals < self.min_signals:
            failures.append(f"resolved_signals<{self.min_signals}")
        if result.ev_maker <= self.min_ev_maker:
            failures.append("ev_maker<=0")
        if result.p_value > self.max_p_value:
            failures.append(f"p_value>{self.max_p_value}")
        if result.calibration_error > self.max_calibration_error:
            failures.append(f"calibration>{self.max_calibration_error}")
        if result.regime_decay:
            failures.append("regime_decay")
        if fallback_ratio > 0.60:
            failures.append("excess_fallback_signals")

        low_fill_ev = 0.0
        if maker_sensitivity:
            low_fill_ev = min(maker_sensitivity.values())
        if low_fill_ev <= self.min_low_fill_ev:
            failures.append("maker_edge_not_robust_at_low_fill")

        if not failures:
            return "pass", failures

        near_miss = (
            result.signals >= max(8, self.min_signals // 2)
            and result.ev_maker > 0
            and result.calibration_error <= self.max_calibration_error + 0.05
        )
        if near_miss:
            return "watch", failures
        return "fail", failures

    @staticmethod
    def _score_variant(
        result: BacktestResult,
        maker_sensitivity: dict[str, float],
        gate_status: str,
        fallback_ratio: float,
    ) -> float:
        low_fill_ev = min(maker_sensitivity.values()) if maker_sensitivity else 0.0
        score = 0.0
        score += 0.45 * result.ev_maker
        score += 0.25 * low_fill_ev
        score += 0.15 * ((result.win_rate - 0.5) * 10.0)
        score += 0.10 * (1.0 - min(1.0, result.calibration_error))
        score += 0.05 * (1.0 - min(1.0, result.p_value))
        score -= 0.25 * min(1.0, max(0.0, fallback_ratio))

        if gate_status == "watch":
            score -= 0.20
        elif gate_status == "fail":
            score -= 1.00
        return score

    @staticmethod
    def _dedupe_signals(signals: list[Signal]) -> list[Signal]:
        seen: set[tuple[str, int, str]] = set()
        out: list[Signal] = []
        for signal in sorted(signals, key=lambda s: (s.condition_id, s.timestamp_ts, s.side)):
            key = (signal.condition_id, signal.timestamp_ts, signal.side)
            if key in seen:
                continue
            seen.add(key)
            out.append(signal)
        return out
