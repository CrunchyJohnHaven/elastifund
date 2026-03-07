"""Sequential confidence calibration for fast-market strategy signals."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CalibrationSummary:
    applied: bool
    method: str
    avg_raw_confidence: float
    avg_calibrated_confidence: float
    mean_abs_adjustment: float


def _clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _isotonic_non_decreasing(values: list[float], weights: list[float]) -> list[float]:
    """Pool-adjacent-violators algorithm (PAVA) for monotone calibration curves."""
    if not values:
        return []

    blocks: list[dict[str, float | int]] = []
    for idx, value in enumerate(values):
        weight = max(1e-6, float(weights[idx]))
        blocks.append(
            {
                "start": idx,
                "end": idx,
                "sum_weight": weight,
                "sum_value_weight": weight * float(value),
            }
        )

        while len(blocks) >= 2:
            prev = blocks[-2]
            curr = blocks[-1]
            prev_avg = float(prev["sum_value_weight"]) / float(prev["sum_weight"])
            curr_avg = float(curr["sum_value_weight"]) / float(curr["sum_weight"])
            if prev_avg <= curr_avg:
                break

            merged = {
                "start": int(prev["start"]),
                "end": int(curr["end"]),
                "sum_weight": float(prev["sum_weight"]) + float(curr["sum_weight"]),
                "sum_value_weight": float(prev["sum_value_weight"]) + float(curr["sum_value_weight"]),
            }
            blocks.pop()
            blocks.pop()
            blocks.append(merged)

    output = [0.0] * len(values)
    for block in blocks:
        mean_value = float(block["sum_value_weight"]) / max(float(block["sum_weight"]), 1e-6)
        for idx in range(int(block["start"]), int(block["end"]) + 1):
            output[idx] = mean_value
    return output


def sequential_bayes_isotonic(
    raw_confidences: list[float],
    outcomes: list[bool],
    *,
    bins: int,
    prior_strength: float,
    min_history: int,
    floor: float,
    ceiling: float,
) -> tuple[list[float], CalibrationSummary]:
    """Calibrate confidence scores using only historical outcomes up to each signal."""
    n = min(len(raw_confidences), len(outcomes))
    if n == 0:
        return (
            [],
            CalibrationSummary(
                applied=False,
                method="none",
                avg_raw_confidence=0.0,
                avg_calibrated_confidence=0.0,
                mean_abs_adjustment=0.0,
            ),
        )

    bucket_count = max(2, int(bins))
    prior_strength = max(0.0, float(prior_strength))
    min_history = max(0, int(min_history))
    floor = _clip(float(floor), 0.0, 1.0)
    ceiling = _clip(float(ceiling), floor, 1.0)

    bin_wins = [0.0] * bucket_count
    bin_counts = [0.0] * bucket_count
    global_wins = 0.0
    global_count = 0.0

    calibrated: list[float] = []
    raw_trimmed: list[float] = []

    for idx in range(n):
        raw = _clip(float(raw_confidences[idx]), floor, ceiling)
        raw_trimmed.append(raw)
        bucket = min(bucket_count - 1, max(0, int(raw * bucket_count)))

        if global_count > 0:
            prior_mean = global_wins / global_count
        else:
            prior_mean = raw
        prior_mean = _clip(prior_mean, floor, ceiling)

        alpha = prior_strength * prior_mean
        beta = prior_strength * (1.0 - prior_mean)

        bucket_rates: list[float] = []
        bucket_weights: list[float] = []
        for b in range(bucket_count):
            denom = bin_counts[b] + alpha + beta
            if denom <= 0:
                rate = prior_mean
            else:
                rate = (bin_wins[b] + alpha) / denom
            bucket_rates.append(_clip(rate, floor, ceiling))
            bucket_weights.append(bin_counts[b] + prior_strength + 1e-6)

        monotone_curve = _isotonic_non_decreasing(bucket_rates, bucket_weights)
        calibrated_prob = _clip(monotone_curve[bucket], floor, ceiling)

        if min_history > 0 and global_count < min_history:
            blend = global_count / min_history
            calibrated_prob = _clip(((1.0 - blend) * raw) + (blend * calibrated_prob), floor, ceiling)

        calibrated.append(calibrated_prob)

        win = 1.0 if outcomes[idx] else 0.0
        bin_counts[bucket] += 1.0
        bin_wins[bucket] += win
        global_count += 1.0
        global_wins += win

    avg_raw = sum(raw_trimmed) / len(raw_trimmed)
    avg_cal = sum(calibrated) / len(calibrated)
    avg_adj = sum(abs(a - b) for a, b in zip(raw_trimmed, calibrated, strict=False)) / len(calibrated)

    return (
        calibrated,
        CalibrationSummary(
            applied=True,
            method="sequential_bayes_isotonic",
            avg_raw_confidence=avg_raw,
            avg_calibrated_confidence=avg_cal,
            mean_abs_adjustment=avg_adj,
        ),
    )
