from __future__ import annotations

import json
from pathlib import Path

from nontrading.models import TelemetryEvent
from nontrading.store import RevenueStore
from nontrading.telemetry import NonTradingTelemetry, TelemetryBridge


def make_bridge(tmp_path: Path) -> TelemetryBridge:
    return TelemetryBridge(output_path=tmp_path / "events.jsonl")


def make_event() -> dict[str, object]:
    return {
        "event_type": "interaction",
        "timestamp": "2026-03-09T00:00:00+00:00",
        "id": "interaction-1",
        "engine": "outreach",
        "status": "queued_review",
    }


def test_format_event_builds_ecs_document(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)

    document = bridge.format_event(make_event())

    assert document["event"]["action"] == "interaction"
    assert document["event"]["dataset"] == "elastifund.nontrading"
    assert document["service"]["type"] == "nontrading"
    assert TelemetryBridge.is_ecs_compatible(document)


def test_emit_writes_jsonl_document(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)

    document = bridge.emit(make_event())

    assert bridge.output_path.exists()
    assert TelemetryBridge.is_ecs_compatible(document)


def test_emit_appends_multiple_documents(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)

    bridge.emit(make_event())
    bridge.emit({**make_event(), "id": "interaction-2"})

    assert len(bridge.read_all()) == 2


def test_read_all_returns_empty_list_when_file_is_missing(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)

    assert bridge.read_all() == []


def test_invalid_document_is_not_ecs_compatible() -> None:
    assert not TelemetryBridge.is_ecs_compatible({"event": {}})


def test_format_event_preserves_original_payload() -> None:
    bridge = TelemetryBridge()

    document = bridge.format_event(make_event())

    assert document["payload"]["engine"] == "outreach"
    assert document["elastifund"]["payload"]["status"] == "queued_review"


def test_store_backed_document_is_ecs_compatible(tmp_path: Path) -> None:
    store = RevenueStore(tmp_path / "revenue_agent.db")
    telemetry = NonTradingTelemetry(store)
    event = TelemetryEvent(
        event_type="account_researched",
        entity_type="account",
        entity_id="account-1",
        payload={"environment": "paper", "system_name": "jj-n", "account_name": "Acme Builders"},
        created_at="2026-03-09T00:00:00+00:00",
    )

    document = telemetry.build_document(event)

    assert TelemetryBridge.is_ecs_compatible(document)
    assert document["event"]["category"] == ["agent"]
    assert document["service"]["name"] == "jj-n"
    assert document["related"]["id"] == ["account-1"]


def test_nontrading_template_matches_bridge_fields() -> None:
    template_path = (
        Path(__file__).resolve().parents[2]
        / "infra"
        / "index_templates"
        / "elastifund-nontrading-events.json"
    )
    template = json.loads(template_path.read_text(encoding="utf-8"))
    bridge = TelemetryBridge()

    document = bridge.format_event(make_event())
    properties = template["template"]["mappings"]["properties"]

    assert template["index_patterns"] == ["elastifund-nontrading-events*"]
    assert properties["payload"]["type"] == "flattened"
    assert properties["elastifund"]["properties"]["payload"]["type"] == "flattened"
    for field_name in ("@timestamp", "ecs", "event", "service", "labels", "elastifund"):
        assert field_name in document
        assert field_name in properties or field_name == "@timestamp"
