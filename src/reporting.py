"""Reporting and artifact generation for edge discovery runs."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from .config import AppConfig
from .hypothesis_manager import HypothesisEvaluation
from .strategies.ml_scanner import FeatureCandidate
from .strategies.base import BacktestResult

try:  # pragma: no cover - optional dependency
    import matplotlib.pyplot as plt  # type: ignore
except Exception:  # pragma: no cover
    plt = None


class ReportWriter:
    """Write markdown, JSON, and chart artifacts for each research cycle."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.report_root = Path(config.system.report_root)
        self.report_root.mkdir(parents=True, exist_ok=True)
        self.analysis_path = Path(config.system.analysis_path)

    def write_run_artifacts(
        self,
        run_ts: int,
        data_coverage: dict[str, Any],
        evaluations: list[HypothesisEvaluation],
        result_by_key: dict[str, BacktestResult],
        model_competition: list[dict[str, Any]],
        ml_candidates: list[FeatureCandidate],
        reality_check: dict[str, Any],
        next_actions: list[str],
        change_log: list[str],
        recommendation: str,
        reasoning: str,
        hypothesis_exploration: dict[str, Any] | None = None,
    ) -> dict[str, Path]:
        stamp = datetime.fromtimestamp(run_ts, tz=timezone.utc).strftime("%Y%m%d_%H%M%S")

        metrics_path = self.report_root / f"run_{stamp}_metrics.json"
        report_path = self.report_root / f"run_{stamp}_summary.md"

        payload = {
            "timestamp": datetime.fromtimestamp(run_ts, tz=timezone.utc).isoformat(),
            "data_coverage": data_coverage,
            "evaluations": [asdict(item) for item in evaluations],
            "results": {k: asdict(v) for k, v in result_by_key.items()},
            "model_competition": model_competition,
            "ml_candidates": [asdict(item) for item in ml_candidates],
            "hypothesis_exploration": hypothesis_exploration or {},
            "reality_check": reality_check,
            "next_actions": next_actions,
            "change_log": change_log,
            "recommendation": recommendation,
            "reasoning": reasoning,
        }
        metrics_path.write_text(json.dumps(payload, indent=2))

        report_md = self._render_run_summary(payload)
        report_path.write_text(report_md)

        chart_paths = self._write_charts(stamp, evaluations, result_by_key)
        self._write_analysis_markdown(
            run_ts=run_ts,
            data_coverage=data_coverage,
            evaluations=evaluations,
            result_by_key=result_by_key,
            model_competition=model_competition,
            ml_candidates=ml_candidates,
            hypothesis_exploration=hypothesis_exploration,
            reality_check=reality_check,
            next_actions=next_actions,
            change_log=change_log,
            recommendation=recommendation,
            reasoning=reasoning,
        )
        pipeline_path = self._write_pipeline_summary(
            run_ts=run_ts,
            metrics_path=metrics_path,
            summary_path=report_path,
            chart_paths=chart_paths,
            data_coverage=data_coverage,
            evaluations=evaluations,
            result_by_key=result_by_key,
            hypothesis_exploration=hypothesis_exploration or {},
            reality_check=reality_check,
            recommendation=recommendation,
            reasoning=reasoning,
        )

        out = {
            "metrics": metrics_path,
            "summary": report_path,
            **chart_paths,
            "analysis": self.analysis_path,
            "pipeline": pipeline_path,
        }
        return out

    @staticmethod
    def _render_run_summary(payload: dict[str, Any]) -> str:
        lines = ["# Run Summary", ""]
        lines.append(f"Timestamp: {payload['timestamp']}")
        lines.append("")
        lines.append("## Coverage")
        coverage = payload["data_coverage"]
        for key, value in coverage.items():
            lines.append(f"- {key}: {value}")
        lines.append("")
        lines.append("## Top Ranked Hypotheses")
        for eval_item in payload["evaluations"][:5]:
            lines.append(
                f"- {eval_item['name']}: status={eval_item['status']}, score={eval_item['score']:.4f}, confidence={eval_item['confidence']:.2f}"
            )
        lines.append("")
        lines.append("## Model Competition")
        for row in payload["model_competition"]:
            lines.append(
                f"- {row['model']}: expectancy={row['oos_expectancy']:.4f}, calibration={row['calibration_error']:.4f}, beats_baseline={row['beats_baseline']}"
            )
        exploration = payload.get("hypothesis_exploration") or {}
        if exploration:
            lines.append("")
            lines.append("## Informed-Flow Hypothesis Explorer")
            lines.append(f"- Verdict: {exploration.get('verdict', 'n/a')}")
            lines.append(f"- Tested variants: {exploration.get('tested_variants', 0)}")
            lines.append(f"- Passing variants: {exploration.get('passing_variants', 0)}")
            lines.append(f"- Best variant: {exploration.get('best_variant_label', 'n/a')}")
        return "\n".join(lines)

    def _write_charts(
        self,
        stamp: str,
        evaluations: list[HypothesisEvaluation],
        result_by_key: dict[str, BacktestResult],
    ) -> dict[str, Path]:
        paths: dict[str, Path] = {}
        if plt is None:
            fallback = self.report_root / f"run_{stamp}_charts_unavailable.txt"
            fallback.write_text("matplotlib not installed; chart generation skipped.")
            paths["charts"] = fallback
            return paths

        names = [item.name for item in evaluations]
        scores = [item.score for item in evaluations]
        evs = [float(result_by_key[item.key].ev_taker) for item in evaluations if item.key in result_by_key]

        score_chart = self.report_root / f"run_{stamp}_score_chart.png"
        plt.figure(figsize=(10, 4))
        plt.bar(range(len(scores)), scores)
        plt.xticks(range(len(scores)), names, rotation=45, ha="right")
        plt.ylabel("Composite score")
        plt.tight_layout()
        plt.savefig(score_chart)
        plt.close()
        paths["score_chart"] = score_chart

        ev_chart = self.report_root / f"run_{stamp}_expectancy_chart.png"
        plt.figure(figsize=(10, 4))
        plt.bar(range(len(evs)), evs)
        plt.xticks(range(len(evs)), names[: len(evs)], rotation=45, ha="right")
        plt.ylabel("EV per trade (taker)")
        plt.tight_layout()
        plt.savefig(ev_chart)
        plt.close()
        paths["expectancy_chart"] = ev_chart

        return paths

    def _write_analysis_markdown(
        self,
        run_ts: int,
        data_coverage: dict[str, Any],
        evaluations: list[HypothesisEvaluation],
        result_by_key: dict[str, BacktestResult],
        model_competition: list[dict[str, Any]],
        ml_candidates: list[FeatureCandidate],
        hypothesis_exploration: dict[str, Any] | None,
        reality_check: dict[str, Any],
        next_actions: list[str],
        change_log: list[str],
        recommendation: str,
        reasoning: str,
    ) -> None:
        timestamp = datetime.fromtimestamp(run_ts, tz=timezone.utc).isoformat()

        validated: list[HypothesisEvaluation] = []
        candidate: list[HypothesisEvaluation] = []
        investigating: list[HypothesisEvaluation] = []
        rejected: list[HypothesisEvaluation] = []

        for item in evaluations:
            result = result_by_key.get(item.key)
            if item.status == "rejected":
                rejected.append(item)
            elif item.status == "promoted" and result and result.signals >= 300 and result.p_value < 0.01:
                validated.append(item)
            elif result and result.signals >= 100 and result.p_value < 0.05:
                candidate.append(item)
            else:
                investigating.append(item)

        lines: list[str] = []
        lines.append("# Fast Trade Edge Analysis")
        lines.append(f"**Last Updated:** {timestamp}")
        lines.append("**System Status:** running")
        lines.append(f"**Data Window:** {data_coverage.get('data_start', 'n/a')} to {data_coverage.get('data_end', 'n/a')}")
        lines.append("")

        lines.append("## Data Coverage")
        lines.append(f"- 15-min markets observed: {data_coverage.get('markets_15m', 0)} ({data_coverage.get('resolved_15m', 0)} resolved)")
        lines.append(f"- 5-min markets observed: {data_coverage.get('markets_5m', 0)}")
        lines.append(f"- 4-hour markets observed: {data_coverage.get('markets_4h', 0)}")
        lines.append(f"- BTC price data points: {data_coverage.get('btc_points', 0)}")
        lines.append(f"- Trade records: {data_coverage.get('trade_records', 0)}")
        lines.append(f"- Unique wallets tracked: {data_coverage.get('unique_wallets', 0)}")
        lines.append("")

        lines.append("## Current Recommendation")
        lines.append(recommendation)
        lines.append("")
        lines.append(f"Reasoning: {reasoning}")
        lines.append("\n---\n")

        lines.append("## VALIDATED EDGES (p < 0.01, n > 300)")
        if validated:
            for item in validated:
                lines.extend(self._render_hypothesis_block(item, result_by_key[item.key]))
        else:
            lines.append("None currently validated.")
        lines.append("\n---\n")

        lines.append("## CANDIDATE EDGES (p < 0.05, n > 100)")
        if candidate:
            for item in candidate:
                lines.extend(self._render_hypothesis_block(item, result_by_key[item.key]))
        else:
            lines.append("No candidate edges currently meet thresholds.")
        lines.append("\n---\n")

        lines.append("## UNDER INVESTIGATION (n < 100)")
        if investigating:
            for item in investigating:
                result = result_by_key.get(item.key)
                if not result:
                    continue
                lines.append(f"### {item.name}")
                lines.append(f"- Signals: {result.signals}")
                lines.append(f"- Win rate: {result.win_rate:.2%}")
                lines.append("- Note: Insufficient data - collecting")
                lines.append("")
        else:
            lines.append("No hypotheses in investigation bucket.")
        lines.append("\n---\n")

        lines.append("## REJECTED")
        lines.append("| Strategy | Signals | Win Rate | Reason for Rejection |")
        lines.append("|----------|---------|----------|----------------------|")
        for item in rejected:
            result = result_by_key.get(item.key)
            if not result:
                continue
            reason = "; ".join(item.rejection_reasons) if item.rejection_reasons else "Failed kill rules"
            lines.append(f"| {item.name} | {result.signals} | {result.win_rate:.2%} | {reason} |")
        if not rejected:
            lines.append("| — | — | — | No strategies rejected in this run |")
        lines.append("\n---\n")

        lines.extend(self._render_hypothesis_exploration(hypothesis_exploration or {}))
        lines.append("\n---\n")

        lines.append("## MODEL COMPETITION TABLE")
        lines.append("| Model | OOS Expectancy | Sharpe | Calibration Error | Beats Baseline? |")
        lines.append("|-------|---------------|--------|-------------------|-----------------|")
        for row in model_competition:
            lines.append(
                f"| {row['model']} | {row['oos_expectancy']:.4f} | {row['sharpe_like']:.4f} | {row['calibration_error']:.4f} | {row['beats_baseline']} |"
            )
        if not model_competition:
            lines.append("| No model comparison available | 0.0 | 0.0 | 0.0 | False |")
        lines.append("\n---\n")

        lines.append("## ML-DISCOVERED FEATURE CANDIDATES")
        if ml_candidates:
            for candidate_item in ml_candidates:
                lines.append(
                    f"- {candidate_item.name}: importance={candidate_item.importance:.3f}; preliminary signal={candidate_item.note}"
                )
        else:
            lines.append("No new feature candidates flagged.")
        lines.append("\n---\n")

        lines.append("## REALITY CHECK")
        lines.append(f"- Slippage assumption: {reality_check.get('slippage_assumption', 'n/a')}")
        lines.append(f"- Spread assumption: {reality_check.get('spread_assumption', 'n/a')}")
        lines.append(f"- Maker fill rate assumption: {reality_check.get('maker_fill_assumption', 'n/a')}")
        lines.append(f"- Maker fill model: {reality_check.get('maker_fill_model', 'constant')}")
        lines.append(f"- Confidence calibration: {reality_check.get('confidence_calibration', 'none')}")
        lines.append(f"- Execution delay assumption: {reality_check.get('execution_delay', 'n/a')}")
        lines.append(f"- Data quality issues: {', '.join(reality_check.get('data_quality_issues', [])) or 'none'}")
        lines.append(f"- Reasons apparent edge may be fake: {', '.join(reality_check.get('edge_fake_risks', []))}")
        lines.append("\n---\n")

        lines.append("## NEXT ACTIONS")
        for action in next_actions:
            lines.append(f"- {action}")
        lines.append("- Kill conditions: reject if OOS expectancy <= 0 or cost-stress flips sign")
        lines.append("- Promotion conditions: n>=300, p<0.01, positive taker EV under stress")
        lines.append("\n---\n")

        lines.append("## CHANGE LOG")
        lines.append("| Timestamp | Change |")
        lines.append("|-----------|--------|")
        for change in change_log:
            lines.append(f"| {timestamp} | {change} |")

        self.analysis_path.write_text("\n".join(lines))

    def _write_pipeline_summary(
        self,
        run_ts: int,
        metrics_path: Path,
        summary_path: Path,
        chart_paths: dict[str, Path],
        data_coverage: dict[str, Any],
        evaluations: list[HypothesisEvaluation],
        result_by_key: dict[str, BacktestResult],
        hypothesis_exploration: dict[str, Any],
        reality_check: dict[str, Any],
        recommendation: str,
        reasoning: str,
    ) -> Path:
        pipeline_stamp = datetime.fromtimestamp(run_ts, tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        pipeline_path = self.report_root / f"pipeline_{pipeline_stamp}.json"
        top_item = evaluations[0] if evaluations else None
        top_result = result_by_key.get(top_item.key) if top_item else None

        fast_market_counts = {
            "total_markets_observed": sum(
                int(data_coverage.get(key, 0)) for key in ("markets_15m", "markets_5m", "markets_4h")
            ),
            "markets_15m": int(data_coverage.get("markets_15m", 0)),
            "resolved_15m": int(data_coverage.get("resolved_15m", 0)),
            "markets_5m": int(data_coverage.get("markets_5m", 0)),
            "markets_4h": int(data_coverage.get("markets_4h", 0)),
            "btc_points": int(data_coverage.get("btc_points", 0)),
            "trade_records": int(data_coverage.get("trade_records", 0)),
            "unique_wallets": int(data_coverage.get("unique_wallets", 0)),
            "data_window_start": data_coverage.get("data_start"),
            "data_window_end": data_coverage.get("data_end"),
        }

        pipeline_payload = {
            "report_generated_at": datetime.now(timezone.utc).isoformat(),
            "run_timestamp": datetime.fromtimestamp(run_ts, tz=timezone.utc).isoformat(),
            "authoritative_artifacts": {
                "analysis_markdown": str(self.analysis_path),
                "metrics_json": str(metrics_path),
                "summary_markdown": str(summary_path),
                "score_chart": str(chart_paths["score_chart"]) if "score_chart" in chart_paths else None,
                "expectancy_chart": (
                    str(chart_paths["expectancy_chart"]) if "expectancy_chart" in chart_paths else None
                ),
                "charts_note": str(chart_paths["charts"]) if "charts" in chart_paths else None,
                "log_path": self.config.system.log_path,
            },
            "public_safe_counts": {
                "fast_markets": fast_market_counts,
                "a6_b1": self._load_structural_public_counts(),
            },
            "pipeline_verdict": {
                "recommendation": recommendation,
                "reasoning": reasoning,
                "top_ranked_hypothesis": self._serialize_hypothesis(top_item, top_result),
            },
            "edges_found": self._build_edge_summary(evaluations, result_by_key, hypothesis_exploration),
            "calibration_drift": self._build_calibration_drift_summary(evaluations),
            "new_viable_strategies": self._build_new_viable_strategies(evaluations, result_by_key),
            "data_quality": {
                "issues_from_metrics": list(reality_check.get("data_quality_issues", [])),
                "maker_fill_model": reality_check.get("maker_fill_model", "constant"),
                "maker_fill_assumption": reality_check.get("maker_fill_assumption"),
                "confidence_calibration": reality_check.get("confidence_calibration", "none"),
                "execution_delay_seconds": reality_check.get("execution_delay"),
                "edge_fake_risks": list(reality_check.get("edge_fake_risks", [])),
            },
        }
        pipeline_path.write_text(json.dumps(pipeline_payload, indent=2))
        return pipeline_path

    @staticmethod
    def _render_hypothesis_exploration(exploration: dict[str, Any]) -> list[str]:
        lines: list[str] = []
        lines.append("## NEXT BEST HYPOTHESIS EXPLORATION")
        if not exploration:
            lines.append("No hypothesis exploration payload available for this run.")
            return lines

        lines.append(f"- Hypothesis: {exploration.get('hypothesis', 'n/a')}")
        lines.append(f"- Verdict: {exploration.get('verdict', 'n/a')}")
        lines.append(f"- Summary: {exploration.get('summary', 'n/a')}")
        lines.append(f"- Variants tested: {exploration.get('tested_variants', 0)}")
        lines.append(f"- Variants passing strict gates: {exploration.get('passing_variants', 0)}")
        lines.append(f"- Best variant: {exploration.get('best_variant_label', 'n/a')}")

        diagnostics = exploration.get("diagnostics", {})
        if diagnostics:
            lines.append(f"- 15m feature rows: {diagnostics.get('rows_15m', 0)}")
            lines.append(f"- 15m rows with trade-flow data: {diagnostics.get('rows_with_trade_flow', 0)}")
            lines.append(f"- 15m rows with wallet-convergence data: {diagnostics.get('rows_with_wallet_signal', 0)}")
            lines.append(
                f"- 15m rows using wallet fallback mode: {diagnostics.get('rows_with_wallet_fallback_signal', 0)}"
            )
            lines.append(f"- Avg wallet trades per wallet-signal row: {float(diagnostics.get('avg_wallet_signal_trades', 0.0)):.2f}")

        shadow = exploration.get("shadow_tracking", {})
        if shadow:
            total = sum(int(item.get("total_signals", 0)) for item in shadow.values())
            resolved = sum(int(item.get("resolved_signals", 0)) for item in shadow.values())
            open_count = sum(int(item.get("open_signals", 0)) for item in shadow.values())
            lines.append(f"- Shadow tracker (variants): total={total}, resolved={resolved}, open={open_count}")

        thresholds = exploration.get("pass_thresholds", {})
        if thresholds:
            lines.append("")
            lines.append("### Pass/Fail Gates")
            lines.append(f"- Min signals: {thresholds.get('min_signals', 'n/a')}")
            lines.append(f"- Max p-value: {thresholds.get('max_p_value', 'n/a')}")
            lines.append(f"- Max calibration error: {thresholds.get('max_calibration_error', 'n/a')}")
            lines.append(f"- Min EV maker: {thresholds.get('min_ev_maker', 'n/a')}")
            lines.append(f"- Min low-fill EV maker: {thresholds.get('min_low_fill_ev', 'n/a')}")

        variants = exploration.get("variants") or []
        lines.append("")
        lines.append("| Variant | Raw Signals | Resolved Signals | Win Rate | EV Maker | EV Taker | P-value | Calibration | Fallback Share | Gate | Gate Failures |")
        lines.append("|---------|-------------|------------------|----------|----------|----------|---------|-------------|----------------|------|---------------|")
        for item in variants[:10]:
            metrics = item.get("metrics", {})
            failures = ", ".join(item.get("gate_failures", [])) or "none"
            lines.append(
                f"| {item.get('label', 'n/a')} | {metrics.get('raw_signals', 0)} | {metrics.get('signals', 0)} | "
                f"{float(metrics.get('win_rate', 0.0)):.2%} | {float(metrics.get('ev_maker', 0.0)):.4f} | "
                f"{float(metrics.get('ev_taker', 0.0)):.4f} | {float(metrics.get('p_value', 1.0)):.4f} | "
                f"{float(metrics.get('calibration_error', 1.0)):.4f} | "
                f"{float(metrics.get('fallback_ratio', 0.0)):.2%} | {item.get('gate_status', 'n/a')} | {failures} |"
            )
        if not variants:
            lines.append("| — | — | — | — | — | — | — | — | — | — | No variants evaluated |")
        return lines

    @staticmethod
    def _render_hypothesis_block(item: HypothesisEvaluation, result: BacktestResult) -> list[str]:
        lines = [f"### {item.name}"]
        lines.append(f"- **Signals:** {result.signals}")
        lines.append(f"- **Win rate:** {result.win_rate:.2%} (95% CI: {result.wilson_low:.2%}-{result.wilson_high:.2%})")
        lines.append(f"- **EV per trade (after maker costs):** ${result.ev_maker:.4f}")
        lines.append(f"- **EV per trade (after taker costs):** ${result.ev_taker:.4f}")
        lines.append(f"- **Monthly estimate at $1K capital:** ${(result.ev_taker * 1000 / 100):.2f}")
        lines.append(f"- **Sharpe:** {result.sharpe:.4f}")
        lines.append(f"- **Max drawdown:** {result.max_drawdown:.4f}")
        lines.append(f"- **P-value:** {result.p_value:.5f}")
        lines.append(f"- **Kelly fraction:** {result.kelly_fraction:.4f}")
        lines.append(f"- **Regime stability:** {'degrading' if result.regime_decay else 'stable'}")
        lines.append(f"- **Beats closed-form baseline?** {'yes' if item.metrics.get('score_vs_closed_form', 0) > 0 else 'no'}")
        lines.append(f"- **Beats naive baseline?** {'yes' if item.score > 0 else 'no'}")
        lines.append(f"- **Survives cost stress test?** {'yes' if item.metrics.get('stress', {}).get('cost_up', -1) > 0 else 'no'}")
        lines.append(f"- **Survives parameter perturbation?** {'yes' if item.metrics.get('perturbation', 0.6) >= 0.6 else 'no'}")
        shadow = item.metrics.get("shadow", {})
        if shadow:
            lines.append(
                f"- **Shadow tracker:** total={int(shadow.get('total_signals', 0))}, "
                f"resolved={int(shadow.get('resolved_signals', 0))}, open={int(shadow.get('open_signals', 0))}, "
                f"EV maker={float(shadow.get('ev_maker', 0.0)):.4f}"
            )
        lines.append(f"- **Main failure modes:** {', '.join(item.failure_modes) if item.failure_modes else 'none identified'}")
        lines.append(f"- **Last signal:** n/a — generated in latest cycle")
        lines.append("")
        return lines

    def _build_edge_summary(
        self,
        evaluations: list[HypothesisEvaluation],
        result_by_key: dict[str, BacktestResult],
        exploration: dict[str, Any],
    ) -> dict[str, Any]:
        validated: list[dict[str, Any]] = []
        candidates: list[dict[str, Any]] = []
        rejected_count = 0

        for item in evaluations:
            result = result_by_key.get(item.key)
            if result is None:
                continue
            if item.status == "rejected":
                rejected_count += 1
            if item.status == "promoted" and result.signals >= 300 and result.p_value < 0.01:
                validated.append(self._serialize_hypothesis(item, result))
            elif result.signals >= 100 and result.p_value < 0.05 and result.ev_taker > 0:
                candidates.append(self._serialize_hypothesis(item, result))

        watchlist: list[dict[str, Any]] = []
        for variant in exploration.get("variants") or []:
            if variant.get("gate_status") != "watch":
                continue
            metrics = variant.get("metrics", {})
            raw_signals = int(metrics.get("raw_signals", 0))
            resolved_signals = int(metrics.get("signals", 0))
            watchlist.append(
                {
                    "name": variant.get("label", "n/a"),
                    "family": exploration.get("hypothesis", "n/a"),
                    "status": variant.get("gate_status"),
                    "promotion_eligible": False,
                    "raw_signals": raw_signals,
                    "resolved_signals": resolved_signals,
                    "open_signals": max(raw_signals - resolved_signals, 0),
                    "fallback_ratio": float(metrics.get("fallback_ratio", 0.0)),
                    "gate_failures": list(variant.get("gate_failures", [])),
                }
            )

        return {
            "validated": validated,
            "candidates": candidates,
            "watchlist": watchlist,
            "rejected_hypotheses": rejected_count,
        }

    def _build_calibration_drift_summary(self, evaluations: list[HypothesisEvaluation]) -> dict[str, Any]:
        flagged: list[dict[str, Any]] = []
        for item in evaluations:
            signals = int(item.metrics.get("signals", 0))
            if signals <= 0:
                continue
            calibration_error = float(item.metrics.get("calibration_error", 0.0))
            if "Probability calibration drift" not in item.failure_modes and calibration_error <= 0.15:
                continue
            flagged.append(
                {
                    "name": item.name,
                    "calibration_error": calibration_error,
                    "failure_mode": "Probability calibration drift",
                }
            )

        flagged.sort(key=lambda row: row["calibration_error"], reverse=True)
        return {
            "warning_threshold": 0.15,
            "hard_fail_threshold": 0.20,
            "status": "drift_present" if flagged else "within_bounds",
            "flagged_hypotheses": flagged,
        }

    def _build_new_viable_strategies(
        self,
        evaluations: list[HypothesisEvaluation],
        result_by_key: dict[str, BacktestResult],
    ) -> list[dict[str, Any]]:
        viable: list[dict[str, Any]] = []
        for item in evaluations:
            result = result_by_key.get(item.key)
            if result is None:
                continue
            if result.signals < self.config.research.min_signals_candidate:
                continue
            if result.p_value >= 0.05 or result.ev_taker <= 0:
                continue
            viable.append(self._serialize_hypothesis(item, result))
        return viable

    def _load_structural_public_counts(self) -> dict[str, Any]:
        snapshot_path = self.report_root / "arb_empirical_snapshot.json"
        b1_audit_path = self.report_root / "b1_template_audit.json"
        payload: dict[str, Any] = {
            "source_artifact": str(snapshot_path),
            "source_generated_at": None,
            "a6": {
                "status": None,
                "allowed_neg_risk_event_count": None,
                "executable_constructions_below_threshold": None,
                "execute_threshold": None,
                "blocked_reasons": [],
            },
            "b1": {
                "status": None,
                "allowed_market_sample_size": None,
                "deterministic_template_pair_count": None,
                "template_market_counts": None,
                "blocked_reasons": [],
            },
        }

        snapshot = self._load_json(snapshot_path)
        if snapshot:
            repo_truth = snapshot.get("repo_truth", {})
            lane_status = snapshot.get("lane_status", {})
            a6_truth = repo_truth.get("public_a6_audit", {})
            b1_truth = repo_truth.get("public_b1_audit", {})
            a6_lane = lane_status.get("a6", {})
            b1_lane = lane_status.get("b1", {})
            payload["source_generated_at"] = snapshot.get("generated_at")
            payload["a6"] = {
                "status": a6_lane.get("status"),
                "allowed_neg_risk_event_count": a6_truth.get("allowed_neg_risk_event_count"),
                "executable_constructions_below_threshold": a6_truth.get("executable_constructions_below_threshold"),
                "execute_threshold": a6_truth.get("execute_threshold"),
                "blocked_reasons": list(a6_lane.get("blocked_reasons", [])),
            }
            payload["b1"] = {
                "status": b1_lane.get("status"),
                "allowed_market_sample_size": b1_truth.get("allowed_market_sample_size"),
                "deterministic_template_pair_count": b1_truth.get("deterministic_template_pair_count"),
                "template_market_counts": None,
                "blocked_reasons": list(b1_lane.get("blocked_reasons", [])),
            }

        b1_audit = self._load_json(b1_audit_path)
        if b1_audit:
            payload["b1"]["template_market_counts"] = dict(b1_audit.get("template_markets", {}))
            if payload["b1"]["deterministic_template_pair_count"] is None:
                payload["b1"]["deterministic_template_pair_count"] = len(b1_audit.get("template_pairs", []))

        return payload

    @staticmethod
    def _serialize_hypothesis(
        item: HypothesisEvaluation | None,
        result: BacktestResult | None,
    ) -> dict[str, Any] | None:
        if item is None or result is None:
            return None
        return {
            "name": item.name,
            "status": item.status,
            "score": item.score,
            "confidence": item.confidence,
            "signals": result.signals,
            "win_rate": result.win_rate,
            "ev_maker": result.ev_maker,
            "ev_taker": result.ev_taker,
            "p_value": result.p_value,
            "calibration_error": result.calibration_error,
        }

    @staticmethod
    def _load_json(path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            loaded = json.loads(path.read_text())
        except json.JSONDecodeError:
            return None
        return loaded if isinstance(loaded, dict) else None
