import unittest

from bot.a6_sum_scanner import A6ScannerConfig, A6SumScanner
from bot.constraint_arb_engine import MarketQuote
from bot.resolution_normalizer import normalize_market


class TestA6SumScanner(unittest.TestCase):
    def _mk_market(
        self,
        *,
        market_id: str,
        event_id: str,
        outcome: str,
        outcomes: list[str],
        token_ids: str,
        question: str = "Who will win the race?",
    ) -> dict:
        return {
            "market_id": market_id,
            "event_id": event_id,
            "question": question,
            "outcome": outcome,
            "outcomes": outcomes,
            "category": "politics",
            "negRisk": True,
            "negRiskAugmented": False,
            "resolutionSource": "Associated Press",
            "endDate": "2026-11-03T23:59:00Z",
            "rules": "Resolves using Associated Press.",
            "clobTokenIds": token_ids,
            "acceptingOrders": True,
            "enableOrderBook": True,
            "orderPriceMinTickSize": 0.01,
        }

    def test_detects_executable_underround_and_dedupes_repeats(self) -> None:
        scanner = A6SumScanner(
            A6ScannerConfig(
                buy_threshold=0.97,
                stale_quote_seconds=5,
                dedupe_window_seconds=30,
            )
        )
        outcomes = ["Alice", "Bob", "Carol"]
        markets = [
            normalize_market(
                self._mk_market(
                    market_id="alice",
                    event_id="evt-1",
                    outcome="Alice",
                    outcomes=outcomes,
                    token_ids='["alice-yes","alice-no"]',
                )
            ),
            normalize_market(
                self._mk_market(
                    market_id="bob",
                    event_id="evt-1",
                    outcome="Bob",
                    outcomes=outcomes,
                    token_ids='["bob-yes","bob-no"]',
                )
            ),
            normalize_market(
                self._mk_market(
                    market_id="carol",
                    event_id="evt-1",
                    outcome="Carol",
                    outcomes=outcomes,
                    token_ids='["carol-yes","carol-no"]',
                )
            ),
        ]
        now_ts = 1_700_000_000
        quotes = {
            "alice": MarketQuote("alice", 0.29, 0.30, 0.70, 0.71, now_ts),
            "bob": MarketQuote("bob", 0.30, 0.31, 0.69, 0.70, now_ts),
            "carol": MarketQuote("carol", 0.31, 0.32, 0.68, 0.69, now_ts),
        }

        snapshots = scanner.build_event_snapshots(markets=markets, quotes=quotes, now_ts=now_ts)
        self.assertEqual(len(snapshots), 1)
        self.assertTrue(snapshots[0].executable)
        self.assertAlmostEqual(snapshots[0].sum_yes_ask or 0.0, 0.93, places=6)

        first = scanner.scan_snapshots(snapshots, now_ts=now_ts)
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0].signal_type, "buy_yes_basket")
        self.assertTrue(first[0].executable)

        second = scanner.scan_snapshots(snapshots, now_ts=now_ts + 1)
        self.assertEqual(second, ())

    def test_drops_stale_and_incomplete_event_books(self) -> None:
        scanner = A6SumScanner(A6ScannerConfig(stale_quote_seconds=5))
        outcomes = ["Alice", "Bob", "Carol"]
        markets = [
            normalize_market(
                self._mk_market(
                    market_id="alice",
                    event_id="evt-2",
                    outcome="Alice",
                    outcomes=outcomes,
                    token_ids='["alice-yes","alice-no"]',
                )
            ),
            normalize_market(
                self._mk_market(
                    market_id="bob",
                    event_id="evt-2",
                    outcome="Bob",
                    outcomes=outcomes,
                    token_ids='["bob-yes","bob-no"]',
                )
            ),
            normalize_market(
                self._mk_market(
                    market_id="carol",
                    event_id="evt-2",
                    outcome="Carol",
                    outcomes=outcomes,
                    token_ids="",
                )
            ),
        ]
        now_ts = 1_700_000_100
        quotes = {
            "alice": MarketQuote("alice", 0.29, 0.30, 0.70, 0.71, now_ts - 100),
            "bob": MarketQuote("bob", 0.30, 0.31, 0.69, 0.70, now_ts),
        }

        snapshots = scanner.build_event_snapshots(markets=markets, quotes=quotes, now_ts=now_ts)
        self.assertEqual(len(snapshots), 1)
        snapshot = snapshots[0]
        self.assertFalse(snapshot.executable)
        self.assertIn("alice", snapshot.stale_leg_ids)
        self.assertIn("carol", snapshot.missing_leg_ids)
        self.assertEqual(scanner.scan_snapshots(snapshots, now_ts=now_ts), ())

    def test_emits_signal_only_for_overround_inventory_unwind(self) -> None:
        scanner = A6SumScanner(A6ScannerConfig(upper_signal_threshold=1.03))
        outcomes = ["Alice", "Bob"]
        markets = [
            normalize_market(
                self._mk_market(
                    market_id="alice",
                    event_id="evt-3",
                    outcome="Alice",
                    outcomes=outcomes,
                    token_ids='["alice-yes","alice-no"]',
                    question="Who will win the runoff?",
                )
            ),
            normalize_market(
                self._mk_market(
                    market_id="bob",
                    event_id="evt-3",
                    outcome="Bob",
                    outcomes=outcomes,
                    token_ids='["bob-yes","bob-no"]',
                    question="Who will win the runoff?",
                )
            ),
        ]
        now_ts = 1_700_000_200
        quotes = {
            "alice": MarketQuote("alice", 0.55, 0.56, 0.44, 0.45, now_ts),
            "bob": MarketQuote("bob", 0.51, 0.52, 0.48, 0.49, now_ts),
        }

        batch = scanner.scan_snapshots(
            scanner.build_event_snapshots(markets=markets, quotes=quotes, now_ts=now_ts),
            now_ts=now_ts,
        )
        self.assertEqual(len(batch), 1)
        self.assertEqual(batch[0].signal_type, "unwind_inventory_only")
        self.assertFalse(batch[0].executable)
        self.assertAlmostEqual(batch[0].sum_yes_bid or 0.0, 1.06, places=6)

    def test_prefers_binary_straddle_when_cheaper_than_full_basket(self) -> None:
        scanner = A6SumScanner(A6ScannerConfig(buy_threshold=0.97))
        outcomes = ["Alice", "Bob", "Carol"]
        markets = [
            normalize_market(
                self._mk_market(
                    market_id="alice",
                    event_id="evt-4",
                    outcome="Alice",
                    outcomes=outcomes,
                    token_ids='["alice-yes","alice-no"]',
                )
            ),
            normalize_market(
                self._mk_market(
                    market_id="bob",
                    event_id="evt-4",
                    outcome="Bob",
                    outcomes=outcomes,
                    token_ids='["bob-yes","bob-no"]',
                )
            ),
            normalize_market(
                self._mk_market(
                    market_id="carol",
                    event_id="evt-4",
                    outcome="Carol",
                    outcomes=outcomes,
                    token_ids='["carol-yes","carol-no"]',
                )
            ),
        ]
        now_ts = 1_700_000_300
        quotes = {
            "alice": MarketQuote("alice", 0.24, 0.25, 0.59, 0.60, now_ts),
            "bob": MarketQuote("bob", 0.36, 0.37, 0.63, 0.64, now_ts),
            "carol": MarketQuote("carol", 0.31, 0.32, 0.68, 0.69, now_ts),
        }

        batch = scanner.scan_snapshots(
            scanner.build_event_snapshots(markets=markets, quotes=quotes, now_ts=now_ts),
            now_ts=now_ts,
        )

        self.assertEqual(len(batch), 1)
        self.assertEqual(batch[0].signal_type, "buy_yes_no_straddle")
        self.assertEqual(batch[0].selected_construction, "binary_straddle")
        self.assertEqual(tuple(leg.quote_side for leg in batch[0].legs), ("YES", "NO"))
        self.assertAlmostEqual(batch[0].theoretical_edge, 0.15, places=6)

    def test_augmented_event_blocks_full_basket_but_keeps_straddle(self) -> None:
        scanner = A6SumScanner(A6ScannerConfig(buy_threshold=0.97))
        outcomes = ["Alice", "Bob", "Other"]
        markets = [
            normalize_market(
                self._mk_market(
                    market_id="alice",
                    event_id="evt-5",
                    outcome="Alice",
                    outcomes=outcomes,
                    token_ids='["alice-yes","alice-no"]',
                )
                | {"negRiskAugmented": True}
            ),
            normalize_market(
                self._mk_market(
                    market_id="bob",
                    event_id="evt-5",
                    outcome="Bob",
                    outcomes=outcomes,
                    token_ids='["bob-yes","bob-no"]',
                )
                | {"negRiskAugmented": True}
            ),
        ]
        now_ts = 1_700_000_320
        quotes = {
            "alice": MarketQuote("alice", 0.18, 0.19, 0.76, 0.77, now_ts),
            "bob": MarketQuote("bob", 0.31, 0.32, 0.67, 0.68, now_ts),
        }

        snapshots = scanner.build_event_snapshots(markets=markets, quotes=quotes, now_ts=now_ts)
        self.assertEqual(len(snapshots), 1)
        self.assertFalse(snapshots[0].full_basket_guaranteed)
        self.assertIsNone(snapshots[0].sum_yes_ask)

        batch = scanner.scan_snapshots(snapshots, now_ts=now_ts)
        self.assertEqual(len(batch), 1)
        self.assertEqual(batch[0].selected_construction, "binary_straddle")


if __name__ == "__main__":
    unittest.main()
