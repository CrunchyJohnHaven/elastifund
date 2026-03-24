from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from strategies.alpaca_crypto_momentum import (  # noqa: E402
    CryptoBar,
    TopOfBook,
    default_alpaca_momentum_variants,
    rank_momentum_candidates,
)


def _wave_bars() -> list[CryptoBar]:
    bars: list[CryptoBar] = []
    price = 100.0
    for cycle in range(10):
        for step in range(12):
            open_price = price
            price *= 1.0018
            bars.append(
                CryptoBar(
                    timestamp=f"2026-03-23T00:{cycle:02d}:{step:02d}Z",
                    open=open_price,
                    high=price * 1.001,
                    low=open_price * 0.999,
                    close=price,
                    volume=1000.0,
                )
            )
        for step in range(8):
            open_price = price
            price *= 0.9992
            bars.append(
                CryptoBar(
                    timestamp=f"2026-03-23T01:{cycle:02d}:{step:02d}Z",
                    open=open_price,
                    high=open_price * 1.0005,
                    low=price * 0.999,
                    close=price,
                    volume=900.0,
                )
            )
    for step in range(18):
        open_price = price
        price *= 1.0022
        bars.append(
            CryptoBar(
                timestamp=f"2026-03-23T02:00:{step:02d}Z",
                open=open_price,
                high=price * 1.001,
                low=open_price * 0.999,
                close=price,
                volume=1100.0,
            )
        )
    return bars


def test_rank_momentum_candidates_returns_tradeable_candidate() -> None:
    symbol = "BTC/USD"
    bars_by_symbol = {symbol: _wave_bars()}
    books_by_symbol = {
        symbol: TopOfBook(symbol=symbol, bid_price=bars_by_symbol[symbol][-1].close * 0.9999, ask_price=bars_by_symbol[symbol][-1].close * 1.0001),
    }
    variants = default_alpaca_momentum_variants([symbol])

    ranked = rank_momentum_candidates(
        bars_by_symbol=bars_by_symbol,
        books_by_symbol=books_by_symbol,
        variants=variants,
        recommended_notional_usd=25.0,
        min_prob_positive=0.50,
        min_expected_edge_bps=5.0,
        max_spread_bps=10.0,
    )

    assert ranked
    top = ranked[0]
    assert top.symbol == symbol
    assert top.action == "buy"
    assert top.replay_trade_count > 0
    assert top.prob_positive >= 0.50
    assert top.expected_edge_bps > 0.0
