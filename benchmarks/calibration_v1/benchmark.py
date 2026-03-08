"""Frozen evaluator for the calibration autoresearch lane."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.adaptive_platt import (  # noqa: E402
    DEFAULT_ECE_BINS,
    DEFAULT_MIN_OBSERVATIONS,
    STATIC_PLATT_A,
    STATIC_PLATT_B,
    ResolvedExample,
    brier_score,
    calibrate_probability_with_params,
    expanding_platt_fit,
    expected_calibration_error,
    load_resolved_examples_from_cache,
    log_loss_score,
    rolling_platt_fit,
)


DEFAULT_VARIANTS = ("static", "expanding", "rolling_100", "rolling_200")
DEFAULT_MAX_ITER = 1_000
DEFAULT_C_VALUE = 1_000.0


@dataclass(frozen=True)
class HoldoutVariantMetrics:
    name: str
    window: int | None
    n_predictions: int
    brier: float
    ece: float
    log_loss: float
    benchmark_score: float
    fallback_predictions: int
    final_a: float
    final_b: float


def load_manifest(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def manifest_path(path_value: str) -> Path:
    return ROOT / path_value


def sha256_file(path: str | Path) -> str:
    return sha256(Path(path).read_bytes()).hexdigest()


def verify_manifest(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    data = manifest["data"]
    for key in ("markets_path", "cache_path"):
        path = manifest_path(data[key])
        expected = data[f"{key.split('_path', 1)[0]}_sha256"]
        observed = sha256_file(path)
        if observed != expected:
            raise ValueError(f"checksum mismatch for {path}: expected {expected}, observed {observed}")
        checks.append({"path": str(path.relative_to(ROOT)), "sha256": observed})
    return checks


def load_benchmark_rows(manifest: dict[str, Any]) -> list[ResolvedExample]:
    rows = load_resolved_examples_from_cache(
        manifest_path(manifest["data"]["markets_path"]),
        manifest_path(manifest["data"]["cache_path"]),
    )
    expected_rows = int(manifest["split"]["total_rows"])
    if len(rows) != expected_rows:
        raise ValueError(f"expected {expected_rows} benchmark rows, found {len(rows)}")
    return rows


def split_rows(
    rows: list[ResolvedExample],
    manifest: dict[str, Any],
) -> tuple[list[ResolvedExample], list[ResolvedExample]]:
    warmup_rows = int(manifest["split"]["warmup_rows"])
    holdout_rows = int(manifest["split"]["holdout_rows"])
    warmup = rows[:warmup_rows]
    holdout = rows[warmup_rows : warmup_rows + holdout_rows]
    if len(warmup) != warmup_rows or len(holdout) != holdout_rows:
        raise ValueError("manifest split does not match dataset shape")
    if warmup and warmup[-1].resolved_at != manifest["split"]["warmup_end_resolved_at"]:
        raise ValueError("warmup split boundary drifted from manifest")
    if holdout and holdout[0].resolved_at != manifest["split"]["holdout_start_resolved_at"]:
        raise ValueError("holdout split boundary drifted from manifest")
    return warmup, holdout


def evaluate_holdout_variant(
    warmup_rows: list[ResolvedExample],
    holdout_rows: list[ResolvedExample],
    *,
    variant_name: str,
    min_samples: int = DEFAULT_MIN_OBSERVATIONS,
    ece_bins: int = DEFAULT_ECE_BINS,
    max_iter: int = DEFAULT_MAX_ITER,
    c_value: float = DEFAULT_C_VALUE,
    static_a: float = STATIC_PLATT_A,
    static_b: float = STATIC_PLATT_B,
) -> HoldoutVariantMetrics:
    predictions: list[float] = []
    outcomes: list[int] = []
    fallback_predictions = 0
    final_a = float(static_a)
    final_b = float(static_b)

    for idx, current in enumerate(holdout_rows):
        history = [*warmup_rows, *holdout_rows[:idx]]
        final_a, final_b, fallback = _fit_variant(
            history,
            variant_name=variant_name,
            min_samples=min_samples,
            max_iter=max_iter,
            c_value=c_value,
            static_a=static_a,
            static_b=static_b,
        )
        if fallback:
            fallback_predictions += 1
        predictions.append(calibrate_probability_with_params(current.raw_prob, final_a, final_b))
        outcomes.append(int(current.outcome))

    window = None
    if variant_name.startswith("rolling_"):
        window = int(variant_name.split("_", 1)[1])

    brier = round(brier_score(predictions, outcomes), 6)
    ece = round(expected_calibration_error(predictions, outcomes, bins=ece_bins), 6)
    log_loss = round(log_loss_score(predictions, outcomes), 6)
    benchmark_score = round(-(brier + (0.25 * ece)), 6)
    return HoldoutVariantMetrics(
        name=variant_name,
        window=window,
        n_predictions=len(predictions),
        brier=brier,
        ece=ece,
        log_loss=log_loss,
        benchmark_score=benchmark_score,
        fallback_predictions=fallback_predictions,
        final_a=round(final_a, 6),
        final_b=round(final_b, 6),
    )


def run_benchmark(
    manifest_path_value: str | Path,
    *,
    description: str = "",
    variants: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    manifest_file = Path(manifest_path_value)
    if not manifest_file.is_absolute():
        manifest_file = ROOT / manifest_file
    manifest = load_manifest(manifest_file)
    checksum_rows = verify_manifest(manifest)
    rows = load_benchmark_rows(manifest)
    warmup_rows, holdout_rows = split_rows(rows, manifest)
    evaluator = manifest["evaluator"]
    variant_names = tuple(evaluator.get("candidate_variants") or variants or DEFAULT_VARIANTS)

    variant_metrics = [
        evaluate_holdout_variant(
            warmup_rows,
            holdout_rows,
            variant_name=name,
            min_samples=int(evaluator.get("min_samples", DEFAULT_MIN_OBSERVATIONS)),
            ece_bins=int(evaluator.get("ece_bins", DEFAULT_ECE_BINS)),
            max_iter=int(evaluator.get("max_iter", DEFAULT_MAX_ITER)),
            c_value=float(evaluator.get("c_value", DEFAULT_C_VALUE)),
        )
        for name in variant_names
    ]
    selected = max(variant_metrics, key=lambda row: row.benchmark_score)
    static_variant = next(row for row in variant_metrics if row.name == "static")

    return {
        "benchmark_id": manifest["benchmark_id"],
        "generated_at": utc_now_iso(),
        "description": description.strip(),
        "manifest_path": str(manifest_file.relative_to(ROOT)),
        "mutable_surface": manifest["mutable_surface"],
        "mutable_surface_sha256": sha256_file(manifest_path(manifest["mutable_surface"])),
        "git": git_metadata(),
        "objective": manifest["objective"],
        "dataset": {
            "markets_path": manifest["data"]["markets_path"],
            "cache_path": manifest["data"]["cache_path"],
            "source": "claude_cache",
            "checksums": checksum_rows,
            "total_rows": len(rows),
            "warmup_rows": len(warmup_rows),
            "holdout_rows": len(holdout_rows),
            "warmup_end_resolved_at": manifest["split"]["warmup_end_resolved_at"],
            "holdout_start_resolved_at": manifest["split"]["holdout_start_resolved_at"],
            "missing_resolved_at_rows": sum(1 for row in rows if not row.resolved_at),
        },
        "selected_variant": asdict(selected),
        "variants": [asdict(row) for row in variant_metrics],
        "comparison": {
            "improvement_vs_static": round(selected.benchmark_score - static_variant.benchmark_score, 6),
            "selected_variant": selected.name,
        },
        "diagnostics": {
            "confidence_bands": confidence_band_drift(warmup_rows, holdout_rows, selected.name, manifest),
        },
    }


def default_artifact_paths(output_dir: str | Path, slug: str | None = None) -> tuple[Path, Path]:
    base_dir = Path(output_dir)
    base_dir.mkdir(parents=True, exist_ok=True)
    stamp = slug.strip() if slug else datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return base_dir / f"{stamp}.json", base_dir / f"{stamp}.md"


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
    json_file.write_text(json.dumps(packet, indent=2, sort_keys=True), encoding="utf-8")
    summary_file.write_text(render_summary_markdown(packet), encoding="utf-8")
    return {"json_path": str(json_file), "summary_path": str(summary_file)}


def render_summary_markdown(packet: dict[str, Any]) -> str:
    selected = packet["selected_variant"]
    lines = [
        "# Calibration Benchmark Packet",
        "",
        f"- Benchmark: `{packet['benchmark_id']}`",
        f"- Generated at: {packet['generated_at']}",
        f"- Mutable surface: `{packet['mutable_surface']}`",
        f"- Working tree dirty: {packet['git']['dirty']}",
        f"- Git SHA: `{packet['git']['sha']}`",
        f"- Holdout rows: {packet['dataset']['holdout_rows']}",
        f"- Selected variant: `{selected['name']}`",
        f"- Benchmark score: {selected['benchmark_score']:.6f}",
        f"- Brier: {selected['brier']:.6f}",
        f"- ECE: {selected['ece']:.6f}",
        f"- Log loss: {selected['log_loss']:.6f}",
        "",
        "Calibration benchmark wins are research artifacts. They do not imply paper, shadow, or live trading readiness.",
        "",
        "## Variant Results",
        "",
        "| Variant | Window | Predictions | Fallbacks | Benchmark Score | Brier | ECE | Log Loss |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for variant in packet["variants"]:
        window = variant["window"] if variant["window"] is not None else "all"
        if variant["name"] == "static":
            window = "static"
        lines.append(
            f"| {variant['name']} | {window} | {variant['n_predictions']} | "
            f"{variant['fallback_predictions']} | {variant['benchmark_score']:.6f} | "
            f"{variant['brier']:.6f} | {variant['ece']:.6f} | {variant['log_loss']:.6f} |"
        )

    lines.extend(
        [
            "",
            "## Confidence Bands",
            "",
            "| Band | Count | Avg Confidence | Win Rate | Abs Gap |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for band in packet["diagnostics"]["confidence_bands"]:
        lines.append(
            f"| {band['label']} | {band['count']} | {band['avg_confidence']:.4f} | "
            f"{band['win_rate']:.4f} | {band['abs_gap']:.4f} |"
        )
    return "\n".join(lines) + "\n"


def confidence_band_drift(
    warmup_rows: list[ResolvedExample],
    holdout_rows: list[ResolvedExample],
    variant_name: str,
    manifest: dict[str, Any],
) -> list[dict[str, Any]]:
    evaluator = manifest["evaluator"]
    min_samples = int(evaluator.get("min_samples", DEFAULT_MIN_OBSERVATIONS))
    ece_bins = int(evaluator.get("ece_bins", DEFAULT_ECE_BINS))
    max_iter = int(evaluator.get("max_iter", DEFAULT_MAX_ITER))
    c_value = float(evaluator.get("c_value", DEFAULT_C_VALUE))

    predictions: list[float] = []
    outcomes: list[int] = []
    for idx, current in enumerate(holdout_rows):
        history = [*warmup_rows, *holdout_rows[:idx]]
        a_value, b_value, _ = _fit_variant(
            history,
            variant_name=variant_name,
            min_samples=min_samples,
            max_iter=max_iter,
            c_value=c_value,
            static_a=STATIC_PLATT_A,
            static_b=STATIC_PLATT_B,
        )
        predictions.append(calibrate_probability_with_params(current.raw_prob, a_value, b_value))
        outcomes.append(int(current.outcome))

    rows: list[dict[str, Any]] = []
    for idx in range(ece_bins):
        lower = idx / ece_bins
        upper = (idx + 1) / ece_bins
        members = [
            pos
            for pos, prediction in enumerate(predictions)
            if (lower <= prediction < upper) or (idx == ece_bins - 1 and lower <= prediction <= upper)
        ]
        if not members:
            continue
        avg_confidence = sum(predictions[pos] for pos in members) / len(members)
        win_rate = sum(outcomes[pos] for pos in members) / len(members)
        rows.append(
            {
                "label": f"{lower:.1f}-{upper:.1f}",
                "count": len(members),
                "avg_confidence": round(avg_confidence, 6),
                "win_rate": round(win_rate, 6),
                "abs_gap": round(abs(avg_confidence - win_rate), 6),
            }
        )
    return rows


def git_metadata() -> dict[str, Any]:
    sha = git_command("rev-parse", "HEAD") or "unknown"
    dirty = bool(git_command("status", "--short"))
    branch = git_command("branch", "--show-current") or "unknown"
    return {"sha": sha, "branch": branch, "dirty": dirty}


def git_command(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return ""
    return result.stdout.strip()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _fit_variant(
    history: list[ResolvedExample],
    *,
    variant_name: str,
    min_samples: int,
    max_iter: int,
    c_value: float,
    static_a: float,
    static_b: float,
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
        raise ValueError(f"unsupported variant: {variant_name}")
    fallback = params == (float(static_a), float(static_b)) and len(history) < int(min_samples)
    return float(params[0]), float(params[1]), fallback
