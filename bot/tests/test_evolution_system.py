"""Tests for the self-improving evolution architecture."""
import json
import math
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from bot.strategy_genome import GenomeFactory, StrategyGenome, PRESETS, build_gene_catalog, GeneType
from bot.bayesian_promoter import LogGrowthPosterior, ThompsonAllocator, NicheScore, OpportunityLedger, OpportunityRecord
from bot.tournament_engine import TournamentEngine, _run_backtest, _generate_composite_signal, _binomial_p
from bot.canonical_event import CanonicalEventKey, SettlementSource, CrossVenueRegistry, VenueContract, Venue


class TestStrategyGenome:
    def test_gene_catalog_completeness(self):
        catalog = build_gene_catalog()
        assert len(catalog) >= 30
        types = {g.gene_type for g in catalog.values()}
        assert GeneType.SIGNAL in types
        assert GeneType.FILTER in types
        assert GeneType.SIZING in types
        assert GeneType.EXIT in types
        assert GeneType.META in types

    def test_random_genome_valid(self):
        factory = GenomeFactory(seed=42)
        g = factory.random_genome()
        assert len(g.genes) > 0
        assert g.genome_id.startswith("G")
        # At least 2 signal sources active
        active = sum(1 for k, gene in g.genes.items() if k.startswith("w_") and gene.value > 0.1)
        assert active >= 2

    def test_mutation_preserves_bounds(self):
        factory = GenomeFactory(seed=42)
        g = factory.random_genome()
        for _ in range(20):
            m = factory.mutate(g, sigma=0.5)  # Very high sigma
            for name, gene in m.genes.items():
                assert gene.value >= gene.lower, f"{name}: {gene.value} < {gene.lower}"
                assert gene.value <= gene.upper, f"{name}: {gene.value} > {gene.upper}"

    def test_crossover_produces_child(self):
        factory = GenomeFactory(seed=42)
        p1 = factory.random_genome()
        p2 = factory.random_genome()
        child = factory.crossover(p1, p2)
        assert len(child.parent_ids) == 2
        assert child.generation > 0

    def test_presets_are_valid(self):
        factory = GenomeFactory(seed=42)
        for name, fn in PRESETS.items():
            params = fn()
            genome = factory.from_params(params, f"test_{name}")
            assert len(genome.genes) > 0

    def test_fingerprint_deterministic(self):
        factory = GenomeFactory(seed=42)
        g1 = factory.from_params(PRESETS["btc5_down_bias"]())
        g2 = factory.from_params(PRESETS["btc5_down_bias"]())
        assert g1.fingerprint == g2.fingerprint

    def test_focused_mutation(self):
        factory = GenomeFactory(seed=42)
        g = factory.random_genome()
        original_signal_values = {k: g.genes[k].value for k in g.genes if g.genes[k].gene_type == GeneType.FILTER}
        m = factory.focused_mutation(g, GeneType.SIGNAL, sigma=0.5)
        # Filter genes should be unchanged (mostly)
        filter_unchanged = sum(
            1 for k in original_signal_values
            if abs(m.genes[k].value - original_signal_values[k]) < 0.001
        )
        # Some filter genes should be unchanged (focused mutation only changes target type)
        assert filter_unchanged > 0


class TestBayesianPromoter:
    def test_prior_is_uninformative(self):
        post = LogGrowthPosterior()
        assert abs(post.prob_positive() - 0.5) < 0.01

    def test_winning_trades_increase_prob(self):
        post = LogGrowthPosterior()
        for _ in range(20):
            post.update(math.log(1.05))
        assert post.prob_positive() > 0.95

    def test_losing_trades_decrease_prob(self):
        post = LogGrowthPosterior()
        for _ in range(20):
            post.update(math.log(0.95))
        assert post.prob_positive() < 0.05

    def test_credible_interval_contains_mean(self):
        post = LogGrowthPosterior()
        for r in [0.05, -0.03, 0.08, -0.02, 0.04]:
            post.update(math.log(1 + r))
        ci = post.credible_interval(0.90)
        assert ci[0] <= post.posterior_mean <= ci[1]

    def test_thompson_allocator_prefers_winners(self):
        alloc = ThompsonAllocator()
        alloc.register_niche("winner")
        alloc.register_niche("loser")
        for _ in range(30):
            alloc.record_return("winner", 0.10)
            alloc.record_return("loser", -0.05)
        decisions = alloc.get_decisions()
        assert decisions["winner"]["decision"] == "PROMOTE"

    def test_niche_score_positive(self):
        ns = NicheScore(niche_id="test", g_hat=0.02, capital_velocity=5.0)
        assert ns.score > 0

    def test_niche_score_zero_for_negative_growth(self):
        ns = NicheScore(niche_id="test", g_hat=-0.01)
        assert ns.score == 0.0


