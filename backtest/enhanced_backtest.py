"""Enhanced backtest system with high-leverage improvements.

Improvements over baseline:
1. Direction-specific calibration — separate Platt scalers for YES vs NO predictions
2. Category auto-classification + per-category calibration
3. Walk-forward temporal cross-validation (train on past, test on future)
4. Multi-prompt ensemble — 3 diverse prompt framings, averaged per market
5. Volume/liquidity-aware filtering
6. Full 2528-market dataset utilization

Run: python enhanced_backtest.py [--mode all|direction|category|walkforward|multiprompt]
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
RANDOM_SEED = 42


# ---------------------------------------------------------------------------
# Category classifier (rule-based, zero cost)
# ---------------------------------------------------------------------------

CATEGORY_PATTERNS = {
    "politics": [
        r"\b(president|election|vote|democrat|republican|trump|biden|congress|senate"
        r"|governor|poll|primary|nominee|party|political|legislation|impeach"
        r"|cabinet|speaker|vp|vice president|gop|dnc|rnc|electoral)\b",
    ],
    "crypto": [
        r"\b(bitcoin|btc|ethereum|eth|crypto|solana|sol|dogecoin|doge|token"
        r"|blockchain|defi|nft|altcoin|binance|coinbase|market\s*cap)\b",
    ],
    "sports": [
        r"\b(nba|nfl|mlb|nhl|fifa|super\s*bowl|world\s*cup|championship"
        r"|playoff|mvp|touchdown|home\s*run|goal|match|game\s+\d|season"
        r"|quarterback|pitcher|coach|team|league|win\s+the|beat\s+the)\b",
    ],
    "weather": [
        r"\b(temperature|weather|degrees|fahrenheit|celsius|rain|snow"
        r"|hurricane|storm|flood|drought|heat\s*wave|cold|warm|noaa"
        r"|forecast|climate|high\s+of|low\s+of|record\s+high|nyc|chicago"
        r"|miami|seattle|denver|los\s+angeles)\b",
    ],
    "economics": [
        r"\b(gdp|inflation|cpi|fed\s*(eral)?(\s+reserve)?|interest\s*rate"
        r"|unemployment|jobs\s*report|stock|s&p|nasdaq|dow|market|trade"
        r"|tariff|recession|growth|fomc|treasury|yield|bond|oil\s+price)\b",
    ],
    "geopolitical": [
        r"\b(war|invasion|sanction|nato|un\s|united\s+nations|ceasefire"
        r"|missile|nuclear|treaty|conflict|military|troops|border"
        r"|territory|occupation|diplomacy|ambassador)\b",
    ],
    "science_tech": [
        r"\b(ai\b|artificial\s+intelligence|spacex|nasa|fda|drug\s+approval"
        r"|vaccine|clinical\s+trial|launch|rocket|satellite|discovery"
        r"|patent|tech|google|apple|microsoft|openai|anthropic|meta)\b",
    ],
    "entertainment": [
        r"\b(oscar|grammy|emmy|box\s+office|movie|film|album|song|artist"
        r"|celebrity|award|netflix|disney|spotify|youtube|tiktok|viral)\b",
    ],
}


def classify_market(question: str, description: str = "") -> str:
    """Classify a market into a category based on question text."""
    text = (question + " " + description[:200]).lower()
    scores = {}
    for cat, patterns in CATEGORY_PATTERNS.items():
        score = 0
        for pat in patterns:
            matches = re.findall(pat, text, re.IGNORECASE)
            score += len(matches)
        if score > 0:
            scores[cat] = score
    if not scores:
        return "other"
    return max(scores, key=scores.get)


# ---------------------------------------------------------------------------
# Direction-specific Platt Scaling
# ---------------------------------------------------------------------------

class DirectionalPlattScaler:
    """Fits separate Platt scalers for YES-leaning and NO-leaning predictions.

    Rationale: Claude's overconfidence pattern differs by direction.
    YES predictions (prob > 0.5) win 55.8% — severely overconfident.
    NO predictions (prob < 0.5) are better calibrated at 76.2%.
    A single scaler is a blunt instrument that averages these patterns.
    """

    def __init__(self):
        self.yes_scaler = PlattScaler()  # For raw_prob > 0.5
        self.no_scaler = PlattScaler()   # For raw_prob <= 0.5
        self.global_scaler = PlattScaler()  # Fallback
        self._fitted = False

    def fit(self, raw_probs: np.ndarray, labels: np.ndarray):
        # Global fit
        self.global_scaler.fit(raw_probs, labels)

        # Split by predicted direction
        yes_mask = raw_probs > 0.5
        no_mask = ~yes_mask

        min_samples = 30
        if yes_mask.sum() >= min_samples:
            self.yes_scaler.fit(raw_probs[yes_mask], labels[yes_mask])
        else:
            self.yes_scaler = self.global_scaler

        if no_mask.sum() >= min_samples:
            self.no_scaler.fit(raw_probs[no_mask], labels[no_mask])
        else:
            self.no_scaler = self.global_scaler

        self._fitted = True
        logger.info(
            f"Directional Platt fitted: YES A={self.yes_scaler.A:.4f} B={self.yes_scaler.B:.4f} "
            f"(n={yes_mask.sum()}), NO A={self.no_scaler.A:.4f} B={self.no_scaler.B:.4f} "
            f"(n={no_mask.sum()})"
        )

    def transform(self, raw_prob: float) -> float:
        if not self._fitted:
            return raw_prob
        if raw_prob > 0.5:
            return self.yes_scaler.transform(raw_prob)
        else:
            return self.no_scaler.transform(raw_prob)

    def transform_array(self, raw_probs: np.ndarray) -> np.ndarray:
        if not self._fitted:
            return raw_probs
        result = np.empty_like(raw_probs)
        yes_mask = raw_probs > 0.5
        if yes_mask.any():
            result[yes_mask] = self.yes_scaler.transform_array(raw_probs[yes_mask])
        if (~yes_mask).any():
            result[~yes_mask] = self.no_scaler.transform_array(raw_probs[~yes_mask])
        return result


# ---------------------------------------------------------------------------
# Category-specific Calibration
# ---------------------------------------------------------------------------

class CategoryCalibrator:
    """Fits per-category Platt scalers. Falls back to global for small categories."""

    def __init__(self, min_category_samples: int = 40):
        self.min_samples = min_category_samples
        self.category_scalers: dict[str, PlattScaler] = {}
        self.global_scaler = PlattScaler()
        self._fitted = False
        self._category_stats: dict[str, dict] = {}

    def fit(self, raw_probs: np.ndarray, labels: np.ndarray, categories: list[str]):
        self.global_scaler.fit(raw_probs, labels)

        unique_cats = set(categories)
        cats_arr = np.array(categories)

        for cat in unique_cats:
            mask = cats_arr == cat
            n = mask.sum()
            if n >= self.min_samples:
                scaler = PlattScaler()
                scaler.fit(raw_probs[mask], labels[mask])
                self.category_scalers[cat] = scaler
                self._category_stats[cat] = {
                    "n": int(n),
                    "A": round(scaler.A, 4),
                    "B": round(scaler.B, 4),
                    "raw_brier": round(float(np.mean((raw_probs[mask] - labels[mask]) ** 2)), 4),
                    "cal_brier": round(float(np.mean(
                        (scaler.transform_array(raw_probs[mask]) - labels[mask]) ** 2
                    )), 4),
                }
            else:
                self._category_stats[cat] = {"n": int(n), "using": "global"}

        self._fitted = True
        logger.info(f"Category calibrator: {len(self.category_scalers)} category-specific "
                     f"scalers, {len(unique_cats) - len(self.category_scalers)} using global")

    def transform(self, raw_prob: float, category: str) -> float:
        if not self._fitted:
            return raw_prob
        scaler = self.category_scalers.get(category, self.global_scaler)
        return scaler.transform(raw_prob)


# ---------------------------------------------------------------------------
# Platt Scaler (copied from calibration.py to keep self-contained)
# ---------------------------------------------------------------------------

class PlattScaler:
    def __init__(self):
        self.A = 1.0
        self.B = 0.0
        self._fitted = False

    @staticmethod
    def _logit(p: np.ndarray) -> np.ndarray:
        p = np.clip(p, 0.001, 0.999)
        return np.log(p / (1 - p))

    @staticmethod
    def _logit_scalar(p: float) -> float:
        p = max(0.001, min(0.999, p))
        return math.log(p / (1 - p))

    def fit(self, raw_probs: np.ndarray, labels: np.ndarray, max_iter: int = 500, lr: float = 0.05):
        n = len(raw_probs)
        if n < 5:
            return
        n_pos = labels.sum()
        n_neg = n - n_pos
        features = self._logit(raw_probs)
        t_pos = (n_pos + 1.0) / (n_pos + 2.0)
        t_neg = 1.0 / (n_neg + 2.0)
        targets = np.where(labels > 0.5, t_pos, t_neg)

        A, B = 1.0, 0.0
        for _ in range(max_iter):
            logits = A * features + B
            logits = np.clip(logits, -30, 30)
            preds = 1.0 / (1.0 + np.exp(-logits))
            preds = np.clip(preds, 1e-10, 1 - 1e-10)
            errors = preds - targets
            A -= lr * np.mean(errors * features)
            B -= lr * np.mean(errors)

        self.A, self.B = A, B
        self._fitted = True

    def transform(self, raw_prob: float) -> float:
        if not self._fitted:
            return raw_prob
        logit_input = self._logit_scalar(raw_prob)
        logit = self.A * logit_input + self.B
        logit = max(-30, min(30, logit))
        return max(0.01, min(0.99, 1.0 / (1.0 + math.exp(-logit))))

    def transform_array(self, raw_probs: np.ndarray) -> np.ndarray:
        if not self._fitted:
            return raw_probs
        features = self._logit(raw_probs)
        logits = self.A * features + self.B
        logits = np.clip(logits, -30, 30)
        return np.clip(1.0 / (1.0 + np.exp(-logits)), 0.01, 0.99)


# ---------------------------------------------------------------------------
# Multi-prompt ensemble
# ---------------------------------------------------------------------------

# Three diverse prompt framings designed to reduce correlated errors
PROMPT_VARIANTS = {
    "base_rate_first": """You are a probability estimation expert. Estimate the TRUE probability that this event resolves YES.

