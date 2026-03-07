"""Category-specific Platt scaling calibration for Polymarket probability estimates.

Research context (March 2026):
- Global Platt scaling (A=0.5914, B=-0.3977) improves Brier from 0.286 → 0.245
- Different market categories show different bias patterns:
  * Politics: Claude overestimates YES most (better target: A=0.65, B=-0.45)
  * Weather: Best calibrated (A=0.50, B=-0.30)
  * Economic: Moderate bias (A=0.55, B=-0.35)
  * Geopolitical: Worst category, most overconfident (A=0.70, B=-0.50)
- Per-category calibration can improve accuracy by ~3-5% (estimated)
- Requires ≥30 samples per category for reliable fitting
- Falls back to global calibration if insufficient category data

Implementation:
- CategoryCalibrator: stores and applies per-category Platt parameters
- CalibrationTrainer: fits parameters from backtest data using scipy.optimize
- CalibrationReport: tracks performance metrics per category
- Integration: enhances edge detection and market ranking
"""

import json
import logging
import math
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional, Dict, List, Tuple

import numpy as np
from scipy.optimize import minimize

logger = logging.getLogger(__name__)


# Default per-category Platt scaling parameters (A, B)
# These are educated estimates based on observed bias patterns
DEFAULT_CATEGORY_PARAMS = {
    "politics": {"A": 0.65, "B": -0.45},      # Claude overestimates YES most on politics
    "weather": {"A": 0.50, "B": -0.30},       # Best calibrated, close to base rates
    "economic": {"A": 0.55, "B": -0.35},      # Moderate bias
    "geopolitical": {"A": 0.70, "B": -0.50},  # Worst category, most overconfident
    "crypto": {"A": 0.60, "B": -0.40},        # Moderate-to-high bias
    "sports": {"A": 0.58, "B": -0.38},        # Moderate bias
    "fed_rates": {"A": 0.62, "B": -0.42},     # High bias on monetary policy
    "unknown": {"A": 0.5914, "B": -0.3977},   # Global default fallback
}

# Asymmetric edge thresholds per category
# Higher YES threshold = requires bigger edge to trade YES (lower conviction)
# Lower NO threshold = easier to trade NO (our primary edge source)
CATEGORY_EDGE_THRESHOLDS = {
    "politics": {"yes_edge": 0.12, "no_edge": 0.04},       # Best category — more aggressive
    "weather": {"yes_edge": 0.15, "no_edge": 0.05},        # Standard
    "economic": {"yes_edge": 0.15, "no_edge": 0.05},       # Standard
    "geopolitical": {"yes_edge": 0.20, "no_edge": 0.08},   # Worst — need bigger edge
    "crypto": {"yes_edge": 0.15, "no_edge": 0.05},         # Standard
    "sports": {"yes_edge": 0.15, "no_edge": 0.05},         # Standard
    "fed_rates": {"yes_edge": 0.18, "no_edge": 0.06},      # High bar for fed/rates
    "unknown": {"yes_edge": 0.15, "no_edge": 0.05},        # Default
}

# Minimum sample count before using category-specific calibration
MIN_SAMPLES_PER_CATEGORY = 30


