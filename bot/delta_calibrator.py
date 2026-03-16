#!/usr/bin/env python3
"""Adaptive delta calibrator for multi-asset 5m maker bots.

This module calibrates BTC5_MAX_ABS_DELTA and BTC5_MIN_DELTA from recent trade
history with two signals:

1) Realized-volatility regime (recent absolute delta distribution)
2) Profitability-by-delta-band (which delta ranges are actually making money)

It applies calibration per asset so ETH/SOL/BNB/DOGE/XRP can diverge from BTC.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ASSET_ORDER: tuple[str, ...] = ("btc", "eth", "sol", "bnb", "doge", "xrp")

DEFAULT_ASSET_DB_PATHS: dict[str, Path] = {
    "btc": Path("data/btc_5min_maker.db"),
    "eth": Path("data/eth_5min_maker.db"),
    "sol": Path("data/sol_5min_maker.db"),
    "bnb": Path("data/bnb_5min_maker.db"),
    "doge": Path("data/doge_5min_maker.db"),
    "xrp": Path("data/xrp_5min_maker.db"),
}

DEFAULT_ASSET_ENV_PATHS: dict[str, Path] = {
    "btc": Path("config/btc5_strategy.env"),
    "eth": Path("config/eth5_strategy.env"),
    "sol": Path("config/sol5_strategy.env"),
    "bnb": Path("config/bnb5_strategy.env"),
    "doge": Path("config/doge5_strategy.env"),
    "xrp": Path("config/xrp5_strategy.env"),
}

DEFAULT_STAGE_ENV_PATH = Path("state/btc5_capital_stage.env")
DEFAULT_REPORT_PATH = Path("data/delta_calibration_report.json")

# Safety bounds for delta controls.
MIN_MAX_ABS_DELTA = 0.0005
MAX_MAX_ABS_DELTA = 0.02
MIN_MIN_DELTA = 0.00005
MAX_MIN_DELTA = 0.004


@dataclass(frozen=True)
class FillObservation:
    abs_delta: float
    pnl_usd: float
    won: int


@dataclass(frozen=True)
class BucketStats:
    lower: float
    upper: float
    fills: int
    wins: int
    total_pnl_usd: float
    win_rate: float


@dataclass(frozen=True)
class AssetCalibration:
    asset: str
    db_path: str
    rows_considered: int
    fills_considered: int
    current_max_abs_delta: float | None
    current_min_delta: float | None
    volatility_q80: float | None
    volatility_target_max_abs_delta: float | None
    profitable_band_lower: float | None
    profitable_band_upper: float | None
    profitability_target_max_abs_delta: float | None
    recommended_max_abs_delta: float | None
    recommended_min_delta: float | None
    recommended_probe_max_abs_delta: float | None
    status: str
    reason: str
    profitable_buckets: list[BucketStats]


def _iso_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _round_env_float(value: float) -> float:
    # Keep env values readable while preserving enough precision.
    return float(f"{value:.6f}")


def _format_env_float(value: float) -> str:
    return f"{_round_env_float(value):.6f}".rstrip("0").rstrip(".")


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return float(values[0])
    q = _clamp(float(q), 0.0, 1.0)
    sorted_vals = sorted(values)
    pos = (len(sorted_vals) - 1) * q
    lower = int(math.floor(pos))
    upper = int(math.ceil(pos))
    if lower == upper:
        return float(sorted_vals[lower])
    frac = pos - lower
    return float(sorted_vals[lower] * (1.0 - frac) + sorted_vals[upper] * frac)


def _parse_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        values[key] = value.strip()
    return values


def _upsert_env_values(path: Path, updates: dict[str, str], *, header_comment: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    original_lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    out_lines: list[str] = []
    seen: set[str] = set()

    if not original_lines and header_comment:
        out_lines.append(f"# {header_comment}")
        out_lines.append(f"# generated_at={_iso_utc_now()}")

    for raw_line in original_lines:
        if "=" not in raw_line or raw_line.lstrip().startswith("#"):
            out_lines.append(raw_line)
            continue
        key, _value = raw_line.split("=", 1)
        key = key.strip()
        if key in updates:
            out_lines.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            out_lines.append(raw_line)

    for key in sorted(updates):
        if key not in seen:
            out_lines.append(f"{key}={updates[key]}")

    path.write_text("\n".join(out_lines).rstrip() + "\n", encoding="utf-8")


def _select_recent_abs_deltas(conn: sqlite3.Connection, *, max_rows: int) -> list[float]:
    sql = """
        SELECT ABS(CAST(delta AS REAL)) AS abs_delta
        FROM window_trades
        WHERE delta IS NOT NULL
          AND ABS(CAST(delta AS REAL)) > 0
        ORDER BY rowid DESC
        LIMIT ?
    """
    rows = conn.execute(sql, (int(max_rows),)).fetchall()
    return [float(row["abs_delta"]) for row in rows if _safe_float(row["abs_delta"]) is not None]


def _coerce_won(won_value: Any, *, pnl_usd: float) -> int:
    if isinstance(won_value, bool):
        return 1 if won_value else 0
    if isinstance(won_value, (int, float)):
        return 1 if float(won_value) > 0 else 0
    text = str(won_value or "").strip().lower()
    if text in {"won", "win", "true", "t", "yes", "y", "1"}:
        return 1
    if text in {"lost", "lose", "false", "f", "no", "n", "0"}:
        return 0
    return 1 if pnl_usd > 0 else 0


def _select_recent_fills(conn: sqlite3.Connection, *, max_rows: int) -> list[FillObservation]:
    sql = """
        SELECT
            ABS(CAST(delta AS REAL)) AS abs_delta,
            CAST(COALESCE(pnl_usd, 0) AS REAL) AS pnl_usd,
            won
        FROM window_trades
        WHERE delta IS NOT NULL
          AND ABS(CAST(delta AS REAL)) > 0
          AND (
            LOWER(COALESCE(order_status, '')) LIKE '%filled%'
            OR LOWER(COALESCE(order_status, '')) = 'live_partial_fill_cancelled'
          )
        ORDER BY rowid DESC
        LIMIT ?
    """
    rows = conn.execute(sql, (int(max_rows),)).fetchall()
    observations: list[FillObservation] = []
    for row in rows:
        abs_delta = _safe_float(row["abs_delta"])
        pnl_usd = _safe_float(row["pnl_usd"])
        if abs_delta is None or pnl_usd is None:
            continue
        observations.append(
            FillObservation(
                abs_delta=float(abs_delta),
                pnl_usd=float(pnl_usd),
                won=_coerce_won(row["won"], pnl_usd=float(pnl_usd)),
            )
        )
    return observations


def _bucketize_fills(
    fills: list[FillObservation],
    *,
    bucket_width: float,
    min_bin_fills: int,
    min_bin_win_rate: float,
) -> list[BucketStats]:
    if not fills:
        return []
    buckets: dict[float, dict[str, float]] = {}
    width = max(bucket_width, 1e-6)
    for fill in fills:
        lower = math.floor(fill.abs_delta / width) * width
        upper = lower + width
        acc = buckets.setdefault(lower, {"fills": 0.0, "wins": 0.0, "pnl": 0.0, "upper": upper})
        acc["fills"] += 1.0
        acc["wins"] += float(fill.won)
        acc["pnl"] += float(fill.pnl_usd)

    profitable: list[BucketStats] = []
    for lower in sorted(buckets):
        acc = buckets[lower]
        fills_n = int(acc["fills"])
        if fills_n < int(min_bin_fills):
            continue
        wins = int(acc["wins"])
        total_pnl = float(acc["pnl"])
        win_rate = wins / fills_n if fills_n > 0 else 0.0
        if total_pnl <= 0:
            continue
        if win_rate < float(min_bin_win_rate):
            continue
        profitable.append(
            BucketStats(
                lower=float(lower),
                upper=float(acc["upper"]),
                fills=fills_n,
                wins=wins,
                total_pnl_usd=total_pnl,
                win_rate=win_rate,
            )
        )
    return profitable


def _pick_profitable_band(
    profitable_buckets: list[BucketStats],
    *,
    bucket_width: float,
) -> tuple[float | None, float | None]:
    if not profitable_buckets:
        return None, None
    by_lower = {bucket.lower: bucket for bucket in profitable_buckets}
    sorted_lowers = sorted(by_lower)
    center = max(
        profitable_buckets,
        key=lambda bucket: (bucket.total_pnl_usd, bucket.win_rate, bucket.fills),
    )
    center_idx = sorted_lowers.index(center.lower)
    selected = {center.lower}

    idx = center_idx - 1
    while idx >= 0:
        cur = sorted_lowers[idx]
        nxt = sorted_lowers[idx + 1]
        if abs(nxt - cur - bucket_width) > max(bucket_width * 0.05, 1e-6):
            break
        selected.add(cur)
        idx -= 1

    idx = center_idx + 1
    while idx < len(sorted_lowers):
        prev = sorted_lowers[idx - 1]
        cur = sorted_lowers[idx]
        if abs(cur - prev - bucket_width) > max(bucket_width * 0.05, 1e-6):
            break
        selected.add(cur)
        idx += 1

    lower = min(selected)
    upper = max(selected) + bucket_width
    return float(lower), float(upper)


def calibrate_asset(
    *,
    asset: str,
    db_path: Path,
    current_max_abs_delta: float | None,
    current_min_delta: float | None,
    max_fill_rows: int,
    max_window_rows: int,
    min_fill_rows: int,
    min_bin_fills: int,
    min_bin_win_rate: float,
    vol_multiplier: float,
) -> AssetCalibration:
    if not db_path.exists():
        return AssetCalibration(
            asset=asset,
            db_path=str(db_path),
            rows_considered=0,
            fills_considered=0,
            current_max_abs_delta=current_max_abs_delta,
            current_min_delta=current_min_delta,
            volatility_q80=None,
            volatility_target_max_abs_delta=None,
            profitable_band_lower=None,
            profitable_band_upper=None,
            profitability_target_max_abs_delta=None,
            recommended_max_abs_delta=None,
            recommended_min_delta=None,
            recommended_probe_max_abs_delta=None,
            status="skipped",
            reason="db_missing",
            profitable_buckets=[],
        )

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        abs_deltas = _select_recent_abs_deltas(conn, max_rows=max_window_rows)
        fills = _select_recent_fills(conn, max_rows=max_fill_rows)
    except sqlite3.Error:
        conn.close()
        return AssetCalibration(
            asset=asset,
            db_path=str(db_path),
            rows_considered=0,
            fills_considered=0,
            current_max_abs_delta=current_max_abs_delta,
            current_min_delta=current_min_delta,
            volatility_q80=None,
            volatility_target_max_abs_delta=None,
            profitable_band_lower=None,
            profitable_band_upper=None,
            profitability_target_max_abs_delta=None,
            recommended_max_abs_delta=None,
            recommended_min_delta=None,
            recommended_probe_max_abs_delta=None,
            status="skipped",
            reason="query_failed",
            profitable_buckets=[],
        )
    finally:
        conn.close()

    vol_q80 = _quantile(abs_deltas, 0.80)
    if vol_q80 is None:
        return AssetCalibration(
            asset=asset,
            db_path=str(db_path),
            rows_considered=0,
            fills_considered=len(fills),
            current_max_abs_delta=current_max_abs_delta,
            current_min_delta=current_min_delta,
            volatility_q80=None,
            volatility_target_max_abs_delta=None,
            profitable_band_lower=None,
            profitable_band_upper=None,
            profitability_target_max_abs_delta=None,
            recommended_max_abs_delta=None,
            recommended_min_delta=None,
            recommended_probe_max_abs_delta=None,
            status="skipped",
            reason="no_delta_rows",
            profitable_buckets=[],
        )

    volatility_target = _clamp(vol_q80 * float(vol_multiplier), MIN_MAX_ABS_DELTA, MAX_MAX_ABS_DELTA)

    dynamic_width = max(0.0001, min(0.001, volatility_target / 6.0))
    profitable_buckets = _bucketize_fills(
        fills,
        bucket_width=dynamic_width,
        min_bin_fills=min_bin_fills,
        min_bin_win_rate=min_bin_win_rate,
    )
    band_lower, band_upper = _pick_profitable_band(profitable_buckets, bucket_width=dynamic_width)

    profitability_target: float | None = None
    if band_upper is not None:
        profitability_target = _clamp(band_upper * 1.08, MIN_MAX_ABS_DELTA, MAX_MAX_ABS_DELTA)

    if len(abs_deltas) < int(min_fill_rows):
        # Not enough windows to recalibrate; keep current values.
        return AssetCalibration(
            asset=asset,
            db_path=str(db_path),
            rows_considered=len(abs_deltas),
            fills_considered=len(fills),
            current_max_abs_delta=current_max_abs_delta,
            current_min_delta=current_min_delta,
            volatility_q80=vol_q80,
            volatility_target_max_abs_delta=volatility_target,
            profitable_band_lower=band_lower,
            profitable_band_upper=band_upper,
            profitability_target_max_abs_delta=profitability_target,
            recommended_max_abs_delta=current_max_abs_delta,
            recommended_min_delta=current_min_delta,
            recommended_probe_max_abs_delta=current_max_abs_delta,
            status="skipped",
            reason="insufficient_rows",
            profitable_buckets=profitable_buckets,
        )

    target_max = volatility_target if profitability_target is None else min(volatility_target, profitability_target)
    if current_max_abs_delta is not None and current_max_abs_delta > 0:
        max_up_step = max(0.0002, current_max_abs_delta * 0.25)
        max_down_step = max(0.0002, current_max_abs_delta * 0.35)
        delta_step = target_max - current_max_abs_delta
        if delta_step > max_up_step:
            target_max = current_max_abs_delta + max_up_step
        elif delta_step < -max_down_step:
            target_max = current_max_abs_delta - max_down_step

    target_max = _round_env_float(_clamp(target_max, MIN_MAX_ABS_DELTA, MAX_MAX_ABS_DELTA))

    if band_lower is not None:
        target_min = band_lower * 0.92
    else:
        q20 = _quantile(abs_deltas, 0.20) or MIN_MIN_DELTA
        target_min = q20 * 0.50
    target_min = _clamp(target_min, MIN_MIN_DELTA, min(MAX_MIN_DELTA, target_max * 0.85))
    target_min = _round_env_float(target_min)

    status = "updated"
    reason = "volatility_and_profitability"
    if profitability_target is None:
        reason = "volatility_only"

    return AssetCalibration(
        asset=asset,
        db_path=str(db_path),
        rows_considered=len(abs_deltas),
        fills_considered=len(fills),
        current_max_abs_delta=current_max_abs_delta,
        current_min_delta=current_min_delta,
        volatility_q80=vol_q80,
        volatility_target_max_abs_delta=volatility_target,
        profitable_band_lower=band_lower,
        profitable_band_upper=band_upper,
        profitability_target_max_abs_delta=profitability_target,
        recommended_max_abs_delta=target_max,
        recommended_min_delta=target_min,
        recommended_probe_max_abs_delta=target_max,
        status=status,
        reason=reason,
        profitable_buckets=profitable_buckets,
    )


def _merge_path_overrides(
    defaults: dict[str, Path],
    overrides: dict[str, Path] | None,
) -> dict[str, Path]:
    merged = dict(defaults)
    for asset, path in (overrides or {}).items():
        merged[asset.lower()] = path
    return merged


def _parse_key_value_pairs(values: list[str] | None, *, arg_name: str) -> dict[str, Path]:
    parsed: dict[str, Path] = {}
    for raw in values or []:
        if "=" not in raw:
            raise ValueError(f"{arg_name} entry must be asset=path, got: {raw!r}")
        asset, path = raw.split("=", 1)
        asset = asset.strip().lower()
        if not asset:
            raise ValueError(f"{arg_name} entry has empty asset: {raw!r}")
        parsed[asset] = Path(path.strip())
    return parsed


def run_calibration(
    *,
    state_env_path: Path = DEFAULT_STAGE_ENV_PATH,
    asset_db_paths: dict[str, Path] | None = None,
    asset_env_paths: dict[str, Path] | None = None,
    report_path: Path = DEFAULT_REPORT_PATH,
    dry_run: bool = False,
    max_fill_rows: int = 600,
    max_window_rows: int = 2000,
    min_fill_rows: int = 80,
    min_bin_fills: int = 4,
    min_bin_win_rate: float = 0.55,
    vol_multiplier: float = 1.35,
) -> dict[str, Any]:
    db_paths = _merge_path_overrides(DEFAULT_ASSET_DB_PATHS, asset_db_paths)
    env_paths = _merge_path_overrides(DEFAULT_ASSET_ENV_PATHS, asset_env_paths)
    stage_env = _parse_env_file(state_env_path)

    calibrations: list[AssetCalibration] = []
    for asset in ASSET_ORDER:
        db_path = db_paths.get(asset)
        if db_path is None:
            continue
        if not db_path.is_absolute():
            db_path = Path.cwd() / db_path

        current_env = stage_env if asset == "btc" else _parse_env_file(env_paths.get(asset, Path()))
        current_max = _safe_float(current_env.get("BTC5_MAX_ABS_DELTA"))
        current_min = _safe_float(current_env.get("BTC5_MIN_DELTA"))

        calibration = calibrate_asset(
            asset=asset,
            db_path=db_path,
            current_max_abs_delta=current_max,
            current_min_delta=current_min,
            max_fill_rows=max_fill_rows,
            max_window_rows=max_window_rows,
            min_fill_rows=min_fill_rows,
            min_bin_fills=min_bin_fills,
            min_bin_win_rate=min_bin_win_rate,
            vol_multiplier=vol_multiplier,
        )
        calibrations.append(calibration)

    writes: list[dict[str, str]] = []
    if not dry_run:
        for calibration in calibrations:
            if calibration.recommended_max_abs_delta is None or calibration.recommended_min_delta is None:
                continue
            updates = {
                "BTC5_MAX_ABS_DELTA": _format_env_float(calibration.recommended_max_abs_delta),
                "BTC5_PROBE_MAX_ABS_DELTA": _format_env_float(calibration.recommended_probe_max_abs_delta or calibration.recommended_max_abs_delta),
                "BTC5_MIN_DELTA": _format_env_float(calibration.recommended_min_delta),
            }

            if calibration.asset == "btc":
                _upsert_env_values(
                    state_env_path,
                    updates,
                    header_comment="state/btc5_capital_stage.env — delta calibrated",
                )
                writes.append({"asset": calibration.asset, "path": str(state_env_path)})
            else:
                env_path = env_paths.get(calibration.asset)
                if env_path is None:
                    continue
                if not env_path.is_absolute():
                    env_path = Path.cwd() / env_path
                _upsert_env_values(
                    env_path,
                    updates,
                    header_comment=f"{calibration.asset.upper()} 5m delta calibration overrides",
                )
                writes.append({"asset": calibration.asset, "path": str(env_path)})

    report_payload = {
        "generated_at": _iso_utc_now(),
        "dry_run": bool(dry_run),
        "state_env_path": str(state_env_path),
        "asset_db_paths": {asset: str(path) for asset, path in db_paths.items()},
        "asset_env_paths": {asset: str(path) for asset, path in env_paths.items()},
        "settings": {
            "max_fill_rows": int(max_fill_rows),
            "max_window_rows": int(max_window_rows),
            "min_fill_rows": int(min_fill_rows),
            "min_bin_fills": int(min_bin_fills),
            "min_bin_win_rate": float(min_bin_win_rate),
            "vol_multiplier": float(vol_multiplier),
            "bounds": {
                "min_max_abs_delta": MIN_MAX_ABS_DELTA,
                "max_max_abs_delta": MAX_MAX_ABS_DELTA,
                "min_min_delta": MIN_MIN_DELTA,
                "max_min_delta": MAX_MIN_DELTA,
            },
        },
        "writes": writes,
        "assets": [],
    }

    for calibration in calibrations:
        row = asdict(calibration)
        row["profitable_buckets"] = [asdict(bucket) for bucket in calibration.profitable_buckets]
        report_payload["assets"].append(row)

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report_payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--state-env",
        type=Path,
        default=DEFAULT_STAGE_ENV_PATH,
        help=f"Path to shared capital-stage env file (default: {DEFAULT_STAGE_ENV_PATH})",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        help=f"JSON report output path (default: {DEFAULT_REPORT_PATH})",
    )
    parser.add_argument(
        "--asset-db",
        action="append",
        default=[],
        help="Override DB path per asset as asset=path (repeatable).",
    )
    parser.add_argument(
        "--asset-env",
        action="append",
        default=[],
        help="Override strategy env path per asset as asset=path (repeatable).",
    )
    parser.add_argument("--max-fill-rows", type=int, default=600)
    parser.add_argument("--max-window-rows", type=int, default=2000)
    parser.add_argument("--min-fill-rows", type=int, default=80)
    parser.add_argument("--min-bin-fills", type=int, default=4)
    parser.add_argument("--min-bin-win-rate", type=float, default=0.55)
    parser.add_argument("--vol-multiplier", type=float, default=1.35)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        asset_db_overrides = _parse_key_value_pairs(args.asset_db, arg_name="--asset-db")
        asset_env_overrides = _parse_key_value_pairs(args.asset_env, arg_name="--asset-env")
    except ValueError as exc:
        parser.error(str(exc))
        return 2

    payload = run_calibration(
        state_env_path=args.state_env,
        asset_db_paths=asset_db_overrides,
        asset_env_paths=asset_env_overrides,
        report_path=args.report,
        dry_run=bool(args.dry_run),
        max_fill_rows=max(1, int(args.max_fill_rows)),
        max_window_rows=max(1, int(args.max_window_rows)),
        min_fill_rows=max(1, int(args.min_fill_rows)),
        min_bin_fills=max(1, int(args.min_bin_fills)),
        min_bin_win_rate=float(_clamp(args.min_bin_win_rate, 0.0, 1.0)),
        vol_multiplier=max(0.1, float(args.vol_multiplier)),
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