Question: {question}

Additional context: {description}

IMPORTANT RULES:
1. Start by identifying the BASE RATE: What percentage of similar events have historically resolved YES?
2. Then adjust from the base rate based on specific circumstances
3. Be well-calibrated — a 70% estimate should be right about 70% of the time
4. You tend to overestimate YES probabilities by 20-30%. Correct for this.

Respond in EXACTLY this format:
PROBABILITY: <number between 0.01 and 0.99>
CONFIDENCE: <low, medium, or high>
REASONING: <1-2 sentence explanation>""",

    "contrarian": """You are a skeptical probability analyst known for avoiding overconfidence. Estimate the probability that this event resolves YES.

Question: {question}

Additional context: {description}

IMPORTANT RULES:
1. Consider what would need to happen for this to resolve NO — is that more likely than you think?
2. Most people are overconfident. If your gut says 80%, the true probability is likely closer to 60%.
3. Consider the null hypothesis: assume NO unless evidence strongly suggests YES.
4. What is the strongest argument AGAINST this resolving YES?

Respond in EXACTLY this format:
PROBABILITY: <number between 0.01 and 0.99>
CONFIDENCE: <low, medium, or high>
REASONING: <1-2 sentence explanation>""",

    "decomposition": """You are an expert forecaster. Break down the probability that this event resolves YES.

Question: {question}

Additional context: {description}

IMPORTANT RULES:
1. Identify 2-3 necessary conditions for YES resolution
2. Estimate the probability of EACH condition independently
3. Multiply the probabilities (if independent) or adjust for dependencies
4. Your final estimate should be well-calibrated — avoid the common trap of overestimating YES.

