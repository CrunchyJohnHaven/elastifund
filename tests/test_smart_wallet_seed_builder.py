from __future__ import annotations

import math

from research.wallet_intelligence import smart_wallet_seed_builder as builder


def _trade(
    wallet: str,
    *,
    condition_id: str,
    side: str,
    outcome_index: int,
    price: float = 0.5,
    size: float = 10.0,
    ts: int = 1_710_000_000,
    title: str = "Bitcoin Up or Down - 5m",
) -> dict:
    return {
        "proxyWallet": wallet,
        "conditionId": condition_id,
        "side": side,
        "outcomeIndex": outcome_index,
        "price": price,
        "size": size,
        "timestamp": ts,
        "title": title,
    }


def test_is_btc5_trade_requires_btc_and_fast_window() -> None:
    assert builder.is_btc5_trade({"title": "Bitcoin Up or Down - 5m"}) is True
    assert builder.is_btc5_trade({"title": "BTC updown 5-minute"}) is True
    assert builder.is_btc5_trade({"title": "Ethereum Up or Down - 5m"}) is False
    assert builder.is_btc5_trade({"title": "Bitcoin election market"}) is False


def test_compute_wallet_metrics_handles_win_rate_dual_sided_and_recency() -> None:
    wallet = "0x1111111111111111111111111111111111111111"
    now_ts = 1_710_000_300
    trades = [
        _trade(
            wallet,
            condition_id="c1",
            side="BUY",
            outcome_index=0,
            ts=1_710_000_000,
        ),
        _trade(
            wallet,
            condition_id="c1",
            side="SELL",
            outcome_index=0,
            ts=1_710_000_030,
        ),
        _trade(
            wallet,
            condition_id="c2",
            side="BUY",
            outcome_index=1,
            ts=1_710_000_060,
        ),
        {
            **_trade(
                wallet,
                condition_id="nonbtc",
                side="BUY",
                outcome_index=0,
                ts=1_710_000_090,
                title="Fed funds target range",
            ),
            "price": 0.6,
        },
    ]
    # c1 resolved to outcome 1 => first trade loses, second wins (SELL outcome0 => effective 1)
    # c2 resolved to outcome 1 => BUY outcome1 wins
    resolution_map = {"c1": 1, "c2": 1}
    metrics = builder.compute_wallet_metrics(
        wallet=wallet,
        trades=trades,
        resolution_map=resolution_map,
        now_ts=now_ts,
        cooccurrence_count=7,
        source_tags={"known_seed"},
    )

    assert metrics is not None
    assert metrics.total_trades == 4
    assert metrics.btc5_trades == 3
    assert metrics.unique_markets == 3
    assert metrics.resolved_trade_count == 3
    assert metrics.estimated_win_rate == 2 / 3
    # c1 has both effective outcomes, c2 has one side => 1 dual market / 2 total BTC5 markets
    assert metrics.dual_sided_rate == 0.5
    assert 0.0 < metrics.recency_score <= 1.0
    expected_specialization = 3 / 4
    assert math.isclose(metrics.btc5_specialization, expected_specialization, rel_tol=1e-9)


def test_score_wallets_uses_dispatch_formula_weights() -> None:
    metrics = [
        builder.WalletMetrics(
            address="0xaaa0000000000000000000000000000000000000",
            total_trades=100,
            btc5_trades=90,
            unique_markets=20,
            total_notional_usd=2000.0,
            avg_trade_notional_usd=20.0,
            estimated_win_rate=0.7,
            resolved_trade_count=80,
            resolved_market_count=18,
            btc5_specialization=0.9,
            dual_sided_rate=0.4,
            recency_score=0.8,
            last_trade_ts=1_710_000_000,
            cooccurrence_count=10,
            source_tags=["leaderboard_week"],
        ),
        builder.WalletMetrics(
            address="0xbbb0000000000000000000000000000000000000",
            total_trades=100,
            btc5_trades=100,
            unique_markets=20,
            total_notional_usd=1000.0,
            avg_trade_notional_usd=10.0,
            estimated_win_rate=0.6,
            resolved_trade_count=80,
            resolved_market_count=18,
            btc5_specialization=1.0,
            dual_sided_rate=0.1,
            recency_score=0.7,
            last_trade_ts=1_710_000_000,
            cooccurrence_count=8,
            source_tags=["cooccurrence"],
        ),
    ]

    ranked = builder.score_wallets(metrics, top_n=50)
    assert len(ranked) == 2
    # 2000 notional should have higher percentile than 1000 and rank first.
    assert ranked[0].address == "0xaaa0000000000000000000000000000000000000"
    assert ranked[0].rank == 1
    assert ranked[1].rank == 2

    high = ranked[0]
    expected = (
        high.estimated_win_rate * 0.3
        + high.volume_rank_percentile * 0.2
        + high.recency_score * 0.2
        + high.btc5_specialization * 0.2
        + high.dual_sided_rate * 0.1
    )
    assert math.isclose(high.smart_score, expected, rel_tol=1e-9)


def test_validate_elites_flags_missing_top10() -> None:
    wallets = [
        builder.ScoredWallet(
            address="0x0000000000000000000000000000000000000001",
            rank=1,
            smart_score=0.9,
            estimated_win_rate=0.8,
            volume_rank_percentile=0.9,
            recency_score=0.9,
            btc5_specialization=0.9,
            dual_sided_rate=0.2,
            total_trades=10,
            btc5_trades=10,
            unique_markets=5,
            total_notional_usd=100.0,
            avg_trade_notional_usd=10.0,
            resolved_trade_count=8,
            resolved_market_count=5,
            cooccurrence_count=3,
            source_tags=["test"],
        )
    ]
    result = builder.validate_elites(wallets)
    assert result["pass"] is False
    assert "gabagool22" in result["missing_top10"]
    assert "k9Q2mX4L8A7ZP3R" in result["missing_top10"]
