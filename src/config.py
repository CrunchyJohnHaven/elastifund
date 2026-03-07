"""Configuration loading for the edge discovery system."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
import json
from typing import Any

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    yaml = None


@dataclass
class SystemConfig:
    timezone: str = "UTC"
    db_path: str = "data/edge_discovery.db"
    log_path: str = "logs/edge_discovery.log"
    report_root: str = "reports"
    analysis_path: str = "FastTradeEdgeAnalysis.md"


@dataclass
class SourceConfig:
    gamma_api: str = "https://gamma-api.polymarket.com/markets"
    trade_api: str = "https://data-api.polymarket.com/trades"
    clob_api: str = "https://clob.polymarket.com/book"
    binance_ws: str = "wss://stream.binance.com:9443/ws/btcusdt@trade"
    binance_ticker_api: str = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"
    binance_klines_api: str = "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1m&limit=2"


@dataclass
class CollectorConfig:
    http_timeout_seconds: int = 15
    http_retries: int = 3
    retry_backoff_seconds: float = 1.5
    market_poll_seconds: int = 30
    trade_poll_seconds: int = 30
    book_poll_seconds: int = 30
    btc_poll_seconds: int = 1
    max_recent_trades: int = 500
    snapshot_every_minutes: int = 30
    slug_probe_windows: int = 6


@dataclass
class MarketFilterConfig:
    target_slugs: list[str] = field(default_factory=lambda: ["btc-updown-5m", "btc-updown-15m", "btc-updown-4h"])
    required_resolution_source_contains: str = "chain.link"


@dataclass
class ResearchConfig:
    run_interval_minutes: int = 30
    ml_interval_hours: int = 6
    lookback_resolved_markets: int = 500
    min_signals_candidate: int = 100
    min_signals_validated: int = 300


@dataclass
class BacktestConfig:
    position_size_usd: float = 100.0
    maker_fill_rate: float = 0.6
    maker_fill_rate_sensitivity: list[float] = field(default_factory=lambda: [0.4, 0.6, 0.8])
    maker_fill_model: str = "trade_through"
    queue_aware_maker_fill: bool = True
    maker_fill_floor: float = 0.05
    maker_fill_ceiling: float = 0.95
    maker_fill_horizon_sec: int = 900
    maker_fill_trade_through_buffer: float = 0.001
    maker_fill_liquidity_trade_count_scale: float = 30.0
    maker_fill_edge_scale: float = 0.12
    maker_fill_logit_urgency: float = 0.9
    maker_fill_logit_liquidity: float = 0.8
    maker_fill_logit_edge_penalty: float = 1.1
    maker_fill_logit_alignment_penalty: float = 0.7
    maker_fill_logit_confidence: float = 0.4
    maker_fill_fallback_penalty: float = 0.4
    confidence_calibration_enabled: bool = True
    confidence_calibration_bins: int = 10
    confidence_calibration_prior_strength: float = 8.0
    confidence_calibration_min_history: int = 30
    confidence_calibration_floor: float = 0.02
    confidence_calibration_ceiling: float = 0.98
    default_spread: float = 0.02
    execution_delay_seconds: int = 2
    slippage_taker: float = 0.005
    cost_stress_pct: float = 0.2
    edge_thresholds: list[float] = field(default_factory=lambda: [0.03, 0.05, 0.08, 0.10, 0.15])


@dataclass
class ModelConfig:
    mc_default_paths: int = 10_000
    mc_final_paths: int = 50_000
    mc_seed: int = 42
    mc_jump_lambda: float = 0.05
    mc_jump_mu: float = -0.02
    mc_jump_sigma: float = 0.03


@dataclass
class AppConfig:
    system: SystemConfig = field(default_factory=SystemConfig)
    sources: SourceConfig = field(default_factory=SourceConfig)
    collector: CollectorConfig = field(default_factory=CollectorConfig)
    markets: MarketFilterConfig = field(default_factory=MarketFilterConfig)
    research: ResearchConfig = field(default_factory=ResearchConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    models: ModelConfig = field(default_factory=ModelConfig)

    def to_dict(self) -> dict[str, Any]:
        """Return config as a nested dictionary."""
        return asdict(self)


def _deep_update(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = _deep_update(base[key], value)
        else:
            base[key] = value
    return base


def load_config(path: str | Path = "config/defaults.yaml") -> AppConfig:
    """Load application config from YAML (or JSON-formatted YAML) with defaults."""
    cfg = AppConfig()
    path_obj = Path(path)
    if not path_obj.exists():
        return cfg

    raw: dict[str, Any]
    if yaml is not None:
        raw = yaml.safe_load(path_obj.read_text()) or {}
    else:
        raw = json.loads(path_obj.read_text())

    merged = _deep_update(cfg.to_dict(), raw)

    return AppConfig(
        system=SystemConfig(**merged.get("system", {})),
        sources=SourceConfig(**merged.get("sources", {})),
        collector=CollectorConfig(**merged.get("collector", {})),
        markets=MarketFilterConfig(**merged.get("markets", {})),
        research=ResearchConfig(**merged.get("research", {})),
        backtest=BacktestConfig(**merged.get("backtest", {})),
        models=ModelConfig(**merged.get("models", {})),
    )
