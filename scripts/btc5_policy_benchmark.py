#!/usr/bin/env python3
"""Shared BTC5 policy benchmark helpers for legacy and market-backed evaluation."""

from __future__ import annotations

import hashlib
import json
import random
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from benchmarks.btc5_market.v1 import benchmark as market_benchmark


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MARKET_LATEST_JSON = ROOT / "reports" / "autoresearch" / "btc5_market" / "latest.json"
DEFAULT_MARKET_POLICY_HANDOFF = ROOT / "reports" / "autoresearch" / "btc5_market" / "policy_handoff.json"

POLICY_BENCHMARK_ID = "btc5_policy_market_v1"
POLICY_BENCHMARK_LABEL = "BTC5 policy benchmark"
POLICY_LOSS_CONTRACT_VERSION = 2
POLICY_LOSS_FORMULA = (
    "(-p05_30d_return_pct) + 0.25*(-median_30d_return_pct) + 2.0*loss_limit_hit_probability "
    "+ 1.0*non_positive_path_probability + 0.05*p95_drawdown_pct"
)
POLICY_KEEP_EPSILON = 0.25
PROMOTION_FILL_RETENTION_FLOOR = 0.85
POLICY_30D_HORIZON_DAYS = 30
POLICY_LOSS_LIMIT_RETURN_PCT = 5.0
POLICY_EVALUATION_SOURCE = "market_champion_replay"
POLICY_FOLD_COUNT = 4
POLICY_CONFIDENCE_BOOTSTRAPS = 400


def safe_float(value: Any, default: float | None = 0.0) -> float | None:
    try:
        if value in (None, ""):
            return None if default is None else float(default)
        return float(value)
    except (TypeError, ValueError):
        return None if default is None else float(default)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return int(default)
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "on"}


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, float(value)))


def _resolve_path(path_value: str | Path) -> Path:
    path = Path(path_value)
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def _relative_path(path_value: str | Path) -> str:
    path = _resolve_path(path_value)
    try:
        return str(path.relative_to(ROOT.resolve()))
    except ValueError:
        return str(path)


def _load_json(path_value: str | Path) -> dict[str, Any]:
    path = _resolve_path(path_value)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _age_seconds(path: Path, payload: dict[str, Any]) -> float | None:
    for key in ("updated_at", "generated_at", "evaluated_at", "finished_at", "created_at"):
        parsed = _parse_timestamp(payload.get(key))
        if parsed is not None:
            return max(0.0, (datetime.now(tz=UTC) - parsed).total_seconds())
    if not path.exists():
        return None
    return max(0.0, datetime.now(tz=UTC).timestamp() - path.stat().st_mtime)


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * (pct / 100.0)))
    index = max(0, min(index, len(ordered) - 1))
    return float(ordered[index])


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(sum(values) / len(values))


def _max_drawdown_pct(values: list[float]) -> float:
    running = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in values:
        running += value
        peak = max(peak, running)
        max_drawdown = max(max_drawdown, peak - running)
    return max_drawdown


def _bootstrap_indices(length: int, *, seed: int, path_length: int, block_size: int) -> list[int]:
    if length <= 0 or path_length <= 0:
        return []
    return market_benchmark._bootstrap_indices(  # type: ignore[attr-defined]
        length,
        seed=seed,
        path_length=path_length,
        block_size=max(1, int(block_size)),
    )


def _contiguous_fold_ranges(length: int, fold_count: int) -> list[tuple[int, int]]:
    if length <= 0:
        return []
    fold_count = max(1, min(int(fold_count), length))
    base, remainder = divmod(length, fold_count)
    ranges: list[tuple[int, int]] = []
    start = 0
    for index in range(fold_count):
        size = base + (1 if index < remainder else 0)
        end = start + size
        if end > start:
            ranges.append((start, end))
        start = end
    return ranges


