#!/usr/bin/env python3
"""Tests for adaptive Platt calibration helpers."""

import json
import os
import tempfile
import unittest
from pathlib import Path

from bot.adaptive_platt import (
    STATIC_PLATT_A,
    STATIC_PLATT_B,
    PlattCalibrator,
    ResolvedExample,
    brier_score,
    calibrate_probability_with_params,
    fit_platt_parameters,
    load_resolved_history,
    question_cache_key,
    rolling_platt_fit,
    write_comparison_report,
)


class TestAdaptivePlatt(unittest.TestCase):
    def test_fit_platt_parameters_recovers_near_identity_on_perfectly_calibrated_data(self):
        raw_probs = []
        outcomes = []
        for bucket in range(1, 10):
            probability = bucket / 10.0
            yes_count = bucket * 10
            no_count = 100 - yes_count
            raw_probs.extend([probability] * 100)
            outcomes.extend([1] * yes_count + [0] * no_count)

        a_value, b_value = fit_platt_parameters(
            raw_probs,
            outcomes,
            initial_a=0.4,
            initial_b=-0.2,
            l2=0.0,
            max_iter=500,
        )

        self.assertAlmostEqual(a_value, 1.0, delta=0.15)
        self.assertAlmostEqual(b_value, 0.0, delta=0.15)

    def test_rolling_platt_fit_uses_only_most_recent_window(self):
        rows = [
            ResolvedExample(
                market_id=str(idx),
                question=f"Q{idx}?",
                resolved_at=f"2026-03-{idx + 1:02d}",
                raw_prob=0.85 if idx < 20 else 0.25,
                outcome=0 if idx < 20 else 1,
                source="test",
            )
            for idx in range(40)
        ]

        expected = fit_platt_parameters(
            [row.raw_prob for row in rows[-10:]],
            [row.outcome for row in rows[-10:]],
            initial_a=0.6,
            initial_b=-0.1,
            min_samples=5,
            max_iter=200,
        )
        observed = rolling_platt_fit(
            rows,
            window=10,
            initial_a=0.6,
            initial_b=-0.1,
            min_samples=5,
            max_iter=200,
        )

        self.assertAlmostEqual(observed[0], expected[0], places=9)
        self.assertAlmostEqual(observed[1], expected[1], places=9)

        rolling_prob = calibrate_probability_with_params(0.25, observed[0], observed[1])
        full_prob = calibrate_probability_with_params(
            0.25,
            *fit_platt_parameters(
                [row.raw_prob for row in rows],
                [row.outcome for row in rows],
                initial_a=0.6,
                initial_b=-0.1,
                min_samples=5,
                max_iter=200,
            ),
        )
        self.assertGreater(abs(rolling_prob - full_prob), 0.2)

    def test_brier_score_matches_manual_calculation(self):
        predictions = [0.25, 0.75, 0.50]
        outcomes = [0, 1, 1]
        expected = (0.25**2 + 0.25**2 + 0.50**2) / 3.0
        self.assertAlmostEqual(brier_score(predictions, outcomes), expected, places=9)

    def test_load_resolved_history_falls_back_to_cache_with_most_matches(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            markets_path = os.path.join(temp_dir, "historical_markets.json")
            ensemble_cache_path = os.path.join(temp_dir, "ensemble_cache.json")
            claude_cache_path = os.path.join(temp_dir, "claude_cache.json")

            questions = ["Will A happen?", "Will B happen?"]
            with open(markets_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "markets": [
                            {
                                "id": "m1",
                                "question": questions[0],
                                "actual_outcome": "YES_WON",
                                "end_date": "2026-03-01T00:00:00Z",
                            },
                            {
                                "id": "m2",
                                "question": questions[1],
                                "actual_outcome": "NO_WON",
                                "end_date": "2026-03-02T00:00:00Z",
                            },
                        ]
                    },
                    handle,
                )

            with open(ensemble_cache_path, "w", encoding="utf-8") as handle:
                json.dump({question_cache_key(questions[0]): {"probability": 0.61}}, handle)

            with open(claude_cache_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        question_cache_key(questions[0]): {"probability": 0.61},
                        question_cache_key(questions[1]): {"probability": 0.42},
                    },
                    handle,
                )

            rows, history_info = load_resolved_history(
                db_paths=(),
                markets_path=markets_path,
                cache_paths=(ensemble_cache_path, claude_cache_path),
            )

            self.assertEqual(len(rows), 2)
            self.assertEqual(history_info["source"], claude_cache_path)
            self.assertEqual(rows[0].market_id, "m1")
            self.assertEqual(rows[1].market_id, "m2")

    def test_platt_calibrator_falls_back_to_static_with_fewer_than_thirty_observations(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            calibrator = PlattCalibrator(
                Path(temp_dir) / "platt.db",
                enabled=True,
                min_observations=30,
                runtime_variant="rolling_100",
                state_path=Path(temp_dir) / "platt_state.json",
                report_path=Path(temp_dir) / "platt_report.md",
                report_json_path=Path(temp_dir) / "platt_report.json",
            )
            for idx in range(20):
                calibrator.add_observation(
                    raw_prob=0.65 if idx % 2 == 0 else 0.35,
                    outcome=1 if idx % 2 == 0 else 0,
                    trade_id=f"t-{idx}",
                    market_id=f"m-{idx}",
                    resolved_at=f"2026-03-{idx + 1:02d}T00:00:00Z",
                )

            changed = calibrator.refit()
            summary = calibrator.summary()

            self.assertFalse(changed)
            self.assertEqual(summary["active_mode"], "static")
            self.assertEqual(summary["a"], STATIC_PLATT_A)
            self.assertEqual(summary["b"], STATIC_PLATT_B)
            self.assertEqual(summary["samples"], 20)
            calibrator.close()

    def test_platt_calibrator_refit_produces_valid_parameters(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            calibrator = PlattCalibrator(
                Path(temp_dir) / "platt.db",
                enabled=True,
                min_observations=30,
                runtime_variant="rolling_100",
                state_path=Path(temp_dir) / "platt_state.json",
                report_path=Path(temp_dir) / "platt_report.md",
                report_json_path=Path(temp_dir) / "platt_report.json",
            )
            for idx in range(60):
                raw_prob = 0.82 if idx % 3 == 0 else (0.68 if idx % 3 == 1 else 0.24)
                outcome = 0 if idx % 3 == 0 else 1
                calibrator.add_observation(
                    raw_prob=raw_prob,
                    outcome=outcome,
                    trade_id=f"fit-{idx}",
                    market_id=f"m-{idx}",
                    resolved_at=f"2026-04-{(idx % 28) + 1:02d}T00:00:00Z",
                )

            changed = calibrator.refit()
            summary = calibrator.summary()

            self.assertTrue(changed)
            self.assertEqual(summary["active_mode"], "rolling_100")
            self.assertGreater(summary["samples"], 30)
            self.assertIsInstance(summary["a"], float)
            self.assertIsInstance(summary["b"], float)
            self.assertNotEqual((summary["a"], summary["b"]), (STATIC_PLATT_A, STATIC_PLATT_B))
            calibrator.close()

    def test_write_comparison_report_outputs_markdown_table(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            markets_path = temp_path / "historical_markets.json"
            cache_path = temp_path / "claude_cache.json"
            report_path = temp_path / "platt_comparison.md"
            json_path = temp_path / "platt_comparison.json"

            markets = []
            cache_payload = {}
            for idx in range(40):
                question = f"Will event {idx} happen?"
                raw_prob = 0.82 if idx % 2 == 0 else 0.22
                outcome = "YES_WON" if idx % 3 != 0 else "NO_WON"
                markets.append(
                    {
                        "id": f"m{idx}",
                        "question": question,
                        "actual_outcome": outcome,
                        "end_date": f"2026-05-{(idx % 28) + 1:02d}T00:00:00Z",
                    }
                )
                cache_payload[question_cache_key(question)] = {"probability": raw_prob}

            markets_path.write_text(json.dumps({"markets": markets}), encoding="utf-8")
            cache_path.write_text(json.dumps(cache_payload), encoding="utf-8")

            comparison = write_comparison_report(
                report_path=report_path,
                json_path=json_path,
                db_paths=(),
                markets_path=markets_path,
                cache_paths=(cache_path,),
                min_samples=30,
            )
            report_text = report_path.read_text(encoding="utf-8")

            self.assertIn("| Variant | Window | Predictions | Fallbacks | Brier |", report_text)
            self.assertIn("static", report_text)
            self.assertIn("expanding", report_text)
            self.assertIn("rolling_100", report_text)
            self.assertIn("rolling_200", report_text)
            self.assertEqual(comparison["dataset_size"], 40)
            self.assertTrue(json_path.exists())


if __name__ == "__main__":
    unittest.main()