Respond in EXACTLY this format:
PROBABILITY: <number between 0.01 and 0.99>
CONFIDENCE: <low, medium, or high>
REASONING: <1-2 sentence explanation>""",
}


class MultiPromptCache:
    """Cache for multi-prompt ensemble estimates."""

    def __init__(self, cache_path: Optional[str] = None):
        self.path = cache_path or os.path.join(DATA_DIR, "multiprompt_cache.json")
        self._cache = {}
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            with open(self.path) as f:
                self._cache = json.load(f)
            logger.info(f"Multi-prompt cache: {len(self._cache)} entries")

    def _save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(self._cache, f, indent=2)

    def _key(self, question: str, prompt_name: str) -> str:
        return hashlib.sha256(f"{prompt_name}:{question}".encode()).hexdigest()[:16]

    def get(self, question: str, prompt_name: str) -> Optional[dict]:
        return self._cache.get(self._key(question, prompt_name))

    def put(self, question: str, prompt_name: str, result: dict):
        self._cache[self._key(question, prompt_name)] = result
        self._save()


def parse_response(text: str) -> dict:
    """Parse Claude's structured response."""
    prob = 0.5
    confidence = "medium"
    reasoning = text
    for line in text.split("\n"):
        line = line.strip()
        if line.upper().startswith("PROBABILITY:"):
            try:
                val = line.split(":", 1)[1].strip()
                prob = float(val)
                prob = max(0.01, min(0.99, prob))
            except (ValueError, IndexError):
                pass
        elif line.upper().startswith("CONFIDENCE:"):
            confidence = line.split(":", 1)[1].strip().lower()
        elif line.upper().startswith("REASONING:"):
            reasoning = line.split(":", 1)[1].strip()
    return {"probability": prob, "confidence": confidence, "reasoning": reasoning}


class MultiPromptEstimator:
    """Run 3 diverse prompts and average, reducing variance."""

    def __init__(self, api_key: str = "", model: str = "claude-haiku-4-5-20251001"):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.model = model
        self.cache = MultiPromptCache()
        self._client = None
        self.prompt_names = list(PROMPT_VARIANTS.keys())

    def _get_client(self):
        if self._client is None:
            from anthropic import Anthropic
            self._client = Anthropic(api_key=self.api_key)
        return self._client

    def estimate(self, question: str, description: str = "") -> dict:
        """Get ensemble estimate from 3 prompts. Uses cache."""
        results = []
        probs = []

        for name in self.prompt_names:
            cached = self.cache.get(question, name)
            if cached:
                results.append(cached)
                probs.append(cached["probability"])
                continue

            # Call API
            prompt_template = PROMPT_VARIANTS[name]
            prompt = prompt_template.format(question=question, description=description[:300])
            client = self._get_client()

            try:
                msg = client.messages.create(
                    model=self.model,
                    max_tokens=200,
                    messages=[{"role": "user", "content": prompt}],
                )
                text = msg.content[0].text.strip()
                result = parse_response(text)
                result["prompt_name"] = name
            except Exception as e:
                logger.error(f"API error ({name}): {e}")
                result = {"probability": 0.5, "confidence": "low",
                          "reasoning": f"API error: {e}", "prompt_name": name}

            self.cache.put(question, name, result)
            results.append(result)
            probs.append(result["probability"])

        # Aggregate: trimmed mean (drop highest and lowest if 3+ prompts)
        if len(probs) >= 3:
            sorted_probs = sorted(probs)
            # Use all 3 for now (with only 3 prompts, trimmed mean = median)
            mean_prob = np.mean(probs)
            median_prob = np.median(probs)
            spread = max(probs) - min(probs)
        else:
            mean_prob = np.mean(probs) if probs else 0.5
            median_prob = mean_prob
            spread = 0.0

        return {
            "probability": float(mean_prob),
            "median_probability": float(median_prob),
            "spread": float(spread),
            "individual_probs": probs,
            "individual_results": results,
            "n_prompts": len(probs),
            # Use spread as disagreement signal — high spread = low confidence
            "confidence": "high" if spread < 0.10 else ("medium" if spread < 0.20 else "low"),
        }


# ---------------------------------------------------------------------------
# Walk-forward temporal cross-validation
# ---------------------------------------------------------------------------

def walk_forward_split(markets: list, cache: dict, n_folds: int = 3) -> list[tuple]:
    """Split markets by time into expanding-window train + test folds.

    Returns list of (train_indices, test_indices) tuples.
    Each fold: train on all data before the test window.
    """
    # Parse end_dates and sort
    dated = []
    for i, m in enumerate(markets):
        end_date = m.get("end_date", "")
        if end_date:
            dated.append((end_date, i))

    dated.sort(key=lambda x: x[0])
    sorted_indices = [idx for _, idx in dated]

    # Split into n_folds+1 equal chunks. Use first chunk as minimum train,
    # then each subsequent chunk is a test fold with all prior chunks as train.
    chunk_size = len(sorted_indices) // (n_folds + 1)
    folds = []

    for fold_idx in range(n_folds):
        train_end = (fold_idx + 1) * chunk_size
        test_start = train_end
        test_end = test_start + chunk_size
        if fold_idx == n_folds - 1:
            test_end = len(sorted_indices)  # Last fold gets remainder

        train_indices = sorted_indices[:train_end]
        test_indices = sorted_indices[test_start:test_end]
        folds.append((train_indices, test_indices))

        train_dates = [markets[i]["end_date"] for i in train_indices if markets[i].get("end_date")]
        test_dates = [markets[i]["end_date"] for i in test_indices if markets[i].get("end_date")]
        logger.info(
            f"Fold {fold_idx + 1}: train {len(train_indices)} markets "
            f"({train_dates[0][:10] if train_dates else '?'} → {train_dates[-1][:10] if train_dates else '?'}), "
            f"test {len(test_indices)} markets "
            f"({test_dates[0][:10] if test_dates else '?'} → {test_dates[-1][:10] if test_dates else '?'})"
        )

    return folds


# ---------------------------------------------------------------------------
# Enhanced Backtest Engine
# ---------------------------------------------------------------------------

@dataclass
class EnhancedTradeResult:
    question: str
    category: str
    actual_outcome: str
    raw_prob: float
    calibrated_prob: float
    confidence: str
    entry_price: float
    direction: str
    size: float
    pnl: float
    won: bool
    edge: float
    end_date: str = ""


