"""Evolutionary parameter search for BTC5 autoresearch cycles.

Each cycle:
1) Loads the current active genome (or builds a genesis baseline from env).
2) Generates bounded parameter mutations (5-10 by default).
3) Scores each genome on a 24h counterfactual replay of live fills.
4) Promotes the best genome to config/autoresearch_overrides.json.
5) Appends lineage metadata for auditability.
"""

from __future__ import annotations

import json
import os
import random
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

MIN_BUY_FLOOR = 0.85
MAX_BUY_CAP = 0.98
MAX_RISK_FRACTION = 0.33

DEFAULT_MUTATION_COUNT_MIN = 5
DEFAULT_MUTATION_COUNT_MAX = 10
DEFAULT_LOOKBACK_HOURS = 24
LINEAGE_LIMIT = 200


@dataclass(frozen=True)
class GenomeScore:
    genome_id: str
    parent_genome_id: str
    params: dict[str, float]
    pnl_usd: float
    fills: int
    win_rate: float
    score: float
    mutation_notes: list[str]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _round_price(value: float) -> float:
    return round(float(value), 2)


def _round_delta(value: float) -> float:
    return round(float(value), 6)


def _round_risk(value: float) -> float:
    return round(float(value), 4)


def _enforce_bounds(raw_params: dict[str, Any]) -> dict[str, float]:
    min_buy = _round_price(max(MIN_BUY_FLOOR, _safe_float(raw_params.get("BTC5_MIN_BUY_PRICE"), 0.90)))
    down_cap = _round_price(min(MAX_BUY_CAP, _safe_float(raw_params.get("BTC5_DOWN_MAX_BUY_PRICE"), 0.95)))
    up_cap = _round_price(min(MAX_BUY_CAP, _safe_float(raw_params.get("BTC5_UP_MAX_BUY_PRICE"), down_cap)))
    max_abs_delta = _round_delta(max(0.0001, _safe_float(raw_params.get("BTC5_MAX_ABS_DELTA"), 0.005)))
    risk_fraction = _round_risk(min(MAX_RISK_FRACTION, max(0.0, _safe_float(raw_params.get("BTC5_RISK_FRACTION"), 0.02))))

    if down_cap < min_buy:
        down_cap = min_buy
    if up_cap < min_buy:
        up_cap = min_buy

    return {
        "BTC5_MIN_BUY_PRICE": min_buy,
        "BTC5_DOWN_MAX_BUY_PRICE": down_cap,
        "BTC5_UP_MAX_BUY_PRICE": up_cap,
        "BTC5_MAX_ABS_DELTA": max_abs_delta,
        "BTC5_RISK_FRACTION": risk_fraction,
    }


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _load_current_genome(overrides_path: Path) -> tuple[str, dict[str, float], dict[str, Any]]:
    payload = _load_json(overrides_path)
    params_raw = payload.get("params", {})
    active = payload.get("active_genome", {})
    genome_id = str(active.get("genome_id") or "genesis")

    if not isinstance(params_raw, dict):
        params_raw = {}
    baseline_from_env = {
        "BTC5_MIN_BUY_PRICE": os.environ.get("BTC5_MIN_BUY_PRICE", "0.90"),
        "BTC5_DOWN_MAX_BUY_PRICE": os.environ.get("BTC5_DOWN_MAX_BUY_PRICE", "0.95"),
        "BTC5_UP_MAX_BUY_PRICE": os.environ.get("BTC5_UP_MAX_BUY_PRICE", os.environ.get("BTC5_DOWN_MAX_BUY_PRICE", "0.95")),
        "BTC5_MAX_ABS_DELTA": os.environ.get("BTC5_MAX_ABS_DELTA", "0.005"),
        "BTC5_RISK_FRACTION": os.environ.get("BTC5_RISK_FRACTION", "0.02"),
    }
    merged_params = dict(baseline_from_env)
    merged_params.update(params_raw)
    return genome_id, _enforce_bounds(merged_params), payload


def _load_replay_rows(*, db_path: Path, lookback_hours: int) -> list[sqlite3.Row]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max(1, int(lookback_hours)))).isoformat()
    rows = conn.execute(
        """
        SELECT direction, order_price, pnl_usd, won, delta, created_at
        FROM window_trades
        WHERE order_status = 'live_filled'
          AND created_at > ?
        ORDER BY created_at ASC
        """,
        (cutoff,),
    ).fetchall()
    conn.close()
    return rows


