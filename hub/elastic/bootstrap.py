"""CLI bootstrap for Elastifund.io Elasticsearch indices and ILM policies."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .client import ElasticRestClient
from .specs import (
    BootstrapNames,
    DEFAULT_METRICS_ILM_POLICY,
    DEFAULT_SNAPSHOT_REPOSITORY,
    DEFAULT_STANDARD_ILM_POLICY,
    DEFAULT_VECTOR_DIMS,
    build_agents_mappings,
    build_initial_alias_index,
    build_knowledge_mappings,
    build_metrics_downsample_schedule,
    build_metrics_ilm_policy,
    build_metrics_template,
    build_rollover_template,
    build_standard_ilm_policy,
    build_strategies_mappings,
    build_trades_mappings,
    initial_index_name,
)


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
class ElasticBootstrapConfig:
    """Runtime config for the Elastic hub bootstrap."""

    cluster_url: str = ""
    api_key: str = ""
    username: str = ""
    password: str = ""
    snapshot_repository: str = DEFAULT_SNAPSHOT_REPOSITORY
    vector_dims: int = DEFAULT_VECTOR_DIMS
    verify_tls: bool = True
    timeout_seconds: float = 30.0

    @classmethod
    def from_env(cls) -> "ElasticBootstrapConfig":
        return cls(
            cluster_url=os.getenv("ELASTICSEARCH_URL", os.getenv("ELASTIC_URL", "")),
            api_key=os.getenv("ELASTIC_API_KEY", ""),
            username=os.getenv("ELASTIC_USERNAME", ""),
            password=os.getenv("ELASTIC_PASSWORD", ""),
            snapshot_repository=os.getenv(
                "ELASTIC_SNAPSHOT_REPOSITORY",
                DEFAULT_SNAPSHOT_REPOSITORY,
            ),
            vector_dims=max(8, _env_int("ELASTIC_VECTOR_DIMS", DEFAULT_VECTOR_DIMS)),
            verify_tls=_env_bool("ELASTIC_VERIFY_TLS", True),
            timeout_seconds=max(1.0, _env_float("ELASTIC_TIMEOUT_SECONDS", 30.0)),
        )

    def make_client(self) -> ElasticRestClient:
        if not self.cluster_url:
            raise ValueError("cluster_url is required for apply/verify operations")
        return ElasticRestClient(
            base_url=self.cluster_url,
            api_key=self.api_key or None,
            username=self.username or None,
            password=self.password or None,
            verify_tls=self.verify_tls,
            timeout_seconds=self.timeout_seconds,
        )


def build_bootstrap_plan(config: ElasticBootstrapConfig) -> dict[str, Any]:
    """Build the full set of ILM, templates, and initial resources."""

    names = BootstrapNames()
    strategy_mappings = build_strategies_mappings(config.vector_dims)
    knowledge_mappings = build_knowledge_mappings(config.vector_dims)
    plan = {
        "settings": {
            "cluster_url": config.cluster_url,
            "snapshot_repository": config.snapshot_repository,
            "vector_dims": config.vector_dims,
        },
        "ilm_policies": {
            DEFAULT_STANDARD_ILM_POLICY: build_standard_ilm_policy(config.snapshot_repository),
            DEFAULT_METRICS_ILM_POLICY: build_metrics_ilm_policy(config.snapshot_repository),
        },
        "index_templates": {
            f"{names.strategies_alias}-template": build_rollover_template(
                alias_name=names.strategies_alias,
                ilm_policy_name=DEFAULT_STANDARD_ILM_POLICY,
                mappings=strategy_mappings,
                priority=500,
            ),
            f"{names.trades_alias}-template": build_rollover_template(
                alias_name=names.trades_alias,
                ilm_policy_name=DEFAULT_STANDARD_ILM_POLICY,
                mappings=build_trades_mappings(),
                priority=490,
            ),
            f"{names.knowledge_alias}-template": build_rollover_template(
                alias_name=names.knowledge_alias,
                ilm_policy_name=DEFAULT_STANDARD_ILM_POLICY,
                mappings=knowledge_mappings,
                priority=480,
            ),
            f"{names.agents_alias}-template": build_rollover_template(
                alias_name=names.agents_alias,
                ilm_policy_name=DEFAULT_STANDARD_ILM_POLICY,
                mappings=build_agents_mappings(),
                priority=470,
            ),
            f"{names.metrics_data_stream}-template": build_metrics_template(
                DEFAULT_METRICS_ILM_POLICY,
                names.metrics_data_stream,
            ),
        },
        "aliases": {
            names.strategies_alias: {
                "initial_index": initial_index_name(names.strategies_alias),
                "create_body": build_initial_alias_index(names.strategies_alias),
                "expected_policy": DEFAULT_STANDARD_ILM_POLICY,
                "fields": {
                    "strategy_id": {"type": "keyword"},
                    "embedding": {
                        "type": "dense_vector",
                        "dims": config.vector_dims,
                    },
                    "verified_return": {"type": "double"},
                },
            },
            names.trades_alias: {
                "initial_index": initial_index_name(names.trades_alias),
                "create_body": build_initial_alias_index(names.trades_alias),
                "expected_policy": DEFAULT_STANDARD_ILM_POLICY,
                "fields": {
                    "trade_id": {"type": "keyword"},
                    "price": {"type": "double"},
                    "realized_pnl_usd": {"type": "double"},
                },
            },
            names.knowledge_alias: {
                "initial_index": initial_index_name(names.knowledge_alias),
                "create_body": build_initial_alias_index(names.knowledge_alias),
                "expected_policy": DEFAULT_STANDARD_ILM_POLICY,
                "fields": {
                    "knowledge_id": {"type": "keyword"},
                    "embedding": {
                        "type": "dense_vector",
                        "dims": config.vector_dims,
                    },
                    "confidence": {"type": "double"},
                },
            },
            names.agents_alias: {
                "initial_index": initial_index_name(names.agents_alias),
                "create_body": build_initial_alias_index(names.agents_alias),
                "expected_policy": DEFAULT_STANDARD_ILM_POLICY,
                "fields": {
                    "agent_id": {"type": "keyword"},
                    "agent_type": {"type": "keyword"},
                    "heartbeat_at": {"type": "date"},
                },
            },
        },
        "data_streams": {
            names.metrics_data_stream: {
                "expected_policy": DEFAULT_METRICS_ILM_POLICY,
                "fields": {
                    "@timestamp": {"type": "date"},
                    "agent_id": {
                        "type": "keyword",
                        "time_series_dimension": True,
                    },
                    "strategy_id": {
                        "type": "keyword",
                        "time_series_dimension": True,
                    },
                    "pnl_usd": {
                        "type": "double",
                        "time_series_metric": "gauge",
                    },
                    "drawdown_pct": {
                        "type": "double",
                        "time_series_metric": "gauge",
                    },
                    "revenue_usd": {
                        "type": "double",
                        "time_series_metric": "gauge",
                    },
                },
                "settings": {
                    "mode": "time_series",
                    "routing_path": ["agent_id", "strategy_id"],
                },
                "downsample_schedule": build_metrics_downsample_schedule(
                    names.metrics_data_stream
                ),
            }
        },
    }
    return plan


def apply_bootstrap(client: ElasticRestClient, plan: dict[str, Any]) -> dict[str, Any]:
    """Create policies, templates, rollover aliases, and the metrics data stream."""

    applied = {
        "ilm_policies": [],
        "index_templates": [],
        "indices_created": [],
        "data_streams_created": [],
    }
    for policy_name, policy in plan["ilm_policies"].items():
        client.put(f"/_ilm/policy/{policy_name}", policy)
        applied["ilm_policies"].append(policy_name)

    for template_name, template in plan["index_templates"].items():
        client.put(f"/_index_template/{template_name}", template)
        applied["index_templates"].append(template_name)

    for alias_name, alias_spec in plan["aliases"].items():
        index_name = alias_spec["initial_index"]
        if not _resource_exists(client, f"/{index_name}"):
            client.put(f"/{index_name}", alias_spec["create_body"])
            applied["indices_created"].append(index_name)
        else:
            applied["indices_created"].append(f"{index_name} (existing)")

    for data_stream_name in plan["data_streams"]:
        if not _resource_exists(client, f"/_data_stream/{data_stream_name}"):
            client.put(f"/_data_stream/{data_stream_name}", {})
            applied["data_streams_created"].append(data_stream_name)
        else:
            applied["data_streams_created"].append(f"{data_stream_name} (existing)")

    return applied


def verify_bootstrap(client: ElasticRestClient, plan: dict[str, Any]) -> dict[str, Any]:
    """Verify mappings and lifecycle settings for all configured resources."""

    verification = {
        "ilm_policies": {},
        "index_templates": {},
        "aliases": {},
        "data_streams": {},
    }
    for policy_name in plan["ilm_policies"]:
        payload = client.get(f"/_ilm/policy/{policy_name}")
        verification["ilm_policies"][policy_name] = policy_name in payload

    for template_name in plan["index_templates"]:
        payload = client.get(f"/_index_template/{template_name}")
        names = [item["name"] for item in payload.get("index_templates", [])]
        verification["index_templates"][template_name] = template_name in names

    for alias_name, alias_spec in plan["aliases"].items():
        mapping = client.get(f"/{alias_name}/_mapping")
        settings = client.get(f"/{alias_name}/_settings")
        index_name, properties = _first_mapping_properties(mapping)
        lifecycle_name = (
            settings.get(index_name, {})
            .get("settings", {})
            .get("index", {})
            .get("lifecycle", {})
            .get("name")
        )
        field_checks = _verify_fields(properties, alias_spec["fields"])
        verification["aliases"][alias_name] = {
            "index_name": index_name,
            "policy": lifecycle_name == alias_spec["expected_policy"],
            "fields": field_checks,
            "verified": lifecycle_name == alias_spec["expected_policy"] and all(field_checks.values()),
        }

    for data_stream_name, data_stream_spec in plan["data_streams"].items():
        stream_payload = client.get(f"/_data_stream/{data_stream_name}")
        stream_names = [item["name"] for item in stream_payload.get("data_streams", [])]
        mapping = client.get(f"/{data_stream_name}/_mapping")
        settings = client.get(f"/{data_stream_name}/_settings")
        index_name, properties = _first_mapping_properties(mapping)
        index_settings = settings.get(index_name, {}).get("settings", {}).get("index", {})
        lifecycle_name = index_settings.get("lifecycle", {}).get("name")
        mode = index_settings.get("mode")
        routing_path = _normalize_routing_path(index_settings.get("routing_path", []))
        field_checks = _verify_fields(properties, data_stream_spec["fields"])
        verification["data_streams"][data_stream_name] = {
            "exists": data_stream_name in stream_names,
            "policy": lifecycle_name == data_stream_spec["expected_policy"],
            "mode": mode == data_stream_spec["settings"]["mode"],
            "routing_path": routing_path == data_stream_spec["settings"]["routing_path"],
            "fields": field_checks,
            "verified": (
                data_stream_name in stream_names
                and lifecycle_name == data_stream_spec["expected_policy"]
                and mode == data_stream_spec["settings"]["mode"]
                and routing_path == data_stream_spec["settings"]["routing_path"]
                and all(field_checks.values())
            ),
        }
    return verification


def _first_mapping_properties(mapping_payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    index_name = next(iter(mapping_payload))
    properties = mapping_payload[index_name]["mappings"]["properties"]
    return index_name, properties


def _verify_fields(
    properties: dict[str, Any],
    expected_fields: dict[str, dict[str, Any]],
) -> dict[str, bool]:
    results: dict[str, bool] = {}
    for field_name, expected in expected_fields.items():
        actual = properties.get(field_name, {})
        result = actual.get("type") == expected["type"]
        if "dims" in expected:
            result = result and actual.get("dims") == expected["dims"]
        if "time_series_dimension" in expected:
            result = result and actual.get("time_series_dimension") == expected["time_series_dimension"]
        if "time_series_metric" in expected:
            result = result and actual.get("time_series_metric") == expected["time_series_metric"]
        results[field_name] = bool(result)
    return results


def _resource_exists(client: ElasticRestClient, path: str) -> bool:
    try:
        client.get(path)
        return True
    except Exception as exc:  # pragma: no cover - exact exception type depends on the transport
        if "status=404" in str(exc):
            return False
        raise


def _normalize_routing_path(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        return [item for item in value.split(",") if item]
    return []


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bootstrap Elastifund.io Elasticsearch policies, templates, and indices."
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="plan",
        choices=("plan", "apply", "verify"),
        help="Print the plan, apply it to Elasticsearch, or verify an existing cluster.",
    )
    parser.add_argument("--cluster-url", help="Override ELASTICSEARCH_URL / ELASTIC_URL.")
    parser.add_argument("--api-key", help="Override ELASTIC_API_KEY.")
    parser.add_argument("--username", help="Override ELASTIC_USERNAME.")
    parser.add_argument("--password", help="Override ELASTIC_PASSWORD.")
    parser.add_argument(
        "--snapshot-repository",
        help="Override ELASTIC_SNAPSHOT_REPOSITORY.",
    )
    parser.add_argument(
        "--vector-dims",
        type=int,
        help="Override ELASTIC_VECTOR_DIMS.",
    )
    parser.add_argument(
        "--write-plan",
        help="Optional path to write the generated bootstrap plan JSON.",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Disable TLS certificate verification for local clusters.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        help="Override ELASTIC_TIMEOUT_SECONDS.",
    )
    return parser.parse_args(argv)


def _apply_overrides(
    config: ElasticBootstrapConfig,
    args: argparse.Namespace,
) -> ElasticBootstrapConfig:
    return ElasticBootstrapConfig(
        cluster_url=args.cluster_url or config.cluster_url,
        api_key=args.api_key or config.api_key,
        username=args.username or config.username,
        password=args.password or config.password,
        snapshot_repository=args.snapshot_repository or config.snapshot_repository,
        vector_dims=max(8, args.vector_dims or config.vector_dims),
        verify_tls=False if args.insecure else config.verify_tls,
        timeout_seconds=max(
            1.0,
            args.timeout_seconds if args.timeout_seconds is not None else config.timeout_seconds,
        ),
    )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    config = _apply_overrides(ElasticBootstrapConfig.from_env(), args)
    plan = build_bootstrap_plan(config)

    if args.write_plan:
        output_path = Path(args.write_plan)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(plan, indent=2, sort_keys=True))

    if args.command == "plan":
        print(json.dumps(plan, indent=2, sort_keys=True))
        return 0

    client = config.make_client()
    if args.command == "apply":
        applied = apply_bootstrap(client, plan)
        verified = verify_bootstrap(client, plan)
        print(json.dumps({"applied": applied, "verified": verified}, indent=2, sort_keys=True))
        return 0

    verified = verify_bootstrap(client, plan)
    print(json.dumps({"verified": verified}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
