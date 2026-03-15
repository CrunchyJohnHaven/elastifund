from __future__ import annotations

import json

from hub.elastic.bootstrap import (
    ElasticBootstrapConfig,
    apply_bootstrap,
    build_bootstrap_plan,
    main,
    verify_bootstrap,
)
from hub.elastic.specs import build_nontrading_control_plane_spec


class FakeElasticClient:
    def __init__(self, get_responses: dict[str, object] | None = None) -> None:
        self.get_responses = get_responses or {}
        self.calls: list[tuple[str, str, object | None]] = []

    def get(self, path: str):
        self.calls.append(("GET", path, None))
        if path not in self.get_responses:
            raise RuntimeError("status=404")
        return self.get_responses[path]

    def put(self, path: str, payload):
        self.calls.append(("PUT", path, payload))
        return {"acknowledged": True}


def _config() -> ElasticBootstrapConfig:
    return ElasticBootstrapConfig(
        cluster_url="http://localhost:9200",
        api_key="encoded-token",
        snapshot_repository="elastifund-snapshots",
        vector_dims=768,
        verify_tls=True,
        timeout_seconds=10.0,
    )


def _verification_responses(plan: dict[str, object]) -> dict[str, object]:
    responses: dict[str, object] = {}
    for policy_name in plan["ilm_policies"]:
        responses[f"/_ilm/policy/{policy_name}"] = {policy_name: {"policy": {}}}

    for template_name in plan["index_templates"]:
        responses[f"/_index_template/{template_name}"] = {
            "index_templates": [{"name": template_name, "index_template": {}}]
        }

    for alias_name, alias_spec in plan["aliases"].items():
        index_name = alias_spec["initial_index"]
        responses[f"/{alias_name}/_mapping"] = {
            index_name: {
                "mappings": {
                    "properties": {
                        field_name: field_spec
                        for field_name, field_spec in alias_spec["fields"].items()
                    }
                }
            }
        }
        responses[f"/{alias_name}/_settings"] = {
            index_name: {
                "settings": {
                    "index": {
                        "lifecycle": {"name": alias_spec["expected_policy"]},
                    }
                }
            }
        }

    for data_stream_name, data_stream_spec in plan["data_streams"].items():
        backing_index = f".ds-{data_stream_name}-2026.03.07-000001"
        responses[f"/_data_stream/{data_stream_name}"] = {
            "data_streams": [{"name": data_stream_name}]
        }
        responses[f"/{data_stream_name}/_mapping"] = {
            backing_index: {
                "mappings": {
                    "properties": {
                        field_name: field_spec
                        for field_name, field_spec in data_stream_spec["fields"].items()
                    }
                }
            }
        }
        responses[f"/{data_stream_name}/_settings"] = {
            backing_index: {
                "settings": {
                    "index": {
                        "lifecycle": {"name": data_stream_spec["expected_policy"]},
                        "mode": data_stream_spec["settings"]["mode"],
                        "routing_path": data_stream_spec["settings"]["routing_path"],
                    }
                }
            }
        }
    return responses


def test_build_bootstrap_plan_contains_expected_resources():
    plan = build_bootstrap_plan(_config())

    assert set(plan["ilm_policies"]) == {
        "elastifund-standard-ilm",
        "elastifund-metrics-ilm",
    }
    assert "elastifund-strategies-template" in plan["index_templates"]
    assert "elastifund-metrics-template" in plan["index_templates"]
    assert "elastifund-strategies" in plan["aliases"]
    assert "elastifund-metrics" in plan["data_streams"]
    assert (
        plan["aliases"]["elastifund-strategies"]["fields"]["embedding"]["dims"] == 768
    )
    assert (
        plan["data_streams"]["elastifund-metrics"]["settings"]["routing_path"]
        == ["agent_id", "strategy_id"]
    )


def test_metrics_plan_records_pre_frozen_90_day_downsample_step():
    plan = build_bootstrap_plan(_config())

    schedule = plan["data_streams"]["elastifund-metrics"]["downsample_schedule"]
    assert schedule[0]["target_resolution"] == "1m"
    assert schedule[1]["target_resolution"] == "1h"
    assert schedule[2]["target_resolution"] == "1d"
    assert schedule[2]["mechanism"] == "pre-frozen-maintenance-job"


def test_apply_bootstrap_creates_missing_resources_in_order():
    plan = build_bootstrap_plan(_config())
    client = FakeElasticClient()

    result = apply_bootstrap(client, plan)

    put_paths = [path for method, path, _ in client.calls if method == "PUT"]
    assert put_paths[:2] == [
        "/_ilm/policy/elastifund-standard-ilm",
        "/_ilm/policy/elastifund-metrics-ilm",
    ]
    assert "/elastifund-strategies-000001" in put_paths
    assert "/_data_stream/elastifund-metrics" in put_paths
    assert "elastifund-metrics" in result["data_streams_created"]


def test_verify_bootstrap_checks_expected_field_shapes():
    plan = build_bootstrap_plan(_config())
    client = FakeElasticClient(_verification_responses(plan))

    result = verify_bootstrap(client, plan)

    assert result["ilm_policies"]["elastifund-standard-ilm"] is True
    assert result["index_templates"]["elastifund-strategies-template"] is True
    assert result["aliases"]["elastifund-strategies"]["verified"] is True
    assert result["data_streams"]["elastifund-metrics"]["verified"] is True


def test_plan_command_writes_json_file(tmp_path, capsys):
    output_path = tmp_path / "elastic-bootstrap-plan.json"

    exit_code = main(["plan", "--write-plan", str(output_path)])

    assert exit_code == 0
    saved = json.loads(output_path.read_text())
    assert "ilm_policies" in saved
    stdout = json.loads(capsys.readouterr().out)
    assert stdout["settings"]["vector_dims"] == 768


def test_nontrading_control_plane_spec_lists_required_dashboards_and_alerts():
    spec = build_nontrading_control_plane_spec()

    assert "engine_scoreboard_latest" in spec["documents"]
    assert spec["dashboards"]["checkout_funnel"] == ["execution_event", "cashflow_event"]
    assert spec["alert_thresholds"]["checkout_webhook_failures"]["threshold"] == 1
    assert spec["kill_switches"]["per_engine"]["field"] == "kill_switch_active"