class TestTournamentEngine:
    def test_binomial_p_coinflip(self):
        # 50 out of 100 at p=0.5 should have large p-value
        p = _binomial_p(100, 50, 0.50)
        assert p > 0.40

    def test_binomial_p_strong_signal(self):
        # 70 out of 100 at p=0.5 should have tiny p-value
        p = _binomial_p(100, 70, 0.50)
        assert p < 0.001

    def test_composite_signal_generation(self):
        market = {
            "sig_mean_reversion": 0.3,
            "sig_book_imbalance": 0.5,
            "sig_cross_timeframe": -0.2,
            "entry_price": 0.7,
            "hour_et": 10,
            "vpin": 0.4,
            "spread": 0.05,
            "book_imbalance": 0.1,
            "outcome": "YES_WON",
        }
        genes = {
            "w_mean_reversion": {"value": 0.8},
            "w_book_imbalance": {"value": 0.9},
            "w_cross_timeframe": {"value": 0.6},
            "w_wallet_flow": {"value": 0.0},
            "w_informed_flow": {"value": 0.0},
            "w_time_of_day": {"value": 0.0},
            "w_vol_regime": {"value": 0.0},
            "w_residual_horizon": {"value": 0.0},
            "w_ml_scanner": {"value": 0.0},
            "w_indicator_consensus": {"value": 0.0},
            "w_chainlink_basis": {"value": 0.0},
            "min_signals_active": {"value": 2},
            "signal_agreement_pct": {"value": 0.5},
        }
        sig = _generate_composite_signal(market, genes)
        assert sig is not None
        assert sig["side"] in ("YES", "NO")

    def test_backtest_with_synthetic_data(self):
        import random
        rng = random.Random(42)
        data = []
        for i in range(100):
            outcome = "YES_WON" if rng.random() > 0.48 else "NO_WON"
            true_dir = 1.0 if outcome == "YES_WON" else -1.0
            data.append({
                "condition_id": f"t_{i}",
                "outcome": outcome,
                "entry_price": rng.uniform(0.4, 0.9),
                "hour_et": rng.randint(0, 23),
                "vpin": rng.uniform(0.1, 0.8),
                "spread": rng.uniform(0.01, 0.2),
                "book_imbalance": rng.gauss(0, 0.3),
                "sig_mean_reversion": max(-1, min(1, true_dir * 0.1 + rng.gauss(0, 0.5))),
                "sig_book_imbalance": max(-1, min(1, true_dir * 0.1 + rng.gauss(0, 0.5))),
                "sig_cross_timeframe": max(-1, min(1, true_dir * 0.1 + rng.gauss(0, 0.5))),
                "sig_wallet_flow": max(-1, min(1, rng.gauss(0, 0.5))),
                "sig_informed_flow": max(-1, min(1, rng.gauss(0, 0.5))),
                "sig_time_of_day": max(-1, min(1, rng.gauss(0, 0.5))),
                "sig_vol_regime": max(-1, min(1, rng.gauss(0, 0.5))),
                "sig_residual_horizon": max(-1, min(1, rng.gauss(0, 0.5))),
                "sig_ml_scanner": max(-1, min(1, rng.gauss(0, 0.5))),
                "sig_indicator_consensus": max(-1, min(1, rng.gauss(0, 0.5))),
                "sig_chainlink_basis": max(-1, min(1, rng.gauss(0, 0.5))),
            })

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            data_path = f.name

        try:
            factory = GenomeFactory(seed=42)
            genome = factory.from_params(PRESETS["conservative_maker"]())
            genome_dict = {
                "genome_id": genome.genome_id,
                "genes": {
                    k: {"value": g.value, "type": g.gene_type.value, "range": [g.lower, g.upper]}
                    for k, g in genome.genes.items()
                },
            }
            result = _run_backtest(genome_dict, data_path, {})
            assert "genome_id" in result
            assert "fitness" in result
            assert "win_rate" in result
        finally:
            os.unlink(data_path)


class TestCanonicalEvent:
    def test_key_deterministic(self):
        k1 = CanonicalEventKey(
            underlying_source=SettlementSource.BINANCE,
            settlement_rule="btc_spot_price",
            time_window_start="2026-03-24T00:00:00Z",
            time_window_end="2026-03-24T00:05:00Z",
            entity="BTC",
        )
        k2 = CanonicalEventKey(
            underlying_source=SettlementSource.BINANCE,
            settlement_rule="btc_spot_price",
            time_window_start="2026-03-24T00:00:00Z",
            time_window_end="2026-03-24T00:05:00Z",
            entity="BTC",
        )
        assert k1.key == k2.key

    def test_different_events_different_keys(self):
        k1 = CanonicalEventKey(
            underlying_source=SettlementSource.BINANCE,
            settlement_rule="btc_spot",
            time_window_start="2026-03-24",
            time_window_end="2026-03-24",
            entity="BTC",
        )
        k2 = CanonicalEventKey(
            underlying_source=SettlementSource.NOAA,
            settlement_rule="weather",
            time_window_start="2026-03-24",
            time_window_end="2026-03-24",
            entity="NYC",
        )
        assert k1.key != k2.key

    def test_cross_venue_registry(self):
        registry = CrossVenueRegistry()
        key = "abc123"
        registry.register_contract(VenueContract(
            venue=Venue.POLYMARKET, contract_id="pm_1",
            canonical_key=key, title="BTC up?", yes_price=0.55,
        ))
        registry.register_contract(VenueContract(
            venue=Venue.KALSHI, contract_id="kal_1",
            canonical_key=key, title="BTC up?", yes_price=0.60,
        ))
        pairs = registry.find_pairs(min_divergence=0.03)
        assert len(pairs) == 1
        assert pairs[0].price_divergence == pytest.approx(0.05)


class TestOpportunityLedger:
    def test_record_and_summary(self):
        ledger = OpportunityLedger()
        import time
        for i in range(10):
            ledger.record(OpportunityRecord(
                timestamp=time.time(),
                niche_id="btc5",
                market_id=f"m_{i}",
                venue="polymarket",
                action="traded" if i < 5 else "filtered",
                reason="test",
            ))
        summary = ledger.summary()
        assert summary["total_opportunities"] == 10
        rates = summary["filter_pass_rate"]
        assert rates["btc5"] == pytest.approx(0.5)
