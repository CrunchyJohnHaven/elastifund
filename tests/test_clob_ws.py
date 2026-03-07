import time
import unittest

from infra.clob_ws import BestBidAskStore, chunk_asset_ids, parse_best_bid_ask_messages


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

    def test_store_tracks_no_orderbook(self) -> None:
        store = BestBidAskStore()
        store.mark_no_orderbook("tok-404")
        self.assertTrue(store.has_no_orderbook("tok-404"))

        store.update("tok-404", best_bid=0.40, best_ask=0.42, updated_ts=time.time())
        self.assertFalse(store.has_no_orderbook("tok-404"))
        self.assertTrue(store.is_fresh("tok-404", max_age_seconds=2.0))


if __name__ == "__main__":
    unittest.main()
