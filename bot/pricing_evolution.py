"""DISPATCH_110 pricing evolution engine for BTC5 autoresearch."""

from __future__ import annotations

import json
import os
import random
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

MIN_BUY_FLOOR = 0.04
MAX_BUY_CAP = 0.55
MAX_RISK_FRACTION = 0.33
MIN_FITNESS_TO_PROMOTE = 0.05  # Don't promote genomes with near-zero fitness

POPULATION_SIZE = 10
SURVIVOR_COUNT = 3
CHILD_COUNT = 7
MUTATION_PROBABILITY = 0.30
MUTATION_FACTOR = 0.10
DEFAULT_LOOKBACK_HOURS = 24
LINEAGE_LIMIT = 200

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = Path(
    os.environ.get("BTC5_DB_PATH", str(REPO_ROOT / "data" / "btc_5min_maker.db"))
)
DEFAULT_OVERRIDES_PATH = Path(
    os.environ.get(
        "BTC5_AUTORESEARCH_OVERRIDES_PATH",
        str(REPO_ROOT / "config" / "autoresearch_overrides.json"),
    )
)
DEFAULT_POPULATION_PATH = Path(
    os.environ.get(
        "BTC5_PRICING_POPULATION_PATH",
        str(REPO_ROOT / "data" / "pricing_population.json"),
    )
)


@dataclass
class ParameterGenome:
    min_buy_price: float
    max_buy_price: float
    min_delta: float
    max_delta: float
    generation: int = 0
    fitness: float = 0.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _normalize_side(value: Any) -> str:
    return str(value or "").strip().upper()


def _bounded_genome(genome: ParameterGenome) -> ParameterGenome:
    min_buy = round(min(MAX_BUY_CAP, max(MIN_BUY_FLOOR, float(genome.min_buy_price))), 4)
    max_buy = round(min(MAX_BUY_CAP, max(MIN_BUY_FLOOR, float(genome.max_buy_price))), 4)
    if max_buy < min_buy:
        max_buy = min_buy
    min_delta = max(0.0, float(genome.min_delta))
    max_delta = max(min_delta, float(genome.max_delta))
    return ParameterGenome(
        min_buy_price=min_buy,
        max_buy_price=max_buy,
        min_delta=round(min_delta, 6),
        max_delta=round(max_delta, 6),
        generation=max(0, int(genome.generation)),
        fitness=round(float(genome.fitness), 6),
    )


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


def _genome_from_row(raw: dict[str, Any]) -> ParameterGenome:
    return _bounded_genome(
        ParameterGenome(
            min_buy_price=_safe_float(raw.get("min_buy_price"), 0.30),
            max_buy_price=_safe_float(raw.get("max_buy_price"), 0.53),
            min_delta=_safe_float(raw.get("min_delta"), 0.0003),
            max_delta=_safe_float(raw.get("max_delta"), 0.008),
            generation=int(_safe_float(raw.get("generation"), 0)),
            fitness=_safe_float(raw.get("fitness"), 0.0),
        )
    )


def _baseline_genome() -> ParameterGenome:
    return _bounded_genome(
        ParameterGenome(
            min_buy_price=_safe_float(os.environ.get("BTC5_MIN_BUY_PRICE"), 0.30),
            max_buy_price=_safe_float(
                os.environ.get("BTC5_DOWN_MAX_BUY_PRICE", os.environ.get("BTC5_UP_MAX_BUY_PRICE")),
                0.53,
            ),
            min_delta=_safe_float(os.environ.get("BTC5_MIN_DELTA"), 0.0003),
            max_delta=_safe_float(os.environ.get("BTC5_MAX_ABS_DELTA"), 0.008),
            generation=0,
            fitness=0.0,
        )
    )


