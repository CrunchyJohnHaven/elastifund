from __future__ import annotations

from src.transfer_entropy import estimate_bidirectional_transfer_entropy


def test_transfer_entropy_detects_information_flow_on_dependent_series() -> None:
    source = [0.02 if idx % 6 in {0, 1, 2} else -0.02 for idx in range(600)]
    target: list[float] = []
    prior = 0.0
    for idx, value in enumerate(source):
        if idx % 5 == 0:
            current = value
        else:
            current = value if prior >= 0.0 else (value * 0.5)
        target.append(current)
        prior = current

    estimate = estimate_bidirectional_transfer_entropy(source, target)

    assert estimate.sample_count > 100
    assert estimate.forward_bits > 0.0
    assert estimate.renyi_forward_bits > 0.0
    assert estimate.symbolic_sample_count > 100
    assert estimate.symbolic_forward_bits > 0.0


def test_transfer_entropy_stays_near_zero_on_independent_series() -> None:
    source = [0.02 if idx % 2 == 0 else -0.02 for idx in range(600)]
    target = [0.01 if idx % 3 == 0 else -0.01 for idx in range(600)]

    estimate = estimate_bidirectional_transfer_entropy(source, target)

    assert estimate.forward_bits < 0.01
    assert estimate.renyi_forward_bits < 0.01
    assert estimate.symbolic_forward_bits < 0.05


def test_transfer_entropy_exposes_symbolic_directional_edge() -> None:
    source = [0.02 if idx % 6 in {0, 1, 2} else -0.02 for idx in range(720)]
    target: list[float] = []
    for idx in range(len(source)):
        target.append(source[max(0, idx - 1)])

    estimate = estimate_bidirectional_transfer_entropy(source, target, symbolic_pattern_size=4)

    assert estimate.symbolic_pattern_size == 4
    assert estimate.symbolic_forward_bits > 0.0
    assert estimate.symbolic_forward_minus_reverse_bits >= 0.0
