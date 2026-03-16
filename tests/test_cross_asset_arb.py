from __future__ import annotations

from pathlib import Path
import sqlite3

from bot.cross_asset_arb import ASSET_ORDER, build_leadlag_payload


def _create_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE window_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                window_start_ts INTEGER NOT NULL UNIQUE,
                decision_ts INTEGER NOT NULL,
                delta REAL,
                direction TEXT,
                resolved_side TEXT,
                order_status TEXT
            )
            """
        )


def _insert_row(
    db_path: Path,
    *,
    window_start_ts: int,
    decision_ts: int,
    delta: float,
    direction: str = "UP",
    resolved_side: str = "UP",
    order_status: str = "live_filled",
) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO window_trades (
                window_start_ts,
                decision_ts,
                delta,
                direction,
                resolved_side,
                order_status
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (window_start_ts, decision_ts, delta, direction, resolved_side, order_status),
        )


def _db_map(base: Path) -> dict[str, Path]:
    return {
        "BTC": Path("data/btc_5min_maker.db"),
        "ETH": Path("data/eth_5min_maker.db"),
        "SOL": Path("data/sol_5min_maker.db"),
        "BNB": Path("data/bnb_5min_maker.db"),
        "DOGE": Path("data/doge_5min_maker.db"),
        "XRP": Path("data/xrp_5min_maker.db"),
    }


def test_cross_asset_arb_builds_btc_first_follower_lag_table(tmp_path: Path) -> None:
    db_paths = _db_map(tmp_path)
    abs_paths = {asset: tmp_path / rel for asset, rel in db_paths.items()}
    for path in abs_paths.values():
        _create_db(path)

    ws1 = 1_000
    _insert_row(abs_paths["BTC"], window_start_ts=ws1, decision_ts=1_010, delta=0.0030)
    _insert_row(abs_paths["ETH"], window_start_ts=ws1, decision_ts=1_015, delta=0.0015)
    _insert_row(abs_paths["SOL"], window_start_ts=ws1, decision_ts=1_012, delta=0.0012)
    _insert_row(abs_paths["BNB"], window_start_ts=ws1, decision_ts=1_020, delta=0.0010)
    _insert_row(abs_paths["DOGE"], window_start_ts=ws1, decision_ts=1_018, delta=0.0008)
    _insert_row(abs_paths["XRP"], window_start_ts=ws1, decision_ts=1_025, delta=0.0009)

    ws2 = 1_300
    _insert_row(abs_paths["ETH"], window_start_ts=ws2, decision_ts=1_310, delta=0.0025)
    _insert_row(abs_paths["BTC"], window_start_ts=ws2, decision_ts=1_320, delta=0.0040)
    _insert_row(abs_paths["SOL"], window_start_ts=ws2, decision_ts=1_315, delta=0.0010)

    ws3 = 1_600
    _insert_row(abs_paths["BTC"], window_start_ts=ws3, decision_ts=1_610, delta=0.0015)
    _insert_row(abs_paths["ETH"], window_start_ts=ws3, decision_ts=1_620, delta=0.0010)
    _insert_row(abs_paths["DOGE"], window_start_ts=ws3, decision_ts=1_615, delta=0.0007)

    payload = build_leadlag_payload(
        root=tmp_path,
        db_paths=db_paths,
        btc_first_delta_threshold=0.002,
        window_details_limit=50,
    )

    assert payload["schema_version"] == "cross_asset_leadlag.v1"
    assert payload["stats"]["multi_asset_windows"] == 3
    assert payload["stats"]["all_asset_windows"] == 1
    assert payload["first_asset_counts"]["BTC"] == 2
    assert payload["first_asset_counts"]["ETH"] == 1
    assert payload["btc_first_threshold_follow"]["qualifying_windows"] == 1
    assert payload["btc_first_threshold_follow"]["followers"]["ETH"]["lag_seconds"]["median"] == 5.0
    assert payload["missing_assets"] == []


def test_cross_asset_arb_counts_tied_first_windows(tmp_path: Path) -> None:
    db_paths = _db_map(tmp_path)
    abs_paths = {asset: tmp_path / rel for asset, rel in db_paths.items()}
    for path in abs_paths.values():
        _create_db(path)

    ws = 2_000
    _insert_row(abs_paths["BTC"], window_start_ts=ws, decision_ts=2_010, delta=0.0030)
    _insert_row(abs_paths["ETH"], window_start_ts=ws, decision_ts=2_010, delta=0.0020)
    _insert_row(abs_paths["SOL"], window_start_ts=ws, decision_ts=2_020, delta=0.0010)

    payload = build_leadlag_payload(
        root=tmp_path,
        db_paths=db_paths,
        btc_first_delta_threshold=0.002,
        window_details_limit=10,
    )

    assert payload["stats"]["multi_asset_windows"] == 1
    assert payload["stats"]["tied_first_windows"] == 1
    assert payload["first_asset_counts"]["BTC"] == 0
    assert payload["first_asset_counts"]["ETH"] == 0
    assert payload["leader_first_windows_including_ties"]["BTC"] == 1
    assert payload["leader_first_windows_including_ties"]["ETH"] == 1
    assert payload["btc_first_threshold_follow"]["qualifying_windows"] == 1
    assert len(payload["window_samples_recent"]) == 1
    assert payload["window_samples_recent"][0]["first_assets"] == ["BTC", "ETH"]
    assert payload["assets"] == list(ASSET_ORDER)
