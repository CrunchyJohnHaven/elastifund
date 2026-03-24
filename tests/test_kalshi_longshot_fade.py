from __future__ import annotations

from signals.tail_bins import posterior_from_results
from strategies.kalshi_longshot_fade import KalshiLongshotFadeStrategy, KalshiLongshotMarket


def test_objective_longshot_market_can_qualify() -> None:
    strategy = KalshiLongshotFadeStrategy(contracts=100)
    # NO at 97c must clear a very high fee-adjusted breakeven, so the fixture
    # needs a genuinely strong posterior rather than a merely good win rate.
    posterior = posterior_from_results(wins=395, losses=2, alpha_prior=8.0, beta_prior=2.0)
    market = KalshiLongshotMarket(
        ticker="TAIL-1",
        title="Will X happen by Friday?",
        yes_ask=0.03,
        no_ask=0.97,
        volume=500.0,
        open_interest=500.0,
        rules_text="Resolves YES if the official BLS release states X.",
        settlement_source="BLS",
    )

    decision = strategy.evaluate(market, posterior=posterior)
    assert decision.qualifies is True
    assert decision.bin_id == "yes_2_5c"
    assert decision.traded_side == "NO"
    assert decision.robust_kelly_fraction > 0.0


def test_subjective_rules_are_blocked() -> None:
    strategy = KalshiLongshotFadeStrategy(contracts=100)
    posterior = posterior_from_results(wins=95, losses=2, alpha_prior=8.0, beta_prior=2.0)
    market = KalshiLongshotMarket(
        ticker="TAIL-2",
        title="Will X happen by Friday?",
        yes_ask=0.03,
        no_ask=0.97,
        volume=500.0,
        open_interest=500.0,
        rules_text="Resolves YES if X is widely reported and generally accepted.",
        settlement_source="news desk",
    )

    decision = strategy.evaluate(market, posterior=posterior)
    assert decision.qualifies is False
    assert "subjective_rules" in decision.reasons


def test_posterior_lower_bound_gate_can_reject_market() -> None:
    strategy = KalshiLongshotFadeStrategy(contracts=100)
    posterior = posterior_from_results(wins=2, losses=2, alpha_prior=1.0, beta_prior=1.0)
    market = KalshiLongshotMarket(
        ticker="TAIL-3",
        title="Will X happen by Friday?",
        yes_ask=0.03,
        no_ask=0.97,
        volume=500.0,
        open_interest=500.0,
        rules_text="Resolves YES if the official BLS release states X.",
        settlement_source="BLS",
    )

    decision = strategy.evaluate(market, posterior=posterior)
    assert decision.qualifies is False
    assert "posterior_lower_below_breakeven" in decision.reasons
