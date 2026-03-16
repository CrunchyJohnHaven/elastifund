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
            order_status TEXT
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
    rows = [
        ("DOWN", 0.91, 0.60, 1, 0.0030, (now - timedelta(minutes=50)).isoformat(), "live_filled"),
        ("UP", 0.90, 0.50, 1, 0.0020, (now - timedelta(minutes=45)).isoformat(), "live_filled"),
        ("DOWN", 0.88, 0.80, 1, 0.0010, (now - timedelta(minutes=40)).isoformat(), "live_filled"),
        ("UP", 0.96, -0.40, 0, 0.0065, (now - timedelta(minutes=35)).isoformat(), "live_filled"),
        ("DOWN", 0.95, -0.20, 0, 0.0040, (now - timedelta(minutes=30)).isoformat(), "live_filled"),
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
        lookback_hours=24,
        mutation_count=5,
        rng_seed=7,
    )
    assert result["status"] == "insufficient_data"
    assert result["replay_rows"] == 0
    assert not overrides_path.exists()


def test_mutate_changes_generation_and_respects_bounds() -> None:
    parent = ParameterGenome(
        min_buy_price=0.86,
        max_buy_price=0.99,
        min_delta=0.0,
        max_delta=0.01,
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
        min_buy_price=0.90,
        max_buy_price=0.96,
        min_delta=0.001,
        max_delta=0.006,
        generation=0,
        fitness=0.0,
    )
    fills = [
        {
            "direction": "DOWN",
            "order_price": 0.92,
            "delta": 0.003,
            "won": 1,
            "pnl_usd": 0.40,
        },
        {
            "direction": "UP",
            "order_price": 0.95,
            "delta": 0.002,
            "won": 0,
            "pnl_usd": -0.30,
        },
        {
            "direction": "UP",
            "order_price": 0.99,
            "delta": 0.003,
            "won": 1,
            "pnl_usd": 0.50,
        },
    ]
    skips = [
        {
            "direction": "DOWN",
            "order_price": 0.93,
            "delta": 0.002,
            "resolved_side": "DOWN",
        },
        {
            "direction": "UP",
            "order_price": 0.94,
            "delta": 0.002,
            "resolved_side": "DOWN",
        },
    ]
    fitness = evaluate_fitness(genome, fills, skips)
    assert fitness == 0.0


def test_evolve_generation_persists_10_genomes(tmp_path: Path) -> None:
    db_path = tmp_path / "btc5_evolve.db"
    population_path = tmp_path / "pricing_population.json"
    _create_window_trades_table(db_path)
    now = datetime.now(timezone.utc)
    rows = [
        ("DOWN", 0.91, 0.60, 1, 0.0030, (now - timedelta(minutes=50)).isoformat(), "live_filled"),
        ("UP", 0.94, -0.40, 0, 0.0020, (now - timedelta(minutes=40)).isoformat(), "live_filled"),
        ("UP", 0.93, 0.0, None, 0.0025, (now - timedelta(minutes=30)).isoformat(), "skip_delta_too_large"),
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
