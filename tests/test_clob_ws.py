import unittest

from infra.clob_ws import (
    BestBidAskStore,
    chunk_asset_ids,
    parse_best_bid_ask_messages,
    parse_tick_size_messages,
)


class TestClobWS(unittest.TestCase):
    def test_chunk_asset_ids(self) -> None:
        chunks = chunk_asset_ids(["a", "b", "c", "d", "e"], chunk_size=2)
        self.assertEqual(chunks, [["a", "b"], ["c", "d"], ["e"]])

    def test_parse_best_bid_ask_messages(self) -> None:
        payload = {
            "type": "best_bid_ask",
            "asset_id": "tok-1",
            "best_bid": "0.44",
            "best_ask": "0.46",
            "timestamp": 100.0,
        }
        msgs = parse_best_bid_ask_messages(payload)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].token_id, "tok-1")
        self.assertAlmostEqual(msgs[0].best_bid, 0.44)
        self.assertAlmostEqual(msgs[0].best_ask, 0.46)

    def test_parse_tick_size_messages(self) -> None:
        payload = {
            "type": "tick_size_change",
            "asset_id": "tok-1",
            "tick_size": "0.005",
            "timestamp": 101.0,
        }
        msgs = parse_tick_size_messages(payload)
        self.assertEqual(msgs, [("tok-1", 0.005, 101.0)])

    def test_store_tracks_no_orderbook_and_tick_size(self) -> None:
        store = BestBidAskStore()
        store.mark_no_orderbook("tok-404")
        self.assertTrue(store.has_no_orderbook("tok-404"))

        store.update_tick_size("tok-404", tick_size=0.005)
        self.assertAlmostEqual(store.get_tick_size("tok-404") or 0.0, 0.005)

        store.update("tok-404", best_bid=0.40, best_ask=0.42, updated_ts=100.0)
        self.assertFalse(store.has_no_orderbook("tok-404"))
        quote = store.get("tok-404")
        self.assertIsNotNone(quote)
        assert quote is not None
        self.assertAlmostEqual(quote.tick_size or 0.0, 0.005)


if __name__ == "__main__":
    unittest.main()
