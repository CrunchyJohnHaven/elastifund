import tempfile
import unittest
from pathlib import Path

from bot.sum_violation_scanner import SumViolationLeg, SumViolationOpportunity, SumViolationScanner
from bot.sum_violation_strategy import SumViolationStrategy


def _market(
    *,
    market_id: str,
    event_id: str,
    event_title: str,
    question: str,
    outcome: str,
    yes_bid: float,
    yes_ask: float,
) -> dict:
    return {
        "id": market_id,
        "event_id": event_id,
        "events": [{"id": event_id, "title": event_title}],
        "question": question,
        "groupItemTitle": outcome,
        "clobTokenIds": f'["{market_id}-yes","{market_id}-no"]',
        "bestBid": yes_bid,
        "bestAsk": yes_ask,
        "active": True,
        "closed": False,
        "category": "politics",
        "orderPriceMinTickSize": 0.01,
    }


def _book(*, bid: float, ask: float, size: float = 200.0) -> dict:
    return {
        "bids": [{"price": f"{bid:.3f}", "size": f"{size:.2f}"}],
        "asks": [{"price": f"{ask:.3f}", "size": f"{size:.2f}"}],
    }


class DummyScanner:
    def __init__(self, opportunities):
        self.opportunities = list(opportunities)

    def scan_market_violations(self, markets=None, threshold=0.05):
        return list(self.opportunities)


class TestSumViolationScannerGrouping(unittest.TestCase):
    def test_grouping_logic_detects_under_and_overround(self) -> None:
        scanner = SumViolationScanner(
            use_websocket=False,
            max_pages=1,
            page_size=100,
            min_event_markets=3,
            prefilter_buffer=0.0,
        )

        books = {
            "u1-yes": _book(bid=0.29, ask=0.30),
            "u1-no": _book(bid=0.69, ask=0.70),
            "u2-yes": _book(bid=0.30, ask=0.31),
            "u2-no": _book(bid=0.68, ask=0.69),
            "u3-yes": _book(bid=0.30, ask=0.31),
            "u3-no": _book(bid=0.68, ask=0.69),
            "o1-yes": _book(bid=0.34, ask=0.35),
            "o1-no": _book(bid=0.64, ask=0.65),
            "o2-yes": _book(bid=0.34, ask=0.35),
            "o2-no": _book(bid=0.64, ask=0.65),
            "o3-yes": _book(bid=0.34, ask=0.35),
            "o3-no": _book(bid=0.64, ask=0.65),
            "f1-yes": _book(bid=0.32, ask=0.33),
            "f1-no": _book(bid=0.66, ask=0.67),
            "f2-yes": _book(bid=0.33, ask=0.33),
            "f2-no": _book(bid=0.66, ask=0.67),
            "f3-yes": _book(bid=0.33, ask=0.34),
            "f3-no": _book(bid=0.65, ask=0.66),
        }
        scanner._fetch_order_book = lambda token_id: books.get(token_id)  # type: ignore[assignment]

        markets = [
            _market(
                market_id="u1",
                event_id="evt-under",
                event_title="Who wins the election?",
                question="Who wins the election?",
                outcome="Alice",
                yes_bid=0.29,
                yes_ask=0.30,
            ),
            _market(
                market_id="u2",
                event_id="evt-under",
                event_title="Who wins the election?",
                question="Who wins the election?",
                outcome="Bob",
                yes_bid=0.30,
                yes_ask=0.31,
            ),
            _market(
                market_id="u3",
                event_id="evt-under",
                event_title="Who wins the election?",
                question="Who wins the election?",
                outcome="Carol",
                yes_bid=0.30,
                yes_ask=0.31,
            ),
            _market(
                market_id="o1",
                event_id="evt-over",
                event_title="Who becomes PM?",
                question="Who becomes PM?",
                outcome="Alpha",
                yes_bid=0.34,
                yes_ask=0.35,
            ),
            _market(
                market_id="o2",
                event_id="evt-over",
                event_title="Who becomes PM?",
                question="Who becomes PM?",
                outcome="Beta",
                yes_bid=0.34,
                yes_ask=0.35,
            ),
            _market(
                market_id="o3",
                event_id="evt-over",
                event_title="Who becomes PM?",
                question="Who becomes PM?",
                outcome="Gamma",
                yes_bid=0.34,
                yes_ask=0.35,
            ),
            _market(
                market_id="f1",
                event_id="evt-fair",
                event_title="Who wins the runoff?",
                question="Who wins the runoff?",
                outcome="Red",
                yes_bid=0.32,
                yes_ask=0.33,
            ),
            _market(
                market_id="f2",
                event_id="evt-fair",
                event_title="Who wins the runoff?",
                question="Who wins the runoff?",
                outcome="Blue",
                yes_bid=0.33,
                yes_ask=0.33,
            ),
            _market(
                market_id="f3",
                event_id="evt-fair",
                event_title="Who wins the runoff?",
                question="Who wins the runoff?",
                outcome="Green",
                yes_bid=0.33,
                yes_ask=0.34,
            ),
        ]

        opportunities = scanner.scan_market_violations(markets, threshold=0.05)
        by_event = {opp.event_id: opp for opp in opportunities}

        self.assertIn("evt-under", by_event)
        self.assertIn("evt-over", by_event)
        self.assertNotIn("evt-fair", by_event)
        self.assertEqual(by_event["evt-under"].trade_side, "buy_yes_basket")
        self.assertEqual(by_event["evt-over"].trade_side, "buy_no_basket")
        self.assertAlmostEqual(by_event["evt-under"].sum_yes_ask or 0.0, 0.92, places=6)
        self.assertAlmostEqual(by_event["evt-over"].sum_yes_ask or 0.0, 1.05, places=6)


