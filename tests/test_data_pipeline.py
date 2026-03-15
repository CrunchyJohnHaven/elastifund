import tempfile
import unittest
from pathlib import Path

from src.config import AppConfig, SystemConfig
from src.data_pipeline import DataPipeline


class TestDataPipeline(unittest.TestCase):
    def test_db_initialization_and_parsers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "edge.db"
            cfg = AppConfig(system=SystemConfig(db_path=str(db_path), report_root=str(Path(tmp) / "reports")))
            pipeline = DataPipeline(cfg)

            yes, no = pipeline._parse_outcome_prices('["0.55", "0.45"]')
            self.assertAlmostEqual(yes or 0, 0.55)
            self.assertAlmostEqual(no or 0, 0.45)

            with pipeline._connect() as conn:
                tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
            self.assertIn("markets", tables)
            self.assertIn("market_prices", tables)
            self.assertIn("btc_spot", tables)

    def test_collect_binance_spot_once_uses_public_fallback(self) -> None:
        class StubHttpClient:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def get_json(self, url: str, params=None):  # noqa: ANN001
                self.calls.append(url)
                if "api.binance.com/api/v3/ticker/price" in url:
                    raise RuntimeError("451 ticker blocked")
                if "api.binance.com/api/v3/klines" in url:
                    raise RuntimeError("451 klines blocked")
                if "api.coinbase.com/v2/prices/BTC-USD/spot" in url:
                    return {"data": {"amount": "65000.12"}}
                raise AssertionError(f"unexpected url {url}")

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "edge.db"
            cfg = AppConfig(system=SystemConfig(db_path=str(db_path), report_root=str(Path(tmp) / "reports")))
            pipeline = DataPipeline(cfg)
            stub = StubHttpClient()
            pipeline.http = stub

            inserted = pipeline.collect_binance_spot_once()

            self.assertEqual(inserted, 1)
            self.assertEqual(len(stub.calls), 3)
            with pipeline._connect() as conn:
                row = conn.execute("SELECT price, source FROM btc_spot").fetchone()
            self.assertIsNotNone(row)
            self.assertAlmostEqual(row[0], 65000.12)
            self.assertEqual(row[1], "coinbase_spot")


if __name__ == "__main__":
    unittest.main()