def _bootstrap_mean_ci(
    values: list[float],
    *,
    seed: int,
    samples: int = POLICY_CONFIDENCE_BOOTSTRAPS,
    alpha: float = 0.05,
) -> tuple[float, float]:
    if not values:
        return (0.0, 0.0)
    if len(values) == 1:
        single = float(values[0])
        return (single, single)
    rng = random.Random(int(seed))
    means: list[float] = []
    population = list(values)
    for _ in range(max(1, int(samples))):
        draw = [population[rng.randrange(len(population))] for _ in range(len(population))]
        means.append(_mean(draw))
    lower_pct = max(0.0, (alpha / 2.0) * 100.0)
    upper_pct = min(100.0, (1.0 - alpha / 2.0) * 100.0)
    return (_percentile(means, lower_pct), _percentile(means, upper_pct))


def policy_loss_components(
    *,
    p05_30d_return_pct: Any,
    median_30d_return_pct: Any,
    loss_limit_hit_probability: Any,
    non_positive_path_probability: Any,
    p95_drawdown_pct: Any,
    fill_retention_ratio: Any = 1.0,
) -> dict[str, float]:
    p05_return = safe_float(p05_30d_return_pct, 0.0)
    median_return = safe_float(median_30d_return_pct, 0.0)
    loss_hit = _clamp(safe_float(loss_limit_hit_probability, 0.0), 0.0, 1.0)
    non_positive = _clamp(safe_float(non_positive_path_probability, 0.0), 0.0, 1.0)
    drawdown = max(0.0, safe_float(p95_drawdown_pct, 0.0))
    fill_retention = max(0.0, safe_float(fill_retention_ratio, 1.0))
    policy_loss = (
        (-p05_return)
        + (0.25 * (-median_return))
        + (2.0 * loss_hit)
        + non_positive
        + (0.05 * drawdown)
    )
    return {
        "p05_30d_return_pct": round(p05_return, 4),
        "median_30d_return_pct": round(median_return, 4),
        "loss_limit_hit_probability": round(loss_hit, 6),
        "non_positive_path_probability": round(non_positive, 6),
        "p95_drawdown_pct": round(drawdown, 4),
        "fill_retention_ratio": round(fill_retention, 4),
        "policy_loss": round(policy_loss, 4),
    }


def _legacy_policy_loss_components(
    *,
    expected_pnl_usd: Any,
    p05_pnl_usd: Any,
    p95_drawdown_usd: Any,
    loss_limit_hit_probability: Any,
) -> dict[str, float]:
    expected = safe_float(expected_pnl_usd, 0.0)
    p05 = safe_float(p05_pnl_usd, 0.0)
    drawdown = max(0.0, safe_float(p95_drawdown_usd, 0.0))
    loss_hit = max(0.0, safe_float(loss_limit_hit_probability, 0.0))
    tail_loss = max(0.0, -p05)
    loss_hit_scale = max(1.0, abs(expected), tail_loss, drawdown)
    loss_hit_penalty = loss_hit * loss_hit_scale
    return {
        "expected_pnl_usd": round(expected, 4),
        "tail_loss_usd": round(tail_loss, 4),
        "p95_drawdown_usd": round(drawdown, 4),
        "loss_limit_hit_probability": round(loss_hit, 6),
        "loss_hit_penalty_usd": round(loss_hit_penalty, 4),
        "policy_loss": round((-expected) + tail_loss + drawdown + loss_hit_penalty, 4),
    }


def policy_loss_from_projection(projection: dict[str, Any] | None) -> dict[str, float]:
    block = projection if isinstance(projection, dict) else {}
    if any(key in block for key in ("p05_30d_return_pct", "median_30d_return_pct", "non_positive_path_probability", "p95_drawdown_pct")):
        return policy_loss_components(
            p05_30d_return_pct=block.get("p05_30d_return_pct"),
            median_30d_return_pct=block.get("median_30d_return_pct"),
            loss_limit_hit_probability=block.get("loss_limit_hit_probability"),
            non_positive_path_probability=block.get("non_positive_path_probability", 1.0 - safe_float(block.get("profit_probability"), 0.0)),
            p95_drawdown_pct=block.get("p95_drawdown_pct", block.get("p95_drawdown_pct_of_wallet")),
            fill_retention_ratio=block.get("fill_retention_ratio", 1.0),
        )
    return _legacy_policy_loss_components(
        expected_pnl_usd=block.get("expected_pnl_30d_usd"),
        p05_pnl_usd=block.get("p05_pnl_30d_usd"),
        p95_drawdown_usd=block.get("p95_drawdown_usd"),
        loss_limit_hit_probability=block.get("loss_limit_hit_probability"),
    )