class EnhancedBacktestEngine:
    """Runs all improvement variants and compares against baseline."""

    def __init__(
        self,
        api_key: str = "",
        position_size: float = 2.0,
        starting_capital: float = 75.0,
    ):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.position_size = position_size
        self.starting_capital = starting_capital

    def _load_data(self) -> tuple[list, dict]:
        with open(os.path.join(DATA_DIR, "historical_markets.json")) as f:
            markets = json.load(f)["markets"]
        with open(os.path.join(DATA_DIR, "claude_cache.json")) as f:
            cache = json.load(f)
        return markets, cache

    def _get_cached_estimate(self, question: str, cache: dict) -> Optional[dict]:
        key = hashlib.sha256(question.encode()).hexdigest()[:16]
        return cache.get(key)

    def _resolve_trade(self, direction: str, entry_price: float, size: float,
                       actual: str) -> tuple[bool, float]:
        """Resolve trade with realistic fee + slippage model."""
        winner_fee = 0.02
        half_spread = 0.015  # Conservative half-spread (was 0.035 for weather only)

        if direction == "buy_yes":
            effective_entry = min(entry_price + half_spread, 0.99)
            if actual == "YES_WON":
                shares = size / effective_entry
                gross = shares * 1.0
                fee = gross * winner_fee
                return True, gross - fee - size
            return False, -size
        else:
            effective_no = min((1.0 - entry_price) + half_spread, 0.99)
            if actual == "NO_WON":
                shares = size / effective_no
                gross = shares * 1.0
                fee = gross * winner_fee
                return True, gross - fee - size
            return False, -size

    def _simulate_trades(
        self,
        markets: list,
        cache: dict,
        calibrator=None,
        yes_threshold: float = 0.05,
        no_threshold: float = 0.05,
        entry_prices: list[float] = None,
        category_calibrator: CategoryCalibrator = None,
        use_multiprompt: bool = False,
        multiprompt_cache: dict = None,
    ) -> tuple[list[EnhancedTradeResult], list[float]]:
        """Core simulation loop."""
        if entry_prices is None:
            entry_prices = [0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80]

        trades = []
        brier_scores = []

        for m in markets:
            question = m["question"]
            actual = m["actual_outcome"]
            description = m.get("description", "")
            end_date = m.get("end_date", "")
            category = classify_market(question, description)

            est = self._get_cached_estimate(question, cache)
            if not est:
                continue

            raw_prob = est["probability"]

            # Apply calibration
            if category_calibrator:
                cal_prob = category_calibrator.transform(raw_prob, category)
            elif calibrator:
                cal_prob = calibrator.transform(raw_prob)
            else:
                cal_prob = raw_prob

            # If using multi-prompt, override with ensemble estimate
            if use_multiprompt and multiprompt_cache:
                mp_key = hashlib.sha256(question.encode()).hexdigest()[:16]
                mp_est = multiprompt_cache.get(mp_key)
                if mp_est:
                    cal_prob = mp_est["probability"]
                    # Still apply calibration on top
                    if calibrator:
                        cal_prob = calibrator.transform(cal_prob)

            actual_binary = 1.0 if actual == "YES_WON" else 0.0
            brier_scores.append((cal_prob - actual_binary) ** 2)

            for entry_price in entry_prices:
                edge = cal_prob - entry_price
                abs_edge = abs(edge)

                if edge > 0:
                    direction = "buy_yes"
                    if abs_edge < yes_threshold:
                        continue
                else:
                    direction = "buy_no"
                    if abs_edge < no_threshold:
                        continue

                size = self.position_size
                won, pnl = self._resolve_trade(direction, entry_price, size, actual)

                trades.append(EnhancedTradeResult(
                    question=question,
                    category=category,
                    actual_outcome=actual,
                    raw_prob=raw_prob,
                    calibrated_prob=cal_prob,
                    confidence=est.get("confidence", "medium"),
                    entry_price=entry_price,
                    direction=direction,
                    size=size,
                    pnl=pnl,
                    won=won,
                    edge=abs_edge,
                    end_date=end_date,
                ))

        return trades, brier_scores

    def _compute_metrics(self, trades: list[EnhancedTradeResult],
                         brier_scores: list[float], label: str = "") -> dict:
        """Compute comprehensive metrics from trades."""
        total = len(trades)
        if total == 0:
            return {"label": label, "trades": 0}

        wins = sum(1 for t in trades if t.won)
        total_pnl = sum(t.pnl for t in trades)
        avg_pnl = total_pnl / total

        # Drawdown
        cum, peak, max_dd = 0.0, 0.0, 0.0
        for t in trades:
            cum += t.pnl
            peak = max(peak, cum)
            max_dd = max(max_dd, peak - cum)

        # By direction
        yes_trades = [t for t in trades if t.direction == "buy_yes"]
        no_trades = [t for t in trades if t.direction == "buy_no"]
        yes_wr = sum(1 for t in yes_trades if t.won) / len(yes_trades) if yes_trades else 0
        no_wr = sum(1 for t in no_trades if t.won) / len(no_trades) if no_trades else 0

        # By category
        cat_stats = {}
        for cat in set(t.category for t in trades):
            ct = [t for t in trades if t.category == cat]
            cat_wins = sum(1 for t in ct if t.won)
            cat_stats[cat] = {
                "trades": len(ct),
                "win_rate": round(cat_wins / len(ct), 4),
                "avg_pnl": round(sum(t.pnl for t in ct) / len(ct), 4),
            }

        avg_brier = sum(brier_scores) / len(brier_scores) if brier_scores else 0.5

        # ARR (5 trades/day, $20/mo infra, $75 capital)
        monthly_net = (avg_pnl * 5 * 30) - 20
        arr = (monthly_net * 12 / self.starting_capital) * 100

        return {
            "label": label,
            "trades": total,
            "win_rate": round(wins / total, 4),
            "total_pnl": round(total_pnl, 2),
            "avg_pnl": round(avg_pnl, 4),
            "brier": round(avg_brier, 4),
            "max_drawdown": round(max_dd, 2),
            "yes_trades": len(yes_trades),
            "yes_win_rate": round(yes_wr, 4),
            "no_trades": len(no_trades),
            "no_win_rate": round(no_wr, 4),
            "arr_5": round(arr, 0),
            "by_category": cat_stats,
        }

    # -------------------------------------------------------------------
    # Improvement 1: Direction-specific calibration
    # -------------------------------------------------------------------

    def run_direction_calibration(self) -> dict:
        """Compare global Platt vs direction-specific Platt."""
        markets, cache = self._load_data()
        logger.info(f"Running direction-specific calibration on {len(markets)} markets")

        # Build samples
        raw_probs = []
        labels = []
        for m in markets:
            est = self._get_cached_estimate(m["question"], cache)
            if not est:
                continue
            raw_probs.append(est["probability"])
            labels.append(1.0 if m["actual_outcome"] == "YES_WON" else 0.0)

        raw_probs = np.array(raw_probs)
        labels = np.array(labels)

        # Train/test split (70/30, stratified)
        rng = np.random.RandomState(RANDOM_SEED)
        yes_idx = np.where(labels > 0.5)[0]
        no_idx = np.where(labels <= 0.5)[0]
        rng.shuffle(yes_idx)
        rng.shuffle(no_idx)

        n_yes_train = int(len(yes_idx) * 0.7)
        n_no_train = int(len(no_idx) * 0.7)

        train_idx = np.concatenate([yes_idx[:n_yes_train], no_idx[:n_no_train]])
        test_idx = np.concatenate([yes_idx[n_yes_train:], no_idx[n_no_train:]])

        train_probs, train_labels = raw_probs[train_idx], labels[train_idx]
        test_probs, test_labels = raw_probs[test_idx], labels[test_idx]

        # Fit calibrators
        global_scaler = PlattScaler()
        global_scaler.fit(train_probs, train_labels)

        dir_scaler = DirectionalPlattScaler()
        dir_scaler.fit(train_probs, train_labels)

        # Evaluate on test set
        brier_raw = float(np.mean((test_probs - test_labels) ** 2))
        brier_global = float(np.mean((global_scaler.transform_array(test_probs) - test_labels) ** 2))
        brier_dir = float(np.mean((dir_scaler.transform_array(test_probs) - test_labels) ** 2))

        # Evaluate by direction on test set
        yes_test_mask = test_probs > 0.5
        no_test_mask = ~yes_test_mask

        results = {
            "n_train": len(train_idx),
            "n_test": len(test_idx),
            "test_brier_raw": round(brier_raw, 4),
            "test_brier_global_platt": round(brier_global, 4),
            "test_brier_directional_platt": round(brier_dir, 4),
            "improvement_global_vs_raw": round(brier_raw - brier_global, 4),
            "improvement_directional_vs_raw": round(brier_raw - brier_dir, 4),
            "improvement_directional_vs_global": round(brier_global - brier_dir, 4),
            "global_platt": {"A": round(global_scaler.A, 4), "B": round(global_scaler.B, 4)},
            "directional_platt": {
                "yes_A": round(dir_scaler.yes_scaler.A, 4),
                "yes_B": round(dir_scaler.yes_scaler.B, 4),
                "no_A": round(dir_scaler.no_scaler.A, 4),
                "no_B": round(dir_scaler.no_scaler.B, 4),
            },
        }

        # By-direction Brier on test set
        for name, mask in [("yes_side", yes_test_mask), ("no_side", no_test_mask)]:
            if mask.sum() > 0:
                results[f"{name}_n"] = int(mask.sum())
                results[f"{name}_brier_raw"] = round(
                    float(np.mean((test_probs[mask] - test_labels[mask]) ** 2)), 4
                )
                results[f"{name}_brier_global"] = round(
                    float(np.mean((global_scaler.transform_array(test_probs[mask]) - test_labels[mask]) ** 2)), 4
                )
                results[f"{name}_brier_directional"] = round(
                    float(np.mean((dir_scaler.transform_array(test_probs[mask]) - test_labels[mask]) ** 2)), 4
                )

        # Run trade simulation comparing global vs directional
        logger.info("Simulating trades with global vs directional calibration...")

        # Fit on ALL data for trade simulation (typical deployment)
        global_full = PlattScaler()
        global_full.fit(raw_probs, labels)
        dir_full = DirectionalPlattScaler()
        dir_full.fit(raw_probs, labels)

        baseline_trades, baseline_brier = self._simulate_trades(
            markets, cache, yes_threshold=0.15, no_threshold=0.05
        )
        global_trades, global_brier = self._simulate_trades(
            markets, cache, calibrator=global_full, yes_threshold=0.15, no_threshold=0.05
        )
        dir_trades, dir_brier = self._simulate_trades(
            markets, cache, calibrator=dir_full, yes_threshold=0.15, no_threshold=0.05
        )

        results["trade_sim"] = {
            "baseline": self._compute_metrics(baseline_trades, baseline_brier, "Baseline (uncalibrated)"),
            "global_platt": self._compute_metrics(global_trades, global_brier, "Global Platt"),
            "directional_platt": self._compute_metrics(dir_trades, dir_brier, "Directional Platt"),
        }

        return results

    # -------------------------------------------------------------------
    # Improvement 2: Category-specific calibration
    # -------------------------------------------------------------------

    def run_category_calibration(self) -> dict:
        """Test category-specific calibration."""
        markets, cache = self._load_data()
        logger.info(f"Running category calibration on {len(markets)} markets")

        raw_probs = []
        labels = []
        categories = []

        for m in markets:
            est = self._get_cached_estimate(m["question"], cache)
            if not est:
                continue
            raw_probs.append(est["probability"])
            labels.append(1.0 if m["actual_outcome"] == "YES_WON" else 0.0)
            categories.append(classify_market(m["question"], m.get("description", "")))

        raw_probs = np.array(raw_probs)
        labels = np.array(labels)

        # Category distribution
        from collections import Counter
        cat_counts = Counter(categories)
        logger.info(f"Category distribution: {dict(cat_counts.most_common())}")

        # Train/test split
        rng = np.random.RandomState(RANDOM_SEED)
        indices = np.arange(len(raw_probs))
        rng.shuffle(indices)
        n_train = int(len(indices) * 0.7)
        train_idx, test_idx = indices[:n_train], indices[n_train:]

        train_probs = raw_probs[train_idx]
        train_labels = labels[train_idx]
        train_cats = [categories[i] for i in train_idx]
        test_probs = raw_probs[test_idx]
        test_labels = labels[test_idx]
        test_cats = [categories[i] for i in test_idx]

        # Fit calibrators
        global_scaler = PlattScaler()
        global_scaler.fit(train_probs, train_labels)

        cat_calibrator = CategoryCalibrator(min_category_samples=30)
        cat_calibrator.fit(train_probs, train_labels, train_cats)

        # Evaluate on test set — overall
        brier_raw = float(np.mean((test_probs - test_labels) ** 2))
        brier_global = float(np.mean((global_scaler.transform_array(test_probs) - test_labels) ** 2))

        cat_cal_probs = np.array([
            cat_calibrator.transform(p, c)
            for p, c in zip(test_probs, test_cats)
        ])
        brier_cat = float(np.mean((cat_cal_probs - test_labels) ** 2))

        results = {
            "n_train": len(train_idx),
            "n_test": len(test_idx),
            "category_distribution": dict(cat_counts.most_common()),
            "test_brier_raw": round(brier_raw, 4),
            "test_brier_global_platt": round(brier_global, 4),
            "test_brier_category_platt": round(brier_cat, 4),
            "improvement_category_vs_raw": round(brier_raw - brier_cat, 4),
            "improvement_category_vs_global": round(brier_global - brier_cat, 4),
            "category_scalers": cat_calibrator._category_stats,
        }

        # Per-category test Brier
        test_cats_arr = np.array(test_cats)
        per_cat_results = {}
        for cat in set(test_cats):
            mask = test_cats_arr == cat
            if mask.sum() >= 10:
                per_cat_results[cat] = {
                    "n": int(mask.sum()),
                    "brier_raw": round(float(np.mean((test_probs[mask] - test_labels[mask]) ** 2)), 4),
                    "brier_global": round(float(np.mean(
                        (global_scaler.transform_array(test_probs[mask]) - test_labels[mask]) ** 2
                    )), 4),
                    "brier_category": round(float(np.mean(
                        (cat_cal_probs[mask] - test_labels[mask]) ** 2
                    )), 4),
                }
        results["per_category_test_brier"] = per_cat_results

        return results

    # -------------------------------------------------------------------
    # Improvement 3: Walk-forward temporal validation
    # -------------------------------------------------------------------

    def run_walkforward(self) -> dict:
        """Walk-forward temporal cross-validation."""
        markets, cache = self._load_data()
        logger.info(f"Running walk-forward validation on {len(markets)} markets")

        # Build index of markets that have cache entries
        valid_markets = []
        for m in markets:
            est = self._get_cached_estimate(m["question"], cache)
            if est and m.get("end_date"):
                valid_markets.append(m)

        logger.info(f"Markets with cache + end_date: {len(valid_markets)}")

        folds = walk_forward_split(valid_markets, cache, n_folds=3)
        fold_results = []

        for fold_idx, (train_indices, test_indices) in enumerate(folds):
            # Extract train data
            train_probs, train_labels = [], []
            for i in train_indices:
                m = valid_markets[i]
                est = self._get_cached_estimate(m["question"], cache)
                if est:
                    train_probs.append(est["probability"])
                    train_labels.append(1.0 if m["actual_outcome"] == "YES_WON" else 0.0)

            train_probs = np.array(train_probs)
            train_labels = np.array(train_labels)

            # Fit on train
            scaler = PlattScaler()
            scaler.fit(train_probs, train_labels)

            dir_scaler = DirectionalPlattScaler()
            dir_scaler.fit(train_probs, train_labels)

            # Evaluate on test
            test_probs, test_labels = [], []
            for i in test_indices:
                m = valid_markets[i]
                est = self._get_cached_estimate(m["question"], cache)
                if est:
                    test_probs.append(est["probability"])
                    test_labels.append(1.0 if m["actual_outcome"] == "YES_WON" else 0.0)

            test_probs = np.array(test_probs)
            test_labels = np.array(test_labels)

            brier_raw = float(np.mean((test_probs - test_labels) ** 2))
            brier_platt = float(np.mean((scaler.transform_array(test_probs) - test_labels) ** 2))
            brier_dir = float(np.mean((dir_scaler.transform_array(test_probs) - test_labels) ** 2))

            fold_results.append({
                "fold": fold_idx + 1,
                "n_train": len(train_probs),
                "n_test": len(test_probs),
                "train_period": f"{valid_markets[train_indices[0]].get('end_date', '?')[:10]} → "
                                f"{valid_markets[train_indices[-1]].get('end_date', '?')[:10]}",
                "test_period": f"{valid_markets[test_indices[0]].get('end_date', '?')[:10]} → "
                               f"{valid_markets[test_indices[-1]].get('end_date', '?')[:10]}",
                "test_brier_raw": round(brier_raw, 4),
                "test_brier_platt": round(brier_platt, 4),
                "test_brier_directional": round(brier_dir, 4),
                "platt_improvement": round(brier_raw - brier_platt, 4),
                "directional_improvement": round(brier_raw - brier_dir, 4),
                "platt_params": {"A": round(scaler.A, 4), "B": round(scaler.B, 4)},
            })

        # Aggregate
        avg_raw = np.mean([f["test_brier_raw"] for f in fold_results])
        avg_platt = np.mean([f["test_brier_platt"] for f in fold_results])
        avg_dir = np.mean([f["test_brier_directional"] for f in fold_results])

        return {
            "n_folds": len(fold_results),
            "total_valid_markets": len(valid_markets),
            "fold_results": fold_results,
            "aggregate": {
                "avg_brier_raw": round(float(avg_raw), 4),
                "avg_brier_platt": round(float(avg_platt), 4),
                "avg_brier_directional": round(float(avg_dir), 4),
                "avg_platt_improvement": round(float(avg_raw - avg_platt), 4),
                "avg_directional_improvement": round(float(avg_raw - avg_dir), 4),
            },
        }

    # -------------------------------------------------------------------
    # Improvement 4: Multi-prompt ensemble
    # -------------------------------------------------------------------

    def run_multiprompt(self, max_markets: int = 100) -> dict:
        """Run multi-prompt ensemble on a subset and measure improvement.

        This costs API calls (3x per market). Use max_markets to limit.
        """
        markets, cache = self._load_data()

        # Only run on markets we already have single-prompt estimates for
        valid = []
        for m in markets:
            est = self._get_cached_estimate(m["question"], cache)
            if est:
                valid.append(m)

        if max_markets > 0:
            valid = valid[:max_markets]

        logger.info(f"Running multi-prompt ensemble on {len(valid)} markets (3 prompts each)")

        estimator = MultiPromptEstimator(api_key=self.api_key)

        single_brier = []
        multi_brier = []
        improvements = []

        for i, m in enumerate(valid):
            question = m["question"]
            actual = m["actual_outcome"]
            actual_binary = 1.0 if actual == "YES_WON" else 0.0

            # Single prompt (existing cache)
            single_est = self._get_cached_estimate(question, cache)
            single_prob = single_est["probability"]
            sb = (single_prob - actual_binary) ** 2
            single_brier.append(sb)

            # Multi-prompt
            mp_est = estimator.estimate(question, m.get("description", ""))
            mp_prob = mp_est["probability"]
            mb = (mp_prob - actual_binary) ** 2
            multi_brier.append(mb)

            improvements.append(sb - mb)

            if (i + 1) % 25 == 0:
                logger.info(
                    f"Progress: {i + 1}/{len(valid)}, "
                    f"single Brier: {np.mean(single_brier):.4f}, "
                    f"multi Brier: {np.mean(multi_brier):.4f}"
                )

        avg_single = float(np.mean(single_brier))
        avg_multi = float(np.mean(multi_brier))

        # Spread analysis — when do prompts disagree?
        spread_data = []
        for m in valid:
            mp_est = estimator.cache.get(m["question"], "base_rate_first")
            # Re-estimate to get spread info
            mp_result = estimator.estimate(m["question"], m.get("description", ""))
            spread_data.append(mp_result["spread"])

        return {
            "n_markets": len(valid),
            "single_prompt_brier": round(avg_single, 4),
            "multi_prompt_brier": round(avg_multi, 4),
            "improvement": round(avg_single - avg_multi, 4),
            "pct_improvement": round((avg_single - avg_multi) / avg_single * 100, 1),
            "avg_prompt_spread": round(float(np.mean(spread_data)), 4),
            "median_prompt_spread": round(float(np.median(spread_data)), 4),
            "high_disagreement_pct": round(
                float(np.mean(np.array(spread_data) > 0.20)) * 100, 1
            ),
        }

    # -------------------------------------------------------------------
    # Combined: run all improvements
    # -------------------------------------------------------------------

    def run_all(self, skip_multiprompt: bool = True) -> dict:
        """Run all improvement tests. Skip multiprompt by default (costs API)."""
        results = {"run_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

        print("\n" + "=" * 80)
        print("  ENHANCED BACKTEST — HIGH-LEVERAGE IMPROVEMENTS")
        print("=" * 80)

        # 1. Direction-specific calibration
        print("\n[1/4] Direction-specific calibration...")
        dir_results = self.run_direction_calibration()
        results["direction_calibration"] = dir_results
        self._print_direction_results(dir_results)

        # 2. Category-specific calibration
        print("\n[2/4] Category-specific calibration...")
        cat_results = self.run_category_calibration()
        results["category_calibration"] = cat_results
        self._print_category_results(cat_results)

        # 3. Walk-forward validation
        print("\n[3/4] Walk-forward temporal validation...")
        wf_results = self.run_walkforward()
        results["walkforward"] = wf_results
        self._print_walkforward_results(wf_results)

        # 4. Multi-prompt (optional)
        if not skip_multiprompt:
            print("\n[4/4] Multi-prompt ensemble...")
            mp_results = self.run_multiprompt()
            results["multiprompt"] = mp_results
            self._print_multiprompt_results(mp_results)
        else:
            print("\n[4/4] Multi-prompt ensemble — SKIPPED (pass --multiprompt to run, costs API)")
            results["multiprompt"] = {"skipped": True}

        # Summary
        self._print_summary(results)

        # Save
        out_path = os.path.join(DATA_DIR, "enhanced_backtest_results.json")
        with open(out_path, "w") as f:
            json.dump(results, f, indent=2, default=str)
        print(f"\nResults saved to {out_path}")

        return results

    def _print_direction_results(self, r: dict):
        print(f"\n  Direction-Specific Calibration (n_train={r['n_train']}, n_test={r['n_test']})")
        print(f"  {'Method':<25s} {'Test Brier':>12s} {'vs Raw':>10s}")
        print(f"  {'-'*25:<25s} {'-'*12:>12s} {'-'*10:>10s}")
        print(f"  {'Raw (uncalibrated)':<25s} {r['test_brier_raw']:>12.4f} {'—':>10s}")
        print(f"  {'Global Platt':<25s} {r['test_brier_global_platt']:>12.4f} "
              f"{r['improvement_global_vs_raw']:>+10.4f}")
        print(f"  {'Directional Platt':<25s} {r['test_brier_directional_platt']:>12.4f} "
              f"{r['improvement_directional_vs_raw']:>+10.4f}")
        delta = r['improvement_directional_vs_global']
        print(f"\n  Directional vs Global improvement: {delta:+.4f} Brier")

        if "trade_sim" in r:
            ts = r["trade_sim"]
            print(f"\n  Trade Simulation (YES thresh=15%, NO thresh=5%):")
            print(f"  {'Strategy':<25s} {'Trades':>7s} {'WinRate':>8s} {'P&L':>10s} "
                  f"{'YES_WR':>7s} {'NO_WR':>7s} {'ARR@5':>8s}")
            for key in ["baseline", "global_platt", "directional_platt"]:
                s = ts[key]
                print(f"  {s['label']:<25s} {s['trades']:>7d} {s['win_rate']:>7.1%} "
                      f"${s['total_pnl']:>9.2f} {s['yes_win_rate']:>6.1%} "
                      f"{s['no_win_rate']:>6.1%} {s['arr_5']:>+7.0f}%")

    def _print_category_results(self, r: dict):
        print(f"\n  Category Calibration (n_train={r['n_train']}, n_test={r['n_test']})")
        print(f"  Category distribution: {r['category_distribution']}")
        print(f"\n  {'Method':<25s} {'Test Brier':>12s} {'vs Raw':>10s}")
        print(f"  {'-'*25:<25s} {'-'*12:>12s} {'-'*10:>10s}")
        print(f"  {'Raw':<25s} {r['test_brier_raw']:>12.4f} {'—':>10s}")
        print(f"  {'Global Platt':<25s} {r['test_brier_global_platt']:>12.4f} "
              f"{r.get('improvement_category_vs_raw', 0) - r.get('improvement_category_vs_global', 0):>+10.4f}")
        print(f"  {'Category Platt':<25s} {r['test_brier_category_platt']:>12.4f} "
              f"{r['improvement_category_vs_raw']:>+10.4f}")

        if r.get("per_category_test_brier"):
            print(f"\n  Per-category test Brier:")
            print(f"  {'Category':<20s} {'N':>5s} {'Raw':>8s} {'Global':>8s} {'Cat-Spec':>8s} {'Delta':>8s}")
            for cat, stats in sorted(r["per_category_test_brier"].items(), key=lambda x: -x[1]["n"]):
                delta = stats["brier_global"] - stats["brier_category"]
                print(f"  {cat:<20s} {stats['n']:>5d} {stats['brier_raw']:>8.4f} "
                      f"{stats['brier_global']:>8.4f} {stats['brier_category']:>8.4f} {delta:>+8.4f}")

    def _print_walkforward_results(self, r: dict):
        print(f"\n  Walk-Forward Temporal Validation ({r['n_folds']} folds, {r['total_valid_markets']} markets)")
        print(f"  {'Fold':>5s} {'Train':>7s} {'Test':>6s} {'Period':>30s} "
              f"{'Raw':>8s} {'Platt':>8s} {'Dir':>8s} {'Improve':>8s}")
        for f in r["fold_results"]:
            print(f"  {f['fold']:>5d} {f['n_train']:>7d} {f['n_test']:>6d} "
                  f"{f['test_period']:>30s} {f['test_brier_raw']:>8.4f} "
                  f"{f['test_brier_platt']:>8.4f} {f['test_brier_directional']:>8.4f} "
                  f"{f['directional_improvement']:>+8.4f}")

        agg = r["aggregate"]
        print(f"\n  Average across folds:")
        print(f"    Raw Brier:          {agg['avg_brier_raw']:.4f}")
        print(f"    Platt Brier:        {agg['avg_brier_platt']:.4f} ({agg['avg_platt_improvement']:+.4f})")
        print(f"    Directional Brier:  {agg['avg_brier_directional']:.4f} ({agg['avg_directional_improvement']:+.4f})")

    def _print_multiprompt_results(self, r: dict):
        print(f"\n  Multi-Prompt Ensemble ({r['n_markets']} markets, 3 prompts each)")
        print(f"  Single-prompt Brier:    {r['single_prompt_brier']:.4f}")
        print(f"  Multi-prompt Brier:     {r['multi_prompt_brier']:.4f}")
        print(f"  Improvement:            {r['improvement']:+.4f} ({r['pct_improvement']:+.1f}%)")
        print(f"  Avg prompt spread:      {r['avg_prompt_spread']:.4f}")
        print(f"  High disagreement (>20%): {r['high_disagreement_pct']:.1f}% of markets")

    def _print_summary(self, results: dict):
        print("\n" + "=" * 80)
        print("  SUMMARY — IMPROVEMENT RANKING")
        print("=" * 80)

        improvements = []

        if "direction_calibration" in results:
            r = results["direction_calibration"]
            improvements.append((
                "Direction-specific Platt",
                r["improvement_directional_vs_raw"],
                r["improvement_directional_vs_global"],
                "Separate YES/NO calibrators",
            ))

        if "category_calibration" in results:
            r = results["category_calibration"]
            improvements.append((
                "Category-specific Platt",
                r["improvement_category_vs_raw"],
                r["improvement_category_vs_global"],
                "Per-category calibrators",
            ))

        if "walkforward" in results and "aggregate" in results["walkforward"]:
            r = results["walkforward"]["aggregate"]
            improvements.append((
                "Walk-forward directional",
                r["avg_directional_improvement"],
                r["avg_directional_improvement"] - r["avg_platt_improvement"],
                "Temporal train→test, direction-specific",
            ))

        if "multiprompt" in results and not results["multiprompt"].get("skipped"):
            r = results["multiprompt"]
            improvements.append((
                "Multi-prompt ensemble",
                r["improvement"],
                r["improvement"],
                "3 diverse prompts averaged",
            ))

        # Sort by vs-raw improvement
        improvements.sort(key=lambda x: -x[1])

        print(f"\n  {'Method':<30s} {'Brier vs Raw':>14s} {'vs Global':>12s} {'Description':<35s}")
        print(f"  {'-'*30:<30s} {'-'*14:>14s} {'-'*12:>12s} {'-'*35:<35s}")
        for name, vs_raw, vs_global, desc in improvements:
            print(f"  {name:<30s} {vs_raw:>+14.4f} {vs_global:>+12.4f} {desc:<35s}")

        print(f"\n  KEY: Positive improvement = lower Brier = better calibration")
        print(f"  Baseline raw Brier ≈ 0.239, random = 0.250, good = 0.200, great = 0.179")
        print("=" * 80)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Enhanced Backtest System")
    parser.add_argument("--mode", choices=["all", "direction", "category", "walkforward", "multiprompt"],
                        default="all", help="Which improvement to test")
    parser.add_argument("--multiprompt", action="store_true",
                        help="Include multi-prompt tests (costs API calls)")
    parser.add_argument("--max-markets", type=int, default=100,
                        help="Max markets for multi-prompt (default 100)")
    args = parser.parse_args()

    engine = EnhancedBacktestEngine()

    if args.mode == "direction":
        r = engine.run_direction_calibration()
        engine._print_direction_results(r)
    elif args.mode == "category":
        r = engine.run_category_calibration()
        engine._print_category_results(r)
    elif args.mode == "walkforward":
        r = engine.run_walkforward()
        engine._print_walkforward_results(r)
    elif args.mode == "multiprompt":
        r = engine.run_multiprompt(max_markets=args.max_markets)
        engine._print_multiprompt_results(r)
    else:
        engine.run_all(skip_multiprompt=not args.multiprompt)


if __name__ == "__main__":
    main()