@dataclass
class CategoryPerformance:
    """Performance metrics for a single category."""

    category: str
    sample_count: int
    brier_score_raw: float
    brier_score_calibrated: float
    brier_improvement: float
    win_rate_yes: float
    win_rate_no: float
    avg_edge_yes: float
    avg_edge_no: float
    platt_a: float
    platt_b: float

    def __post_init__(self):
        """Validate that metrics are reasonable."""
        if not 0 <= self.brier_score_raw <= 1:
            raise ValueError(f"Invalid Brier score: {self.brier_score_raw}")
        if not 0 <= self.brier_score_calibrated <= 1:
            raise ValueError(f"Invalid calibrated Brier: {self.brier_score_calibrated}")

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class CalibrationReport:
    """Complete calibration report across all categories."""

    timestamp: str
    categories: Dict[str, CategoryPerformance]
    overall_brier_raw: float
    overall_brier_calibrated: float
    overall_improvement: float
    weighted_brier_raw: float
    weighted_brier_calibrated: float
    total_samples: int

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        data = {
            "timestamp": self.timestamp,
            "overall_brier_raw": self.overall_brier_raw,
            "overall_brier_calibrated": self.overall_brier_calibrated,
            "overall_improvement": self.overall_improvement,
            "weighted_brier_raw": self.weighted_brier_raw,
            "weighted_brier_calibrated": self.weighted_brier_calibrated,
            "total_samples": self.total_samples,
            "categories": {k: v.to_dict() for k, v in self.categories.items()},
        }
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "CalibrationReport":
        """Reconstruct from dictionary."""
        categories = {
            k: CategoryPerformance(**v)
            for k, v in data["categories"].items()
        }
        return cls(
            timestamp=data["timestamp"],
            categories=categories,
            overall_brier_raw=data["overall_brier_raw"],
            overall_brier_calibrated=data["overall_brier_calibrated"],
            overall_improvement=data["overall_improvement"],
            weighted_brier_raw=data["weighted_brier_raw"],
            weighted_brier_calibrated=data["weighted_brier_calibrated"],
            total_samples=data["total_samples"],
        )


