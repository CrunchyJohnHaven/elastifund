#!/usr/bin/env python3
"""Adaptive rolling Platt evaluation for Stream 3 (D-12).

This module mirrors the live bot's current Platt transform so the offline
comparison matches runtime behavior. The adaptive branch is intentionally
evaluated as a walk-forward process: for each validation market, fit on the
latest resolved window only, then score the next market out of sample.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import fmean
from typing import Iterable, Sequence

BACKTEST_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BACKTEST_DIR, "data")

DEFAULT_MARKETS_PATH = os.path.join(DATA_DIR, "historical_markets_532.json")
DEFAULT_CACHE_PATH = os.path.join(DATA_DIR, "claude_cache.json")
DEFAULT_OUTPUT_PATH = os.path.join(DATA_DIR, "adaptive_platt_results.json")

STATIC_PLATT_A = 0.5914
STATIC_PLATT_B = -0.3977
DEFAULT_WINDOWS = (50, 100, 200)


@dataclass(frozen=True)
class ResolvedMarket:
    question: str
    raw_prob: float
    outcome: int
    end_date: str | None
    original_index: int


def _cache_key(question: str) -> str:
    return hashlib.sha256(question.encode()).hexdigest()[:16]


def _parse_end_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _sort_key(sample: ResolvedMarket) -> tuple[int, datetime, int]:
    parsed = _parse_end_date(sample.end_date)
    if parsed is None:
        # Missing timestamps are pushed to the end to avoid leaking unknown-future
        # outcomes into earlier windows.
        return (1, datetime.max.replace(tzinfo=timezone.utc), sample.original_index)
    return (0, parsed, sample.original_index)


def load_resolved_markets(
    markets_path: str = DEFAULT_MARKETS_PATH,
    cache_path: str = DEFAULT_CACHE_PATH,
) -> list[ResolvedMarket]:
    """Load resolved markets plus cached raw probabilities in temporal order."""
    with open(markets_path) as f:
        market_payload = json.load(f)
    with open(cache_path) as f:
        cache = json.load(f)

    markets = market_payload["markets"] if isinstance(market_payload, dict) else market_payload

    resolved: list[ResolvedMarket] = []
    for idx, market in enumerate(markets):
        question = market.get("question")
        if not question:
            continue

        est = cache.get(_cache_key(question))
        if not est:
            continue

        outcome_raw = market.get("actual_outcome")
        if outcome_raw not in {"YES_WON", "NO_WON"}:
            continue

        raw_prob = float(est["probability"])
        resolved.append(
            ResolvedMarket(
                question=question,
                raw_prob=raw_prob,
                outcome=1 if outcome_raw == "YES_WON" else 0,
                end_date=market.get("end_date"),
                original_index=idx,
            )
        )

    resolved.sort(key=_sort_key)
    return resolved


def calibrate_probability_with_params(raw_prob: float, a: float, b: float) -> float:
    """Mirror the live bot's current Platt transform exactly."""
    raw_prob = max(0.001, min(0.999, raw_prob))
    if abs(raw_prob - 0.5) < 1e-9:
        return 0.5
    if raw_prob < 0.5:
        return 1.0 - calibrate_probability_with_params(1.0 - raw_prob, a, b)
    logit_input = math.log(raw_prob / (1.0 - raw_prob))
    logit_output = a * logit_input + b
    logit_output = max(-30.0, min(30.0, logit_output))
    calibrated = 1.0 / (1.0 + math.exp(-logit_output))
    return max(0.01, min(0.99, calibrated))


def fit_platt_parameters(
    raw_probs: Sequence[float],
    outcomes: Sequence[int],
    *,
    initial_a: float = STATIC_PLATT_A,
    initial_b: float = STATIC_PLATT_B,
    max_iter: int = 300,
    learning_rate: float = 0.08,
    l2_penalty: float = 1e-3,
) -> tuple[float, float]:
    """Fit Platt A/B on the supplied history with light regularization."""
    if len(raw_probs) < 20 or len(raw_probs) != len(outcomes):
        return (float(initial_a), float(initial_b))

    x = [
        math.log(max(0.001, min(0.999, prob)) / (1.0 - max(0.001, min(0.999, prob))))
        for prob in raw_probs
    ]
    y = [1.0 if int(value) == 1 else 0.0 for value in outcomes]

    a = float(initial_a)
    b = float(initial_b)
    lr = float(learning_rate)
    prev_loss = float("inf")

    for _ in range(max_iter):
        preds = []
        for feature in x:
            score = max(-30.0, min(30.0, a * feature + b))
            preds.append(1.0 / (1.0 + math.exp(-score)))

        eps = 1e-9
        loss = -fmean(
            yi * math.log(pi + eps) + (1.0 - yi) * math.log(1.0 - pi + eps)
            for yi, pi in zip(y, preds)
        ) + l2_penalty * (a * a + b * b)

        grad_a = fmean((pi - yi) * feature for pi, yi, feature in zip(preds, y, x))
        grad_b = fmean(pi - yi for pi, yi in zip(preds, y))
        grad_a += 2.0 * l2_penalty * a
        grad_b += 2.0 * l2_penalty * b

        next_a = a - lr * grad_a
        next_b = b - lr * grad_b
        if loss > prev_loss + 1e-8:
            lr *= 0.5
            if lr < 1e-4:
                break
            continue

        a = next_a
        b = next_b
        prev_loss = loss

    return (float(a), float(b))


