from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlite3
import time
from pathlib import Path

from bot.multi_asset_arb import generate_cross_asset_signals, load_asset_confirmation, write_cross_asset_signals


def _seed_prices(db_path: Path, *, start_ts: int, prices: list[float]) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS window_trades (
                decision_ts INTEGER,
                current_price REAL
            )
            """
        )
        for idx, price in enumerate(prices):
            conn.execute(
                "INSERT INTO window_trades(decision_ts, current_price) VALUES (?, ?)",
                (int(start_ts + (idx * 60)), float(price)),
            )


def _prices_from_returns(start_price: float, returns: list[float]) -> list[float]:
    prices = [float(start_price)]
    for ret in returns:
        prices.append(prices[-1] * (1.0 + float(ret)))
    return prices


def test_generate_cross_asset_signals_detects_btc_leading_eth(tmp_path: Path) -> None:
    n = 180
    btc_returns = [0.0010 if idx % 3 == 0 else -0.0007 if idx % 3 == 1 else 0.0005 for idx in range(n)]
    eth_returns = [0.0] + [btc_returns[idx - 1] for idx in range(1, n)]
    btc_prices = _prices_from_returns(100.0, btc_returns)
    eth_prices = _prices_from_returns(200.0, eth_returns)
    start_ts = int(time.time()) - ((n + 5) * 60)

    btc_db = tmp_path / "btc.db"
    eth_db = tmp_path / "eth.db"
    _seed_prices(btc_db, start_ts=start_ts, prices=btc_prices)
    _seed_prices(eth_db, start_ts=start_ts, prices=eth_prices)

    payload = generate_cross_asset_signals(
        db_paths={"BTCUSDT": btc_db, "ETHUSDT": eth_db},
        lookback_minutes=120,
        max_lag_minutes=3,
        min_points=60,
        min_correlation=0.2,
        min_signal_confidence=0.5,
    )

    metrics = [
        row
        for row in payload.get("pair_metrics", [])
        if row.get("leader") == "BTCUSDT" and row.get("follower") == "ETHUSDT"
    ]
    assert metrics, "expected BTC->ETH lead/lag metric"
    top = metrics[0]
    assert int(top.get("lag_minutes") or 0) == 1
    assert float(top.get("correlation") or 0.0) > 0.8

    signal = payload.get("signals", {}).get("ETHUSDT")
    assert isinstance(signal, dict)
    expected_direction = "UP" if btc_returns[-1] > 0 else "DOWN"
    assert signal.get("direction") == expected_direction
    assert float(signal.get("confidence") or 0.0) >= 0.5


def test_load_asset_confirmation_applies_freshness_direction_and_confidence(tmp_path: Path) -> None:
    path = tmp_path / "cross_asset_signals.json"
    payload = {
        "schema_version": "cross_asset_signals.v1",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "signals": {
            "ETHUSDT": {
                "direction": "UP",
                "confidence": 0.74,
                "leader": "BTCUSDT",
                "lag_minutes": 1,
                "correlation": 0.67,
                "score": 1.2,
            }
        },
    }
    write_cross_asset_signals(path, payload)

    confirmed = load_asset_confirmation(
        signals_path=path,
        asset_symbol="ETHUSDT",
        direction="UP",
        max_age_seconds=900,
        min_confidence=0.6,
    )
    assert confirmed is not None
    assert confirmed.get("leader") == "BTCUSDT"
    assert int(confirmed.get("lag_minutes") or 0) == 1

    mismatch = load_asset_confirmation(
        signals_path=path,
        asset_symbol="ETHUSDT",
        direction="DOWN",
        max_age_seconds=900,
        min_confidence=0.6,
    )
    assert mismatch is None

    stale_payload = dict(payload)
    stale_payload["generated_at"] = (
        datetime.now(timezone.utc) - timedelta(hours=2)
    ).isoformat().replace("+00:00", "Z")
    write_cross_asset_signals(path, stale_payload)
    stale = load_asset_confirmation(
        signals_path=path,
        asset_symbol="ETHUSDT",
        direction="UP",
        max_age_seconds=900,
        min_confidence=0.6,
    )
    assert stale is None

