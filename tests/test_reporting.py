import tempfile
import unittest
import json
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
            report_root = Path(cfg.system.report_root)
            report_root.mkdir(parents=True, exist_ok=True)
            refresh_path = report_root / "pipeline_refresh_20260309T010557Z.json"
            refresh_path.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-03-09T01:05:57+00:00",
                        "instance_version": "2.8.0",
                        "system_status": "stopped",
                        "markets_pulled": 120,
                        "markets_under_24h": 22,
                        "markets_under_48h": 35,
                        "markets_in_price_window": 19,
                        "markets_in_allowed_categories": 5,
                        "threshold_sensitivity": {
                            "current": {"yes": 0.15, "no": 0.05, "tradeable": 5, "yes_reachable_markets": 3},
                            "aggressive": {"yes": 0.08, "no": 0.03, "tradeable": 14, "yes_reachable_markets": 8},
                            "wide_open": {"yes": 0.05, "no": 0.02, "tradeable": 18, "yes_reachable_markets": 11},
                        },
                        "category_snapshot": {
                            "politics": {"count": 5, "avg_yes_price": 0.44, "under_24h": 2},
                            "weather": {"count": 2, "avg_yes_price": 0.51, "under_24h": 1},
                            "economic": {"count": 3, "avg_yes_price": 0.47, "under_24h": 1},
                            "crypto": {"count": 8, "avg_yes_price": 0.50, "under_24h": 4},
                            "sports": {"count": 6, "avg_yes_price": 0.62, "under_24h": 0},
                            "other": {"count": 1, "avg_yes_price": 0.38, "under_24h": 0},
                        },
                        "a6_scan": {
                            "status": "blocked",
                            "allowed_events": 563,
                            "qualified": 57,
                            "executable": 0,
                            "blocked_reasons": ["public_audit_zero_executable_constructions_below_0.95_gate"],
                        },
                        "wallet_flow": {"ready": True, "scored_wallets": 80, "status": "ready"},
                        "reasoning": "Lower thresholds widen the theoretical universe, but no validated edge is promoted.",
                    }
                )
            )

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
            self.assertIn("## Threshold Sensitivity", text)
            self.assertIn("## Market Universe Snapshot", text)
            self.assertIn("## Wallet-Flow Status", text)
            self.assertIn("**System Status:** stopped", text)


if __name__ == "__main__":
    unittest.main()
