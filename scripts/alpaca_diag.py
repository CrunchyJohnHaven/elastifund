#!/usr/bin/env python3
"""Diagnostic: show raw signal, spread, and edge for Alpaca crypto."""
from __future__ import annotations
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env", override=False)
except ImportError:
    pass

from bot.alpaca_client import AlpacaClient, AlpacaClientConfig
from strategies.alpaca_crypto_momentum import (
    parse_crypto_bars_response,
    parse_latest_orderbooks_response,
    _rolling_signal_bps,
    _realized_volatility_bps,
    _normalize_symbol,
)

def main():
    config = AlpacaClientConfig.from_env(mode="live")
    client = AlpacaClient(config)

    symbols = ["BTC/USD", "ETH/USD", "SOL/USD"]

    # Get account info
    account = client.get_account()
    print(f"Account status: {account.get('status')}, Cash: ${float(account.get('cash', 0)):.2f}")
    print(f"Buying power: ${float(account.get('buying_power', 0)):.2f}")
    print()

    # Get bars and books
    bars_payload = client.get_crypto_bars(symbols=symbols, timeframe="1Min", limit=240)
    books_payload = client.get_latest_crypto_orderbooks(symbols=symbols)
    bars_by_symbol = parse_crypto_bars_response(bars_payload)
    books_by_symbol = parse_latest_orderbooks_response(books_payload)

    for symbol in symbols:
        norm = _normalize_symbol(symbol)
        bars = bars_by_symbol.get(norm, [])
        book = books_by_symbol.get(norm)

        if not bars:
            print(f"{norm}: NO BARS RETURNED")
            continue

        closes = [b.close for b in sorted(bars, key=lambda x: x.timestamp) if b.close > 0]
        last_price = closes[-1] if closes else 0

        # Compute signals
        signal_5_20 = _rolling_signal_bps(closes, short_window=5, long_window=20)
        signal_3_10 = _rolling_signal_bps(closes, short_window=3, long_window=10)
        vol = _realized_volatility_bps(closes, long_window=20)

        # Spread
        if book:
            mid = book.mid_price
            spread_bps = book.spread_bps
            bid = book.bid_price
            ask = book.ask_price
        else:
            mid = last_price
            spread_bps = 0
            bid = ask = last_price

        edge_5_20 = abs(signal_5_20) - spread_bps
        edge_3_10 = abs(signal_3_10) - spread_bps

        print(f"=== {norm} ===")
        print(f"  Last price:     ${last_price:,.2f}")
        print(f"  Bars returned:  {len(bars)}")
        print(f"  Bid/Ask:        ${bid:,.2f} / ${ask:,.2f}")
        print(f"  Spread:         {spread_bps:.1f} bps")
        print(f"  Signal(5/20):   {signal_5_20:+.1f} bps")
        print(f"  Signal(3/10):   {signal_3_10:+.1f} bps")
        print(f"  Edge(5/20):     {edge_5_20:+.1f} bps  {'PASS' if edge_5_20 > 15 else 'FAIL'}")
        print(f"  Edge(3/10):     {edge_3_10:+.1f} bps  {'PASS' if edge_3_10 > 15 else 'FAIL'}")
        print(f"  Volatility:     {vol:.1f} bps")
        print(f"  Direction:      {'BUY' if signal_5_20 > 0 else 'SELL' if signal_5_20 < 0 else 'FLAT'}")
        print()

if __name__ == "__main__":
    main()
