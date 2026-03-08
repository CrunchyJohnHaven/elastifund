#!/usr/bin/env python3
"""Adaptive Platt calibration for live trading and walk-forward validation."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import time
from typing import Any, Iterable, Sequence

try:
    from sklearn.linear_model import LogisticRegression
except ImportError:  # pragma: no cover - exercised only in misconfigured envs
    LogisticRegression = None


def _float_env(name: str, default: str) -> float:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return float(default)
    try:
        return float(raw)
    except ValueError:
        return float(default)


STATIC_PLATT_A = _float_env("PLATT_A", "0.5914")
STATIC_PLATT_B = _float_env("PLATT_B", "-0.3977")

DEFAULT_MIN_OBSERVATIONS = 30
DEFAULT_RUNTIME_WINDOW = 100
DEFAULT_REPORT_WINDOWS = (100, 200)
DEFAULT_ECE_BINS = 10
DEFAULT_DB_PATH = Path("data/jj_trades.db")
DEFAULT_STATE_PATH = Path("data/adaptive_platt_state.json")
DEFAULT_REPORT_PATH = Path("reports/platt_comparison.md")
DEFAULT_REPORT_JSON_PATH = Path("reports/platt_comparison.json")

STATE_TABLE = "adaptive_platt_state"
OBSERVATIONS_TABLE = "adaptive_platt_observations"
RUNTIME_VARIANTS = {"static", "expanding", "rolling_100", "rolling_200"}


@dataclass(frozen=True)
class ResolvedExample:
    market_id: str
    question: str
    resolved_at: str
    raw_prob: float
    outcome: int
    source: str


@dataclass(frozen=True)
class VariantMetrics:
    name: str
    window: int | None
    n_predictions: int
    brier: float
    calibration_error: float
    log_loss: float
    final_a: float
    final_b: float
    fallback_predictions: int = 0


def question_cache_key(question: str) -> str:
    return hashlib.sha256(question.encode()).hexdigest()[:16]


def clamp_probability(probability: float) -> float:
    return max(0.001, min(0.999, float(probability)))


def calibrate_probability_with_params(raw_prob: float, a: float, b: float) -> float:
    raw_prob = clamp_probability(raw_prob)
    if abs(raw_prob - 0.5) < 1e-9:
        return 0.5
    if raw_prob < 0.5:
        return 1.0 - calibrate_probability_with_params(1.0 - raw_prob, a, b)
    logit_input = math.log(raw_prob / (1.0 - raw_prob))
    logit_output = max(-30.0, min(30.0, a * logit_input + b))
    calibrated = 1.0 / (1.0 + math.exp(-logit_output))
    return max(0.01, min(0.99, calibrated))


def _normalize_resolved_rows(
    resolved: Iterable[ResolvedExample | tuple[float, int]],
) -> list[tuple[float, int]]:
    rows: list[tuple[float, int]] = []
    for row in resolved:
        if isinstance(row, ResolvedExample):
            rows.append((float(row.raw_prob), int(row.outcome)))
            continue

        if not isinstance(row, tuple) or len(row) < 2:
            raise TypeError("resolved rows must be ResolvedExample or (raw_prob, outcome) tuples")
        rows.append((float(row[0]), int(row[1])))
    return rows


def fit_platt_parameters(
    raw_probs: Sequence[float],
    outcomes: Sequence[int],
    *,
    initial_a: float = STATIC_PLATT_A,
    initial_b: float = STATIC_PLATT_B,
    min_samples: int = DEFAULT_MIN_OBSERVATIONS,
    learning_rate: float | None = None,
    l2: float | None = None,
    max_iter: int = 1000,
    c_value: float = 1_000.0,
) -> tuple[float, float]:
    """Fit Platt A/B on logit(raw_prob) using sklearn LogisticRegression."""
    if len(raw_probs) != len(outcomes) or len(raw_probs) < int(min_samples):
        return float(initial_a), float(initial_b)

    labels = [int(value) for value in outcomes]
    if len(set(labels)) < 2:
        return float(initial_a), float(initial_b)

    if LogisticRegression is None:
        raise RuntimeError(
            "scikit-learn is required for adaptive Platt refits; install requirements.txt"
        )

    features = [
        [math.log(clamp_probability(prob) / (1.0 - clamp_probability(prob)))]
        for prob in raw_probs
    ]
    model = LogisticRegression(
        C=float(c_value),
        solver="lbfgs",
        fit_intercept=True,
        max_iter=int(max_iter),
    )
    model.fit(features, labels)
    return float(model.coef_[0][0]), float(model.intercept_[0])


def rolling_platt_fit(
    resolved: Iterable[ResolvedExample | tuple[float, int]],
    window: int = DEFAULT_RUNTIME_WINDOW,
    *,
    initial_a: float = STATIC_PLATT_A,
    initial_b: float = STATIC_PLATT_B,
    min_samples: int = DEFAULT_MIN_OBSERVATIONS,
    learning_rate: float | None = None,
    l2: float | None = None,
    max_iter: int = 1000,
    c_value: float = 1_000.0,
) -> tuple[float, float]:
    """Fit Platt parameters on the most recent ``window`` resolved markets."""
    rows = _normalize_resolved_rows(resolved)
    sample = rows[-max(1, int(window)) :]
    if len(sample) < int(min_samples):
        return float(initial_a), float(initial_b)
    raw_probs = [row[0] for row in sample]
    outcomes = [row[1] for row in sample]
    return fit_platt_parameters(
        raw_probs,
        outcomes,
        initial_a=initial_a,
        initial_b=initial_b,
        min_samples=min_samples,
        learning_rate=learning_rate,
        l2=l2,
        max_iter=max_iter,
        c_value=c_value,
    )


def expanding_platt_fit(
    resolved: Iterable[ResolvedExample | tuple[float, int]],
    *,
    initial_a: float = STATIC_PLATT_A,
    initial_b: float = STATIC_PLATT_B,
    min_samples: int = DEFAULT_MIN_OBSERVATIONS,
    max_iter: int = 1000,
    c_value: float = 1_000.0,
) -> tuple[float, float]:
    rows = _normalize_resolved_rows(resolved)
    if len(rows) < int(min_samples):
        return float(initial_a), float(initial_b)
    raw_probs = [row[0] for row in rows]
    outcomes = [row[1] for row in rows]
    return fit_platt_parameters(
        raw_probs,
        outcomes,
        initial_a=initial_a,
        initial_b=initial_b,
        min_samples=min_samples,
        max_iter=max_iter,
        c_value=c_value,
    )


def brier_score(predictions: Sequence[float], outcomes: Sequence[int]) -> float:
    if not predictions or len(predictions) != len(outcomes):
        raise ValueError("predictions/outcomes must be non-empty and aligned")
    return sum((float(pred) - float(outcome)) ** 2 for pred, outcome in zip(predictions, outcomes)) / len(predictions)


def expected_calibration_error(
    predictions: Sequence[float],
    outcomes: Sequence[int],
    *,
    bins: int = DEFAULT_ECE_BINS,
) -> float:
    if not predictions or len(predictions) != len(outcomes):
        raise ValueError("predictions/outcomes must be non-empty and aligned")

    total = 0.0
    n_predictions = len(predictions)
    for idx in range(int(bins)):
        lower = idx / bins
        upper = (idx + 1) / bins
        members = [
            pos
            for pos, pred in enumerate(predictions)
            if (lower <= pred < upper) or (idx == bins - 1 and lower <= pred <= upper)
        ]
        if not members:
            continue

        mean_confidence = sum(predictions[pos] for pos in members) / len(members)
        mean_accuracy = sum(outcomes[pos] for pos in members) / len(members)
        total += abs(mean_confidence - mean_accuracy) * (len(members) / n_predictions)

    return total


def log_loss_score(predictions: Sequence[float], outcomes: Sequence[int]) -> float:
    if not predictions or len(predictions) != len(outcomes):
        raise ValueError("predictions/outcomes must be non-empty and aligned")

    eps = 1e-9
    return -sum(
        float(outcome) * math.log(max(eps, min(1.0 - eps, float(pred))))
        + (1.0 - float(outcome)) * math.log(max(eps, min(1.0 - eps, 1.0 - float(pred))))
        for pred, outcome in zip(predictions, outcomes)
    ) / len(predictions)


def _sqlite_tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {str(row[0]) for row in rows}


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row[1]) for row in rows}


def _load_trade_db_examples(db_path: Path) -> list[ResolvedExample]:
    conn = sqlite3.connect(str(db_path))
    try:
        tables = _sqlite_tables(conn)
        if "trades" not in tables:
            return []

        columns = _table_columns(conn, "trades")
        needed = {"market_id", "question", "raw_prob", "resolution_price"}
        if not needed.issubset(columns):
            return []

        resolved_column = "resolved_at" if "resolved_at" in columns else "timestamp"
        rows = conn.execute(
            f"""
            SELECT COALESCE(market_id, ''),
                   COALESCE(question, ''),
                   COALESCE({resolved_column}, ''),
                   raw_prob,
                   resolution_price
            FROM trades
            WHERE raw_prob IS NOT NULL
              AND resolution_price IS NOT NULL
              AND outcome IS NOT NULL
            ORDER BY COALESCE({resolved_column}, ''), market_id
            """
        ).fetchall()

        return [
            ResolvedExample(
                market_id=str(row[0]),
                question=str(row[1]),
                resolved_at=str(row[2]),
                raw_prob=float(row[3]),
                outcome=1 if float(row[4]) >= 0.5 else 0,
                source=str(db_path),
            )
            for row in rows
        ]
    finally:
        conn.close()


def _load_brier_db_examples(db_path: Path) -> list[ResolvedExample]:
    conn = sqlite3.connect(str(db_path))
    try:
        tables = _sqlite_tables(conn)
        if not {"estimates", "resolutions"}.issubset(tables):
            return []

        estimate_columns = _table_columns(conn, "estimates")
        resolution_columns = _table_columns(conn, "resolutions")
        needed_estimate = {"market_id", "question", "timestamp", "model_name", "raw_probability"}
        needed_resolution = {"market_id", "outcome", "resolved_at"}
        if not needed_estimate.issubset(estimate_columns) or not needed_resolution.issubset(resolution_columns):
            return []

        rows = conn.execute(
            """
            WITH latest_ensemble AS (
                SELECT market_id, MAX(timestamp) AS latest_ts
                FROM estimates
                WHERE model_name = 'ensemble'
                  AND raw_probability IS NOT NULL
                GROUP BY market_id
            )
            SELECT e.market_id,
                   COALESCE(e.question, ''),
                   r.resolved_at,
                   e.raw_probability,
                   r.outcome
            FROM estimates e
            JOIN latest_ensemble le
              ON le.market_id = e.market_id
             AND le.latest_ts = e.timestamp
            JOIN resolutions r
              ON r.market_id = e.market_id
            WHERE e.model_name = 'ensemble'
              AND e.raw_probability IS NOT NULL
            ORDER BY r.resolved_at, e.market_id
            """
        ).fetchall()

        return [
            ResolvedExample(
                market_id=str(row[0]),
                question=str(row[1]),
                resolved_at=str(row[2]),
                raw_prob=float(row[3]),
                outcome=int(row[4]),
                source=str(db_path),
            )
            for row in rows
        ]
    finally:
        conn.close()


def load_resolved_examples_from_cache(
    markets_path: str | Path,
    cache_path: str | Path,
) -> list[ResolvedExample]:
    markets_payload = json.loads(Path(markets_path).read_text(encoding="utf-8"))
    cache_payload = json.loads(Path(cache_path).read_text(encoding="utf-8"))

    loaded: list[ResolvedExample] = []
    markets = markets_payload.get("markets", []) if isinstance(markets_payload, dict) else markets_payload
    for market in markets:
        question = str(market.get("question", "")).strip()
        if not question:
            continue

        cache_entry = cache_payload.get(question_cache_key(question))
        if not cache_entry:
            continue

        outcome_raw = str(market.get("actual_outcome", "")).upper()
        if outcome_raw not in {"YES_WON", "NO_WON"}:
            continue

        probability = cache_entry.get("probability")
        if probability is None:
            continue

        loaded.append(
            ResolvedExample(
                market_id=str(market.get("id", "")),
                question=question,
                resolved_at=str(market.get("end_date", "")),
                raw_prob=float(probability),
                outcome=1 if outcome_raw == "YES_WON" else 0,
                source=str(cache_path),
            )
        )

    loaded.sort(key=lambda row: (row.resolved_at, row.market_id))
    return loaded


def load_resolved_history(
    *,
    db_paths: Sequence[str | Path] = (
        "data/jj_trades.db",
        "data/brier_tracking.db",
        "data/edge_discovery.db",
        "data/quant.db",
    ),
    markets_path: str | Path = "backtest/data/historical_markets_532.json",
    cache_paths: Sequence[str | Path] = (
        "backtest/data/ensemble_cache.json",
        "backtest/data/claude_cache.json",
    ),
) -> tuple[list[ResolvedExample], dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    for raw_path in db_paths:
        db_path = Path(raw_path)
        if not db_path.exists():
            checks.append({"path": str(db_path), "type": "sqlite", "rows": 0, "status": "missing"})
            continue

        rows = _load_trade_db_examples(db_path)
        if not rows:
            rows = _load_brier_db_examples(db_path)

        checks.append(
            {
                "path": str(db_path),
                "type": "sqlite",
                "rows": len(rows),
                "status": "loaded" if rows else "no_resolved_pairs",
            }
        )
        if rows:
            return rows, {"source": str(db_path), "checks": checks}

    best_rows: list[ResolvedExample] = []
    best_path = ""
    for raw_path in cache_paths:
        cache_path = Path(raw_path)
        if not cache_path.exists():
            checks.append({"path": str(cache_path), "type": "cache", "rows": 0, "status": "missing"})
            continue

        rows = load_resolved_examples_from_cache(markets_path, cache_path)
        checks.append(
            {
                "path": str(cache_path),
                "type": "cache",
                "rows": len(rows),
                "status": "loaded" if rows else "no_matches",
            }
        )
        if len(rows) > len(best_rows):
            best_rows = rows
            best_path = str(cache_path)

    if best_rows:
        return best_rows, {"source": best_path, "checks": checks}

    raise FileNotFoundError("Unable to locate resolved (raw_prob, outcome) pairs in SQLite or cache artifacts")


def _fit_history(
    history: Sequence[ResolvedExample],
    *,
    variant_name: str,
    static_a: float,
    static_b: float,
    min_samples: int,
    max_iter: int,
    c_value: float,
) -> tuple[float, float, bool]:
    if variant_name == "static":
        return float(static_a), float(static_b), False

    if variant_name == "expanding":
        params = expanding_platt_fit(
            history,
            initial_a=static_a,
            initial_b=static_b,
            min_samples=min_samples,
            max_iter=max_iter,
            c_value=c_value,
        )
    elif variant_name.startswith("rolling_"):
        params = rolling_platt_fit(
            history,
            window=int(variant_name.split("_", 1)[1]),
            initial_a=static_a,
            initial_b=static_b,
            min_samples=min_samples,
            max_iter=max_iter,
            c_value=c_value,
        )
    else:
        raise ValueError(f"unknown variant: {variant_name}")

    fallback = params == (float(static_a), float(static_b)) and len(history) < int(min_samples)
    return float(params[0]), float(params[1]), fallback


def evaluate_variant(
    resolved_examples: Sequence[ResolvedExample],
    *,
    variant_name: str,
    static_a: float = STATIC_PLATT_A,
    static_b: float = STATIC_PLATT_B,
    min_samples: int = DEFAULT_MIN_OBSERVATIONS,
    max_iter: int = 1000,
    c_value: float = 1_000.0,
) -> VariantMetrics:
    if not resolved_examples:
        raise ValueError("resolved_examples must be non-empty")

    predictions: list[float] = []
    outcomes: list[int] = []
    final_a = float(static_a)
    final_b = float(static_b)
    fallback_predictions = 0

    for idx, current in enumerate(resolved_examples):
        history = resolved_examples[:idx]
        final_a, final_b, fallback = _fit_history(
            history,
            variant_name=variant_name,
            static_a=static_a,
            static_b=static_b,
            min_samples=min_samples,
            max_iter=max_iter,
            c_value=c_value,
        )
        if fallback:
            fallback_predictions += 1

        predictions.append(calibrate_probability_with_params(current.raw_prob, final_a, final_b))
        outcomes.append(int(current.outcome))

    window = None
    if variant_name.startswith("rolling_"):
        window = int(variant_name.split("_", 1)[1])

    return VariantMetrics(
        name=variant_name,
        window=window,
        n_predictions=len(predictions),
        brier=round(brier_score(predictions, outcomes), 6),
        calibration_error=round(expected_calibration_error(predictions, outcomes), 6),
        log_loss=round(log_loss_score(predictions, outcomes), 6),
        final_a=round(final_a, 6),
        final_b=round(final_b, 6),
        fallback_predictions=fallback_predictions,
    )


def walk_forward_compare(
    resolved_examples: Sequence[ResolvedExample],
    *,
    min_samples: int = DEFAULT_MIN_OBSERVATIONS,
    static_a: float = STATIC_PLATT_A,
    static_b: float = STATIC_PLATT_B,
    rolling_windows: Sequence[int] = DEFAULT_REPORT_WINDOWS,
    max_iter: int = 1000,
    c_value: float = 1_000.0,
) -> dict[str, Any]:
    if not resolved_examples:
        raise ValueError("resolved_examples must be non-empty")

    variants = [
        evaluate_variant(
            resolved_examples,
            variant_name="static",
            static_a=static_a,
            static_b=static_b,
            min_samples=min_samples,
            max_iter=max_iter,
            c_value=c_value,
        ),
        evaluate_variant(
            resolved_examples,
            variant_name="expanding",
            static_a=static_a,
            static_b=static_b,
            min_samples=min_samples,
            max_iter=max_iter,
            c_value=c_value,
        ),
    ]
    for window in rolling_windows:
        variants.append(
            evaluate_variant(
                resolved_examples,
                variant_name=f"rolling_{int(window)}",
                static_a=static_a,
                static_b=static_b,
                min_samples=min_samples,
                max_iter=max_iter,
                c_value=c_value,
            )
        )

    ordered = sorted(variants, key=lambda item: item.brier)
    best_variant = ordered[0]
    static_variant = next(item for item in variants if item.name == "static")
    best_rolling_variant = min(
        (item for item in variants if item.name.startswith("rolling_")),
        key=lambda item: item.brier,
    )
    improvement_vs_static = round(static_variant.brier - best_variant.brier, 6)

    return {
        "dataset_size": len(resolved_examples),
        "min_samples": int(min_samples),
        "static_a": float(static_a),
        "static_b": float(static_b),
        "variants": [asdict(variant) for variant in variants],
        "best_variant": asdict(best_variant),
        "best_rolling_variant": asdict(best_rolling_variant),
        "brier_improvement_vs_static": improvement_vs_static,
    }


def build_comparison_report(
    comparison: dict[str, Any],
    history_info: dict[str, Any],
) -> str:
    best_variant = comparison["best_variant"]
    lines = [
        "# Platt Comparison",
        "",
        f"- Dataset size: {comparison['dataset_size']} resolved markets",
        f"- Static baseline: A={comparison['static_a']:.4f}, B={comparison['static_b']:.4f}",
        f"- Minimum refit history: {comparison['min_samples']} resolved trades",
        f"- Winner: `{best_variant['name']}`",
        f"- Brier improvement vs static: {comparison['brier_improvement_vs_static']:+.6f}",
        "",
        "## Data Search",
        "",
        "| Source | Type | Rows | Status |",
        "|---|---|---:|---|",
    ]

    for check in history_info.get("checks", []):
        lines.append(
            f"| {check['path']} | {check['type']} | {check['rows']} | {check['status']} |"
        )

    lines.extend(
        [
            "",
            "## Walk-Forward Results",
            "",
            "| Variant | Window | Predictions | Fallbacks | Brier | Calibration Error | Log-Loss | Final A | Final B |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )

    for variant in comparison["variants"]:
        window_label = "all" if variant["name"] == "expanding" else ("static" if variant["window"] is None else str(variant["window"]))
        lines.append(
            f"| {variant['name']} | {window_label} | {variant['n_predictions']} | "
            f"{variant.get('fallback_predictions', 0)} | {variant['brier']:.6f} | "
            f"{variant['calibration_error']:.6f} | {variant['log_loss']:.6f} | "
            f"{variant['final_a']:.4f} | {variant['final_b']:.4f} |"
        )

    lines.extend(
        [
            "",
            "## Runtime Recommendation",
            "",
            (
                f"Deploy `{best_variant['name']}` in `jj_live.py`. The historical walk-forward run "
                f"shows it with the best Brier score ({best_variant['brier']:.6f}) against static "
                f"({next(item['brier'] for item in comparison['variants'] if item['name'] == 'static'):.6f})."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def write_comparison_report(
    report_path: str | Path = DEFAULT_REPORT_PATH,
    *,
    json_path: str | Path = DEFAULT_REPORT_JSON_PATH,
    db_paths: Sequence[str | Path] = (
        "data/jj_trades.db",
        "data/brier_tracking.db",
        "data/edge_discovery.db",
        "data/quant.db",
    ),
    markets_path: str | Path = "backtest/data/historical_markets_532.json",
    cache_paths: Sequence[str | Path] = (
        "backtest/data/ensemble_cache.json",
        "backtest/data/claude_cache.json",
    ),
    min_samples: int = DEFAULT_MIN_OBSERVATIONS,
    rolling_windows: Sequence[int] = DEFAULT_REPORT_WINDOWS,
) -> dict[str, Any]:
    resolved_examples, history_info = load_resolved_history(
        db_paths=db_paths,
        markets_path=markets_path,
        cache_paths=cache_paths,
    )
    comparison = walk_forward_compare(
        resolved_examples,
        min_samples=min_samples,
        rolling_windows=rolling_windows,
    )
    report_file = Path(report_path)
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(build_comparison_report(comparison, history_info), encoding="utf-8")

    json_file = Path(json_path)
    json_file.parent.mkdir(parents=True, exist_ok=True)
    json_file.write_text(
        json.dumps(
            {
                **comparison,
                "history_info": history_info,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return comparison


class PlattCalibrator:
    """Persist resolved observations and maintain live Platt parameters."""

    def __init__(
        self,
        db: Any = DEFAULT_DB_PATH,
        *,
        enabled: bool = True,
        min_observations: int = DEFAULT_MIN_OBSERVATIONS,
        runtime_variant: str = "auto",
        refit_seconds: int = 300,
        state_path: str | Path = DEFAULT_STATE_PATH,
        report_path: str | Path = DEFAULT_REPORT_PATH,
        report_json_path: str | Path = DEFAULT_REPORT_JSON_PATH,
        static_a: float = STATIC_PLATT_A,
        static_b: float = STATIC_PLATT_B,
    ):
        self.enabled = bool(enabled)
        self.min_observations = max(DEFAULT_MIN_OBSERVATIONS, int(min_observations))
        self.refit_seconds = max(0, int(refit_seconds))
        self.static_a = float(static_a)
        self.static_b = float(static_b)
        self.runtime_variant = str(runtime_variant or "auto")
        self.state_path = Path(state_path)
        self.report_path = Path(report_path)
        self.report_json_path = Path(report_json_path)

        self._owns_connection = False
        if isinstance(db, sqlite3.Connection):
            self.conn = db
            self.db_path = DEFAULT_DB_PATH
        elif hasattr(db, "conn"):
            self.conn = db.conn
            self.db_path = Path(getattr(db, "db_path", DEFAULT_DB_PATH))
        else:
            self.db_path = Path(db)
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(str(self.db_path))
            self._owns_connection = True

        self.conn.row_factory = sqlite3.Row
        self._ensure_tables()

        self.selected_variant = "static"
        self.active_mode = "static"
        self.active_a = float(self.static_a)
        self.active_b = float(self.static_b)
        self.sample_size = 0
        self.last_refit_ts = 0.0
        self.last_refit_at = ""
        self.last_refit_rows = 0

        self._load_state()
        self.selected_variant = self._resolve_selected_variant(self.runtime_variant)
        self.sample_size = self._observation_count()
        self._persist_state()

    def close(self) -> None:
        if self._owns_connection:
            self.conn.close()

    def _ensure_tables(self) -> None:
        self.conn.executescript(
            f"""
            CREATE TABLE IF NOT EXISTS {OBSERVATIONS_TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id TEXT UNIQUE,
                market_id TEXT,
                question TEXT,
                resolved_at TEXT,
                raw_prob REAL NOT NULL,
                outcome INTEGER NOT NULL,
                source TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS {STATE_TABLE} (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_{OBSERVATIONS_TABLE}_resolved_at
                ON {OBSERVATIONS_TABLE}(resolved_at, id);
            """
        )
        self.conn.commit()

    def _state_get(self, key: str, default: Any = None) -> Any:
        row = self.conn.execute(
            f"SELECT value FROM {STATE_TABLE} WHERE key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return default
        return json.loads(row["value"])

    def _state_set(self, key: str, value: Any) -> None:
        self.conn.execute(
            f"""
            INSERT INTO {STATE_TABLE} (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, json.dumps(value, sort_keys=True)),
        )

    def _load_state(self) -> None:
        payload = self._state_get("calibrator")
        if payload is None and self.state_path.exists():
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return

        self.active_a = float(payload.get("active_a", self.static_a))
        self.active_b = float(payload.get("active_b", self.static_b))
        self.active_mode = str(payload.get("active_mode", "static"))
        self.selected_variant = str(payload.get("selected_variant", "static"))
        self.sample_size = int(payload.get("sample_size", 0))
        self.last_refit_ts = float(payload.get("last_refit_ts", 0.0))
        self.last_refit_at = str(payload.get("last_refit_at", ""))
        self.last_refit_rows = int(payload.get("last_refit_rows", 0))

    def _persist_state(self) -> None:
        payload = {
            "active_a": self.active_a,
            "active_b": self.active_b,
            "active_mode": self.active_mode,
            "selected_variant": self.selected_variant,
            "sample_size": self.sample_size,
            "last_refit_ts": self.last_refit_ts,
            "last_refit_at": self.last_refit_at,
            "last_refit_rows": self.last_refit_rows,
        }
        self._state_set("calibrator", payload)
        self.conn.commit()

        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def _resolve_selected_variant(self, requested_variant: str) -> str:
        requested = str(requested_variant or "auto").strip().lower()
        if requested in RUNTIME_VARIANTS:
            return requested

        report_payload = None
        if self.report_json_path.exists():
            try:
                report_payload = json.loads(self.report_json_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                report_payload = None

        if isinstance(report_payload, dict):
            winner = str(
                report_payload.get("best_variant", {}).get("name")
                or report_payload.get("winner", "")
            ).strip()
            if winner in RUNTIME_VARIANTS:
                return winner

        return f"rolling_{DEFAULT_RUNTIME_WINDOW}"

    def _observation_count(self) -> int:
        row = self.conn.execute(
            f"SELECT COUNT(*) AS count FROM {OBSERVATIONS_TABLE}"
        ).fetchone()
        return int(row["count"]) if row else 0

    def _rows_for_refit(self) -> list[tuple[float, int]]:
        if self.selected_variant == "static":
            return []

        if self.selected_variant.startswith("rolling_"):
            limit = int(self.selected_variant.split("_", 1)[1])
            rows = self.conn.execute(
                f"""
                SELECT raw_prob, outcome
                FROM (
                    SELECT id, resolved_at, raw_prob, outcome
                    FROM {OBSERVATIONS_TABLE}
                    ORDER BY COALESCE(resolved_at, '') DESC, id DESC
                    LIMIT ?
                )
                ORDER BY COALESCE(resolved_at, '') ASC, id ASC
                """,
                (limit,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                f"""
                SELECT raw_prob, outcome
                FROM {OBSERVATIONS_TABLE}
                ORDER BY COALESCE(resolved_at, '') ASC, id ASC
                """
            ).fetchall()
        return [(float(row["raw_prob"]), int(row["outcome"])) for row in rows]

    def _recent_resolved_rows(self) -> list[tuple[float, int]]:
        self.sync_from_trade_db()
        rows = self.conn.execute(
            f"""
            SELECT raw_prob, outcome
            FROM (
                SELECT id, resolved_at, raw_prob, outcome
                FROM {OBSERVATIONS_TABLE}
                ORDER BY COALESCE(resolved_at, '') DESC, id DESC
                LIMIT ?
            )
            ORDER BY COALESCE(resolved_at, '') ASC, id ASC
            """,
            (DEFAULT_RUNTIME_WINDOW,),
        ).fetchall()
        return [(float(row["raw_prob"]), int(row["outcome"])) for row in rows]

    def add_observation(
        self,
        raw_prob: float,
        outcome: int,
        *,
        trade_id: str | None = None,
        market_id: str = "",
        question: str = "",
        resolved_at: str = "",
        source: str = "live",
    ) -> bool:
        raw_prob = float(raw_prob)
        outcome = int(outcome)
        if not (0.0 <= raw_prob <= 1.0):
            raise ValueError("raw_prob must be in [0, 1]")
        if outcome not in (0, 1):
            raise ValueError("outcome must be 0 or 1")

        cursor = self.conn.execute(
            f"""
            INSERT OR IGNORE INTO {OBSERVATIONS_TABLE} (
                trade_id,
                market_id,
                question,
                resolved_at,
                raw_prob,
                outcome,
                source
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade_id,
                str(market_id or ""),
                str(question or ""),
                str(resolved_at or ""),
                raw_prob,
                outcome,
                str(source or "live"),
            ),
        )
        inserted = cursor.rowcount > 0
        if inserted:
            self.sample_size = self._observation_count()
            self.conn.commit()
            self._persist_state()
        return inserted

    def sync_from_trade_db(self) -> int:
        tables = _sqlite_tables(self.conn)
        if "trades" not in tables:
            return 0

        columns = _table_columns(self.conn, "trades")
        required = {"id", "market_id", "question", "raw_prob", "resolution_price", "resolved_at"}
        if not required.issubset(columns):
            return 0

        platt_clause = "AND t.platt_mode IS NOT NULL" if "platt_mode" in columns else ""
        rows = self.conn.execute(
            f"""
            SELECT t.id,
                   COALESCE(t.market_id, '') AS market_id,
                   COALESCE(t.question, '') AS question,
                   COALESCE(t.resolved_at, '') AS resolved_at,
                   t.raw_prob AS raw_prob,
                   t.resolution_price AS resolution_price
            FROM trades t
            LEFT JOIN {OBSERVATIONS_TABLE} o
              ON o.trade_id = t.id
            WHERE o.trade_id IS NULL
              AND t.outcome IS NOT NULL
              AND t.raw_prob IS NOT NULL
              AND t.resolution_price IS NOT NULL
              {platt_clause}
            ORDER BY COALESCE(t.resolved_at, ''), t.id
            """
        ).fetchall()

        inserted = 0
        for row in rows:
            raw_prob = float(row["raw_prob"])
            resolved_price = float(row["resolution_price"])
            inserted += int(
                self.add_observation(
                    raw_prob,
                    1 if resolved_price >= 0.5 else 0,
                    trade_id=str(row["id"]),
                    market_id=str(row["market_id"]),
                    question=str(row["question"]),
                    resolved_at=str(row["resolved_at"]),
                    source="trades",
                )
            )
        return inserted

    def refit(self) -> bool:
        self.sample_size = self._observation_count()
        previous_mode = self.active_mode
        previous_a = self.active_a
        previous_b = self.active_b

        if not self.enabled or self.selected_variant == "static":
            self.active_mode = "static"
            self.active_a = float(self.static_a)
            self.active_b = float(self.static_b)
            self.last_refit_ts = time.time()
            self.last_refit_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.last_refit_ts))
            self.last_refit_rows = 0
            self._persist_state()
            return (self.active_mode, self.active_a, self.active_b) != (previous_mode, previous_a, previous_b)

        rows = self._rows_for_refit()
        self.last_refit_ts = time.time()
        self.last_refit_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.last_refit_ts))
        self.last_refit_rows = len(rows)

        if self.sample_size < self.min_observations or len(rows) < self.min_observations:
            self.active_mode = "static"
            self.active_a = float(self.static_a)
            self.active_b = float(self.static_b)
            self._persist_state()
            return (self.active_mode, self.active_a, self.active_b) != (previous_mode, previous_a, previous_b)

        raw_probs = [row[0] for row in rows]
        outcomes = [row[1] for row in rows]
        self.active_a, self.active_b = fit_platt_parameters(
            raw_probs,
            outcomes,
            initial_a=self.static_a,
            initial_b=self.static_b,
            min_samples=self.min_observations,
        )
        self.active_mode = self.selected_variant
        self._persist_state()
        return (self.active_mode, self.active_a, self.active_b) != (previous_mode, previous_a, previous_b)

    def refresh(self, force: bool = False) -> bool:
        inserted = self.sync_from_trade_db()
        if not self.enabled:
            self.active_mode = "static"
            self.active_a = float(self.static_a)
            self.active_b = float(self.static_b)
            self._persist_state()
            return False

        now = time.time()
        if not force and inserted == 0 and self.refit_seconds > 0 and (now - self.last_refit_ts) < self.refit_seconds:
            self.sample_size = self._observation_count()
            self._persist_state()
            return False
        return self.refit()

    def ensure_report(self, force: bool = False) -> dict[str, Any] | None:
        if not force and self.report_path.exists() and self.report_json_path.exists():
            try:
                payload = json.loads(self.report_json_path.read_text(encoding="utf-8"))
                winner = str(payload.get("best_variant", {}).get("name", "")).strip()
                if self.runtime_variant == "auto" and winner in RUNTIME_VARIANTS:
                    self.selected_variant = winner
                    self._persist_state()
                return payload
            except json.JSONDecodeError:
                pass

        comparison = write_comparison_report(
            report_path=self.report_path,
            json_path=self.report_json_path,
            min_samples=self.min_observations,
        )
        if self.runtime_variant == "auto":
            winner = str(
                comparison.get("best_variant", {}).get("name")
                or comparison.get("winner", "")
            ).strip()
            if winner in RUNTIME_VARIANTS:
                self.selected_variant = winner
                self._persist_state()
        return comparison

    def calibrate(self, raw_prob: float) -> float:
        return calibrate_probability_with_params(raw_prob, self.active_a, self.active_b)

    def summary(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "selected_variant": self.selected_variant,
            "active_mode": self.active_mode,
            "a": self.active_a,
            "b": self.active_b,
            "samples": self.sample_size,
            "min_observations": self.min_observations,
            "last_refit_at": self.last_refit_at,
            "last_refit_rows": self.last_refit_rows,
            "report_path": str(self.report_path),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the adaptive Platt comparison report.")
    parser.add_argument("--report-path", default=str(DEFAULT_REPORT_PATH))
    parser.add_argument("--json-path", default=str(DEFAULT_REPORT_JSON_PATH))
    parser.add_argument("--min-samples", type=int, default=DEFAULT_MIN_OBSERVATIONS)
    args = parser.parse_args()

    comparison = write_comparison_report(
        report_path=args.report_path,
        json_path=args.json_path,
        min_samples=args.min_samples,
    )
    print(
        f"Winner: {comparison['best_variant']['name']} "
        f"(Brier={comparison['best_variant']['brier']:.6f})"
    )
    print(f"Wrote {args.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