def _score_genome(*, genome_id: str, parent_genome_id: str, params: dict[str, float], rows: list[sqlite3.Row], mutation_notes: list[str]) -> GenomeScore:
    pnl = 0.0
    fills = 0
    wins = 0
    min_buy = float(params["BTC5_MIN_BUY_PRICE"])
    down_cap = float(params["BTC5_DOWN_MAX_BUY_PRICE"])
    up_cap = float(params["BTC5_UP_MAX_BUY_PRICE"])
    max_abs_delta = float(params["BTC5_MAX_ABS_DELTA"])

    for row in rows:
        side = str(row["direction"] or "").strip().upper()
        price = _safe_float(row["order_price"], 0.0)
        delta = abs(_safe_float(row["delta"], 0.0))
        trade_pnl = _safe_float(row["pnl_usd"], 0.0)
        won = int(_safe_float(row["won"], 0.0))

        if price < min_buy:
            continue
        if side == "DOWN" and price > down_cap:
            continue
        if side == "UP" and price > up_cap:
            continue
        if delta > max_abs_delta:
            continue

        fills += 1
        pnl += trade_pnl
        if won == 1:
            wins += 1

    win_rate = (wins / fills) if fills else 0.0
    # Prioritize realized replay PnL; tiny tie-breakers favor healthier samples.
    score = round(pnl + (win_rate * 0.05) + (fills * 0.001), 6)
    return GenomeScore(
        genome_id=genome_id,
        parent_genome_id=parent_genome_id,
        params=params,
        pnl_usd=round(pnl, 4),
        fills=fills,
        win_rate=round(win_rate, 6),
        score=score,
        mutation_notes=mutation_notes,
    )


def _mutate(parent_params: dict[str, float], *, rng: random.Random, child_idx: int) -> tuple[dict[str, float], list[str]]:
    params = dict(parent_params)
    notes: list[str] = []

    floor_shift = rng.choice([-0.02, -0.01, 0.0, 0.01, 0.02])
    cap_shift = rng.choice([-0.02, -0.01, 0.0, 0.01, 0.02])
    delta_shift = rng.choice([-0.001, -0.0005, 0.0, 0.0005, 0.001, 0.0015])
    risk_shift = rng.choice([-0.02, -0.01, 0.0, 0.01, 0.02])

    params["BTC5_MIN_BUY_PRICE"] = _safe_float(params["BTC5_MIN_BUY_PRICE"], 0.90) + floor_shift
    if floor_shift != 0.0:
        notes.append(f"min_buy_shift={floor_shift:+.3f}")

    params["BTC5_DOWN_MAX_BUY_PRICE"] = _safe_float(params["BTC5_DOWN_MAX_BUY_PRICE"], 0.95) + cap_shift
    if cap_shift != 0.0:
        notes.append(f"down_cap_shift={cap_shift:+.3f}")

    # Keep UP cap close but not necessarily identical to DOWN cap.
    params["BTC5_UP_MAX_BUY_PRICE"] = _safe_float(params["BTC5_UP_MAX_BUY_PRICE"], 0.95) + cap_shift + rng.choice([-0.01, 0.0, 0.01])
    if cap_shift != 0.0:
        notes.append("up_cap_coupled_to_down_cap=true")

    params["BTC5_MAX_ABS_DELTA"] = _safe_float(params["BTC5_MAX_ABS_DELTA"], 0.005) + delta_shift
    if delta_shift != 0.0:
        notes.append(f"max_abs_delta_shift={delta_shift:+.6f}")

    # Allow risk_fraction exploration with a strict hard ceiling.
    params["BTC5_RISK_FRACTION"] = _safe_float(params["BTC5_RISK_FRACTION"], 0.02) + risk_shift
    if risk_shift != 0.0:
        notes.append(f"risk_fraction_shift={risk_shift:+.3f}")

    bounded = _enforce_bounds(params)
    if not notes:
        notes.append(f"child_{child_idx}_identity_mutation")
    return bounded, notes


def _choose_best(scored: list[GenomeScore]) -> GenomeScore:
    return max(scored, key=lambda item: (item.score, item.pnl_usd, item.win_rate, item.fills))


