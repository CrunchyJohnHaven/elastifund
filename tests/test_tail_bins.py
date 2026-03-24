from __future__ import annotations

from signals.tail_bins import assign_tail_bin, default_kalshi_longshot_bins, posterior_from_results, robust_kelly_fraction


def test_assign_tail_bin_matches_expected_range() -> None:
    bins = default_kalshi_longshot_bins()
    match = assign_tail_bin(yes_price=0.03, specs=bins)
    assert match is not None
    assert match.bin_id == "yes_2_5c"


def test_posterior_from_results_shrinks_sparse_data() -> None:
    posterior = posterior_from_results(wins=8, losses=1, alpha_prior=8.0, beta_prior=2.0)
    assert 0.7 < posterior.mean < 0.9
    assert posterior.lower_bound < posterior.mean
    assert posterior.upper_bound > posterior.mean


def test_robust_kelly_fraction_clips_negative_to_zero() -> None:
    assert robust_kelly_fraction(p_lower=0.80, entry_price=0.95) == 0.0
    assert robust_kelly_fraction(p_lower=0.99, entry_price=0.95) > 0.0