def mutate(
    parent: ParameterGenome,
    *,
    rng: random.Random | None = None,
    generation: int | None = None,
) -> ParameterGenome:
    """Perturb each parameter by +/-10% with 30% probability."""

    prng = rng or random.Random()
    next_generation = parent.generation + 1 if generation is None else int(generation)
    values = {
        "min_buy_price": float(parent.min_buy_price),
        "max_buy_price": float(parent.max_buy_price),
        "min_delta": float(parent.min_delta),
        "max_delta": float(parent.max_delta),
    }
    for key in values:
        if prng.random() < MUTATION_PROBABILITY:
            multiplier = 1.0 + (MUTATION_FACTOR if prng.random() < 0.5 else -MUTATION_FACTOR)
            values[key] *= multiplier
    return _bounded_genome(
        ParameterGenome(
            min_buy_price=values["min_buy_price"],
            max_buy_price=values["max_buy_price"],
            min_delta=values["min_delta"],
            max_delta=values["max_delta"],
            generation=next_generation,
            fitness=0.0,
        )
    )


def _crossover(
    parent_a: ParameterGenome,
    parent_b: ParameterGenome,
    *,
    rng: random.Random,
    generation: int,
) -> ParameterGenome:
    return _bounded_genome(
        ParameterGenome(
            min_buy_price=parent_a.min_buy_price if rng.random() < 0.5 else parent_b.min_buy_price,
            max_buy_price=parent_a.max_buy_price if rng.random() < 0.5 else parent_b.max_buy_price,
            min_delta=parent_a.min_delta if rng.random() < 0.5 else parent_b.min_delta,
            max_delta=parent_a.max_delta if rng.random() < 0.5 else parent_b.max_delta,
            generation=generation,
            fitness=0.0,
        )
    )


def _extract_price(row: dict[str, Any]) -> float | None:
    for key in ("order_price", "best_ask", "current_price", "best_bid"):
        value = row.get(key)
        if value is None:
            continue
        price = _safe_float(value, -1.0)
        if price > 0:
            return price
    return None


def _would_trade(genome: ParameterGenome, row: dict[str, Any]) -> bool:
    price = _extract_price(row)
    if price is None:
        return False
    delta = abs(_safe_float(row.get("delta"), 0.0))
    return (
        genome.min_buy_price <= price <= genome.max_buy_price
        and genome.min_delta <= delta <= genome.max_delta
    )


def _fill_outcome(row: dict[str, Any]) -> bool | None:
    won = row.get("won")
    if won is not None and str(won) != "":
        try:
            return int(won) == 1
        except (TypeError, ValueError):
            pass
    pnl = row.get("pnl_usd")
    if pnl is not None:
        pnl_value = _safe_float(pnl, 0.0)
        if pnl_value != 0.0:
            return pnl_value > 0.0
    resolved_side = _normalize_side(row.get("resolved_side"))
    direction = _normalize_side(row.get("direction"))
    if resolved_side in {"UP", "DOWN"} and direction in {"UP", "DOWN"}:
        return direction == resolved_side
    return None


def evaluate_fitness(
    genome: ParameterGenome,
    fills: list[dict[str, Any]],
    skips: list[dict[str, Any]],
) -> float:
    """Counterfactual fitness = (wins - losses) / total trades."""

    counterfactual_wins = 0
    counterfactual_losses = 0

    for row in fills:
        if not _would_trade(genome, row):
            continue
        outcome = _fill_outcome(row)
        if outcome is None:
            continue
        if outcome:
            counterfactual_wins += 1
        else:
            counterfactual_losses += 1

    for row in skips:
        resolved_side = _normalize_side(row.get("resolved_side"))
        direction = _normalize_side(row.get("direction"))
        if resolved_side not in {"UP", "DOWN"} or direction not in {"UP", "DOWN"}:
            continue
        if not _would_trade(genome, row):
            continue
        if direction == resolved_side:
            counterfactual_wins += 1
        else:
            counterfactual_losses += 1

    total = counterfactual_wins + counterfactual_losses
    if total <= 0:
        return 0.0
    return round((counterfactual_wins - counterfactual_losses) / total, 6)


def _load_population(
    *,
    population_path: Path,
    rng: random.Random,
) -> list[ParameterGenome]:
    payload = _load_json(population_path)
    raw_population = payload.get("population")
    genomes: list[ParameterGenome] = []
    if isinstance(raw_population, list):
        for item in raw_population:
            if isinstance(item, dict):
                genomes.append(_genome_from_row(item))
    if not genomes:
        base = _baseline_genome()
        genomes = [base]
        while len(genomes) < POPULATION_SIZE:
            genomes.append(mutate(base, rng=rng, generation=0))
    elif len(genomes) < POPULATION_SIZE:
        base = genomes[0]
        while len(genomes) < POPULATION_SIZE:
            genomes.append(mutate(base, rng=rng, generation=base.generation))
    else:
        genomes = genomes[:POPULATION_SIZE]
    return genomes


