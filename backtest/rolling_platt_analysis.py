#!/usr/bin/env python3
"""Walk-forward validation for rolling Platt calibration on cached markets."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Iterable, Sequence


def _float_env(name: str, default: str) -> float:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return float(default)
    try:
        return float(raw)
    except ValueError:
        return float(default)


STATIC_A = _float_env("PLATT_A", "0.55")
STATIC_B = _float_env("PLATT_B", "-0.40")


@dataclass(frozen=True)
class ResolvedEstimate:
    market_id: str
    question: str
    end_date: str
    raw_prob: float
    outcome: int
    volume: float = 0.0
    liquidity: float = 0.0


@dataclass(frozen=True)
class VariantResult:
    name: str
    window: int | None
    n_predictions: int
    brier: float
    final_a: float
    final_b: float


def question_cache_key(question: str) -> str:
    return hashlib.sha256(question.encode()).hexdigest()[:16]


def clamp_prob(prob: float) -> float:
    return max(0.001, min(0.999, float(prob)))


def calibrate_probability_with_params(raw_prob: float, a: float, b: float) -> float:
    raw_prob = clamp_prob(raw_prob)
    if abs(raw_prob - 0.5) < 1e-9:
        return 0.5
    if raw_prob < 0.5:
        return 1.0 - calibrate_probability_with_params(1.0 - raw_prob, a, b)
    logit_input = math.log(raw_prob / (1.0 - raw_prob))
    logit_output = max(-30.0, min(30.0, a * logit_input + b))
    calibrated = 1.0 / (1.0 + math.exp(-logit_output))
    return max(0.01, min(0.99, calibrated))


def fit_platt_parameters(
    raw_probs: Sequence[float],
    outcomes: Sequence[int],
    *,
    initial_a: float = STATIC_A,
    initial_b: float = STATIC_B,
) -> tuple[float, float]:
    """Fit Platt parameters in logit space with simple gradient descent."""
    if len(raw_probs) < 20 or len(raw_probs) != len(outcomes):
        return float(initial_a), float(initial_b)

    xs = [math.log(clamp_prob(p) / (1.0 - clamp_prob(p))) for p in raw_probs]
    ys = [1.0 if int(v) == 1 else 0.0 for v in outcomes]

    a = float(initial_a)
    b = float(initial_b)
    lr = 0.08
    l2 = 1e-3
    prev_loss = float("inf")

    for _ in range(300):
        preds = []
        for x in xs:
            z = max(-30.0, min(30.0, a * x + b))
            preds.append(1.0 / (1.0 + math.exp(-z)))

        eps = 1e-9
        loss = (
            -sum(
                y * math.log(p + eps) + (1.0 - y) * math.log(1.0 - p + eps)
                for p, y in zip(preds, ys)
            )
            / len(preds)
        ) + l2 * (a * a + b * b)

        grad_a = (sum((p - y) * x for p, y, x in zip(preds, ys, xs)) / len(preds)) + 2.0 * l2 * a
        grad_b = (sum(p - y for p, y in zip(preds, ys)) / len(preds)) + 2.0 * l2 * b

        cand_a = a - lr * grad_a
        cand_b = b - lr * grad_b

        cand_preds = []
        for x in xs:
            z = max(-30.0, min(30.0, cand_a * x + cand_b))
            cand_preds.append(1.0 / (1.0 + math.exp(-z)))
        cand_loss = (
            -sum(
                y * math.log(p + eps) + (1.0 - y) * math.log(1.0 - p + eps)
                for p, y in zip(cand_preds, ys)
            )
            / len(cand_preds)
        ) + l2 * (cand_a * cand_a + cand_b * cand_b)

        if cand_loss <= loss:
            a, b = cand_a, cand_b
            if abs(prev_loss - cand_loss) < 1e-7:
                break
            prev_loss = cand_loss
        else:
            lr *= 0.5
            if lr < 1e-4:
                break

    return float(a), float(b)


def rolling_platt_fit(
    resolved_markets: Iterable[ResolvedEstimate],
    window: int = 100,
    *,
    initial_a: float = STATIC_A,
    initial_b: float = STATIC_B,
) -> tuple[float, float]:
    """Fit Platt parameters on the most recent N resolved markets."""
    rows = list(resolved_markets)
    if len(rows) < 20:
        return float(initial_a), float(initial_b)

    sample = rows[-max(20, int(window)) :]
    raw_probs = [row.raw_prob for row in sample]
    outcomes = [row.outcome for row in sample]
    return fit_platt_parameters(raw_probs, outcomes, initial_a=initial_a, initial_b=initial_b)


def brier_score(predictions: Sequence[float], outcomes: Sequence[int]) -> float:
    if not predictions or len(predictions) != len(outcomes):
        raise ValueError("predictions/outcomes must be non-empty and aligned")
    return sum((float(p) - float(y)) ** 2 for p, y in zip(predictions, outcomes)) / len(predictions)


def load_resolved_estimates(
    markets_path: str | Path,
    cache_path: str | Path,
    *,
    limit: int = 0,
) -> list[ResolvedEstimate]:
    markets_payload = json.loads(Path(markets_path).read_text())
    cache_payload = json.loads(Path(cache_path).read_text())

    loaded: list[ResolvedEstimate] = []
    for market in markets_payload.get("markets", []):
        question = str(market.get("question", "")).strip()
        if not question:
            continue
        cache_entry = cache_payload.get(question_cache_key(question))
        if not cache_entry:
            continue

        outcome_raw = str(market.get("actual_outcome", "")).upper()
        if outcome_raw not in {"YES_WON", "NO_WON"}:
            continue

        loaded.append(
            ResolvedEstimate(
                market_id=str(market.get("id", "")),
                question=question,
                end_date=str(market.get("end_date", "")),
                raw_prob=float(cache_entry.get("probability", 0.5)),
                outcome=1 if outcome_raw == "YES_WON" else 0,
                volume=float(market.get("volume", 0.0) or 0.0),
                liquidity=float(market.get("liquidity", 0.0) or 0.0),
            )
        )

    loaded.sort(key=lambda row: (row.end_date or "", row.market_id))
    if limit > 0:
        loaded = loaded[:limit]
    return loaded


def evaluate_variant(
    resolved_markets: Sequence[ResolvedEstimate],
    *,
    window: int | None,
    initial_train: int,
    static_a: float = STATIC_A,
    static_b: float = STATIC_B,
) -> VariantResult:
    if len(resolved_markets) <= initial_train:
        raise ValueError("not enough resolved markets for requested train/test split")

    predictions: list[float] = []
    outcomes: list[int] = []
    final_a = float(static_a)
    final_b = float(static_b)

    for idx in range(initial_train, len(resolved_markets)):
        train_rows = resolved_markets[:idx]
        if window is None:
            final_a, final_b = float(static_a), float(static_b)
        else:
            final_a, final_b = rolling_platt_fit(
                train_rows,
                window=window,
                initial_a=static_a,
                initial_b=static_b,
            )

        current = resolved_markets[idx]
        predictions.append(
            calibrate_probability_with_params(current.raw_prob, final_a, final_b)
        )
        outcomes.append(current.outcome)

    name = "static" if window is None else f"rolling_{window}"
    return VariantResult(
        name=name,
        window=window,
        n_predictions=len(predictions),
        brier=round(brier_score(predictions, outcomes), 6),
        final_a=round(final_a, 6),
        final_b=round(final_b, 6),
    )


def run_walk_forward(
    resolved_markets: Sequence[ResolvedEstimate],
    *,
    windows: Sequence[int] = (50, 100, 200),
    initial_train: int = 400,
    static_a: float = STATIC_A,
    static_b: float = STATIC_B,
) -> dict:
    variants = [
        evaluate_variant(
            resolved_markets,
            window=None,
            initial_train=initial_train,
            static_a=static_a,
            static_b=static_b,
        )
    ]
    for window in windows:
        variants.append(
            evaluate_variant(
                resolved_markets,
                window=int(window),
                initial_train=initial_train,
                static_a=static_a,
                static_b=static_b,
            )
        )

    ordered = sorted(variants, key=lambda item: item.brier)
    winner = ordered[0]
    return {
        "dataset_size": len(resolved_markets),
        "initial_train": initial_train,
        "validation_size": len(resolved_markets) - initial_train,
        "static_a": static_a,
        "static_b": static_b,
        "variants": [asdict(result) for result in variants],
        "winner": asdict(winner),
        "winner_is_static": winner.window is None,
    }


def build_markdown_report(payload: dict) -> str:
    lines = [
        "# Adaptive Platt Walk-Forward Validation",
        "",
        f"- Dataset size: {payload['dataset_size']} resolved markets",
        f"- Train split: first {payload['initial_train']} markets",
        f"- Validation split: last {payload['validation_size']} markets",
        f"- Static baseline: A={payload['static_a']:.4f}, B={payload['static_b']:.4f}",
        "",
        "| Variant | Window | OOS Brier | Final A | Final B |",
        "|---|---:|---:|---:|---:|",
    ]

    for variant in payload["variants"]:
        window_label = "static" if variant["window"] is None else str(variant["window"])
        lines.append(
            f"| {variant['name']} | {window_label} | {variant['brier']:.6f} | "
            f"{variant['final_a']:.4f} | {variant['final_b']:.4f} |"
        )

    winner = payload["winner"]
    recommendation = (
        "Keep static Platt in live mode."
        if payload["winner_is_static"]
        else f"Use rolling window {winner['window']} in live mode."
    )
    lines.extend(
        [
            "",
            f"Winner: `{winner['name']}` with OOS Brier `{winner['brier']:.6f}`.",
            recommendation,
            "",
            "Live status: `bot/jj_live.py` already contains an adaptive calibrator, so this report only decides which mode should stay active.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_outputs(payload: dict, report_path: str | Path, json_path: str | Path) -> None:
    report_path = Path(report_path)
    json_path = Path(json_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(build_markdown_report(payload), encoding="utf-8")
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rolling Platt walk-forward validator")
    parser.add_argument("--markets", default="backtest/data/historical_markets_532.json")
    parser.add_argument("--cache", default="backtest/data/claude_cache.json")
    parser.add_argument("--initial-train", type=int, default=400)
    parser.add_argument("--windows", nargs="*", type=int, default=[50, 100, 200])
    parser.add_argument("--report-path", default="reports/adaptive_platt_validation.md")
    parser.add_argument("--json-path", default="reports/adaptive_platt_validation.json")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    resolved_markets = load_resolved_estimates(args.markets, args.cache)
    payload = run_walk_forward(
        resolved_markets,
        windows=args.windows,
        initial_train=args.initial_train,
    )
    write_outputs(payload, args.report_path, args.json_path)
    winner = payload["winner"]
    print(
        f"walk-forward complete | winner={winner['name']} "
        f"brier={winner['brier']:.6f} dataset={payload['dataset_size']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
