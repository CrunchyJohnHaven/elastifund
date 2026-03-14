"""Frozen BTC5 market-model benchmark for one 24-hour epoch."""

from __future__ import annotations

import importlib.util
import json
import random
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.btc5_monte_carlo_core import DEFAULT_LOCAL_DB, DEFAULT_REMOTE_ROWS_JSON, load_observed_rows_from_db  # noqa: E402


DEFAULT_BENCHMARK_DIR = ROOT / "benchmarks" / "btc5_market" / "v1"
DEFAULT_MANIFEST_PATH = DEFAULT_BENCHMARK_DIR / "manifest.json"
DEFAULT_SNAPSHOT_PATH = DEFAULT_BENCHMARK_DIR / "frozen_windows.jsonl"
DEFAULT_MUTABLE_SURFACE = ROOT / "btc5_market_model_candidate.py"
WINDOW_MINUTES = 5
DEFAULT_EPOCH_HOURS = 24
DEFAULT_EPOCH_ROWS = int((DEFAULT_EPOCH_HOURS * 60) / WINDOW_MINUTES)
DEFAULT_BLOCK_SIZE = 4
BENCHMARK_VERSION = 1
OBJECTIVE_NAME = "simulator_loss"
SIMULATOR_LOSS_FORMULA = (
    "0.40*pnl_window_mae_pct + 0.25*fill_rate_mae_pct + 0.20*side_brier + 0.15*p95_drawdown_mae_pct"
)
SIMULATOR_LOSS_WEIGHTS = {
    "pnl_window_mae_pct": 0.40,
    "fill_rate_mae_pct": 0.25,
    "side_brier": 0.20,
    "p95_drawdown_mae_pct": 0.15,
}
IMMUTABLE_RUNNER_PATHS = (
    "benchmarks/btc5_market/v1/benchmark.py",
    "scripts/run_btc5_market_model_autoresearch.py",
    "scripts/render_btc5_market_model_progress.py",
)
DEFAULT_SEEDS = (
    11,
    29,
    53,
    71,
    97,
    113,
    149,
    173,
    197,
    223,
    251,
    281,
    313,
    337,
    367,
    397,
    421,
    449,
    479,
    503,
    541,
    569,
    601,
    631,
    659,
    691,
    719,
    751,
    787,
    811,
    839,
    863,
)
DEFAULT_FEATURE_FIELDS = [
    "direction",
    "session_name",
    "et_hour",
    "price_bucket",
    "delta_bucket",
    "delta",
    "abs_delta",
    "order_price",
    "best_bid",
    "best_ask",
    "open_price",
    "current_price",
    "edge_tier",
    "session_policy_name",
    "effective_stage",
    "loss_cluster_suppressed",
]


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return _now_utc().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_utc_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _plus_hours_iso(value: str, hours: int) -> str:
    return (_parse_utc_iso(value) + timedelta(hours=hours)).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _ts_to_iso(ts: int | None) -> str | None:
    if ts is None or int(ts) <= 0:
        return None
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: str | Path) -> str:
    return sha256(Path(path).read_bytes()).hexdigest()


def _relative(path: str | Path) -> str:
    target = Path(path)
    try:
        return str(target.relative_to(ROOT))
    except ValueError:
        return str(target)


def _git_metadata() -> dict[str, Any]:
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
    except Exception:
        sha = "unknown"
    try:
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=True,
            ).stdout.strip()
        )
    except Exception:
        dirty = True
    return {"sha": sha, "dirty": dirty}


def _load_remote_cache_rows(path: str | Path) -> list[dict[str, Any]]:
    cache_path = Path(path)
    if not cache_path.exists():
        return []
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        rows = payload.get("rows") or []
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = []
    return [dict(row) for row in rows if isinstance(row, dict)]


def _load_db_extra_rows(db_path: Path) -> dict[tuple[int, str, str], dict[str, Any]]:
    if not db_path.exists():
        return {}
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM window_trades ORDER BY window_start_ts ASC, id ASC").fetchall()
    except sqlite3.DatabaseError:
        conn.close()
        return {}
    finally:
        conn.close()

    enriched: dict[tuple[int, str, str], dict[str, Any]] = {}
    for row in rows:
        payload = dict(row)
        key = (
            _safe_int(payload.get("window_start_ts")),
            str(payload.get("slug") or ""),
            str(payload.get("direction") or "").strip().upper(),
        )
        enriched[key] = payload
    return enriched