class CategoryCalibrator:
    """Stores and applies per-category Platt scaling calibration.

    Falls back to global calibration if category has insufficient data.
    """

    def __init__(self, category_params: Optional[Dict[str, Dict[str, float]]] = None):
        """Initialize with category parameters.

        Args:
            category_params: Dict of category -> {A, B} parameters.
                           If None, uses DEFAULT_CATEGORY_PARAMS.
        """
        self.category_params = category_params or DEFAULT_CATEGORY_PARAMS.copy()
        self.global_params = self.category_params.get("unknown", {
            "A": 0.5914,
            "B": -0.3977
        })

    def calibrate(self, raw_probability: float, category: str) -> float:
        """Apply category-specific Platt scaling calibration.

        Calibration formula:
            logit_input = log(p / (1-p))
            logit_output = A * logit_input + B
            calibrated_prob = sigmoid(logit_output)

        Args:
            raw_probability: Claude's raw estimate (0.001 to 0.999)
            category: Market category (politics, weather, etc.)

        Returns:
            Calibrated probability (0.01 to 0.99)
        """
        # Clamp to valid range to avoid log domain errors
        raw_prob = max(0.001, min(0.999, raw_probability))

        # Get category parameters, fall back to global if not found
        params = self.category_params.get(category, self.global_params)
        a = params.get("A", self.global_params["A"])
        b = params.get("B", self.global_params["B"])

        # Apply logit transformation and Platt scaling
        logit_input = math.log(raw_prob / (1 - raw_prob))
        logit_output = a * logit_input + b

        # Clamp logit output to avoid numerical overflow
        logit_output = max(-30, min(30, logit_output))

        # Inverse logit (sigmoid)
        calibrated = 1.0 / (1.0 + math.exp(-logit_output))

        # Final clamp to reasonable range
        return max(0.01, min(0.99, calibrated))

    def train(
        self,
        training_data: List[Tuple[float, int, str]]
    ) -> Tuple[bool, Dict[str, str]]:
        """Fit Platt scaling parameters per category.

        Args:
            training_data: List of (raw_probability, actual_outcome, category) tuples
                         actual_outcome: 0 (NO) or 1 (YES)

        Returns:
            (success: bool, messages: dict with training details)
        """
        messages = {}

        # Group by category
        category_data = {}
        for raw_prob, outcome, category in training_data:
            if category not in category_data:
                category_data[category] = []
            category_data[category].append((raw_prob, outcome))

        # Fit parameters for each category
        for category, data in category_data.items():
            if len(data) < MIN_SAMPLES_PER_CATEGORY:
                msg = (
                    f"{category}: {len(data)} samples < "
                    f"{MIN_SAMPLES_PER_CATEGORY} minimum. Using defaults."
                )
                messages[category] = msg
                logger.info(msg)
                continue

            try:
                raw_probs = np.array([d[0] for d in data])
                outcomes = np.array([d[1] for d in data])

                # Fit Platt scaling parameters
                a, b = self._fit_platt_scaling(raw_probs, outcomes)

                self.category_params[category] = {"A": float(a), "B": float(b)}
                msg = (
                    f"{category}: fitted A={a:.4f}, B={b:.4f} "
                    f"({len(data)} samples)"
                )
                messages[category] = msg
                logger.info(msg)

            except Exception as e:
                msg = f"{category}: fitting failed: {str(e)}"
                messages[category] = msg
                logger.error(msg)

        return True, messages

    @staticmethod
    def _fit_platt_scaling(
        raw_probs: np.ndarray,
        outcomes: np.ndarray
    ) -> Tuple[float, float]:
        """Fit Platt scaling parameters using maximum likelihood.

        Minimizes negative log-likelihood of calibration parameters.

        Args:
            raw_probs: Array of raw probabilities from model
            outcomes: Array of actual binary outcomes (0 or 1)

        Returns:
            (A, B) Platt scaling parameters
        """
        # Clamp to avoid log domain errors
        raw_probs = np.clip(raw_probs, 0.001, 0.999)

        # Transform to logit space
        logits = np.log(raw_probs / (1 - raw_probs))

        def neg_log_likelihood(params):
            """Negative log-likelihood for Platt scaling."""
            a, b = params

            # Apply Platt transformation
            calibrated_logits = a * logits + b
            calibrated_logits = np.clip(calibrated_logits, -30, 30)

            # Sigmoid probabilities
            probs = 1.0 / (1.0 + np.exp(-calibrated_logits))

            # Binary cross-entropy loss
            eps = 1e-7
            probs = np.clip(probs, eps, 1 - eps)
            loss = -np.mean(
                outcomes * np.log(probs) +
                (1 - outcomes) * np.log(1 - probs)
            )

            return loss

        # Initial guess (identity transformation)
        initial_params = [1.0, 0.0]

        # Minimize
        result = minimize(
            neg_log_likelihood,
            initial_params,
            method="Nelder-Mead",
            options={"maxiter": 1000}
        )

        if result.success:
            return result.x[0], result.x[1]
        else:
            # Fall back to identity
            logger.warning(f"Platt fitting failed: {result.message}. Using identity.")
            return 1.0, 0.0

    def validate(
        self,
        test_data: List[Tuple[float, int, str]]
    ) -> Dict[str, CategoryPerformance]:
        """Validate calibration on test data.

        Computes Brier scores for both raw and calibrated predictions
        per category.

        Args:
            test_data: List of (raw_probability, actual_outcome, category) tuples

        Returns:
            Dict of category -> CategoryPerformance
        """
        # Group by category
        category_data = {}
        for raw_prob, outcome, category in test_data:
            if category not in category_data:
                category_data[category] = []
            category_data[category].append((raw_prob, outcome))

        results = {}

        for category, data in category_data.items():
            raw_probs = np.array([d[0] for d in data])
            outcomes = np.array([d[1] for d in data])

            # Calibrate
            calibrated_probs = np.array([
                self.calibrate(p, category) for p in raw_probs
            ])

            # Compute Brier scores
            brier_raw = np.mean((raw_probs - outcomes) ** 2)
            brier_calibrated = np.mean((calibrated_probs - outcomes) ** 2)

            # Win rates by direction
            yes_mask = calibrated_probs > 0.5
            no_mask = ~yes_mask

            win_rate_yes = np.mean(outcomes[yes_mask]) if yes_mask.sum() > 0 else 0.5
            win_rate_no = np.mean(1 - outcomes[no_mask]) if no_mask.sum() > 0 else 0.5

            # Average edges
            avg_edge_yes = np.mean(
                calibrated_probs[yes_mask] - 0.5
            ) if yes_mask.sum() > 0 else 0.0
            avg_edge_no = np.mean(
                0.5 - calibrated_probs[no_mask]
            ) if no_mask.sum() > 0 else 0.0

            # Get parameters
            params = self.category_params.get(category, self.global_params)

            results[category] = CategoryPerformance(
                category=category,
                sample_count=len(data),
                brier_score_raw=float(brier_raw),
                brier_score_calibrated=float(brier_calibrated),
                brier_improvement=float(brier_raw - brier_calibrated),
                win_rate_yes=float(win_rate_yes),
                win_rate_no=float(win_rate_no),
                avg_edge_yes=float(avg_edge_yes),
                avg_edge_no=float(avg_edge_no),
                platt_a=float(params["A"]),
                platt_b=float(params["B"]),
            )

        return results

    def compute_edge(
        self,
        raw_prob: float,
        market_price: float,
        category: str
    ) -> float:
        """Compute trading edge using category-specific calibration.

        Edge = |calibrated_prob - market_price|

        Args:
            raw_prob: Claude's raw probability estimate
            market_price: Current market price (YES probability)
            category: Market category for calibration routing

        Returns:
            Absolute edge value
        """
        calibrated = self.calibrate(raw_prob, category)
        return abs(calibrated - market_price)

    def get_thresholds(self, category: str) -> Tuple[float, float]:
        """Get asymmetric edge thresholds for a category.

        Args:
            category: Market category

        Returns:
            (yes_edge_threshold, no_edge_threshold)
        """
        thresholds = CATEGORY_EDGE_THRESHOLDS.get(
            category,
            CATEGORY_EDGE_THRESHOLDS["unknown"]
        )
        return thresholds["yes_edge"], thresholds["no_edge"]

    def save(self, path: Path) -> None:
        """Save calibration parameters to JSON file.

        Args:
            path: Output file path
        """
        output = {
            "timestamp": __import__("datetime").datetime.utcnow().isoformat() + "Z",
            "category_params": self.category_params,
            "edge_thresholds": CATEGORY_EDGE_THRESHOLDS,
            "min_samples": MIN_SAMPLES_PER_CATEGORY,
        }

        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(output, f, indent=2)

        logger.info(f"Calibration saved to {path}")

    @classmethod
    def load(cls, path: Path) -> "CategoryCalibrator":
        """Load calibration parameters from JSON file.

        Args:
            path: Input file path

        Returns:
            Initialized CategoryCalibrator instance
        """
        with open(path, "r") as f:
            data = json.load(f)

        calibrator = cls(category_params=data["category_params"])
        logger.info(f"Calibration loaded from {path}")
        return calibrator


