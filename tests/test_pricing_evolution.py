from __future__ import annotations

import json
import random
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bot.pricing_evolution import (
    MAX_BUY_CAP,
    MAX_RISK_FRACTION,
    MIN_BUY_FLOOR,
    MIN_FITNESS_TO_PROMOTE,
    ParameterGenome,
    evaluate_fitness,
    evolve_generation,
    mutate,
    run_pricing_evolution,
)


def _create_window_trades_table(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE window_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            direction TEXT,
            order_price REAL,
            pnl_usd REAL,
            won INTEGER,
            delta REAL,
            created_at TEXT,
            order_status TEXT,
            resolved_side TEXT,
            best_ask REAL,
            best_bid REAL,
            current_price REAL
        )
        """
    )
    conn.commit()
    conn.close()


def test_pricing_evolution_promotes_bounded_genome(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "btc5.db"
    overrides_path = tmp_path / "autoresearch_overrides.json"
    population_path = tmp_path / "pricing_population.json"
    monkeypatch.setenv("BTC5_PRICING_POPULATION_PATH", str(population_path))
    _create_window_trades_table(db_path)

    now = datetime.now(timezone.utc)
    # Prices in the new regime: 0.04-0.55
    rows = [
        ("DOWN", 0.45, 8.80, 1, 0.0030, (now - timedelta(minutes=50)).isoformat(), "live_filled"),
        ("DOWN", 0.40, 7.50, 1, 0.0020, (now - timedelta(minutes=45)).isoformat(), "live_filled"),
        ("DOWN", 0.35, 6.80, 1, 0.0010, (now - timedelta(minutes=40)).isoformat(), "live_filled"),
        ("DOWN", 0.48, -7.80, 0, 0.0065, (now - timedelta(minutes=35)).isoformat(), "live_filled"),
        ("DOWN", 0.50, -7.20, 0, 0.0040, (now - timedelta(minutes=30)).isoformat(), "live_filled"),
    ]
    conn = sqlite3.connect(db_path)
    conn.executemany(
        """
        INSERT INTO window_trades(direction, order_price, pnl_usd, won, delta, created_at, order_status)
        VALUES (?,?,?,?,?,?,?)
        """,
        rows,
    )
    conn.commit()
    conn.close()

    result = run_pricing_evolution(
        db_path=db_path,
        overrides_path=overrides_path,
        population_path=population_path,
        lookback_hours=24,
        mutation_count=6,
        rng_seed=42,
    )

    assert result["status"] == "promoted"
    assert result["mutation_count"] == 6
    assert result["replay_rows"] == 5

    promoted = json.loads(overrides_path.read_text())
    assert promoted["promotion_stage"] == "validated"
    assert isinstance(promoted.get("lineage"), list)
    assert len(promoted["lineage"]) >= 1

    params = promoted["params"]
    assert params["BTC5_MIN_BUY_PRICE"] >= MIN_BUY_FLOOR
    assert params["BTC5_DOWN_MAX_BUY_PRICE"] <= MAX_BUY_CAP
    assert params["BTC5_UP_MAX_BUY_PRICE"] <= MAX_BUY_CAP
    assert params["BTC5_RISK_FRACTION"] <= MAX_RISK_FRACTION
    assert params["BTC5_DOWN_MAX_BUY_PRICE"] >= params["BTC5_MIN_BUY_PRICE"]
    assert params["BTC5_UP_MAX_BUY_PRICE"] >= params["BTC5_MIN_BUY_PRICE"]


def test_pricing_evolution_returns_insufficient_data_when_no_rows(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "btc5_empty.db"
    overrides_path = tmp_path / "autoresearch_overrides.json"
    population_path = tmp_path / "pricing_population.json"
    monkeypatch.setenv("BTC5_PRICING_POPULATION_PATH", str(population_path))
    _create_window_trades_table(db_path)

    result = run_pricing_evolution(
        db_path=db_path,
        overrides_path=overrides_path,
        population_path=population_path,
        lookback_hours=24,
        mutation_count=5,
        rng_seed=7,
    )
    assert result["status"] == "insufficient_data"
    assert result["replay_rows"] == 0
    assert not overrides_path.exists()


def test_mutate_changes_generation_and_respects_bounds() -> None:
    parent = ParameterGenome(
        min_buy_price=0.30,
        max_buy_price=0.50,
        min_delta=0.0003,
        max_delta=0.008,
        generation=5,
        fitness=0.25,
    )
    child = mutate(parent, rng=random.Random(7))
    assert child.generation == 6
    assert child.min_buy_price >= MIN_BUY_FLOOR
    assert child.max_buy_price <= MAX_BUY_CAP
    assert child.max_buy_price >= child.min_buy_price
    assert child.max_delta >= child.min_delta


def test_evaluate_fitness_counts_fill_and_skip_counterfactuals() -> None:
    genome = ParameterGenome(
        min_buy_price=0.30,
        max_buy_price=0.53,
        min_delta=0.001,
        max_delta=0.006,
        generation=0,
        fitness=0.0,
    )
    fills = [
        {
            "direction": "DOWN",
            "order_price": 0.45,
            "delta": 0.003,
            "won": 1,
            "pnl_usd": 8.80,
        },
        {
            "direction": "DOWN",
            "order_price": 0.48,
            "delta": 0.002,
            "won": 0,
            "pnl_usd": -7.80,
        },
        {
            "direction": "DOWN",
            "order_price": 0.60,
            "delta": 0.003,
            "won": 1,
            "pnl_usd": 6.50,
        },
    ]
    skips = [
        {
            "direction": "DOWN",
            "order_price": 0.42,
            "delta": 0.002,
            "resolved_side": "DOWN",
        },
        {
            "direction": "UP",
            "order_price": 0.40,
            "delta": 0.002,
            "resolved_side": "DOWN",
        },
    ]
    fitness = evaluate_fitness(genome, fills, skips)
    # fill at 0.45 (won) + fill at 0.48 (lost) + skip at 0.42 (DOWN==DOWN, win) + skip at 0.40 (UP!=DOWN, loss)
    # fill at 0.60 is outside max_buy_price=0.53, excluded
    # 2 wins, 2 losses = 0.0
    assert fitness == 0.0


def test_evolve_generation_persists_10_genomes(tmp_path: Path) -> None:
    db_path = tmp_path / "btc5_evolve.db"
    population_path = tmp_path / "pricing_population.json"
    _create_window_trades_table(db_path)
    now = datetime.now(timezone.utc)
    rows = [
        ("DOWN", 0.45, 8.80, 1, 0.0030, (now - timedelta(minutes=50)).isoformat(), "live_filled"),
        ("DOWN", 0.48, -7.80, 0, 0.0020, (now - timedelta(minutes=40)).isoformat(), "live_filled"),
        ("DOWN", 0.42, 0.0, None, 0.0025, (now - timedelta(minutes=30)).isoformat(), "skip_delta_too_large"),
    ]
    conn = sqlite3.connect(db_path)
    conn.executemany(
        """
        INSERT INTO window_trades(direction, order_price, pnl_usd, won, delta, created_at, order_status)
        VALUES (?,?,?,?,?,?,?)
        """,
        rows,
    )
    conn.commit()
    conn.close()

    result = evolve_generation(
        db_path=db_path,
        population_path=population_path,
        lookback_hours=24,
        rng_seed=99,
    )
    assert result["status"] == "evolved"
    payload = json.loads(population_path.read_text())
    assert len(payload["population"]) == 10


def test_promotion_gate_blocks_zero_fitness(tmp_path: Path, monkeypatch) -> None:
    """Promotion should be blocked when champion fitness is below threshold."""
    db_path = tmp_path / "btc5.db"
    overrides_path = tmp_path / "autoresearch_overrides.json"
    population_path = tmp_path / "pricing_population.json"
    monkeypatch.setenv("BTC5_PRICING_POPULATION_PATH", str(population_path))
    _create_window_trades_table(db_path)

    now = datetime.now(timezone.utc)
    # Only skips with no resolved_side — fitness will be 0.0 for all genomes
    rows = [
        ("DOWN", 0.45, None, None, 0.003, (now - timedelta(minutes=50)).isoformat(), "skip_delta_too_large"),
        ("UP", 0.40, None, None, 0.002, (now - timedelta(minutes=40)).isoformat(), "skip_bad_book"),
    ]
    conn = sqlite3.connect(db_path)
    conn.executemany(
        """
        INSERT INTO window_trades(direction, order_price, pnl_usd, won, delta, created_at, order_status)
        VALUES (?,?,?,?,?,?,?)
        """,
        rows,
    )
    conn.commit()
    conn.close()

    result = run_pricing_evolution(
        db_path=db_path,
        overrides_path=overrides_path,
        population_path=population_path,
        lookback_hours=24,
        rng_seed=42,
    )

    # Should NOT promote — fitness is 0.0 < MIN_FITNESS_TO_PROMOTE
    assert result["status"] == "insufficient_data"
    assert not overrides_path.exists()


def test_promotion_gate_blocks_identical_genome(tmp_path: Path, monkeypatch) -> None:
    """Promotion should be blocked when champion is identical to current."""
    db_path = tmp_path / "btc5.db"
    overrides_path = tmp_path / "autoresearch_overrides.json"
    population_path = tmp_path / "pricing_population.json"
    monkeypatch.setenv("BTC5_PRICING_POPULATION_PATH", str(population_path))
    _create_window_trades_table(db_path)

    now = datetime.now(timezone.utc)
    rows = [
        ("DOWN", 0.45, 8.80, 1, 0.003, (now - timedelta(minutes=50)).isoformat(), "live_filled"),
        ("DOWN", 0.40, 7.50, 1, 0.002, (now - timedelta(minutes=45)).isoformat(), "live_filled"),
        ("DOWN", 0.35, 6.80, 1, 0.001, (now - timedelta(minutes=40)).isoformat(), "live_filled"),
        ("DOWN", 0.48, -7.80, 0, 0.005, (now - timedelta(minutes=35)).isoformat(), "live_filled"),
    ]
    conn = sqlite3.connect(db_path)
    conn.executemany(
        """
        INSERT INTO window_trades(direction, order_price, pnl_usd, won, delta, created_at, order_status)
        VALUES (?,?,?,?,?,?,?)
        """,
        rows,
    )
    conn.commit()
    conn.close()

    # First promotion should work
    result1 = run_pricing_evolution(
        db_path=db_path,
        overrides_path=overrides_path,
        population_path=population_path,
        lookback_hours=24,
        rng_seed=42,
    )
    assert result1["status"] == "promoted"

    # Second promotion with same data and seed should be blocked (identical genome)
    result2 = run_pricing_evolution(
        db_path=db_path,
        overrides_path=overrides_path,
        population_path=population_path,
        lookback_hours=24,
        rng_seed=42,
    )
    # Should either be skipped_no_change or insufficient_data (via the wrapper)
    assert result2["status"] == "insufficient_data"
