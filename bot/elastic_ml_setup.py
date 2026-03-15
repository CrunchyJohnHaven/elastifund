#!/usr/bin/env python3
"""Elastic ML bootstrap helpers for Elastifund anomaly jobs."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass, field
from typing import Any, Iterable

from hub.elastic.client import ElasticClientError, ElasticRestClient

VPIN_ANOMALY_JOB_ID = "elastifund-vpin-anomaly"
SPREAD_ANOMALY_JOB_ID = "elastifund-spread-anomaly"
OFI_DIVERGENCE_JOB_ID = "elastifund-ofi-divergence"
SIGNAL_CONFIDENCE_DRIFT_JOB_ID = "elastifund-signal-confidence-drift"
KILL_RULE_FREQUENCY_JOB_ID = "elastifund-kill-rule-frequency"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return bool(default)
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return float(default)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return float(default)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return int(default)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return int(default)


@dataclass(frozen=True)
class MLDetectorSpec:
    """Declarative detector config for an Elastic anomaly job."""

    function: str
    field_name: str | None = None
    partition_field_name: str | None = None
    by_field_name: str | None = None
    description: str = ""

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"function": self.function}
        if self.field_name:
            payload["field_name"] = self.field_name
        if self.partition_field_name:
            payload["partition_field_name"] = self.partition_field_name
        if self.by_field_name:
            payload["by_field_name"] = self.by_field_name
        if self.description:
            payload["detector_description"] = self.description
        return payload


@dataclass(frozen=True)
class ElasticMLJobSpec:
    """Specification for one anomaly job and its datafeed."""

    job_id: str
    description: str
    purpose: str
    indices: tuple[str, ...]
    bucket_span: str
    detectors: tuple[MLDetectorSpec, ...]
    query: dict[str, Any] = field(default_factory=lambda: {"match_all": {}})
    influencers: tuple[str, ...] = ()
    time_field: str = "timestamp"
    query_delay: str = "60s"
    frequency: str | None = None
    model_memory_limit: str = "64mb"
    scroll_size: int = 1000

    @property
    def datafeed_id(self) -> str:
        return f"datafeed-{self.job_id}"

    def job_payload(self) -> dict[str, Any]:
        influencer_fields = list(self.influencers)
        for detector in self.detectors:
            for field_name in (detector.partition_field_name, detector.by_field_name):
                if field_name and field_name not in influencer_fields:
                    influencer_fields.append(field_name)

        return {
            "description": self.description,
            "analysis_config": {
                "bucket_span": self.bucket_span,
                "detectors": [detector.to_payload() for detector in self.detectors],
                "influencers": influencer_fields,
            },
            "analysis_limits": {"model_memory_limit": self.model_memory_limit},
            "data_description": {"time_field": self.time_field},
            "custom_settings": {
                "managed_by": "bot.elastic_ml_setup",
                "purpose": self.purpose,
            },
        }

    def datafeed_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "job_id": self.job_id,
            "indices": list(self.indices),
            "query": self.query,
            "query_delay": self.query_delay,
            "scroll_size": self.scroll_size,
        }
        if self.frequency:
            payload["frequency"] = self.frequency
        return payload

    def to_plan_entry(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "datafeed_id": self.datafeed_id,
            "description": self.description,
            "purpose": self.purpose,
            "indices": list(self.indices),
            "bucket_span": self.bucket_span,
            "detectors": [detector.to_payload() for detector in self.detectors],
        }


@dataclass(frozen=True)
class ElasticMLConfig:
    """Runtime config for Elastic ML bootstrap and status commands."""

    cluster_url: str = ""
    api_key: str = ""
    username: str = ""
    password: str = ""
    verify_tls: bool = True
    timeout_seconds: float = 30.0
    start_time: str = "now-7d"
    summary_lookback: str = "24h"
    summary_min_score: float = 50.0
    summary_size: int = 20

    @classmethod
    def from_env(cls) -> "ElasticMLConfig":
        return cls(
            cluster_url=os.getenv("ELASTICSEARCH_URL", os.getenv("ELASTIC_URL", "")),
            api_key=os.getenv("ELASTIC_API_KEY", ""),
            username=os.getenv("ELASTIC_USERNAME", ""),
            password=os.getenv("ELASTIC_PASSWORD", ""),
            verify_tls=_env_bool("ELASTIC_VERIFY_TLS", True),
            timeout_seconds=max(1.0, _env_float("ELASTIC_TIMEOUT_SECONDS", 30.0)),
            start_time=os.getenv("ELASTIC_ML_START_TIME", "now-7d"),
            summary_lookback=os.getenv("ELASTIC_ML_SUMMARY_LOOKBACK", "24h"),
            summary_min_score=max(0.0, _env_float("ELASTIC_ML_SUMMARY_MIN_SCORE", 50.0)),
            summary_size=max(1, _env_int("ELASTIC_ML_SUMMARY_SIZE", 20)),
        )

    def make_client(self) -> ElasticRestClient:
        if not self.cluster_url:
            raise ValueError("ELASTICSEARCH_URL or ELASTIC_URL is required")
        return ElasticRestClient(
            base_url=self.cluster_url,
            api_key=self.api_key or None,
            username=self.username or None,
            password=self.password or None,
            verify_tls=self.verify_tls,
            timeout_seconds=self.timeout_seconds,
        )


def build_default_job_specs() -> list[ElasticMLJobSpec]:
    """Return the anomaly jobs used by the trading bot."""

    return [
        ElasticMLJobSpec(
            job_id=VPIN_ANOMALY_JOB_ID,
            description="VPIN spikes on elastifund-orderbook partitioned by market_id.",
            purpose="Detect sudden VPIN spikes that indicate informed trading or toxic flow.",
            indices=("elastifund-orderbook",),
            bucket_span="5m",
            detectors=(
                MLDetectorSpec(
                    function="high_mean",
                    field_name="vpin",
                    partition_field_name="market_id",
                    description="High mean VPIN by market_id",
                ),
            ),
            influencers=("market_id",),
        ),
        ElasticMLJobSpec(
            job_id=SPREAD_ANOMALY_JOB_ID,
            description="Spread blowouts on elastifund-orderbook partitioned by market_id.",
            purpose="Detect liquidity crises before they hit execution quality.",
            indices=("elastifund-orderbook",),
            bucket_span="5m",
            detectors=(
                MLDetectorSpec(
                    function="high_mean",
                    field_name="spread_bps",
                    partition_field_name="market_id",
                    description="High mean spread_bps by market_id",
                ),
            ),
            influencers=("market_id",),
        ),
        ElasticMLJobSpec(
            job_id=OFI_DIVERGENCE_JOB_ID,
            description="Order-flow imbalance divergence on elastifund-orderbook.",
            purpose="Detect one-sided order flow that often precedes large price moves.",
            indices=("elastifund-orderbook",),
            bucket_span="5m",
            detectors=(
                MLDetectorSpec(
                    function="high_mean",
                    field_name="ofi",
                    partition_field_name="market_id",
                    description="High mean OFI by market_id",
                ),
                MLDetectorSpec(
                    function="low_mean",
                    field_name="ofi",
                    partition_field_name="market_id",
                    description="Low mean OFI by market_id",
                ),
            ),
            influencers=("market_id",),
        ),
        ElasticMLJobSpec(
            job_id=SIGNAL_CONFIDENCE_DRIFT_JOB_ID,
            description="Signal confidence drift on elastifund-signals partitioned by signal_source.",
            purpose="Detect when a signal source starts degrading in live conditions.",
            indices=("elastifund-signals",),
            bucket_span="1h",
            detectors=(
                MLDetectorSpec(
                    function="low_mean",
                    field_name="confidence",
                    partition_field_name="signal_source",
                    description="Low mean confidence by signal_source",
                ),
            ),
            influencers=("signal_source",),
        ),
        ElasticMLJobSpec(
            job_id=KILL_RULE_FREQUENCY_JOB_ID,
            description="Kill-rule event-rate spikes on elastifund-kills.",
            purpose="Detect abnormal kill-rule firing frequency that signals system stress.",
            indices=("elastifund-kills",),
            bucket_span="1h",
            detectors=(
                MLDetectorSpec(
                    function="high_count",
                    partition_field_name="kill_rule",
                    description="High kill-rule count by kill_rule",
                ),
            ),
            influencers=("kill_rule",),
        ),
    ]


def build_jobs() -> list[ElasticMLJobSpec]:
    """Compatibility alias for older bootstrap code."""
    return build_default_job_specs()


def _exists(client: ElasticRestClient, path: str) -> bool:
    try:
        client.get(path)
        return True
    except ElasticClientError as exc:
        if "status=404" in str(exc):
            return False
        raise


def _conflict_is_safe(exc: ElasticClientError, *needles: str) -> bool:
    message = str(exc)
    return "status=409" in message and any(needle in message for needle in needles)


def build_plan(job_specs: Iterable[ElasticMLJobSpec]) -> dict[str, Any]:
    return {"jobs": [spec.to_plan_entry() for spec in job_specs]}


def ensure_jobs(client: ElasticRestClient, job_specs: Iterable[ElasticMLJobSpec]) -> dict[str, list[str]]:
    """Create all jobs and datafeeds if they do not already exist."""

    result = {
        "jobs_created": [],
        "jobs_existing": [],
        "datafeeds_created": [],
        "datafeeds_existing": [],
    }

    for spec in job_specs:
        if _exists(client, f"/_ml/anomaly_detectors/{spec.job_id}"):
            result["jobs_existing"].append(spec.job_id)
        else:
            client.put(f"/_ml/anomaly_detectors/{spec.job_id}", spec.job_payload())
            result["jobs_created"].append(spec.job_id)

        if _exists(client, f"/_ml/datafeeds/{spec.datafeed_id}"):
            result["datafeeds_existing"].append(spec.datafeed_id)
        else:
            client.put(f"/_ml/datafeeds/{spec.datafeed_id}", spec.datafeed_payload())
            result["datafeeds_created"].append(spec.datafeed_id)

    return result


def open_and_start_jobs(
    client: ElasticRestClient,
    job_specs: Iterable[ElasticMLJobSpec],
    *,
    start_time: str,
) -> dict[str, list[str]]:
    """Open jobs and start their datafeeds."""

    result = {
        "jobs_opened": [],
        "jobs_already_open": [],
        "datafeeds_started": [],
        "datafeeds_already_started": [],
    }

    for spec in job_specs:
        try:
            client.post(f"/_ml/anomaly_detectors/{spec.job_id}/_open")
            result["jobs_opened"].append(spec.job_id)
        except ElasticClientError as exc:
            if _conflict_is_safe(exc, "job_already_open_exception", "already open"):
                result["jobs_already_open"].append(spec.job_id)
            else:
                raise

        try:
            client.post(
                f"/_ml/datafeeds/{spec.datafeed_id}/_start",
                {"start": start_time},
            )
            result["datafeeds_started"].append(spec.datafeed_id)
        except ElasticClientError as exc:
            if _conflict_is_safe(exc, "already started", "cannot start datafeed"):
                result["datafeeds_already_started"].append(spec.datafeed_id)
            else:
                raise

    return result


def collect_job_status(
    client: ElasticRestClient,
    job_specs: Iterable[ElasticMLJobSpec],
) -> dict[str, dict[str, Any]]:
    """Return job and datafeed state for every managed job."""

    status: dict[str, dict[str, Any]] = {}
    for spec in job_specs:
        entry: dict[str, Any] = {
            "job_id": spec.job_id,
            "datafeed_id": spec.datafeed_id,
            "exists": False,
        }
        try:
            job_stats = client.get(f"/_ml/anomaly_detectors/{spec.job_id}/_stats")
            datafeed_stats = client.get(f"/_ml/datafeeds/{spec.datafeed_id}/_stats")
        except ElasticClientError as exc:
            if "status=404" in str(exc):
                status[spec.job_id] = entry
                continue
            raise

        job_info = (job_stats.get("jobs") or [{}])[0]
        datafeed_info = (datafeed_stats.get("datafeeds") or [{}])[0]
        entry.update(
            {
                "exists": True,
                "job_state": job_info.get("state", "unknown"),
                "data_counts": job_info.get("data_counts", {}),
                "model_bytes": job_info.get("model_size_stats", {}).get("model_bytes", 0),
                "datafeed_state": datafeed_info.get("state", "unknown"),
                "node": datafeed_info.get("node", {}),
            }
        )
        status[spec.job_id] = entry

    return status


def fetch_anomaly_summaries(
    client: ElasticRestClient,
    job_specs: Iterable[ElasticMLJobSpec],
    *,
    lookback: str,
    min_score: float,
    size: int,
) -> list[dict[str, Any]]:
    """Fetch top anomaly records across the managed jobs."""

    job_ids = [spec.job_id for spec in job_specs]
    response = client.post(
        "/.ml-anomalies-*/_search",
        {
            "size": size,
            "sort": [{"record_score": "desc"}, {"timestamp": "desc"}],
            "_source": [
                "job_id",
                "timestamp",
                "record_score",
                "bucket_span",
                "function",
                "field_name",
                "partition_field_name",
                "partition_field_value",
                "actual",
                "typical",
                "description",
            ],
            "query": {
                "bool": {
                    "filter": [
                        {"terms": {"job_id": job_ids}},
                        {"term": {"result_type": "record"}},
                        {"term": {"is_interim": False}},
                        {"range": {"timestamp": {"gte": f"now-{lookback}"}}},
                        {"range": {"record_score": {"gte": min_score}}},
                    ]
                }
            },
        },
    )

    summaries: list[dict[str, Any]] = []
    for hit in response.get("hits", {}).get("hits", []):
        source = hit.get("_source", {})
        summaries.append(
            {
                "job_id": source.get("job_id", ""),
                "timestamp": source.get("timestamp"),
                "record_score": source.get("record_score", 0.0),
                "partition_field_name": source.get("partition_field_name"),
                "partition_field_value": source.get("partition_field_value"),
                "field_name": source.get("field_name"),
                "function": source.get("function"),
                "actual": source.get("actual", []),
                "typical": source.get("typical", []),
                "description": source.get("description", ""),
            }
        )
    return summaries


def setup_all(client: ElasticRestClient, config: ElasticMLConfig) -> dict[str, Any]:
    """Create, open, and start the full ML job suite."""

    job_specs = build_default_job_specs()
    created = ensure_jobs(client, job_specs)
    started = open_and_start_jobs(client, job_specs, start_time=config.start_time)
    status = collect_job_status(client, job_specs)
    return {
        "created": created,
        "started": started,
        "status": status,
    }


class ElasticMLManager:
    """Compatibility wrapper around the newer helper functions."""

    def __init__(
        self,
        client: ElasticRestClient | None = None,
        *,
        config: ElasticMLConfig | None = None,
    ) -> None:
        self.config = config or ElasticMLConfig.from_env()
        self.client = client or self.config.make_client()

    def available(self) -> bool:
        return self.client is not None

    def create_all(self) -> dict[str, bool]:
        result = setup_all(self.client, self.config)
        created_jobs = set(result["created"]["jobs_created"]) | set(result["created"]["jobs_existing"])
        return {spec.job_id: spec.job_id in created_jobs for spec in build_default_job_specs()}

    def job_status(self) -> dict[str, Any]:
        return collect_job_status(self.client, build_default_job_specs())

    def anomaly_summaries(self, min_score: int = 75) -> list[dict[str, Any]]:
        return fetch_anomaly_summaries(
            self.client,
            build_default_job_specs(),
            lookback=self.config.summary_lookback,
            min_score=float(min_score),
            size=self.config.summary_size,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Manage Elastic anomaly-detection jobs for Elastifund."
    )
    subparsers = parser.add_subparsers(dest="command", required=False)

    subparsers.add_parser("plan", help="Print the managed ML job plan.")
    subparsers.add_parser("setup", help="Create, open, and start all jobs.")
    subparsers.add_parser("create", help="Compatibility alias for setup.")
    subparsers.add_parser("status", help="Print job and datafeed state.")

    summaries_parser = subparsers.add_parser(
        "summaries",
        help="Print recent anomaly summaries from .ml-anomalies-*.",
    )
    summaries_parser.add_argument("--lookback", default=None)
    summaries_parser.add_argument("--min-score", type=float, default=None)
    summaries_parser.add_argument("--size", type=int, default=None)

    summary_alias_parser = subparsers.add_parser(
        "summary",
        help="Compatibility alias for summaries.",
    )
    summary_alias_parser.add_argument("--lookback", default=None)
    summary_alias_parser.add_argument("--min-score", type=float, default=None)
    summary_alias_parser.add_argument("--size", type=int, default=None)

    args = parser.parse_args(argv)
    config = ElasticMLConfig.from_env()
    command = args.command or "setup"

    if command == "plan":
        print(json.dumps(build_plan(build_default_job_specs()), indent=2, sort_keys=True))
        return 0

    client = config.make_client()

    if command in {"setup", "create"}:
        print(json.dumps(setup_all(client, config), indent=2, sort_keys=True))
        return 0

    if command == "status":
        print(
            json.dumps(
                collect_job_status(client, build_default_job_specs()),
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if command in {"summaries", "summary"}:
        lookback = getattr(args, "lookback", None) or config.summary_lookback
        min_score = (
            getattr(args, "min_score", None)
            if getattr(args, "min_score", None) is not None
            else config.summary_min_score
        )
        size = getattr(args, "size", None) or config.summary_size
        print(
            json.dumps(
                fetch_anomaly_summaries(
                    client,
                    build_default_job_specs(),
                    lookback=lookback,
                    min_score=float(min_score),
                    size=int(size),
                ),
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    parser.error(f"unsupported command: {command}")
    return 2


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