def rolling_platt_fit(
    resolved_markets: Sequence[ResolvedMarket],
    window: int = 100,
    *,
    min_samples: int = 50,
    default_a: float = STATIC_PLATT_A,
    default_b: float = STATIC_PLATT_B,
) -> tuple[float, float]:
    """Fit Platt parameters on the latest resolved window."""
    bounded_window = max(1, int(window))
    history = list(resolved_markets)[-bounded_window:]
    if len(history) < max(20, int(min_samples)):
        return (float(default_a), float(default_b))
    return fit_platt_parameters(
        [sample.raw_prob for sample in history],
        [sample.outcome for sample in history],
        initial_a=default_a,
        initial_b=default_b,
    )


def _brier_error(raw_prob: float, outcome: int, a: float, b: float) -> float:
    calibrated = calibrate_probability_with_params(raw_prob, a, b)
    return (calibrated - float(outcome)) ** 2


def _mean_or_none(values: Iterable[float]) -> float | None:
    values = list(values)
    if not values:
        return None
    return float(fmean(values))


def _last_known_end_date(samples: Sequence[ResolvedMarket]) -> str | None:
    for sample in reversed(samples):
        if sample.end_date not in (None, ""):
            return sample.end_date
    return None


def _first_known_end_date(samples: Sequence[ResolvedMarket]) -> str | None:
    for sample in samples:
        if sample.end_date not in (None, ""):
            return sample.end_date
    return None


def evaluate_adaptive_platt(
    resolved_markets: Sequence[ResolvedMarket],
    *,
    train_size: int = 400,
    windows: Sequence[int] = DEFAULT_WINDOWS,
    min_samples: int = 50,
    static_a: float = STATIC_PLATT_A,
    static_b: float = STATIC_PLATT_B,
) -> dict:
    """Compare static Platt versus rolling variants on a walk-forward holdout."""
    ordered = list(resolved_markets)
    if len(ordered) <= train_size:
        raise ValueError(
            f"Need more than train_size={train_size} markets, got {len(ordered)}."
        )

    validation = ordered[train_size:]
    variants: list[dict] = []

    static_errors = [
        _brier_error(sample.raw_prob, sample.outcome, static_a, static_b)
        for sample in validation
    ]
    variants.append(
        {
            "name": "static",
            "window": None,
            "brier": float(fmean(static_errors)),
            "mean_a": float(static_a),
            "mean_b": float(static_b),
            "fallback_predictions": 0,
        }
    )

    for window in windows:
        errors: list[float] = []
        fitted_params: list[tuple[float, float]] = []
        fallback_predictions = 0

        for idx in range(train_size, len(ordered)):
            params = rolling_platt_fit(
                ordered[:idx],
                window=window,
                min_samples=min_samples,
                default_a=static_a,
                default_b=static_b,
            )
            if params == (float(static_a), float(static_b)) and min(window, idx) < max(20, int(min_samples)):
                fallback_predictions += 1
            fitted_params.append(params)
            target = ordered[idx]
            errors.append(_brier_error(target.raw_prob, target.outcome, *params))

        variants.append(
            {
                "name": f"rolling_{window}",
                "window": int(window),
                "brier": float(fmean(errors)),
                "mean_a": _mean_or_none(a for a, _ in fitted_params),
                "mean_b": _mean_or_none(b for _, b in fitted_params),
                "fallback_predictions": fallback_predictions,
            }
        )

    winner = min(variants, key=lambda row: row["brier"])
    baseline_brier = variants[0]["brier"]
    for row in variants:
        row["delta_vs_static"] = round(row["brier"] - baseline_brier, 6)

    missing_end_dates = sum(1 for sample in ordered if sample.end_date in (None, ""))

    return {
        "dataset": {
            "markets": len(ordered),
            "train_size": train_size,
            "validation_size": len(validation),
            "missing_end_dates": missing_end_dates,
            "train_end_date": _last_known_end_date(ordered[:train_size]),
            "validation_start_date": _first_known_end_date(validation),
            "validation_end_date": _last_known_end_date(validation),
        },
        "static_params": {"A": static_a, "B": static_b},
        "variants": variants,
        "winner": winner["name"],
        "recommendation": (
            "keep_static"
            if winner["name"] == "static"
            else f"deploy_{winner['name']}"
        ),
    }


def _format_table(result: dict) -> str:
    lines = [
        "Variant       Window  Brier     DeltaVsStatic  MeanA   MeanB",
        "------------  ------  --------  -------------  ------  ------",
    ]
    for row in result["variants"]:
        window = "-" if row["window"] is None else str(row["window"])
        lines.append(
            f"{row['name']:<12}  {window:>6}  {row['brier']:.6f}  "
            f"{row['delta_vs_static']:+.6f}      {row['mean_a']:.4f}  {row['mean_b']:.4f}"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate rolling Platt calibration.")
    parser.add_argument("--markets", default=DEFAULT_MARKETS_PATH, help="Historical markets JSON.")
    parser.add_argument("--cache", default=DEFAULT_CACHE_PATH, help="Cached Claude probabilities JSON.")
    parser.add_argument("--train-size", type=int, default=400, help="Number of leading markets to use as initial history.")
    parser.add_argument(
        "--windows",
        default="50,100,200",
        help="Comma-separated rolling windows to evaluate.",
    )
    parser.add_argument("--min-samples", type=int, default=50, help="Minimum history required before fitting rolling params.")
    parser.add_argument("--output", default=DEFAULT_OUTPUT_PATH, help="Where to write the JSON report.")
    args = parser.parse_args()

    windows = tuple(int(chunk) for chunk in args.windows.split(",") if chunk.strip())
    resolved = load_resolved_markets(args.markets, args.cache)
    result = evaluate_adaptive_platt(
        resolved,
        train_size=args.train_size,
        windows=windows,
        min_samples=args.min_samples,
    )

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(result, f, indent=2, sort_keys=True)

    print(_format_table(result))
    print(f"\nWinner: {result['winner']} ({result['recommendation']})")
    print(f"Saved report to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
