"""Discrete transfer-entropy helpers for cross-asset information-flow gating."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import math
from typing import Iterable


def _safe_log2(value: float) -> float:
    if value <= 0.0:
        return float("-inf")
    return math.log2(value)


def _quantile(values: list[float], q: float, default: float) -> float:
    if not values:
        return float(default)
    if len(values) == 1:
        return float(values[0])
    ordered = sorted(float(value) for value in values)
    clamped = max(0.0, min(1.0, float(q)))
    index = clamped * (len(ordered) - 1)
    low = int(math.floor(index))
    high = int(math.ceil(index))
    if low == high:
        return float(ordered[low])
    weight = index - low
    return float((ordered[low] * (1.0 - weight)) + (ordered[high] * weight))


def _conditional_shannon_entropy(
    outcomes: list[int],
    contexts: list[tuple[int, ...]],
) -> float:
    if not outcomes or len(outcomes) != len(contexts):
        return 0.0
    total = float(len(outcomes))
    by_context: dict[tuple[int, ...], dict[int, int]] = defaultdict(lambda: defaultdict(int))
    context_totals: dict[tuple[int, ...], int] = defaultdict(int)
    for outcome, context in zip(outcomes, contexts):
        by_context[context][int(outcome)] += 1
        context_totals[context] += 1

    entropy = 0.0
    for context, counts in by_context.items():
        context_total = float(context_totals[context])
        if context_total <= 0.0:
            continue
        context_weight = context_total / total
        inner = 0.0
        for count in counts.values():
            probability = float(count) / context_total
            if probability > 0.0:
                inner -= probability * _safe_log2(probability)
        entropy += context_weight * inner
    return max(0.0, float(entropy))


def _conditional_renyi_entropy(
    outcomes: list[int],
    contexts: list[tuple[int, ...]],
    *,
    alpha: float,
) -> float:
    if not outcomes or len(outcomes) != len(contexts):
        return 0.0
    if abs(float(alpha) - 1.0) <= 1e-9:
        return _conditional_shannon_entropy(outcomes, contexts)

    total = float(len(outcomes))
    by_context: dict[tuple[int, ...], dict[int, int]] = defaultdict(lambda: defaultdict(int))
    context_totals: dict[tuple[int, ...], int] = defaultdict(int)
    for outcome, context in zip(outcomes, contexts):
        by_context[context][int(outcome)] += 1
        context_totals[context] += 1

    accumulator = 0.0
    for context, counts in by_context.items():
        context_total = float(context_totals[context])
        if context_total <= 0.0:
            continue
        context_weight = context_total / total
        power_sum = 0.0
        for count in counts.values():
            probability = float(count) / context_total
            if probability > 0.0:
                power_sum += probability ** float(alpha)
        accumulator += context_weight * power_sum

    if accumulator <= 0.0:
        return 0.0
    return max(0.0, (1.0 / (1.0 - float(alpha))) * _safe_log2(accumulator))


def _discretization_threshold(values: Iterable[float]) -> float:
    ordered = [abs(float(value)) for value in values]
    return max(1e-6, _quantile(ordered, 0.35, 1e-3))


def discretize_returns(
    values: Iterable[float],
    *,
    threshold: float | None = None,
) -> list[int]:
    raw_values = [float(value) for value in values]
    gate = max(1e-6, float(threshold) if threshold is not None else _discretization_threshold(raw_values))
    buckets: list[int] = []
    for value in raw_values:
        if value >= gate:
            buckets.append(1)
        elif value <= -gate:
            buckets.append(-1)
        else:
            buckets.append(0)
    return buckets


def _ordinal_pattern(window: list[float]) -> tuple[int, ...]:
    pairs = sorted(enumerate(window), key=lambda item: (float(item[1]), int(item[0])))
    ranks = [0] * len(window)
    for rank, (index, _value) in enumerate(pairs):
        ranks[index] = rank
    return tuple(ranks)


def symbolize_ordinal_patterns(
    values: Iterable[float],
    *,
    pattern_size: int = 3,
) -> list[int]:
    ordered = [float(value) for value in values]
    size = max(2, int(pattern_size))
    if len(ordered) < size:
        return []
    pattern_ids: dict[tuple[int, ...], int] = {}
    symbols: list[int] = []
    for start in range(len(ordered) - size + 1):
        pattern = _ordinal_pattern(ordered[start : start + size])
        symbol = pattern_ids.setdefault(pattern, len(pattern_ids))
        symbols.append(symbol)
    return symbols


@dataclass(frozen=True)
class TransferEntropyEstimate:
    forward_bits: float
    reverse_bits: float
    forward_minus_reverse_bits: float
    renyi_forward_bits: float
    renyi_reverse_bits: float
    renyi_forward_minus_reverse_bits: float
    symbolic_forward_bits: float
    symbolic_reverse_bits: float
    symbolic_forward_minus_reverse_bits: float
    sample_count: int
    symbolic_sample_count: int
    source_threshold: float
    target_threshold: float
    renyi_alpha: float
    symbolic_pattern_size: int


def estimate_bidirectional_transfer_entropy(
    source_returns: Iterable[float],
    target_returns: Iterable[float],
    *,
    renyi_alpha: float = 2.0,
    symbolic_pattern_size: int = 3,
) -> TransferEntropyEstimate:
    source_values = [float(value) for value in source_returns]
    target_values = [float(value) for value in target_returns]
    sample_count = min(len(source_values), len(target_values))
    if sample_count < 3:
        return TransferEntropyEstimate(
            forward_bits=0.0,
            reverse_bits=0.0,
            forward_minus_reverse_bits=0.0,
            renyi_forward_bits=0.0,
            renyi_reverse_bits=0.0,
            renyi_forward_minus_reverse_bits=0.0,
            symbolic_forward_bits=0.0,
            symbolic_reverse_bits=0.0,
            symbolic_forward_minus_reverse_bits=0.0,
            sample_count=sample_count,
            symbolic_sample_count=0,
            source_threshold=0.0,
            target_threshold=0.0,
            renyi_alpha=float(renyi_alpha),
            symbolic_pattern_size=max(2, int(symbolic_pattern_size)),
        )

    source_values = source_values[:sample_count]
    target_values = target_values[:sample_count]
    source_threshold = _discretization_threshold(source_values)
    target_threshold = _discretization_threshold(target_values)
    source_states = discretize_returns(source_values, threshold=source_threshold)
    target_states = discretize_returns(target_values, threshold=target_threshold)

    target_now = target_states[1:]
    target_prev = target_states[:-1]
    source_now = source_states[1:]

    source_target_now = source_states[1:]
    source_prev = source_states[:-1]
    target_source_now = target_states[1:]

    forward_shannon = _conditional_shannon_entropy(target_now, [(state,) for state in target_prev]) - _conditional_shannon_entropy(
        target_now,
        list(zip(target_prev, source_now)),
    )
    reverse_shannon = _conditional_shannon_entropy(source_target_now, [(state,) for state in source_prev]) - _conditional_shannon_entropy(
        source_target_now,
        list(zip(source_prev, target_source_now)),
    )
    forward_renyi = _conditional_renyi_entropy(
        target_now,
        [(state,) for state in target_prev],
        alpha=renyi_alpha,
    ) - _conditional_renyi_entropy(
        target_now,
        list(zip(target_prev, source_now)),
        alpha=renyi_alpha,
    )
    reverse_renyi = _conditional_renyi_entropy(
        source_target_now,
        [(state,) for state in source_prev],
        alpha=renyi_alpha,
    ) - _conditional_renyi_entropy(
        source_target_now,
        list(zip(source_prev, target_source_now)),
        alpha=renyi_alpha,
    )

    forward_bits = max(0.0, float(forward_shannon))
    reverse_bits = max(0.0, float(reverse_shannon))
    renyi_forward_bits = max(0.0, float(forward_renyi))
    renyi_reverse_bits = max(0.0, float(reverse_renyi))
    pattern_size = max(2, int(symbolic_pattern_size))
    source_symbols = symbolize_ordinal_patterns(source_values, pattern_size=pattern_size)
    target_symbols = symbolize_ordinal_patterns(target_values, pattern_size=pattern_size)
    symbolic_sample_count = min(len(source_symbols), len(target_symbols))
    symbolic_forward_bits = 0.0
    symbolic_reverse_bits = 0.0
    if symbolic_sample_count >= 2:
        source_symbols = source_symbols[:symbolic_sample_count]
        target_symbols = target_symbols[:symbolic_sample_count]
        target_symbol_now = target_symbols[1:]
        target_symbol_prev = target_symbols[:-1]
        source_symbol_now = source_symbols[1:]
        source_symbol_prev = source_symbols[:-1]

        symbolic_forward = _conditional_shannon_entropy(
            target_symbol_now,
            [(state,) for state in target_symbol_prev],
        ) - _conditional_shannon_entropy(
            target_symbol_now,
            list(zip(target_symbol_prev, source_symbol_now)),
        )
        symbolic_reverse = _conditional_shannon_entropy(
            source_symbol_now,
            [(state,) for state in source_symbol_prev],
        ) - _conditional_shannon_entropy(
            source_symbol_now,
            list(zip(source_symbol_prev, target_symbol_now)),
        )
        symbolic_forward_bits = max(0.0, float(symbolic_forward))
        symbolic_reverse_bits = max(0.0, float(symbolic_reverse))

    return TransferEntropyEstimate(
        forward_bits=forward_bits,
        reverse_bits=reverse_bits,
        forward_minus_reverse_bits=float(forward_bits - reverse_bits),
        renyi_forward_bits=renyi_forward_bits,
        renyi_reverse_bits=renyi_reverse_bits,
        renyi_forward_minus_reverse_bits=float(renyi_forward_bits - renyi_reverse_bits),
        symbolic_forward_bits=symbolic_forward_bits,
        symbolic_reverse_bits=symbolic_reverse_bits,
        symbolic_forward_minus_reverse_bits=float(symbolic_forward_bits - symbolic_reverse_bits),
        sample_count=max(0, sample_count - 1),
        symbolic_sample_count=max(0, symbolic_sample_count - 1),
        source_threshold=float(source_threshold),
        target_threshold=float(target_threshold),
        renyi_alpha=float(renyi_alpha),
        symbolic_pattern_size=pattern_size,
    )