def policy_loss_from_candidate(candidate: dict[str, Any] | None) -> dict[str, float]:
    payload = candidate if isinstance(candidate, dict) else {}
    if isinstance(payload.get("policy_benchmark"), dict):
        benchmark = payload["policy_benchmark"]
        if "p05_30d_return_pct" in benchmark or "median_30d_return_pct" in benchmark:
            return policy_loss_components(
                p05_30d_return_pct=benchmark.get("p05_30d_return_pct"),
                median_30d_return_pct=benchmark.get("median_30d_return_pct"),
                loss_limit_hit_probability=benchmark.get("loss_limit_hit_probability"),
                non_positive_path_probability=benchmark.get("non_positive_path_probability"),
                p95_drawdown_pct=benchmark.get("p95_drawdown_pct"),
                fill_retention_ratio=benchmark.get("fill_retention_ratio", 1.0),
            )
    continuation = payload.get("continuation") if isinstance(payload.get("continuation"), dict) else {}
    monte_carlo = payload.get("monte_carlo") if isinstance(payload.get("monte_carlo"), dict) else {}
    if continuation:
        return policy_loss_components(
            p05_30d_return_pct=continuation.get("p05_arr_pct"),
            median_30d_return_pct=continuation.get("median_arr_pct"),
            loss_limit_hit_probability=monte_carlo.get("loss_limit_hit_probability"),
            non_positive_path_probability=monte_carlo.get("non_positive_path_probability", 1.0 - safe_float(monte_carlo.get("profit_probability"), 0.0)),
            p95_drawdown_pct=monte_carlo.get("p95_max_drawdown_pct", 0.0),
            fill_retention_ratio=payload.get("fill_retention_ratio", 1.0),
        )
    return _legacy_policy_loss_components(
        expected_pnl_usd=monte_carlo.get("median_total_pnl_usd"),
        p05_pnl_usd=monte_carlo.get("p05_total_pnl_usd"),
        p95_drawdown_usd=monte_carlo.get("p95_max_drawdown_usd"),
        loss_limit_hit_probability=monte_carlo.get("loss_limit_hit_probability"),
    )


def runtime_package_hash(runtime_package: dict[str, Any] | None) -> str:
    payload = runtime_package if isinstance(runtime_package, dict) else {}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def runtime_package_id(runtime_package: dict[str, Any] | None) -> str:
    payload = runtime_package if isinstance(runtime_package, dict) else {}
    profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}
    profile_name = str(profile.get("name") or "").strip()
    if profile_name:
        return profile_name
    return runtime_package_hash(payload)[:12]


def _normalized_runtime_package(runtime_package: dict[str, Any] | None) -> dict[str, Any]:
    payload = runtime_package if isinstance(runtime_package, dict) else {}
    profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}
    session_policy_raw = payload.get("session_policy") if isinstance(payload.get("session_policy"), list) else []
    session_policy: list[dict[str, Any]] = []
    for item in session_policy_raw:
        if not isinstance(item, dict):
            continue
        hours = sorted(
            int(hour)
            for hour in (item.get("et_hours") or [])
            if isinstance(hour, int) or (isinstance(hour, str) and str(hour).isdigit())
        )
        session_policy.append(
            {
                "name": str(item.get("name") or profile.get("name") or "session_policy").strip() or "session_policy",
                "et_hours": hours,
                "max_abs_delta": safe_float(item.get("max_abs_delta"), None) if item.get("max_abs_delta") is not None else None,
                "up_max_buy_price": safe_float(item.get("up_max_buy_price"), None) if item.get("up_max_buy_price") is not None else None,
                "down_max_buy_price": safe_float(item.get("down_max_buy_price"), None) if item.get("down_max_buy_price") is not None else None,
            }
        )
    session_policy.sort(key=lambda item: (len(item["et_hours"]), tuple(item["et_hours"]), item["name"]))
    return {
        "profile": {
            "name": str(profile.get("name") or "").strip() or runtime_package_id(payload),
            "max_abs_delta": safe_float(profile.get("max_abs_delta"), None) if profile.get("max_abs_delta") is not None else None,
            "up_max_buy_price": safe_float(profile.get("up_max_buy_price"), None) if profile.get("up_max_buy_price") is not None else None,
            "down_max_buy_price": safe_float(profile.get("down_max_buy_price"), None) if profile.get("down_max_buy_price") is not None else None,
        },
        "session_policy": session_policy,
    }


