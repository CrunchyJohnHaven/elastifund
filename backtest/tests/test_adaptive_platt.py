"""Tests for adaptive rolling Platt evaluation."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
import hashlib

from backtest.adaptive_platt import (
    STATIC_PLATT_A,
    STATIC_PLATT_B,
    ResolvedMarket,
    evaluate_adaptive_platt,
    load_resolved_markets,
    rolling_platt_fit,
)


def _synthetic_samples(count: int) -> list[ResolvedMarket]:
    samples: list[ResolvedMarket] = []
    levels = [0.18, 0.27, 0.39, 0.48, 0.52, 0.61, 0.73, 0.84]
    for idx in range(count):
        raw_prob = levels[idx % len(levels)]
        true_prob = min(0.95, max(0.05, raw_prob * 0.85 + 0.03))
        outcome = 1 if ((idx * 37) % 100) < int(true_prob * 100) else 0
        month = 1 + (idx // 28)
        day = 1 + (idx % 28)
        end_date = f"2024-{month:02d}-{day:02d}T00:00:00Z"
        samples.append(
            ResolvedMarket(
                question=f"Q{idx}",
                raw_prob=raw_prob,
                outcome=outcome,
                end_date=end_date,
                original_index=idx,
            )
        )
    return samples


class TestRollingPlattFit(unittest.TestCase):
    def test_returns_static_when_history_too_small(self):
        params = rolling_platt_fit(_synthetic_samples(25), window=50, min_samples=50)
        self.assertEqual(params, (STATIC_PLATT_A, STATIC_PLATT_B))

    def test_refits_when_enough_history_exists(self):
        a, b = rolling_platt_fit(_synthetic_samples(140), window=100, min_samples=50)
        self.assertIsInstance(a, float)
        self.assertIsInstance(b, float)
        self.assertGreater(abs(a - STATIC_PLATT_A) + abs(b - STATIC_PLATT_B), 1e-3)


class TestAdaptiveEvaluation(unittest.TestCase):
    def test_report_contains_static_and_rolling_variants(self):
        report = evaluate_adaptive_platt(
            _synthetic_samples(160),
            train_size=100,
            windows=(50, 100),
            min_samples=50,
        )
        variant_names = {row["name"] for row in report["variants"]}
        self.assertEqual(report["dataset"]["train_size"], 100)
        self.assertEqual(report["dataset"]["validation_size"], 60)
        self.assertIn("static", variant_names)
        self.assertIn("rolling_50", variant_names)
        self.assertIn("rolling_100", variant_names)
        self.assertIn(report["winner"], variant_names)


class TestLoadResolvedMarkets(unittest.TestCase):
    def test_missing_dates_are_sorted_last(self):
        markets_payload = {
            "markets": [
                {
                    "question": "Later dated",
                    "actual_outcome": "YES_WON",
                    "end_date": "2024-01-03T00:00:00Z",
                },
                {
                    "question": "Missing date",
                    "actual_outcome": "NO_WON",
                    "end_date": None,
                },
                {
                    "question": "Earlier dated",
                    "actual_outcome": "YES_WON",
                    "end_date": "2024-01-01T00:00:00Z",
                },
            ]
        }
        cache_payload = {
            hashlib.sha256("Later dated".encode()).hexdigest()[:16]: {"probability": 0.70},
            hashlib.sha256("Missing date".encode()).hexdigest()[:16]: {"probability": 0.40},
            hashlib.sha256("Earlier dated".encode()).hexdigest()[:16]: {"probability": 0.65},
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            markets_path = os.path.join(tmpdir, "markets.json")
            cache_path = os.path.join(tmpdir, "cache.json")
            with open(markets_path, "w") as f:
                json.dump(markets_payload, f)
            with open(cache_path, "w") as f:
                json.dump(cache_payload, f)

            resolved = load_resolved_markets(markets_path, cache_path)

        self.assertEqual(
            [sample.question for sample in resolved],
            ["Earlier dated", "Later dated", "Missing date"],
        )


if __name__ == "__main__":
    unittest.main()