def _row_identity(row: dict[str, Any]) -> tuple[int, str, str]:
    return (
        _safe_int(row.get("window_start_ts")),
        str(row.get("slug") or ""),
        str(row.get("direction") or "").strip().upper(),
    )


def _merge_rows(
    *,
    remote_rows: list[dict[str, Any]],
    db_rows: list[dict[str, Any]],
    db_extras: dict[tuple[int, str, str], dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    merged: dict[tuple[int, str, str], dict[str, Any]] = {}
    source_counts = {"remote_cache_rows": len(remote_rows), "db_rows": len(db_rows)}
    db_enrichment_hits = 0

    for row in remote_rows:
        key = _row_identity(row)
        merged[key] = dict(row)

    for row in db_rows:
        key = _row_identity(row)
        bucket = merged.setdefault(key, {})
        for field, value in row.items():
            if field not in bucket or bucket.get(field) in (None, "", 0, 0.0):
                bucket[field] = value

    for key, extras in db_extras.items():
        if key not in merged:
            continue
        db_enrichment_hits += 1
        bucket = merged[key]
        for field, value in extras.items():
            if field in {"won", "pnl_usd", "trade_size_usd", "order_status", "direction", "slug", "window_start_ts"}:
                continue
            if field not in bucket or bucket.get(field) in (None, ""):
                bucket[field] = value

    ordered = sorted(merged.values(), key=lambda item: (_safe_int(item.get("window_start_ts")), str(item.get("slug"))))
    return ordered, {
        "remote_cache_rows": len(remote_rows),
        "db_rows": len(db_rows),
        "merged_rows": len(ordered),
        "db_enrichment_hits": db_enrichment_hits,
    }


def _is_live_filled(row: dict[str, Any]) -> bool:
    status = str(row.get("order_status") or "").strip().lower()
    return status == "live_filled"


def _actual_side_up(row: dict[str, Any]) -> float:
    resolved_side = str(row.get("resolved_side") or "").strip().upper()
    if resolved_side == "UP":
        return 1.0
    if resolved_side == "DOWN":
        return 0.0
    direction = str(row.get("direction") or "").strip().upper()
    won = bool(row.get("won"))
    if direction == "UP":
        return 1.0 if won else 0.0
    if direction == "DOWN":
        return 0.0 if won else 1.0
    return 0.5


def _actual_fill_rate(row: dict[str, Any]) -> float:
    if _is_live_filled(row):
        return 1.0
    filled = _safe_int(row.get("filled"), 0)
    return 1.0 if filled > 0 else 0.0


def _actual_pnl_pct(row: dict[str, Any]) -> float:
    trade_size = _safe_float(row.get("trade_size_usd"), 0.0)
    pnl = _safe_float(row.get("realized_pnl_usd"), _safe_float(row.get("pnl_usd"), 0.0))
    if trade_size <= 0.0:
        return 0.0
    return pnl / trade_size


def _benchmark_row(row: dict[str, Any], feature_fields: list[str]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": _safe_int(row.get("id")),
        "window_start_ts": _safe_int(row.get("window_start_ts")),
        "slug": str(row.get("slug") or ""),
        "actual_side_up": _actual_side_up(row),
        "actual_fill_rate": _actual_fill_rate(row),
        "actual_pnl_pct": _actual_pnl_pct(row),
        "order_status": str(row.get("order_status") or ""),
        "source": str(row.get("source") or ""),
    }
    for field in feature_fields:
        payload[field] = row.get(field)
    return payload


def _write_snapshot(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(row, sort_keys=True) for row in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _load_snapshot_rows(path: str | Path) -> list[dict[str, Any]]:
    snapshot_path = Path(path)
    if not snapshot_path.exists():
        raise FileNotFoundError(snapshot_path)
    rows: list[dict[str, Any]] = []
    for line in snapshot_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def freeze_benchmark_from_rows(
    rows: list[dict[str, Any]],
    *,
    benchmark_dir: str | Path = DEFAULT_BENCHMARK_DIR,
    generated_at: str | None = None,
    source_artifacts: list[dict[str, Any]] | None = None,
    feature_fields: list[str] | None = None,
) -> dict[str, Any]:
    if not rows:
        raise ValueError("cannot freeze BTC5 market benchmark without rows")
    benchmark_root = Path(benchmark_dir)
    manifest_path = benchmark_root / "manifest.json"
    snapshot_path = benchmark_root / "frozen_windows.jsonl"
    generated_at = generated_at or utc_now_iso()
    feature_fields = list(feature_fields or DEFAULT_FEATURE_FIELDS)
    normalized_rows = [_benchmark_row(row, feature_fields) for row in rows]
    normalized_rows.sort(key=lambda item: (_safe_int(item.get("window_start_ts")), str(item.get("slug"))))

    benchmark_rows = min(DEFAULT_EPOCH_ROWS, len(normalized_rows))
    warmup_rows = max(0, len(normalized_rows) - benchmark_rows)
    epoch_rows = normalized_rows[warmup_rows:]
    _write_snapshot(snapshot_path, normalized_rows)
    snapshot_sha = sha256_file(snapshot_path)

    epoch_start_ts = _safe_int(epoch_rows[0].get("window_start_ts")) if epoch_rows else None
    epoch_end_ts = _safe_int(epoch_rows[-1].get("window_start_ts")) if epoch_rows else None
    epoch_hours_actual = (
        (((epoch_end_ts - epoch_start_ts) / 3600.0) + (WINDOW_MINUTES / 60.0))
        if epoch_start_ts is not None and epoch_end_ts is not None
        else 0.0
    )
    epoch_started_at_utc = generated_at
    epoch_expires_at_utc = _plus_hours_iso(epoch_started_at_utc, DEFAULT_EPOCH_HOURS)
    manifest = {
        "benchmark_id": "btc5_market_v1",
        "version": BENCHMARK_VERSION,
        "lane": "btc5_market",
        "mutable_surface": _relative(DEFAULT_MUTABLE_SURFACE),
        "immutable_runner_paths": list(IMMUTABLE_RUNNER_PATHS),
        "objective": {
            "name": OBJECTIVE_NAME,
            "formula": SIMULATOR_LOSS_FORMULA,
            "higher_is_better": False,
        },
        "epoch": {
            "epoch_length_hours_target": DEFAULT_EPOCH_HOURS,
            "epoch_length_hours_actual": round(epoch_hours_actual, 4),
            "epoch_row_target": DEFAULT_EPOCH_ROWS,
            "warmup_rows": warmup_rows,
            "benchmark_rows": benchmark_rows,
            "epoch_start_ts": epoch_start_ts,
            "epoch_end_ts": epoch_end_ts,
            "epoch_start_iso": _ts_to_iso(epoch_start_ts),
            "epoch_end_iso": _ts_to_iso(epoch_end_ts),
            "epoch_id": (
                f"{_ts_to_iso(epoch_start_ts) or 'unknown'}__{_ts_to_iso(epoch_end_ts) or 'unknown'}"
            ),
            "frozen_at": generated_at,
            "epoch_started_at_utc": epoch_started_at_utc,
            "epoch_expires_at_utc": epoch_expires_at_utc,
        },
        "data": {
            "snapshot_path": _relative(snapshot_path),
            "snapshot_sha256": snapshot_sha,
            "total_rows": len(normalized_rows),
            "feature_fields": feature_fields,
            "target_fields": ["actual_side_up", "actual_fill_rate", "actual_pnl_pct"],
            "source_artifacts": source_artifacts or [],
        },
        "replay": {
            "fit_seed": 0,
            "bootstrap_paths": len(DEFAULT_SEEDS),
            "path_length": benchmark_rows,
            "block_size": DEFAULT_BLOCK_SIZE,
            "seed_list": list(DEFAULT_SEEDS),
        },
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def freeze_current_benchmark(
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
    db_path: str | Path = DEFAULT_LOCAL_DB,
    remote_cache_path: str | Path = DEFAULT_REMOTE_ROWS_JSON,
) -> dict[str, Any]:
    manifest_file = Path(manifest_path)
    benchmark_dir = manifest_file.parent
    db_file = Path(db_path)
    cache_file = Path(remote_cache_path)
    remote_rows = _load_remote_cache_rows(cache_file)
    db_rows = load_observed_rows_from_db(db_file) if db_file.exists() else []
    db_extras = _load_db_extra_rows(db_file)
    merged_rows, merge_meta = _merge_rows(remote_rows=remote_rows, db_rows=db_rows, db_extras=db_extras)
    source_artifacts = [
        {
            "path": _relative(cache_file),
            "exists": cache_file.exists(),
            "rows_loaded": len(remote_rows),
            "role": "cached_rows",
        },
        {
            "path": _relative(db_file),
            "exists": db_file.exists(),
            "rows_loaded": len(db_rows),
            "role": "local_db_rows",
        },
        {
            "path": _relative(db_file),
            "exists": db_file.exists(),
            "rows_loaded": len(db_extras),
            "role": "db_only_enrichments",
        },
    ]
    source_artifacts.append({"merge": merge_meta})
    return freeze_benchmark_from_rows(
        merged_rows,
        benchmark_dir=benchmark_dir,
        generated_at=utc_now_iso(),
        source_artifacts=source_artifacts,
    )


def load_manifest(path: str | Path = DEFAULT_MANIFEST_PATH) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def verify_manifest(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    if int(manifest.get("version") or 0) != BENCHMARK_VERSION:
        raise ValueError(
            f"expected benchmark version {BENCHMARK_VERSION}, found {manifest.get('version')!r}"
        )
    if str(manifest.get("mutable_surface") or "") != _relative(DEFAULT_MUTABLE_SURFACE):
        raise ValueError(
            f"mutable_surface drifted from {_relative(DEFAULT_MUTABLE_SURFACE)}: {manifest.get('mutable_surface')!r}"
        )
    objective = manifest.get("objective") or {}
    if str(objective.get("name") or "") != OBJECTIVE_NAME:
        raise ValueError(f"objective.name drifted from {OBJECTIVE_NAME!r}")
    if str(objective.get("formula") or "") != SIMULATOR_LOSS_FORMULA:
        raise ValueError("objective.formula drifted from frozen simulator_loss contract")
    immutable_runner_paths = manifest.get("immutable_runner_paths") or []
    if list(immutable_runner_paths) != list(IMMUTABLE_RUNNER_PATHS):
        raise ValueError("immutable_runner_paths drifted from the frozen BTC5 market runner contract")
    for relative_path in immutable_runner_paths:
        runner_path = ROOT / str(relative_path)
        if not runner_path.exists():
            raise FileNotFoundError(runner_path)
    epoch = manifest.get("epoch") or {}
    started_at = str(epoch.get("epoch_started_at_utc") or "")
    expires_at = str(epoch.get("epoch_expires_at_utc") or "")
    if not started_at or not expires_at:
        raise ValueError("epoch_started_at_utc and epoch_expires_at_utc are required")
    expiry_delta = _parse_utc_iso(expires_at) - _parse_utc_iso(started_at)
    if expiry_delta.total_seconds() != float(DEFAULT_EPOCH_HOURS * 3600):
        raise ValueError("frozen benchmark epoch must expire exactly 24 hours after epoch_started_at_utc")
    snapshot_path = ROOT / manifest["data"]["snapshot_path"]
    observed_sha = sha256_file(snapshot_path)
    expected_sha = manifest["data"]["snapshot_sha256"]
    if observed_sha != expected_sha:
        raise ValueError(
            f"snapshot checksum mismatch for {snapshot_path}: expected {expected_sha}, observed {observed_sha}"
        )
    rows = _load_snapshot_rows(snapshot_path)
    if len(rows) != int(manifest["data"]["total_rows"]):
        raise ValueError(
            f"expected {manifest['data']['total_rows']} snapshot rows, found {len(rows)}"
        )
    return [{"path": _relative(snapshot_path), "sha256": observed_sha, "rows": len(rows)}]


def split_rows(
    rows: list[dict[str, Any]],
    manifest: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    warmup_rows = int(manifest["epoch"]["warmup_rows"])
    benchmark_rows = int(manifest["epoch"]["benchmark_rows"])
    warmup = rows[:warmup_rows]
    holdout = rows[warmup_rows : warmup_rows + benchmark_rows]
    if len(holdout) != benchmark_rows:
        raise ValueError("manifest benchmark_rows does not match snapshot shape")
    return warmup, holdout


def _load_candidate_module(candidate_path: str | Path) -> Any:
    candidate_file = Path(candidate_path)
    if not candidate_file.is_absolute():
        candidate_file = ROOT / candidate_file
    spec = importlib.util.spec_from_file_location("btc5_market_model_candidate_runtime", candidate_file)
    if spec is None or spec.loader is None:
        raise ImportError(f"unable to load candidate module from {candidate_file}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, float(value)))


def _bootstrap_indices(length: int, *, seed: int, path_length: int, block_size: int) -> list[int]:
    rng = random.Random(seed)
    indices: list[int] = []
    while len(indices) < path_length:
        start = rng.randrange(length)
        for offset in range(block_size):
            indices.append((start + offset) % length)
            if len(indices) >= path_length:
                break
    return indices


def _max_drawdown_pct(path_values: list[float]) -> float:
    running = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in path_values:
        running += value
        peak = max(peak, running)
        max_drawdown = max(max_drawdown, peak - running)
    return max_drawdown


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * (pct / 100.0)))
    index = max(0, min(index, len(ordered) - 1))
    return float(ordered[index])


def _p95_drawdown_pct(
    pnl_pct_values: list[float],
    *,
    seed_list: list[int],
    path_length: int,
    block_size: int,
) -> float:
    if not pnl_pct_values:
        return 0.0
    drawdowns = [
        _max_drawdown_pct(
            [pnl_pct_values[index] for index in _bootstrap_indices(len(pnl_pct_values), seed=seed, path_length=path_length, block_size=block_size)]
        )
        for seed in seed_list
    ]
    return _percentile(drawdowns, 95.0)


def _mean_abs_error(predicted: list[float], actual: list[float]) -> float:
    if not predicted or not actual or len(predicted) != len(actual):
        return 0.0
    return sum(abs(left - right) for left, right in zip(predicted, actual, strict=False)) / float(len(predicted))


def _brier_score(predicted: list[float], actual: list[float]) -> float:
    if not predicted or not actual or len(predicted) != len(actual):
        return 0.0
    return sum((left - right) ** 2 for left, right in zip(predicted, actual, strict=False)) / float(len(predicted))


def run_benchmark(
    manifest_path_value: str | Path = DEFAULT_MANIFEST_PATH,
    *,
    candidate_path: str | Path = DEFAULT_MUTABLE_SURFACE,
    allow_noncanonical_candidate: bool = False,
    description: str = "",
) -> dict[str, Any]:
    manifest_file = Path(manifest_path_value)
    if not manifest_file.is_absolute():
        manifest_file = ROOT / manifest_file
    manifest = load_manifest(manifest_file)
    checks = verify_manifest(manifest)
    rows = _load_snapshot_rows(ROOT / manifest["data"]["snapshot_path"])
    warmup_rows, holdout_rows = split_rows(rows, manifest)

    candidate_file = Path(candidate_path)
    if not candidate_file.is_absolute():
        candidate_file = ROOT / candidate_file
    canonical_candidate = DEFAULT_MUTABLE_SURFACE.resolve()
    if (not allow_noncanonical_candidate) and candidate_file.resolve() != canonical_candidate:
        raise ValueError(
            "btc5_market_v1 enforces one mutable surface: "
            f"{_relative(canonical_candidate)}"
        )

    candidate_module = _load_candidate_module(candidate_file)
    if not hasattr(candidate_module, "fit_market_model") or not hasattr(candidate_module, "predict_market_row"):
        raise AttributeError("candidate module must define fit_market_model() and predict_market_row()")

    feature_fields = list(manifest["data"]["feature_fields"])
    model = candidate_module.fit_market_model(
        warmup_rows,
        feature_fields=feature_fields,
        seed=int(manifest["replay"].get("fit_seed", 0)),
    )

    predicted_p_up: list[float] = []
    predicted_fill_rate: list[float] = []
    predicted_pnl_pct: list[float] = []
    actual_side_up: list[float] = []
    actual_fill_rate: list[float] = []
    actual_pnl_pct: list[float] = []
    preview_rows: list[dict[str, Any]] = []

    for row in holdout_rows:
        candidate_row = {"window_start_ts": row["window_start_ts"], "slug": row["slug"]}
        for field in feature_fields:
            candidate_row[field] = row.get(field)
        prediction = candidate_module.predict_market_row(model, candidate_row, feature_fields=feature_fields)
        p_up = _clamp(_safe_float(prediction.get("p_up"), 0.5), 0.001, 0.999)
        fill_rate = _clamp(_safe_float(prediction.get("fill_rate"), 0.0), 0.0, 1.0)
        pnl_pct = _clamp(_safe_float(prediction.get("pnl_pct"), 0.0), -2.0, 2.0)

        predicted_p_up.append(p_up)
        predicted_fill_rate.append(fill_rate)
        predicted_pnl_pct.append(pnl_pct)
        actual_side_up.append(_safe_float(row.get("actual_side_up"), 0.5))
        actual_fill_rate.append(_safe_float(row.get("actual_fill_rate"), 0.0))
        actual_pnl_pct.append(_safe_float(row.get("actual_pnl_pct"), 0.0))

        if len(preview_rows) < 5:
            preview_rows.append(
                {
                    "window_start_ts": row["window_start_ts"],
                    "slug": row["slug"],
                    "actual_side_up": round(_safe_float(row.get("actual_side_up"), 0.5), 4),
                    "predicted_p_up": round(p_up, 4),
                    "actual_fill_rate": round(_safe_float(row.get("actual_fill_rate"), 0.0), 4),
                    "predicted_fill_rate": round(fill_rate, 4),
                    "actual_pnl_pct": round(_safe_float(row.get("actual_pnl_pct"), 0.0), 4),
                    "predicted_pnl_pct": round(pnl_pct, 4),
                }
            )

    replay = manifest["replay"]
    observed_p95_drawdown_pct = _p95_drawdown_pct(
        actual_pnl_pct,
        seed_list=list(replay["seed_list"]),
        path_length=int(replay["path_length"]),
        block_size=int(replay["block_size"]),
    )
    predicted_p95_drawdown_pct = _p95_drawdown_pct(
        predicted_pnl_pct,
        seed_list=list(replay["seed_list"]),
        path_length=int(replay["path_length"]),
        block_size=int(replay["block_size"]),
    )

    metrics = {
        "pnl_window_mae_pct": round(_mean_abs_error(predicted_pnl_pct, actual_pnl_pct), 6),
        "fill_rate_mae_pct": round(_mean_abs_error(predicted_fill_rate, actual_fill_rate), 6),
        "side_brier": round(_brier_score(predicted_p_up, actual_side_up), 6),
        "p95_drawdown_mae_pct": round(abs(predicted_p95_drawdown_pct - observed_p95_drawdown_pct), 6),
    }
    simulator_loss = round(
        sum(weight * metrics[metric_name] for metric_name, weight in SIMULATOR_LOSS_WEIGHTS.items()),
        6,
    )

    return {
        "benchmark_id": manifest["benchmark_id"],
        "benchmark_version": int(manifest.get("version") or BENCHMARK_VERSION),
        "generated_at": utc_now_iso(),
        "description": description.strip(),
        "manifest_path": _relative(manifest_file),
        "mutable_surface": manifest["mutable_surface"],
        "mutable_surface_sha256": sha256_file(candidate_file),
        "candidate_contract_version": int(getattr(candidate_module, "CANDIDATE_CONTRACT_VERSION", 1)),
        "candidate_model_name": str(getattr(candidate_module, "MODEL_NAME", candidate_file.stem)),
        "candidate_model_version": int(getattr(candidate_module, "MODEL_VERSION", 1)),
        "git": _git_metadata(),
        "objective": manifest["objective"],
        "epoch": manifest["epoch"],
        "dataset": {
            "total_rows": int(manifest["data"]["total_rows"]),
            "warmup_rows": len(warmup_rows),
            "benchmark_rows": len(holdout_rows),
            "feature_fields": feature_fields,
            "checksums": checks,
            "source_artifacts": manifest["data"]["source_artifacts"],
        },
        "metrics": {**metrics, "simulator_loss": simulator_loss},
        "diagnostics": {
            "observed_fill_rate": round(sum(actual_fill_rate) / float(len(actual_fill_rate) or 1), 6),
            "predicted_fill_rate": round(sum(predicted_fill_rate) / float(len(predicted_fill_rate) or 1), 6),
            "observed_mean_pnl_pct": round(sum(actual_pnl_pct) / float(len(actual_pnl_pct) or 1), 6),
            "predicted_mean_pnl_pct": round(sum(predicted_pnl_pct) / float(len(predicted_pnl_pct) or 1), 6),
            "observed_p95_drawdown_pct": round(observed_p95_drawdown_pct, 6),
            "predicted_p95_drawdown_pct": round(predicted_p95_drawdown_pct, 6),
            "sample_predictions": preview_rows,
        },
    }


def default_artifact_paths(output_dir: str | Path, slug: str | None = None) -> tuple[Path, Path]:
    base_dir = Path(output_dir)
    base_dir.mkdir(parents=True, exist_ok=True)
    stem = slug.strip() if slug else _now_utc().strftime("%Y%m%dT%H%M%SZ")
    return base_dir / f"{stem}.json", base_dir / f"{stem}.md"


def render_summary_markdown(packet: dict[str, Any]) -> str:
    metrics = packet["metrics"]
    proposal = packet.get("proposal") if isinstance(packet.get("proposal"), dict) else {}
    decision = packet.get("decision") if isinstance(packet.get("decision"), dict) else {}
    lines = [
        "# BTC5 Market Benchmark Packet",
        "",
        f"- Benchmark: `{packet['benchmark_id']}`",
        f"- Generated at: {packet['generated_at']}",
        f"- Epoch: `{packet['epoch']['epoch_id']}`",
        f"- Mutable surface: `{packet['mutable_surface']}`",
        f"- Candidate model: `{packet['candidate_model_name']}` v{packet['candidate_model_version']}",
        f"- Working tree dirty: {packet['git']['dirty']}",
        f"- Git SHA: `{packet['git']['sha']}`",
        f"- Warmup rows: {packet['dataset']['warmup_rows']}",
        f"- Benchmark rows: {packet['dataset']['benchmark_rows']}",
        f"- Loss: `{metrics['simulator_loss']:.6f}`",
        f"- pnl_window_mae_pct: `{metrics['pnl_window_mae_pct']:.6f}`",
        f"- fill_rate_mae_pct: `{metrics['fill_rate_mae_pct']:.6f}`",
        f"- side_brier: `{metrics['side_brier']:.6f}`",
        f"- p95_drawdown_mae_pct: `{metrics['p95_drawdown_mae_pct']:.6f}`",
    ]
    if proposal:
        lines.extend(
            [
                f"- Proposal id: `{proposal.get('proposal_id', 'n/a')}`",
                f"- Parent champion id: `{proposal.get('parent_champion_id', 'n/a')}`",
                f"- Proposer model: `{proposal.get('proposer_model', 'n/a')}`",
                f"- Estimated proposer cost usd: `{proposal.get('estimated_llm_cost_usd', 'n/a')}`",
                f"- Mutation type: `{proposal.get('mutation_type', 'n/a')}`",
                f"- Mutation summary: {proposal.get('mutation_summary', '')}",
            ]
        )
    if decision:
        lines.extend(
            [
                f"- Decision status: `{decision.get('status', 'n/a')}`",
                f"- Decision reason: `{decision.get('reason', 'n/a')}`",
            ]
        )
    lines.extend(
        [
            "",
            "Benchmark progress is benchmark evidence, not realized P&L.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_benchmark_artifacts(
    packet: dict[str, Any],
    *,
    json_path: str | Path,
    summary_path: str | Path,
) -> dict[str, str]:
    json_file = Path(json_path)
    summary_file = Path(summary_path)
    json_file.parent.mkdir(parents=True, exist_ok=True)
    summary_file.parent.mkdir(parents=True, exist_ok=True)
    json_file.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary_file.write_text(render_summary_markdown(packet), encoding="utf-8")
    return {"json_path": str(json_file), "summary_path": str(summary_file)}