def _profile_allows_row(row: dict[str, Any], profile: dict[str, Any]) -> bool:
    direction = str(row.get("direction") or "").strip().upper()
    order_price = safe_float(row.get("order_price"), 0.0)
    abs_delta = safe_float(row.get("abs_delta"), abs(safe_float(row.get("delta"), 0.0)))
    max_abs_delta = profile.get("max_abs_delta")
    if max_abs_delta is not None and abs_delta > safe_float(max_abs_delta, 0.0):
        return False
    up_max = profile.get("up_max_buy_price")
    down_max = profile.get("down_max_buy_price")
    if direction == "UP" and up_max is not None and order_price > safe_float(up_max, 0.0):
        return False
    if direction == "DOWN" and down_max is not None and order_price > safe_float(down_max, 0.0):
        return False
    return True


def runtime_package_matches_row(row: dict[str, Any], runtime_package: dict[str, Any] | None) -> bool:
    package = _normalized_runtime_package(runtime_package)
    hour = row.get("et_hour")
    if hour is not None:
        for item in package["session_policy"]:
            if int(hour) in item.get("et_hours", []):
                return _profile_allows_row(row, item)
    return _profile_allows_row(row, package["profile"])


def market_policy_handoff_payload(
    *,
    market_latest_path: str | Path = DEFAULT_MARKET_LATEST_JSON,
) -> dict[str, Any]:
    latest_path = _resolve_path(market_latest_path)
    latest_payload = _load_json(latest_path)
    champion = latest_payload.get("champion") if isinstance(latest_payload.get("champion"), dict) else {}
    manifest_path_text = str(
        latest_payload.get("manifest_path")
        or champion.get("manifest_path")
        or market_benchmark.DEFAULT_MANIFEST_PATH
    )
    manifest_path = _resolve_path(manifest_path_text)
    manifest = market_benchmark.load_manifest(manifest_path)
    packet_path_text = str(champion.get("packet_json") or "")
    packet_path = _resolve_path(packet_path_text) if packet_path_text else None
    packet_payload = _load_json(packet_path) if packet_path is not None else {}
    latest_age_seconds = _age_seconds(latest_path, latest_payload)
    freshness_seconds = int(market_benchmark.DEFAULT_EPOCH_HOURS * 3600)
    epoch = manifest.get("epoch") if isinstance(manifest.get("epoch"), dict) else {}
    epoch_expires_at = _parse_timestamp(epoch.get("epoch_expires_at_utc"))
    now = datetime.now(tz=UTC)
    epoch_active = bool(epoch_expires_at and epoch_expires_at > now)
    market_model_version = (
        f"{champion.get('experiment_id')}:{champion.get('candidate_hash')}"
        if champion.get("experiment_id") is not None or champion.get("candidate_hash")
        else epoch.get("epoch_id")
    )
    return {
        "benchmark_id": manifest.get("benchmark_id", "btc5_market_v1"),
        "generated_at": latest_payload.get("updated_at") or latest_payload.get("latest_experiment", {}).get("generated_at"),
        "market_epoch_id": epoch.get("epoch_id"),
        "market_epoch_expires_at_utc": epoch.get("epoch_expires_at_utc"),
        "market_epoch_active": epoch_active,
        "market_model_version": market_model_version,
        "policy_benchmark": {
            "benchmark_id": POLICY_BENCHMARK_ID,
            "label": POLICY_BENCHMARK_LABEL,
            "policy_loss_contract_version": POLICY_LOSS_CONTRACT_VERSION,
            "policy_loss_formula": POLICY_LOSS_FORMULA,
            "horizon_days": POLICY_30D_HORIZON_DAYS,
            "loss_limit_return_pct": POLICY_LOSS_LIMIT_RETURN_PCT,
            "keep_epsilon": POLICY_KEEP_EPSILON,
            "fill_retention_floor": PROMOTION_FILL_RETENTION_FLOOR,
            "evaluation_source": POLICY_EVALUATION_SOURCE,
        },
        "market_champion": {
            "id": champion.get("experiment_id"),
            "candidate_model_name": champion.get("candidate_model_name"),
            "candidate_hash": champion.get("candidate_hash"),
            "candidate_path": champion.get("candidate_path") or manifest.get("mutable_surface"),
            "loss": champion.get("loss"),
            "packet_json": packet_path_text or champion.get("packet_json"),
        },
        "market_latest": {
            "path": _relative_path(latest_path),
            "freshness_seconds": freshness_seconds,
            "age_seconds": round(latest_age_seconds, 4) if latest_age_seconds is not None else None,
            "is_fresh": latest_age_seconds is not None and latest_age_seconds <= freshness_seconds,
        },
        "artifacts": {
            "manifest_path": _relative_path(manifest_path),
            "snapshot_path": manifest["data"]["snapshot_path"],
            "snapshot_sha256": manifest["data"]["snapshot_sha256"],
            "source_artifacts": manifest["data"].get("source_artifacts") or [],
            "champion_packet_path": packet_path_text or None,
            "champion_packet_preview": packet_payload.get("diagnostics", {}).get("sample_predictions") if packet_payload else None,
        },
    }