def _persist_promotion(*, overrides_path: Path, prior_payload: dict[str, Any], promoted: GenomeScore, mutation_count: int, replay_rows: int, lookback_hours: int, cycle_started_at: str) -> None:
    payload = dict(prior_payload)
    lineage = payload.get("lineage", [])
    if not isinstance(lineage, list):
        lineage = []

    lineage_entry = {
        "promoted_at": _now_iso(),
        "genome_id": promoted.genome_id,
        "parent_genome_id": promoted.parent_genome_id,
        "score": promoted.score,
        "pnl_usd": promoted.pnl_usd,
        "fills": promoted.fills,
        "win_rate": promoted.win_rate,
        "mutation_notes": promoted.mutation_notes,
        "cycle_started_at": cycle_started_at,
        "lookback_hours": int(lookback_hours),
        "mutation_count": int(mutation_count),
        "replay_rows": int(replay_rows),
    }
    lineage.append(lineage_entry)

    payload["promotion_stage"] = "validated"
    payload["params"] = promoted.params
    payload["active_genome"] = {
        "genome_id": promoted.genome_id,
        "parent_genome_id": promoted.parent_genome_id,
        "score": promoted.score,
        "pnl_usd": promoted.pnl_usd,
        "fills": promoted.fills,
        "win_rate": promoted.win_rate,
        "promoted_at": lineage_entry["promoted_at"],
    }
    payload["lineage"] = lineage[-LINEAGE_LIMIT:]
    payload["last_evolution_cycle"] = {
        "cycle_started_at": cycle_started_at,
        "lookback_hours": int(lookback_hours),
        "mutation_count": int(mutation_count),
        "replay_rows": int(replay_rows),
        "selected_genome_id": promoted.genome_id,
    }

    overrides_path.parent.mkdir(parents=True, exist_ok=True)
    overrides_path.write_text(json.dumps(payload, indent=2))


def run_pricing_evolution(
    *,
    db_path: str | Path,
    overrides_path: str | Path,
    lookback_hours: int = DEFAULT_LOOKBACK_HOURS,
    mutation_count: int | None = None,
    rng_seed: int | None = None,
) -> dict[str, Any]:
    """Run one bounded evolution cycle and promote the best genome."""

    db_path_obj = Path(db_path)
    overrides_path_obj = Path(overrides_path)
    if rng_seed is None:
        rng_seed = int(datetime.now(timezone.utc).timestamp())
    rng = random.Random(rng_seed)
    cycle_started_at = _now_iso()

    parent_genome_id, parent_params, payload = _load_current_genome(overrides_path_obj)
    if mutation_count is None:
        mutation_count = rng.randint(DEFAULT_MUTATION_COUNT_MIN, DEFAULT_MUTATION_COUNT_MAX)
    mutation_count = max(DEFAULT_MUTATION_COUNT_MIN, min(DEFAULT_MUTATION_COUNT_MAX, int(mutation_count)))

    rows = _load_replay_rows(db_path=db_path_obj, lookback_hours=lookback_hours)
    if not rows:
        return {
            "status": "insufficient_data",
            "reason": "no_live_filled_rows_in_lookback",
            "lookback_hours": int(lookback_hours),
            "mutation_count": int(mutation_count),
            "replay_rows": 0,
        }

    scored: list[GenomeScore] = [
        _score_genome(
            genome_id=parent_genome_id,
            parent_genome_id=parent_genome_id,
            params=parent_params,
            rows=rows,
            mutation_notes=["baseline_parent_genome"],
        )
    ]

    for idx in range(mutation_count):
        child_params, notes = _mutate(parent_params, rng=rng, child_idx=idx + 1)
        child_id = f"g_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{idx + 1}"
        scored.append(
            _score_genome(
                genome_id=child_id,
                parent_genome_id=parent_genome_id,
                params=child_params,
                rows=rows,
                mutation_notes=notes,
            )
        )

    winner = _choose_best(scored)
    _persist_promotion(
        overrides_path=overrides_path_obj,
        prior_payload=payload,
        promoted=winner,
        mutation_count=mutation_count,
        replay_rows=len(rows),
        lookback_hours=lookback_hours,
        cycle_started_at=cycle_started_at,
    )

    top_candidates = sorted(scored, key=lambda item: (item.score, item.pnl_usd, item.fills), reverse=True)[:3]
    return {
        "status": "promoted",
        "lookback_hours": int(lookback_hours),
        "mutation_count": int(mutation_count),
        "replay_rows": len(rows),
        "seed": int(rng_seed),
        "parent_genome_id": parent_genome_id,
        "selected_genome": {
            "genome_id": winner.genome_id,
            "parent_genome_id": winner.parent_genome_id,
            "score": winner.score,
            "pnl_usd": winner.pnl_usd,
            "fills": winner.fills,
            "win_rate": winner.win_rate,
            "params": winner.params,
            "mutation_notes": winner.mutation_notes,
        },
        "top_candidates": [
            {
                "genome_id": g.genome_id,
                "score": g.score,
                "pnl_usd": g.pnl_usd,
                "fills": g.fills,
                "win_rate": g.win_rate,
            }
            for g in top_candidates
        ],
    }
