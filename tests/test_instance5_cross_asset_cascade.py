from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3

from src.cross_asset_cascade import (
    _best_registry_rows_by_asset,
    apply_cluster_cap,
    build_cascade_payload,
    build_lookup_table,
    estimate_fair_prob_up,
    run_instance5_cycle,
    select_stress_mode,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _seed_history_db(path: Path, *, now: datetime, minutes: int = 900) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE reference_bars (
                venue TEXT NOT NULL,
                asset TEXT NOT NULL,
                interval TEXT NOT NULL,
                open_time_ms INTEGER NOT NULL,
                close_time_ms INTEGER NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL NOT NULL,
                source TEXT NOT NULL,
                inserted_at TEXT NOT NULL,
                PRIMARY KEY (venue, asset, interval, open_time_ms)
            )
            """
        )
        start_ms = int((now - timedelta(minutes=minutes + 5)).timestamp() * 1000)
        start_ms -= start_ms % 300_000
        prices = {
            "BTC": 100.0,
            "ETH": 50.0,
            "SOL": 20.0,
            "XRP": 5.0,
            "DOGE": 1.0,
        }
        multipliers = {
            "ETH": 0.95,
            "SOL": 0.85,
            "XRP": 0.75,
            "DOGE": 0.65,
        }
        rows: list[tuple] = []
        for idx in range(minutes):
            open_time_ms = start_ms + (idx * 60_000)
            close_time_ms = open_time_ms + 59_999
            btc_ret = 0.0034 if idx % 8 < 4 else -0.0030

            btc_open = prices["BTC"]
            btc_close = btc_open * (1.0 + btc_ret)
            prices["BTC"] = btc_close
            rows.append(
                (
                    "binance",
                    "BTC",
                    "1m",
                    open_time_ms,
                    close_time_ms,
                    btc_open,
                    max(btc_open, btc_close),
                    min(btc_open, btc_close),
                    btc_close,
                    1000.0,
                    "test_seed",
                    now.isoformat(),
                )
            )
            for asset, multiplier in multipliers.items():
                follower_ret = btc_ret * multiplier
                open_px = prices[asset]
                close_px = open_px * (1.0 + follower_ret)
                prices[asset] = close_px
                rows.append(
                    (
                        "binance",
                        asset,
                        "1m",
                        open_time_ms,
                        close_time_ms,
                        open_px,
                        max(open_px, close_px),
                        min(open_px, close_px),
                        close_px,
                        1000.0,
                        "test_seed",
                        now.isoformat(),
                    )
                )

        conn.executemany(
            """
            INSERT INTO reference_bars (
                venue,
                asset,
                interval,
                open_time_ms,
                close_time_ms,
                open,
                high,
                low,
                close,
                volume,
                source,
                inserted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )


def _seed_ticks_db(path: Path, *, now: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE market_envelopes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT UNIQUE NOT NULL,
                schema_version TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                event_at TEXT NOT NULL,
                event_ts_ms INTEGER NOT NULL,
                venue TEXT NOT NULL,
                venue_stream TEXT NOT NULL,
                asset TEXT NOT NULL,
                symbol TEXT NOT NULL,
                event_type TEXT NOT NULL,
                price REAL,
                size REAL,
                bid REAL,
                ask REAL,
                mid REAL,
                sequence INTEGER,
                sequence_gap INTEGER NOT NULL DEFAULT 0,
                staleness_ms INTEGER,
                metadata_json TEXT NOT NULL,
                raw_json TEXT NOT NULL,
                inserted_at_ts INTEGER NOT NULL
            );
            CREATE TABLE candle_anchors (
                anchor_id TEXT PRIMARY KEY,
                schema_version TEXT NOT NULL,
                asset TEXT NOT NULL,
                timeframe_seconds INTEGER NOT NULL,
                window_start_ts INTEGER NOT NULL,
                window_end_ts INTEGER NOT NULL,
                anchor_price REAL NOT NULL,
                source_event_id TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        now_ms = int(now.timestamp() * 1000)
        event_at = now.isoformat()
        inserted_at_ts = int(now.timestamp())
        rows = [
            (
                "ev-btc",
                "market_envelope.v1",
                event_at,
                event_at,
                now_ms - 1_000,
                "binance",
                "book_ticker",
                "BTC",
                "BTCUSDT",
                "book_ticker",
                None,
                None,
                100.79,
                100.81,
                100.80,
                None,
                0,
                0,
                "{}",
                "{}",
                inserted_at_ts,
            ),
            (
                "ev-eth",
                "market_envelope.v1",
                event_at,
                event_at,
                now_ms - 1_000,
                "binance",
                "book_ticker",
                "ETH",
                "ETHUSDT",
                "book_ticker",
                None,
                None,
                50.11,
                50.12,
                50.115,
                None,
                0,
                0,
                "{}",
                "{}",
                inserted_at_ts,
            ),
        ]
        conn.executemany(
            """
            INSERT INTO market_envelopes (
                event_id,
                schema_version,
                observed_at,
                event_at,
                event_ts_ms,
                venue,
                venue_stream,
                asset,
                symbol,
                event_type,
                price,
                size,
                bid,
                ask,
                mid,
                sequence,
                sequence_gap,
                staleness_ms,
                metadata_json,
                raw_json,
                inserted_at_ts
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )

        window_start_ts = int(now.timestamp()) - (int(now.timestamp()) % 300)
        conn.execute(
            """
            INSERT INTO candle_anchors (
                anchor_id,
                schema_version,
                asset,
                timeframe_seconds,
                window_start_ts,
                window_end_ts,
                anchor_price,
                source_event_id,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "anchor-btc-300",
                "candle_anchor.v1",
                "BTC",
                300,
                window_start_ts,
                window_start_ts + 300,
                100.0,
                "ev-btc",
                now.isoformat(),
            ),
        )


def _seed_reports(root: Path, *, now: datetime, one_second_ready: bool) -> None:
    ticks_db = root / "state" / "cross_asset_ticks.db"
    history_db = root / "state" / "cross_asset_history.db"
    _seed_ticks_db(ticks_db, now=now)
    _seed_history_db(history_db, now=now)

    _write_json(
        root / "reports" / "data_plane_health" / "latest.json",
        {
            "generated_at": now.isoformat(),
            "source_of_truth": str(ticks_db),
            "overall": {
                "global_asset_status": {
                    "BTC": {"best_venue": "binance"},
                    "ETH": {"best_venue": "binance"},
                    "SOL": {"best_venue": "binance"},
                    "XRP": {"best_venue": "binance"},
                    "DOGE": {"best_venue": "binance"},
                }
            },
        },
    )
    _write_json(
        root / "reports" / "market_registry" / "latest.json",
        {
            "generated_at": now.isoformat(),
            "registry": [
                {
                    "asset": "ETH",
                    "timeframe": "5m",
                    "timeframe_minutes": 5,
                    "eligible": True,
                    "quote_staleness_seconds": 3.0,
                    "best_bid": 0.39,
                    "best_ask": 0.40,
                    "mid": 0.395,
                },
                {
                    "asset": "SOL",
                    "timeframe": "5m",
                    "timeframe_minutes": 5,
                    "eligible": True,
                    "quote_staleness_seconds": 3.0,
                    "best_bid": 0.41,
                    "best_ask": 0.42,
                    "mid": 0.415,
                },
                {
                    "asset": "XRP",
                    "timeframe": "5m",
                    "timeframe_minutes": 5,
                    "eligible": True,
                    "quote_staleness_seconds": 3.0,
                    "best_bid": 0.43,
                    "best_ask": 0.44,
                    "mid": 0.435,
                },
                {
                    "asset": "DOGE",
                    "timeframe": "5m",
                    "timeframe_minutes": 5,
                    "eligible": True,
                    "quote_staleness_seconds": 3.0,
                    "best_bid": 0.45,
                    "best_ask": 0.46,
                    "mid": 0.455,
                },
            ],
        },
    )
    _write_json(
        root / "reports" / "cross_asset_history" / "latest.json",
        {
            "generated_at": now.isoformat(),
            "store_path": str(history_db),
            "coverage": {
                "complete_assets_1s": 5 if one_second_ready else 0,
                "missing_assets_1s": [] if one_second_ready else ["BTC", "ETH", "SOL", "XRP", "DOGE"],
            },
        },
    )
    _write_json(
        root / "reports" / "runtime_truth_latest.json",
        {
            "effective_caps": {"initial_bankroll": 250.0},
            "capital": {"tracked_capital_usd": 350.0},
        },
    )
    _write_json(
        root / "reports" / "finance" / "latest.json",
        {"finance_gate_pass": True, "finance_gate": {"pass": True}},
    )
    _write_json(
        root / "reports" / "instance3_vendor_backfill" / "latest.json",
        {
            "details": {
                "one_second_coverage_by_asset": {
                    asset: {"row_count": 1 if one_second_ready else 0}
                    for asset in ("BTC", "ETH", "SOL", "XRP", "DOGE")
                }
            }
        },
    )


def _insert_polymarket_btc_quote(path: Path, *, now: datetime, mid: float) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            INSERT INTO market_envelopes (
                event_id,
                schema_version,
                observed_at,
                event_at,
                event_ts_ms,
                venue,
                venue_stream,
                asset,
                symbol,
                event_type,
                price,
                size,
                bid,
                ask,
                mid,
                sequence,
                sequence_gap,
                staleness_ms,
                metadata_json,
                raw_json,
                inserted_at_ts
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "ev-btc-poly",
                "market_envelope.v1",
                now.isoformat(),
                now.isoformat(),
                int(now.timestamp() * 1000),
                "polymarket",
                "rest.gamma_clob",
                "BTC",
                "btc-5m-updown",
                "market_quote",
                None,
                None,
                0.48,
                0.50,
                mid,
                None,
                0,
                0,
                "{}",
                "{}",
                int(now.timestamp()),
            ),
        )


def test_lookup_probability_estimation_uses_historical_conditional_table(tmp_path: Path) -> None:
    now = datetime(2026, 3, 11, 12, 0, 30, tzinfo=timezone.utc)
    history_db = tmp_path / "state" / "cross_asset_history.db"
    _seed_history_db(history_db, now=now)
    lookup = build_lookup_table(history_db, now=now, lookback_days=30)

    fair_prob, support, matched_key = estimate_fair_prob_up(
        lookup,
        follower_asset="ETH",
        leader_move=0.0035,
        elapsed_seconds=60.0,
        volatility_proxy_move=0.0035,
    )

    assert support > 0
    assert fair_prob > 0.55
    assert "fallback" not in matched_key


def test_cluster_cap_scales_total_notional_to_six_percent_of_bankroll() -> None:
    scaled, scale = apply_cluster_cap(
        {"ETH": 5.0, "SOL": 5.0, "XRP": 5.0},
        bankroll=100.0,
    )
    assert scale < 1.0
    assert round(sum(scaled.values()), 6) == 6.0
    assert all(value <= 5.0 for value in scaled.values())


def test_best_registry_rows_prefer_eligible_5m_rows_over_fresher_intraday_rows() -> None:
    selected = _best_registry_rows_by_asset(
        [
            {
                "asset": "ETH",
                "timeframe": "15m",
                "timeframe_minutes": 15,
                "eligible": True,
                "quote_staleness_seconds": 1.0,
                "best_bid": 0.51,
                "best_ask": 0.52,
                "mid": 0.515,
            },
            {
                "asset": "ETH",
                "timeframe": "5m",
                "timeframe_minutes": 5,
                "eligible": True,
                "quote_staleness_seconds": 4.0,
                "best_bid": 0.41,
                "best_ask": 0.42,
                "mid": 0.415,
            },
        ]
    )

    assert selected["ETH"]["timeframe_minutes"] == 5
    assert selected["ETH"]["mid"] == 0.415


def test_stress_mode_selection_switches_on_one_second_coverage() -> None:
    local_mode = select_stress_mode(
        {"coverage": {"complete_assets_1s": 0, "missing_assets_1s": ["BTC"]}},
        {},
    )
    batch_mode = select_stress_mode(
        {"coverage": {"complete_assets_1s": 5, "missing_assets_1s": []}},
        {},
    )
    assert local_mode == "local_only"
    assert batch_mode == "batch_plus_replay"


def test_instance5_cycle_emits_shadow_intents_and_local_only_mc_when_1s_missing(tmp_path: Path) -> None:
    now = datetime(2026, 3, 11, 12, 0, 30, tzinfo=timezone.utc)
    _seed_reports(tmp_path, now=now, one_second_ready=False)

    result = run_instance5_cycle(tmp_path, now=now)

    cascade_payload = result["cross_asset_cascade"]["payload"]
    mc_payload = result["cross_asset_mc"]["payload"]
    summary_payload = result["instance5_cascade_mc"]["payload"]

    assert Path(result["cross_asset_cascade"]["latest"]).exists()
    assert Path(result["cross_asset_mc"]["latest"]).exists()
    assert Path(result["instance5_cascade_mc"]["latest"]).exists()
    assert cascade_payload["schema_version"] == "cross_asset_cascade.v1"
    assert mc_payload["schema_version"] == "cross_asset_mc.v1"
    assert len(cascade_payload["intents"]) >= 1
    assert cascade_payload["shadow_intended_notional_usd"] > 0.0
    assert sum(intent["notional_usd"] for intent in cascade_payload["intents"]) <= 15.0
    eth_payload = cascade_payload["followers"]["ETH"]
    assert eth_payload["transfer_entropy_bits"] >= 0.0
    assert eth_payload["renyi_transfer_entropy_bits"] >= 0.0
    assert eth_payload["symbolic_transfer_entropy_bits"] >= 0.0
    assert eth_payload["information_flow_gate_pass"] is True
    assert eth_payload["maker_rebate_bps"] > 0.0
    assert eth_payload["post_cost_ev"] == round(eth_payload["post_cost_ev_bps"] / 10_000.0, 6)
    assert mc_payload["stress_mode"] == "local_only"
    assert summary_payload["finance_gate_pass"] is True


def test_instance5_cycle_switches_to_batch_plus_replay_when_1s_ready(tmp_path: Path) -> None:
    now = datetime(2026, 3, 11, 12, 0, 30, tzinfo=timezone.utc)
    _seed_reports(tmp_path, now=now, one_second_ready=True)

    result = run_instance5_cycle(tmp_path, now=now)
    mc_payload = result["cross_asset_mc"]["payload"]

    assert mc_payload["stress_mode"] == "batch_plus_replay"
    assert mc_payload["paths"]["stress"] == 10000


def test_cascade_uses_centralized_btc_reference_even_if_health_prefers_polymarket(tmp_path: Path) -> None:
    now = datetime(2026, 3, 11, 12, 0, 30, tzinfo=timezone.utc)
    _seed_reports(tmp_path, now=now, one_second_ready=True)
    ticks_db = tmp_path / "state" / "cross_asset_ticks.db"
    _insert_polymarket_btc_quote(ticks_db, now=now, mid=0.49)

    health_path = tmp_path / "reports" / "data_plane_health" / "latest.json"
    health_payload = json.loads(health_path.read_text(encoding="utf-8"))
    health_payload["overall"]["global_asset_status"]["BTC"]["best_venue"] = "polymarket"
    health_path.write_text(json.dumps(health_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    payload = build_cascade_payload(tmp_path, now=now)

    assert payload["leader_reference_venue"] == "binance"
    assert payload["leader_price"] > 100.0
    assert abs(payload["leader_move_from_open"]) < 0.1
