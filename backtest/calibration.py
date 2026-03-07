"""Out-of-sample calibration system for Claude probability estimates.

Implements:
- Platt scaling (logistic regression) fitted on training split
- Isotonic regression (PAVA) fitted on training split
- Evaluation on held-out test split to avoid overfitting
- Confidence-weighted sizing based on training bucket sample counts
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import random
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

RANDOM_SEED = 42


@dataclass
class CalibrationSample:
    question: str
    raw_prob: float
    actual_binary: float  # 1.0 = YES_WON, 0.0 = NO_WON
    confidence: str


@dataclass
class CalibrationResult:
    method: str
    brier_before: float
    brier_after: float
    improvement: float
    n_train: int
    n_test: int
    bucket_stats: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Platt Scaling (logistic regression calibration)
# ---------------------------------------------------------------------------

class PlattScaler:
    """Platt scaling: fits P(y=1 | s) = 1 / (1 + exp(A*logit(s) + B)).

    Uses logit-transform of raw probabilities as input features,
    which is the standard approach when calibrating probability outputs.
    """

    def __init__(self):
        self.A = 1.0
        self.B = 0.0
        self._fitted = False

    @staticmethod
    def _logit(p: np.ndarray) -> np.ndarray:
        """Safe logit transform."""
        p = np.clip(p, 0.001, 0.999)
        return np.log(p / (1 - p))

    @staticmethod
    def _logit_scalar(p: float) -> float:
        """Safe logit transform for scalar."""
        p = max(0.001, min(0.999, p))
        return math.log(p / (1 - p))

    def fit(self, raw_probs: np.ndarray, labels: np.ndarray, max_iter: int = 500, lr: float = 0.05):
        """Fit Platt scaling parameters A, B via gradient descent on NLL.

        Input: logit(raw_prob) — transforms probabilities to log-odds space.
        Uses the Platt (1999) target encoding to avoid overfitting:
        t+ = (N+ + 1) / (N+ + 2), t- = 1 / (N- + 2)
        """
        n = len(raw_probs)
        n_pos = labels.sum()
        n_neg = n - n_pos

        # Transform probabilities to logits
        features = self._logit(raw_probs)

        # Platt target encoding
        t_pos = (n_pos + 1.0) / (n_pos + 2.0)
        t_neg = 1.0 / (n_neg + 2.0)
        targets = np.where(labels > 0.5, t_pos, t_neg)

        # Initialize A=1 (identity in logit space), B=0
        A = 1.0
        B = 0.0

        for iteration in range(max_iter):
            logits = A * features + B
            logits = np.clip(logits, -30, 30)
            preds = 1.0 / (1.0 + np.exp(-logits))
            preds = np.clip(preds, 1e-10, 1 - 1e-10)

            errors = preds - targets
            grad_A = np.mean(errors * features)
            grad_B = np.mean(errors)

            A -= lr * grad_A
            B -= lr * grad_B

            if iteration % 100 == 0:
                nll = -np.mean(targets * np.log(preds) + (1 - targets) * np.log(1 - preds))
                logger.debug(f"Platt iter {iteration}: NLL={nll:.4f}, A={A:.4f}, B={B:.4f}")

        self.A = A
        self.B = B
        self._fitted = True
        logger.info(f"Platt scaling fitted: A={A:.4f}, B={B:.4f} (logit-space)")

    def transform(self, raw_prob: float) -> float:
        """Apply Platt scaling to a single probability."""
        if not self._fitted:
            return raw_prob
        logit_input = self._logit_scalar(raw_prob)
        logit = self.A * logit_input + self.B
        logit = max(-30, min(30, logit))
        calibrated = 1.0 / (1.0 + math.exp(-logit))
        return max(0.01, min(0.99, calibrated))

    def transform_array(self, raw_probs: np.ndarray) -> np.ndarray:
        """Apply Platt scaling to an array."""
        if not self._fitted:
            return raw_probs
        features = self._logit(raw_probs)
        logits = self.A * features + self.B
        logits = np.clip(logits, -30, 30)
        calibrated = 1.0 / (1.0 + np.exp(-logits))
        return np.clip(calibrated, 0.01, 0.99)


# ---------------------------------------------------------------------------
# Isotonic Regression (Pool Adjacent Violators)
# ---------------------------------------------------------------------------

class IsotonicCalibrator:
    """Isotonic regression calibration using PAVA."""

    def __init__(self):
        self._x_points: list[float] = []
        self._y_points: list[float] = []
        self._fitted = False

    def fit(self, raw_probs: np.ndarray, labels: np.ndarray, n_bins: int = 15):
        """Fit isotonic regression by binning then applying PAVA.

        Uses more bins than the old 10-bucket approach for finer granularity.
        """
        # Sort by raw probability
        order = np.argsort(raw_probs)
        sorted_probs = raw_probs[order]
        sorted_labels = labels[order]

        # Bin into n_bins equal-width bins
        bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
        bin_midpoints = []
        bin_means = []
        bin_weights = []

        for i in range(n_bins):
            mask = (sorted_probs >= bin_edges[i]) & (sorted_probs < bin_edges[i + 1])
            if i == n_bins - 1:
                mask = (sorted_probs >= bin_edges[i]) & (sorted_probs <= bin_edges[i + 1])

            if mask.sum() > 0:
                bin_midpoints.append(sorted_probs[mask].mean())
                bin_means.append(sorted_labels[mask].mean())
                bin_weights.append(float(mask.sum()))

        if len(bin_midpoints) < 2:
            logger.warning("Isotonic: too few bins with data, using identity")
            self._x_points = [0.0, 1.0]
            self._y_points = [0.0, 1.0]
            self._fitted = True
            return

        # PAVA (Pool Adjacent Violators Algorithm) for isotonic regression
        x = list(bin_midpoints)
        y = list(bin_means)
        w = list(bin_weights)
        n = len(y)

        i = 0
        while i < n - 1:
            if y[i] > y[i + 1]:
                # Pool i and i+1
                combined_y = (y[i] * w[i] + y[i + 1] * w[i + 1]) / (w[i] + w[i + 1])
                combined_x = (x[i] * w[i] + x[i + 1] * w[i + 1]) / (w[i] + w[i + 1])
                combined_w = w[i] + w[i + 1]

                y[i] = combined_y
                x[i] = combined_x
                w[i] = combined_w

                y.pop(i + 1)
                x.pop(i + 1)
                w.pop(i + 1)
                n -= 1

                # Check backwards
                if i > 0:
                    i -= 1
            else:
                i += 1

        self._x_points = x
        self._y_points = y
        self._fitted = True

        logger.info(f"Isotonic calibration fitted with {len(x)} knots: "
                     f"{list(zip([round(xi, 3) for xi in x], [round(yi, 3) for yi in y]))}")

    def transform(self, raw_prob: float) -> float:
        """Apply isotonic calibration with linear interpolation."""
        if not self._fitted:
            return raw_prob

        raw_prob = max(0.01, min(0.99, raw_prob))

        if raw_prob <= self._x_points[0]:
            return max(0.01, min(0.99, self._y_points[0]))
        if raw_prob >= self._x_points[-1]:
            return max(0.01, min(0.99, self._y_points[-1]))

        for i in range(len(self._x_points) - 1):
            if self._x_points[i] <= raw_prob <= self._x_points[i + 1]:
                dx = self._x_points[i + 1] - self._x_points[i]
                if dx < 1e-10:
                    return max(0.01, min(0.99, self._y_points[i]))
                t = (raw_prob - self._x_points[i]) / dx
                val = self._y_points[i] + t * (self._y_points[i + 1] - self._y_points[i])
                return max(0.01, min(0.99, val))

        return raw_prob

    def transform_array(self, raw_probs: np.ndarray) -> np.ndarray:
        """Apply isotonic calibration to an array."""
        return np.array([self.transform(p) for p in raw_probs])


# ---------------------------------------------------------------------------
# Confidence-Weighted Sizing
# ---------------------------------------------------------------------------

class ConfidenceWeighter:
    """Assigns confidence multipliers based on training sample density per bucket."""

    def __init__(self, low_threshold: int = 10, high_threshold: int = 30, n_buckets: int = 10):
        self.low_threshold = low_threshold
        self.high_threshold = high_threshold
        self.n_buckets = n_buckets
        self._bucket_counts: list[int] = [0] * n_buckets
        self._fitted = False

    def fit(self, raw_probs: np.ndarray):
        """Count training samples per probability bucket."""
        self._bucket_counts = [0] * self.n_buckets
        for p in raw_probs:
            bucket = min(int(p * self.n_buckets), self.n_buckets - 1)
            self._bucket_counts[bucket] += 1
        self._fitted = True
        logger.info(f"Confidence weighter bucket counts: {self._bucket_counts}")

    def get_multiplier(self, raw_prob: float) -> float:
        """Get position sizing multiplier for a given raw probability.

        Returns:
            1.0 for high confidence (n > high_threshold)
            0.5 for low confidence (n < low_threshold)
            Linear interpolation between
        """
        if not self._fitted:
            return 1.0

        bucket = min(int(raw_prob * self.n_buckets), self.n_buckets - 1)
        n = self._bucket_counts[bucket]

        if n >= self.high_threshold:
            return 1.0
        elif n <= self.low_threshold:
            return 0.5
        else:
            # Linear interpolation
            return 0.5 + 0.5 * (n - self.low_threshold) / (self.high_threshold - self.low_threshold)

    def get_confidence_label(self, raw_prob: float) -> str:
        """Get human-readable confidence label."""
        mult = self.get_multiplier(raw_prob)
        if mult >= 0.9:
            return "high"
        elif mult >= 0.7:
            return "medium"
        else:
            return "low"


# ---------------------------------------------------------------------------
# Unified Calibration System (v2)
# ---------------------------------------------------------------------------

class CalibrationV2:
    """Out-of-sample calibration system with Platt + Isotonic + confidence weighting."""

    def __init__(self, method: str = "auto", train_ratio: float = 0.7, seed: int = RANDOM_SEED):
        self.method = method  # "platt", "isotonic", or "auto" (pick best on test set)
        self.train_ratio = train_ratio
        self.seed = seed

        self.platt = PlattScaler()
        self.isotonic = IsotonicCalibrator()
        self.weighter = ConfidenceWeighter()

        self._chosen_method: str = "platt"
        self._fitted = False
        self._results: Optional[dict] = None

    def fit_from_data(self, samples: list[CalibrationSample]) -> dict:
        """Fit calibration on train split, evaluate on test split.

        Returns dict with comparison metrics.
        """
        # Deterministic shuffle
        rng = random.Random(self.seed)
        shuffled = list(samples)
        rng.shuffle(shuffled)

        # Stratified split: maintain outcome ratio in both sets
        yes_samples = [s for s in shuffled if s.actual_binary > 0.5]
        no_samples = [s for s in shuffled if s.actual_binary <= 0.5]

        n_yes_train = int(len(yes_samples) * self.train_ratio)
        n_no_train = int(len(no_samples) * self.train_ratio)

        train = yes_samples[:n_yes_train] + no_samples[:n_no_train]
        test = yes_samples[n_yes_train:] + no_samples[n_no_train:]

        # Shuffle train/test again for good measure
        rng.shuffle(train)
        rng.shuffle(test)

        logger.info(f"Split: {len(train)} train ({len([s for s in train if s.actual_binary > 0.5])} YES), "
                     f"{len(test)} test ({len([s for s in test if s.actual_binary > 0.5])} YES)")

        # Extract arrays
        train_probs = np.array([s.raw_prob for s in train])
        train_labels = np.array([s.actual_binary for s in train])
        test_probs = np.array([s.raw_prob for s in test])
        test_labels = np.array([s.actual_binary for s in test])

        # Fit both methods on TRAIN set
        self.platt.fit(train_probs, train_labels)
        self.isotonic.fit(train_probs, train_labels)
        self.weighter.fit(train_probs)

        # Evaluate on TEST set
        brier_raw_test = float(np.mean((test_probs - test_labels) ** 2))

        platt_test_probs = self.platt.transform_array(test_probs)
        brier_platt_test = float(np.mean((platt_test_probs - test_labels) ** 2))

        iso_test_probs = self.isotonic.transform_array(test_probs)
        brier_iso_test = float(np.mean((iso_test_probs - test_labels) ** 2))

        # Also evaluate on TRAIN set (for comparison / overfit detection)
        brier_raw_train = float(np.mean((train_probs - train_labels) ** 2))

        platt_train_probs = self.platt.transform_array(train_probs)
        brier_platt_train = float(np.mean((platt_train_probs - train_labels) ** 2))

        iso_train_probs = self.isotonic.transform_array(train_probs)
        brier_iso_train = float(np.mean((iso_train_probs - train_labels) ** 2))

        # Pick best method on TEST set
        if self.method == "auto":
            if brier_platt_test <= brier_iso_test:
                self._chosen_method = "platt"
            else:
                self._chosen_method = "isotonic"
        else:
            self._chosen_method = self.method

        # Compute bucket-level calibration stats on TEST set
        bucket_stats = self._compute_bucket_stats(test_probs, test_labels)
        train_bucket_stats = self._compute_bucket_stats(train_probs, train_labels)

        self._fitted = True
        self._results = {
            "n_total": len(samples),
            "n_train": len(train),
            "n_test": len(test),
            "chosen_method": self._chosen_method,
            "train_set": {
                "brier_raw": round(brier_raw_train, 4),
                "brier_platt": round(brier_platt_train, 4),
                "brier_isotonic": round(brier_iso_train, 4),
                "bucket_stats": train_bucket_stats,
            },
            "test_set": {
                "brier_raw": round(brier_raw_test, 4),
                "brier_platt": round(brier_platt_test, 4),
                "brier_isotonic": round(brier_iso_test, 4),
                "bucket_stats": bucket_stats,
            },
            "improvement": {
                "platt_vs_raw": round(brier_raw_test - brier_platt_test, 4),
                "isotonic_vs_raw": round(brier_raw_test - brier_iso_test, 4),
                "best_vs_raw": round(brier_raw_test - min(brier_platt_test, brier_iso_test), 4),
            },
            "platt_params": {"A": round(self.platt.A, 4), "B": round(self.platt.B, 4)},
            "confidence_weighter": {
                "bucket_counts": self.weighter._bucket_counts,
            },
        }

        return self._results

    def correct(self, raw_prob: float) -> float:
        """Apply the chosen calibration method."""
        if not self._fitted:
            return raw_prob

        if self._chosen_method == "platt":
            return self.platt.transform(raw_prob)
        else:
            return self.isotonic.transform(raw_prob)

    def get_sizing_multiplier(self, raw_prob: float) -> float:
        """Get confidence-weighted sizing multiplier."""
        return self.weighter.get_multiplier(raw_prob)

    def _compute_bucket_stats(self, probs: np.ndarray, labels: np.ndarray,
                               n_buckets: int = 10) -> dict:
        """Compute per-bucket calibration statistics."""
        stats = {}
        for i in range(n_buckets):
            lo = i / n_buckets
            hi = (i + 1) / n_buckets
            key = f"{lo:.1f}-{hi:.1f}"

            if i < n_buckets - 1:
                mask = (probs >= lo) & (probs < hi)
            else:
                mask = (probs >= lo) & (probs <= hi)

            n = int(mask.sum())
            if n > 0:
                actual_rate = float(labels[mask].mean())
                midpoint = float(probs[mask].mean())
                stats[key] = {
                    "count": n,
                    "actual_yes_rate": round(actual_rate, 4),
                    "avg_raw_prob": round(midpoint, 4),
                    "error": round(midpoint - actual_rate, 4),
                }
            else:
                stats[key] = {"count": 0, "actual_yes_rate": None, "avg_raw_prob": None, "error": None}

        return stats


# ---------------------------------------------------------------------------
# Data Loading
# ---------------------------------------------------------------------------

def load_calibration_samples() -> list[CalibrationSample]:
    """Load all 532 markets + Claude cache into CalibrationSample list."""
    markets_path = os.path.join(DATA_DIR, "historical_markets.json")
    cache_path = os.path.join(DATA_DIR, "claude_cache.json")

    with open(markets_path) as f:
        markets = json.load(f)["markets"]
    with open(cache_path) as f:
        cache = json.load(f)

    samples = []
    for m in markets:
        question = m["question"]
        key = hashlib.sha256(question.encode()).hexdigest()[:16]
        est = cache.get(key)
        if not est:
            continue

        actual_binary = 1.0 if m["actual_outcome"] == "YES_WON" else 0.0
        samples.append(CalibrationSample(
            question=question,
            raw_prob=est["probability"],
            actual_binary=actual_binary,
            confidence=est.get("confidence", "medium"),
        ))

    logger.info(f"Loaded {len(samples)} calibration samples "
                f"({sum(1 for s in samples if s.actual_binary > 0.5)} YES, "
                f"{sum(1 for s in samples if s.actual_binary <= 0.5)} NO)")
    return samples


# ---------------------------------------------------------------------------
# Legacy API compatibility
# ---------------------------------------------------------------------------

class CalibrationCorrector:
    """Drop-in replacement for the old CalibrationCorrector.

    Uses CalibrationV2 under the hood with Platt scaling.
    """

    def __init__(self):
        self._v2 = CalibrationV2(method="auto")
        samples = load_calibration_samples()
        self._v2.fit_from_data(samples)
        self._results = self._v2._results

    def correct(self, raw_prob: float) -> float:
        return self._v2.correct(raw_prob)

    def get_sizing_multiplier(self, raw_prob: float) -> float:
        return self._v2.get_sizing_multiplier(raw_prob)

    def print_mapping(self):
        """Print calibration details."""
        r = self._results
        if not r:
            print("No results available")
            return

        print(f"\n{'='*70}")
        print("  CALIBRATION V2 — OUT-OF-SAMPLE VALIDATION")
        print(f"{'='*70}")
        print(f"  Chosen method: {r['chosen_method'].upper()}")
        print(f"  Train/Test split: {r['n_train']}/{r['n_test']}")

        if r['chosen_method'] == 'platt':
            print(f"  Platt params: A={r['platt_params']['A']:.4f}, B={r['platt_params']['B']:.4f}")

        print(f"\n  TRAIN SET:")
        print(f"    Brier (raw):      {r['train_set']['brier_raw']:.4f}")
        print(f"    Brier (platt):    {r['train_set']['brier_platt']:.4f}")
        print(f"    Brier (isotonic): {r['train_set']['brier_isotonic']:.4f}")

        print(f"\n  TEST SET (out-of-sample):")
        print(f"    Brier (raw):      {r['test_set']['brier_raw']:.4f}")
        print(f"    Brier (platt):    {r['test_set']['brier_platt']:.4f}")
        print(f"    Brier (isotonic): {r['test_set']['brier_isotonic']:.4f}")

        print(f"\n  IMPROVEMENT (test set):")
        print(f"    Platt vs raw:     {r['improvement']['platt_vs_raw']:+.4f}")
        print(f"    Isotonic vs raw:  {r['improvement']['isotonic_vs_raw']:+.4f}")
        print(f"    Best vs raw:      {r['improvement']['best_vs_raw']:+.4f}")

        # Confidence weighting
        print(f"\n  CONFIDENCE WEIGHTER (training bucket counts):")
        for i, count in enumerate(r['confidence_weighter']['bucket_counts']):
            lo = i / 10
            hi = (i + 1) / 10
            mult = self._v2.weighter.get_multiplier(lo + 0.05)
            label = self._v2.weighter.get_confidence_label(lo + 0.05)
            print(f"    [{lo:.1f}-{hi:.1f}]: n={count:3d}, multiplier={mult:.2f} ({label})")

        # Test set calibration table
        print(f"\n  TEST SET CALIBRATION TABLE:")
        print(f"    {'Bucket':>10s}  {'N':>4s}  {'Avg Raw':>8s}  {'Actual':>8s}  {'Error':>8s}")
        for bucket, stats in r['test_set']['bucket_stats'].items():
            if stats['count'] > 0:
                print(f"    {bucket:>10s}  {stats['count']:4d}  "
                      f"{stats['avg_raw_prob']:8.3f}  {stats['actual_yes_rate']:8.3f}  "
                      f"{stats['error']:+8.3f}")

        print(f"{'='*70}")


# ---------------------------------------------------------------------------
# Standalone run
# ---------------------------------------------------------------------------

def run_calibrated_backtest():
    """Re-run backtest with calibration v2 and produce comprehensive results."""
    import hashlib
    import time

    samples = load_calibration_samples()

    # Run calibration with out-of-sample validation
    cal = CalibrationV2(method="auto")
    fit_results = cal.fit_from_data(samples)

    # Print results
    corrector = CalibrationCorrector.__new__(CalibrationCorrector)
    corrector._v2 = cal
    corrector._results = fit_results
    corrector.correct = cal.correct
    corrector.get_sizing_multiplier = cal.get_sizing_multiplier
    corrector.print_mapping()

    # Run strategy variant comparison
    from strategy_variants import load_data, simulate_strategy
    markets, cache = load_data()

    variant_configs = {
        "baseline_5pct": {"yes_threshold": 0.05, "no_threshold": 0.05, "entry_price": 0.50},
        "no_only": {"yes_threshold": 999.0, "no_threshold": 0.05, "entry_price": 0.50},
        "asymmetric_15_5": {"yes_threshold": 0.15, "no_threshold": 0.05, "entry_price": 0.50},
        "calibrated_v2": {
            "yes_threshold": 0.05, "no_threshold": 0.05, "entry_price": 0.50,
            "use_calibration": True, "calibrator": corrector,
        },
        "calibrated_v2_no_only": {
            "yes_threshold": 999.0, "no_threshold": 0.05, "entry_price": 0.50,
            "use_calibration": True, "calibrator": corrector,
        },
        "calibrated_v2_asymmetric": {
            "yes_threshold": 0.15, "no_threshold": 0.05, "entry_price": 0.50,
            "use_calibration": True, "calibrator": corrector,
        },
        "calibrated_v2_confidence": {
            "yes_threshold": 0.05, "no_threshold": 0.05, "entry_price": 0.50,
            "use_calibration": True, "calibrator": corrector,
            "use_confidence_sizing": True,
        },
        "calibrated_v2_asym_confidence": {
            "yes_threshold": 0.15, "no_threshold": 0.05, "entry_price": 0.50,
            "use_calibration": True, "calibrator": corrector,
            "use_confidence_sizing": True,
        },
    }

    variant_results = {}
    for name, config in variant_configs.items():
        variant_results[name] = simulate_strategy(markets, cache, config)

    # Build comprehensive output
    comprehensive = {
        "run_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "calibration": fit_results,
        "strategy_variants": variant_results,
        "comparison": {
            "old_brier_full_dataset": 0.2391,
            "new_brier_full_dataset_calibrated": variant_results["calibrated_v2"]["brier"],
            "brier_improvement_full": round(0.2391 - variant_results["calibrated_v2"]["brier"], 4),
            "old_brier_test_set": fit_results["test_set"]["brier_raw"],
            "new_brier_test_set_platt": fit_results["test_set"]["brier_platt"],
            "new_brier_test_set_isotonic": fit_results["test_set"]["brier_isotonic"],
            "brier_improvement_test_set": fit_results["improvement"]["best_vs_raw"],
            "old_win_rate": variant_results["baseline_5pct"]["win_rate"],
            "new_win_rate_calibrated": variant_results["calibrated_v2"]["win_rate"],
            "win_rate_improvement": round(
                variant_results["calibrated_v2"]["win_rate"] - variant_results["baseline_5pct"]["win_rate"], 4
            ),
        },
        "calibration_map_v2": {
            "method": fit_results["chosen_method"],
            "platt_A": fit_results["platt_params"]["A"],
            "platt_B": fit_results["platt_params"]["B"],
            "sample_mappings": {
                f"{p:.2f}": round(cal.correct(p), 3)
                for p in [0.05, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 0.95]
            },
        },
    }

    # Save comprehensive results
    out_path = os.path.join(DATA_DIR, "calibration_v2_results.json")
    with open(out_path, "w") as f:
        json.dump(comprehensive, f, indent=2)
    logger.info(f"Saved comprehensive calibration v2 results to {out_path}")

    return cal


if __name__ == "__main__":
    run_calibrated_backtest()
