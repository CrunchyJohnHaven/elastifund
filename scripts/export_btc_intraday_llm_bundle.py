#!/usr/bin/env python3
"""Export a BTC intraday analysis bundle for downstream LLM review."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests


REPO_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = REPO_ROOT / "reports"
DEFAULT_LOCAL_BTC5_DB = REPO_ROOT / "data" / "btc_5min_maker.db"
DEFAULT_REMOTE_BTC5_DB = REPORTS_DIR / "tmp_remote_btc_5min_maker.db"
DEFAULT_EDGE_DB = REPO_ROOT / "data" / "edge_discovery_locked.db"
DEFAULT_WALLET_DB = REPO_ROOT / "data" / "wallet_scores.db"
DEFAULT_RUNTIME_TRUTH = REPORTS_DIR / "runtime_truth_latest.json"
DEFAULT_STATE_IMPROVEMENT = REPORTS_DIR / "state_improvement_latest.json"
COINBASE_CANDLES_URL = "https://api.exchange.coinbase.com/products/{product}/candles"
USER_AGENT = "Elastifund intraday bundle exporter/1.0"
COINBASE_MAX_CANDLES = 300
ET_TZ = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class BundlePaths:
    root: Path
    charts_dir: Path
    raw_dir: Path
    derived_dir: Path


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _stamp() -> str:
    return _now_utc().strftime("%Y%m%dT%H%M%SZ")


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        if isinstance(value, float) and math.isnan(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _prepare_bundle_root(output_dir: Path | None) -> BundlePaths:
    root = output_dir or (REPORTS_DIR / f"btc_intraday_llm_bundle_{_stamp()}")
    charts_dir = root / "charts"
    raw_dir = root / "raw"
    derived_dir = root / "derived"
    charts_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    derived_dir.mkdir(parents=True, exist_ok=True)
    return BundlePaths(root=root, charts_dir=charts_dir, raw_dir=raw_dir, derived_dir=derived_dir)


def _read_sql_table(db_path: Path, table: str) -> pd.DataFrame:
    if not db_path.exists():
        return pd.DataFrame()
    conn = sqlite3.connect(db_path)
    try:
        return pd.read_sql_query(f'SELECT * FROM "{table}"', conn)
    finally:
        conn.close()


def _copy_if_exists(src: Path, dest: Path) -> bool:
    if not src.exists():
        return False
    shutil.copy2(src, dest)
    return True


def _fetch_coinbase_candles(*, product: str, granularity: int, days: int) -> pd.DataFrame:
    end_at = _now_utc().replace(second=0, microsecond=0)
    start_at = end_at - timedelta(days=max(1, int(days)))
    chunk_seconds = granularity * COINBASE_MAX_CANDLES
    cursor = end_at
    session = requests.Session()
    rows: list[list[Any]] = []

    while cursor > start_at:
        chunk_start = max(start_at, cursor - timedelta(seconds=chunk_seconds))
        params = {
            "granularity": granularity,
            "start": chunk_start.isoformat(),
            "end": cursor.isoformat(),
        }
        response = None
        for attempt in range(3):
            response = session.get(
                COINBASE_CANDLES_URL.format(product=product),
                params=params,
                headers={"User-Agent": USER_AGENT},
                timeout=30,
            )
            if response.status_code == 200:
                break
            if attempt == 2:
                response.raise_for_status()
            time.sleep(0.5 * (attempt + 1))
        payload = response.json() if response is not None else []
        if not isinstance(payload, list):
            raise RuntimeError(f"Unexpected Coinbase candle payload: {payload!r}")
        rows.extend(payload)
        cursor = chunk_start
        time.sleep(0.05)

    frame = pd.DataFrame(rows, columns=["timestamp_ts", "low", "high", "open", "close", "volume"])
    if frame.empty:
        raise RuntimeError("Coinbase candle pull returned no rows.")

    frame = frame.drop_duplicates(subset=["timestamp_ts"]).sort_values("timestamp_ts").reset_index(drop=True)
    numeric_columns = ["low", "high", "open", "close", "volume"]
    for column in numeric_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_ts"], unit="s", utc=True)
    frame["timestamp_et"] = frame["timestamp_utc"].dt.tz_convert(ET_TZ)
    return frame


def _derive_coinbase_features(raw: pd.DataFrame) -> pd.DataFrame:
    frame = raw.copy()
    frame["return_oc"] = (frame["close"] / frame["open"]) - 1.0
    frame["abs_return_oc"] = frame["return_oc"].abs()
    frame["range_frac"] = (frame["high"] - frame["low"]) / frame["open"]
    frame["prev_close_return"] = frame["close"].pct_change()
    frame["prior_15m_return"] = (frame["close"].shift(1) / frame["close"].shift(4)) - 1.0
    frame["prior_60m_return"] = (frame["close"].shift(1) / frame["close"].shift(13)) - 1.0
    frame["rolling_vol_1h"] = frame["return_oc"].rolling(12).std()
    frame["up"] = (frame["close"] > frame["open"]).astype(int)
    frame["date_et"] = frame["timestamp_et"].dt.date.astype(str)
    frame["hour_et"] = frame["timestamp_et"].dt.hour
    frame["minute_et"] = frame["timestamp_et"].dt.minute
    frame["minute_of_day_et"] = (frame["hour_et"] * 60) + frame["minute_et"]
    frame["slot_5m_et"] = (frame["minute_of_day_et"] // 5).astype(int)
    frame["slot_5m_label_et"] = frame["timestamp_et"].dt.strftime("%H:%M")
    frame["weekday_et"] = frame["timestamp_et"].dt.day_name()
    frame["hour_utc"] = frame["timestamp_utc"].dt.hour

    first_open = frame.groupby("date_et")["open"].transform("first")
    frame["from_day_open_return"] = (frame["close"] / first_open) - 1.0

    threshold = 0.0005
    frame["prior_15m_sign"] = np.select(
        [
            frame["prior_15m_return"] > threshold,
            frame["prior_15m_return"] < -threshold,
        ],
        ["up", "down"],
        default="flat",
    )
    return frame


def _group_summary(frame: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    grouped = frame.groupby(by, dropna=False)
    summary = grouped["return_oc"].agg(["count", "mean", "std"]).rename(
        columns={"count": "bars", "mean": "mean_return", "std": "std_return"}
    )
    summary["up_rate"] = grouped["up"].mean()
    summary["mean_abs_return"] = grouped["abs_return_oc"].mean()
    summary["mean_range"] = grouped["range_frac"].mean()
    summary["mean_from_day_open"] = grouped["from_day_open_return"].mean()
    summary["t_stat_mean_return"] = np.where(
        summary["std_return"].fillna(0.0) > 0,
        summary["mean_return"] / (summary["std_return"] / np.sqrt(summary["bars"])),
        np.nan,
    )
    summary = summary.reset_index()
    for column in ("mean_return", "std_return", "mean_abs_return", "mean_range", "mean_from_day_open"):
        summary[f"{column}_bp"] = summary[column] * 10_000.0
    summary["up_rate_pct"] = summary["up_rate"] * 100.0
    return summary


def _hour_slot_heatmap(frame: pd.DataFrame, output_path: Path) -> None:
    pivot = (
        frame.assign(slot_in_hour=frame["minute_et"] // 5)
        .pivot_table(index="hour_et", columns="slot_in_hour", values="up", aggfunc="mean")
        .sort_index()
    )
    plt.figure(figsize=(10, 7))
    plt.imshow(pivot.values, aspect="auto", cmap="RdYlGn", vmin=0.45, vmax=0.55)
    plt.colorbar(label="UP rate")
    plt.yticks(range(len(pivot.index)), [f"{hour:02d}:00" for hour in pivot.index])
    plt.xticks(range(len(pivot.columns)), [f"{int(slot) * 5:02d}" for slot in pivot.columns])
    plt.xlabel("Minute within hour (ET)")
    plt.ylabel("Hour (ET)")
    plt.title("BTC 5m UP Rate by Time of Day (Coinbase, ET)")
    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close()


def _hourly_charts(
    hour_summary: pd.DataFrame,
    *,
    full_feature_frame: pd.DataFrame,
    charts_dir: Path,
) -> dict[str, str]:
    outputs: dict[str, str] = {}

    up_rate_path = charts_dir / "coinbase_up_rate_by_hour_et.png"
    plt.figure(figsize=(10, 4))
    plt.plot(hour_summary["hour_et"], hour_summary["up_rate_pct"], marker="o")
    plt.axhline(50.0, color="black", linestyle="--", linewidth=1)
    plt.xlabel("Hour (ET)")
    plt.ylabel("UP rate %")
    plt.title("BTC 5m Directional Bias by Hour (Coinbase)")
    plt.tight_layout()
    plt.savefig(up_rate_path, dpi=150)
    plt.close()
    outputs["coinbase_up_rate_by_hour_et"] = str(up_rate_path)

    abs_move_path = charts_dir / "coinbase_abs_return_by_hour_et.png"
    plt.figure(figsize=(10, 4))
    plt.bar(hour_summary["hour_et"], hour_summary["mean_abs_return_bp"])
    plt.xlabel("Hour (ET)")
    plt.ylabel("Mean abs return (bp)")
    plt.title("BTC 5m Absolute Move by Hour (Coinbase)")
    plt.tight_layout()
    plt.savefig(abs_move_path, dpi=150)
    plt.close()
    outputs["coinbase_abs_return_by_hour_et"] = str(abs_move_path)

    heatmap_path = charts_dir / "coinbase_up_rate_heatmap_et.png"
    _hour_slot_heatmap(full_feature_frame, heatmap_path)
    outputs["coinbase_up_rate_heatmap_et"] = str(heatmap_path)

    return outputs


def _price_bucket(price: Any) -> str:
    parsed = _safe_float(price, default=float("nan"))
    if math.isnan(parsed):
        return "unknown"
    if parsed < 0.49:
        return "<0.49"
    if parsed < 0.50:
        return "0.49"
    if parsed < 0.51:
        return "0.50"
    return "0.51+"


def _rollup_live_rows(frame: pd.DataFrame, label: str) -> dict[str, Any]:
    rows = len(frame)
    pnl = round(frame["pnl_usd"].fillna(0.0).sum(), 4)
    avg_pnl = round(pnl / rows, 4) if rows else 0.0
    avg_order_price = round(frame["order_price"].fillna(0.0).mean(), 4) if rows else 0.0
    win_rate = round(frame["won"].fillna(0).mean(), 4) if rows and "won" in frame.columns else None
    return {
        "label": label,
        "fills": int(rows),
        "pnl_usd": pnl,
        "avg_pnl_usd": avg_pnl,
        "avg_order_price": avg_order_price,
        "win_rate": win_rate,
    }


def _recommend_guardrails(live_rows: pd.DataFrame) -> dict[str, Any] | None:
    if live_rows.empty or len(live_rows) < 10:
        return None

    baseline_pnl = round(live_rows["pnl_usd"].fillna(0.0).sum(), 4)
    best_score: tuple[float, int, float, float] | None = None
    best_candidate: dict[str, Any] | None = None

    for max_abs_delta in (0.00002, 0.00005, 0.00010, 0.00015):
        for down_cap in (0.48, 0.49, 0.50, 0.51):
            for up_cap in (0.47, 0.48, 0.49, 0.50, 0.51):
                subset = live_rows[
                    (live_rows["abs_delta"] <= max_abs_delta)
                    & (
                        ((live_rows["direction"] == "DOWN") & (live_rows["order_price"] <= down_cap))
                        | ((live_rows["direction"] == "UP") & (live_rows["order_price"] <= up_cap))
                    )
                ]
                if subset.empty:
                    continue
                pnl = round(subset["pnl_usd"].fillna(0.0).sum(), 4)
                score = (pnl, len(subset), -abs(down_cap - 0.50), -abs(up_cap - 0.51))
                if best_score is None or score > best_score:
                    best_score = score
                    best_candidate = {
                        "max_abs_delta": max_abs_delta,
                        "down_max_buy_price": down_cap,
                        "up_max_buy_price": up_cap,
                        "replay_live_filled_rows": int(len(subset)),
                        "replay_live_filled_pnl_usd": pnl,
                    }

    if best_candidate is None:
        return None

    best_candidate["baseline_live_filled_rows"] = int(len(live_rows))
    best_candidate["baseline_live_filled_pnl_usd"] = baseline_pnl
    return best_candidate


def _summarize_btc5_db(frame: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    if frame.empty:
        return {"status": "missing"}, pd.DataFrame(), pd.DataFrame()

    summary: dict[str, Any] = {
        "total_rows": int(len(frame)),
        "by_status": [],
    }
    by_status = (
        frame.assign(pnl_usd=frame["pnl_usd"].fillna(0.0))
        .groupby("order_status", dropna=False)
        .agg(rows=("id", "count"), pnl_usd=("pnl_usd", "sum"))
        .reset_index()
        .sort_values(["rows", "order_status"], ascending=[False, True])
    )
    by_status["pnl_usd"] = by_status["pnl_usd"].round(4)
    summary["by_status"] = by_status.to_dict(orient="records")

    live = frame[frame["order_status"] == "live_filled"].copy()
    if live.empty:
        summary["live_filled_rows"] = 0
        summary["live_filled_pnl_usd"] = 0.0
        return summary, by_status, live

    live["abs_delta"] = live["delta"].abs()
    live["price_bucket"] = live["order_price"].apply(_price_bucket)
    summary["live_filled_rows"] = int(len(live))
    summary["live_filled_pnl_usd"] = round(live["pnl_usd"].fillna(0.0).sum(), 4)
    summary["avg_live_filled_pnl_usd"] = round(live["pnl_usd"].fillna(0.0).mean(), 4)

    by_direction = [
        _rollup_live_rows(group, label)
        for label, group in sorted(live.groupby("direction"), key=lambda item: item[0])
    ]
    by_price_bucket = [
        _rollup_live_rows(group, label)
        for label, group in sorted(live.groupby("price_bucket"), key=lambda item: item[0])
    ]
    by_direction.sort(key=lambda item: (item["pnl_usd"], item["fills"]), reverse=True)
    by_price_bucket.sort(key=lambda item: (item["pnl_usd"], item["fills"]), reverse=True)

    recent_live = live.sort_values(["id", "updated_at"]).tail(12)
    recent_by_direction = [
        _rollup_live_rows(group, label)
        for label, group in sorted(recent_live.groupby("direction"), key=lambda item: item[0])
    ]
    recent_by_direction.sort(key=lambda item: (item["pnl_usd"], item["fills"]), reverse=True)

    summary["best_direction"] = by_direction[0] if by_direction else None
    summary["best_price_bucket"] = by_price_bucket[0] if by_price_bucket else None
    summary["recent_live_filled_summary"] = _rollup_live_rows(recent_live, "recent_12_live_filled")
    summary["recent_live_filled_by_direction"] = recent_by_direction
    summary["by_direction"] = by_direction
    summary["by_price_bucket"] = by_price_bucket
    summary["guardrail_recommendation"] = _recommend_guardrails(live)
    summary["latest_trade"] = (
        frame.sort_values(["id", "updated_at"]).tail(1).to_dict(orient="records")[0]
    )
    return summary, by_status, live


def _effective_wallet_direction(row: pd.Series) -> str:
    outcome = str(row.get("outcome") or "").strip().lower()
    side = str(row.get("side") or "").strip().lower()
    if outcome == "up":
        return "UP" if side == "buy" else "DOWN"
    if outcome == "down":
        return "DOWN" if side == "buy" else "UP"
    return "UNKNOWN"


def _export_sql_tables(db_path: Path, tables: list[str], raw_dir: Path, prefix: str) -> dict[str, int]:
    row_counts: dict[str, int] = {}
    for table in tables:
        frame = _read_sql_table(db_path, table)
        row_counts[table] = int(len(frame))
        if frame.empty:
            continue
        frame.to_csv(raw_dir / f"{prefix}_{table}.csv", index=False)
    return row_counts


def _render_report(
    *,
    bundle: BundlePaths,
    args: argparse.Namespace,
    runtime_truth: dict[str, Any],
    state_improvement: dict[str, Any],
    local_btc5_summary: dict[str, Any],
    remote_btc5_summary: dict[str, Any],
    coinbase_raw: pd.DataFrame,
    hour_summary: pd.DataFrame,
    slot_summary: pd.DataFrame,
    hour_sign_summary: pd.DataFrame,
    wallet_scores: pd.DataFrame,
    wallet_consensus: pd.DataFrame,
) -> str:
    overall_up_rate = coinbase_raw["up"].mean() * 100.0
    overall_abs_bp = coinbase_raw["abs_return_oc"].mean() * 10_000.0
    best_hour = hour_summary.sort_values(["up_rate_pct", "bars"], ascending=[False, False]).iloc[0]
    worst_hour = hour_summary.sort_values(["up_rate_pct", "bars"], ascending=[True, False]).iloc[0]
    most_volatile_hour = hour_summary.sort_values(["mean_abs_return_bp", "bars"], ascending=[False, False]).iloc[0]
    best_slot = slot_summary.sort_values(["up_rate_pct", "bars"], ascending=[False, False]).iloc[0]
    worst_slot = slot_summary.sort_values(["up_rate_pct", "bars"], ascending=[True, False]).iloc[0]
    strongest_trend_regime = hour_sign_summary.sort_values(
        ["up_rate_pct", "bars"], ascending=[False, False]
    ).iloc[0]
    weakest_trend_regime = hour_sign_summary.sort_values(
        ["up_rate_pct", "bars"], ascending=[True, False]
    ).iloc[0]

    runtime = runtime_truth.get("runtime") or {}
    live_guardrails = remote_btc5_summary.get("guardrail_recommendation") or {}
    best_bucket = remote_btc5_summary.get("best_price_bucket") or {}
    price_bucket_050 = next(
        (row for row in remote_btc5_summary.get("by_price_bucket") or [] if row.get("label") == "0.50"),
        None,
    )
    wallet_fast = int((wallet_scores.get("crypto_trades", pd.Series(dtype=float)) > 0).sum())
    top_consensus = (
        wallet_consensus.sort_values(["consensus_share", "total_volume"], ascending=[False, False]).head(3)
        if not wallet_consensus.empty
        else pd.DataFrame()
    )

    lines = [
        "# BTC Intraday Edge Bundle",
        "",
        f"Generated at: {_now_utc().isoformat()}",
        f"Coinbase product: `{args.coinbase_product}`",
        f"Coinbase lookback: `{args.coinbase_days}` days of `{args.coinbase_granularity // 60}m` candles",
        "",
        "## Executive Take",
        "",
        (
            f"The repo is not currently broad-trading generic BTC intraday seasonality. "
            f"The only intended live sleeve remains the dedicated BTC 5-minute maker, while the wider "
            f"`maker_velocity_all_in` posture is still blocked in `{DEFAULT_RUNTIME_TRUTH.name}`."
        ),
        (
            f"Pure time-of-day directionality exists but is weak on its own. Across `{len(coinbase_raw):,}` "
            f"Coinbase 5-minute bars, BTC closed up `{overall_up_rate:.2f}%` of the time, and the average "
            f"absolute open-to-close move was `{overall_abs_bp:.2f}` bp. That is enough to use as a conditioning "
            f"feature, not enough to trust as a standalone edge."
        ),
        (
            f"The stronger evidence in this repo is execution-conditioned: the pulled remote BTC5 maker DB "
            f"shows `{remote_btc5_summary.get('live_filled_rows', 0)}` `live_filled` rows with "
            f"`{remote_btc5_summary.get('live_filled_pnl_usd', 0.0):.4f}` USD cumulative PnL, and the best "
            f"live fill bucket is `{best_bucket.get('label', 'n/a')}` with "
            f"`{best_bucket.get('pnl_usd', 0.0):.4f}` USD over `{best_bucket.get('fills', 0)}` fills."
        ),
        (
            "The practical revision target is therefore not 'trade hour-of-day drift by itself'. "
            "It is 'trade final-window momentum only when quote price, delta guardrails, time-of-day regime, "
            "and wallet-flow context all agree.'"
        ),
        "",
        "## What We Are Actually Trading",
        "",
        f"- Runtime truth file: `{DEFAULT_RUNTIME_TRUTH}`",
        f"- Runtime truth generated at: `{runtime_truth.get('generated_at', 'unknown')}`",
        f"- Remote runtime profile: `{runtime_truth.get('remote_runtime_profile', 'unknown')}`",
        f"- Launch posture: `{runtime_truth.get('launch_posture', 'unknown')}`",
        f"- Repo runtime BTC5 summary at snapshot time: `{runtime.get('btc5_live_filled_rows', 'n/a')}` live-filled rows, `{runtime.get('btc5_live_filled_pnl_usd', 'n/a')}` USD live-filled PnL",
        f"- Fresh raw remote BTC5 pull used in this bundle: `{remote_btc5_summary.get('live_filled_rows', 0)}` live-filled rows, `{remote_btc5_summary.get('live_filled_pnl_usd', 0.0):.4f}` USD PnL",
        (
            f"- Local BTC5 DB is stale: `{local_btc5_summary.get('total_rows', 0)}` rows / "
            f"`{local_btc5_summary.get('live_filled_rows', 0)}` live-filled"
        ),
        "",
        "## Coinbase Intraday Findings",
        "",
        f"- Best ET hour by UP rate: `{int(best_hour['hour_et']):02d}:00` at `{best_hour['up_rate_pct']:.2f}%` over `{int(best_hour['bars'])}` bars",
        f"- Worst ET hour by UP rate: `{int(worst_hour['hour_et']):02d}:00` at `{worst_hour['up_rate_pct']:.2f}%` over `{int(worst_hour['bars'])}` bars",
        f"- Highest absolute-move ET hour: `{int(most_volatile_hour['hour_et']):02d}:00` with `{most_volatile_hour['mean_abs_return_bp']:.2f}` bp mean abs move",
        f"- Best 5-minute ET slot: `{best_slot['slot_5m_label_et']}` at `{best_slot['up_rate_pct']:.2f}%` over `{int(best_slot['bars'])}` bars",
        f"- Worst 5-minute ET slot: `{worst_slot['slot_5m_label_et']}` at `{worst_slot['up_rate_pct']:.2f}%` over `{int(worst_slot['bars'])}` bars",
        (
            f"- Strongest conditional regime in this bundle: hour `{int(strongest_trend_regime['hour_et']):02d}:00` "
            f"when prior 15m sign is `{strongest_trend_regime['prior_15m_sign']}`, UP rate = "
            f"`{strongest_trend_regime['up_rate_pct']:.2f}%` over `{int(strongest_trend_regime['bars'])}` bars"
        ),
        (
            f"- Weakest conditional regime in this bundle: hour `{int(weakest_trend_regime['hour_et']):02d}:00` "
            f"when prior 15m sign is `{weakest_trend_regime['prior_15m_sign']}`, UP rate = "
            f"`{weakest_trend_regime['up_rate_pct']:.2f}%` over `{int(weakest_trend_regime['bars'])}` bars"
        ),
        "",
        "## Repo-Native BTC5 Findings",
        "",
        (
            f"- Best live direction: `{(remote_btc5_summary.get('best_direction') or {}).get('label', 'n/a')}` "
            f"with `{(remote_btc5_summary.get('best_direction') or {}).get('pnl_usd', 0.0):.4f}` USD"
        ),
        (
            f"- Best live price bucket: `{best_bucket.get('label', 'n/a')}` "
            f"with `{best_bucket.get('avg_pnl_usd', 0.0):.4f}` USD average PnL per fill"
        ),
        (
            f"- `0.50` price bucket performance: "
            f"`{(price_bucket_050 or {}).get('pnl_usd', 0.0):.4f}` USD over `{(price_bucket_050 or {}).get('fills', 0)}` fills"
        ),
        (
            f"- Fresh guardrail replay winner: `max_abs_delta <= {live_guardrails.get('max_abs_delta', 'n/a')}`, "
            f"`UP <= {live_guardrails.get('up_max_buy_price', 'n/a')}`, "
            f"`DOWN <= {live_guardrails.get('down_max_buy_price', 'n/a')}`"
        ),
        (
            f"- Guardrail replay PnL: `{live_guardrails.get('replay_live_filled_pnl_usd', 0.0)}` USD "
            f"on `{live_guardrails.get('replay_live_filled_rows', 0)}` fills vs baseline "
            f"`{live_guardrails.get('baseline_live_filled_pnl_usd', 0.0)}` USD"
        ),
        "",
        "## Wallet-Flow Coverage",
        "",
        f"- Wallet score DB rows: `{len(wallet_scores):,}` wallets",
        f"- Wallets with crypto-fast activity: `{wallet_fast}`",
        f"- Wallet-trade consensus windows exported: `{len(wallet_consensus):,}` BTC 5m windows",
    ]

    if not top_consensus.empty:
        lines.extend(
            [
                "- Highest consensus windows in export:",
                *[
                    (
                        f"  - `{row.event_slug}` direction `{row.consensus_direction}` "
                        f"share `{row.consensus_share * 100:.2f}%` volume `{row.total_volume:.2f}`"
                    )
                    for row in top_consensus.itertuples(index=False)
                ],
            ]
        )

    lines.extend(
        [
            "",
            "## Algorithmic Advantage To Pursue",
            "",
            (
                "Use time-of-day as a prior, not a trigger. The trigger should stay close to the current "
                "BTC5 maker structure: near-close directional signal plus strict quote-price and delta filters."
            ),
            (
                "Promising composite feature set for the next revision: "
                "`[abs_delta_to_window_open, sign(delta), order_price_bucket, hour_et, slot_5m_et, "
                "prior_15m_return_sign, rolling_1h_vol, wallet_consensus_share, wallet_consensus_direction]`."
            ),
            (
                "Decision rule to test first: only quote when the seasonal prior and the live signal agree, "
                "and only below the empirically good buckets (`<0.49` or `0.49`) under the fresh guardrails."
            ),
            (
                "Do not let the model widen into raw 0.50+ chasing. The live remote fills in this bundle do "
                "not justify that."
            ),
            "",
            "## Data Gaps That Still Matter",
            "",
            "- There is no sub-minute reference-price tape in this bundle, so true T-10s latency edge is still unproven.",
            "- Local `edge_discovery_locked.db` remains sparse; it is useful as schema context, not final statistical proof.",
            "- Wallet-trade rows are useful for consensus/flow features, but realized wallet PnL is not fully labeled here.",
            "- The repo runtime snapshot and the fresh pulled remote BTC5 DB differ, so reconciliation remains a first-class task.",
            "",
            "## Bundle Contents",
            "",
            f"- Manifest: `{bundle.root / 'manifest.json'}`",
            f"- LLM prompt: `{bundle.root / 'llm_handoff_prompt.md'}`",
            f"- Coinbase raw candles: `{bundle.raw_dir / 'coinbase_btc_usd_5m_raw.csv'}`",
            f"- Coinbase features: `{bundle.derived_dir / 'coinbase_btc_usd_5m_features.csv'}`",
            f"- Hour summary: `{bundle.derived_dir / 'coinbase_intraday_hour_summary.csv'}`",
            f"- Slot summary: `{bundle.derived_dir / 'coinbase_intraday_slot_summary.csv'}`",
            f"- Remote BTC5 raw rows: `{bundle.raw_dir / 'remote_btc5_window_trades.csv'}`",
            f"- Wallet consensus windows: `{bundle.derived_dir / 'wallet_consensus_btc5_windows.csv'}`",
            f"- Charts: `{bundle.charts_dir}`",
            "",
        ]
    )

    return "\n".join(lines) + "\n"


def _render_llm_prompt(bundle: BundlePaths) -> str:
    return "\n".join(
        [
            "# LLM Handoff Prompt",
            "",
            "Use the attached bundle to redesign the BTC intraday agent logic for Elastifund.",
            "",
            "Objective:",
            "Build a conditional, execution-aware model for Polymarket BTC 5-minute markets.",
            "",
            "Important constraints:",
            "- Treat time-of-day seasonality as a prior, not a standalone signal.",
            "- Use the remote BTC5 fill data as the highest-value evidence in the bundle.",
            "- Penalize any proposal that requires buying above the empirically profitable price buckets.",
            "- Explicitly account for missing sub-minute data and sample-size risk.",
            "",
            "Primary files:",
            f"- `{bundle.root / 'report.md'}`",
            f"- `{bundle.root / 'manifest.json'}`",
            f"- `{bundle.raw_dir / 'remote_btc5_window_trades.csv'}`",
            f"- `{bundle.derived_dir / 'coinbase_btc_usd_5m_features.csv'}`",
            f"- `{bundle.derived_dir / 'coinbase_intraday_hour_summary.csv'}`",
            f"- `{bundle.derived_dir / 'coinbase_intraday_slot_summary.csv'}`",
            f"- `{bundle.derived_dir / 'coinbase_hour_prior15_sign_summary.csv'}`",
            f"- `{bundle.derived_dir / 'wallet_consensus_btc5_windows.csv'}`",
            "",
            "Questions to answer:",
            "1. Which conditional feature interactions produce the strongest out-of-sample directional edge?",
            "2. What quote-price ceilings should vary by direction, hour, and volatility regime?",
            "3. When should the bot refuse to quote even if raw delta suggests a side?",
            "4. Can wallet consensus add signal quality without overfitting?",
            "5. What is the simplest revised policy that improves expectancy while reducing blow-up risk?",
            "",
        ]
    ) + "\n"


def _write_manifest(
    *,
    bundle: BundlePaths,
    args: argparse.Namespace,
    runtime_truth: dict[str, Any],
    state_improvement: dict[str, Any],
    local_btc5_summary: dict[str, Any],
    remote_btc5_summary: dict[str, Any],
    edge_counts: dict[str, int],
    wallet_counts: dict[str, int],
    coinbase_rows: int,
    chart_paths: dict[str, str],
) -> None:
    payload = {
        "generated_at": _now_utc().isoformat(),
        "bundle_root": str(bundle.root),
        "coinbase": {
            "product": args.coinbase_product,
            "granularity_seconds": args.coinbase_granularity,
            "days": args.coinbase_days,
            "rows": coinbase_rows,
        },
        "source_files": {
            "runtime_truth_latest": str(DEFAULT_RUNTIME_TRUTH),
            "state_improvement_latest": str(DEFAULT_STATE_IMPROVEMENT),
            "local_btc5_db": str(args.local_btc5_db),
            "remote_btc5_db": str(args.remote_btc5_db),
            "edge_discovery_db": str(args.edge_db),
            "wallet_db": str(args.wallet_db),
        },
        "runtime_truth_excerpt": {
            "generated_at": runtime_truth.get("generated_at"),
            "remote_runtime_profile": runtime_truth.get("remote_runtime_profile"),
            "launch_posture": runtime_truth.get("launch_posture"),
            "runtime": runtime_truth.get("runtime"),
        },
        "state_improvement_excerpt": {
            "generated_at": state_improvement.get("generated_at"),
            "reject_reasons": state_improvement.get("reject_reasons"),
            "strategy_recommendations": state_improvement.get("strategy_recommendations"),
        },
        "local_btc5_summary": local_btc5_summary,
        "remote_btc5_summary": remote_btc5_summary,
        "edge_discovery_row_counts": edge_counts,
        "wallet_row_counts": wallet_counts,
        "charts": chart_paths,
    }
    (bundle.root / "manifest.json").write_text(json.dumps(payload, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=None, help="Write bundle into this directory.")
    parser.add_argument("--coinbase-product", default="BTC-USD")
    parser.add_argument("--coinbase-granularity", type=int, default=300)
    parser.add_argument("--coinbase-days", type=int, default=90)
    parser.add_argument("--local-btc5-db", type=Path, default=DEFAULT_LOCAL_BTC5_DB)
    parser.add_argument("--remote-btc5-db", type=Path, default=DEFAULT_REMOTE_BTC5_DB)
    parser.add_argument("--edge-db", type=Path, default=DEFAULT_EDGE_DB)
    parser.add_argument("--wallet-db", type=Path, default=DEFAULT_WALLET_DB)
    args = parser.parse_args()

    bundle = _prepare_bundle_root(args.output_dir)

    runtime_truth = _load_json(DEFAULT_RUNTIME_TRUTH)
    state_improvement = _load_json(DEFAULT_STATE_IMPROVEMENT)

    local_btc5 = _read_sql_table(args.local_btc5_db, "window_trades")
    remote_btc5 = _read_sql_table(args.remote_btc5_db, "window_trades")
    local_btc5_summary, _, _ = _summarize_btc5_db(local_btc5)
    remote_btc5_summary, _, remote_live = _summarize_btc5_db(remote_btc5)

    if not local_btc5.empty:
        local_btc5.to_csv(bundle.raw_dir / "local_btc5_window_trades.csv", index=False)
    if not remote_btc5.empty:
        remote_btc5.to_csv(bundle.raw_dir / "remote_btc5_window_trades.csv", index=False)
    _copy_if_exists(args.local_btc5_db, bundle.raw_dir / "local_btc5_window_trades.db")
    _copy_if_exists(args.remote_btc5_db, bundle.raw_dir / "remote_btc5_window_trades.db")

    edge_counts = _export_sql_tables(
        args.edge_db,
        tables=["markets", "market_prices", "btc_spot", "trades", "orderbook_snapshots"],
        raw_dir=bundle.raw_dir,
        prefix="edge_discovery",
    )
    wallet_counts = _export_sql_tables(
        args.wallet_db,
        tables=["wallet_scores", "wallet_trades"],
        raw_dir=bundle.raw_dir,
        prefix="wallet",
    )

    wallet_scores = _read_sql_table(args.wallet_db, "wallet_scores")
    wallet_trades = _read_sql_table(args.wallet_db, "wallet_trades")
    wallet_consensus = pd.DataFrame()
    if not wallet_trades.empty:
        wallet_trades["effective_direction"] = wallet_trades.apply(_effective_wallet_direction, axis=1)
        wallet_trades["is_btc_5m"] = wallet_trades["event_slug"].fillna("").str.startswith("btc-updown-5m-")
        wallet_fast_btc5 = wallet_trades[wallet_trades["is_btc_5m"]].copy()
        if not wallet_fast_btc5.empty:
            grouped = wallet_fast_btc5.groupby(["event_slug", "effective_direction"], dropna=False).agg(
                total_volume=("size", "sum"),
                trades=("id", "count"),
                unique_wallets=("wallet", "nunique"),
                avg_price=("price", "mean"),
                first_timestamp=("timestamp", "min"),
                last_timestamp=("timestamp", "max"),
            )
            consensus = grouped.reset_index()
            totals = consensus.groupby("event_slug")["total_volume"].sum().rename("window_total_volume")
            consensus = consensus.merge(totals, on="event_slug", how="left")
            consensus["consensus_share"] = np.where(
                consensus["window_total_volume"] > 0,
                consensus["total_volume"] / consensus["window_total_volume"],
                0.0,
            )
            wallet_consensus = (
                consensus.sort_values(["event_slug", "consensus_share", "total_volume"], ascending=[True, False, False])
                .drop_duplicates(subset=["event_slug"])
                .rename(columns={"effective_direction": "consensus_direction"})
                .sort_values("first_timestamp")
                .reset_index(drop=True)
            )
    wallet_consensus.to_csv(bundle.derived_dir / "wallet_consensus_btc5_windows.csv", index=False)

    coinbase_raw = _fetch_coinbase_candles(
        product=args.coinbase_product,
        granularity=args.coinbase_granularity,
        days=args.coinbase_days,
    )
    coinbase_features = _derive_coinbase_features(coinbase_raw)
    coinbase_raw.to_csv(bundle.raw_dir / "coinbase_btc_usd_5m_raw.csv", index=False)
    coinbase_features.to_csv(bundle.derived_dir / "coinbase_btc_usd_5m_features.csv", index=False)

    hour_summary = _group_summary(coinbase_features, ["hour_et"]).sort_values("hour_et").reset_index(drop=True)
    slot_summary = _group_summary(coinbase_features, ["slot_5m_et", "slot_5m_label_et"]).sort_values(
        "slot_5m_et"
    ).reset_index(drop=True)
    hour_sign_summary = _group_summary(
        coinbase_features.dropna(subset=["prior_15m_return"]), ["hour_et", "prior_15m_sign"]
    ).sort_values(["hour_et", "prior_15m_sign"]).reset_index(drop=True)
    weekday_hour_summary = _group_summary(coinbase_features, ["weekday_et", "hour_et"]).reset_index(drop=True)

    hour_summary.to_csv(bundle.derived_dir / "coinbase_intraday_hour_summary.csv", index=False)
    slot_summary.to_csv(bundle.derived_dir / "coinbase_intraday_slot_summary.csv", index=False)
    hour_sign_summary.to_csv(bundle.derived_dir / "coinbase_hour_prior15_sign_summary.csv", index=False)
    weekday_hour_summary.to_csv(bundle.derived_dir / "coinbase_weekday_hour_summary.csv", index=False)

    chart_paths = _hourly_charts(
        hour_summary,
        full_feature_frame=coinbase_features,
        charts_dir=bundle.charts_dir,
    )

    if not remote_live.empty:
        maker_bucket = (
            remote_live.groupby("price_bucket")
            .agg(fills=("id", "count"), pnl_usd=("pnl_usd", "sum"))
            .reset_index()
            .sort_values("price_bucket")
        )
        plt.figure(figsize=(6, 4))
        plt.bar(maker_bucket["price_bucket"], maker_bucket["pnl_usd"])
        plt.xlabel("Order price bucket")
        plt.ylabel("PnL USD")
        plt.title("Remote BTC5 Live PnL by Price Bucket")
        plt.tight_layout()
        maker_path = bundle.charts_dir / "remote_btc5_pnl_by_price_bucket.png"
        plt.savefig(maker_path, dpi=150)
        plt.close()
        chart_paths["remote_btc5_pnl_by_price_bucket"] = str(maker_path)

    report_text = _render_report(
        bundle=bundle,
        args=args,
        runtime_truth=runtime_truth,
        state_improvement=state_improvement,
        local_btc5_summary=local_btc5_summary,
        remote_btc5_summary=remote_btc5_summary,
        coinbase_raw=coinbase_features,
        hour_summary=hour_summary,
        slot_summary=slot_summary,
        hour_sign_summary=hour_sign_summary,
        wallet_scores=wallet_scores,
        wallet_consensus=wallet_consensus,
    )
    (bundle.root / "report.md").write_text(report_text)
    (bundle.root / "llm_handoff_prompt.md").write_text(_render_llm_prompt(bundle))

    _write_manifest(
        bundle=bundle,
        args=args,
        runtime_truth=runtime_truth,
        state_improvement=state_improvement,
        local_btc5_summary=local_btc5_summary,
        remote_btc5_summary=remote_btc5_summary,
        edge_counts=edge_counts,
        wallet_counts=wallet_counts,
        coinbase_rows=len(coinbase_raw),
        chart_paths=chart_paths,
    )

    print(bundle.root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
