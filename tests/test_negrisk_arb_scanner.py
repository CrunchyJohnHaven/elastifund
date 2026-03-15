import tempfile
import unittest
from pathlib import Path

from bot.negrisk_arb_scanner import NegRiskArbScanner, parse_clob_token_ids, scan_to_report


def _market(
    *,
    market_id: str,
    outcome: str,
    yes_bid: float,
    yes_ask: float,
    volume24hr: float = 250.0,
) -> dict:
    return {
        "id": market_id,
        "conditionId": market_id,
        "groupItemTitle": outcome,
        "bestBid": yes_bid,
        "bestAsk": yes_ask,
        "clobTokenIds": f'["{market_id}-yes","{market_id}-no"]',
        "volume24hr": volume24hr,
        "negRisk": True,
        "active": True,
        "closed": False,
        "endDate": "2026-12-01T00:00:00Z",
    }


class TestNegRiskArbScanner(unittest.TestCase):
    def test_parse_clob_token_ids(self) -> None:
        self.assertEqual(
            parse_clob_token_ids('["a", "b"]'),
            ("a", "b"),
        )
        self.assertEqual(
            parse_clob_token_ids("x,y"),
            ("x", "y"),
        )

    def test_scanner_detects_overround_buy_all_no(self) -> None:
        scanner = NegRiskArbScanner(min_deviation=0.03, min_volume24hr_usd=500.0, max_pages=1)
        scanner.fetch_active_events = lambda: [  # type: ignore[assignment]
            {
                "id": "evt-over",
                "slug": "evt-over",
                "title": "Who wins?",
                "negRisk": True,
                "volume24hr": 1200.0,
                "markets": [
                    _market(market_id="m1", outcome="Alice", yes_bid=0.38, yes_ask=0.40),
                    _market(market_id="m2", outcome="Bob", yes_bid=0.37, yes_ask=0.39),
                    _market(market_id="m3", outcome="Carol", yes_bid=0.35, yes_ask=0.37),
                ],
            }
        ]
        try:
            opportunities, stats = scanner.scan()
        finally:
            scanner.close()

        self.assertEqual(stats["opportunities_found"], 1)
        self.assertEqual(len(opportunities), 1)
        opp = opportunities[0]
        self.assertEqual(opp.strategy, "buy_all_no")
        self.assertGreater(opp.sum_yes_ask, 1.02)
        self.assertGreater(opp.expected_profit_usd, 0.0)

    def test_scanner_detects_underround_buy_all_yes(self) -> None:
        scanner = NegRiskArbScanner(min_deviation=0.03, min_volume24hr_usd=500.0, max_pages=1)
        scanner.fetch_active_events = lambda: [  # type: ignore[assignment]
            {
                "id": "evt-under",
                "slug": "evt-under",
                "title": "Who wins?",
                "negRisk": True,
                "volume24hr": 1800.0,
                "markets": [
                    _market(market_id="m1", outcome="Alice", yes_bid=0.30, yes_ask=0.31),
                    _market(market_id="m2", outcome="Bob", yes_bid=0.31, yes_ask=0.32),
                    _market(market_id="m3", outcome="Carol", yes_bid=0.32, yes_ask=0.33),
                ],
            }
        ]
        try:
            opportunities, stats = scanner.scan()
        finally:
            scanner.close()

        self.assertEqual(stats["opportunities_found"], 1)
        opp = opportunities[0]
        self.assertEqual(opp.strategy, "buy_all_yes")
        self.assertLess(opp.sum_yes_ask, 0.98)
        self.assertGreater(opp.expected_profit_usd, 0.0)

    def test_scan_to_report_writes_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.json"
            report = scan_to_report(
                output_path=out,
                max_pages=1,
                page_size=10,
                min_volume24hr_usd=10_000_000.0,  # force empty report from live data
            )
            self.assertTrue(out.exists())
            self.assertIn("opportunities", report)
            self.assertIn("stats", report)


if __name__ == "__main__":
    unittest.main()
