"""Consume Elastic ML anomalies and translate them into trading controls."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

from hub.elastic.client import ElasticClientError, ElasticRestClient

try:
    from bot import elastic_client
except ImportError:  # pragma: no cover - runtime fallback
    import elastic_client  # type: ignore

from bot.elastic_ml_setup import (
    ElasticMLConfig,
    KILL_RULE_FREQUENCY_JOB_ID,
    OFI_DIVERGENCE_JOB_ID,
    SIGNAL_CONFIDENCE_DRIFT_JOB_ID,
    SPREAD_ANOMALY_JOB_ID,
    VPIN_ANOMALY_JOB_ID,
)

logger = logging.getLogger("JJ.elastic_ml")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return bool(default)
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class ElasticAnomaly:
    """Normalized view of one Elastic ML record."""

    job_id: str
    score: float
    timestamp: int
    entity: str | None
    actual: tuple[float, ...] = ()
    typical: tuple[float, ...] = ()
    field_name: str = ""
    function: str = ""
    description: str = ""

    @property
    def category(self) -> str:
        if self.job_id == VPIN_ANOMALY_JOB_ID:
            return "vpin"
        if self.job_id == OFI_DIVERGENCE_JOB_ID:
            return "ofi"
        if self.job_id == SPREAD_ANOMALY_JOB_ID:
            return "spread"
        if self.job_id == SIGNAL_CONFIDENCE_DRIFT_JOB_ID:
            return "confidence"
        if self.job_id == KILL_RULE_FREQUENCY_JOB_ID:
            return "kill_frequency"
        return "unknown"

    def to_log_payload(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "record_score": round(self.score, 2),
            "timestamp": self.timestamp,
            "entity": self.entity,
            "field_name": self.field_name,
            "function": self.function,
            "actual": list(self.actual),
            "typical": list(self.typical),
            "description": self.description,
        }


@dataclass
class MarketControl:
    """Active ML-derived controls for one market."""

    market_id: str
    size_multiplier: float = 1.0
    caution_score: float = 0.0
    caution_jobs: set[str] = field(default_factory=set)
    caution_expires_at: float = 0.0
    pause_until: float = 0.0
    pause_reason: str = ""
    pause_score: float = 0.0


@dataclass
class ReviewFlag:
    signal_source: str
    score: float
    message: str
    expires_at: float


class ElasticAnomalyConsumer:
    """Best-effort Elastic ML consumer that never blocks trading."""

    def __init__(
        self,
        client: ElasticRestClient | Any | None = None,
        *,
        config: ElasticMLConfig | None = None,
        enabled: bool | None = None,
        score_threshold: float = 75.0,
        poll_interval_seconds: float = 60.0,
        market_pause_seconds: float = 900.0,
        caution_hold_seconds: float = 1800.0,
        review_hold_seconds: float = 86400.0,
    ) -> None:
        self.config = config or ElasticMLConfig.from_env()
        self.enabled = _env_bool("ELASTIC_ML_ENABLED", False) if enabled is None else bool(enabled)
        self.score_threshold = float(score_threshold)
        self.poll_interval_seconds = float(poll_interval_seconds)
        self.market_pause_seconds = float(market_pause_seconds)
        self.caution_hold_seconds = float(caution_hold_seconds)
        self.review_hold_seconds = float(review_hold_seconds)
        self.initial_lookback = os.getenv("ELASTIC_ML_INITIAL_LOOKBACK", "24h")
        self.search_size = max(25, int(float(os.getenv("ELASTIC_ML_SEARCH_SIZE", "200"))))

        self.client = client or self._build_default_client()
        if self.enabled and self.client is None:
            logger.warning("Elastic ML disabled: no Elasticsearch client available")
            self.enabled = False

        self.last_timestamp = 0
        self._last_poll_monotonic = 0.0
        self._last_warning_ts = 0.0
        self._stop_requested = False

        self._market_controls: dict[str, MarketControl] = {}
        self.position_size_multipliers: dict[str, float] = {}
        self.paused_markets: dict[str, ElasticAnomaly] = {}
        self.flagged_signal_sources: dict[str, ElasticAnomaly] = {}
        self.last_critical_warning: ElasticAnomaly | None = None
        self._review_flags: dict[str, ReviewFlag] = {}

    def _build_default_client(self) -> ElasticRestClient | Any | None:
        if self.config.cluster_url:
            try:
                return self.config.make_client()
            except Exception:
                return None
        getter = getattr(elastic_client, "get_raw_client", None)
        if callable(getter):
            try:
                return getter()
            except Exception:
                return None
        return None

    def _build_query(self) -> dict[str, Any]:
        filters: list[dict[str, Any]] = [
            {
                "terms": {
                    "job_id": [
                        VPIN_ANOMALY_JOB_ID,
                        SPREAD_ANOMALY_JOB_ID,
                        OFI_DIVERGENCE_JOB_ID,
                        SIGNAL_CONFIDENCE_DRIFT_JOB_ID,
                        KILL_RULE_FREQUENCY_JOB_ID,
                    ]
                }
            },
            {"term": {"result_type": "record"}},
            {"term": {"is_interim": False}},
            {"range": {"record_score": {"gte": self.score_threshold}}},
        ]
        if self.last_timestamp > 0:
            filters.append({"range": {"timestamp": {"gt": self.last_timestamp}}})
        else:
            filters.append({"range": {"timestamp": {"gte": f"now-{self.initial_lookback}"}}})
        return {
            "size": self.search_size,
            "sort": [{"timestamp": {"order": "asc"}}, {"record_score": {"order": "desc"}}],
            "_source": [
                "job_id",
                "timestamp",
                "record_score",
                "partition_field_value",
                "by_field_value",
                "over_field_value",
                "actual",
                "typical",
                "field_name",
                "function",
                "description",
            ],
            "query": {"bool": {"filter": filters}},
        }

    def _search_anomalies(self, query: dict[str, Any]) -> dict[str, Any]:
        if self.client is None:
            return {"hits": {"hits": []}}

        if hasattr(self.client, "post"):
            return self.client.post("/.ml-anomalies-*/_search", query)

        if hasattr(self.client, "search"):
            try:
                return self.client.search(index=".ml-anomalies-*", body=query)
            except TypeError:  # pragma: no cover - newer elasticsearch client signature
                return self.client.search(
                    index=".ml-anomalies-*",
                    query=query["query"],
                    sort=query["sort"],
                    size=query["size"],
                    source=query.get("_source"),
                )

        raise RuntimeError("Elastic ML client does not support search or post")

    def _parse_hits(self, response: dict[str, Any]) -> list[ElasticAnomaly]:
        anomalies: list[ElasticAnomaly] = []
        for hit in response.get("hits", {}).get("hits", []):
            source = hit.get("_source", {})
            entity = (
                source.get("partition_field_value")
                or source.get("by_field_value")
                or source.get("over_field_value")
            )
            anomalies.append(
                ElasticAnomaly(
                    job_id=str(source.get("job_id", "")),
                    score=float(source.get("record_score", 0.0) or 0.0),
                    timestamp=int(source.get("timestamp", 0) or 0),
                    entity=str(entity) if entity not in (None, "") else None,
                    actual=tuple(float(value) for value in source.get("actual", []) or []),
                    typical=tuple(float(value) for value in source.get("typical", []) or []),
                    field_name=str(source.get("field_name", "") or ""),
                    function=str(source.get("function", "") or ""),
                    description=str(source.get("description", "") or ""),
                )
            )
        return anomalies

    def poll_once(self) -> list[ElasticAnomaly]:
        if not self.enabled:
            return []

        query = self._build_query()
        try:
            response = self._search_anomalies(query)
        except Exception as exc:
            self._log_warning_once(exc)
            return []

        anomalies = self._parse_hits(response)
        self._prune_state()
        for anomaly in anomalies:
            self.last_timestamp = max(self.last_timestamp, anomaly.timestamp)
            self._apply_anomaly(anomaly)
        return anomalies

    async def poll_if_due(self, *, force: bool = False) -> list[ElasticAnomaly]:
        now = time.monotonic()
        if not force and (now - self._last_poll_monotonic) < self.poll_interval_seconds:
            self._prune_state()
            return []
        self._last_poll_monotonic = now
        return self.poll_once()

    def _apply_anomaly(self, anomaly: ElasticAnomaly) -> None:
        logger.warning("Elastic ML anomaly %s", json.dumps(anomaly.to_log_payload(), sort_keys=True))
        now = time.time()

        if anomaly.category in {"vpin", "ofi"} and anomaly.entity:
            multiplier = max(0.0, 1.0 - (anomaly.score / 100.0))
            control = self._market_controls.setdefault(anomaly.entity, MarketControl(market_id=anomaly.entity))
            control.size_multiplier = min(control.size_multiplier, multiplier)
            control.caution_score = max(control.caution_score, anomaly.score)
            control.caution_jobs.add(anomaly.job_id)
            control.caution_expires_at = max(control.caution_expires_at, now + self.caution_hold_seconds)
            self.position_size_multipliers[anomaly.entity] = control.size_multiplier
            return

        if anomaly.category == "spread" and anomaly.entity:
            control = self._market_controls.setdefault(anomaly.entity, MarketControl(market_id=anomaly.entity))
            control.pause_until = max(control.pause_until, now + self.market_pause_seconds)
            control.pause_reason = f"spread anomaly score {anomaly.score:.1f}"
            control.pause_score = max(control.pause_score, anomaly.score)
            self.paused_markets[anomaly.entity] = anomaly
            return

        if anomaly.category == "confidence" and anomaly.entity:
            message = (
                f"Elastic ML flagged signal source {anomaly.entity} "
                f"for confidence drift (score={anomaly.score:.1f})"
            )
            self.flagged_signal_sources[anomaly.entity] = anomaly
            self._review_flags[anomaly.entity] = ReviewFlag(
                signal_source=anomaly.entity,
                score=anomaly.score,
                message=message,
                expires_at=now + self.review_hold_seconds,
            )
            logger.warning(message)
            return

        if anomaly.category == "kill_frequency":
            self.last_critical_warning = anomaly
            logger.critical("Elastic ML critical %s", json.dumps(anomaly.to_log_payload(), sort_keys=True))

    def _prune_state(self) -> None:
        now = time.time()
        for market_id in list(self._market_controls):
            control = self._market_controls[market_id]
            if control.caution_expires_at <= now:
                control.size_multiplier = 1.0
                control.caution_score = 0.0
                control.caution_jobs.clear()
                self.position_size_multipliers.pop(market_id, None)
            if control.pause_until <= now:
                control.pause_reason = ""
                control.pause_score = 0.0
                self.paused_markets.pop(market_id, None)
            if control.caution_expires_at <= now and control.pause_until <= now:
                self._market_controls.pop(market_id, None)

        for signal_source in list(self._review_flags):
            if self._review_flags[signal_source].expires_at <= now:
                self._review_flags.pop(signal_source, None)
                self.flagged_signal_sources.pop(signal_source, None)

    def _log_warning_once(self, exc: Exception) -> None:
        now = time.time()
        if (now - self._last_warning_ts) < 300:
            return
        self._last_warning_ts = now
        if isinstance(exc, ElasticClientError):
            message = str(exc)
        else:
            message = repr(exc)
        logger.warning("Elastic ML poll failed (non-fatal): %s", message)

    def get_market_feedback(self, market_id: str) -> dict[str, Any]:
        self._prune_state()
        control = self._market_controls.get(str(market_id))
        if control is None:
            return {
                "market_id": str(market_id),
                "size_multiplier": 1.0,
                "score": 0.0,
                "jobs": [],
                "paused": False,
                "pause_reason": "",
            }

        now = time.time()
        paused = control.pause_until > now
        active_caution = control.caution_expires_at > now
        return {
            "market_id": control.market_id,
            "size_multiplier": control.size_multiplier if active_caution else 1.0,
            "score": control.caution_score if active_caution else 0.0,
            "jobs": sorted(control.caution_jobs),
            "paused": paused,
            "pause_reason": control.pause_reason if paused else "",
            "pause_score": control.pause_score if paused else 0.0,
        }

    def snapshot(self) -> dict[str, Any]:
        self._prune_state()
        return {
            "enabled": self.enabled,
            "paused_markets": sorted(self.paused_markets),
            "cautioned_markets": sorted(self.position_size_multipliers),
            "flagged_signal_sources": sorted(self.flagged_signal_sources),
            "last_timestamp": self.last_timestamp,
        }

    def adjust_position_size(self, market_id: str, base_size_usd: float) -> float:
        multiplier = float(self.get_market_feedback(market_id)["size_multiplier"])
        return round(base_size_usd * multiplier, 2)

    def is_market_paused(self, market_id: str) -> bool:
        return bool(self.get_market_feedback(market_id)["paused"])

    def pause_reason(self, market_id: str) -> str:
        return str(self.get_market_feedback(market_id).get("pause_reason", ""))

    def signal_source_flagged(self, signal_source: str) -> bool:
        self._prune_state()
        return signal_source in self.flagged_signal_sources

    async def run_forever(self) -> None:
        self._stop_requested = False
        while not self._stop_requested:
            self.poll_once()
            await asyncio.sleep(self.poll_interval_seconds)

    async def start(self) -> None:
        await self.run_forever()

    def stop(self) -> None:
        self._stop_requested = True


AnomalyConsumer = ElasticAnomalyConsumer