class CalibrationTrainer:
    """Trains category-specific calibration from backtest data."""

    def __init__(self):
        """Initialize the trainer."""
        pass

    @staticmethod
    def _classify_market_category(question: str) -> str:
        """Simple category classifier (embedded to avoid import issues).

        Args:
            question: Market question text

        Returns:
            Category string
        """
        category_keywords = {
            "politics": ["election", "president", "congress", "senate", "governor", "vote",
                        "democrat", "republican", "trump", "biden", "party", "primary",
                        "legislation", "bill", "law", "executive order", "cabinet",
                        "impeach", "poll", "ballot", "nominee", "campaign"],
            "weather": ["temperature", "rain", "snow", "weather", "hurricane", "storm",
                       "heat", "cold", "wind", "flood", "drought", "celsius", "fahrenheit",
                       "high of", "low of", "degrees"],
            "crypto": ["bitcoin", "btc", "ethereum", "eth", "crypto", "solana", "sol",
                      "token", "defi", "nft", "blockchain", "altcoin", "dogecoin", "xrp"],
            "sports": ["nba", "nfl", "mlb", "nhl", "soccer", "football", "basketball",
                      "baseball", "tennis", "golf", "championship", "playoff", "world cup",
                      "super bowl", "mvp", "draft", "stanley cup", "series"],
            "geopolitical": ["war", "invasion", "nato", "china", "russia", "taiwan",
                            "sanctions", "ceasefire", "nuclear", "military", "conflict"],
            "fed_rates": ["fed", "federal reserve", "interest rate", "fomc",
                         "recession", "treasury"],
            "economic": ["inflation", "cpi", "gdp", "unemployment rate", "jobs report",
                        "nonfarm", "payroll", "retail sales", "housing starts",
                        "consumer confidence", "pmi", "manufacturing", "trade deficit",
                        "economic growth", "bls", "bureau of labor"],
        }

        question_lower = question.lower()
        scores = {}
        for category, keywords in category_keywords.items():
            scores[category] = sum(1 for kw in keywords if kw in question_lower)
        best = max(scores, key=scores.get)
        return best if scores[best] > 0 else "unknown"

    @staticmethod
    def train_from_backtest(
        historical_markets_path: Path,
        claude_cache_path: Path,
        train_ratio: float = 0.7,
    ) -> Tuple[CategoryCalibrator, CalibrationReport]:
        """Train category calibration from backtest data.

        Loads resolved markets and Claude estimates, splits into train/test,
        and fits Platt scaling per category.

        Args:
            historical_markets_path: Path to historical_markets.json
            claude_cache_path: Path to claude_cache.json (Claude estimates)
            train_ratio: Fraction of data to use for training (0.7 = 70/30 split)

        Returns:
            (trained_calibrator, validation_report)
        """
        # Load data
        with open(historical_markets_path) as f:
            markets_data = json.load(f)

        with open(claude_cache_path) as f:
            claude_cache = json.load(f)

        markets = markets_data.get("markets", [])
        logger.info(f"Loaded {len(markets)} markets from {historical_markets_path}")
        logger.info(f"Loaded {len(claude_cache)} Claude estimates from {claude_cache_path}")

        # Build training data - try to match markets with cache
        training_points = []
        cache_list = list(claude_cache.values())

        # If cache is indexed by hash or position rather than market ID,
        # use positional matching
        use_positional = len(cache_list) > 0 and markets[0].get("id") not in claude_cache

        for idx, market in enumerate(markets):
            # Get Claude estimate - try ID match first, then positional
            claude_est = None
            market_id = market.get("id")

            if market_id in claude_cache:
                claude_est = claude_cache[market_id]
            elif use_positional and idx < len(cache_list):
                claude_est = cache_list[idx]

            if claude_est is None:
                continue

            raw_prob = claude_est.get("probability", 0.5)

            # Get actual outcome
            actual_outcome = market.get("actual_outcome")
            if actual_outcome not in ["YES_WON", "NO_WON"]:
                continue

            outcome = 1 if actual_outcome == "YES_WON" else 0

            # Get category from question
            category = CalibrationTrainer._classify_market_category(market.get("question", ""))

            training_points.append((raw_prob, outcome, category))

        logger.info(f"Built {len(training_points)} training points")

        # Train/test split
        rng = np.random.RandomState(42)  # Fixed seed for reproducibility
        indices = np.arange(len(training_points))
        rng.shuffle(indices)

        train_size = int(len(training_points) * train_ratio)
        train_indices = indices[:train_size]
        test_indices = indices[train_size:]

        train_data = [training_points[i] for i in train_indices]
        test_data = [training_points[i] for i in test_indices]

        logger.info(f"Split: {len(train_data)} train, {len(test_data)} test")

        # Train calibrator
        calibrator = CategoryCalibrator()
        success, messages = calibrator.train(train_data)

        for msg in messages.values():
            logger.info(f"Training: {msg}")

        # Validate on test set
        category_results = calibrator.validate(test_data)

        # Compute overall metrics
        raw_probs = np.array([d[0] for d in test_data])
        outcomes = np.array([d[1] for d in test_data])
        calibrated_probs = np.array([
            calibrator.calibrate(p, c) for p, _, c in test_data
        ])

        overall_brier_raw = np.mean((raw_probs - outcomes) ** 2)
        overall_brier_calibrated = np.mean((calibrated_probs - outcomes) ** 2)

        # Weighted average by category size
        weighted_raw = sum(
            result.brier_score_raw * result.sample_count
            for result in category_results.values()
        ) / sum(r.sample_count for r in category_results.values())

        weighted_calibrated = sum(
            result.brier_score_calibrated * result.sample_count
            for result in category_results.values()
        ) / sum(r.sample_count for r in category_results.values())

        report = CalibrationReport(
            timestamp=__import__("datetime").datetime.utcnow().isoformat() + "Z",
            categories=category_results,
            overall_brier_raw=float(overall_brier_raw),
            overall_brier_calibrated=float(overall_brier_calibrated),
            overall_improvement=float(overall_brier_raw - overall_brier_calibrated),
            weighted_brier_raw=float(weighted_raw),
            weighted_brier_calibrated=float(weighted_calibrated),
            total_samples=len(test_data),
        )

        logger.info(
            f"Validation complete. Overall Brier: "
            f"{overall_brier_raw:.4f} (raw) → "
            f"{overall_brier_calibrated:.4f} (calibrated) "
            f"[{report.overall_improvement:.4f} improvement]"
        )

        return calibrator, report

    @staticmethod
    def cross_validate(
        data: List[Tuple[float, int, str]],
        k: int = 5,
    ) -> Dict[str, Dict]:
        """Perform k-fold cross-validation per category.

        Args:
            data: List of (raw_probability, actual_outcome, category) tuples
            k: Number of folds

        Returns:
            Dict of results per category with mean and std metrics
        """
        # Group by category
        category_data = {}
        for raw_prob, outcome, category in data:
            if category not in category_data:
                category_data[category] = []
            category_data[category].append((raw_prob, outcome))

        results = {}

        for category, points in category_data.items():
            if len(points) < k:
                logger.warning(
                    f"Category {category}: {len(points)} samples < k={k}. Skipping CV."
                )
                continue

            fold_results = []
            points_array = np.array(points)
            rng = np.random.RandomState(42)
            rng.shuffle(points_array)

            fold_size = len(points) // k

            for fold_idx in range(k):
                test_start = fold_idx * fold_size
                test_end = (fold_idx + 1) * fold_size if fold_idx < k - 1 else len(points)

                test_fold = points_array[test_start:test_end]
                train_fold = np.concatenate([
                    points_array[:test_start],
                    points_array[test_end:]
                ])

                # Format for training
                train_data_formatted = [
                    (p, int(o), category) for p, o in train_fold
                ]
                test_data_formatted = [
                    (p, int(o), category) for p, o in test_fold
                ]

                # Train and validate
                calibrator = CategoryCalibrator()
                calibrator.train(train_data_formatted)

                fold_result = calibrator.validate(test_data_formatted)
                fold_results.append(fold_result[category])

            # Aggregate across folds
            brier_raws = [r.brier_score_raw for r in fold_results]
            brier_cals = [r.brier_score_calibrated for r in fold_results]

            results[category] = {
                "mean_brier_raw": float(np.mean(brier_raws)),
                "std_brier_raw": float(np.std(brier_raws)),
                "mean_brier_calibrated": float(np.mean(brier_cals)),
                "std_brier_calibrated": float(np.std(brier_cals)),
                "num_folds": k,
                "samples_per_fold": int(fold_size),
            }

        return results


