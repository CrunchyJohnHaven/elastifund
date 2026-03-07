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


if __name__ == "__main__":
    unittest.main()