def write_market_policy_handoff(
    *,
    market_latest_path: str | Path = DEFAULT_MARKET_LATEST_JSON,
    output_path: str | Path = DEFAULT_MARKET_POLICY_HANDOFF,
) -> dict[str, Any]:
    payload = market_policy_handoff_payload(market_latest_path=market_latest_path)
    target = _resolve_path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def load_market_policy_handoff(
    *,
    handoff_path: str | Path = DEFAULT_MARKET_POLICY_HANDOFF,
    market_latest_path: str | Path = DEFAULT_MARKET_LATEST_JSON,
) -> dict[str, Any]:
    handoff_file = _resolve_path(handoff_path)
    if handoff_file.exists():
        payload = _load_json(handoff_file)
        if payload:
            return payload
    return market_policy_handoff_payload(market_latest_path=market_latest_path)


def evaluate_runtime_package_against_market(
    runtime_package: dict[str, Any] | None,
    *,
    handoff_path: str | Path = DEFAULT_MARKET_POLICY_HANDOFF,
    market_latest_path: str | Path = DEFAULT_MARKET_LATEST_JSON,
) -> dict[str, Any]:
    runtime_package = runtime_package if isinstance(runtime_package, dict) else {}
    handoff = load_market_policy_handoff(handoff_path=handoff_path, market_latest_path=market_latest_path)
    market_champion = handoff.get("market_champion") if isinstance(handoff.get("market_champion"), dict) else {}
    if not market_champion.get("candidate_path"):
        raise ValueError("market policy handoff missing market champion candidate_path")
    market_model_version = str(
        handoff.get("market_model_version")
        or (
            f"{market_champion.get('id')}:{market_champion.get('candidate_hash')}"
            if market_champion.get("id") is not None or market_champion.get("candidate_hash")
            else handoff.get("market_epoch_id")
        )
        or ""
    ).strip()

    manifest_path = _resolve_path((handoff.get("artifacts") or {}).get("manifest_path") or market_benchmark.DEFAULT_MANIFEST_PATH)
    manifest = market_benchmark.load_manifest(manifest_path)
    market_benchmark.verify_manifest(manifest)
    snapshot_path = _resolve_path(manifest["data"]["snapshot_path"])
    rows = market_benchmark._load_snapshot_rows(snapshot_path)  # type: ignore[attr-defined]
    warmup_rows, holdout_rows = market_benchmark.split_rows(rows, manifest)
    candidate_module = market_benchmark._load_candidate_module(  # type: ignore[attr-defined]
        _resolve_path(market_champion["candidate_path"])
    )
    feature_fields = list(manifest["data"]["feature_fields"])
    model = candidate_module.fit_market_model(
        warmup_rows,
        feature_fields=feature_fields,
        seed=int(manifest["replay"].get("fit_seed", 0)),
    )

    package = _normalized_runtime_package(runtime_package)
    horizon_days = int(((handoff.get("policy_benchmark") or {}).get("horizon_days") or POLICY_30D_HORIZON_DAYS))
    benchmark_rows = max(1, int(manifest["epoch"].get("benchmark_rows") or len(holdout_rows)))
    epoch_hours_actual = max(1e-9, safe_float(manifest["epoch"].get("epoch_length_hours_actual"), 24.0))
    rows_per_day = benchmark_rows / (epoch_hours_actual / 24.0)
    path_length = max(benchmark_rows, int(round(rows_per_day * float(horizon_days))))
    seeds = list(manifest["replay"].get("seed_list") or [])
    block_size = max(1, int(manifest["replay"].get("block_size") or 1))
    loss_limit_return_pct = safe_float(
        ((handoff.get("policy_benchmark") or {}).get("loss_limit_return_pct")),
        POLICY_LOSS_LIMIT_RETURN_PCT,
    )

    row_returns_pct: list[float] = []
    row_fill_probabilities: list[float] = []
    activation_flags: list[bool] = []
    preview_rows: list[dict[str, Any]] = []
    for row in holdout_rows:
        candidate_row = {"window_start_ts": row["window_start_ts"], "slug": row["slug"]}
        for field in feature_fields:
            candidate_row[field] = row.get(field)
        prediction = candidate_module.predict_market_row(model, candidate_row, feature_fields=feature_fields)
        active = runtime_package_matches_row(candidate_row, package)
        fill_rate = _clamp(safe_float(prediction.get("fill_rate"), 0.0), 0.0, 1.0)
        pnl_pct = _clamp(safe_float(prediction.get("pnl_pct"), 0.0), -2.0, 2.0)
        realized_row_return_pct = (pnl_pct * 100.0) if active else 0.0
        row_returns_pct.append(realized_row_return_pct)
        row_fill_probabilities.append(fill_rate if active else 0.0)
        activation_flags.append(active)
        if len(preview_rows) < 5:
            preview_rows.append(
                {
                    "slug": row.get("slug"),
                    "direction": row.get("direction"),
                    "session_name": row.get("session_name"),
                    "order_price": row.get("order_price"),
                    "active": active,
                    "predicted_fill_rate": round(fill_rate, 4),
                    "predicted_pnl_pct": round(pnl_pct, 4),
                    "projected_row_return_pct": round(realized_row_return_pct, 4),
                }
            )

    total_expected_fills_per_epoch = sum(row_fill_probabilities)
    expected_fills_per_day = total_expected_fills_per_epoch / (epoch_hours_actual / 24.0)
    active_row_ratio = sum(1 for value in activation_flags if value) / float(len(activation_flags) or 1)
    fill_retention_ratio = 1.0

    path_returns: list[float] = []
    path_drawdowns: list[float] = []
    path_expected_fills: list[float] = []
    loss_hits = 0
    non_positive_paths = 0
    for seed in seeds or [0]:
        indices = _bootstrap_indices(len(row_returns_pct), seed=int(seed), path_length=path_length, block_size=block_size)
        sampled_returns = [row_returns_pct[index] for index in indices]
        sampled_fills = [row_fill_probabilities[index] for index in indices]
        total_return_pct = sum(sampled_returns)
        drawdown_pct = _max_drawdown_pct(sampled_returns)
        if total_return_pct <= 0.0:
            non_positive_paths += 1
        if min(0.0, total_return_pct) <= -abs(loss_limit_return_pct) or _max_drawdown_pct(sampled_returns) >= abs(loss_limit_return_pct):
            loss_hits += 1
        path_returns.append(total_return_pct)
        path_drawdowns.append(drawdown_pct)
        path_expected_fills.append(sum(sampled_fills))

    holdout_row_count = max(1, len(holdout_rows))
    fold_results: list[dict[str, Any]] = []
    for fold_index, (start, end) in enumerate(_contiguous_fold_ranges(holdout_row_count, POLICY_FOLD_COUNT), start=1):
        fold_rows = holdout_rows[start:end]
        fold_returns = row_returns_pct[start:end]
        fold_fills = row_fill_probabilities[start:end]
        fold_activations = activation_flags[start:end]
        if not fold_rows:
            continue
        fold_ratio = len(fold_rows) / float(holdout_row_count)
        fold_epoch_hours = max(1e-9, epoch_hours_actual * fold_ratio)
        fold_rows_per_day = len(fold_rows) / (fold_epoch_hours / 24.0)
        fold_path_length = max(1, int(round(path_length * fold_ratio)))
        fold_path_returns: list[float] = []
        fold_path_drawdowns: list[float] = []
        fold_path_expected_fills: list[float] = []
        fold_loss_hits = 0
        fold_non_positive_paths = 0
        for seed in seeds or [0]:
            indices = _bootstrap_indices(
                len(fold_returns),
                seed=int(seed) + (fold_index * 10_000),
                path_length=fold_path_length,
                block_size=min(block_size, len(fold_returns)),
            )
            sampled_returns = [fold_returns[index] for index in indices]
            sampled_fills = [fold_fills[index] for index in indices]
            total_return_pct = sum(sampled_returns)
            drawdown_pct = _max_drawdown_pct(sampled_returns)
            if total_return_pct <= 0.0:
                fold_non_positive_paths += 1
            if min(0.0, total_return_pct) <= -abs(loss_limit_return_pct) or drawdown_pct >= abs(loss_limit_return_pct):
                fold_loss_hits += 1
            fold_path_returns.append(total_return_pct)
            fold_path_drawdowns.append(drawdown_pct)
            fold_path_expected_fills.append(sum(sampled_fills))
        fold_components = policy_loss_components(
            p05_30d_return_pct=_percentile(fold_path_returns, 5.0),
            median_30d_return_pct=_percentile(fold_path_returns, 50.0),
            loss_limit_hit_probability=(fold_loss_hits / float(len(fold_path_returns) or 1)),
            non_positive_path_probability=(fold_non_positive_paths / float(len(fold_path_returns) or 1)),
            p95_drawdown_pct=_percentile(fold_path_drawdowns, 95.0),
            fill_retention_ratio=fill_retention_ratio,
        )
        fold_results.append(
            {
                "fold_id": f"fold_{fold_index}",
                "fold_index": fold_index,
                "row_count": len(fold_rows),
                "start_ts": fold_rows[0].get("window_start_ts"),
                "end_ts": fold_rows[-1].get("window_start_ts"),
                "start_slug": fold_rows[0].get("slug"),
                "end_slug": fold_rows[-1].get("slug"),
                "market_model_version": market_model_version or None,
                "policy_loss": round(safe_float(fold_components.get("policy_loss"), 0.0) or 0.0, 4),
                "p05_30d_return_pct": round(safe_float(fold_components.get("p05_30d_return_pct"), 0.0) or 0.0, 4),
                "median_30d_return_pct": round(safe_float(fold_components.get("median_30d_return_pct"), 0.0) or 0.0, 4),
                "loss_limit_hit_probability": round(
                    safe_float(fold_components.get("loss_limit_hit_probability"), 0.0) or 0.0,
                    6,
                ),
                "non_positive_path_probability": round(
                    safe_float(fold_components.get("non_positive_path_probability"), 0.0) or 0.0,
                    6,
                ),
                "p95_drawdown_pct": round(safe_float(fold_components.get("p95_drawdown_pct"), 0.0) or 0.0, 4),
                "fill_retention_ratio": round(safe_float(fold_components.get("fill_retention_ratio"), 1.0) or 1.0, 4),
                "expected_fills_per_day": round(sum(fold_fills) / (fold_epoch_hours / 24.0), 4),
                "expected_fill_count_30d": round(
                    sum(fold_path_expected_fills) / float(len(fold_path_expected_fills) or 1),
                    4,
                ),
                "active_row_ratio": round(sum(1 for flag in fold_activations if flag) / float(len(fold_activations) or 1), 4),
                "paths": len(fold_path_returns),
            }
        )

    components = policy_loss_components(
        p05_30d_return_pct=_percentile(path_returns, 5.0),
        median_30d_return_pct=_percentile(path_returns, 50.0),
        loss_limit_hit_probability=(loss_hits / float(len(path_returns) or 1)),
        non_positive_path_probability=(non_positive_paths / float(len(path_returns) or 1)),
        p95_drawdown_pct=_percentile(path_drawdowns, 95.0),
        fill_retention_ratio=fill_retention_ratio,
    )
    fold_policy_losses = [safe_float(item.get("policy_loss"), 0.0) or 0.0 for item in fold_results]
    fold_ci_low, fold_ci_high = _bootstrap_mean_ci(
        fold_policy_losses,
        seed=int(manifest["replay"].get("fit_seed", 0)) + 42,
    )
    return {
        "policy_benchmark_id": POLICY_BENCHMARK_ID,
        "policy_loss_contract_version": POLICY_LOSS_CONTRACT_VERSION,
        "policy_loss_formula": POLICY_LOSS_FORMULA,
        "evaluation_source": POLICY_EVALUATION_SOURCE,
        "market_epoch_id": handoff.get("market_epoch_id"),
        "market_model_version": market_model_version or None,
        "simulator_champion_id": market_champion.get("id"),
        "simulator_candidate_hash": market_champion.get("candidate_hash"),
        "simulator_model_name": market_champion.get("candidate_model_name"),
        "runtime_package": package,
        "runtime_package_id": runtime_package_id(package),
        "runtime_package_hash": runtime_package_hash(package),
        "market_handoff": {
            "path": _relative_path(handoff_path if _resolve_path(handoff_path).exists() else market_latest_path),
            "is_fresh": _safe_bool(((handoff.get("market_latest") or {}).get("is_fresh"))),
            "age_seconds": safe_float(((handoff.get("market_latest") or {}).get("age_seconds")), None),
            "epoch_active": _safe_bool(handoff.get("market_epoch_active")),
            "market_model_version": market_model_version or None,
        },
        "market_context": {
            "manifest_path": _relative_path(manifest_path),
            "snapshot_path": manifest["data"]["snapshot_path"],
            "feature_fields": feature_fields,
            "benchmark_rows": benchmark_rows,
            "epoch_hours_actual": round(epoch_hours_actual, 4),
            "policy_horizon_days": horizon_days,
            "bootstrap_paths": len(path_returns),
            "path_length_rows": path_length,
            "block_size_rows": block_size,
            "loss_limit_return_pct": loss_limit_return_pct,
        },
        "policy_benchmark": {
            **components,
            "expected_fills_per_day": round(expected_fills_per_day, 4),
            "expected_fill_count_30d": round(sum(path_expected_fills) / float(len(path_expected_fills) or 1), 4),
            "active_row_ratio": round(active_row_ratio, 4),
            "paths": len(path_returns),
            "fold_count": len(fold_results),
        },
        "fold_results": fold_results,
        "confidence_summary": {
            "fold_count": len(fold_results),
            "mean_fold_policy_loss": round(_mean(fold_policy_losses), 4),
            "bootstrap_mean_fold_policy_loss_ci_low": round(fold_ci_low, 4),
            "bootstrap_mean_fold_policy_loss_ci_high": round(fold_ci_high, 4),
            "confidence_method": "bootstrap_mean_fold_policy_loss_v1",
        },
        "preview_rows": preview_rows,
    }
