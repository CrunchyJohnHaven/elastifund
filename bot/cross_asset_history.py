"""Historical cross-asset backfill and vendor ranking for the cascade lane."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
from typing import Any, Protocol

import httpx

try:
    from nontrading.finance.config import FinanceSettings
except ModuleNotFoundError:
    @dataclass(frozen=True)
    class FinanceSettings:
        """Minimal fallback for trading-box operator scripts."""

        single_action_cap_usd: float = 250.0

        @classmethod
        def from_env(cls) -> "FinanceSettings":
            raw = os.getenv("JJ_FINANCE_SINGLE_ACTION_CAP_USD", "").strip()
            try:
                value = float(raw) if raw else 250.0
            except ValueError:
                value = 250.0
            return cls(single_action_cap_usd=value)

        def with_workspace(self, _workspace_root: Path) -> "FinanceSettings":
            return self

REPORTS_DIR = Path("reports")
STATE_DIR = Path("state") / "cross_asset_history"
DEFAULT_HISTORY_REPORT_PATH = REPORTS_DIR / "cross_asset_history" / "latest.json"
DEFAULT_VENDOR_STACK_REPORT_PATH = REPORTS_DIR / "vendor_stack" / "latest.json"
DEFAULT_INSTANCE_REPORT_PATH = REPORTS_DIR / "parallel" / "instance3_multi_asset_data_dispatch.json"

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
COINGECKO_RANGE_URL = "https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart/range"
COINAPI_OHLCV_URL = "https://rest.coinapi.io/v1/ohlcv/{symbol_id}/history"

COINAPI_STARTUP_MONTHLY_USD = 79.0
NANSEN_PRO_MONTHLY_USD = 69.0
GLASSNODE_PROFESSIONAL_BASE_MONTHLY_USD = 999.0


@dataclass(frozen=True)
class AssetSpec:
    symbol: str
    binance_symbol: str
    coingecko_id: str
    coinapi_symbol_id: str


DEFAULT_ASSETS: tuple[AssetSpec, ...] = (
    AssetSpec("BTC", "BTCUSDT", "bitcoin", "BINANCE_SPOT_BTC_USDT"),
    AssetSpec("ETH", "ETHUSDT", "ethereum", "BINANCE_SPOT_ETH_USDT"),
    AssetSpec("SOL", "SOLUSDT", "solana", "BINANCE_SPOT_SOL_USDT"),
    AssetSpec("XRP", "XRPUSDT", "ripple", "BINANCE_SPOT_XRP_USDT"),
    AssetSpec("DOGE", "DOGEUSDT", "dogecoin", "BINANCE_SPOT_DOGE_USDT"),
)


@dataclass(frozen=True)
class CrossAssetHistorySettings:
    workspace_root: Path = field(default_factory=Path.cwd)
    state_dir: Path = STATE_DIR
    history_report_path: Path = DEFAULT_HISTORY_REPORT_PATH
    vendor_stack_report_path: Path = DEFAULT_VENDOR_STACK_REPORT_PATH
    instance_report_path: Path = DEFAULT_INSTANCE_REPORT_PATH
    assets: tuple[AssetSpec, ...] = DEFAULT_ASSETS
    lookback_days: int = 30
    enable_binance_backfill: bool = True
    enable_coingecko_reference: bool = True
    enable_coinapi_reference: bool = False
    enable_glassnode_reference: bool = False
    enable_nansen_reference: bool = False
    coinapi_api_key: str = ""
    glassnode_api_key: str = ""
    nansen_api_key: str = ""
    timeout_seconds: float = 20.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "workspace_root", Path(self.workspace_root))
        object.__setattr__(self, "state_dir", self._normalize_path(self.state_dir))
        object.__setattr__(self, "history_report_path", self._normalize_path(self.history_report_path))
        object.__setattr__(self, "vendor_stack_report_path", self._normalize_path(self.vendor_stack_report_path))
        object.__setattr__(self, "instance_report_path", self._normalize_path(self.instance_report_path))

    def _normalize_path(self, path: str | Path) -> Path:
        path = Path(path)
        return path if path.is_absolute() else self.workspace_root / path


class HttpClient(Protocol):
    def get(self, url: str, **kwargs: Any) -> Any: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _isoformat_z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _finance_gate_snapshot(workspace_root: Path) -> dict[str, Any]:
    path = workspace_root / "reports" / "finance" / "latest.json"
    if not path.exists():
        return {
            "path": str(path),
            "finance_gate_pass": False,
            "free_cash_after_floor_usd": 0.0,
            "single_action_cap_usd": 0.0,
            "reason": "finance_report_missing",
        }
    payload = json.loads(path.read_text(encoding="utf-8"))
    cycle_budget = payload.get("cycle_budget_ledger") if isinstance(payload.get("cycle_budget_ledger"), dict) else {}
    dollars = cycle_budget.get("dollars") if isinstance(cycle_budget.get("dollars"), dict) else {}
    return {
        "path": str(path),
        "finance_gate_pass": bool(payload.get("finance_gate_pass")),
        "free_cash_after_floor_usd": float(
            payload.get("finance_totals", {}).get("free_cash_after_floor", dollars.get("free_cash_after_floor_usd", 0.0))
            or 0.0
        ),
        "single_action_cap_usd": float(dollars.get("single_action_cap_usd", 0.0) or 0.0),
        "reason": str((payload.get("finance_gate") or {}).get("reason") or "unknown"),
    }


def _binance_backfill_path(settings: CrossAssetHistorySettings, asset: AssetSpec) -> Path:
    return settings.state_dir / "binance" / f"{asset.symbol.lower()}_1m.jsonl"


def _coingecko_backfill_path(settings: CrossAssetHistorySettings, asset: AssetSpec) -> Path:
    return settings.state_dir / "coingecko" / f"{asset.symbol.lower()}_reference.jsonl"


def _coinapi_backfill_path(settings: CrossAssetHistorySettings, asset: AssetSpec, interval_label: str) -> Path:
    return settings.state_dir / "coinapi" / f"{asset.symbol.lower()}_{interval_label}.jsonl"


def fetch_binance_minute_bars(
    client: HttpClient,
    *,
    asset: AssetSpec,
    lookback_days: int,
) -> list[dict[str, Any]]:
    end_dt = _utc_now().replace(second=0, microsecond=0)
    start_dt = end_dt - timedelta(days=lookback_days)
    cursor_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)
    rows: list[dict[str, Any]] = []

    while cursor_ms < end_ms:
        response = client.get(
            BINANCE_KLINES_URL,
            params={
                "symbol": asset.binance_symbol,
                "interval": "1m",
                "startTime": cursor_ms,
                "endTime": end_ms,
                "limit": 1000,
            },
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list) or not payload:
            break
        for entry in payload:
            open_ms = int(entry[0])
            close_ms = int(entry[6])
            rows.append(
                {
                    "asset": asset.symbol,
                    "venue": "binance",
                    "interval": "1m",
                    "open_time": _isoformat_z(datetime.fromtimestamp(open_ms / 1000, UTC)),
                    "close_time": _isoformat_z(datetime.fromtimestamp(close_ms / 1000, UTC)),
                    "open": float(entry[1]),
                    "high": float(entry[2]),
                    "low": float(entry[3]),
                    "close": float(entry[4]),
                    "volume": float(entry[5]),
                    "trade_count": int(entry[8]),
                    "quote_volume": float(entry[7]),
                }
            )
        cursor_ms = int(payload[-1][6]) + 1
        if len(payload) < 1000:
            break

    return rows


def fetch_coingecko_reference(
    client: HttpClient,
    *,
    asset: AssetSpec,
    lookback_days: int,
) -> list[dict[str, Any]]:
    end_ts = int(_utc_now().timestamp())
    start_ts = int((_utc_now() - timedelta(days=lookback_days)).timestamp())
    response = client.get(
        COINGECKO_RANGE_URL.format(coin_id=asset.coingecko_id),
        params={"vs_currency": "usd", "from": start_ts, "to": end_ts},
        headers={"accept": "application/json"},
    )
    response.raise_for_status()
    payload = response.json()
    prices = payload.get("prices") if isinstance(payload, dict) else []
    rows: list[dict[str, Any]] = []
    for point in prices if isinstance(prices, list) else []:
        timestamp_ms = int(point[0])
        rows.append(
            {
                "asset": asset.symbol,
                "vendor": "coingecko",
                "interval": "reference",
                "time": _isoformat_z(datetime.fromtimestamp(timestamp_ms / 1000, UTC)),
                "price_usd": float(point[1]),
            }
        )
    return rows


def fetch_coinapi_ohlcv(
    client: HttpClient,
    *,
    asset: AssetSpec,
    period_id: str,
    limit: int,
    api_key: str,
) -> list[dict[str, Any]]:
    if not api_key.strip():
        return []
    response = client.get(
        COINAPI_OHLCV_URL.format(symbol_id=asset.coinapi_symbol_id),
        params={
            "period_id": period_id,
            "limit": limit,
        },
        headers={"X-CoinAPI-Key": api_key.strip()},
    )
    response.raise_for_status()
    payload = response.json()
    rows: list[dict[str, Any]] = []
    for entry in payload if isinstance(payload, list) else []:
        rows.append(
            {
                "asset": asset.symbol,
                "vendor": "coinapi",
                "interval": "1s" if period_id == "1SEC" else "1m",
                "time_period_start": entry.get("time_period_start"),
                "time_period_end": entry.get("time_period_end"),
                "price_open": float(entry.get("price_open", 0.0) or 0.0),
                "price_high": float(entry.get("price_high", 0.0) or 0.0),
                "price_low": float(entry.get("price_low", 0.0) or 0.0),
                "price_close": float(entry.get("price_close", 0.0) or 0.0),
                "volume_traded": float(entry.get("volume_traded", 0.0) or 0.0),
                "trades_count": int(entry.get("trades_count", 0) or 0),
            }
        )
    return rows


def _dataset_summary(
    *,
    provider: str,
    asset: str,
    interval: str,
    rows: list[dict[str, Any]],
    path: Path | None,
    blocked_reason: str | None = None,
) -> dict[str, Any]:
    if not rows:
        return {
            "provider": provider,
            "asset": asset,
            "interval": interval,
            "status": "blocked" if blocked_reason else "empty",
            "rows": 0,
            "first_time": None,
            "last_time": None,
            "path": str(path) if path is not None else None,
            "blocked_reason": blocked_reason,
        }
    time_keys = ("open_time", "time", "time_period_start")
    extracted = [str(row.get(key) or "") for row in rows for key in time_keys if row.get(key)]
    return {
        "provider": provider,
        "asset": asset,
        "interval": interval,
        "status": "ready",
        "rows": len(rows),
        "first_time": min(extracted) if extracted else None,
        "last_time": max(extracted) if extracted else None,
        "path": str(path) if path is not None else None,
        "blocked_reason": blocked_reason,
    }


def collect_history(
    settings: CrossAssetHistorySettings,
    *,
    client: HttpClient | None = None,
) -> dict[str, Any]:
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    http_client = client or httpx.Client(timeout=settings.timeout_seconds)
    close_client = client is None
    generated_at = _isoformat_z(_utc_now())
    datasets: list[dict[str, Any]] = []
    coverage_rows: list[dict[str, Any]] = []
    failures: list[str] = []

    try:
        for asset in settings.assets:
            if settings.enable_binance_backfill:
                try:
                    rows = fetch_binance_minute_bars(http_client, asset=asset, lookback_days=settings.lookback_days)
                    path = _binance_backfill_path(settings, asset)
                    _write_jsonl(path, rows)
                    datasets.append(_dataset_summary(provider="binance", asset=asset.symbol, interval="1m", rows=rows, path=path))
                except Exception as exc:
                    failures.append(f"binance_backfill_failed:{asset.symbol}:{exc}")
                    datasets.append(
                        _dataset_summary(
                            provider="binance",
                            asset=asset.symbol,
                            interval="1m",
                            rows=[],
                            path=_binance_backfill_path(settings, asset),
                            blocked_reason=str(exc),
                        )
                    )

            if settings.enable_coingecko_reference:
                try:
                    rows = fetch_coingecko_reference(http_client, asset=asset, lookback_days=settings.lookback_days)
                    path = _coingecko_backfill_path(settings, asset)
                    _write_jsonl(path, rows)
                    datasets.append(
                        _dataset_summary(provider="coingecko", asset=asset.symbol, interval="reference", rows=rows, path=path)
                    )
                except Exception as exc:
                    failures.append(f"coingecko_reference_failed:{asset.symbol}:{exc}")
                    datasets.append(
                        _dataset_summary(
                            provider="coingecko",
                            asset=asset.symbol,
                            interval="reference",
                            rows=[],
                            path=_coingecko_backfill_path(settings, asset),
                            blocked_reason=str(exc),
                        )
                    )

            if settings.enable_coinapi_reference:
                for period_id, interval_label, limit in (("1MIN", "1m", 2000), ("1SEC", "1s", 2000)):
                    try:
                        rows = fetch_coinapi_ohlcv(
                            http_client,
                            asset=asset,
                            period_id=period_id,
                            limit=limit,
                            api_key=settings.coinapi_api_key,
                        )
                        path = _coinapi_backfill_path(settings, asset, interval_label)
                        if rows:
                            _write_jsonl(path, rows)
                        datasets.append(
                            _dataset_summary(
                                provider="coinapi",
                                asset=asset.symbol,
                                interval=interval_label,
                                rows=rows,
                                path=path,
                                blocked_reason="coinapi_api_key_missing" if not rows and not settings.coinapi_api_key.strip() else None,
                            )
                        )
                    except Exception as exc:
                        failures.append(f"coinapi_{interval_label}_failed:{asset.symbol}:{exc}")
                        datasets.append(
                            _dataset_summary(
                                provider="coinapi",
                                asset=asset.symbol,
                                interval=interval_label,
                                rows=[],
                                path=_coinapi_backfill_path(settings, asset, interval_label),
                                blocked_reason=str(exc),
                            )
                        )
            else:
                for interval_label in ("1m", "1s"):
                    datasets.append(
                        _dataset_summary(
                            provider="coinapi",
                            asset=asset.symbol,
                            interval=interval_label,
                            rows=[],
                            path=_coinapi_backfill_path(settings, asset, interval_label),
                            blocked_reason="feature_flag_disabled",
                        )
                    )

            for provider, enabled, blocked_reason in (
                ("glassnode", settings.enable_glassnode_reference, "feature_flag_disabled"),
                ("nansen", settings.enable_nansen_reference, "feature_flag_disabled"),
            ):
                datasets.append(
                    _dataset_summary(
                        provider=provider,
                        asset=asset.symbol,
                        interval="derived",
                        rows=[],
                        path=None,
                        blocked_reason=None if enabled else blocked_reason,
                    )
                )

        for asset in settings.assets:
            asset_rows = [row for row in datasets if row["asset"] == asset.symbol]
            minute_ready = any(row["provider"] == "binance" and row["interval"] == "1m" and row["status"] == "ready" for row in asset_rows)
            second_ready = any(row["provider"] == "coinapi" and row["interval"] == "1s" and row["status"] == "ready" for row in asset_rows)
            coverage_rows.append(
                {
                    "asset": asset.symbol,
                    "one_minute_replay_ready": minute_ready,
                    "one_second_replay_ready": second_ready,
                    "reference_sources": [row["provider"] for row in asset_rows if row["status"] == "ready"],
                }
            )

        return {
            "schema_version": "cross_asset_history.v1",
            "generated_at": generated_at,
            "lookback_days": settings.lookback_days,
            "assets": [asset.symbol for asset in settings.assets],
            "datasets": datasets,
            "coverage": coverage_rows,
            "summary": {
                "asset_count": len(settings.assets),
                "one_minute_replay_ready_assets": sum(1 for row in coverage_rows if row["one_minute_replay_ready"]),
                "one_second_replay_ready_assets": sum(1 for row in coverage_rows if row["one_second_replay_ready"]),
                "free_stack_only": not settings.enable_coinapi_reference,
                "failures": failures,
            },
        }
    finally:
        if close_client:
            http_client.close()


def build_vendor_stack(
    history_report: dict[str, Any],
    *,
    workspace_root: Path,
    finance_settings: FinanceSettings | None = None,
) -> dict[str, Any]:
    finance_snapshot = _finance_gate_snapshot(workspace_root)
    finance_settings = finance_settings or FinanceSettings.from_env().with_workspace(workspace_root)

    one_second_gap = int(history_report.get("summary", {}).get("one_second_replay_ready_assets", 0) or 0) < len(
        history_report.get("assets", [])
    )
    one_minute_ready = int(history_report.get("summary", {}).get("one_minute_replay_ready_assets", 0) or 0) == len(
        history_report.get("assets", [])
    )
    finance_gate_pass = bool(finance_snapshot["finance_gate_pass"])
    free_cash = float(finance_snapshot["free_cash_after_floor_usd"])
    action_cap = min(float(finance_snapshot["single_action_cap_usd"]), finance_settings.single_action_cap_usd)

    coinapi_finance_pass = finance_gate_pass and free_cash >= COINAPI_STARTUP_MONTHLY_USD and action_cap >= COINAPI_STARTUP_MONTHLY_USD

    ranking = [
        {
            "vendor": "free_stack",
            "rank": 1,
            "status": "active",
            "recommendation": "keep",
            "monthly_commitment_impact_usd": 0.0,
            "expected_info_gain_score": 0.46 if one_minute_ready else 0.22,
            "expected_arr_lift_bps": 0.0,
            "cap_impact": "none",
            "why_now": "Free venue backfill covers 1m replay for the leader/follower set.",
            "gaps": ["1s_history_missing"] if one_second_gap else [],
        },
        {
            "vendor": "coinapi_startup",
            "rank": 2,
            "status": "recommended" if coinapi_finance_pass and one_second_gap else "deferred",
            "recommendation": "buy_now" if coinapi_finance_pass and one_second_gap else "hold",
            "monthly_commitment_impact_usd": COINAPI_STARTUP_MONTHLY_USD,
            "expected_info_gain_score": 0.84 if one_second_gap else 0.3,
            "expected_arr_lift_bps": 1800.0 if one_second_gap else 0.0,
            "cap_impact": "within_policy" if COINAPI_STARTUP_MONTHLY_USD <= action_cap else "exceeds_single_action_cap",
            "why_now": "CoinAPI is the cheapest visible step that closes the 1s history gap and normalizes venue data.",
            "gaps": [] if one_second_gap else ["free_stack_already_sufficient"],
            "blocked_reasons": ([] if coinapi_finance_pass else ["finance_gate_or_budget_blocked"]) if one_second_gap else [],
        },
        {
            "vendor": "nansen_pro",
            "rank": 3,
            "status": "optional",
            "recommendation": "defer",
            "monthly_commitment_impact_usd": NANSEN_PRO_MONTHLY_USD,
            "expected_info_gain_score": 0.55,
            "expected_arr_lift_bps": 700.0,
            "cap_impact": "within_policy" if NANSEN_PRO_MONTHLY_USD <= action_cap else "exceeds_single_action_cap",
            "why_now": "Useful once the free stack proves a wallet-label or smart-money information gap.",
            "gaps": ["not_required_for_price_history"],
        },
        {
            "vendor": "glassnode_api_addon",
            "rank": 4,
            "status": "blocked",
            "recommendation": "defer",
            "monthly_commitment_impact_usd": GLASSNODE_PROFESSIONAL_BASE_MONTHLY_USD,
            "expected_info_gain_score": 0.68,
            "expected_arr_lift_bps": 900.0,
            "cap_impact": "exceeds_monthly_commitment_cap",
            "why_now": "High-quality on-chain and market metrics, but API access requires the Professional tier plus an API add-on.",
            "gaps": ["contact_sales_required", "exceeds_default_monthly_commitment_cap"],
        },
        {
            "vendor": "kaiko_or_amberdata",
            "rank": 5,
            "status": "blocked",
            "recommendation": "defer",
            "monthly_commitment_impact_usd": None,
            "expected_info_gain_score": 0.72,
            "expected_arr_lift_bps": 950.0,
            "cap_impact": "unknown_contact_sales",
            "why_now": "Reserved for a later step if CoinAPI and the free stack still leave an information gap.",
            "gaps": ["deferred_by_policy"],
        },
    ]

    return {
        "schema_version": "vendor_stack.v1",
        "generated_at": history_report.get("generated_at"),
        "assets": list(history_report.get("assets", [])),
        "history_summary": history_report.get("summary", {}),
        "finance": finance_snapshot,
        "ranking": ranking,
        "recommendation": {
            "decision": "buy_coinapi_startup" if coinapi_finance_pass and one_second_gap else "hold_free_stack",
            "reason": (
                "Free stack covers 1m replay but not 1s; CoinAPI Startup fits current policy caps."
                if coinapi_finance_pass and one_second_gap
                else "Hold the free stack until the finance gate is green or the 1s gap becomes binding."
            ),
            "monthly_commitment_impact_usd": COINAPI_STARTUP_MONTHLY_USD if one_second_gap else 0.0,
        },
    }


def build_instance_artifact(
    history_report: dict[str, Any],
    vendor_stack_report: dict[str, Any],
    *,
    workspace_root: Path,
) -> dict[str, Any]:
    finance = vendor_stack_report.get("finance", {})
    one_second_ready = int(history_report.get("summary", {}).get("one_second_replay_ready_assets", 0) or 0)
    asset_count = len(history_report.get("assets", []))
    failures = list(history_report.get("summary", {}).get("failures", []) or [])
    block_reasons = list(dict.fromkeys(
        failures
        + (
            ["one_second_reference_history_missing"]
            if one_second_ready < asset_count
            else []
        )
        + (
            ["finance_gate_not_green_for_coinapi"]
            if vendor_stack_report.get("recommendation", {}).get("decision") != "buy_coinapi_startup" and one_second_ready < asset_count
            else []
        )
    ))

    return {
        "schema_version": "instance3_output.v3",
        "instance": 3,
        "instance_role": "GPT-4 / Medium - Historical backfill, vendor ladder, and paid-feed feature flags",
        "generated_at": history_report.get("generated_at"),
        "history_report_path": str(workspace_root / "reports" / "cross_asset_history" / "latest.json"),
        "vendor_stack_report_path": str(workspace_root / "reports" / "vendor_stack" / "latest.json"),
        "candidate_delta_arr_bps": 1800.0 if one_second_ready < asset_count else 250.0,
        "expected_improvement_velocity_delta": "+1 vendor step; 1m replay ready across leader/follower assets, 1s gap isolated to paid-feed lane.",
        "arr_confidence_score": 0.61 if one_second_ready < asset_count else 0.38,
        "block_reasons": block_reasons,
        "finance_gate_pass": bool(finance.get("finance_gate_pass")),
        "one_next_cycle_action": (
            "Buy CoinAPI Startup and rerun the cross-asset backfill with 1SEC enabled."
            if vendor_stack_report.get("recommendation", {}).get("decision") == "buy_coinapi_startup"
            else "Keep the free stack running and rerun after finance gate recovery or a confirmed 1s-history bottleneck."
        ),
    }


def run_cross_asset_history_dispatch(
    settings: CrossAssetHistorySettings,
    *,
    client: HttpClient | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    history_report = collect_history(settings, client=client)
    vendor_stack_report = build_vendor_stack(history_report, workspace_root=settings.workspace_root)
    instance_artifact = build_instance_artifact(history_report, vendor_stack_report, workspace_root=settings.workspace_root)

    _write_json(settings.history_report_path, history_report)
    _write_json(settings.vendor_stack_report_path, vendor_stack_report)
    _write_json(settings.instance_report_path, instance_artifact)
    return history_report, vendor_stack_report, instance_artifact


def settings_from_env(*, workspace_root: Path | None = None) -> CrossAssetHistorySettings:
    workspace = Path.cwd() if workspace_root is None else Path(workspace_root)

    def _env_bool(name: str, default: bool) -> bool:
        raw = os.getenv(name)
        if raw is None or not raw.strip():
            return default
        return raw.strip().lower() in {"1", "true", "yes", "on"}

    def _env_int(name: str, default: int) -> int:
        raw = os.getenv(name)
        return int(raw.strip()) if raw and raw.strip() else default

    return CrossAssetHistorySettings(
        workspace_root=workspace,
        lookback_days=_env_int("JJ_CROSS_ASSET_LOOKBACK_DAYS", 30),
        enable_binance_backfill=_env_bool("JJ_ENABLE_BINANCE_BACKFILL", True),
        enable_coingecko_reference=_env_bool("JJ_ENABLE_COINGECKO_REFERENCE", True),
        enable_coinapi_reference=_env_bool("JJ_ENABLE_COINAPI_REFERENCE", False),
        enable_glassnode_reference=_env_bool("JJ_ENABLE_GLASSNODE_REFERENCE", False),
        enable_nansen_reference=_env_bool("JJ_ENABLE_NANSEN_REFERENCE", False),
        coinapi_api_key=os.getenv("COINAPI_KEY", ""),
        glassnode_api_key=os.getenv("GLASSNODE_API_KEY", ""),
        nansen_api_key=os.getenv("NANSEN_API_KEY", ""),
    )


__all__ = [
    "COINAPI_STARTUP_MONTHLY_USD",
    "CrossAssetHistorySettings",
    "DEFAULT_HISTORY_REPORT_PATH",
    "DEFAULT_INSTANCE_REPORT_PATH",
    "DEFAULT_VENDOR_STACK_REPORT_PATH",
    "GLASSNODE_PROFESSIONAL_BASE_MONTHLY_USD",
    "NANSEN_PRO_MONTHLY_USD",
    "build_instance_artifact",
    "build_vendor_stack",
    "collect_history",
    "run_cross_asset_history_dispatch",
    "settings_from_env",
]
