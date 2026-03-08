import tempfile
import unittest
from pathlib import Path

from src.config import AppConfig, SystemConfig
from src.hypothesis_manager import HypothesisEvaluation
from src.reporting import ReportWriter
from src.strategies.base import BacktestResult


class TestReporting(unittest.TestCase):
    def test_analysis_generation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = AppConfig(system=SystemConfig(report_root=str(Path(tmp) / "reports"), analysis_path=str(Path(tmp) / "FAST_TRADE_EDGE_ANALYSIS.md")))
            writer = ReportWriter(cfg)

            evals = [
                HypothesisEvaluation(
                    key="h1",
                    name="Hypothesis 1",
                    status="active",
                    confidence=0.6,
                    score=0.4,
                )
            ]
            results = {
                "h1": BacktestResult(
                    strategy="Hypothesis 1",
                    signals=120,
                    wins=70,
                    win_rate=70 / 120,
                    ev_maker=0.2,
                    ev_taker=0.1,
                    sharpe=0.3,
                    max_drawdown=5.0,
                    p_value=0.04,
                    calibration_error=0.1,
                    regime_decay=False,
                    kelly_fraction=0.1,
                    wilson_low=0.5,
                    wilson_high=0.65,
                )
            }

            writer.write_run_artifacts(
                run_ts=1_700_000_000,
                data_coverage={
                    "markets_15m": 10,
                    "resolved_15m": 8,
                    "markets_5m": 20,
                    "markets_4h": 2,
                    "btc_points": 1000,
                    "trade_records": 500,
                    "unique_wallets": 30,
                    "data_start": "2026-01-01T00:00:00+00:00",
                    "data_end": "2026-01-02T00:00:00+00:00",
                },
                evaluations=evals,
                result_by_key=results,
                model_competition=[],
                ml_candidates=[],
                reality_check={
                    "slippage_assumption": 0.005,
                    "spread_assumption": 0.02,
                    "maker_fill_assumption": 0.6,
                    "execution_delay": 2,
                    "data_quality_issues": [],
                    "edge_fake_risks": ["test"],
                },
                next_actions=["test action"],
                change_log=["test change"],
                recommendation="CONTINUE RESEARCH",
                reasoning="test reasoning",
            )

            text = Path(cfg.system.analysis_path).read_text()
            self.assertIn("# Fast Trade Edge Analysis", text)
            self.assertIn("## Current Recommendation", text)
            self.assertIn("## MODEL COMPETITION TABLE", text)


if __name__ == "__main__":
    unittest.main()
