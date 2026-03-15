import unittest

from src.feature_engineering import FeatureEngineer


class TestWalletCausality(unittest.TestCase):
    def test_wallet_score_asof_excludes_future_resolution(self) -> None:
        fe = FeatureEngineer("data/edge_discovery.db")

        wallet = "0xabc"
        wallet_history = {
            wallet: [
                {"timestamp_ts": 90, "condition_id": "c_past", "outcome": "Down", "size": 5.0},
                {"timestamp_ts": 100, "condition_id": "c_future", "outcome": "Up", "size": 10.0},
            ]
        }
        resolution_info = {
            "c_past": {"resolution": "DOWN", "resolution_ts": 95.0},
            "c_future": {"resolution": "UP", "resolution_ts": 200.0},
        }

        cache: dict[tuple[str, int, str], dict[str, float] | None] = {}
        early = fe._wallet_score_asof(
            wallet=wallet,
            asof_ts=150,
            exclude_condition_id="",
            wallet_trade_history=wallet_history,
            condition_resolution_info=resolution_info,
            cache=cache,
        )
        late = fe._wallet_score_asof(
            wallet=wallet,
            asof_ts=250,
            exclude_condition_id="",
            wallet_trade_history=wallet_history,
            condition_resolution_info=resolution_info,
            cache=cache,
        )

        self.assertIsNotNone(early)
        self.assertIsNotNone(late)
        assert early is not None
        assert late is not None
        self.assertEqual(early["trades"], 1.0)
        self.assertEqual(late["trades"], 2.0)
        self.assertEqual(early["wins"], 1.0)
        self.assertEqual(late["wins"], 2.0)

    def test_wallet_score_asof_excludes_current_condition(self) -> None:
        fe = FeatureEngineer("data/edge_discovery.db")
        wallet = "0xdef"
        wallet_history = {
            wallet: [
                {"timestamp_ts": 70, "condition_id": "c_ref", "outcome": "Down", "size": 3.0},
                {"timestamp_ts": 80, "condition_id": "c_current", "outcome": "Up", "size": 4.0},
                {"timestamp_ts": 150, "condition_id": "c_future_trade", "outcome": "Up", "size": 2.0},
            ]
        }
        resolution_info = {
            "c_ref": {"resolution": "DOWN", "resolution_ts": 75.0},
            "c_current": {"resolution": "UP", "resolution_ts": 85.0},
            "c_future_trade": {"resolution": "UP", "resolution_ts": 170.0},
        }

        cache: dict[tuple[str, int, str], dict[str, float] | None] = {}
        included = fe._wallet_score_asof(
            wallet=wallet,
            asof_ts=100,
            exclude_condition_id="",
            wallet_trade_history=wallet_history,
            condition_resolution_info=resolution_info,
            cache=cache,
        )
        excluded = fe._wallet_score_asof(
            wallet=wallet,
            asof_ts=100,
            exclude_condition_id="c_current",
            wallet_trade_history=wallet_history,
            condition_resolution_info=resolution_info,
            cache=cache,
        )

        self.assertIsNotNone(included)
        self.assertIsNotNone(excluded)
        assert included is not None
        assert excluded is not None
        self.assertEqual(included["trades"], 2.0)
        self.assertEqual(excluded["trades"], 1.0)
        self.assertEqual(included["all_trades"], 2.0)
        self.assertEqual(excluded["all_trades"], 1.0)


if __name__ == "__main__":
    unittest.main()
