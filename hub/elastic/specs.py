"""Elasticsearch specs for the Elastifund.io hub."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DEFAULT_VECTOR_DIMS = 768
DEFAULT_SNAPSHOT_REPOSITORY = "elastifund-snapshots"
DEFAULT_STANDARD_ILM_POLICY = "elastifund-standard-ilm"
DEFAULT_METRICS_ILM_POLICY = "elastifund-metrics-ilm"
DEFAULT_CHECKOUT_WEBHOOK_FAILURE_THRESHOLD = 1
DEFAULT_FULFILLMENT_STALL_MINUTES = 120
DEFAULT_REFUND_RATE_ALERT_THRESHOLD = 0.05
DEFAULT_COMPLAINT_RATE_ALERT_THRESHOLD = 0.001
DEFAULT_MISSING_WORKER_ACTIVITY_MINUTES = 60
DEFAULT_NEGATIVE_ROI_THRESHOLD = 0.0


@dataclass(frozen=True)
class BootstrapNames:
    """Canonical alias and data-stream names used by the hub."""

    strategies_alias: str = "elastifund-strategies"
    metrics_data_stream: str = "elastifund-metrics"
    trades_alias: str = "elastifund-trades"
    knowledge_alias: str = "elastifund-knowledge"
    agents_alias: str = "elastifund-agents"


def build_standard_ilm_policy(snapshot_repository: str) -> dict[str, Any]:
    """ILM for strategy, trade, knowledge, and registry indices."""

    searchable_snapshot = {
        "snapshot_repository": snapshot_repository,
        "force_merge_index": False,
        "total_shards_per_node": 1,
    }
    return {
        "policy": {
            "phases": {
                "hot": {
                    "actions": {
                        "set_priority": {"priority": 100},
                        "rollover": {
                            "max_age": "7d",
                            "max_primary_shard_size": "50gb",
                        },
                    }
                },
                "warm": {
                    "min_age": "7d",
                    "actions": {
                        "set_priority": {"priority": 50},
                        "readonly": {},
                        "forcemerge": {"max_num_segments": 1},
                    },
                },
                "cold": {
                    "min_age": "30d",
                    "actions": {
                        "set_priority": {"priority": 25},
                        "readonly": {},
                        "searchable_snapshot": searchable_snapshot,
                    },
                },
                "frozen": {
                    "min_age": "90d",
                    "actions": {
                        "searchable_snapshot": searchable_snapshot,
                    },
                },
                "delete": {
                    "min_age": "365d",
                    "actions": {
                        "delete": {"delete_searchable_snapshot": False},
                    },
                },
            }
        }
    }


def build_metrics_ilm_policy(snapshot_repository: str) -> dict[str, Any]:
    """ILM for the TSDS metrics stream.

    The 90-day 1d downsample step is emitted separately in the maintenance
    manifest because Elasticsearch only supports downsample through the cold
    phase, while the frozen phase supports searchable snapshots instead.
    """

    searchable_snapshot = {
        "snapshot_repository": snapshot_repository,
        "force_merge_index": False,
        "total_shards_per_node": 1,
    }
    return {
        "policy": {
            "phases": {
                "hot": {
                    "actions": {
                        "set_priority": {"priority": 100},
                        "rollover": {
                            "max_age": "1d",
                            "max_primary_shard_size": "50gb",
                        },
                    }
                },
                "warm": {
                    "min_age": "7d",
                    "actions": {
                        "set_priority": {"priority": 50},
                        "readonly": {},
                        "downsample": {"fixed_interval": "1m"},
                        "forcemerge": {"max_num_segments": 1},
                    },
                },
                "cold": {
                    "min_age": "30d",
                    "actions": {
                        "set_priority": {"priority": 25},
                        "readonly": {},
                        "downsample": {"fixed_interval": "1h"},
                        "searchable_snapshot": searchable_snapshot,
                    },
                },
                "frozen": {
                    "min_age": "90d",
                    "actions": {
                        "searchable_snapshot": searchable_snapshot,
                    },
                },
                "delete": {
                    "min_age": "365d",
                    "actions": {
                        "delete": {"delete_searchable_snapshot": False},
                    },
                },
            }
        }
    }


def build_strategies_mappings(vector_dims: int) -> dict[str, Any]:
    return {
        "dynamic": True,
        "properties": {
            "strategy_id": {"type": "keyword"},
            "agent_id": {"type": "keyword"},
            "strategy_type": {"type": "keyword"},
            "lane": {"type": "keyword"},
            "privacy_tier": {"type": "keyword"},
            "status": {"type": "keyword"},
            "title": {"type": "text"},
            "summary": {"type": "text"},
            "tags": {"type": "keyword"},
            "stake_weight": {"type": "double"},
            "verified_return": {"type": "double"},
            "monthly_revenue_usd": {"type": "double"},
            "sharpe_ratio": {"type": "double"},
            "max_drawdown_pct": {"type": "double"},
            "embedding": {
                "type": "dense_vector",
                "dims": vector_dims,
                "index": True,
                "similarity": "cosine",
            },
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
            "metadata": {"type": "object", "enabled": False},
        },
    }


def build_trades_mappings() -> dict[str, Any]:
    return {
        "dynamic": True,
        "properties": {
            "trade_id": {"type": "keyword"},
            "agent_id": {"type": "keyword"},
            "strategy_id": {"type": "keyword"},
            "venue": {"type": "keyword"},
            "market_id": {"type": "keyword"},
            "event_id": {"type": "keyword"},
            "side": {"type": "keyword"},
            "order_type": {"type": "keyword"},
            "status": {"type": "keyword"},
            "price": {"type": "double"},
            "size": {"type": "double"},
            "notional_usd": {"type": "double"},
            "fee_usd": {"type": "double"},
            "realized_pnl_usd": {"type": "double"},
            "unrealized_pnl_usd": {"type": "double"},
            "executed_at": {"type": "date"},
            "recorded_at": {"type": "date"},
            "metadata": {"type": "object", "enabled": False},
        },
    }


def build_knowledge_mappings(vector_dims: int) -> dict[str, Any]:
    return {
        "dynamic": True,
        "properties": {
            "knowledge_id": {"type": "keyword"},
            "source_agent_id": {"type": "keyword"},
            "knowledge_type": {"type": "keyword"},
            "privacy_tier": {"type": "keyword"},
            "confidence": {"type": "double"},
            "title": {"type": "text"},
            "summary": {"type": "text"},
            "signal_direction": {"type": "keyword"},
            "tags": {"type": "keyword"},
            "embedding": {
                "type": "dense_vector",
                "dims": vector_dims,
                "index": True,
                "similarity": "cosine",
            },
            "created_at": {"type": "date"},
            "metadata": {"type": "object", "enabled": False},
        },
    }


def build_agents_mappings() -> dict[str, Any]:
    return {
        "dynamic": True,
        "properties": {
            "agent_id": {"type": "keyword"},
            "agent_type": {"type": "keyword"},
            "status": {"type": "keyword"},
            "runtime": {"type": "keyword"},
            "stake_weight": {"type": "double"},
            "verified_return": {"type": "double"},
            "capabilities": {"type": "keyword"},
            "heartbeat_at": {"type": "date"},
            "registered_at": {"type": "date"},
            "last_model_sync_at": {"type": "date"},
            "metadata": {"type": "object", "enabled": False},
        },
    }


def build_metrics_template(policy_name: str, data_stream_name: str) -> dict[str, Any]:
    return {
        "index_patterns": [f"{data_stream_name}*"],
        "priority": 600,
        "data_stream": {},
        "template": {
            "settings": {
                "index.lifecycle.name": policy_name,
                "index.mode": "time_series",
                "index.routing_path": ["agent_id", "strategy_id"],
                "number_of_shards": 1,
                "number_of_replicas": 1,
                "codec": "best_compression",
            },
            "mappings": {
                "dynamic": True,
                "properties": {
                    "@timestamp": {"type": "date"},
                    "agent_id": {"type": "keyword", "time_series_dimension": True},
                    "strategy_id": {"type": "keyword", "time_series_dimension": True},
                    "agent_type": {"type": "keyword", "time_series_dimension": True},
                    "venue": {"type": "keyword", "time_series_dimension": True},
                    "pnl_usd": {"type": "double", "time_series_metric": "gauge"},
                    "drawdown_pct": {"type": "double", "time_series_metric": "gauge"},
                    "revenue_usd": {"type": "double", "time_series_metric": "gauge"},
                    "sharpe_ratio": {"type": "double", "time_series_metric": "gauge"},
                    "cost_usd": {"type": "double", "time_series_metric": "gauge"},
                },
            },
        },
    }


def build_rollover_template(
    *,
    alias_name: str,
    ilm_policy_name: str,
    mappings: dict[str, Any],
    priority: int,
) -> dict[str, Any]:
    return {
        "index_patterns": [f"{alias_name}-*"],
        "priority": priority,
        "template": {
            "settings": {
                "index.lifecycle.name": ilm_policy_name,
                "index.lifecycle.rollover_alias": alias_name,
                "number_of_shards": 1,
                "number_of_replicas": 1,
                "codec": "best_compression",
            },
            "mappings": mappings,
        },
    }


def build_initial_alias_index(alias_name: str) -> dict[str, Any]:
    return {
        "aliases": {
            alias_name: {
                "is_write_index": True,
            }
        }
    }


def initial_index_name(alias_name: str) -> str:
    return f"{alias_name}-000001"


def build_metrics_downsample_schedule(data_stream_name: str) -> list[dict[str, str]]:
    """Planned metric rollups, including the 90-day pre-frozen maintenance step."""

    return [
        {
            "source": data_stream_name,
            "source_resolution": "10s",
            "target_resolution": "1m",
            "trigger_age": "7d",
            "mechanism": "ilm-warm-phase",
        },
        {
            "source": data_stream_name,
            "source_resolution": "1m",
            "target_resolution": "1h",
            "trigger_age": "30d",
            "mechanism": "ilm-cold-phase",
        },
        {
            "source": data_stream_name,
            "source_resolution": "1h",
            "target_resolution": "1d",
            "trigger_age": "90d",
            "mechanism": "pre-frozen-maintenance-job",
            "note": (
                "Frozen phase supports searchable snapshots but not downsample; "
                "schedule this before the frozen cutover."
            ),
        },
    ]


def build_nontrading_control_plane_spec() -> dict[str, Any]:
    """Shared schema and threshold contract for non-trading control-plane ops."""

    return {
        "documents": {
            "engine_scoreboard_latest": {
                "dimensions": ["engine_name", "engine_family", "run_mode", "status"],
                "metrics": [
                    "opportunities_discovered",
                    "opportunities_scored",
                    "qualified_prospects",
                    "checkout_sessions_created",
                    "payments_collected",
                    "refund_rate",
                    "net_roi_30d",
                    "knowledge_packs_published",
                    "last_heartbeat_at",
                    "kill_switch_active",
                ],
            },
            "prospect_profile_latest": {
                "dimensions": ["prospect_id", "engine_name", "segment", "source"],
                "metrics": ["site_quality_score", "qualification_score", "qualified", "last_scored_at"],
            },
            "campaign_rollup_daily": {
                "dimensions": ["engine_name", "channel", "status", "follow_up_enabled"],
                "metrics": ["messages_sent", "complaints", "unsubscribes", "bounce_rate"],
            },
        },
        "dashboards": {
            "engine_performance": ["engine_scoreboard_latest"],
            "prospect_pipeline": ["prospect_profile_latest"],
            "checkout_funnel": ["execution_event", "cashflow_event"],
            "fulfillment_status": ["execution_event", "outcome_event"],
            "refunds_and_churn": ["cashflow_event", "outcome_event"],
            "allocator_decisions": ["allocator_snapshot"],
            "knowledge_pack_activity": ["knowledge_pack", "leaderboard_daily"],
        },
        "alert_thresholds": {
            "checkout_webhook_failures": {
                "document": "execution_event",
                "field": "webhook_failures",
                "threshold": DEFAULT_CHECKOUT_WEBHOOK_FAILURE_THRESHOLD,
                "operator": ">=",
            },
            "fulfillment_stalls": {
                "document": "execution_event",
                "field": "oldest_inflight_age_minutes",
                "threshold": DEFAULT_FULFILLMENT_STALL_MINUTES,
                "operator": ">=",
            },
            "refund_spikes": {
                "document": "cashflow_event",
                "field": "refund_rate",
                "threshold": DEFAULT_REFUND_RATE_ALERT_THRESHOLD,
                "operator": ">=",
            },
            "complaint_spikes": {
                "document": "campaign_rollup_daily",
                "field": "complaint_rate",
                "threshold": DEFAULT_COMPLAINT_RATE_ALERT_THRESHOLD,
                "operator": ">=",
            },
            "missing_worker_activity": {
                "document": "engine_scoreboard_latest",
                "field": "heartbeat_age_minutes",
                "threshold": DEFAULT_MISSING_WORKER_ACTIVITY_MINUTES,
                "operator": ">=",
            },
            "negative_roi_regimes": {
                "document": "engine_scoreboard_latest",
                "field": "net_roi_30d",
                "threshold": DEFAULT_NEGATIVE_ROI_THRESHOLD,
                "operator": "<",
            },
        },
        "kill_switches": {
            "global_non_trading": {
                "scope": "agent_state",
                "field": "global_kill_switch",
            },
            "per_engine": {
                "scope": "engine_scoreboard_latest",
                "field": "kill_switch_active",
            },
        },
    }