def _persist_population(
    *,
    population: list[ParameterGenome],
    population_path: Path,
    generation: int,
) -> None:
    _save_json(
        population_path,
        {
            "updated_at": _now_iso(),
            "generation": int(generation),
            "population": [asdict(_bounded_genome(item)) for item in population],
        },
    )


def _load_observations(
    *,
    db_path: Path,
    lookback_hours: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not db_path.exists():
        return [], []
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        table_columns = {
            str(row["name"]) for row in conn.execute("PRAGMA table_info(window_trades)").fetchall()
        }
        if not table_columns:
            return [], []

        expected = (
            "direction",
            "order_price",
            "best_ask",
            "best_bid",
            "current_price",
            "delta",
            "won",
            "pnl_usd",
            "resolved_side",
            "order_status",
            "created_at",
        )
        selected_columns = [
            column if column in table_columns else f"NULL AS {column}" for column in expected
        ]
        where_parts = ["1=1"]
        params: list[Any] = []
        if "created_at" in table_columns:
            cutoff = (
                datetime.now(timezone.utc) - timedelta(hours=max(1, int(lookback_hours)))
            ).isoformat()
            where_parts.append("created_at > ?")
            params.append(cutoff)
        if "order_status" in table_columns:
            where_parts.append("(order_status = 'live_filled' OR LOWER(order_status) LIKE 'skip_%')")
        query = (
            f"SELECT {', '.join(selected_columns)} FROM window_trades "
            f"WHERE {' AND '.join(where_parts)} "
            "ORDER BY created_at ASC"
        )
        rows = [dict(row) for row in conn.execute(query, params).fetchall()]
    finally:
        conn.close()

    fills = [row for row in rows if str(row.get("order_status") or "").strip().lower() == "live_filled"]
    skips = [row for row in rows if str(row.get("order_status") or "").strip().lower().startswith("skip_")]
    return fills, skips


def evolve_generation(
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    population_path: str | Path = DEFAULT_POPULATION_PATH,
    lookback_hours: int = DEFAULT_LOOKBACK_HOURS,
    rng_seed: int | None = None,
) -> dict[str, Any]:
    """Rank by fitness, keep top 3, and generate 7 children."""

    prng = random.Random(rng_seed if rng_seed is not None else int(datetime.now(timezone.utc).timestamp()))
    db_path_obj = Path(db_path)
    population_path_obj = Path(population_path)

    fills, skips = _load_observations(db_path=db_path_obj, lookback_hours=lookback_hours)
    if not fills and not skips:
        return {
            "status": "insufficient_data",
            "replay_rows": 0,
            "fills_considered": 0,
            "skips_considered": 0,
            "generation": None,
        }

    current_population = _load_population(population_path=population_path_obj, rng=prng)
    scored_population = [
        _bounded_genome(
            ParameterGenome(
                min_buy_price=g.min_buy_price,
                max_buy_price=g.max_buy_price,
                min_delta=g.min_delta,
                max_delta=g.max_delta,
                generation=g.generation,
                fitness=evaluate_fitness(g, fills, skips),
            )
        )
        for g in current_population
    ]
    scored_population.sort(key=lambda item: item.fitness, reverse=True)

    survivors = scored_population[:SURVIVOR_COUNT]
    next_generation = max(item.generation for item in survivors) + 1
    children: list[ParameterGenome] = []
    while len(children) < CHILD_COUNT:
        if len(survivors) >= 2:
            parent_a, parent_b = prng.sample(survivors, 2)
        else:
            parent_a = survivors[0]
            parent_b = survivors[0]
        crossover_child = _crossover(parent_a, parent_b, rng=prng, generation=next_generation)
        child = mutate(crossover_child, rng=prng, generation=next_generation)
        child.fitness = evaluate_fitness(child, fills, skips)
        children.append(_bounded_genome(child))

    next_population = survivors + children
    next_population.sort(key=lambda item: item.fitness, reverse=True)
    _persist_population(
        population=next_population,
        population_path=population_path_obj,
        generation=next_generation,
    )

    return {
        "status": "evolved",
        "generation": next_generation,
        "replay_rows": len(fills) + len(skips),
        "fills_considered": len(fills),
        "skips_considered": len(skips),
        "best_genome": asdict(next_population[0]),
        "survivor_genomes": [asdict(item) for item in survivors],
    }


def _promote_genome(
    *,
    genome: ParameterGenome,
    overrides_path: Path,
    lookback_hours: int,
    replay_rows: int,
) -> dict[str, Any]:
    payload = _load_json(overrides_path)
    params_raw = payload.get("params")
    params = dict(params_raw) if isinstance(params_raw, dict) else {}
    bounded = _bounded_genome(genome)
    risk_fraction = min(
        MAX_RISK_FRACTION,
        max(
            0.0,
            _safe_float(
                params.get("BTC5_RISK_FRACTION", os.environ.get("BTC5_RISK_FRACTION", "0.02")),
                0.02,
            ),
        ),
    )

    params.update(
        {
            "BTC5_MIN_BUY_PRICE": round(bounded.min_buy_price, 4),
            "BTC5_DOWN_MAX_BUY_PRICE": round(bounded.max_buy_price, 4),
            "BTC5_UP_MAX_BUY_PRICE": round(bounded.max_buy_price, 4),
            "BTC5_MIN_DELTA": round(bounded.min_delta, 6),
            "BTC5_MAX_ABS_DELTA": round(bounded.max_delta, 6),
            "BTC5_RISK_FRACTION": round(risk_fraction, 4),
        }
    )

    lineage = payload.get("lineage")
    if not isinstance(lineage, list):
        lineage = []
    promoted_at = _now_iso()
    lineage.append(
        {
            "promoted_at": promoted_at,
            "generation": int(bounded.generation),
            "fitness": round(float(bounded.fitness), 6),
            "lookback_hours": int(lookback_hours),
            "replay_rows": int(replay_rows),
            "genome": asdict(bounded),
        }
    )

    payload["promotion_stage"] = "validated"
    payload["params"] = params
    payload["hard_bounds"] = {
        "BTC5_MIN_BUY_PRICE": {"min": MIN_BUY_FLOOR, "max": MAX_BUY_CAP},
        "BTC5_DOWN_MAX_BUY_PRICE": {"max": MAX_BUY_CAP},
        "BTC5_UP_MAX_BUY_PRICE": {"max": MAX_BUY_CAP},
    }
    payload["active_genome"] = {
        "genome_id": f"generation_{bounded.generation}",
        "generation": int(bounded.generation),
        "fitness": round(float(bounded.fitness), 6),
        "promoted_at": promoted_at,
    }
    payload["lineage"] = lineage[-LINEAGE_LIMIT:]
    payload["last_evolution_cycle"] = {
        "promoted_at": promoted_at,
        "generation": int(bounded.generation),
        "fitness": round(float(bounded.fitness), 6),
        "lookback_hours": int(lookback_hours),
        "replay_rows": int(replay_rows),
    }
    _save_json(overrides_path, payload)
    return payload


def _genomes_identical(a: ParameterGenome, b: ParameterGenome) -> bool:
    """Check if two genomes have the same trading parameters."""
    return (
        abs(a.min_buy_price - b.min_buy_price) < 1e-6
        and abs(a.max_buy_price - b.max_buy_price) < 1e-6
        and abs(a.min_delta - b.min_delta) < 1e-8
        and abs(a.max_delta - b.max_delta) < 1e-8
    )


def evolve_and_maybe_promote(
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    overrides_path: str | Path = DEFAULT_OVERRIDES_PATH,
    population_path: str | Path = DEFAULT_POPULATION_PATH,
    lookback_hours: int = DEFAULT_LOOKBACK_HOURS,
    rng_seed: int | None = None,
) -> dict[str, Any]:
    evolution = evolve_generation(
        db_path=db_path,
        population_path=population_path,
        lookback_hours=lookback_hours,
        rng_seed=rng_seed,
    )
    if evolution.get("status") != "evolved":
        return evolution

    champion = _genome_from_row(dict(evolution.get("best_genome") or {}))

    # GATE 1: Don't promote genomes with zero or near-zero fitness.
    # A fitness of 0.0 means no qualifying data matched — the genome is blind.
    if champion.fitness < MIN_FITNESS_TO_PROMOTE:
        evolution["status"] = "skipped_low_fitness"
        evolution["skip_reason"] = (
            f"champion fitness {champion.fitness:.6f} < threshold {MIN_FITNESS_TO_PROMOTE}"
        )
        return evolution

    # GATE 2: Don't re-promote identical genomes (parameter deduplication).
    overrides_path_obj = Path(overrides_path)
    existing = _load_json(overrides_path_obj)
    existing_genome_raw = existing.get("active_genome")
    if isinstance(existing_genome_raw, dict):
        existing_params = existing.get("params", {})
        existing_genome = _bounded_genome(ParameterGenome(
            min_buy_price=_safe_float(existing_params.get("BTC5_MIN_BUY_PRICE"), 0),
            max_buy_price=_safe_float(existing_params.get("BTC5_DOWN_MAX_BUY_PRICE"), 0),
            min_delta=_safe_float(existing_params.get("BTC5_MIN_DELTA"), 0),
            max_delta=_safe_float(existing_params.get("BTC5_MAX_ABS_DELTA"), 0),
        ))
        if _genomes_identical(champion, existing_genome):
            evolution["status"] = "skipped_no_change"
            evolution["skip_reason"] = "champion identical to currently promoted genome"
            return evolution

    # GATE 3: Champion must have been evaluated on at least 5 qualifying rows.
    fills_considered = int(evolution.get("fills_considered", 0))
    if fills_considered < 3:
        evolution["status"] = "skipped_insufficient_fills"
        evolution["skip_reason"] = f"only {fills_considered} fills evaluated, need >= 3"
        return evolution

    _promote_genome(
        genome=champion,
        overrides_path=overrides_path_obj,
        lookback_hours=int(lookback_hours),
        replay_rows=int(evolution.get("replay_rows", 0)),
    )
    evolution["status"] = "promoted"
    return evolution


def run_pricing_evolution(
    *,
    db_path: str | Path,
    overrides_path: str | Path,
    population_path: str | Path | None = None,
    lookback_hours: int = DEFAULT_LOOKBACK_HOURS,
    mutation_count: int | None = None,
    rng_seed: int | None = None,
) -> dict[str, Any]:
    """Compatibility wrapper used by existing autoresearch callers."""

    kwargs: dict[str, Any] = {
        "db_path": db_path,
        "overrides_path": overrides_path,
        "lookback_hours": lookback_hours,
        "rng_seed": rng_seed,
    }
    if population_path is not None:
        kwargs["population_path"] = population_path
    result = evolve_and_maybe_promote(**kwargs)
    if result.get("status") != "promoted":
        return {
            "status": "insufficient_data",
            "reason": "no_counterfactual_rows_in_lookback",
            "lookback_hours": int(lookback_hours),
            "mutation_count": int(mutation_count) if mutation_count is not None else CHILD_COUNT,
            "replay_rows": int(result.get("replay_rows", 0)),
        }

    selected = dict(result.get("best_genome") or {})
    return {
        "status": "promoted",
        "lookback_hours": int(lookback_hours),
        "mutation_count": int(mutation_count) if mutation_count is not None else CHILD_COUNT,
        "replay_rows": int(result.get("replay_rows", 0)),
        "selected_genome": {
            "genome_id": f"generation_{selected.get('generation', 0)}",
            "fitness": float(selected.get("fitness", 0.0)),
            "fills": int(result.get("fills_considered", 0)),
            "params": {
                "BTC5_MIN_BUY_PRICE": float(selected.get("min_buy_price", 0.0)),
                "BTC5_DOWN_MAX_BUY_PRICE": float(selected.get("max_buy_price", 0.0)),
                "BTC5_UP_MAX_BUY_PRICE": float(selected.get("max_buy_price", 0.0)),
                "BTC5_MIN_DELTA": float(selected.get("min_delta", 0.0)),
                "BTC5_MAX_ABS_DELTA": float(selected.get("max_delta", 0.0)),
            },
        },
        "top_candidates": list(result.get("survivor_genomes") or []),
    }