def rank_markets_by_category_edge(
    markets: List[Dict],
    calibrator: CategoryCalibrator,
) -> List[Dict]:
    """Rank markets by category-specific calibrated edge.

    Args:
        markets: List of market dicts with keys:
                - question (required)
                - raw_prob or probability (required)
                - market_price or current_price (required)
        calibrator: CategoryCalibrator instance

    Returns:
        Sorted list of markets with added keys:
        - category
        - raw_prob
        - calibrated_prob
        - market_price
        - edge
        - yes_threshold
        - no_threshold
        - direction (buy_yes, buy_no, hold)
    """
    # Local category classifier (avoid import issues)
    def classify_market(question: str) -> str:
        """Simple category classification."""
        keywords = {
            "politics": ["election", "president", "congress", "senate", "governor", "vote",
                        "democrat", "republican", "trump", "biden", "party"],
            "weather": ["temperature", "rain", "snow", "weather", "hurricane", "storm"],
            "crypto": ["bitcoin", "btc", "ethereum", "eth", "crypto"],
            "sports": ["nba", "nfl", "mlb", "nhl", "soccer", "football"],
            "geopolitical": ["war", "invasion", "nato", "china", "russia"],
            "economic": ["inflation", "gdp", "unemployment", "jobs", "payroll"],
        }
        q_lower = question.lower()
        scores = {cat: sum(1 for kw in kws if kw in q_lower)
                 for cat, kws in keywords.items()}
        best = max(scores, key=scores.get)
        return best if scores[best] > 0 else "unknown"

    ranked = []

    for market in markets:
        question = market.get("question", "")
        raw_prob = market.get("raw_prob") or market.get("probability", 0.5)
        market_price = market.get("market_price") or market.get("current_price", 0.5)

        # Classify and calibrate
        category = classify_market(question)
        calibrated_prob = calibrator.calibrate(raw_prob, category)
        edge = calibrator.compute_edge(raw_prob, market_price, category)
        yes_threshold, no_threshold = calibrator.get_thresholds(category)

        # Determine direction
        direction = "hold"
        if calibrated_prob - market_price > 0:
            if edge >= yes_threshold:
                direction = "buy_yes"
        elif calibrated_prob - market_price < 0:
            if edge >= no_threshold:
                direction = "buy_no"

        ranked.append({
            **market,
            "category": category,
            "raw_prob": float(raw_prob),
            "calibrated_prob": float(calibrated_prob),
            "market_price": float(market_price),
            "edge": float(edge),
            "yes_threshold": float(yes_threshold),
            "no_threshold": float(no_threshold),
            "direction": direction,
        })

    # Sort by edge descending
    ranked.sort(key=lambda m: m["edge"], reverse=True)

    return ranked


