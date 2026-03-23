#!/usr/bin/env python3
"""Unit tests for bot.deribit_iv_feed — no network required."""

from __future__ import annotations

import json
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure the bot package is importable without full dependencies.
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from bot.deribit_iv_feed import (
    DeribitIVFeed,
    IVSnapshot,
    OptionSnapshot,
    _parse_instrument,
    _to_float,
)


class TestParseInstrument(unittest.TestCase):
    def test_call(self):
        result = _parse_instrument("BTC-28MAR26-90000-C")
        self.assertEqual(result, (90000.0, "call"))

    def test_put(self):
        result = _parse_instrument("BTC-28MAR26-85000-P")
        self.assertEqual(result, (85000.0, "put"))

    def test_invalid_short(self):
        self.assertIsNone(_parse_instrument("BTC-28MAR26"))

    def test_invalid_strike(self):
        self.assertIsNone(_parse_instrument("BTC-28MAR26-abc-C"))

    def test_invalid_type(self):
        self.assertIsNone(_parse_instrument("BTC-28MAR26-90000-X"))


class TestToFloat(unittest.TestCase):
    def test_normal(self):
        self.assertEqual(_to_float(42.5), 42.5)

    def test_string(self):
        self.assertEqual(_to_float("3.14"), 3.14)

    def test_none(self):
        self.assertIsNone(_to_float(None))

    def test_bad_string(self):
        self.assertIsNone(_to_float("nope"))


class TestIVSnapshot(unittest.TestCase):
    def test_age_fresh(self):
        snap = IVSnapshot(last_update_ts=time.time())
        self.assertLess(snap.age_seconds(), 1.0)

    def test_age_stale(self):
        snap = IVSnapshot(last_update_ts=time.time() - 60)
        self.assertTrue(snap.is_stale(max_age_s=30.0))

    def test_age_never_updated(self):
        snap = IVSnapshot()
        self.assertTrue(snap.is_stale())

    def test_to_dict(self):
        snap = IVSnapshot(dvol=55.0, underlying_price=87000.0, connected=True)
        d = snap.to_dict()
        self.assertEqual(d["dvol"], 55.0)
        self.assertEqual(d["underlying_price"], 87000.0)
        self.assertTrue(d["connected"])
        self.assertIn("age_s", d)


class TestDeribitIVFeedLocal(unittest.TestCase):
    """Test feed logic without WebSocket."""

    def setUp(self):
        self.feed = DeribitIVFeed()

    def test_snapshot_starts_empty(self):
        snap = self.feed.snapshot()
        self.assertIsNone(snap.dvol)
        self.assertFalse(snap.connected)

    def test_volindex_update(self):
        msg = json.dumps({
            "method": "subscription",
            "params": {
                "channel": "deribit_volatility_index.btc_usd",
                "data": {"volatility": 62.5, "timestamp": int(time.time() * 1000)},
            },
        })
        self.feed._handle_message(msg)
        snap = self.feed.snapshot()
        self.assertAlmostEqual(snap.dvol, 62.5, places=1)

    def test_price_index_update(self):
        msg = json.dumps({
            "method": "subscription",
            "params": {
                "channel": "deribit_price_index.btc_usd",
                "data": {"price": 87250.0, "timestamp": int(time.time() * 1000)},
            },
        })
        self.feed._handle_message(msg)
        snap = self.feed.snapshot()
        self.assertAlmostEqual(snap.underlying_price, 87250.0, places=1)

    def test_markprice_list_format(self):
        """Simulate markprice.options bulk update in list-of-lists format."""
        rows = [
            ["BTC-28MAR26-85000-P", 0.012, 58.0],
            ["BTC-28MAR26-85000-C", 0.015, 55.0],
            ["BTC-28MAR26-86000-P", 0.010, 57.5],
            ["BTC-28MAR26-86000-C", 0.013, 54.5],
            ["BTC-28MAR26-87000-P", 0.008, 57.0],
            ["BTC-28MAR26-87000-C", 0.011, 54.0],
            ["BTC-28MAR26-88000-P", 0.006, 56.5],
            ["BTC-28MAR26-88000-C", 0.009, 53.5],
            ["BTC-28MAR26-89000-P", 0.004, 56.0],
            ["BTC-28MAR26-89000-C", 0.007, 53.0],
        ]
        msg = json.dumps({
            "method": "subscription",
            "params": {
                "channel": "markprice.options.btc_usd",
                "data": rows,
            },
        })
        self.feed._handle_message(msg)
        snap = self.feed.snapshot()
        # Should have computed ATM IVs and skew.
        self.assertIsNotNone(snap.atm_iv_call)
        self.assertIsNotNone(snap.atm_iv_put)
        self.assertIsNotNone(snap.put_call_skew)
        # Puts should have higher IV than calls (downside skew).
        self.assertGreater(snap.put_call_skew, 0)

    def test_markprice_dict_format(self):
        """Simulate a single dict-format mark-price update."""
        msg = json.dumps({
            "method": "subscription",
            "params": {
                "channel": "markprice.options.btc_usd",
                "data": {
                    "instrument_name": "BTC-28MAR26-90000-C",
                    "mark_iv": 52.0,
                    "underlying_price": 87500.0,
                    "delta": 0.45,
                    "gamma": 0.001,
                    "vega": 120.0,
                    "theta": -50.0,
                    "timestamp": int(time.time() * 1000),
                },
            },
        })
        self.feed._handle_message(msg)
        self.assertIn("BTC-28MAR26-90000-C", self.feed._option_marks)

    def test_json_rpc_response_handling(self):
        """Test that JSON-RPC responses resolve pending futures."""
        import asyncio
        loop = asyncio.new_event_loop()
        fut = loop.create_future()
        self.feed._pending[42] = fut
        msg = json.dumps({"jsonrpc": "2.0", "id": 42, "result": {"ok": True}})
        self.feed._handle_message(msg)
        self.assertTrue(fut.done())
        self.assertEqual(loop.run_until_complete(fut), {"ok": True})
        loop.close()

    def test_malformed_json_ignored(self):
        """Non-JSON messages shouldn't crash the handler."""
        self.feed._handle_message("this is not json")
        snap = self.feed.snapshot()
        self.assertIsNone(snap.dvol)

    def test_stop(self):
        self.feed.stop()
        self.assertFalse(self.feed._running)


if __name__ == "__main__":
    unittest.main()