class TestSumViolationStrategy(unittest.TestCase):
    def _opportunity(self, *, violation_id: str, category: str, resolution_hours: float | None) -> SumViolationOpportunity:
        legs = tuple(
            SumViolationLeg(
                market_id=f"m{i}",
                event_id="evt-1",
                question="Who wins the tournament?",
                outcome=outcome,
                category=category,
                yes_token_id=f"m{i}-yes",
                no_token_id=f"m{i}-no",
                yes_bid=0.332,
                yes_ask=0.333,
                no_bid=0.666,
                no_ask=0.667,
                yes_depth_usd=120.0,
                no_depth_usd=120.0,
                resolution_hours=resolution_hours,
                tick_size=0.01,
                raw_market={},
            )
            for i, outcome in enumerate(("Alice", "Bob", "Carol"), start=1)
        )
        return SumViolationOpportunity(
            violation_id=violation_id,
            event_id="evt-1",
            event_key="evt-1",
            event_title="Who wins the tournament?",
            market_ids=tuple(leg.market_id for leg in legs),
            outcomes=tuple(leg.outcome for leg in legs),
            legs=legs,
            threshold=0.001,
            sum_yes_bid=0.996,
            sum_yes_ask=0.998,
            sum_no_bid=1.998,
            sum_no_ask=2.001,
            trade_side="buy_yes_basket",
            violation_amount=0.002,
            gross_profit_per_basket=0.002,
            gross_profit_per_dollar=0.002004008,
            execution_cost=0.998,
            payout_per_basket=1.0,
            can_trade_fifty_cents_per_leg=True,
        )

    def test_maker_only_economics_preserves_thin_violations(self) -> None:
        strategy = SumViolationStrategy(
            scanner=DummyScanner([self._opportunity(violation_id="sig-fee", category="crypto", resolution_hours=4.0)]),
            threshold=0.001,
            min_depth_usd=50.0,
            max_resolution_hours=24.0,
            position_size_usd=0.50,
        )

        signals = strategy.generate_signals()

        self.assertEqual(len(signals), 1)
        self.assertEqual(strategy.last_evaluations[0].action, "ready")
        self.assertEqual(strategy.last_evaluations[0].reason, "passes_filters")
        self.assertAlmostEqual(strategy.last_evaluations[0].fee_drag_per_basket, 0.0)
        self.assertGreater(strategy.last_evaluations[0].maker_rebate_per_basket, 0.0)
        self.assertGreater(
            strategy.last_evaluations[0].hypothetical_taker_fee_drag_per_basket,
            strategy.last_evaluations[0].maker_rebate_per_basket,
        )

    def test_velocity_filter_kills_long_dated_legs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            strategy = SumViolationStrategy(
                scanner=DummyScanner([self._opportunity(violation_id="sig-vel", category="politics", resolution_hours=48.0)]),
                threshold=0.001,
                min_depth_usd=50.0,
                max_resolution_hours=24.0,
                position_size_usd=0.50,
                report_path=Path(tmp) / "sum_violations_log.md",
            )

            signals = strategy.generate_signals()

        self.assertEqual(signals, [])
        self.assertEqual(strategy.last_evaluations[0].action, "killed_by_filter")
        self.assertEqual(strategy.last_evaluations[0].reason, "resolution>24.0h")


if __name__ == "__main__":
    unittest.main()