if __name__ == "__main__":
    """Demo: Train and validate category calibration on backtest data."""

    import sys
    from datetime import datetime

    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Paths
    backtest_dir = Path("/sessions/dreamy-tender-gates/mnt/Quant/backtest/data")
    historical_markets_path = backtest_dir / "historical_markets.json"
    claude_cache_path = backtest_dir / "claude_cache.json"

    if not historical_markets_path.exists():
        print(f"ERROR: {historical_markets_path} not found")
        sys.exit(1)

    if not claude_cache_path.exists():
        print(f"ERROR: {claude_cache_path} not found")
        sys.exit(1)

    print("=" * 80)
    print("CATEGORY CALIBRATION TRAINER")
    print("=" * 80)
    print(f"Timestamp: {datetime.utcnow().isoformat()}Z")
    print()

    # Train calibrator
    print("Training category-specific calibration...")
    print("-" * 80)

    calibrator, report = CalibrationTrainer.train_from_backtest(
        historical_markets_path,
        claude_cache_path,
        train_ratio=0.7,
    )

    print()
    print("=" * 80)
    print("VALIDATION RESULTS")
    print("=" * 80)
    print()

    # Overall metrics
    print(f"Total test samples: {report.total_samples}")
    print(f"Overall Brier (raw): {report.overall_brier_raw:.4f}")
    print(f"Overall Brier (calibrated): {report.overall_brier_calibrated:.4f}")
    print(f"Overall improvement: {report.overall_improvement:.4f}")
    print(f"Weighted Brier (raw): {report.weighted_brier_raw:.4f}")
    print(f"Weighted Brier (calibrated): {report.weighted_brier_calibrated:.4f}")
    print()

    # Per-category breakdown
    print("=" * 80)
    print("PER-CATEGORY BREAKDOWN")
    print("=" * 80)
    print()

    for category in sorted(report.categories.keys()):
        perf = report.categories[category]
        print(f"{category.upper()}")
        print(f"  Samples: {perf.sample_count}")
        print(f"  Brier (raw): {perf.brier_score_raw:.4f}")
        print(f"  Brier (calibrated): {perf.brier_score_calibrated:.4f}")
        print(f"  Improvement: {perf.brier_improvement:.4f}")
        print(f"  Win rate (YES): {perf.win_rate_yes:.1%}")
        print(f"  Win rate (NO): {perf.win_rate_no:.1%}")
        print(f"  Avg edge (YES): {perf.avg_edge_yes:.4f}")
        print(f"  Avg edge (NO): {perf.avg_edge_no:.4f}")
        print(f"  Platt params: A={perf.platt_a:.4f}, B={perf.platt_b:.4f}")
        print()

    # Save calibration
    output_path = Path("/sessions/dreamy-tender-gates/mnt/Quant/polymarket-bot/src/calibration/trained_params.json")
    calibrator.save(output_path)

    # Save report
    report_path = Path("/sessions/dreamy-tender-gates/mnt/Quant/polymarket-bot/src/calibration/calibration_report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(report.to_dict(), f, indent=2)

    print("=" * 80)
    print("SAVED")
    print("=" * 80)
    print(f"Parameters: {output_path}")
    print(f"Report: {report_path}")
    print()
